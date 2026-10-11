"""Offline maintainer qualification; network blocked and credentials fictional."""

from dataclasses import replace
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import runpy
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch, Mock

from fishery_ai.capability_store import CapabilityStore
from fishery_ai.contracts import Usage, UsageSource
from fishery_ai.credentials import CredentialStore
from fishery_ai.domain import DiagnosisService
from fishery_ai.execution import RequestHandle, request_scope
from fishery_ai.model_gateway import ModelResponse, ModelToolCall, MockGateway, ProfileRegistry, GatewayError
from fishery_ai.model_options import Support, ModelCapabilities
from fishery_ai.observability import JsonlTraceSink
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.preset_tool_qualification import qualify_preset_tools
from fishery_ai.presets import preset_profiles, _catalog
from fishery_ai.telemetry import CurrentSnapshotStore, CurrentWaterQualityReader
from fishery_ai.tools import ToolRegistry

NAME="get_current_water_quality"


class CaptureGateway(MockGateway):
    def __init__(self,**kwargs):
        super().__init__(**kwargs)
        self.requests=[]

    def complete(self,request,runtime):
        self.requests.append((request,runtime))
        return super().complete(request,runtime)


from tests.support.paths import PROJECT_ROOT
class PresetToolQualificationTests(unittest.TestCase):
    def setUp(self):
        for target in ("socket.socket.connect","socket.socket.connect_ex","socket.socket.sendto",
                       "socket.create_connection","socket.getaddrinfo"):
            guard=patch(target,side_effect=AssertionError("qualification tests are offline"))
            guard.start(); self.addCleanup(guard.stop)
        temp=TemporaryDirectory(); self.addCleanup(temp.cleanup); self.root=Path(temp.name)
        self.credentials=CredentialStore(process_env={"DASHSCOPE_API_KEY":"fictional-dashscope",
                                                     "DEEPSEEK_API_KEY":"fictional-deepseek"})
        self.profiles=[p for p in preset_profiles() if p.preset_variant=="off"]
        self.profile=self.profiles[0]
        self.runtime=ProfileRegistry([self.profile],self.credentials).snapshot(self.profile.profile_id)
        self.store=CurrentSnapshotStore()
        self.registry=ToolRegistry(CurrentWaterQualityReader(self.store,stale_after_s=300),DiagnosisService())
        self.traces=JsonlTraceSink(self.root / "trace.jsonl")
        self.usage=Usage(input_tokens=10,output_tokens=2,total_tokens=12,source=UsageSource.PROVIDER)

    def responses(self, first=None, second=None, concept=None):
        return (first or ModelResponse(None,self.usage,tool_calls=(ModelToolCall("valid-call",NAME,"{}"),),finish_reason="tool_calls"),
                second or ModelResponse("没有当前水质数据。",self.usage,finish_reason="stop"),
                concept or ModelResponse("溶氧是水中溶解的氧气。",self.usage,finish_reason="stop"))

    def run_qualification(self, responses=None, profile=None):
        profile=profile or self.profile
        runtime=ProfileRegistry([profile],self.credentials).snapshot(profile.profile_id)
        gateway=CaptureGateway(responses=responses or self.responses())
        return qualify_preset_tools(gateway,profile,runtime,self.registry,self.traces),gateway

    def test_each_exact_preset_qualifies_offline_without_changing_contract(self):
        before=_catalog()
        for profile in self.profiles:
            result,gateway=self.run_qualification(profile=profile)
            self.assertEqual(result["verdict"],"SUPPORTED")
            self.assertEqual(result["model_requests"],3)
            self.assertEqual(result["tool_result_status"],"NO_DATA")
            self.assertTrue(result["concept_question"]["no_tool"])
            self.assertEqual(len(gateway.calls),3)
        self.assertEqual(_catalog(),before)

    def test_tool_round_trip_has_filtered_schema_ids_none_then_concept_auto(self):
        result,gateway=self.run_qualification()
        requests=[call[0] for call in gateway.requests]
        self.assertEqual([d.name for d in requests[0].tools],[NAME])
        self.assertEqual([m.role for m in requests[0].messages],["system","user"])
        self.assertNotIn("dissolved_oxygen",requests[0].messages[1].content)
        self.assertEqual(requests[1].messages[-2].tool_calls[0].id,"valid-call")
        self.assertEqual(requests[1].messages[-1].tool_call_id,"valid-call")
        self.assertEqual(json.loads(requests[1].messages[-1].content)["status"],"NO_DATA")
        self.assertEqual(requests[1].tool_choice,"none")
        self.assertEqual(requests[2].tool_choice,"auto")
        self.assertIn("什么是溶氧？",requests[2].messages[-1].content)
        self.assertIn("一两句话",requests[2].messages[-1].content)
        self.assertTrue(result["arguments_empty_object"])

    def test_diagnostic_authorization_budget_fixed_protocol_retry_zero(self):
        for profile in self.profiles:
            _,gateway=self.run_qualification(profile=profile)
            for request,runtime in gateway.requests:
                self.assertEqual(runtime.max_retries,0)
                self.assertEqual(runtime.default_generation.max_output_tokens,192)
                self.assertEqual(runtime.default_reasoning,profile.default_reasoning)
                self.assertIs(runtime.preset_protocol_spec,profile.preset_protocol_spec)
                wire=OpenAICompatibleAdapter._kwargs(request,runtime,stream=False)
                self.assertNotIn("stream",wire)
                self.assertEqual(wire[profile.preset_protocol_spec.max_output_tokens_field],384 if request.generation.max_output_tokens else 192)
        self.assertEqual(self.runtime.default_generation.max_output_tokens,None)

    def test_missing_secret_before_model_or_reader(self):
        runtime=ProfileRegistry([self.profile],CredentialStore(process_env={})).snapshot(self.profile.profile_id)
        gateway=Mock()
        with self.assertRaises(GatewayError) as error:
            qualify_preset_tools(gateway,self.profile,runtime,self.registry,self.traces)
        self.assertEqual(error.exception.code,"SECRET_MISSING")
        gateway.complete.assert_not_called()

    def test_mismatched_identity_or_variant_rejected(self):
        for runtime in (replace(self.runtime,model="other-model"),replace(self.runtime,base_url="https://other.invalid"),
                        replace(self.runtime,profile_id="other")):
            with self.assertRaises(GatewayError):
                qualify_preset_tools(Mock(),self.profile,runtime,self.registry,self.traces)
        on=next(p for p in preset_profiles() if p.model==self.profile.model and p.preset_variant=="on")
        with self.assertRaises(GatewayError):
            qualify_preset_tools(Mock(),on,ProfileRegistry([on],self.credentials).snapshot(on.profile_id),self.registry,self.traces)

    def test_no_first_tool_is_unknown_and_no_concept_exploration(self):
        result,gateway=self.run_qualification(self.responses(first=ModelResponse("直接猜测",finish_reason="stop")))
        self.assertEqual(result["verdict"],"UNKNOWN")
        self.assertEqual(result["model_requests"],1)
        self.assertEqual(result["concept_question"]["outcome"],"not_started")

    def test_wrong_tool_arguments_unknown_and_no_followup(self):
        for name,args in (("shell","{}"),(NAME,'{"extra":1}')):
            result,gateway=self.run_qualification(self.responses(first=ModelResponse(None,
                tool_calls=(ModelToolCall("c1",name,args),),finish_reason="tool_calls")))
            self.assertEqual(result["verdict"],"UNKNOWN")
            self.assertEqual(result["model_requests"],1)

    def test_second_tool_call_and_truncated_final_cannot_publish(self):
        for response in (ModelResponse(None,tool_calls=(ModelToolCall("c2",NAME,"{}"),),finish_reason="tool_calls"),
                         ModelResponse("截断正文",finish_reason="length")):
            result,_=self.run_qualification(self.responses(second=response))
            self.assertEqual(result["verdict"],"UNKNOWN")
            self.assertEqual(result["model_requests"],2)

    def test_concept_tool_call_rejected_without_executor_or_request_four(self):
        class CountingReader:
            def __init__(self):self.count=0
            def query(self):self.count+=1;return None
        reader=CountingReader(); self.registry=ToolRegistry(reader,DiagnosisService())
        result,_=self.run_qualification(self.responses(concept=ModelResponse(None,
            tool_calls=(ModelToolCall("concept-call",NAME,"{}"),),finish_reason="tool_calls")))
        self.assertEqual(reader.count,1)
        self.assertEqual(result["model_requests"],3)
        self.assertEqual(result["verdict"],"UNKNOWN")
        self.assertEqual(result["error_code"],"CONCEPT_QUESTION_NOT_DIRECT")

    def test_deepseek_concept_length_stays_unknown_with_independent_budget(self):
        profile=next(p for p in self.profiles if p.model=="deepseek-flash")
        result,gateway=self.run_qualification(self.responses(concept=ModelResponse("截断解释",finish_reason="length")),profile)
        self.assertEqual(result["verdict"],"UNKNOWN")
        self.assertEqual(result["model_requests"],3)
        self.assertEqual(result["concept_question"]["finish_reason"],"length")
        self.assertEqual(result["concept_max_output_tokens"],384)
        self.assertEqual([request.generation.max_output_tokens for request,_ in gateway.requests],[None,None,384])
        self.assertTrue(all(runtime.default_generation.max_output_tokens==192 for _,runtime in gateway.requests))

    def test_network_unauthorized_rate_limit_errors_do_not_retry_or_publish(self):
        for code in ("CONNECT_TIMEOUT","HTTP_401","HTTP_429","TOOL_UNSUPPORTED"):
            gateway=Mock(complete=Mock(side_effect=GatewayError(code)))
            result=qualify_preset_tools(gateway,self.profile,self.runtime,self.registry,self.traces)
            self.assertEqual(result["verdict"],"UNKNOWN")
            self.assertEqual(result["model_requests"],1)
            self.assertEqual(gateway.complete.call_count,1)

    def test_returned_model_mismatch_unknown(self):
        result,_=self.run_qualification(self.responses(first=ModelResponse(None,
            tool_calls=(ModelToolCall("c1",NAME,"{}"),),returned_model="other",finish_reason="tool_calls")))
        self.assertEqual(result["error_code"],"MODEL_IDENTITY_MISMATCH")
        self.assertEqual(result["model_requests"],1)
        self.assertNotIn("other",json.dumps(result))

    def test_cancellation_prevents_concept_request(self):
        handle=RequestHandle();handle.start()
        gateway=MockGateway(responses=self.responses())
        original=gateway.complete
        def complete(request,runtime):
            response=original(request,runtime)
            if len(gateway.calls)==2:handle.cancel()
            return response
        gateway.complete=complete
        with request_scope(handle):
            result=qualify_preset_tools(gateway,self.profile,self.runtime,self.registry,self.traces)
        self.assertEqual(result["verdict"],"UNKNOWN")
        self.assertEqual(result["error_code"],"USER_CANCELLED")
        self.assertEqual(result["model_requests"],2)

    def test_three_usage_values_preserved_and_merged(self):
        result,_=self.run_qualification()
        self.assertEqual(result["usage"]["request_count"],3)
        self.assertEqual(result["usage"]["usage"]["total_tokens"],36)
        self.assertEqual(result["request_2_usage"]["total_tokens"],12)
        self.assertEqual(result["concept_question"]["usage"]["total_tokens"],12)

    def test_report_trace_has_no_secret_prompt_text_or_private_paths(self):
        result,_=self.run_qualification()
        text=json.dumps(result)+self.traces.path.read_text(encoding="utf-8")
        for forbidden in ("fictional-dashscope","fictional-deepseek",str(self.root),"什么是溶氧","没有当前水质数据"):
            self.assertNotIn(forbidden,text)

    def test_evidence_store_not_used_for_qualification(self):
        with patch.object(CapabilityStore,"apply",side_effect=AssertionError("no Managed Evidence")), \
             patch.object(CapabilityStore,"save_probe",side_effect=AssertionError("no Managed write")):
            result,_=self.run_qualification()
        self.assertEqual(result["verdict"],"SUPPORTED")

    def test_contract_tool_support_only_for_explicit_publications(self):
        templates={t["id"]:t for t in _catalog()["templates"]}
        for profile in preset_profiles():
            publication=templates[profile.preset_id]["maintenance"].get("tool_calling_qualification")
            if publication and publication.get("verdict")=="SUPPORTED":
                self.assertEqual(profile.capabilities.tool_calling,Support.SUPPORTED)
                self.assertTrue(publication["concept_question"]["no_tool"])
            else:
                self.assertEqual(profile.capabilities.tool_calling,Support.UNKNOWN)

    def test_three_actual_publications_preserve_other_modes(self):
        for template in _catalog()["templates"]:
            local = template["id"] in ("ollama-qwen35-4b-r1", "dashscope-qwen38-flash-r1", "deepseek-flash-r1")
            self.assertEqual(template["contract_version"], "1.0.2" if local else "1.0.1")
            self.assertEqual(template["capabilities"].get("tool_calling", "unknown"),
                             "supported" if local else "unknown")
            self.assertEqual({(v["thinking"], r) for v in template["variants"] for r in v["response_modes"]},
                             {("off", "normal"), ("off", "streaming"), ("on", "normal"), ("on", "streaming")})
            if local:
                publication = template["maintenance"]["tool_calling_qualification"]
                self.assertEqual(publication["identity"], template["identity"])
                self.assertIn(publication["validation_source"], ("MAINTAINER_PRESET_QUALIFICATION", "USER_RUN_MAINTAINER_PRESET_QUALIFICATION"))
                self.assertEqual(publication["model_requests"], 3)
                self.assertEqual(publication["qualified_variant"], "off")
                self.assertEqual(publication["tool_result_status"], "NO_DATA")
                self.assertEqual(publication["request_2"], "final_answer")
                self.assertTrue(publication["concept_question"]["no_tool"])
                self.assertEqual(template["capabilities"]["streaming_usage"], "unknown" if template["id"].startswith("ollama") else "supported")

    def test_published_support_is_not_inherited_or_overwritten_by_managed(self):
        profile = next(p for p in self.profiles if p.model == "qwen3.5:4b")
        evidence = CapabilityStore(self.root / "evidence")
        managed = replace(profile, access_mode="managed_custom", preset_id=None, preset_variant=None,
            preset_contract_version=None, preset_protocol_spec=None, preset_response_modes=())
        evidence.save_probe(managed, "tool_calling", Support.UNSUPPORTED, "2026-10-06T00:00:00Z", {})
        self.assertIs(evidence.apply(profile), profile)
        self.assertEqual(profile.capabilities.tool_calling, Support.SUPPORTED)
        other = replace(managed, model="qwen3.5:other", capabilities=ModelCapabilities(), capability_basis=None)
        self.assertEqual(evidence.apply(other).capabilities.tool_calling, Support.UNKNOWN)
        self.assertEqual(next(p for p in preset_profiles() if p.profile_id == profile.profile_id).capabilities.tool_calling,
                         Support.SUPPORTED)

    def test_cli_requires_confirmation_before_private_composition(self):
        script = PROJECT_ROOT / "scripts/qualification/qualify_preset_tools.py"
        cli = runpy.run_path(str(script))
        with patch.object(sys, "argv", [str(script), "--preset-id", self.profile.preset_id]), \
             patch.dict(cli["main"].__globals__, private_project_location=Mock(side_effect=AssertionError("no credentials"))), \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli["main"](), 2)
        self.assertEqual(output.getvalue().strip(), "NETWORK_CONFIRMATION_REQUIRED")

    def test_cli_uses_shared_private_composition_with_fictional_store_only(self):
        script = PROJECT_ROOT / "scripts/qualification/qualify_preset_tools.py"
        cli = runpy.run_path(str(script))
        (self.root / "pyproject.toml").write_text("# temporary workspace", encoding="utf-8")
        (self.root / ".env").write_text("DASHSCOPE_API_KEY=legacy-not-allowed\n", encoding="utf-8")
        location = Mock(env_path=self.root / "private/credentials/.env")
        path_factory = Mock(return_value=location)
        store_factory = Mock(return_value=self.credentials)
        gateway = CaptureGateway(responses=self.responses())
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            with patch.object(sys, "argv", [str(script), "--preset-id", self.profile.preset_id, "--confirm-network"]), \
                 patch.dict(cli["main"].__globals__, private_project_location=path_factory,
                            CredentialStore=store_factory, OpenAICompatibleAdapter=lambda: gateway), \
                 redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli["main"](), 0)
        finally:
            os.chdir(previous)
        path_factory.assert_called_once_with(self.root)
        store_factory.assert_called_once_with(location.env_path, private_location=location)
        self.assertEqual(len(gateway.requests), 3)
        self.assertEqual((self.root / ".env").read_text(encoding="utf-8"),
                         "DASHSCOPE_API_KEY=legacy-not-allowed\n")
        for forbidden in ("legacy-not-allowed", "fictional-dashscope", str(location.env_path)):
            self.assertNotIn(forbidden, output.getvalue())

    def test_managed_evidence_does_not_change_preset_or_other_model(self):
        profile=self.profile
        managed=replace(profile,access_mode="managed_custom",preset_id=None,preset_variant=None,
            preset_contract_version=None,preset_protocol_spec=None,preset_response_modes=())
        evidence=CapabilityStore(self.root / "evidence")
        before=profile.capabilities.tool_calling
        evidence.save_probe(managed,"tool_calling",Support.SUPPORTED,"2026-10-06T00:00:00Z",{})
        self.assertEqual(next(p for p in preset_profiles() if p.profile_id==profile.profile_id).capabilities.tool_calling,before)
        other=replace(managed,model="unpublished-exact-model",capabilities=replace(
            managed.capabilities,model_id="unpublished-exact-model",tool_calling=Support.UNKNOWN),capability_basis=None)
        self.assertEqual(evidence.apply(other).capabilities.tool_calling,Support.UNKNOWN)


if __name__=="__main__":unittest.main()
