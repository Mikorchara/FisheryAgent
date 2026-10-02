"""R2: private temporary .env only, fictional values, all sockets blocked."""

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import logging
import os
import socket
import unittest

from fishery_ai import secure_files
from fishery_ai.credentials import CredentialStore
from fishery_ai.project_env import EnvWriteError, ProjectEnvWriter, edit_env
from fishery_ai.providers import AuthSpec
from fishery_ai.model_gateway import ModelResponse, ProfileRegistry
from fishery_ai.web import _builtin_profiles, create_app


REF = "DASHSCOPE_API_KEY"
FAKE_A = "fictional-r2-secret-A"
FAKE_B = "fictional-r2-secret-B"
PROFILE = "qwen-plus-experimental"


class R2Fixture(unittest.TestCase):
    private_storage = False

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        secure_files.private_directory(self.root)
        self.source_root = self.root
        self.location = None
        if self.private_storage:
            from fishery_ai.credential_paths import private_project_location
            self.source_root = self.root / "source"
            secure_files.private_directory(self.source_root)
            with patch("fishery_ai.credential_paths.Path.home", return_value=self.root):
                self.location = private_project_location(self.source_root,
                    {"LOCALAPPDATA": str(self.root)})
            self.location.check(create=True)
            self.root = self.location.env_path.parent
        self.env = self.root / ".env"
        self.process = {}
        self.store = CredentialStore(self.env, self.process, private_location=self.location)
        self.writer = ProjectEnvWriter(self.root, self.store, require_git_ignored=False)
        for obj, names in ((socket.socket, ("connect", "connect_ex", "sendto")),
                           (socket, ("getaddrinfo", "create_connection"))):
            for name in names:
                guard = patch.object(obj, name, side_effect=AssertionError("R2 is offline"))
                guard.start()
                self.addCleanup(guard.stop)
        for method in ("read_text", "read_bytes", "write_text", "write_bytes"):
            original = getattr(Path, method)
            def guarded(path, *args, _original=original, **kwargs):
                if path.name == ".env" and not path.absolute().is_relative_to(Path(self.temp.name)):
                    raise AssertionError("R2 must not touch the real .env")
                return _original(path, *args, **kwargs)
            guard = patch.object(Path, method, guarded)
            guard.start()
            self.addCleanup(guard.stop)

    def seed(self, body=None):
        raw = body if body is not None else f"{REF}='{FAKE_A}'\n".encode()
        if self.env.exists():
            self.env.write_bytes(raw)
        else:
            secure_files.write_private(self.env, raw)

    def revision(self):
        return self.writer.inspect(REF, AuthSpec.REQUIRED_BEARER)["revision"]

    def change(self, action, value=None, revision=None):
        return self.writer.mutate(REF, AuthSpec.REQUIRED_BEARER, action=action,
            expected_revision=revision or self.revision(), secret=value)

    def assert_code(self, code, callback):
        with self.assertRaises(EnvWriteError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)
        self.assertNotIn(FAKE_A, str(raised.exception))
        self.assertNotIn(FAKE_B, str(raised.exception))


class EnvWriterTests(R2Fixture):
    def test_create_replace_remove_and_missing_status(self):
        self.change("create", FAKE_A)
        self.assertEqual(self.store.resolve(REF)._for_adapter(), FAKE_A)
        self.change("replace", FAKE_B)
        self.assertEqual(self.store.resolve(REF)._for_adapter(), FAKE_B)
        self.change("remove")
        self.assertEqual(self.store.status(REF).availability, "MISSING")
        self.assertEqual(list(self.root.glob(".env.stage-*")), [])

    def test_snapshot_hot_reload_keeps_old_request(self):
        self.change("create", FAKE_A)
        profile = next(p for p in _builtin_profiles() if p.profile_id == PROFILE)
        old = ProfileRegistry([profile], self.store).snapshot(PROFILE)
        self.change("replace", FAKE_B)
        new = ProfileRegistry([profile], self.store).snapshot(PROFILE)
        self.assertEqual((old.api_key, new.api_key), (FAKE_A, FAKE_B))
        self.assertNotEqual(old.credential.revision, new.credential.revision)
        self.assertNotIn(FAKE_A, repr(old))
        self.assertNotIn(FAKE_B, repr(new))

    def test_same_value_replace_also_rotates_opaque_generation(self):
        self.change("create", FAKE_A)
        old = self.store.resolve(REF).revision
        self.change("replace", FAKE_A)
        self.assertNotEqual(old, self.store.resolve(REF).revision)
        self.assertNotIn(FAKE_A, self.revision())

    def test_stale_revision_and_external_edit_conflict(self):
        self.seed()
        old = self.revision()
        self.env.write_bytes(self.env.read_bytes() + b"# external\n")
        original = self.env.read_bytes()
        self.assert_code("ENV_REVISION_CONFLICT", lambda: self.change("replace", FAKE_B, old))
        self.assertEqual(self.env.read_bytes(), original)

    def test_missing_created_externally_conflicts(self):
        old = self.revision()
        self.seed()
        self.assert_code("ENV_REVISION_CONFLICT", lambda: self.change("create", FAKE_B, old))

    def test_process_present_and_empty_are_readonly_without_file_read(self):
        for value in (FAKE_A, ""):
            self.process[REF] = value
            with patch.object(self.writer, "_policy", side_effect=AssertionError("no file inspection")):
                self.assert_code("PROCESS_ENV_READ_ONLY", lambda: self.change("create", FAKE_B, "unused"))

    def test_auth_none_does_not_read_file_or_environment(self):
        with patch.object(self.writer, "_policy", side_effect=AssertionError("no inspection")):
            self.assert_code("AUTH_NONE", lambda: self.writer.mutate(None, AuthSpec.NONE,
                action="create", expected_revision="unused", secret=FAKE_A))

    def test_format_preserves_bom_crlf_comments_unknown_order(self):
        original = ("\ufeff# 中文注释\r\nUNKNOWN='opaque ${HOME}'\r\nexport " + REF
                    + " = \"old\"  # 保留注释\r\nMULTI='line1\r\nline2'\r\nLAST=value").encode("utf-8")
        self.seed(original)
        self.change("replace", FAKE_B)
        expected = original.replace(b'"old"', ("'" + FAKE_B + "'").encode())
        self.assertEqual(self.env.read_bytes(), expected)
        self.change("remove")
        removed = self.env.read_bytes()
        self.assertIn("# 保留注释\r\n".encode(), removed)
        self.assertTrue(removed.startswith(b"\xef\xbb\xbf"))
        self.assertTrue(removed.endswith(b"LAST=value"))
        self.assertNotIn(REF.encode(), removed)

    def test_lf_and_mixed_existing_newlines_preserved(self):
        for body in (b"# note\n", b"# note\r\nOTHER=v\n"):
            self.seed(body)
            self.change("create", FAKE_A)
            self.assertTrue(self.env.read_bytes().startswith(body))
            self.change("remove")
            self.assertEqual(self.env.read_bytes(), body)

    def test_special_quote_backslash_dollar_hash_roundtrip(self):
        value = "fake'\\${HOME}#abc"
        self.change("create", value)
        self.assertEqual(self.store.resolve(REF)._for_adapter(), value)

    def test_duplicate_multiline_invalid_encoding_fail_closed(self):
        cases = [(f"{REF}=a\n{REF}=b\n".encode(), "ENV_DUPLICATE_KEY"),
                 (f"{REF}='a\nb'\n".encode(), "ENV_FORMAT_UNSUPPORTED"),
                 (b"\xff", "ENV_FORMAT_UNSUPPORTED")]
        for body, code in cases:
            self.seed(body)
            # Opaque revision can be read internally before the unsupported text edit.
            revision = self.writer._state()[3]
            self.assert_code(code, lambda: self.change("replace", FAKE_B, revision))
            self.assertEqual(self.env.read_bytes(), body)

    def test_invalid_secret_and_key_are_rejected(self):
        for value in ("", "fake\nINJECT=1", "fake\x00", "x" * 4097):
            self.assert_code("INVALID_CREDENTIAL_VALUE", lambda: self.change("create", value))
        self.assert_code("INVALID_SECRET_ENV", lambda: self.writer.inspect("../escape", AuthSpec.REQUIRED_BEARER))
        self.assertFalse(self.env.exists())

    def test_create_existing_replace_missing_and_remove_missing(self):
        self.assert_code("CREDENTIAL_NOT_FOUND", lambda: self.change("remove"))
        self.assert_code("CREDENTIAL_NOT_FOUND", lambda: self.change("replace", FAKE_B))
        self.change("create", FAKE_A)
        self.assert_code("CREDENTIAL_EXISTS", lambda: self.change("create", FAKE_B))

    def test_staging_write_failure_leaves_original_complete(self):
        self.seed()
        original = self.env.read_bytes()
        with patch.object(secure_files, "write_private", side_effect=OSError(FAKE_B)):
            self.assert_code("ENV_WRITE_FAILED", lambda: self.change("replace", FAKE_B))
        self.assertEqual(self.env.read_bytes(), original)

    def test_atomic_replace_failure_leaves_original_complete(self):
        self.seed()
        original = self.env.read_bytes()
        with patch.object(secure_files, "atomic_replace", side_effect=OSError(FAKE_B)):
            self.assert_code("ENV_WRITE_FAILED", lambda: self.change("replace", FAKE_B))
        self.assertEqual(self.env.read_bytes(), original)

    def test_error_after_rename_rolls_back_original(self):
        self.seed()
        original = self.env.read_bytes()
        real = secure_files.atomic_replace
        calls = []
        def failure_after_rename(source, target):
            real(source, target)
            calls.append(source)
            if len(calls) == 1:
                raise OSError(FAKE_B)
        with patch.object(secure_files, "atomic_replace", side_effect=failure_after_rename):
            self.assert_code("ENV_WRITE_FAILED", lambda: self.change("replace", FAKE_B))
        self.assertEqual(self.env.read_bytes(), original)
        self.assertEqual(len(calls), 2)

    def test_failed_rollback_retains_private_recovery_and_safe_error(self):
        self.seed()
        real = secure_files.atomic_replace
        count = 0
        def fail_both(source, target):
            nonlocal count
            count += 1
            if count == 1:
                real(source, target)
            raise OSError(FAKE_B)
        with patch.object(secure_files, "atomic_replace", side_effect=fail_both):
            self.assert_code("ENV_RECOVERY_REQUIRED", lambda: self.change("replace", FAKE_B))
        retained = list(self.root.glob(".env.stage-*/original"))
        self.assertEqual(len(retained), 1)
        secure_files.inspect_policy(retained[0])
        secure_files.inspect_policy(retained[0].parent, directory=True)

    def test_revision_recheck_before_commit_prevents_external_overwrite(self):
        self.seed()
        real = secure_files.write_private
        def concurrent_edit(path, body, policy=None):
            real(path, body, policy)
            if path.name == "original":
                self.env.write_bytes(b"# outside edit\n")
        with patch.object(secure_files, "write_private", side_effect=concurrent_edit):
            self.assert_code("ENV_REVISION_CONFLICT", lambda: self.change("replace", FAKE_B))
        self.assertEqual(self.env.read_bytes(), b"# outside edit\n")

    def test_security_failure_and_unignored_path_fail_closed(self):
        with patch.object(secure_files, "inspect_policy", side_effect=secure_files.SecureFileError()):
            self.assert_code("ENV_PERMISSION_ERROR", lambda: self.change("create", FAKE_A))
        self.writer.require_git_ignored = True
        self.assert_code("ENV_NOT_IGNORED", lambda: self.change("create", FAKE_A))
        self.assertFalse(self.env.exists())

    def test_hardlink_is_rejected(self):
        self.seed()
        os.link(self.env, self.root / "linked")
        self.assert_code("ENV_PERMISSION_ERROR", lambda: self.writer.inspect(REF, AuthSpec.REQUIRED_BEARER))

    def test_private_acl_or_mode_preserved_on_replace(self):
        self.seed()
        policy = secure_files.inspect_policy(self.env)
        self.change("replace", FAKE_B)
        self.assertEqual(secure_files.inspect_policy(self.env), policy)

    def test_cooperating_writers_cannot_enter_same_lock(self):
        with secure_files.exclusive_lock(self.root / ".env.writer.lock"):
            self.assert_code("ENV_LOCK_UNAVAILABLE", lambda: self.change("create", FAKE_A))
        self.assertFalse(self.env.exists())

    def test_actual_staging_paths_must_be_git_ignored(self):
        self.writer.require_git_ignored = True
        checked = []
        def policy(paths):
            checked.extend(paths)
            if any(".env.stage-" in path for path in paths):
                raise EnvWriteError("ENV_NOT_IGNORED")
        with patch.object(self.writer, "_check_ignored", side_effect=policy):
            self.assert_code("ENV_NOT_IGNORED", lambda: self.change("create", FAKE_A))
        self.assertTrue(any(path.endswith("/new") for path in checked))
        self.assertFalse(self.env.exists())

    def test_git_ignored_but_tracked_file_is_rejected(self):
        self.writer.require_git_ignored = True
        def result(command, **_kwargs):
            return type("Result", (), {"returncode": 0})()
        with patch("fishery_ai.project_env.subprocess.run", side_effect=result):
            self.assert_code("ENV_NOT_IGNORED", lambda: self.change("create", FAKE_A))

    def test_empty_assignment_inline_comment_survives_replacement(self):
        self.seed(f"{REF}= # retain comment\nUNKNOWN=v\n".encode())
        self.change("replace", FAKE_B)
        self.assertIn(b"# retain comment\nUNKNOWN=v\n", self.env.read_bytes())
        self.assertEqual(self.store.resolve(REF)._for_adapter(), FAKE_B)

    def test_failed_creation_after_rename_restores_absence(self):
        real = secure_files.atomic_replace
        def fail_after(source, target):
            real(source, target)
            raise OSError("fictional failure")
        with patch.object(secure_files, "atomic_replace", side_effect=fail_after):
            self.assert_code("ENV_WRITE_FAILED", lambda: self.change("create", FAKE_A))
        self.assertFalse(self.env.exists())


class CredentialWebTests(R2Fixture):
    def setUp(self):
        super().setUp()
        self.app = create_app(credential_store=self.store, credential_writer=self.writer,
            custom_profiles_dir=self.root / "profiles", capability_evidence_dir=self.root / "evidence",
            trace_path=self.root / "trace.jsonl", real_gateway_factory=lambda: self.gateway)
        self.client = self.app.test_client()
        self.headers = {"Origin": "http://localhost", "X-CSRF-Token":
                        self.client.get("/api/credential-session").get_json()["csrf_token"]}

    def status(self, profile=PROFILE):
        return self.client.post("/api/credentials/status", json={"profile_id": profile}).get_json()

    def api_change(self, action, value=None, revision=None, **extra):
        payload = {"profile_id": PROFILE, "revision": revision or self.status()["revision"], **extra}
        if value is not None:
            payload["secret"] = value
        return getattr(self.client, {"create": "post", "replace": "put", "remove": "delete"}[action])(
            "/api/credentials", json=payload, headers=self.headers)

    def fields(self):
        return {"display_name": "R2 custom", "service_id": "dashscope", "model_family": "qwen",
            "adapter_id": "openai_chat", "base_url": "https://example.invalid/v1",
            "model": "fake-model", "secret_env": REF, "provider_kind": "cloud",
            "auth_spec": "REQUIRED_BEARER"}

    def test_web_crud_safe_json_and_hot_reload(self):
        for action, value, expected in (("create", FAKE_A, "PRESENT"), ("replace", FAKE_B, "PRESENT"),
                                        ("remove", None, "MISSING")):
            response = self.api_change(action, value)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["availability"], expected)
            for fake in (FAKE_A, FAKE_B):
                self.assertNotIn(fake, response.get_data(as_text=True))
                self.assertNotIn(fake, repr(self.store.resolve(REF)))
            self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))
        self.assertEqual(self.status()["source"], "MISSING")

    def test_stale_revision_returns_conflict_without_echoing_input(self):
        old = self.status()["revision"]
        self.api_change("create", FAKE_A)
        response = self.api_change("replace", FAKE_B, old)
        self.assertEqual((response.status_code, response.get_json()["error_code"]), (409, "ENV_REVISION_CONFLICT"))
        self.assertEqual(self.store.resolve(REF)._for_adapter(), FAKE_A)
        self.assertNotIn(FAKE_B, response.get_data(as_text=True))

    def test_process_env_and_auth_none_are_readonly(self):
        for value in (FAKE_A, ""):
            self.process[REF] = value
            state = self.status()
            self.assertEqual((state["source"], state["editable"]), ("PROCESS_ENV", False))
            self.assertEqual(self.api_change("create", FAKE_B, "unused").get_json()["error_code"], "PROCESS_ENV_READ_ONLY")
        with patch.object(self.store, "_project_values", side_effect=AssertionError("NONE never reads file")):
            state = self.status("ollama-qwen35-4b-local")
            self.assertEqual(state["availability"], "NONE_REQUIRED")
            response = self.client.post("/api/credentials", json=dict(profile_id="ollama-qwen35-4b-local",
                revision="unused", secret=FAKE_A), headers=self.headers)
            self.assertEqual(response.get_json()["error_code"], "AUTH_NONE")

    def test_host_origin_csrf_and_session_binding(self):
        data = dict(profile_id=PROFILE, revision="unused", secret=FAKE_A)
        cases = [({}, "ORIGIN_NOT_ALLOWED"), ({"Origin": "http://evil.invalid"}, "ORIGIN_NOT_ALLOWED"),
                 ({"Origin": "http://localhost"}, "CSRF_INVALID"),
                 ({**self.headers, "Host": "evil.invalid"}, "HOST_NOT_ALLOWED"),
                 ({**self.headers, "Sec-Fetch-Site": "cross-site"}, "ORIGIN_NOT_ALLOWED"),
                 ({**self.headers, "X-CSRF-Token": "non-ascii-凭据"}, "CSRF_INVALID")]
        for headers, code in cases:
            response = self.client.post("/api/credentials", json=data, headers=headers)
            self.assertEqual(response.get_json()["error_code"], code)
        other = self.app.test_client()
        self.assertEqual(other.post("/api/credentials", json=data, headers=self.headers).get_json()["error_code"], "CSRF_INVALID")
        self.assertFalse(self.env.exists())
        cookie = self.app.test_client().get("/api/credential-session").headers.get("Set-Cookie", "")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)

    def test_foreign_host_cannot_read_config_or_csrf(self):
        for url in ("/", "/api/config", "/api/credential-session"):
            self.assertEqual(self.client.get(url, headers={"Host": "evil.invalid"}).get_json()["error_code"], "HOST_NOT_ALLOWED")

    def test_web_has_no_path_override_or_arbitrary_auth_override(self):
        for field in ("path", "file_path", "auth_spec", "secret_env"):
            response = self.api_change("create", FAKE_A, **{field: "unauthorized"})
            self.assertEqual(response.get_json()["error_code"], "INVALID_REQUEST")
        self.assertFalse(self.env.exists())

    def test_new_profile_draft_can_set_credential_before_connection_test(self):
        context = {"draft": self.fields()}
        state = self.client.post("/api/credentials/status", json=context).get_json()
        response = self.client.post("/api/credentials", json={**context, "revision": state["revision"],
            "secret": FAKE_A}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.store.resolve(REF)._for_adapter(), FAKE_A)
        self.assertEqual(list((self.root / "profiles").glob("*.json")), [])

    def test_connection_authorization_invalidated_on_rotation_and_evidence_untouched(self):
        self.seed()
        self.gateway = type("Gateway", (), {"list_models": lambda _s, *_a, **_k: [{"id": "fake-model"}]})()
        evidence = self.root / "evidence" / "preserve.json"
        evidence.parent.mkdir(exist_ok=True)
        evidence.write_text('{"fixture":"preserve"}', encoding="utf-8")
        result = self.client.post("/api/profiles/test", json={**self.fields(), "method": "models", "confirm_network": True}).get_json()
        self.assertEqual(result["status"], "success")
        self.api_change("replace", FAKE_B)
        saved = self.client.post("/api/profiles", json={**self.fields(), "test_id": result["test_id"]})
        self.assertEqual(saved.get_json()["error_code"], "CONNECTION_TEST_REQUIRED")
        self.assertEqual(evidence.read_text(), '{"fixture":"preserve"}')

    def test_late_test_and_model_list_results_after_rotation_are_rejected(self):
        self.seed()
        owner = self
        class Gateway:
            def list_models(self, *_a, **_k):
                owner.change("replace", FAKE_B)
                return [{"id": "fake-model"}]
        self.gateway = Gateway()
        for url, extra in (("/api/profiles/test", {"method": "models"}), ("/api/profiles/models", {})):
            self.seed()
            response = self.client.post(url, json={**self.fields(), **extra, "confirm_network": True})
            self.assertEqual((response.status_code, response.get_json()["error_code"]), (409, "CREDENTIAL_CHANGED"))

    def test_web_safe_write_failure_does_not_leak_or_log_secret(self):
        self.seed()
        with patch.object(secure_files, "atomic_replace", side_effect=OSError(FAKE_B)), self.assertNoLogs(level=logging.WARNING):
            response = self.api_change("replace", FAKE_B)
        self.assertEqual(response.get_json()["error_code"], "ENV_WRITE_FAILED")
        self.assertNotIn(FAKE_B, response.get_data(as_text=True))
        self.assertEqual(self.store.resolve(REF)._for_adapter(), FAKE_A)

    def test_rotation_during_analysis_keeps_inflight_snapshot_and_trace_redacted(self):
        self.seed()
        seen = []
        owner = self
        class Gateway:
            def complete(self, _request, runtime):
                owner.change("replace", FAKE_B)
                seen.append(runtime.api_key)
                return ModelResponse('{"inference":"fixture","recommendations":[],"uncertainty":[]}')
        self.gateway = Gateway()
        response = self.client.post("/api/analyze", json=dict(profile_id=PROFILE,
            scenario="low_oxygen", question="fixture", confirm_network=True))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen, [FAKE_A])
        self.assertEqual(self.store.resolve(REF)._for_adapter(), FAKE_B)
        for fake in (FAKE_A, FAKE_B):
            self.assertNotIn(fake, response.get_data(as_text=True))
            self.assertNotIn(fake, (self.root / "trace.jsonl").read_text(encoding="utf-8"))

    def test_request_limit_non_json_and_loopback_policy(self):
        response = self.client.post("/api/credentials", data="bad form", headers=self.headers)
        self.assertEqual(response.get_json()["error_code"], "INVALID_REQUEST")
        response = self.client.post("/api/credentials", json={"secret": "fictional" * 4000}, headers=self.headers)
        self.assertEqual((response.status_code, response.get_json()["error_code"]), (413, "REQUEST_TOO_LARGE"))
        response = self.client.get("/api/credential-session", environ_overrides={"REMOTE_ADDR": "192.0.2.1"})
        self.assertEqual(response.get_json()["error_code"], "LOCAL_ACCESS_REQUIRED")
        self.assertFalse(self.env.exists())

    def test_runtime_defaults_persist_byte_for_byte_after_rotation(self):
        self.seed()
        self.gateway = type("Gateway", (), {"list_models": lambda _s, *_a, **_k: [{"id": "fake-model"}]})()
        fields = {**self.fields(), "default_thinking_mode": "off", "default_response_mode": "streaming"}
        token = self.client.post("/api/profiles/test", json={**fields, "method": "models", "confirm_network": True}).get_json()["test_id"]
        response = self.client.post("/api/profiles", json={**fields, "test_id": token})
        self.assertEqual(response.status_code, 201)
        saved = next((self.root / "profiles").glob("*.json"))
        before = saved.read_bytes()
        self.api_change("replace", FAKE_B)
        self.assertEqual(saved.read_bytes(), before)
        self.assertNotIn(FAKE_A.encode(), before)
        self.assertNotIn(FAKE_B.encode(), before)

    def test_stale_profile_credential_ref_cannot_write_another_variable(self):
        self.seed()
        self.gateway = type("Gateway", (), {"list_models": lambda _s, *_a, **_k: [{"id": "fake-model"}]})()
        fields = {**self.fields(), "provider_kind": "local"}
        created = self.client.post("/api/profiles", json=fields).get_json()["profile"]
        identifier = created["profile_id"]
        old = self.status(identifier)["revision"]
        changed = {**fields, "secret_env": "OTHER_FAKE_KEY"}
        response = self.client.put(f"/api/profiles/{identifier}", json=changed)
        self.assertEqual(response.status_code, 200)
        response = self.client.put("/api/credentials", json=dict(profile_id=identifier,
            revision=old, secret=FAKE_B), headers=self.headers)
        self.assertEqual(response.get_json()["error_code"], "ENV_REVISION_CONFLICT")
        self.assertEqual(self.store.resolve(REF)._for_adapter(), FAKE_A)
        self.assertEqual(self.store.resolve("OTHER_FAKE_KEY").status.availability, "MISSING")


if __name__ == "__main__":
    unittest.main()


# Explicit historical fixtures; not active startup assets.
from historical_model_fixtures import install as _install_history
_install_history(globals())
