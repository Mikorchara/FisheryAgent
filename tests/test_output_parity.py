"""Offline Normal/Streaming parity checks, independent of model wording."""

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from types import SimpleNamespace
from contextlib import redirect_stdout
import importlib.util
import io
import json
import socket
import unittest

from fishery_ai.application import Orchestrator, _parse_model_text, result_to_dict
from fishery_ai.composition import RESOURCE_ROOT
from fishery_ai.contracts import AnalysisRequest, Mode, Usage, UsageSource
from fishery_ai.domain import DiagnosisService
from fishery_ai.knowledge import KnowledgeService
from fishery_ai.model_gateway import ModelEvent, ModelResponse, ProfileRegistry
from fishery_ai.model_options import ReasoningMode, ReasoningOptions, Support
from fishery_ai.observability import JsonlTraceSink
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.repositories import MockRepository
from fishery_ai.web import _builtin_profiles


FINAL = json.dumps({"inference": "当前低氧", "recommendations": ["增氧"],
                    "uncertainty": ["缺少鱼体症状"]}, ensure_ascii=False)


class OutputParityTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for name in ("connect", "connect_ex", "sendto"):
            guard = patch.object(socket.socket, name, side_effect=AssertionError("offline only"))
            guard.start()
            self.addCleanup(guard.stop)
        guard = patch.object(socket, "getaddrinfo", side_effect=AssertionError("offline only"))
        guard.start()
        self.addCleanup(guard.stop)

    def pair(self, text=FINAL):
        calls = []

        class Gateway:
            def complete(self, request, runtime):
                calls.append((request, runtime))
                return ModelResponse(text, Usage(8, 5, 13, source=UsageSource.PROVIDER), reasoning_content="debug reasoning")

            def stream(self, request, runtime):
                calls.append((request, runtime))
                yield ModelEvent(reasoning_delta="debug ")
                yield ModelEvent(reasoning_delta="reasoning")
                for offset in range(0, len(text), 3):
                    yield ModelEvent(delta=text[offset:offset + 3])
                yield ModelEvent(usage=Usage(8, 5, 13, source=UsageSource.PROVIDER))

        profile = next(p for p in _builtin_profiles() if p.profile_id == "mock-demo")
        fixed = datetime(2026, 10, 1, tzinfo=timezone.utc)
        app = Orchestrator(MockRepository(RESOURCE_ROOT.joinpath("mock/scenarios.json")),
            DiagnosisService(), KnowledgeService(RESOURCE_ROOT.joinpath("knowledge/eel_knowledge.json")),
            ProfileRegistry([profile]), Gateway(), JsonlTraceSink(Path(self.temp.name) / "trace.jsonl"),
            clock=lambda: fixed, resolve_secrets=False)
        request = AnalysisRequest(Mode.CHAT, profile.profile_id, "当前水质情况怎么样？")
        normal = result_to_dict(app.analyze(request, scenario="low_oxygen"))
        events = list(app.analyze_stream(request, scenario="low_oxygen"))
        return normal, events[-1].data["result"], events, calls

    def test_both_transports_call_the_same_parser_with_aggregated_final_content(self):
        for text in (FINAL, "```json\n" + FINAL + "\n```", '{"inference": broken'):
            with self.subTest(text=text[:12]), patch(
                    "fishery_ai.application._parse_model_text", wraps=_parse_model_text) as parser:
                normal, stream, _, _ = self.pair(text)
                self.assertEqual([call.args[0] for call in parser.call_args_list], [text, text])
                self.assertEqual(normal["structured_parse_ok"], stream["structured_parse_ok"])
                self.assertEqual(normal["generated_text"], stream["generated_text"])

    def test_final_contract_and_program_facts_are_equal(self):
        normal, stream, _, calls = self.pair()
        self.assertEqual(set(normal), set(stream))
        for field in ("inference", "recommendations", "uncertainty", "observed_facts",
                      "rule_results", "evidence", "runtime", "structured_parse_ok", "usage"):
            self.assertEqual(normal[field], stream[field])
        self.assertIsInstance(stream["inference"], str)
        self.assertIsInstance(stream["recommendations"], list)
        self.assertIsInstance(stream["uncertainty"], list)
        self.assertEqual(calls[0], calls[1])
        self.assertIn("OXYGEN_CRITICAL_LOW", [r["code"] for r in stream["rule_results"]])

    def test_reasoning_never_enters_final_content_or_parser(self):
        normal, stream, events, _ = self.pair()
        self.assertEqual(normal["reasoning_content"], stream["reasoning_content"])
        self.assertEqual("".join(e.data["delta"] for e in events if e.kind == "content_delta"), FINAL)
        self.assertEqual(stream["generated_text"], FINAL)
        self.assertNotIn("debug", stream["inference"])

    def test_qwen_adapter_payload_differs_only_in_stream_transport_options(self):
        profile = next(p for p in _builtin_profiles() if p.profile_id == "qwen-plus-experimental")
        # Obtain the same model messages produced by the application, without a transport.
        _, _, _, calls = self.pair()
        from dataclasses import replace
        for mode in (ReasoningMode.OFF, ReasoningMode.ON):
            request = replace(calls[0][0], reasoning=ReasoningOptions(mode))
            profile = replace(profile, capabilities=replace(profile.capabilities,
                thinking_off_streaming_combination=Support.SUPPORTED))
            runtime = ProfileRegistry([profile]).snapshot(profile.profile_id, {})
            normal = OpenAICompatibleAdapter._kwargs(request, runtime, stream=False)
            stream = OpenAICompatibleAdapter._kwargs(request, runtime, stream=True)
            self.assertTrue(stream.pop("stream"))
            self.assertEqual(stream.pop("stream_options"), {"include_usage": True})
            self.assertEqual(normal, stream)
            self.assertEqual(normal["extra_body"], {"enable_thinking": mode == ReasoningMode.ON})



if __name__ == "__main__":
    unittest.main()


# Explicit historical fixtures; not active startup assets.
from historical_model_fixtures import install as _install_history
_install_history(globals())
