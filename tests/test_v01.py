"""Offline V0.1 tests. Network calls are blocked before importing the prototype."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
import ast
import importlib.util
from importlib.resources import files
import json
import socket
import sys
import unittest


def _network_forbidden(*_args, **_kwargs):
    raise AssertionError("network access is forbidden in the V0.1 test suite")


_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex
_original_sendto = socket.socket.sendto
_original_create_connection = socket.create_connection
_original_getaddrinfo = socket.getaddrinfo
socket.socket.connect = _network_forbidden
socket.socket.connect_ex = _network_forbidden
socket.socket.sendto = _network_forbidden
socket.create_connection = _network_forbidden
socket.getaddrinfo = _network_forbidden


def tearDownModule():
    socket.socket.connect = _original_connect
    socket.socket.connect_ex = _original_connect_ex
    socket.socket.sendto = _original_sendto
    socket.create_connection = _original_create_connection
    socket.getaddrinfo = _original_getaddrinfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fishery_ai.application import Orchestrator, _parse_model_text, result_to_dict
from fishery_ai.composition import RESOURCE_ROOT, build_offline_demo
from fishery_ai.contracts import (AnalysisRequest, Detection, DetectionSummary,
                                  Freshness, Mode, Quality, Status, WaterQualityReading,
                                  parse_time)
from fishery_ai.domain import DiagnosisService
from fishery_ai.knowledge import KnowledgeService
from fishery_ai.model_gateway import (Capabilities, GatewayError, MockGateway,
                                      ModelMessage, ModelProfile, ModelRequest,
                                      ProfileRegistry,
                                      RetryableGatewayError)
from fishery_ai.model_options import Support
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai import openai_compatible_adapter as sdk_adapter
from fishery_ai.observability import JsonlTraceSink
from fishery_ai.repositories import MockRepository


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.repository = MockRepository(RESOURCE_ROOT.joinpath("scenarios"))

    def test_water_quality_scenarios(self):
        expected = {"normal": (Quality.VALID, Freshness.FRESH),
                    "low_oxygen": (Quality.VALID, Freshness.FRESH),
                    "partial": (Quality.PARTIAL, Freshness.FRESH),
                    "stale": (Quality.VALID, Freshness.STALE),
                    "partial_stale": (Quality.PARTIAL, Freshness.STALE)}
        for name, (quality, freshness) in expected.items():
            with self.subTest(name=name):
                reading = self.repository.water_quality(name)
                self.assertEqual(reading.quality, quality)
                self.assertEqual(reading.freshness, freshness)

    def test_invalid_and_configurable_stale_policy(self):
        now = parse_time("2026-09-27T00:00:20Z")
        reading = WaterQualityReading.from_raw(
            {"temp": "bad", "ph": 7.5, "oxygen": 6},
            observed_at=now, retrieved_at=now, source="mock", stale_after_s=300)
        self.assertEqual(reading.quality, Quality.INVALID)
        self.assertEqual(reading.freshness, Freshness.FRESH)
        old = self.repository.water_quality("stale")
        relaxed = MockRepository(RESOURCE_ROOT.joinpath("scenarios"), stale_after_s=4000)
        self.assertEqual(old.freshness, Freshness.STALE)
        self.assertEqual(relaxed.water_quality("stale").freshness, Freshness.FRESH)
        with self.assertRaises(ValueError):
            WaterQualityReading.from_raw({"temp": 1}, observed_at=now,
                                         retrieved_at=now, source="mock", stale_after_s=-1)

    def test_timestamps_and_detection_contracts(self):
        event = self.repository.detection("normal")
        jumped = self.repository.detection("count_jump")
        self.assertEqual(DetectionSummary.from_event(event).count, 2)
        self.assertEqual(DetectionSummary.from_event(jumped).count, 7)
        self.assertEqual(event.frame_id, "frame-001")
        self.assertIsNone(jumped.detections[0].bbox)
        with self.assertRaises(ValueError):
            Detection("eel", 1.1)
        with self.assertRaises(ValueError):
            parse_time("2026-09-27T00:00:00")


class DiagnosisTests(unittest.TestCase):
    def setUp(self):
        self.repository = MockRepository(RESOURCE_ROOT.joinpath("scenarios"))
        self.service = DiagnosisService()

    def test_fixed_rules_and_quality_findings(self):
        self.assertEqual(self.service.diagnose(self.repository.water_quality("normal")), ())
        low = self.service.diagnose(self.repository.water_quality("low_oxygen"))
        self.assertEqual([item.code for item in low], ["OXYGEN_CRITICAL_LOW"])
        self.assertEqual(low[0].severity, "critical")
        self.assertEqual(low[0].facts_used, ("dissolved_oxygen_mg_l",))
        self.assertTrue(low[0].rule_version)
        self.assertEqual(self.service.diagnose(self.repository.water_quality("partial"))[0].code,
                         "SENSOR_PARTIAL")
        self.assertEqual(self.service.diagnose(self.repository.water_quality("stale"))[0].code,
                         "SENSOR_STALE")
        self.assertEqual([f.code for f in self.service.diagnose(
            self.repository.water_quality("partial_stale"))],
            ["SENSOR_PARTIAL", "SENSOR_STALE"])

    def test_production_threshold_boundaries_use_one_finding_per_metric(self):
        base = self.repository.water_quality("normal")
        self.assertEqual([f.code for f in self.service.diagnose(replace(base, dissolved_oxygen_mg_l=0.9))],
                         ["OXYGEN_CRITICAL_EXTREME"])
        self.assertEqual([f.code for f in self.service.diagnose(replace(base, temperature_c=34))],
                         ["TEMP_CRITICAL_HIGH"])
        self.assertEqual([f.code for f in self.service.diagnose(replace(base, ph=6.4))],
                         ["PH_CRITICAL_LOW"])


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.path = RESOURCE_ROOT.joinpath("knowledge/eel_knowledge.json")

    def test_tfidf_baseline_evidence_preserves_ids_and_source(self):
        service = KnowledgeService(self.path, backend="portable")
        self.assertEqual(len(service.chunks), 31)
        self.assertEqual(len(service._index.idf) <= 2000, True)
        results = service.search("溶氧偏低 鳗鲡浮头", top_k=4)
        self.assertTrue(results)
        self.assertTrue(any("oxygen" in item.evidence_id or "oxygen" in item.text.lower()
                            or "溶氧" in item.text for item in results))
        for item in results:
            self.assertTrue(item.evidence_id)
            self.assertEqual(item.source_id, "legacy:eel_knowledge.json")
            self.assertTrue(item.source_version)
            self.assertGreaterEqual(item.score, 0.04)
        self.assertLessEqual(len(results), 4)

    def test_keyword_fallback_and_missing_sklearn(self):
        fallback = KnowledgeService(self.path, backend="keyword")
        self.assertTrue(fallback.search("投喂", top_k=3))
        optional = KnowledgeService(self.path, backend="sklearn")
        if importlib.util.find_spec("sklearn") is None:
            self.assertEqual(optional.backend, "keyword")
        else:
            self.assertEqual(optional.backend, "sklearn")

    def test_installed_package_resource_layout(self):
        package = files("fishery_ai")
        for relative in ("resources/knowledge/eel_knowledge.json",
                         "resources/knowledge/SOURCE.md",
                         "resources/mock/profiles.json",
                         "resources/scenarios/water_quality/normal.json",
                         "resources/scenarios/detection/normal.json",
                         "resources/profiles/deepseek_experimental.json"):
            self.assertTrue(package.joinpath(relative).is_file(), relative)


class ProfileAndGatewayTests(unittest.TestCase):
    def setUp(self):
        self.registry = ProfileRegistry.from_json(RESOURCE_ROOT.joinpath("mock/profiles.json"))

    def test_profile_parsing_and_runtime_snapshot(self):
        cloud = self.registry.snapshot("cloud-demo", {"DEEPSEEK_API_KEY": "sentinel-secret"})
        local = self.registry.snapshot("local-demo", {})
        self.assertEqual(cloud.connect_timeout_s, 5)
        self.assertEqual(cloud.read_timeout_s, 30)
        self.assertEqual(cloud.total_timeout_s, 120)
        self.assertEqual(cloud.max_retries, 1)
        self.assertEqual(cloud.api_key, "sentinel-secret")
        self.assertNotIn("sentinel-secret", repr(cloud))
        self.assertIsNone(local.api_key)
        self.assertEqual(local.base_url, "http://localhost:11434/v1")
        with self.assertRaises(FrozenInstanceError):
            cloud.model = "changed"
        old = self.registry._profiles["cloud-demo"]
        self.registry._profiles["cloud-demo"] = replace(
            old, model="new", capabilities=replace(old.capabilities, model_id="new"))
        self.assertEqual(cloud.model, "deepseek-v4-flash")

    def test_invalid_profile_and_mock_gateway(self):
        with self.assertRaises(ValueError):
            ModelProfile("bad", "bad", "cloud", "file:///tmp", "m")
        with self.assertRaises(ValueError):
            ModelProfile("bad", "bad", "cloud", "https://example.com", "m", secret_env="bad-key")
        mock = MockGateway()
        request = ModelRequest(Mode.ADVICE, (ModelMessage("user", "test"),))
        response = mock.complete(request, self.registry.snapshot("local-demo", {}))
        self.assertIn("recommendations", json.loads(response.text))
        self.assertEqual("".join(event.delta for event in mock.stream(
            request, self.registry.snapshot("local-demo", {}))), response.text)

    def test_adapter_uses_fake_sdk_and_retries_only_before_body(self):
        calls = {"complete": 0, "stream": 0, "closed": 0}

        def complete_create(**kwargs):
            self.assertFalse(kwargs.get("stream", False))
            calls["complete"] += 1
            if calls["complete"] == 1:
                raise RetryableGatewayError("HTTP_503")
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                usage=SimpleNamespace(prompt_tokens=2, completion_tokens=1, total_tokens=3))

        def stream_create(**kwargs):
            self.assertTrue(kwargs["stream"])
            calls["stream"] += 1
            if calls["stream"] == 1:
                raise RetryableGatewayError("HTTP_503")
            return iter([SimpleNamespace(choices=[SimpleNamespace(
                delta=SimpleNamespace(content="ok"))], usage=None)])

        class FakeClient:
            def __init__(self, create):
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

            def close(self):
                calls["closed"] += 1

        def factory(_runtime, _remaining):
            return FakeClient(complete_create if calls["complete"] < 2 else stream_create)

        gateway = OpenAICompatibleAdapter(factory)
        runtime = self.registry.snapshot("local-demo", {})
        runtime = replace(runtime, capabilities=replace(runtime.capabilities,
                                                         streaming=Support.SUPPORTED))
        request = ModelRequest(Mode.CHAT, (ModelMessage("user", "hello"),))
        response = gateway.complete(request, runtime)
        self.assertEqual(response.text, "ok")
        self.assertEqual(response.usage.total_tokens, 3)
        self.assertEqual(calls["complete"], 2)
        self.assertEqual("".join(e.delta for e in gateway.stream(request, runtime)), "ok")
        self.assertEqual(calls["stream"], 2)
        self.assertEqual(calls["closed"], 4)

        mid_calls = 0

        def mid_stream(**_kwargs):
            nonlocal mid_calls
            mid_calls += 1
            yield SimpleNamespace(choices=[SimpleNamespace(
                delta=SimpleNamespace(content="first"))], usage=None)
            raise RetryableGatewayError("READ_OR_IDLE_TIMEOUT")

        broken = OpenAICompatibleAdapter(lambda _runtime, _remaining: FakeClient(mid_stream))
        with self.assertRaises(RetryableGatewayError):
            list(broken.stream(request, runtime))
        self.assertEqual(mid_calls, 1)

    def test_sdk_retries_disabled_and_import_isolation(self):
        runtime = self.registry.snapshot("local-demo", {})
        with patch("fishery_ai.openai_compatible_adapter.OpenAI") as sdk:
            OpenAICompatibleAdapter._make_client(runtime, 20)
            self.assertEqual(sdk.call_args.kwargs["max_retries"], 0)
            self.assertEqual(sdk.call_args.kwargs["base_url"], runtime.base_url)
        for path in (ROOT / "src/fishery_ai").glob("*.py"):
            imports = [node for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
                       if (isinstance(node, ast.Import) and any(
                           alias.name == "openai" for alias in node.names)) or
                       (isinstance(node, ast.ImportFrom) and node.module == "openai")]
            self.assertEqual(bool(imports), path.name == "openai_compatible_adapter.py")

    def test_sdk_connection_error_is_retryable_before_stream_content_only(self):
        runtime = self.registry.snapshot("local-demo", {})
        runtime = replace(runtime, capabilities=replace(runtime.capabilities,
                                                         streaming=Support.SUPPORTED))
        request = ModelRequest(Mode.CHAT, (ModelMessage("user", "hello"),))
        calls = 0

        def sdk_error():
            return sdk_adapter.APIConnectionError(
                request=sdk_adapter.httpx.Request("POST", "http://localhost:11434/v1/chat/completions"))

        def before_output(**_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise sdk_error()
            return iter([SimpleNamespace(choices=[SimpleNamespace(
                delta=SimpleNamespace(content="ok"))], usage=None)])

        class FakeClient:
            def __init__(self, create):
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

            def close(self):
                pass

        gateway = OpenAICompatibleAdapter(lambda _runtime, _remaining: FakeClient(before_output))
        self.assertEqual("".join(e.delta for e in gateway.stream(request, runtime)), "ok")
        self.assertEqual(calls, 2)

        calls = 0

        def after_output(**_kwargs):
            nonlocal calls
            calls += 1
            yield SimpleNamespace(choices=[SimpleNamespace(
                delta=SimpleNamespace(content="first"))], usage=None)
            raise sdk_error()

        gateway = OpenAICompatibleAdapter(lambda _runtime, _remaining: FakeClient(after_output))
        with self.assertRaises(RetryableGatewayError):
            list(gateway.stream(request, runtime))
        self.assertEqual(calls, 1)

    def test_cloud_secret_required_only_by_real_adapter(self):
        request = ModelRequest(Mode.ADVICE, (ModelMessage("user", "test"),))
        runtime = self.registry.snapshot("cloud-demo", {})
        with self.assertRaises(GatewayError) as caught:
            OpenAICompatibleAdapter().complete(request, runtime)
        self.assertEqual(caught.exception.code, "SECRET_MISSING")


class OrchestratorAndTraceTests(unittest.TestCase):
    def test_model_json_parsing(self):
        plain = '{"inference":"ok","recommendations":["check"]}'
        fenced = '```json\n' + plain + '\n```'
        self.assertEqual(_parse_model_text(plain), ("ok", ("check",), (), True))
        self.assertEqual(_parse_model_text(fenced), ("ok", ("check",), (), True))
        malformed = "```json\n{broken}\n```"
        parsed = _parse_model_text(malformed)
        self.assertEqual(parsed[0], malformed)
        self.assertFalse(parsed[3])

    def test_malformed_model_output_preserved_in_analysis_result(self):
        class MalformedGateway(MockGateway):
            def complete(self, request, runtime):
                from fishery_ai.model_gateway import ModelResponse
                return ModelResponse("```json\n{broken}\n```")

        with TemporaryDirectory() as tmp:
            app, _ = build_offline_demo(trace_path=Path(tmp) / "trace.jsonl")
            app.gateway = MalformedGateway()
            result = app.analyze(AnalysisRequest(Mode.ADVICE, "local-demo"))
            self.assertEqual(result.generated_text, "```json\n{broken}\n```")
            self.assertFalse(result.structured_parse_ok)
            self.assertEqual(result.recommendations, ())
            trace = json.loads((Path(tmp) / "trace.jsonl").read_text(encoding="utf-8"))
            self.assertFalse(trace["structured_parse_ok"])

    def test_profile_switch_during_request_keeps_original_runtime(self):
        with TemporaryDirectory() as tmp:
            registry = ProfileRegistry.from_json(RESOURCE_ROOT.joinpath("mock/profiles.json"))

            class SwitchingGateway(MockGateway):
                def complete(self, request, runtime):
                    old = registry._profiles[runtime.profile_id]
                    registry._profiles[runtime.profile_id] = replace(
                        old, model="switched-model",
                        capabilities=replace(old.capabilities, model_id="switched-model"))
                    return super().complete(request, runtime)

            gateway = SwitchingGateway()
            app = Orchestrator(
                MockRepository(RESOURCE_ROOT.joinpath("scenarios")), DiagnosisService(),
                KnowledgeService(RESOURCE_ROOT.joinpath("knowledge/eel_knowledge.json")), registry,
                gateway, JsonlTraceSink(Path(tmp) / "trace.jsonl"), resolve_secrets=False,
            )
            first = app.analyze(AnalysisRequest(Mode.ADVICE, "local-demo"))
            second = app.analyze(AnalysisRequest(Mode.ADVICE, "local-demo"))
            self.assertEqual(first.runtime.model, "replace-with-installed-model")
            self.assertEqual(second.runtime.model, "switched-model")

    def test_fixed_flow_cloud_and_local_analysis_result(self):
        with TemporaryDirectory() as tmp:
            orchestrator, mock = build_offline_demo(trace_path=Path(tmp) / "trace.jsonl")
            cloud = orchestrator.analyze(AnalysisRequest(Mode.ADVICE, "cloud-demo"), scenario="low_oxygen")
            local = orchestrator.analyze(AnalysisRequest(Mode.CHAT, "local-demo", "溶氧如何？"),
                                         scenario="partial")
            self.assertEqual(cloud.status, Status.COMPLETED)
            self.assertEqual(cloud.runtime.profile_id, "cloud-demo")
            self.assertEqual(local.runtime.profile_id, "local-demo")
            self.assertIn("OXYGEN_CRITICAL_LOW", [item.code for item in cloud.rule_results])
            self.assertTrue(cloud.evidence)
            self.assertTrue(cloud.inference)
            self.assertTrue(cloud.recommendations)
            self.assertTrue(cloud.uncertainty)
            self.assertEqual(cloud.usage.source.value, "unavailable")
            self.assertEqual(len(mock.calls), 2)
            self.assertIsNone(mock.calls[0][1].api_key)
            data = result_to_dict(cloud)
            self.assertEqual(data["observed_facts"]["water_quality"]["quality"], "valid")
            self.assertTrue(data["structured_parse_ok"])
            self.assertEqual(data["status"], "completed")
            traces = [json.loads(line) for line in (Path(tmp) / "trace.jsonl").read_text(
                encoding="utf-8").splitlines()]
            self.assertEqual(len(traces), 2)
            self.assertEqual(traces[0]["rule_codes"], ["OXYGEN_CRITICAL_LOW"])
            self.assertEqual(traces[0]["input_snapshot_metadata"]["freshness"], "fresh")
            self.assertTrue(traces[0]["evidence_ids"])
            self.assertIn("total_ms", traces[0]["timing"])
            self.assertNotIn("messages", traces[0])

    def test_trace_allowlist_never_writes_secret_or_prompt(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            registry = ProfileRegistry.from_json(RESOURCE_ROOT.joinpath("mock/profiles.json"))

            class InjectedRegistry:
                def snapshot(self, profile_id, environ=None):
                    return registry.snapshot(profile_id, {"DEEPSEEK_API_KEY": "SENTINEL_SECRET"})

            mock = MockGateway()
            app = Orchestrator(
                MockRepository(RESOURCE_ROOT.joinpath("scenarios")), DiagnosisService(),
                KnowledgeService(RESOURCE_ROOT.joinpath("knowledge/eel_knowledge.json")),
                InjectedRegistry(), mock, JsonlTraceSink(path),
            )
            app.analyze(AnalysisRequest(Mode.CHAT, "cloud-demo", "SENTINEL_PROMPT"))
            self.assertEqual(mock.calls[0][1].api_key, "SENTINEL_SECRET")
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("SENTINEL_PROMPT", content)
            self.assertNotIn("SENTINEL_SECRET", content)
            self.assertEqual(json.loads(content)["runtime"]["profile_id"], "cloud-demo")

    def test_gateway_error_returns_structured_failure_and_trace(self):
        class BrokenGateway:
            def complete(self, _request, _runtime):
                raise GatewayError("MODEL_UNAVAILABLE")

            def stream(self, _request, _runtime):
                raise GatewayError("MODEL_UNAVAILABLE")

        with TemporaryDirectory() as tmp:
            app, _ = build_offline_demo(trace_path=Path(tmp) / "trace.jsonl")
            app.gateway = BrokenGateway()
            result = app.analyze(AnalysisRequest(Mode.ADVICE, "local-demo"))
            self.assertEqual(result.status, Status.FAILED)
            self.assertEqual(result.error_code, "MODEL_UNAVAILABLE")
            self.assertEqual(json.loads((Path(tmp) / "trace.jsonl").read_text(
                encoding="utf-8"))["error_code"], "MODEL_UNAVAILABLE")

    def test_network_guard_is_active(self):
        with self.assertRaises(AssertionError):
            socket.create_connection(("example.invalid", 443))


if __name__ == "__main__":
    unittest.main()
