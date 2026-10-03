"""Offline OFF+Streaming evidence, probe and fixed contract checks."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import unittest

import test_execution
from fishery_ai.capability_probe import run_capability_probe
from fishery_ai.capability_store import CapabilityStore
from fishery_ai.credentials import CredentialStore
from fishery_ai.custom_profiles import CustomProfileStore
from fishery_ai.evidence_resolver import CapabilityEvidence, CapabilityIdentity, resolve_capabilities
from fishery_ai.model_gateway import GatewayError, ModelEvent, ProfileRegistry, effective_runtime_defaults
from fishery_ai.model_options import (CapabilitySource, GenerationOptions, ReasoningMode,
    ReasoningOptions, Support, OptionValidationError, validate_options)
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.web import create_app

FIELD = "thinking_off_streaming_combination"

class OffStreamingTests(unittest.TestCase):
    def setUp(self):
        test_execution.ExecutionTests.setUp(self)
        temp=TemporaryDirectory(); self.addCleanup(temp.cleanup); self.root=Path(temp.name)
        self.credentials=CredentialStore(self.root/'fictional.env',process_env={})
        self.profile=CustomProfileStore(self.root/'profiles').create({
            "display_name":"OFF streaming test", "service_id":"dashscope", "model_family":"qwen", "provider_kind":"local",
            "adapter_id":"openai_chat", "base_url":"http://localhost:8812/v1/", "model":"exact-model",
            "secret_env":""})
        self.store=CapabilityStore(self.root/'evidence')
        self.profile=self.store.save_probe(self.profile,"streaming",Support.SUPPORTED,"2026-10-04")
        self.profile=self.store.save_probe(self.profile,"reasoning_off",Support.SUPPORTED,"2026-10-04")
        self.calls=[]

    def client(self,events=None,error=None):
        outer=self
        class Fake:
            def stream(self,request,runtime):
                outer.calls.append((request,runtime))
                if error: raise GatewayError(error)
                yield from (events if events is not None else [ModelEvent(delta="OK"),ModelEvent(finish_reason="stop")])
        return create_app(trace_path=self.root/'trace.jsonl',custom_profiles_dir=self.root/'profiles',
            capability_evidence_dir=self.root/'evidence',credential_store=self.credentials,
            real_gateway_factory=lambda:Fake()).test_client()

    def probe(self,client):
        return client.post(f"/api/profiles/{self.profile.profile_id}/probe",
            json={"capability":FIELD,"confirm_network":True})

    def test_independent_unknown_gate_and_safe_default(self):
        caps=self.profile.capabilities
        self.assertEqual(getattr(caps,FIELD),Support.UNKNOWN)
        with self.assertRaises(OptionValidationError) as error:
            validate_options(GenerationOptions(),ReasoningOptions(ReasoningMode.OFF),caps,streaming=True)
        self.assertEqual((error.exception.code,error.exception.option),("OPTION_UNKNOWN",FIELD))
        p=replace(self.profile,default_reasoning=ReasoningOptions(ReasoningMode.OFF),default_response_mode="streaming")
        reason,response,notices=effective_runtime_defaults(p)
        self.assertEqual((reason.mode,response),(ReasoningMode.OFF,"normal"))
        self.assertIn("COMBINATION_DEFAULT_FALLBACK",notices)

    def test_first_unknown_probe_and_only_requested_evidence(self):
        result=self.probe(self.client()).get_json()
        self.assertEqual(result["status"],"success")
        self.assertEqual(result["finish_reason"],"stop")
        self.assertEqual(result["capability"][FIELD]["source"],"USER_VERIFIED")
        req,runtime=self.calls[0]
        self.assertEqual(req.reasoning.mode,ReasoningMode.OFF)
        self.assertEqual(req.generation.max_output_tokens,16)
        self.assertEqual(runtime.max_retries,0)
        self.assertEqual(len(self.calls),1)
        p=self.store.apply(self.profile)
        self.assertEqual(p.capabilities.reasoning_on,Support.UNKNOWN)
        self.assertEqual(p.capabilities.thinking_streaming_combination,Support.UNKNOWN)
        self.assertEqual(p.capabilities.max_output_tokens,Support.UNKNOWN)
        record=json.loads(self.store._path(p,FIELD).read_text())
        self.assertEqual(record["metrics"]["finish_reason"],"stop")

    def test_missing_finish_truncation_and_blank_content_do_not_publish(self):
        for events,code in [([ModelEvent(delta="OK")],"PROBE_INCOMPLETE_STREAM"),
                           ([ModelEvent(delta="OK",finish_reason="length")],"PROBE_INCOMPLETE_STREAM"),
                           ([ModelEvent(delta="   ",finish_reason="stop")],"PROBE_NO_CONTENT")]:
            with self.subTest(code=code):
                result=self.probe(self.client(events=events)).get_json()
                self.assertEqual(result["error_code"],code)
                self.assertFalse(self.store._path(self.profile,FIELD).exists())

    def test_network_failures_remain_unknown(self):
        for code in ("CONNECT_TIMEOUT","READ_TIMEOUT","TLS_ERROR","PROXY_ERROR","STREAM_INTERRUPTED"):
            with self.subTest(code=code):
                result=self.probe(self.client(error=code)).get_json()
                self.assertEqual(result["status"],"failure")
                self.assertEqual(getattr(self.store.apply(self.profile).capabilities,FIELD),Support.UNKNOWN)

    def test_explicit_refusal_changes_only_combination(self):
        result=self.probe(self.client(error="STREAM_UNSUPPORTED")).get_json()
        self.assertEqual(result["status"],"unsupported")
        self.assertEqual(result["capability"][FIELD]["status"],"unsupported")
        self.assertEqual(result["capability"]["streaming"],"supported")
        self.assertEqual(result["capability"]["thinking_off"]["status"],"supported")

    def test_confirmation_and_prerequisites(self):
        client=self.client()
        no=client.post(f"/api/profiles/{self.profile.profile_id}/probe",json={"capability":FIELD})
        self.assertEqual(no.status_code,403)
        self.store._path(self.profile,"reasoning_off").unlink()
        result=self.probe(self.client()).get_json()
        self.assertEqual(result["error_code"],"OPTION_CONFLICT")
        self.assertFalse(self.calls)

    def test_resolver_conflict_exact_identity_and_shared_profiles(self):
        p=self.profile; identity=CapabilityIdentity.for_profile(p)
        claims=[CapabilityEvidence(identity,FIELD,status,CapabilitySource.USER_VERIFIED,"2026-10-04","offline_fixture")
                for status in (Support.SUPPORTED,Support.UNSUPPORTED)]
        resolved=resolve_capabilities(p,claims)
        self.assertEqual(getattr(resolved.capabilities,FIELD),Support.UNKNOWN)
        self.assertEqual(dict(resolved.capabilities.resolution_details)[FIELD],"EVIDENCE_CONFLICT")
        self.store.save_probe(p,FIELD,Support.SUPPORTED,"2026-10-04")
        same=replace(p,profile_id="other-profile",display_name="same identity")
        self.assertEqual(getattr(self.store.apply(same).capabilities,FIELD),Support.SUPPORTED)
        other=replace(p,model="different-model",capabilities=replace(p.capabilities,model_id="different-model"),capability_basis=None)
        self.assertEqual(getattr(self.store.apply(other).capabilities,FIELD),Support.UNKNOWN)

    def test_adapter_finish_marker_is_separate_from_content(self):
        chunk=SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None,reasoning_content=None),
            finish_reason="stop")],usage=None)
        event=OpenAICompatibleAdapter._event(chunk)
        self.assertEqual((event.delta,event.finish_reason),("","stop"))

    def test_managed_request_body_uses_off_protocol_and_no_on_injection(self):
        p=self.store.save_probe(self.profile,FIELD,Support.SUPPORTED,"2026-10-04")
        from fishery_ai.model_gateway import ModelRequest,ModelMessage
        from fishery_ai.contracts import Mode
        runtime=ProfileRegistry([p],self.credentials).snapshot(p.profile_id)
        req=ModelRequest(Mode.CHAT,(ModelMessage("user","OK"),),reasoning=ReasoningOptions(ReasoningMode.OFF))
        body=OpenAICompatibleAdapter._kwargs(req,runtime,stream=True)
        self.assertEqual(body["extra_body"],{"enable_thinking":False})
        self.assertTrue(body["stream"])
        self.assertNotIn("reasoning_effort",body)




