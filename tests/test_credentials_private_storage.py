"""Private migration tests: temporary ACL-protected roots and fictional secrets only."""

from pathlib import Path
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from unittest.mock import patch
import os
import importlib.util

from fishery_ai import secure_files
from fishery_ai.credential_paths import CredentialLocationError, private_project_location
from fishery_ai.credentials import CredentialFileError, CredentialStore
from fishery_ai.project_env import ProjectEnvWriter
from fishery_ai.providers import AuthSpec
from fishery_ai.web import MOCK_PROFILE_ID
import test_credential_writer as r2
from test_credential_writer import R2Fixture, FAKE_A, FAKE_B, REF


class _ReachedValidationBoundary(Exception):
    """Stop before any model call; only credential composition is under test."""




class PrivateStorageTests(R2Fixture):
    private_storage = True

    def test_location_is_stable_normalized_project_specific_and_has_no_side_effect(self):
        with patch("fishery_ai.credential_paths.Path.home", return_value=self.location.base):
            first = private_project_location(self.source_root, {"LOCALAPPDATA": str(self.location.base)})
            normalized = private_project_location(self.source_root / ".", {"LOCALAPPDATA": str(self.location.base)})
            other = private_project_location(self.source_root / "other", {"LOCALAPPDATA": str(self.location.base)})
        self.assertEqual(first, normalized)
        self.assertNotEqual(first.env_path, other.env_path)
        self.assertEqual(first.env_path.relative_to(first.base).parts[0], "Fishery_AI_Prototype")
        self.assertEqual(first.env_path.name, ".env")
        self.assertFalse(other.env_path.parent.exists())
        if os.name == "nt":
            with patch("fishery_ai.credential_paths.os.environ", {"LOCALAPPDATA": str(self.location.base)}):
                upper = private_project_location(Path(str(self.source_root).upper()))
            self.assertEqual(first.env_path.name, upper.env_path.name)
            self.assertEqual(first.env_path.parent.parent.name, upper.env_path.parent.parent.name)

    def test_missing_or_relative_localappdata_fails_closed(self):
        if os.name != "nt":
            self.skipTest("Windows location policy")
        for environment in ({}, {"LOCALAPPDATA": "relative-path"}):
            with self.assertRaises(CredentialLocationError) as raised:
                private_project_location(self.source_root, environment)
            self.assertEqual(str(raised.exception), "CREDENTIAL_STORAGE_UNAVAILABLE")

    def test_first_read_and_status_do_not_create_storage_or_read_legacy_env(self):
        with patch("fishery_ai.credential_paths.Path.home", return_value=self.location.base):
            fresh = private_project_location(self.source_root / "fresh", {"LOCALAPPDATA": str(self.location.base)})
        store = CredentialStore(fresh.env_path, {}, private_location=fresh)
        writer = ProjectEnvWriter(fresh.env_path.parent, store, require_git_ignored=False)
        legacy = self.source_root / ".env"
        legacy.write_text(f"{REF}={FAKE_A}\n", encoding="utf-8")
        original = legacy.read_bytes()
        with patch.object(Path, "read_text", side_effect=AssertionError("no fallback read")):
            self.assertEqual(store.status(REF).availability, "MISSING")
            self.assertFalse(writer.inspect(REF, AuthSpec.REQUIRED_BEARER)["exists"])
        self.assertFalse(fresh.env_path.parent.exists())
        revision = writer.inspect(REF, AuthSpec.REQUIRED_BEARER)["revision"]
        writer.mutate(REF, AuthSpec.REQUIRED_BEARER, action="create", expected_revision=revision, secret=FAKE_B)
        self.assertTrue(store.resolve(REF)._for_adapter() == FAKE_B)
        self.assertTrue(legacy.read_bytes() == original)

    def test_create_replace_remove_hot_reload_old_snapshot_and_generation(self):
        self.change("create", FAKE_A)
        first = self.store.resolve(REF)
        self.change("replace", FAKE_B)
        second = self.store.resolve(REF)
        self.assertTrue(first._for_adapter() == FAKE_A)
        self.assertTrue(second._for_adapter() == FAKE_B)
        self.assertNotEqual(first.revision, second.revision)
        self.env.write_text(f"{REF}='{FAKE_A}'\n", encoding="utf-8")
        self.assertTrue(self.store.resolve(REF)._for_adapter() == FAKE_A)
        self.assertEqual(second.status.source, "PROJECT_ENV")
        self.change("remove")
        self.assertEqual(self.store.status(REF).availability, "MISSING")

    def test_process_environment_priority_and_none_do_not_inspect_storage(self):
        for value in (FAKE_A, ""):
            self.process[REF] = value
            with patch.object(type(self.location), "check", side_effect=AssertionError("no disk access")):
                result = self.store.resolve(REF)
                self.assertEqual(result.status.source, "PROCESS_ENV")
                self.assertFalse(result.status.editable)
                self.assertEqual(self.store.status(REF, AuthSpec.NONE).source, "NONE_REQUIRED")
        self.assert_code("PROCESS_ENV_READ_ONLY", lambda: self.change("create", FAKE_A, revision="fake"))

    def test_unsafe_acl_blocks_reads_and_writes_without_inspecting_secret(self):
        self.seed()
        with patch.object(secure_files, "inspect_policy", side_effect=secure_files.SecureFileError()), \
                patch.object(Path, "read_text", side_effect=AssertionError("unsafe file must not be read")):
            with self.assertRaises(CredentialFileError):
                self.store.resolve(REF)
            self.assert_code("ENV_PERMISSION_ERROR", lambda: self.change("replace", FAKE_B, revision="fake"))

    def test_base_acl_is_checked_even_when_credential_directories_are_missing(self):
        with patch("fishery_ai.credential_paths.Path.home", return_value=self.location.base):
            missing = private_project_location(self.source_root / "missing", {"LOCALAPPDATA": str(self.location.base)})
        with patch.object(secure_files, "inspect_policy", side_effect=secure_files.SecureFileError()):
            with self.assertRaises(secure_files.SecureFileError):
                missing.check()

    def test_external_mode_cannot_bypass_git_checks_by_pointing_inside_source_tree(self):
        with patch("fishery_ai.credential_paths.Path.home", return_value=self.source_root):
            with self.assertRaises(CredentialLocationError):
                private_project_location(self.source_root, {"LOCALAPPDATA": str(self.source_root)})

    def test_real_validation_default_uses_private_source_with_fake_gateway_only(self):
        from fishery_ai.real_validation import run_real_validation
        from fishery_ai.model_gateway import ModelResponse
        from fishery_ai.contracts import Usage
        secure_files.write_private(self.env, f"DEEPSEEK_API_KEY={FAKE_A}\n".encode())
        legacy = self.source_root / ".env"
        legacy.write_text(f"DEEPSEEK_API_KEY={FAKE_B}\n", encoding="utf-8")
        original_read = Path.read_text
        def no_legacy(path, *args, **kwargs):
            if path == legacy:
                raise AssertionError("no legacy CLI fallback")
            return original_read(path, *args, **kwargs)
        owner = self
        class FakeGateway:
            request_attempts = 1
            def complete(self, _request, runtime):
                owner.assertTrue(runtime.credential._for_adapter() == FAKE_A)
                owner.assertEqual(runtime.credential.status.source, "PROJECT_ENV")
                return ModelResponse("OK", Usage())
        output = StringIO()
        with patch.dict(os.environ, {}, clear=True), \
                patch("fishery_ai.real_validation.private_project_location", return_value=self.location), \
                patch("fishery_ai.real_validation.OpenAICompatibleAdapter", return_value=FakeGateway()), \
                patch.object(Path, "read_text", no_legacy), redirect_stdout(output):
            result = run_real_validation(check="basic", scenario="normal", confirm_network=True)
        self.assertEqual(result, 0)
        for fake in (FAKE_A, FAKE_B):
            self.assertNotIn(fake, output.getvalue())

    def test_real_broad_file_permissions_fail_closed_on_temporary_fake_credentials(self):
        if os.name == "nt":
            with self.assertRaises(secure_files.SecureFileError):
                secure_files.write_private(self.env, f"{REF}={FAKE_A}\n".encode(),
                    secure_files.private_policy() + "(A;;FR;;;BU)")
        else:
            self.seed()
            self.env.chmod(0o644)
        with patch.object(Path, "read_text", side_effect=AssertionError("no unsafe Secret read")):
            with self.assertRaises(CredentialFileError):
                self.store.resolve(REF)
        self.assert_code("ENV_PERMISSION_ERROR", lambda: self.writer.inspect(REF, AuthSpec.REQUIRED_BEARER))

    def test_directory_and_file_acl_are_user_owned(self):
        with patch.object(secure_files, "inspect_policy", wraps=secure_files.inspect_policy) as checker:
            self.change("create", FAKE_A)
        directories = [call for call in checker.call_args_list if call.kwargs.get("user_owned")]
        self.assertTrue(directories)
        for path in (self.location.base, self.root, self.env):
            secure_files.inspect_policy(path, directory=path != self.env, user_owned=True)

    def test_hardlink_rejected_before_private_file_read(self):
        self.seed()
        os.link(self.env, self.root / "hardlink")
        with self.assertRaises(CredentialFileError):
            self.store.resolve(REF)
        self.assert_code("ENV_PERMISSION_ERROR", lambda: self.writer.inspect(REF, AuthSpec.REQUIRED_BEARER))

    def test_reparse_path_is_rejected(self):
        with patch.object(secure_files, "guard_path", side_effect=secure_files.SecureFileError()):
            self.assert_code("ENV_PERMISSION_ERROR", lambda: self.change("create", FAKE_A, revision="fake"))
            with self.assertRaises(CredentialFileError):
                self.store.resolve(REF)

    def test_git_is_not_used_for_external_storage(self):
        with patch("fishery_ai.project_env.subprocess.run", side_effect=AssertionError("no external Git checks")):
            self.change("create", FAKE_A)
            self.change("replace", FAKE_B)
            self.change("remove")

    def test_lock_staging_and_retained_recovery_are_inside_storage_boundary(self):
        self.seed()
        writes = []
        real_write = secure_files.write_private
        def record_write(path, body, policy=None):
            writes.append(path)
            return real_write(path, body, policy)
        real_replace = secure_files.atomic_replace
        moves = []
        def fail_after_replace(source, destination):
            moves.append((source, destination))
            if len(moves) == 1:
                real_replace(source, destination)
            raise OSError("fictional failure")
        with patch.object(secure_files, "write_private", side_effect=record_write), \
                patch.object(secure_files, "atomic_replace", side_effect=fail_after_replace):
            self.assert_code("ENV_RECOVERY_REQUIRED", lambda: self.change("replace", FAKE_B))
        self.assertTrue((self.root / ".env.writer.lock").exists())
        self.assertEqual(len(writes), 2)
        for path in writes:
            self.assertTrue(path.is_relative_to(self.root))
            self.assertEqual(path.parent.stat().st_dev, self.root.stat().st_dev)
            secure_files.inspect_policy(path if path.exists() else self.env)
        self.assertEqual(len(list(self.root.glob(".env.stage-*/original"))), 1)
        self.assertFalse((self.source_root / ".env.writer.lock").exists())

    def test_rollback_and_revision_conflict_still_work(self):
        self.seed()
        old_revision = self.revision()
        original = self.env.read_bytes()
        real = secure_files.atomic_replace
        calls = []
        def fail_once(source, destination):
            real(source, destination)
            calls.append(source)
            if len(calls) == 1:
                raise OSError("fictional failure")
        with patch.object(secure_files, "atomic_replace", side_effect=fail_once):
            self.assert_code("ENV_WRITE_FAILED", lambda: self.change("replace", FAKE_B))
        self.assertTrue(self.env.read_bytes() == original)
        self.change("replace", FAKE_B)
        self.assert_code("ENV_REVISION_CONFLICT", lambda: self.change("replace", FAKE_A, old_revision))


class PrivateStorageWebTests(r2.CredentialWebTests):
    # Replay the R2 Web security/cache/trace tests against the actual private layout.
    private_storage = True

    def test_normal_and_streaming_share_one_private_snapshot_per_request(self):
        from fishery_ai.model_gateway import ModelEvent, ModelResponse
        from fishery_ai.contracts import Usage
        snapshots = []
        text = '{"inference":"fixture","recommendations":[],"uncertainty":[]}'
        class FakeGateway:
            def complete(self, _request, runtime):
                snapshots.append(runtime.credential)
                return ModelResponse(text, Usage())
            def stream(self, _request, runtime):
                snapshots.append(runtime.credential)
                yield ModelEvent(delta=text)
        self.gateway = FakeGateway()
        self.api_change("create", FAKE_A)
        payload = {"profile_id": r2.PROFILE, "scenario": "low_oxygen",
                   "question": "当前水质情况怎么样？", "confirm_network": True}
        with patch.object(self.store, "resolve", wraps=self.store.resolve) as resolver:
            normal = self.client.post("/api/analyze", json=payload)
        self.assertEqual(normal.status_code, 200)
        self.assertEqual(resolver.call_count, 1)
        self.api_change("replace", FAKE_B)
        with patch.object(self.store, "resolve", wraps=self.store.resolve) as resolver:
            streaming = self.client.post("/api/analyze/stream", json=payload)
            streaming_text = streaming.get_data(as_text=True)
        self.assertEqual(streaming.status_code, 200)
        self.assertEqual(resolver.call_count, 1)
        self.assertIn("event: completed", streaming_text)
        self.assertEqual([item.status.source for item in snapshots], ["PROJECT_ENV", "PROJECT_ENV"])
        self.assertTrue(snapshots[0]._for_adapter() == FAKE_A)
        self.assertTrue(snapshots[1]._for_adapter() == FAKE_B)
        for fake in (FAKE_A, FAKE_B):
            self.assertNotIn(fake, normal.get_data(as_text=True) + streaming_text)
            self.assertNotIn(fake, (self.root / "trace.jsonl").read_text(encoding="utf-8"))

    def test_mock_and_ollama_none_never_inspect_private_file(self):
        from fishery_ai.model_gateway import ModelResponse
        from fishery_ai.contracts import Usage
        owner = self
        class FakeGateway:
            def complete(self, _request, runtime):
                owner.assertEqual(runtime.credential.status.source, "NONE_REQUIRED")
                return ModelResponse('{"inference":"fixture","recommendations":[]}', Usage())
        self.gateway = FakeGateway()
        with patch.object(self.store, "_project_values", side_effect=AssertionError("NONE must not read credentials")):
            for profile_id in (MOCK_PROFILE_ID, "ollama-qwen35-4b-local"):
                response = self.client.post("/api/analyze", json={"profile_id": profile_id,
                    "scenario": "normal", "question": "当前水质？", "confirm_network": True})
                self.assertEqual(response.status_code, 200)

    def test_status_marks_user_private_storage_without_secret_or_path(self):
        self.api_change("create", FAKE_A)
        state = self.status()
        self.assertEqual(state["source"], "PROJECT_ENV")
        self.assertEqual(state["storage"], "USER_PRIVATE")
        response = self.client.post("/api/secret-status", json={"profile_id": "qwen-plus-experimental"})
        self.assertEqual(response.get_json()["storage"], "USER_PRIVATE")
        self.assertNotIn(FAKE_A, response.get_data(as_text=True))
        self.assertNotIn(str(self.root), response.get_data(as_text=True))

    def test_browser_path_override_rejected_without_creation(self):
        for field in ("path", "env_path", "project_root", "storage_root", "LOCALAPPDATA"):
            response = self.api_change("create", FAKE_A, **{field: str(self.source_root / ".env")})
            self.assertEqual(response.get_json()["error_code"], "INVALID_REQUEST")
        self.assertFalse(self.env.exists())


# Explicit historical fixtures; not active startup assets.
from historical_model_fixtures import install as _install_history
_install_history(globals())
