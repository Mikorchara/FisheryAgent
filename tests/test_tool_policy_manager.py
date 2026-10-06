"""Offline UI policy storage: fake data, temp paths, no real credential access."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from fishery_ai.credentials import CredentialStore
from fishery_ai.domain import DiagnosisService
from fishery_ai.model_gateway import ModelToolCall
from fishery_ai.telemetry import CurrentSnapshotStore, CurrentWaterQualityReader
from fishery_ai.tools.policy import UserToolPolicyStore, ToolPolicyError, load_tool_policies
from fishery_ai.tools import ToolRegistry, ToolExecutor
from fishery_ai.tools.catalog import tool_catalog
from fishery_ai.web import create_app

NAME = "get_current_water_quality"


class ToolPolicyManagerTests(unittest.TestCase):
    def setUp(self):
        for target in ("socket.socket.connect", "socket.socket.connect_ex", "socket.socket.sendto",
                       "socket.create_connection", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("offline only"))
            guard.start(); self.addCleanup(guard.stop)
        directory = TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.reader = CurrentWaterQualityReader(CurrentSnapshotStore(), stale_after_s=300)
        self.registry = ToolRegistry(self.reader, DiagnosisService())
        self.store = UserToolPolicyStore(self.root / "policies", self.registry)
        self.factory = Mock(side_effect=AssertionError("no provider calls"))
        self.app = self.make_app()
        self.client = self.app.test_client()
        csrf = self.client.get("/api/credential-session").get_json()["csrf_token"]
        self.headers = {"Origin": "http://localhost", "X-CSRF-Token": csrf}

    def make_app(self):
        return create_app(trace_path=self.root / "trace.jsonl", custom_profiles_dir=self.root / "profiles",
            capability_evidence_dir=self.root / "evidence", manual_experiments_dir=self.root / "experiments",
            scenario_templates_dir=self.root / "scenarios", tool_policy_dir=self.root / "policies",
            credential_store=CredentialStore(process_env={}), real_gateway_factory=self.factory)

    def selection(self, analysis=(), assistant=(NAME,)):
        return {"schema_version":1, "modes": {"analysis":{"selected_tools":list(analysis)},
            "assistant":{"selected_tools":list(assistant)}}}

    def test_catalog_two_real_and_three_disabled_placeholders(self):
        catalog = tool_catalog(self.registry)
        self.assertEqual(len(catalog), 5)
        self.assertEqual([i["name"] for i in catalog if i["executable"]], [NAME, "score_current_water_quality"])
        for item in catalog[2:]:
            self.assertTrue(item["dev_only"])
            self.assertFalse(item["registered"])
            self.assertFalse(item["executable"])
        self.assertEqual(self.registry.registered_names(), (NAME, "score_current_water_quality"))

    def test_absent_override_loads_builtin_without_creating_file(self):
        self.assertFalse(self.store.path.exists())
        self.assertEqual(self.store.public()["source"], "BUILTIN_DEFAULT")
        self.assertEqual(self.store.effective()["analysis"].exposed_tools, ())
        self.assertEqual(self.store.effective()["assistant"].exposed_tools, (NAME,))

    def test_save_and_restart_preserve_both_selections(self):
        self.store.save(self.selection((NAME,), ()))
        reloaded = UserToolPolicyStore(self.store.directory, self.registry)
        self.assertEqual(reloaded.load(), self.selection((NAME,), ()))
        self.assertEqual(reloaded.public()["source"], "USER_OVERRIDE")
        self.assertEqual(reloaded.effective()["analysis"].exposed_tools, (NAME,))
        self.assertEqual(reloaded.effective()["assistant"].exposed_tools, ())

    def test_reset_removes_only_override_and_restores_defaults(self):
        self.store.save(self.selection((NAME,), ()))
        unrelated=self.store.directory / "keep.txt"; unrelated.write_text("keep")
        self.store.reset()
        self.assertFalse(self.store.path.exists())
        self.assertEqual(unrelated.read_text(), "keep")
        self.assertEqual(self.store.load(), self.selection())

    def test_unknown_and_placeholder_cannot_enter_policy(self):
        for name in ("unknown", "testTool_1", "testTool_2", "testTool_3"):
            with self.subTest(name=name), self.assertRaises(ToolPolicyError) as error:
                self.store.save(self.selection(assistant=(name,)))
            self.assertEqual(error.exception.code, "UNKNOWN_POLICY_TOOL")
        self.assertFalse(self.store.path.exists())

    def test_schema_extra_fields_duplicate_and_secret_field_rejected(self):
        for data in ({**self.selection(), "path":"arbitrary"}, {**self.selection(), "secret":"fictional"},
                     {**self.selection(), "schema_version":2}, self.selection(assistant=(NAME,NAME)),
                     {"schema_version":1,"modes":{"assistant":{"selected_tools":[NAME]}}}):
            with self.assertRaises(ToolPolicyError): self.store.save(data)

    def test_corrupt_override_fails_closed_not_builtin_fallback(self):
        self.store.directory.mkdir(); self.store.path.write_text("not JSON")
        with self.assertRaises(ToolPolicyError): self.store.effective()
        with self.assertRaises(ToolPolicyError): self.make_app()

    def test_unknown_override_at_startup_fails_closed(self):
        self.store.directory.mkdir(); self.store.path.write_text(json.dumps(self.selection(assistant=("testTool_1",))))
        with self.assertRaises(ToolPolicyError): self.make_app()
        self.factory.assert_not_called()

    def test_atomic_replace_failure_preserves_original_and_cleans_staging(self):
        self.store.save(self.selection())
        original=self.store.path.read_bytes()
        with patch("fishery_ai.tools.policy.os.replace", side_effect=OSError("fictional path error")):
            with self.assertRaises(ToolPolicyError) as error: self.store.save(self.selection(assistant=()))
        self.assertEqual(str(error.exception), "TOOL_POLICY_STORAGE_ERROR")
        self.assertEqual(self.store.path.read_bytes(), original)
        self.assertEqual(list(self.store.directory.glob("*.tmp")), [])

    def test_hardlinked_override_rejected_without_reading_target(self):
        self.store.directory.mkdir()
        target=self.root / "unrelated.json"; target.write_text(json.dumps(self.selection()))
        os.link(target,self.store.path)
        with patch.object(Path,"read_text",side_effect=AssertionError("unsafe path cannot be read")):
            with self.assertRaises(ToolPolicyError): self.store.load()
            with self.assertRaises(ToolPolicyError): self.store.save(self.selection(assistant=()))
            with self.assertRaises(ToolPolicyError): self.store.reset()
        self.assertTrue(target.exists())

    def test_effective_policy_is_immutable_per_request_new_resolve_hot_loads(self):
        old=self.store.effective()["assistant"]
        self.store.save(self.selection(assistant=()))
        self.assertEqual(old.exposed_tools, (NAME,))
        self.assertEqual(self.store.effective()["assistant"].exposed_tools, ())

    def test_catalog_mutation_cannot_add_handler_or_grant_execution(self):
        catalog=tool_catalog(self.registry); catalog[2]["executable"]=True
        result=ToolExecutor(self.registry).execute(ModelToolCall("c1", "testTool_1", "{}"))
        self.assertEqual(result.error_code.value,"UNKNOWN_TOOL")
        self.assertEqual(self.registry.registered_names(),(NAME, "score_current_water_quality"))

    def test_web_returns_catalog_and_no_profile_or_secret(self):
        response=self.client.get("/api/tool-policies")
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.get_json()["catalog"]),5)
        self.assertNotIn("credential",response.get_data(as_text=True).lower())
        self.assertNotIn("path",response.get_json())
        self.factory.assert_not_called()

    def test_web_save_refresh_and_restart_persist(self):
        saved=self.client.put("/api/tool-policies",json=self.selection((NAME,),()),headers=self.headers)
        self.assertEqual(saved.status_code,200)
        self.assertEqual(self.client.get("/api/tool-policies").get_json()["policy"]["modes"],self.selection((NAME,),())["modes"])
        client=self.make_app().test_client()
        self.assertEqual(client.get("/api/tool-policies").get_json()["policy"]["source"],"USER_OVERRIDE")

    def test_web_reset_requires_json_and_reverts_builtin(self):
        self.client.put("/api/tool-policies",json=self.selection(assistant=()),headers=self.headers)
        response=self.client.delete("/api/tool-policies",json={},headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.get_json()["policy"]["source"],"BUILTIN_DEFAULT")
        self.assertEqual(self.client.delete("/api/tool-policies",json={"path":"x"},headers=self.headers).status_code,400)

    def test_web_host_origin_csrf_guards_and_no_cors(self):
        self.assertEqual(self.client.put("/api/tool-policies",json=self.selection()).status_code,403)
        self.assertEqual(self.client.put("/api/tool-policies",json=self.selection(),headers={**self.headers,"Origin":"http://evil.invalid"}).status_code,403)
        self.assertEqual(self.client.get("/api/tool-policies",headers={"Host":"evil.invalid"}).status_code,403)
        self.assertNotIn("Access-Control-Allow-Origin",self.client.get("/api/tool-policies").headers)

    def test_web_cannot_choose_path_or_placeholder_or_modify_package(self):
        builtin=load_tool_policies()
        for data in (self.selection(assistant=("testTool_1",)),{**self.selection(),"path":"private.env"}):
            response=self.client.put("/api/tool-policies",json=data,headers=self.headers)
            self.assertEqual(response.status_code,400)
        self.assertEqual(load_tool_policies(),builtin)
        self.assertFalse(self.store.path.exists())

    def test_disabled_assistant_tool_has_no_definition_and_does_not_read_snapshot(self):
        self.store.save(self.selection(assistant=()))
        control=self.client.post("/api/requests",json={},headers=self.headers).get_json()
        with patch.object(self.app.extensions["fishery_current_water_quality_reader"], "query",
                          side_effect=AssertionError("disabled Tool cannot read")):
            response=self.client.post("/api/tool-conversation",json={"target":"mock","question":"现在水质怎么样？",
                "request_id":control["request_id"],"control_token":control["control_token"]},headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertIsNone(response.get_json()["result"]["tool_result"])
        self.assertIn("未允许",response.get_json()["result"]["generated_text"])

    def test_page_title_manager_and_coming_soon_structure(self):
        html=self.client.get("/").get_data(as_text=True)
        self.assertIn('<h2>Analysis Model</h2>',html)
        self.assertNotIn("基础模型配置",html)
        for identifier in ("open-tool-manager","tool-manager","tool-policy-analysis","tool-policy-assistant","assistant-mode-entry"):
            self.assertIn('id="'+identifier+'"',html)
        self.assertIn("Coming Soon",html)


if __name__ == "__main__": unittest.main()
