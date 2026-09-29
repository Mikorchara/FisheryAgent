"""Offline Profile Manager flow; fake gateway and blocked external sockets."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import os
import socket
import unittest

from fishery_ai.model_gateway import GatewayError, ModelResponse, ProfileRegistry
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.web import _builtin_profiles, create_app


def _deny_network(*_args, **_kwargs):
    raise AssertionError("real network is forbidden in Profile Manager tests")


class FakeGateway:
    def __init__(self):
        self.model_calls = 0
        self.chat_calls = 0
        self.last_request = None

    def list_models(self, runtime, *, all_models=False):
        self.model_calls += 1
        if runtime.model == "broken":
            raise GatewayError("HTTP_404")
        return [{"id": "school-model"}, {"id": "other-model"}, {"id": "qwen-plus"}]

    def complete(self, request, runtime):
        self.chat_calls += 1
        self.last_request = request
        return ModelResponse("OK", returned_model=runtime.model)


class ProfileManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store_dir = self.root / "custom_profiles"
        self.gateway = FakeGateway()
        self.client = create_app(trace_path=self.root / "trace.jsonl",
                                 custom_profiles_dir=self.store_dir,
                                 real_gateway_factory=lambda: self.gateway).test_client()
        for target in ("connect", "connect_ex", "sendto"):
            blocker = patch.object(socket.socket, target, _deny_network)
            blocker.start()
            self.addCleanup(blocker.stop)
        dns = patch.object(socket, "getaddrinfo", _deny_network)
        dns.start()
        self.addCleanup(dns.stop)

    @staticmethod
    def fields(**changes):
        values = {"display_name": "学校服务", "provider_id": "school",
                  "adapter_id": "openai_chat", "base_url": "https://example.invalid/v1",
                  "model": "school-model", "secret_env": "SCHOOL_LLM_API_KEY",
                  "provider_kind": "cloud"}
        values.update(changes)
        return values

    def test_presets_and_presence_only_secret_status(self):
        presets = self.client.get("/api/config").get_json()["presets"]
        by_id = {item["id"]: item for item in presets}
        self.assertEqual(set(by_id), {"qwen", "deepseek", "custom"})
        self.assertEqual(by_id["qwen"]["base_url"],
                         "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.assertEqual(by_id["deepseek"]["secret_env"], "DEEPSEEK_API_KEY")
        self.assertEqual(by_id["custom"]["adapter_id"], "generic_openai_chat")
        with patch.dict(os.environ, {}, clear=True):
            missing = self.client.post("/api/secret-status", json={"secret_env": "SCHOOL_LLM_API_KEY"})
        self.assertEqual(missing.get_json()["status"], "MISSING")
        with patch.dict(os.environ, {"SCHOOL_LLM_API_KEY": "offline-fixture"}):
            present = self.client.post("/api/secret-status", json={"secret_env": "SCHOOL_LLM_API_KEY"})
        self.assertEqual(present.get_json()["status"], "PRESENT")
        self.assertNotIn("offline-fixture", present.get_data(as_text=True))
        self.assertEqual(self.client.post("/api/secret-status", json={
            "secret_env": "not-a-name"}).status_code, 400)

    def test_model_query_and_connection_are_explicit_and_safe(self):
        fields = self.fields(model="", display_name="")
        with patch.dict(os.environ, {"SCHOOL_LLM_API_KEY": "offline-fixture"}):
            blocked = self.client.post("/api/profiles/models", json=fields)
            self.assertEqual(blocked.status_code, 403)
            self.assertEqual(self.gateway.model_calls, 0)
            models = self.client.post("/api/profiles/models", json={**fields, "confirm_network": True})
            self.assertEqual(models.status_code, 200)
            self.assertEqual(models.get_json()["models"],
                             ["other-model", "qwen-plus", "school-model"])
            self.assertFalse(models.get_json()["capabilities_verified"])
            self.assertNotIn("offline-fixture", models.get_data(as_text=True))
            no_confirm = self.client.post("/api/profiles/test", json={**self.fields(), "method": "models"})
            self.assertEqual(no_confirm.status_code, 403)
            tested = self.client.post("/api/profiles/test", json={
                **self.fields(), "method": "models", "confirm_network": True})
            self.assertEqual(tested.status_code, 200)
            self.assertEqual(tested.get_json()["model"], "school-model")
            self.assertGreaterEqual(tested.get_json()["latency_ms"], 0)
            self.assertTrue(tested.get_json()["test_id"])
            self.assertEqual(self.gateway.chat_calls, 0)

    def test_cloud_save_requires_matching_successful_test(self):
        self.assertEqual(self.client.post("/api/profiles", json=self.fields()).get_json()[
            "error_code"], "CONNECTION_TEST_REQUIRED")
        with patch.dict(os.environ, {"SCHOOL_LLM_API_KEY": "offline-fixture"}):
            tested = self.client.post("/api/profiles/test", json={
                **self.fields(), "method": "chat", "confirm_network": True}).get_json()
            self.assertEqual(self.gateway.chat_calls, 1)
            self.assertEqual(self.gateway.last_request.messages[0].content, "只回复 OK")
            changed = self.client.post("/api/profiles", json={
                **self.fields(model="other-model"), "test_id": tested["test_id"]})
            self.assertEqual(changed.get_json()["error_code"], "CONNECTION_TEST_REQUIRED")
            created = self.client.post("/api/profiles", json={
                **self.fields(), "test_id": tested["test_id"]})
            self.assertEqual(created.status_code, 201)
            self.assertEqual(created.get_json()["profile"]["source"], "user_custom")
            self.assertNotIn("offline-fixture", created.get_data(as_text=True))
            reused = self.client.post("/api/profiles", json={
                **self.fields(display_name="又一个配置"), "test_id": tested["test_id"]})
            self.assertEqual(reused.get_json()["error_code"], "CONNECTION_TEST_REQUIRED")
            profile_id = created.get_json()["profile"]["profile_id"]
            untested_edit = self.client.put(f"/api/profiles/{profile_id}", json=self.fields(
                display_name="改名"))
            self.assertEqual(untested_edit.get_json()["error_code"], "CONNECTION_TEST_REQUIRED")

    def test_unsupported_models_endpoint_can_use_explicit_chat(self):
        with patch.dict(os.environ, {"SCHOOL_LLM_API_KEY": "offline-fixture"}):
            failed = self.client.post("/api/profiles/test", json={
                **self.fields(model="broken"), "method": "models", "confirm_network": True})
            self.assertEqual(failed.get_json()["error_code"], "HTTP_404")
            self.assertEqual(self.gateway.chat_calls, 0)
            fallback = self.client.post("/api/profiles/test", json={
                **self.fields(model="broken"), "method": "chat", "confirm_network": True})
            self.assertEqual(fallback.status_code, 200)
            self.assertEqual(self.gateway.chat_calls, 1)

    def test_duplicate_update_copy_edit_and_soft_delete(self):
        first = self.client.post("/api/profiles", json=self.fields(
            provider_kind="local", secret_env="", base_url="http://localhost:11434/v1"))
        self.assertEqual(first.status_code, 201)
        first_id = first.get_json()["profile"]["profile_id"]
        second_fields = self.fields(provider_kind="local", secret_env="",
                                    base_url="http://localhost:11434/v1", model="second-model")
        collision = self.client.post("/api/profiles", json=second_fields)
        self.assertEqual(collision.status_code, 409)
        self.assertEqual(collision.get_json()["reason"], "SAME_DISPLAY_NAME")
        self.assertEqual(collision.get_json()["allowed_actions"], ["update", "copy", "cancel"])
        updated = self.client.post("/api/profiles", json={
            **second_fields, "conflict_action": "update", "conflict_profile_id": first_id})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["profile"]["profile_id"], first_id)
        duplicate = self.client.post("/api/profiles", json=second_fields)
        self.assertEqual(duplicate.get_json()["reason"], "SAME_ENDPOINT_MODEL")
        copied = self.client.post("/api/profiles", json={
            **second_fields, "conflict_action": "copy"})
        self.assertEqual(copied.status_code, 201)
        copy_id = copied.get_json()["profile"]["profile_id"]
        self.assertIn("副本", copied.get_json()["profile"]["display_name"])
        details = self.client.get(f"/api/profiles/{copy_id}").get_json()
        self.assertEqual(details["fields"]["secret_env"], "")
        self.assertNotIn("api_key", str(details))
        edit = self.client.put(f"/api/profiles/{copy_id}", json={
            **second_fields, "display_name": "编辑后副本", "model": "third-model"})
        self.assertEqual(edit.status_code, 200)
        removed = self.client.delete(f"/api/profiles/{copy_id}")
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(self.client.get(f"/api/profiles/{copy_id}").status_code, 404)
        self.assertFalse((self.store_dir / f"{copy_id}.json").exists())
        self.assertEqual(len(list((self.store_dir / "archive").glob(f"{copy_id}-*.json"))), 1)
        self.assertEqual(self.client.delete("/api/profiles/qwen-plus-experimental").status_code, 403)

    def test_builtin_collision_only_allows_copy_or_cancel(self):
        builtin = next(p for p in _builtin_profiles() if p.provider_id == "qwen")
        by_name = self.fields(provider_kind="local", secret_env="",
                              display_name=builtin.display_name,
                              base_url="http://localhost:11434/v1")
        conflict = self.client.post("/api/profiles", json=by_name)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.get_json()["existing"]["source"], "built_in")
        self.assertEqual(conflict.get_json()["allowed_actions"], ["copy", "cancel"])
        denied = self.client.post("/api/profiles", json={**by_name,
            "conflict_action": "update", "conflict_profile_id": builtin.profile_id})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.get_json()["error_code"], "PROFILE_NOT_EDITABLE")
        copy = self.client.post("/api/profiles", json={**by_name, "conflict_action": "copy"})
        self.assertEqual(copy.status_code, 201)
        self.assertEqual(copy.get_json()["profile"]["source"], "user_custom")
        self.assertIn("副本", copy.get_json()["profile"]["display_name"])
        mixed = self.client.post("/api/profiles", json=by_name)
        self.assertEqual(mixed.status_code, 409)
        self.assertEqual(mixed.get_json()["existing"]["source"], "built_in")
        self.assertEqual(mixed.get_json()["allowed_actions"], ["copy", "cancel"])

        by_endpoint = self.fields(display_name="另一个 Qwen", provider_id=builtin.provider_id,
                                  base_url=builtin.base_url, model=builtin.model,
                                  secret_env=builtin.secret_env)
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "offline-fixture"}):
            tested = self.client.post("/api/profiles/test", json={**by_endpoint,
                "method": "models", "confirm_network": True}).get_json()
            endpoint_collision = self.client.post("/api/profiles", json={**by_endpoint,
                "test_id": tested["test_id"]})
            self.assertEqual(endpoint_collision.status_code, 409)
            self.assertEqual(endpoint_collision.get_json()["reason"], "SAME_ENDPOINT_MODEL")
            self.assertEqual(endpoint_collision.get_json()["allowed_actions"], ["copy", "cancel"])
        self.assertEqual(self.client.put(f"/api/profiles/{builtin.profile_id}", json=by_name).status_code, 403)

        mock_name = self.fields(provider_kind="local", secret_env="",
                                base_url="http://localhost:11434/v1",
                                display_name="Mock 离线演示")
        mock_collision = self.client.post("/api/profiles", json=mock_name)
        self.assertEqual(mock_collision.status_code, 409)
        self.assertEqual(mock_collision.get_json()["existing"]["profile_id"], "mock-demo")
        self.assertEqual(mock_collision.get_json()["allowed_actions"], ["copy", "cancel"])

    def test_adapter_lists_all_models_without_changing_old_default(self):
        class Client:
            def __init__(self):
                self.models = SimpleNamespace(list=lambda: SimpleNamespace(data=[
                    SimpleNamespace(id="qwen-plus", model_extra={}),
                    SimpleNamespace(id="other-model", model_extra={}),
                ]))

            def close(self):
                pass

        profile = next(p for p in _builtin_profiles() if p.provider_id == "qwen")
        runtime = ProfileRegistry([profile]).snapshot(profile.profile_id, {"DASHSCOPE_API_KEY": "offline-fixture"})
        adapter = OpenAICompatibleAdapter(client_factory=lambda _runtime, _remaining: Client())
        self.assertEqual([x["id"] for x in adapter.list_models(runtime)], ["qwen-plus"])
        self.assertEqual([x["id"] for x in adapter.list_models(runtime, all_models=True)],
                         ["qwen-plus", "other-model"])

    def test_simple_advanced_controls_and_builtin_are_not_editable(self):
        html = self.client.get("/").get_data(as_text=True)
        script = self.client.get("/assets/app.js").get_data(as_text=True)
        for marker in ('id="provider-preset"', 'id="secret-status"',
                       'id="query-models"', 'id="test-profile"',
                       'id="advanced-settings"', 'id="conflict-panel"',
                       'id="edit-profile"', 'id="delete-profile"'):
            self.assertIn(marker, html)
        self.assertIn("selectPreset", script)
        self.assertIn("PROFILE_CONFLICT", str(self.client.post("/api/profiles", json={
            **self.fields(provider_kind="local", secret_env="",
                          base_url="http://localhost:11434/v1", model="x",
                          display_name="Qwen Plus（实验）")}).get_json()))
        self.assertEqual(self.client.get("/api/profiles/qwen-plus-experimental").status_code, 404)
        self.assertEqual(self.client.put("/api/profiles/qwen-plus-experimental", json=self.fields(
            provider_kind="local", secret_env="")).status_code, 403)


if __name__ == "__main__":
    unittest.main()
