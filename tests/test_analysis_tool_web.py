"""Formal Analysis routes consume saved policy; all providers are offline fixtures."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from fishery_ai.credentials import CredentialStore
from fishery_ai.model_gateway import ModelResponse, ModelToolCall
from fishery_ai.presets import preset_profiles
from fishery_ai.web import create_app
from test_tool_conversation import RecordingGateway
from test_analysis_tools import FINAL, NOW, NAME


class AnalysisToolWebTests(unittest.TestCase):
    def setUp(self):
        for target in ("socket.socket.connect", "socket.socket.connect_ex", "socket.socket.sendto",
                       "socket.create_connection", "socket.getaddrinfo"):
            guard=patch(target,side_effect=AssertionError("offline Web tests"));guard.start();self.addCleanup(guard.stop)
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.gateway=RecordingGateway(ModelResponse(None,tool_calls=(ModelToolCall("web-call",NAME,"{}"),)),
                                      ModelResponse(FINAL,finish_reason="stop"))
        self.factory=Mock(return_value=self.gateway)
        self.app=create_app(trace_path=self.root/"trace.jsonl",custom_profiles_dir=self.root/"profiles",
            capability_evidence_dir=self.root/"evidence",manual_experiments_dir=self.root/"experiments",
            scenario_templates_dir=self.root/"templates",tool_policy_dir=self.root/"policies",
            credential_store=CredentialStore(process_env={"DEEPSEEK_API_KEY":"fictional-only"}),
            scenario_clock=lambda:NOW,real_gateway_factory=self.factory)
        self.client=self.app.test_client()
        csrf=self.client.get("/api/credential-session").get_json()["csrf_token"]
        self.headers={"Origin":"http://localhost","X-CSRF-Token":csrf}
        self.local=next(p for p in preset_profiles() if p.model=="qwen3.5:4b" and p.preset_variant=="off")
        self.policy(True)
        response=self.client.post("/api/water-quality/apply",json={"template_id":"low_oxygen"},headers=self.headers)
        self.assertEqual(response.status_code,200)

    def policy(self,on):
        response=self.client.put("/api/tool-policies",json={"schema_version":1,"modes":{
            "analysis":{"selected_tools":[NAME] if on else []},"assistant":{"selected_tools":[NAME]}}},headers=self.headers)
        self.assertEqual(response.status_code,200)

    def analyze(self,profile=None,path="/api/analyze"):
        return self.client.post(path,json={"profile_id":profile or self.local.profile_id,"question":"现在水质怎么样？",
            "confirm_network":True},headers=self.headers)

    def test_saved_analysis_policy_reaches_shared_executor_and_activity(self):
        response=self.analyze();self.assertEqual(response.status_code,200)
        result=response.get_json()["result"]
        self.assertEqual(result["tool_activity"]["result_status"],"OK")
        self.assertEqual(result["tool_activity"]["request_2"]["outcome"],"final_answer")
        self.assertTrue(result["tool_activity"]["called"])
        self.assertIn("OXYGEN_CRITICAL_LOW",[f["code"] for f in result["rule_results"]])
        self.assertEqual(self.gateway.requests[1].tool_choice,"none")
        self.assertFalse((self.root/"evidence").exists())

    def test_streaming_policy_enabled_rejected_before_gateway_or_snapshot_read(self):
        before=self.app.extensions["fishery_snapshot_store"].get_current()
        response=self.analyze(path="/api/analyze/stream")
        self.assertEqual(response.get_json()["error_code"],"TOOL_STREAMING_NOT_IMPLEMENTED")
        self.factory.assert_not_called()
        self.assertIs(self.app.extensions["fishery_snapshot_store"].get_current(),before)

    def test_newly_published_deepseek_fixed_contract_can_complete_offline(self):
        profile=next(p for p in preset_profiles() if p.model=="deepseek-flash" and p.preset_variant=="off")
        response=self.analyze(profile.profile_id)
        self.assertIsNone(response.get_json()["result"]["error_code"])
        self.assertEqual(len(self.gateway.requests),2)
        self.assertNotIn("fictional-only",response.get_data(as_text=True))

    def test_policy_disabled_normal_and_streaming_are_unchanged(self):
        self.policy(False)
        self.factory.return_value=RecordingGateway(ModelResponse(FINAL,finish_reason="stop"))
        response=self.analyze();self.assertEqual(response.status_code,200)
        self.assertFalse(response.get_json()["result"]["tool_activity"]["called"])
        self.assertEqual(self.factory.return_value.requests[0].tools,())
        self.factory.return_value=RecordingGateway(ModelResponse(FINAL,finish_reason="stop"))
        response=self.analyze(path="/api/analyze/stream")
        self.assertIn("event: completed",response.get_data(as_text=True))

    def test_panel_is_in_formal_result_area_not_configuration(self):
        html=self.client.get("/").get_data(as_text=True)
        self.assertGreater(html.index('id="analysis-tool-activity"'),html.index('<main class="results"'))
        self.assertIn("Tool Activity · 工具调用记录",html)
        self.assertNotIn('id="analysis-tool-activity" open',html)

    def test_enabled_analysis_policy_captured_once_for_both_requests(self):
        original=self.gateway.complete
        def complete(request,runtime):
            response=original(request,runtime)
            if len(self.gateway.requests)==1:
                store=self.app.extensions["fishery_tool_policy_store"]
                store.save({"schema_version":1,"modes":{"analysis":{"selected_tools":[]},"assistant":{"selected_tools":[]}}})
            return response
        self.gateway.complete=complete
        response=self.analyze();self.assertEqual(response.status_code,200)
        self.assertEqual(len(self.gateway.requests),2)
        self.assertEqual(response.get_json()["result"]["tool_activity"]["allowed_tools"],[NAME])

    def test_score_tool_policy_reaches_normal_analysis_and_activity(self):
        name="score_current_water_quality"
        response=self.client.put("/api/tool-policies",json={"schema_version":1,"modes":{
            "analysis":{"selected_tools":[name]},"assistant":{"selected_tools":[NAME]}}},headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.factory.return_value=RecordingGateway(ModelResponse(None,tool_calls=(ModelToolCall("score",name,"{}"),)),
                                                   ModelResponse(FINAL,finish_reason="stop"))
        result=self.analyze().get_json()["result"]
        self.assertEqual(result["tool_activity"]["tool_name"],name)
        self.assertEqual(result["tool_activity"]["tool_result"]["score"],81.3)
        self.assertEqual(result["tool_activity"]["result_status"],"OK")
        self.assertTrue(result["structured_parse_ok"])


if __name__ == "__main__": unittest.main()
