"""Manual V2: temporary private stores, fictional credentials, no network."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO
import json
import threading

from fishery_ai import secure_files
from fishery_ai.credential_paths import private_manual_location, private_project_location
from fishery_ai.credentials import CredentialStore
from fishery_ai.project_env import ProjectEnvWriter
from fishery_ai.providers import AuthSpec
from fishery_ai.manual import ManualRequest, ManualResponse
from fishery_ai.manual_experiments import ManualExperimentStore, validate_experiment
from fishery_ai.model_gateway import ModelProfile, GatewayError
from fishery_ai.execution import current_handle
from fishery_ai.web import create_app
from tests.security.test_credential_writer import R2Fixture, FAKE_A, FAKE_B, REF


MANUAL_REF = "MANUAL_TEST_KEY"


def draft(**changes):
    return {"name": "离线实验", "service_name": "未注册服务标签", "transport": "openai_chat",
            "base_url": "http://127.0.0.1:11434/v1", "model": "unknown-exact-model",
            "credential_ref": "", "timeout": 30,
            "raw_request_body": {"model": "unknown-exact-model", "messages": [{"role": "user", "content": "OK"}],
                                 "enable_thinking": False}, "notes": "offline", **changes}


class ManualV2Tests(R2Fixture):
    private_storage = True

    def setUp(self):
        super().setUp()
        self.seed()
        self.formal_bytes = self.env.read_bytes()
        self.manual_location = replace(self.location, env_path=self.env.with_name("manual.env"))
        self.manual_store = CredentialStore(self.manual_location.env_path, {}, private_location=self.manual_location)
        self.manual_writer = ProjectEnvWriter(self.root, self.manual_store, require_git_ignored=False, filename="manual.env")
        self.seen = []
        self.wait = False
        self.started = threading.Event()
        outer = self

        class Gateway:
            def manual_complete(self, request, runtime):
                outer.seen.append((request, runtime))
                if outer.wait:
                    outer.started.set()
                    current_handle()._cancel.wait(2)
                    current_handle().check()
                return ManualResponse({"choices": [{"message": {"content": "offline",
                    "tool_calls": [{"function": {"name": "never_execute"}}]}}], "echo": runtime.api_key or "no-key"})

            def manual_stream(self, request, runtime):
                outer.seen.append((request, runtime))
                yield ManualResponse({"choices": [{"delta": {"content": "offline"}}]})
                current_handle().check()
                yield ManualResponse({"usage": {"total_tokens": 3}})

        profile = ModelProfile("v1-saved", "V1 saved", "cloud", "https://offline.invalid/v1", "v1-model",
            credential_ref=REF, service_id="custom", auth_spec=AuthSpec.REQUIRED_BEARER)
        with patch("fishery_ai.web._builtin_profiles", return_value=(profile,)):
            self.app = create_app(credential_store=self.store, credential_writer=self.writer,
                manual_credential_store=self.manual_store, manual_credential_writer=self.manual_writer,
                manual_experiments_dir=self.source_root / "outputs/manual-experiments",
                trace_path=self.source_root / "outputs/trace.jsonl", custom_profiles_dir=self.source_root / "outputs/custom",
                capability_evidence_dir=self.source_root / "outputs/evidence", real_gateway_factory=Gateway)
        self.client = self.app.test_client()
        self.headers = {"Origin": "http://localhost", "X-CSRF-Token": self.client.get("/api/credential-session").json["csrf_token"]}

    def prepare(self):
        data = self.client.post("/api/requests", json={}, headers=self.headers).json
        return {key: data[key] for key in ("request_id", "control_token")}

    def key_status(self, ref=MANUAL_REF):
        return self.client.post("/api/manual-v2/credentials/status", json={"credential_ref": ref})

    def key(self, action, secret=None, revision=None):
        revision = revision if revision is not None else self.key_status().json["revision"]
        return self.client.open("/api/manual-v2/credentials", method=action, headers=self.headers,
            json={"credential_ref": MANUAL_REF, "revision": revision, **({"secret": secret} if secret else {})})

    def send(self, values=None, **extra):
        return self.client.post("/api/manual-v2", headers=self.headers,
            json={"experiment": values or draft(), "confirm_network": True, **self.prepare(), **extra})

    def test_path_is_stable_and_file_boundary_independent(self):
        with patch("fishery_ai.credential_paths.Path.home", return_value=self.location.base):
            manual = private_manual_location(self.source_root, {"LOCALAPPDATA": str(self.location.base)})
            formal = private_project_location(self.source_root, {"LOCALAPPDATA": str(self.location.base)})
            self.assertEqual(manual.env_path.parent, formal.env_path.parent)
            self.assertEqual(manual.env_path.name, "manual.env")
            self.assertEqual(manual, private_manual_location(self.source_root, {"LOCALAPPDATA": str(self.location.base)}))
        with self.assertRaises(ValueError):
            ProjectEnvWriter(self.root, self.manual_store, require_git_ignored=False, filename="../arbitrary")

    def test_experiment_crud_save_as_and_restart(self):
        created = self.client.post("/api/manual-v2/experiments", json=draft(), headers=self.headers).json["experiment"]
        identifier = created["id"]
        changed = draft(name="更新实验", timeout=60)
        response = self.client.put(f"/api/manual-v2/experiments/{identifier}", json=changed, headers=self.headers)
        self.assertEqual(response.json["experiment"]["created_at"], created["created_at"])
        copied = self.client.post("/api/manual-v2/experiments", json=changed, headers=self.headers).json["experiment"]
        self.assertNotEqual(identifier, copied["id"])
        store = ManualExperimentStore(self.source_root / "outputs/manual-experiments")
        self.assertEqual(len(store.list()), 2)
        self.assertEqual(store.get(identifier)["timeout"], 60)
        self.assertEqual(self.client.delete(f"/api/manual-v2/experiments/{identifier}", headers=self.headers, json={}).status_code, 200)
        self.assertEqual(len(store.list()), 1)
        self.assertEqual(self.client.get(f"/api/manual-v2/experiments/{identifier}").status_code, 404)

    def test_missing_raw_model_injected_for_normal_and_stream_without_changing_saved_body(self):
        self.key("POST", FAKE_B)
        body = {"messages": [{"role": "user", "content": "OK"}], "enable_thinking": False}
        values = draft(credential_ref=MANUAL_REF, raw_request_body=body)
        original = json.dumps(values, ensure_ascii=False, sort_keys=True)
        response = self.client.post("/api/manual-v2/experiments", json=values, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        saved = response.json["experiment"]
        self.assertEqual(saved["raw_request_body"], body)
        self.assertNotIn("model", saved["raw_request_body"])
        path = self.source_root / "outputs/manual-experiments" / (saved["id"] + ".json")
        before = path.read_bytes()
        self.assertEqual(self.send(values).status_code, 200)
        self.assertEqual(json.loads(self.seen[-1][0].body_json), {**body, "model": values["model"]})
        streaming_body = {**body, "stream": True}
        response = self.send(draft(credential_ref=MANUAL_REF, raw_request_body=streaming_body))
        self.assertIn(b"event: completed", response.data)
        self.assertEqual(json.loads(self.seen[-1][0].body_json), {**streaming_body, "model": values["model"]})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(json.dumps(values, ensure_ascii=False, sort_keys=True), original)
        reloaded = self.client.get(f"/api/manual-v2/experiments/{saved['id']}").json["experiment"]
        self.assertEqual(reloaded["raw_request_body"], body)
        self.assertNotIn(FAKE_B, path.read_text(encoding="utf-8"))

    def test_same_explicit_raw_model_remains_compatible(self):
        values = draft()
        self.assertEqual(validate_experiment(values)["raw_request_body"], values["raw_request_body"])
        self.assertEqual(self.send(values).status_code, 200)
        self.assertEqual(json.loads(self.seen[-1][0].body_json), values["raw_request_body"])

    def test_conflicting_raw_model_still_rejected_and_v1_requires_explicit_model(self):
        body = {"model": "other-model", "messages": [{"role": "user", "content": "OK"}]}
        values = draft(raw_request_body=body)
        self.assertEqual(self.send(values).json["error_code"], "MANUAL_MODEL_MISMATCH")
        self.assertEqual(self.client.post("/api/manual-v2/experiments", json=values, headers=self.headers).json["error_code"], "MANUAL_MODEL_MISMATCH")
        response = self.client.post("/api/manual", json={"profile_id": "v1-saved", "confirm_network": True,
            "body": {"messages": [{"role": "user", "content": "OK"}]}, **self.prepare()}, headers=self.headers)
        self.assertEqual(response.json["error_code"], "MANUAL_MODEL_MISMATCH")
        self.assertFalse(self.seen)

    def test_manual_credential_crud_hot_reload_and_formal_unaffected(self):
        self.assertEqual(self.key_status().json["availability"], "MISSING")
        response = self.key("POST", FAKE_B)
        self.assertEqual(response.json["availability"], "PRESENT")
        self.assertNotIn(FAKE_B, response.get_data(as_text=True))
        old = self.manual_store.resolve(MANUAL_REF)
        self.assertEqual(self.key("PUT", FAKE_A).status_code, 200)
        self.assertEqual(self.manual_store.resolve(MANUAL_REF)._for_adapter(), FAKE_A)
        self.assertEqual(old._for_adapter(), FAKE_B)
        self.assertEqual(self.env.read_bytes(), self.formal_bytes)
        self.assertEqual(self.store.resolve(MANUAL_REF).status.availability, "MISSING")
        self.assertEqual(self.key("DELETE").json["availability"], "MISSING")
        self.assertEqual(self.env.read_bytes(), self.formal_bytes)
        self.assertTrue((self.root / "manual.env.writer.lock").exists())
        self.assertFalse(list(self.root.glob("manual.env.stage-*")))

    def test_revision_conflict_csrf_origin_host_and_arbitrary_path(self):
        old = self.key_status().json["revision"]
        self.assertEqual(self.key("POST", FAKE_A).status_code, 200)
        self.assertEqual(self.key("PUT", FAKE_B, old).json["error_code"], "ENV_REVISION_CONFLICT")
        for headers in ({}, {**self.headers, "Origin": "http://evil.invalid"}, {**self.headers, "Host": "evil.invalid"}):
            response = self.client.post("/api/manual-v2/credentials", json={}, headers=headers)
            self.assertEqual(response.status_code, 403)
        response = self.client.post("/api/manual-v2/credentials/status", json={"credential_ref": MANUAL_REF, "path": "arbitrary"})
        self.assertEqual(response.json["error_code"], "INVALID_REQUEST")

    def test_unsafe_acl_fail_closed_and_atomic_failure_preserves_file(self):
        self.key("POST", FAKE_A)
        original = self.manual_location.env_path.read_bytes()
        revision = self.key_status().json["revision"]
        with patch("fishery_ai.secure_files.inspect_policy", side_effect=secure_files.SecureFileError()):
            response = self.key("PUT", FAKE_B, revision)
            self.assertIn(response.json["error_code"], ("ENV_PERMISSION_ERROR", "CREDENTIAL_FILE_ERROR"))
        with patch("fishery_ai.secure_files.atomic_replace", side_effect=OSError("fictional failure")):
            self.assertEqual(self.key("PUT", FAKE_B, revision).json["error_code"], "ENV_WRITE_FAILED")
        self.assertEqual(self.manual_location.env_path.read_bytes(), original)

    def test_no_capability_defaults_protocol_or_analysis_and_raw_body_parity(self):
        values = draft()
        with patch("fishery_ai.web.Orchestrator", side_effect=AssertionError()), \
             patch("fishery_ai.web.validate_options", side_effect=AssertionError()), \
             patch("fishery_ai.model_gateway.effective_runtime_defaults", side_effect=AssertionError()), \
             patch("fishery_ai.protocol_specs.protocol_for", side_effect=AssertionError()), \
             patch("fishery_ai.web.ProfileRegistry", side_effect=AssertionError()):
            response = self.send(values)
        self.assertEqual(response.status_code, 200)
        manual, runtime = self.seen[-1]
        self.assertEqual(json.loads(manual.body_json), values["raw_request_body"])
        self.assertEqual(runtime.max_retries, 0)
        self.assertEqual(runtime.read_timeout_s, 30)
        self.assertEqual(runtime.service_id, "custom")
        self.assertEqual(runtime.auth_spec, AuthSpec.NONE)
        self.assertIn("never_execute", response.get_data(as_text=True))
        self.assertFalse((self.source_root / "outputs/evidence").exists())
        self.assertFalse((self.source_root / "outputs/trace.jsonl").exists())
        self.assertFalse((self.source_root / "outputs/custom").exists())

    def test_v1_reads_formal_and_v2_never_reads_formal_or_process(self):
        self.key("POST", FAKE_B)
        response = self.client.post("/api/manual", json={"profile_id": "v1-saved", "confirm_network": True,
            "body": {"model": "v1-model", "messages": [{"role": "user", "content": "OK"}]}, **self.prepare()}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.seen[-1][1].credential._for_adapter(), FAKE_A)
        self.assertEqual(self.manual_store.resolve(REF).status.availability, "MISSING")
        self.process[MANUAL_REF] = FAKE_A
        response = self.send(draft(credential_ref=MANUAL_REF))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.seen[-1][1].credential._for_adapter(), FAKE_B)
        self.assertNotIn(FAKE_B, response.get_data(as_text=True))
        self.assertEqual(self.send(draft(credential_ref=REF)).json["error_code"], "SECRET_MISSING")

    def test_secret_not_saved_echoed_or_in_repr_and_deletes_are_independent(self):
        self.key("POST", FAKE_B)
        values = draft(credential_ref=MANUAL_REF)
        response = self.client.post("/api/manual-v2/experiments", json=values, headers=self.headers)
        identifier = response.json["experiment"]["id"]
        self.assertNotIn(FAKE_B, response.get_data(as_text=True))
        path = self.source_root / "outputs/manual-experiments" / (identifier + ".json")
        self.assertNotIn(FAKE_B, path.read_text(encoding="utf-8"))
        malicious = draft(credential_ref=MANUAL_REF, notes=FAKE_B)
        self.assertEqual(self.client.post("/api/manual-v2/experiments", json=malicious, headers=self.headers).json["error_code"], "MANUAL_SECRET_IN_BODY")
        escaped_fake = FAKE_B + '"\\雪'
        self.key("PUT", escaped_fake)
        escaped = draft(credential_ref=MANUAL_REF, notes=escaped_fake)
        self.assertEqual(self.client.post("/api/manual-v2/experiments", json=escaped, headers=self.headers).json["error_code"], "MANUAL_SECRET_IN_BODY")
        self.key("PUT", FAKE_B)
        self.assertEqual(self.send(values).status_code, 200)
        self.assertNotIn(FAKE_B, repr(self.seen[-1]))
        self.key("DELETE")
        self.assertTrue(path.exists())
        self.assertEqual(self.send(values).json["error_code"], "SECRET_MISSING")
        self.key("POST", FAKE_A)
        self.client.delete(f"/api/manual-v2/experiments/{identifier}", headers=self.headers, json={})
        self.assertEqual(self.manual_store.status(MANUAL_REF).availability, "PRESENT")

    def test_validation_url_reserved_fields_timeout_size_and_depth(self):
        bad_cases = [draft(base_url="file:///tmp"), draft(base_url="http://user:password@localhost/v1"),
                     draft(base_url="http://localhost/v1?key=unsafe"), draft(timeout=0), draft(timeout=601),
                     draft(credential_ref="bad-ref"), draft(transport="other"), draft(path="arbitrary")]
        for values in bad_cases:
            self.assertEqual(self.send(values).status_code, 400)
        body = draft()["raw_request_body"]
        for key in ("Authorization", "extra_headers", "base_url", "api_key", "extra_body"):
            self.assertEqual(self.send(draft(raw_request_body={**body, key: "blocked"})).json["error_code"], "MANUAL_RESERVED_FIELD")
        with self.assertRaises(GatewayError) as caught:
            validate_experiment(draft(raw_request_body={**body, "padding": "x" * 13000}))
        self.assertEqual(caught.exception.code, "REQUEST_TOO_LARGE")
        deep = "value"
        for _ in range(34):
            deep = [deep]
        with self.assertRaises(GatewayError) as caught:
            validate_experiment(draft(raw_request_body={**body, "nested": deep}))
        self.assertEqual(caught.exception.code, "REQUEST_TOO_COMPLEX")
        self.assertEqual(self.send(confirm_network=False).json["error_code"], "NETWORK_CONFIRMATION_REQUIRED")
        self.assertFalse(self.seen)

    def test_stream_has_raw_usage_and_cancellation(self):
        body = {**draft()["raw_request_body"], "stream": True}
        response = self.send(draft(raw_request_body=body))
        self.assertIn(b"event: raw_delta", response.data)
        self.assertIn(b"event: completed", response.data)
        self.assertEqual(json.loads(self.seen[-1][0].body_json), body)
        control = self.prepare()
        response = self.client.post("/api/manual-v2", headers=self.headers, buffered=False,
            json={"experiment": draft(raw_request_body=body), "confirm_network": True, **control})
        iterator = iter(response.response)
        first = next(iterator)
        self.client.post(f"/api/requests/{control['request_id']}/cancel", json=control, headers=self.headers)
        raw = first + b"".join(iterator)
        response.close()
        self.assertIn(b"USER_CANCELLED", raw)
        self.assertNotIn(b"event: completed", raw)

    def test_normal_stop_uses_shared_request_handle(self):
        self.wait = True
        control = self.prepare()
        responses = []
        with self.client.session_transaction() as original:
            session_copy = dict(original)
        def run():
            with self.app.test_client() as client:
                with client.session_transaction() as session:
                    session.update(session_copy)
                responses.append(client.post("/api/manual-v2", headers=self.headers,
                    json={"experiment": draft(), "confirm_network": True, **control}))
        worker = threading.Thread(target=run)
        worker.start()
        self.assertTrue(self.started.wait(2))
        self.client.post(f"/api/requests/{control['request_id']}/cancel", json=control, headers=self.headers)
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(responses[0].json["error_code"], "USER_CANCELLED")

    def test_path_injection_missing_and_shared_store_rejected(self):
        self.assertEqual(self.client.get("/api/manual-v2/experiments/arbitrary").status_code, 404)
        self.assertEqual(self.client.post("/api/manual-v2", headers=self.headers, json={"credential_path": "arbitrary"}).json["error_code"], "INVALID_REQUEST")
        with self.assertRaises(ValueError):
            create_app(credential_store=self.store, manual_credential_store=self.store)

    def test_startup_composes_separate_fixed_private_files_without_reading_them(self):
        from fishery_ai.web import run_web
        with patch("fishery_ai.web.Path.cwd", return_value=self.source_root), \
             patch("fishery_ai.web.private_project_location", return_value=self.location), \
             patch("fishery_ai.web.private_manual_location", return_value=self.manual_location), \
             patch("fishery_ai.web.create_app") as factory, redirect_stdout(StringIO()):
            run_web()
        fields = factory.call_args.kwargs
        self.assertEqual(fields["credential_store"].project_env_path, self.env)
        self.assertEqual(fields["manual_credential_store"].project_env_path, self.manual_location.env_path)
        self.assertEqual(fields["manual_credential_store"]._process_env, {})
        self.assertEqual(fields["manual_credential_writer"].path.name, "manual.env")
        self.assertEqual(fields["credential_writer"].path.name, ".env")
        self.assertIs(factory.return_value.run.call_args.kwargs["load_dotenv"], False)

    def test_existing_adapter_manual_transport_receives_body_unmodified(self):
        from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
        self.send()
        manual, runtime = self.seen[-1]
        expected = json.loads(manual.body_json)
        result = ManualResponse({"choices": []})
        adapter = OpenAICompatibleAdapter()
        with patch.object(adapter, "_bridge", return_value=(item for item in [result])) as bridge:
            self.assertIs(adapter.manual_complete(manual, runtime), result)
            self.assertEqual(bridge.call_args.args[0], expected)
            self.assertEqual(bridge.call_args.kwargs, {"stream": False, "manual": True})
        self.assertEqual(runtime.max_retries, 0)

    def test_manual_writer_keeps_bom_comments_crlf_and_unrelated_values(self):
        body = b"\xef\xbb\xbf# offline\r\nUNRELATED='fixture'\r\n"
        secure_files.write_private(self.manual_location.env_path, body, secure_files.private_policy())
        self.key("POST", FAKE_A)
        changed = self.manual_location.env_path.read_bytes()
        self.assertTrue(changed.startswith(body))
        self.key("PUT", FAKE_B)
        self.key("DELETE")
        self.assertEqual(self.manual_location.env_path.read_bytes(), body)

    def test_known_secret_in_saved_experiment_cannot_be_returned_after_rotation(self):
        values = draft(credential_ref=MANUAL_REF, notes=FAKE_A)
        created = self.client.post("/api/manual-v2/experiments", json=values, headers=self.headers)
        self.assertEqual(created.status_code, 200)  # Missing key: no secret is read or invented.
        self.key("POST", FAKE_A)
        response = self.client.get("/api/manual-v2/experiments")
        self.assertEqual(response.json["error_code"], "MANUAL_SECRET_IN_BODY")
        self.assertNotIn(FAKE_A, response.get_data(as_text=True))
