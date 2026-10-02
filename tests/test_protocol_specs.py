"""R3 encoding parity with offline, fake connections only."""

from dataclasses import FrozenInstanceError, replace
import unittest

from fishery_ai.contracts import Mode
from fishery_ai.model_gateway import ModelProfile, ModelMessage, ModelRequest, ProfileRegistry, GatewayError
from fishery_ai.model_options import GenerationOptions, ReasoningOptions, ReasoningMode, Support, ModelCapabilities
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.protocol_specs import protocol_for


class ProtocolTests(unittest.TestCase):
    def profile(self, service, model, adapter="openai_chat"):
        return ModelProfile("test", "Test", "local", "http://localhost:8000/v1", model,
            service_id=service, provider_id="custom", adapter_id=adapter)

    def test_parity_matrix(self):
        for service, model, adapter, encoding in (
            ("dashscope", "qwen-plus", "openai_chat", "enable_thinking"),
            ("dashscope", "qwen3.8-flash", "openai_chat", "enable_thinking"),
            ("dashscope", "qwen3.8-omni-flash", "openai_chat", "effort_xhigh_none"),
            ("deepseek_api", "deepseek-flash", "openai_chat", "thinking_type"),
            ("ollama", "qwen3.5:4b", "generic_openai_chat", "effort_high_none")):
            for mode in ReasoningMode:
                for streaming in (False, True):
                    with self.subTest(service=service, model=model, mode=mode, stream=streaming):
                        p = self.profile(service, model, adapter)
                        cap = ModelCapabilities(streaming=Support.SUPPORTED, reasoning_on=Support.SUPPORTED,
                            reasoning_off=Support.SUPPORTED, thinking_streaming_combination=Support.SUPPORTED,
                            streaming_usage=Support.SUPPORTED, model_id=model, base_url=p.base_url,
                            service_id=service, adapter_id=adapter)
                        runtime = ProfileRegistry([replace(p, capabilities=cap)]).snapshot("test", {})
                        request = ModelRequest(Mode.CHAT, (ModelMessage("user", "OK"),),
                            reasoning=ReasoningOptions(mode))
                        expected = {"model": model, "messages": [{"role": "user", "content": "OK"}]}
                        if streaming:
                            expected.update(stream=True, stream_options={"include_usage": True})
                        if mode != ReasoningMode.AUTO:
                            enabled = mode == ReasoningMode.ON
                            if encoding == "enable_thinking": expected["extra_body"] = {"enable_thinking": enabled}
                            elif encoding == "thinking_type": expected["extra_body"] = {"thinking": {"type": "enabled" if enabled else "disabled"}}
                            else: expected["reasoning_effort"] = ("high" if encoding == "effort_high_none" else "xhigh") if enabled else "none"
                        self.assertEqual(OpenAICompatibleAdapter._kwargs(request, runtime, stream=streaming), expected)

    def test_generic_safe_and_legacy_token_field(self):
        p = self.profile("custom", "unknown", "generic_openai_chat")
        spec = protocol_for(p)
        self.assertIsNone(spec.thinking_encoding)
        self.assertEqual(spec.encode(GenerationOptions(), ReasoningOptions(), streaming=False, include_usage=False), {})
        for field in (None, "max_tokens", "max_completion_tokens"):
            cap = ModelCapabilities(max_output_tokens=Support.SUPPORTED, max_tokens_field=field,
                model_id=p.model, base_url=p.base_url, service_id=p.service_id, adapter_id=p.adapter_id)
            runtime = ProfileRegistry([replace(p, capabilities=cap)]).snapshot("test", {})
            request = ModelRequest(Mode.CHAT, (), generation=GenerationOptions(max_output_tokens=7))
            self.assertEqual(OpenAICompatibleAdapter._kwargs(request, runtime, stream=False)[field or "max_tokens"], 7)

    def test_protocol_does_not_grant_capability_and_snapshot_is_frozen(self):
        p = self.profile("dashscope", "qwen-plus")
        runtime = ProfileRegistry([p]).snapshot("test", {})
        self.assertEqual(runtime.capabilities.reasoning_on, Support.UNKNOWN)
        with self.assertRaises(GatewayError) as caught:
            OpenAICompatibleAdapter._kwargs(ModelRequest(Mode.CHAT, (), reasoning=ReasoningOptions(ReasoningMode.ON)), runtime, stream=False)
        self.assertEqual(caught.exception.code, "OPTION_UNKNOWN")
        with self.assertRaises(FrozenInstanceError): runtime.protocol_spec.version = "2"
