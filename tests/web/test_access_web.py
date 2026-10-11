"""Preset / cancellation / Manual Web boundaries; temporary files and fictional keys only."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import threading
import unittest
from unittest.mock import patch

import tests.security.test_execution as test_execution
from fishery_ai.credentials import CredentialStore
from fishery_ai.execution import current_handle
from fishery_ai.manual import ManualResponse
from fishery_ai.model_gateway import GatewayError, ModelEvent, ModelResponse
from fishery_ai.contracts import Usage
from fishery_ai.web import create_app


class AccessWebTests(unittest.TestCase):
    def setUp(self):
        test_execution.ExecutionTests.setUp(self)
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.process = {"DASHSCOPE_API_KEY": "fictional-old-key"}
        self.store = CredentialStore(self.root / "private.env", self.process)
        self.seen = []
        self.started = threading.Event()
        outer = self
        class Gateway:
            def complete(self, request, runtime):
                outer.seen.append(runtime)
                if outer.wait:
                    outer.started.set()
                    current_handle()._cancel.wait(2)
                    current_handle().check()
                return ModelResponse('{"inference":"offline","recommendations":[],"uncertainty":[]}')
            def stream(self, request, runtime):
                outer.seen.append(runtime)
                yield ModelEvent(delta='{"inference":')
                if outer.wait:
                    outer.started.set()
                    current_handle()._cancel.wait(2)
                    current_handle().check()
                yield ModelEvent(delta='"offline"}')
            def manual_complete(self, request, runtime):
                outer.seen.append((request, runtime))
                return ManualResponse({"choices":[{"message":{"tool_calls":[{"function":{"name":"never_execute"}}]}}]}, Usage())
            def manual_stream(self, request, runtime):
                outer.seen.append((request, runtime))
                yield ManualResponse({"choices":[{"delta":{"content":"offline"}}]}, Usage())
        self.wait = False
        self.app = create_app(credential_store=self.store, real_gateway_factory=Gateway,
            trace_path=self.root / "trace.jsonl", custom_profiles_dir=self.root / "custom",
            capability_evidence_dir=self.root / "evidence")
        self.client = self.app.test_client()
        self.csrf = self.client.get("/api/credential-session").json["csrf_token"]
        self.headers = {"Origin":"http://localhost", "X-CSRF-Token": self.csrf}

    def prepare(self):
        response = self.client.post("/api/requests", json={}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        return {key:response.json[key] for key in ("request_id", "control_token")}

    def payload(self, control, **fields):
        return {"profile_id":"preset-qwen-plus-off", "scenario":"low_oxygen",
                "question":"offline", "confirm_network":True, **control, **fields}

    def test_mock_request_id_and_terminal_state(self):
        control = self.prepare()
        response = self.client.post("/api/analyze", json=self.payload(control, profile_id="mock-demo"), headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["result"]["request_id"], control["request_id"])
        state = self.client.post(f"/api/requests/{control['request_id']}/status", json=control, headers=self.headers).json
        self.assertEqual(state["state"], "COMPLETED")
        self.assertTrue(state["backend_io_closed"])
        self.assertNotIn(control["control_token"], (self.root / "trace.jsonl").read_text())

    def test_stop_cancels_normal_and_preserves_credential_snapshot(self):
        self.wait = True
        control = self.prepare()
        responses = []
        def execute():
            with self.app.test_client() as client:
                with client.session_transaction() as session:
                    with self.client.session_transaction() as original:
                        session.update(original)
                responses.append(client.post("/api/analyze", json=self.payload(control), headers=self.headers))
        worker = threading.Thread(target=execute)
        worker.start()
        self.assertTrue(self.started.wait(2))
        self.process["DASHSCOPE_API_KEY"] = "fictional-rotated-key"
        cancelled = self.client.post(f"/api/requests/{control['request_id']}/cancel", json=control, headers=self.headers)
        self.assertEqual(cancelled.status_code, 200)
        worker.join(3)
        self.assertFalse(worker.is_alive())
        result = responses[0].json["result"]
        self.assertEqual(result["error_code"], "USER_CANCELLED")
        self.assertEqual(result["status"], "cancelled")
        self.assertFalse(result["structured_parse_ok"])
        self.assertEqual(self.seen[0].credential._for_adapter(), "fictional-old-key")
        self.assertEqual(self.store.resolve("DASHSCOPE_API_KEY")._for_adapter(), "fictional-rotated-key")
        self.assertFalse((self.root / "evidence").exists())
        self.assertNotIn("fictional-old-key", (self.root / "trace.jsonl").read_text())

    def test_cancel_stream_partial_json_never_becomes_structured_result(self):
        self.wait = True
        control = self.prepare()
        response = self.client.post("/api/analyze/stream", json=self.payload(control), headers=self.headers, buffered=False)
        iterator = iter(response.response)
        chunks = []
        for _ in range(5):
            chunks.append(next(iterator))
        self.client.post(f"/api/requests/{control['request_id']}/cancel", json=control, headers=self.headers)
        chunks.extend(iterator)
        response.close()
        raw = b"".join(chunks).decode()
        self.assertIn("USER_CANCELLED", raw)
        self.assertIn('"structured_parse_ok":false', raw)
        self.assertNotIn("event: completed", raw)

    def test_control_requires_csrf_origin_and_ownership(self):
        self.assertEqual(self.client.post("/api/requests", json={}).status_code, 403)
        self.assertEqual(self.client.post("/api/requests", json={}, headers={**self.headers,"Origin":"http://evil.invalid"}).status_code, 403)
        self.assertEqual(self.client.post("/api/requests", json={}, headers={**self.headers,"Host":"evil.invalid"}).status_code, 403)
        control = self.prepare()
        response = self.client.post(f"/api/requests/{control['request_id']}/cancel", json={"control_token":"wrong"}, headers=self.headers)
        self.assertEqual(response.json["error_code"], "REQUEST_NOT_FOUND")
        response = self.client.post(f"/api/requests/{control['request_id']}/status", json=["invalid"], headers=self.headers)
        self.assertEqual(response.json["error_code"], "INVALID_REQUEST")
        response = self.client.post("/api/manual", json={"profile_id":[]}, headers=self.headers)
        self.assertEqual(response.json["error_code"], "INVALID_REQUEST")

    def test_manual_bypasses_every_managed_component_and_defaults(self):
        control = self.prepare()
        body = {"model":"qwen-plus","messages":[{"role":"user","content":"OK"}],"enable_thinking":False}
        with patch("fishery_ai.web.Orchestrator", side_effect=AssertionError("no orchestration")), \
             patch("fishery_ai.model_gateway.effective_runtime_defaults", side_effect=AssertionError("no defaults")), \
             patch("fishery_ai.web.validate_options", side_effect=AssertionError("no validation")):
            response = self.client.post("/api/manual", json={**self.payload(control), "body":body}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn("never_execute", json.dumps(response.json))
        manual, runtime = self.seen[0]
        self.assertEqual(json.loads(manual.body_json), body)
        self.assertEqual(runtime.max_retries, 0)
        self.assertEqual(runtime.access_mode, "manual_expert")
        self.assertNotIn("AnalysisResult", json.dumps(response.json))
        self.assertNotIn("fictional-old-key", json.dumps(response.json))
        self.assertFalse((self.root / "trace.jsonl").exists())
        self.assertFalse((self.root / "evidence").exists())

    def test_manual_stream_preserves_raw_events_without_usage_injection(self):
        control = self.prepare()
        body = {"model":"qwen-plus","messages":[{"role":"user","content":"OK"}],"stream":True}
        response = self.client.post("/api/manual", json={**self.payload(control),"body":body}, headers=self.headers)
        self.assertIn(b"event: raw_delta", response.data)
        self.assertIn(b"event: completed", response.data)
        self.assertEqual(json.loads(self.seen[0][0].body_json), body)

    def test_missing_secret_and_network_confirmation_fail_closed(self):
        control = self.prepare()
        body = {"model":"qwen-plus","messages":[{"role":"user","content":"OK"}]}
        self.process.clear()
        response = self.client.post("/api/manual", json={**self.payload(control),"body":body}, headers=self.headers)
        self.assertEqual(response.json["error_code"], "SECRET_MISSING")
        response = self.client.post("/api/manual", json={**self.payload(control),"body":body,"confirm_network":False}, headers=self.headers)
        self.assertEqual(response.json["error_code"], "NETWORK_CONFIRMATION_REQUIRED")
        self.assertEqual(self.seen, [])


# Explicit historical fixtures; not active startup assets.
from tests.support.historical_model_fixtures import install as _install_history
_install_history(globals())
