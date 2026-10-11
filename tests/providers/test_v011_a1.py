"""V0.1.1-A1 capability and usage tests; every request is simulated offline."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import socket
import sys
import unittest


def _deny_network(*_args, **_kwargs):
    raise AssertionError("network is forbidden")


_socket_methods = ("connect", "connect_ex", "sendto")
_originals = {}


def setUpModule():
    for name in _socket_methods:
        _originals[name] = getattr(socket.socket, name)
        setattr(socket.socket, name, _deny_network)
    _originals["create_connection"] = socket.create_connection
    socket.create_connection = _deny_network
    _originals["getaddrinfo"] = socket.getaddrinfo
    socket.getaddrinfo = _deny_network


def tearDownModule():
    for name in _socket_methods:
        setattr(socket.socket, name, _originals[name])
    socket.create_connection = _originals["create_connection"]
    socket.getaddrinfo = _originals["getaddrinfo"]


from tests.support.paths import PROJECT_ROOT
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from fishery_ai.composition import build_offline_demo, RESOURCE_ROOT
from fishery_ai.contracts import (AnalysisRequest, Mode, Usage, UsageAccumulator,
                                  UsageSource)
from fishery_ai.model_gateway import (GatewayError, ModelMessage, ModelProfile,
                                      ModelRequest, ProfileRegistry)
from fishery_ai.model_options import (GenerationOptions, ModelCapabilities,
                                      OptionValidationError, ProfileStatus,
                                      ReasoningMode, ReasoningOptions, Support,
                                      validate_options)
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter, _usage


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.registry = ProfileRegistry.from_json(RESOURCE_ROOT.joinpath("mock/profiles.json"))

    def test_profile_identity_and_status_are_separate(self):
        cloud = self.registry.snapshot("cloud-demo", {})
        local = self.registry.snapshot("local-demo", {})
        self.assertEqual((cloud.provider_id, cloud.adapter_id, cloud.provider_kind,
                          cloud.profile_status),
                         ("deepseek", "openai_chat", "cloud", ProfileStatus.EXPERIMENTAL))
        self.assertEqual((cloud.service_id, cloud.model_family), ("deepseek_api", "deepseek"))
        self.assertEqual((local.provider_id, local.adapter_id, local.provider_kind,
                          local.profile_status),
                         ("custom", "generic_openai_chat", "local", ProfileStatus.CUSTOM))
        self.assertEqual(local.capabilities.reasoning_on, Support.UNKNOWN)
        self.assertEqual(local.capabilities.temperature, Support.UNKNOWN)
        self.assertEqual(local.capabilities.max_output_tokens, Support.UNKNOWN)
        self.assertNotIn("verified", {cloud.profile_status.value, local.profile_status.value})

    def test_verified_requires_scoped_evidence_and_cannot_inherit_after_edit(self):
        base = "https://example.invalid/v1"
        caps = ModelCapabilities(
            streaming=Support.SUPPORTED, source="user_verified",
            model_id="exact-model", base_url=base, verified_at="2026-09-29")
        profile = ModelProfile(
            "verified-fixture", "Verified fixture", "cloud", base, "exact-model",
            adapter_id="openai_chat", provider_id="example",
            profile_status=ProfileStatus.VERIFIED, capabilities=caps)
        self.assertEqual(profile.profile_status, ProfileStatus.VERIFIED)
        with self.assertRaises(ValueError):
            replace(profile, model="different-model")
        with self.assertRaises(ValueError):
            replace(profile, base_url="https://other.invalid/v1")
        with self.assertRaises(ValueError):
            replace(profile, capabilities=replace(caps, source="official_docs"))
        with self.assertRaises(ValueError):
            replace(self.registry._profiles["cloud-demo"], profile_status=ProfileStatus.VERIFIED)

    def test_verified_defaults_require_current_model_capability(self):
        base = "https://example.invalid/v1"
        caps = ModelCapabilities(
            max_output_tokens=Support.SUPPORTED, max_tokens_field="max_tokens",
            source="user_verified", model_id="exact-model", base_url=base,
            verified_at="2026-09-29")
        profile = ModelProfile(
            "verified-fixture", "Verified fixture", "cloud", base, "exact-model",
            adapter_id="openai_chat", provider_id="example",
            profile_status=ProfileStatus.VERIFIED, capabilities=caps,
            default_generation=GenerationOptions(max_output_tokens=100))
        runtime = ProfileRegistry([profile]).snapshot("verified-fixture", {})
        kwargs = OpenAICompatibleAdapter._kwargs(
            ModelRequest(Mode.CHAT, (ModelMessage("user", "test"),)), runtime, stream=False)
        self.assertEqual(kwargs["max_tokens"], 100)
        with self.assertRaises(ValueError):
            replace(profile, capabilities=replace(caps, max_output_tokens=Support.UNKNOWN,
                                                   max_tokens_field=None))

    def test_profile_file_cannot_rebind_declared_capability_implicitly(self):
        data = {
            "profile_id": "other", "display_name": "Other", "provider_kind": "cloud",
            "adapter_id": "openai_chat", "provider_id": "example",
            "base_url": "https://example.invalid/v1", "model": "new-model",
            "profile_status": "experimental",
            "capabilities": {"source": "official_docs", "streaming": "supported"},
        }
        with self.assertRaises(ValueError):
            ModelProfile.from_dict(data)

    def test_unverified_defaults_and_generic_provider_are_restricted(self):
        base = self.registry._profiles["local-demo"]
        with self.assertRaises(ValueError):
            replace(base, default_generation=GenerationOptions(temperature=0.7))
        with self.assertRaises(ValueError):
            replace(base, provider_id="deepseek")
        with self.assertRaises(ValueError):
            replace(base, model="changed")

    def test_snapshot_is_immutable_and_keeps_exact_capabilities(self):
        runtime = self.registry.snapshot("cloud-demo", {"DEEPSEEK_API_KEY": "SENTINEL_KEY"})
        self.assertNotIn("SENTINEL_KEY", repr(runtime))
        self.assertEqual(runtime.capabilities.model_id, runtime.model)
        with self.assertRaises(FrozenInstanceError):
            runtime.model = "other"
        old = self.registry._profiles["cloud-demo"]
        self.registry._profiles["cloud-demo"] = replace(
            old, model="other", capabilities=replace(old.capabilities, model_id="other"))
        self.assertEqual(runtime.model, "deepseek-v4-flash")
        self.assertEqual(runtime.capabilities.model_id, "deepseek-v4-flash")

    def test_reasoning_auto_on_off_unknown_and_unsupported(self):
        caps = ModelCapabilities()
        validate_options(GenerationOptions(), ReasoningOptions(), caps)
        for mode in (ReasoningMode.ON, ReasoningMode.OFF):
            with self.subTest(mode=mode), self.assertRaises(OptionValidationError) as caught:
                validate_options(GenerationOptions(), ReasoningOptions(mode), caps)
            self.assertEqual(caught.exception.code, "OPTION_UNKNOWN")
        unsupported = replace(caps, reasoning_on=Support.UNSUPPORTED)
        with self.assertRaises(OptionValidationError) as caught:
            validate_options(GenerationOptions(), ReasoningOptions(ReasoningMode.ON), unsupported)
        self.assertEqual(caught.exception.code, "OPTION_UNSUPPORTED")
        supported = replace(caps, reasoning_on=Support.SUPPORTED,
                            reasoning_off=Support.SUPPORTED)
        validate_options(GenerationOptions(), ReasoningOptions(ReasoningMode.ON), supported)
        validate_options(GenerationOptions(), ReasoningOptions(ReasoningMode.OFF), supported)

    def test_unknown_sampling_output_limit_and_conflicts(self):
        caps = ModelCapabilities()
        for generation in (GenerationOptions(temperature=0.7), GenerationOptions(top_p=0.9),
                           GenerationOptions(max_output_tokens=2048)):
            with self.subTest(generation=generation), self.assertRaises(OptionValidationError) as caught:
                validate_options(generation, ReasoningOptions(), caps)
            self.assertEqual(caught.exception.code, "OPTION_UNKNOWN")
        caps = replace(caps, temperature=Support.UNSUPPORTED)
        with self.assertRaises(OptionValidationError) as caught:
            validate_options(GenerationOptions(temperature=0.7), ReasoningOptions(), caps)
        self.assertEqual(caught.exception.code, "OPTION_UNSUPPORTED")
        caps = replace(caps, temperature=Support.SUPPORTED,
                       reasoning_on=Support.SUPPORTED,
                       reasoning_temperature_conflict=True)
        validate_options(GenerationOptions(), ReasoningOptions(ReasoningMode.ON), caps)
        with self.assertRaises(OptionValidationError) as caught:
            validate_options(GenerationOptions(temperature=0.7),
                             ReasoningOptions(ReasoningMode.ON), caps)
        self.assertEqual(caught.exception.code, "OPTION_CONFLICT")
        with self.assertRaises(OptionValidationError) as caught:
            validate_options(GenerationOptions(max_output_tokens=0), ReasoningOptions(), caps)
        self.assertEqual(caught.exception.code, "INVALID_OPTION_VALUE")

    def test_effort_values_are_exact_model_values(self):
        caps = ModelCapabilities(reasoning_on=Support.SUPPORTED,
                                 reasoning_effort=Support.SUPPORTED,
                                 effort_values=("low", "high"))
        validate_options(GenerationOptions(), ReasoningOptions(ReasoningMode.ON, "high"), caps)
        with self.assertRaises(OptionValidationError) as caught:
            validate_options(GenerationOptions(), ReasoningOptions(ReasoningMode.ON, "medium"), caps)
        self.assertEqual(caught.exception.code, "INVALID_OPTION_VALUE")
        with self.assertRaises(OptionValidationError) as caught:
            validate_options(GenerationOptions(), ReasoningOptions(ReasoningMode.OFF, "high"), caps)
        self.assertEqual(caught.exception.code, "OPTION_CONFLICT")


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.registry = ProfileRegistry.from_json(RESOURCE_ROOT.joinpath("mock/profiles.json"))
        self.request = ModelRequest(Mode.CHAT, (ModelMessage("user", "hello"),))

    def test_generic_request_sends_only_minimal_fields(self):
        runtime = self.registry.snapshot("local-demo", {})
        kwargs = OpenAICompatibleAdapter._kwargs(self.request, runtime, stream=False)
        self.assertEqual(set(kwargs), {"model", "messages"})
        with self.assertRaises(GatewayError) as caught:
            OpenAICompatibleAdapter._kwargs(
                replace(self.request, generation=GenerationOptions(max_output_tokens=2048)),
                runtime, stream=False)
        self.assertEqual((caught.exception.code, caught.exception.option),
                         ("OPTION_UNKNOWN", "max_output_tokens"))

    def test_explicit_output_limit_uses_scoped_field(self):
        runtime = self.registry.snapshot("local-demo", {})
        caps = replace(runtime.capabilities, max_output_tokens=Support.SUPPORTED,
                       max_tokens_field="max_completion_tokens")
        runtime = replace(runtime, capabilities=caps)
        kwargs = OpenAICompatibleAdapter._kwargs(
            replace(self.request, generation=GenerationOptions(max_output_tokens=2048)),
            runtime, stream=False)
        self.assertEqual(kwargs["max_completion_tokens"], 2048)
        self.assertNotIn("max_tokens", kwargs)

    def test_provider_specific_reasoning_is_isolated(self):
        cloud = self.registry.snapshot("cloud-demo", {})
        caps = replace(cloud.capabilities, reasoning_on=Support.SUPPORTED,
                       reasoning_off=Support.SUPPORTED)
        cloud = replace(cloud, capabilities=caps, model="deepseek-flash")
        on = replace(self.request, reasoning=ReasoningOptions(ReasoningMode.ON))
        off = replace(self.request, reasoning=ReasoningOptions(ReasoningMode.OFF))
        self.assertEqual(OpenAICompatibleAdapter._kwargs(on, cloud, stream=False)["extra_body"],
                         {"thinking": {"type": "enabled"}})
        self.assertEqual(OpenAICompatibleAdapter._kwargs(off, cloud, stream=False)["extra_body"],
                         {"thinking": {"type": "disabled"}})
        qwen = replace(cloud, provider_id="qwen", service_id="dashscope", model_family="qwen", model="qwen-plus")
        self.assertEqual(OpenAICompatibleAdapter._kwargs(on, qwen, stream=False)["extra_body"],
                         {"enable_thinking": True})
        generic = replace(cloud, provider_id="custom", service_id="custom",
                          model_family="unknown", adapter_id="generic_openai_chat")
        with self.assertRaises(GatewayError) as caught:
            OpenAICompatibleAdapter._kwargs(on, generic, stream=False)
        self.assertEqual(caught.exception.code, "OPTION_UNSUPPORTED")
        auto = OpenAICompatibleAdapter._kwargs(self.request, generic, stream=False)
        self.assertNotIn("extra_body", auto)

    def test_fake_provider_usage_breakdown_and_stream_final_event(self):
        calls = []
        provider_usage = SimpleNamespace(
            prompt_tokens=12, completion_tokens=5, total_tokens=17,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=2),
            prompt_tokens_details=SimpleNamespace(cached_tokens=3))

        def create(**kwargs):
            calls.append(kwargs)
            if kwargs.get("stream"):
                return iter([
                    SimpleNamespace(choices=[SimpleNamespace(
                        delta=SimpleNamespace(content="ok"))], usage=None),
                    SimpleNamespace(choices=[], usage=provider_usage),
                ])
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                usage=provider_usage)

        class FakeClient:
            chat = SimpleNamespace(completions=SimpleNamespace(create=create))

            def close(self):
                pass

        runtime = self.registry.snapshot("local-demo", {})
        runtime = replace(runtime, capabilities=replace(runtime.capabilities,
                                                         streaming=Support.SUPPORTED))
        gateway = OpenAICompatibleAdapter(lambda _runtime, _remaining: FakeClient())
        response = gateway.complete(self.request, runtime)
        self.assertEqual((response.usage.input_tokens, response.usage.output_tokens,
                          response.usage.total_tokens, response.usage.reasoning_tokens,
                          response.usage.cached_input_tokens, response.usage.source),
                         (12, 5, 17, 2, 3, UsageSource.PROVIDER))
        events = list(gateway.stream(self.request, runtime))
        self.assertEqual(events[0].delta, "ok")
        self.assertEqual(events[-1].usage.total_tokens, 17)
        self.assertEqual(events[-1].delta, "")
        self.assertNotIn("stream_options", calls[-1])

    def test_missing_provider_usage_is_unavailable_not_zero(self):
        self.assertEqual(_usage(None), Usage())
        self.assertIsNone(_usage(None).total_tokens)
        self.assertEqual(_usage(SimpleNamespace(prompt_tokens=None,
                                                completion_tokens=None,
                                                total_tokens=None)).source,
                         UsageSource.UNAVAILABLE)

    def test_unknown_streaming_never_opens_transport(self):
        called = []
        gateway = OpenAICompatibleAdapter(lambda *_args: called.append(True))
        with self.assertRaises(GatewayError) as caught:
            list(gateway.stream(self.request, self.registry.snapshot("local-demo", {})))
        self.assertEqual(caught.exception.code, "OPTION_UNKNOWN")
        self.assertFalse(called)


class UsageAndFlowTests(unittest.TestCase):
    def test_session_aggregation_preserves_missing_data(self):
        totals = UsageAccumulator()
        totals.add(Usage(10, 5, 15, source=UsageSource.PROVIDER))
        self.assertEqual(totals.snapshot().usage.total_tokens, 15)
        self.assertIsNone(totals.snapshot().usage.reasoning_tokens)
        totals.add(Usage(4, 3, 7, reasoning_tokens=1, cached_input_tokens=2,
                         source=UsageSource.PROVIDER))
        self.assertEqual((totals.snapshot().usage.input_tokens,
                          totals.snapshot().usage.output_tokens,
                          totals.snapshot().usage.total_tokens), (14, 8, 22))
        self.assertIsNone(totals.snapshot().usage.reasoning_tokens)
        totals.add(None)
        result = totals.snapshot()
        self.assertEqual((result.request_count, result.reported_count), (3, 2))
        self.assertFalse(result.complete)
        self.assertIsNone(result.usage.total_tokens)

    def test_invalid_usage_does_not_become_zero(self):
        with self.assertRaises(ValueError):
            Usage(0, source=UsageSource.UNAVAILABLE)
        with self.assertRaises(ValueError):
            Usage(-1, source=UsageSource.PROVIDER)
        self.assertEqual(Usage().source, UsageSource.UNAVAILABLE)

    def test_mock_flow_and_trace_do_not_expose_secret(self):
        with TemporaryDirectory() as tmp:
            app, _ = build_offline_demo(trace_path=Path(tmp) / "trace.jsonl")
            result = app.analyze(AnalysisRequest(Mode.ADVICE, "cloud-demo"))
            self.assertEqual(result.usage.source, UsageSource.UNAVAILABLE)
            trace = json.loads((Path(tmp) / "trace.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(trace["usage"]["source"], "unavailable")
            self.assertIsNone(trace["usage"]["total_tokens"])
            self.assertNotIn("api_key", json.dumps(trace))
            self.assertEqual(trace["runtime"]["provider_id"], "deepseek")

    def test_analysis_request_options_reach_validator_before_mock_call(self):
        with TemporaryDirectory() as tmp:
            app, gateway = build_offline_demo(trace_path=Path(tmp) / "trace.jsonl")
            request = AnalysisRequest(
                Mode.ADVICE, "local-demo",
                generation=GenerationOptions(temperature=0.7))
            result = app.analyze(request)
            self.assertEqual((result.error_code, result.error_option),
                             ("OPTION_UNKNOWN", "temperature"))
            self.assertFalse(gateway.calls)
            trace = json.loads((Path(tmp) / "trace.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(trace["error_option"], "temperature")
            self.assertNotIn("messages", trace)

    def test_network_guard_is_active(self):
        with self.assertRaises(AssertionError):
            socket.create_connection(("example.invalid", 443))
        with self.assertRaises(AssertionError):
            socket.getaddrinfo("example.invalid", 443)


if __name__ == "__main__":
    unittest.main()
