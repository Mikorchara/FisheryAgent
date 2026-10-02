"""A3.0.2 grounding and custom Profile tests; external sockets are forbidden."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import os
import runpy
import socket
import unittest

from fishery_ai.contracts import Usage
from fishery_ai.knowledge import KnowledgeService
from fishery_ai.composition import RESOURCE_ROOT
from fishery_ai.model_gateway import ModelResponse
from fishery_ai.web import create_app


def _deny_network(*_args, **_kwargs):
    raise AssertionError("network is forbidden in grounding tests")


class GroundingAndProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profiles_dir = self.root / "profiles"
        self.trace_path = self.root / "traces.jsonl"
        for target in ("connect", "connect_ex", "sendto"):
            blocker = patch.object(socket.socket, target, _deny_network)
            blocker.start()
            self.addCleanup(blocker.stop)
        dns = patch.object(socket, "getaddrinfo", _deny_network)
        dns.start()
        self.addCleanup(dns.stop)

    def _app(self, gateway_factory=None):
        kwargs = {"trace_path": self.trace_path, "custom_profiles_dir": self.profiles_dir,
                  "capability_evidence_dir": self.root / "evidence"}
        if gateway_factory is not None:
            kwargs["real_gateway_factory"] = gateway_factory
        return create_app(**kwargs)

    @staticmethod
    def _profile(**overrides):
        data = {
            "display_name": "学校兼容接口", "provider_id": "school",
            "adapter_id": "openai_chat", "base_url": "https://example.invalid/v1",
            "model": "school-model", "secret_env": "SCHOOL_LLM_API_KEY",
            "provider_kind": "cloud",
        }
        data.update(overrides)
        return data

    def test_water_question_prioritizes_water_and_relationship_evidence(self):
        service = KnowledgeService(RESOURCE_ROOT.joinpath("knowledge/eel_knowledge.json"))
        query = ("当前水质情况怎么样？ 水温28 pH7.5 溶解氧2.2 "
                 "OXYGEN_CRITICAL_LOW 溶氧严重偏低 dissolved_oxygen_mg_l")
        results = service.search(query, intent_text="当前水质情况怎么样？")
        self.assertTrue(results)
        self.assertEqual(results[0].evidence_id, "wq_dissolved_oxygen")
        self.assertTrue(any(item.category == "relationships" for item in results))
        self.assertFalse(any(item.category == "disease" for item in results))

    def test_explicit_disease_intent_can_retrieve_disease_knowledge(self):
        service = KnowledgeService(RESOURCE_ROOT.joinpath("knowledge/eel_knowledge.json"))
        results = service.search("鳗鲡车轮虫病有哪些症状？", intent_text="鳗鲡车轮虫病有哪些症状？")
        self.assertTrue(any(item.category == "disease" for item in results))

    def test_low_oxygen_prompt_marks_evidence_as_background(self):
        requests = []

        class CaptureGateway:
            def complete(self, request, _runtime):
                requests.append(request)
                return ModelResponse(json.dumps({"inference": "溶氧已低于规则阈值。",
                                                 "recommendations": ["优先增氧并复测。"],
                                                 "uncertainty": ["缺少鱼体症状。"]},
                                                ensure_ascii=False), Usage())

        client = self._app(CaptureGateway).test_client()
        # The fake gateway is used through a real Profile; no external socket is opened.
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "offline-fixture"}):
            response = client.post("/api/analyze", json={
                "profile_id": "qwen-plus-experimental", "scenario": "low_oxygen",
                "question": "当前水质情况怎么样？", "confirm_network": True})
        self.assertEqual(response.status_code, 200)
        result = response.get_json()["result"]
        self.assertEqual([item["code"] for item in result["rule_results"]],
                         ["OXYGEN_CRITICAL_LOW"])
        self.assertFalse(any(item["category"] == "disease" for item in result["evidence"]))
        self.assertEqual(len(requests), 1)
        self.assertIn("RAG Evidence 仅是背景知识", requests[0].messages[0].content)
        self.assertIn("不得诊断具体疾病", requests[0].messages[0].content)
        self.assertIn("不得直接推荐具体药物", requests[0].messages[0].content)
        self.assertIn("OXYGEN_CRITICAL_LOW", requests[0].messages[1].content)

    def test_custom_profile_persists_reload_and_secret_is_only_reference(self):
        client = self._app().test_client()
        created = client.post("/api/profiles", json=self._profile(provider_kind="local"))
        self.assertEqual(created.status_code, 201)
        public = created.get_json()["profile"]
        self.assertEqual(public["source"], "user_custom")
        self.assertEqual(public["profile_status"], "custom")
        self.assertEqual(public["secret_env"], "SCHOOL_LLM_API_KEY")  # name only, never a value
        self.assertNotIn("api_key", public)
        files = list(self.profiles_dir.glob("custom-*.json"))
        self.assertEqual(len(files), 1)
        stored = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(stored["secret_env"], "SCHOOL_LLM_API_KEY")
        self.assertNotIn("api_key", stored)
        self.assertNotIn("capabilities", stored)
        reloaded = self._app().test_client().get("/api/config").get_json()["profiles"]
        self.assertEqual([p["profile_id"] for p in reloaded if p["source"] == "user_custom"],
                         [public["profile_id"]])
        with patch.dict(os.environ, {}, clear=True):
            response = client.post("/api/analyze", json={
                "profile_id": public["profile_id"], "scenario": "low_oxygen",
                "question": "当前水质情况怎么样？", "confirm_network": True})
        self.assertEqual(response.get_json()["error_code"], "SECRET_MISSING")
        self.assertFalse(self.trace_path.exists())

    def test_custom_profile_rejects_key_and_invalid_config(self):
        client = self._app().test_client()
        for payload in (self._profile(api_key="forbidden"),
                        self._profile(secret_env=""),
                        self._profile(secret_env="not-a-name"),
                        self._profile(base_url="file:///private"),
                        self._profile(adapter_id="generic_openai_chat")):
            with self.subTest(payload=sorted(payload)):
                response = client.post("/api/profiles", json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json()["error_code"], "INVALID_PROFILE")
        self.assertFalse(self.profiles_dir.exists())

    def test_profile_errors_identify_fields_without_echoing_input(self):
        client = self._app().test_client()
        cases = (
            (self._profile(secret_env=""), "secret_env", "REQUIRED"),
            (self._profile(provider_id="School"), "service_id", "INVALID_FORMAT"),
            (self._profile(base_url="file:///private"), "base_url", "INVALID_URL"),
            (self._profile(adapter_id="generic_openai_chat"), "service_id", "CONFLICT"),
            (self._profile(api_key="fixture-only"), "profile", "UNKNOWN_FIELD"),
        )
        for body, field, reason in cases:
            with self.subTest(field=field, reason=reason):
                response = client.post("/api/profiles", json=body)
                self.assertEqual(response.status_code, 400)
                data = response.get_json()
                self.assertEqual(data["field"], field)
                self.assertEqual(data["reason"], reason)
                self.assertTrue(data["message"])
                self.assertNotIn("fixture-only", response.get_data(as_text=True))

    def test_local_profile_can_omit_secret_reference(self):
        client = self._app().test_client()
        response = client.post("/api/profiles", json=self._profile(
            provider_kind="local", secret_env="", base_url="http://localhost:11434/v1"))
        self.assertEqual(response.status_code, 201)
        stored = json.loads(next(self.profiles_dir.glob("custom-*.json")).read_text(encoding="utf-8"))
        self.assertIsNone(stored["secret_env"])

    def test_utf8_record_preserves_non_gbk_model_text_and_usage(self):
        script = Path(__file__).resolve().parents[1] / "scripts/validate_qwen_grounding.py"
        writer = runpy.run_path(str(script))["write_record"]
        path = self.root / "record.json"
        writer(path, {"inference": "溶氧偏低；NO₃ 需要进一步检测。",
                      "usage": {"input_tokens": 12, "output_tokens": 7}})
        decoded = path.read_bytes().decode("utf-8")
        self.assertIn("NO₃", decoded)
        self.assertIn('"input_tokens": 12', decoded)
        self.assertNotIn("\\u2083", decoded)
        with self.assertRaises(FileExistsError):
            writer(path, {"inference": "不会覆盖"})

    def test_ui_has_facts_boundary_and_collapsible_sections(self):
        client = self._app().test_client()
        html = client.get("/").get_data(as_text=True)
        script = client.get("/assets/app.js").get_data(as_text=True)
        self.assertIn('id="custom-editor"', html)
        self.assertIn('class="panel raw-output"', html)
        profile_editor = html.split('id="custom-editor"', 1)[1].split('id="credential-manager"', 1)[0]
        self.assertNotIn('type="password"', profile_editor)
        self.assertIn('id="credential-value" type="password"', html)
        self.assertIn('document.createElement("details")', script)
        self.assertIn("Built-in Profiles", script)
        self.assertIn("User Custom Profiles", script)
        self.assertIn("认证必填", html)
        self.assertIn('id="custom-auth"', html)
        self.assertIn("只填写环境变量名", html)
        self.assertIn('id="provider-preset"', html)
        self.assertIn('id="advanced-settings"', html)
        self.assertIn("data.field", script)


if __name__ == "__main__":
    unittest.main()
