"""Real Adapter / formal Assistant, fake SDK only; not Provider qualification evidence."""

from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
from io import StringIO
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from fishery_ai.assistant import assistant_profile
from fishery_ai.credentials import CredentialStore
from fishery_ai.execution import RequestHandle
from fishery_ai.model_gateway import GatewayError
from fishery_ai.model_options import Support
from fishery_ai.development.qualification import multi_round_qualification as qualification
from fishery_ai.development.qualification.qualification_adapter import QualificationAdapter
from tests.providers.test_streaming_tool_assembler import chunk, delta
import tests.security.test_execution as execution_fixture
from tests.support.paths import PROJECT_ROOT


FAKE_SECRET = "fictional-streaming-qualification-secret"
PRIVATE_QUERY = 'fictional-私有查询 "转义" 🐟'
STATISTICS = NS(prompt_tokens=2, completion_tokens=3, total_tokens=5)


def tool_frames(name=qualification.WATER, identifier="first", arguments="{}"):
    midpoint = len(arguments) // 2
    return [chunk([delta(name=name[:5], identifier=identifier, call_type="function")]),
            chunk([delta(arguments[:midpoint], name=name[5:])]),
            chunk([delta(arguments[midpoint:])]), chunk(finish="tool_calls", usage=STATISTICS)]


def final_frames():
    # Sensitive/HTML text remains transient. It must not be saved or previewed.
    return [chunk(content="fictional-answer <script>" + FAKE_SECRET),
            chunk(content="尾部", finish="stop", usage=STATISTICS)]


class StreamingQualificationTests(unittest.TestCase):
    def setUp(self):
        execution_fixture.ExecutionTests.setUp(self)
        temporary = TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.credentials = CredentialStore(process_env={"DASHSCOPE_API_KEY": FAKE_SECRET,
                                                      "DEEPSEEK_API_KEY": FAKE_SECRET})
        self.clients, self.bodies, self.runtimes, self.remaining = [], [], [], []

    def adapter(self, plan, preset=qualification.DEFAULT_PRESET, *, close_failure=False):
        fixture = self
        model = assistant_profile(preset).model
        case = qualification._streaming_case("low-oxygen", "water-knowledge")
        registry = qualification._isolated_registry(case, qualification.utcnow())
        class Stream:
            def __init__(self, frames): self.frames, self.closed = frames, False
            def __aiter__(self): return self.events()
            async def events(self):
                for item in self.frames:
                    if callable(item): item = item()
                    if isinstance(item, Exception): raise item
                    item.model = model
                    yield item
            async def close(self):
                if close_failure: raise RuntimeError("fictional-private-path")
                self.closed = True
        class Client:
            def __init__(self, index):
                self.index, self.closed, self.stream = index, False, None
                self.chat = NS(completions=NS(create=self.create))
            async def create(self, **body):
                fixture.bodies.append(body)
                frames = plan(self.index, body) if callable(plan) else plan[self.index - 1]
                self.stream = Stream(frames)
                return self.stream
            async def close(self): self.closed = True
        def factory(runtime, remaining):
            self.runtimes.append(runtime); self.remaining.append(remaining)
            client = Client(len(self.clients) + 1); self.clients.append(client)
            return client
        return QualificationAdapter(model, registry, case.exposed_tools, 256,
                                    streaming=True, async_client_factory=factory)

    def execute(self, case, frames, *, preset=qualification.DEFAULT_PRESET, tool_set="water-knowledge", **options):
        adapter = self.adapter(frames, preset, close_failure=options.pop("close_failure", False))
        if tool_set == "three-tools":
            adapter.exposed_tools = qualification._streaming_case(case, tool_set).exposed_tools
        report = qualification.run(case, self.root, preset_id=preset, streaming=True, tool_set=tool_set,
            confirm_network=True, credential_store=self.credentials, gateway=adapter, **options)
        return report, adapter

    def assert_closed(self, report):
        self.assertTrue(all(c.closed and c.stream.closed for c in self.clients))
        self.assertTrue(report["backend_io_closed"])
        for row in report["requests"]:
            observed = row["provider_observation"]
            self.assertTrue(observed["sdk_stream_closed"])
            self.assertTrue(observed["sdk_client_closed"])

    def test_independent_precise_plans_for_three_presets_and_both_tool_sets(self):
        hashes = set()
        for preset in qualification.STREAMING_PRESETS:
            for tool_set in qualification.STREAMING_TOOL_SETS:
                plan = qualification.plan("low-oxygen", preset, streaming=True, tool_set=tool_set)
                profile = assistant_profile(preset)
                self.assertEqual(plan["identity"]["model"], profile.model)
                self.assertEqual(plan["protocol_spec_id"], profile.preset_protocol_spec.spec_id)
                self.assertEqual(plan["contract_version"], profile.preset_contract_version)
                self.assertEqual(plan["release_status"], "candidate")
                self.assertIsNone(plan["release_id"]); self.assertIsNone(plan["release_scope"])
                self.assertFalse(plan["release_eligible"])
                scope = plan["streaming_scope"]
                self.assertEqual(scope["model_transport"], "STREAMING")
                self.assertEqual(scope["response_mode"], "streaming")
                self.assertEqual(scope["history_projection"], "UNTRUSTED_TRANSCRIPT_V1")
                self.assertEqual(scope["prompt_id"], qualification.MULTI_ROUND_PROMPT_ID)
                self.assertEqual(scope["tools"], plan["exposed_tools"])
                self.assertEqual((plan["max_tool_calls"], plan["max_tool_rounds"], plan["max_requests"]), (2,2,3))
                self.assertTrue(plan["openai_sdk_version"])
                self.assertEqual(plan["provider_service_version"], "NOT_OBSERVED")
                self.assertEqual(plan["done_marker"], "NOT_OBSERVABLE_BY_SDK")
                self.assertEqual(plan["plan_sha256"], qualification.plan("low-oxygen", preset,
                    streaming=True, tool_set=tool_set)["plan_sha256"])
                hashes.add(plan["plan_sha256"])
        self.assertEqual(len(hashes), 6)

    def test_dry_run_does_not_resolve_credentials_or_construct_sdk_or_send(self):
        with patch.object(qualification, "_credentials", side_effect=AssertionError("no credentials")), \
             patch.object(qualification, "QualificationAdapter", side_effect=AssertionError("no SDK")), \
             patch.object(qualification.AssistantService, "send", side_effect=AssertionError("no request")):
            for preset in qualification.STREAMING_PRESETS:
                report = qualification.run("low-oxygen", self.root, preset_id=preset, streaming=True)
                self.assertEqual(report["status"], "not_executed")
                self.assertEqual(report["request_count"], 0)
                self.assertEqual(report["actual_network_requests"], 0)
        self.assertFalse((self.root / "outputs").exists())

    def test_unsupported_unknown_capabilities_and_arbitrary_presets_cannot_bypass_gate(self):
        for field in ("tool_calling", "streaming", "reasoning_off", "thinking_off_streaming_combination"):
            profile = assistant_profile(qualification.DEFAULT_PRESET)
            profile = replace(profile, capabilities=replace(profile.capabilities, **{field: Support.UNKNOWN}))
            with patch.object(qualification, "assistant_profile", return_value=profile):
                if field in ("tool_calling", "streaming"):
                    with self.assertRaises(qualification.QualificationError):
                        qualification.plan("normal", streaming=True)
                else:
                    report, _ = self.execute("normal", [tool_frames(), final_frames()])
                    self.assertFalse(report["success"])
                    self.assertEqual(report["transport_attempts"], 0)
        for preset in ("DS_1", "../escape", "unpublished-preset"):
            with self.assertRaises(qualification.QualificationError):
                qualification.plan("normal", preset, streaming=True)

    def test_two_real_results_reach_subsequent_streams_with_frozen_runtime_and_formal_prompt(self):
        def decide(index, body):
            self.assertTrue(body["stream"])
            self.assertEqual(body["max_tokens"], 256)
            self.assertEqual(body["extra_body"]["enable_thinking"], False)
            self.assertEqual(body["messages"][0]["content"], qualification.MULTI_ROUND_SYSTEM_INSTRUCTION)
            if index == 1:
                self.assertEqual(len(body["messages"]), 2)
                return tool_frames()
            self.assertTrue(all(c.closed and c.stream.closed for c in self.clients[:-1]))
            messages = [m for m in body["messages"] if m["role"] == "tool"]
            if index == 2:
                result = json.loads(messages[-1]["content"])
                self.assertEqual(result["water_quality"]["dissolved_oxygen_mg_l"], 2.2)
                return tool_frames(qualification.KNOWLEDGE, "second", json.dumps({"query": PRIVATE_QUERY}, ensure_ascii=False))
            self.assertEqual(index, 3); self.assertEqual(body["tool_choice"], "none")
            self.assertEqual(len(messages), 2)
            return final_frames()
        report, adapter = self.execute("low-oxygen", decide)
        self.assertTrue(report["success"])
        self.assertTrue(report["product_commit_gate_passed"])
        self.assertTrue(report["provider_protocol_verified"])
        self.assertEqual(report["qualification_verdict"], "PENDING_MANUAL_REVIEW")
        self.assertEqual(report["request_count"], 3)
        self.assertEqual(report["actual_network_requests"], 0) # Fake SDK is not evidence.
        self.assertEqual(adapter.request_attempts, 3)
        self.assertEqual(report["usage"]["usage"]["total_tokens"], 15)
        self.assertEqual(len(report["ledger"]["entries"]), 2)
        self.assertTrue(all(e["actual_result_in_next_request"] for e in report["executions"]))
        self.assertTrue(all(r is self.runtimes[0] for r in self.runtimes))
        self.assert_closed(report)
        observation = report["requests"][1]["provider_observation"]
        self.assertEqual(observation["chunk_count"], 4)
        self.assertEqual(observation["tool_delta_chunks"], 3)
        self.assertEqual(observation["argument_delta_chunks"], 2)
        self.assertTrue(observation["calls"][0]["query_present"])
        self.assertTrue(observation["calls"][0]["query_valid"])

    def test_single_query_early_final_all_three_provider_plans(self):
        for preset in qualification.STREAMING_PRESETS:
            self.clients.clear(); self.bodies.clear()
            report, _ = self.execute("current-do", [tool_frames(), final_frames()], preset=preset)
            self.assertTrue(report["success"], report["error_code"])
            self.assertEqual(report["request_count"], 2)
            self.assertTrue(report["early_final"])
            self.assertEqual(self.bodies[-1]["tool_choice"], "auto")
            self.assert_closed(report)

    def test_concept_direct_final_and_empty_history(self):
        report, _ = self.execute("concept", [final_frames()])
        self.assertTrue(report["success"])
        self.assertEqual(report["request_count"], 1)
        self.assertEqual(report["ledger"], {"entries": []})
        self.assertEqual(len(self.bodies[0]["messages"]), 2)
        self.assertEqual(report["requests"][0]["provider_observation"]["tool_delta_chunks"], 0)
        self.assert_closed(report)

    def test_history_current_uses_product_projection_and_requeries(self):
        report, _ = self.execute("history-current", [tool_frames(), final_frames()])
        self.assertTrue(report["success"])
        self.assertEqual(report["history_projection"]["sent"], 2)
        from fishery_ai.history_projection import TRANSCRIPT_KIND
        self.assertEqual(json.loads(self.bodies[0]["messages"][1]["content"])["kind"], TRANSCRIPT_KIND)
        self.assertEqual(self.bodies[0]["messages"][-1]["role"], "user")
        self.assertEqual(len(report["ledger"]["entries"]), 1)

    def test_three_tool_scope_score_is_a_separate_receipt(self):
        report, _ = self.execute("current-score", [tool_frames(qualification.SCORE), final_frames()], tool_set="three-tools")
        self.assertTrue(report["success"], report["error_code"])
        self.assertEqual(report["plan"]["exposed_tools"], [qualification.WATER, qualification.SCORE, qualification.KNOWLEDGE])
        receipt = report["ledger"]["entries"][0]["receipt"]
        self.assertTrue(receipt["score_evaluation_completed"])
        self.assertTrue(receipt["has_score"])
        self.assertEqual(report["executions"][0]["tool_name"], qualification.SCORE)

    def test_safe_report_never_retains_or_previews_sensitive_data(self):
        report, _ = self.execute("low-oxygen", [tool_frames(), tool_frames(qualification.KNOWLEDGE,
            "second", json.dumps({"query": PRIVATE_QUERY}, ensure_ascii=False)), final_frames()])
        filename = qualification.write_report(self.root, report)
        saved = (self.root / "outputs/assistant-qualification" / filename).read_text(encoding="utf-8")
        for text in (FAKE_SECRET, PRIVATE_QUERY, "fictional-answer", "<script>",
                     qualification.MULTI_ROUND_SYSTEM_INSTRUCTION, "arguments_json", "Authorization", "raw_result"):
            self.assertNotIn(text, saved)
        self.assertFalse((self.root / ".env").exists())

    def test_no_calls_imitation_and_unnecessary_call_do_not_pass_qualification(self):
        report, _ = self.execute("history-current", [final_frames()])
        self.assertFalse(report["success"])
        self.assertEqual(report["error_code"], "ASSISTANT_SOURCE_REQUIREMENT_UNMET")
        self.assertFalse(report["product_commit_gate_passed"])
        self.assertEqual(report["ledger"], {"entries": []})
        self.clients.clear(); self.bodies.clear()
        report, _ = self.execute("concept", [tool_frames(), final_frames()])
        self.assertFalse(report["success"])
        self.assertEqual(report["error_code"], "QUALIFICATION_PATH_MISMATCH")
        self.assertEqual(report["request_count"], 2) # Observe model choice, no extra recovery.

    def test_incomplete_truncated_invalid_and_multiple_calls_do_not_execute(self):
        cases = ((tool_frames()[:-1], "STREAM_INTERRUPTED"),
                 ([chunk(content="private-partial", finish="length", usage=STATISTICS)], "STREAM_TRUNCATED"),
                 (tool_frames(arguments='{"invalid":'), "INVALID_TOOL_ARGUMENTS"),
                 ([chunk([delta("{}", name=qualification.WATER, identifier="a", call_type="function"),
                          delta("{}", name=qualification.SCORE, identifier="b", call_type="function", index=1)])], "TOOL_CALL_LIMIT"))
        for frames, code in cases:
            self.clients.clear(); self.bodies.clear()
            report, _ = self.execute("low-oxygen", [frames])
            self.assertEqual(report["error_code"], code)
            self.assertEqual(report["executions"], [])
            self.assertFalse(report["product_commit_gate_passed"])
            self.assertEqual(report["request_count"], 1)
            if code in ("STREAM_INTERRUPTED", "STREAM_TRUNCATED"):
                self.assertTrue(any(entry["error_code"] == code for entry in report["trace"]))
            self.assertFalse(report["requests"][0]["provider_observation"]["assembly_complete"])
            self.assert_closed(report)

    def test_later_stream_failure_preserves_ledger_partial_usage_and_stops(self):
        report, _ = self.execute("low-oxygen", [tool_frames(),
            [chunk(content="private-partial", usage=STATISTICS), RuntimeError("fictional-private")]])
        self.assertFalse(report["success"])
        self.assertEqual(report["error_code"], "SDK_ERROR")
        self.assertEqual(report["request_count"], 2)
        self.assertEqual(len(report["ledger"]["entries"]), 1)
        self.assertEqual(report["usage"]["usage"]["total_tokens"], 10)
        self.assertFalse(report["requests"][1]["provider_observation"]["sdk_iterator_exhausted"])
        self.assert_closed(report)

    def test_close_failure_is_separate_observation_not_executable(self):
        report, _ = self.execute("low-oxygen", [tool_frames()], close_failure=True)
        self.assertFalse(report["success"])
        self.assertEqual(report["error_code"], "SDK_ERROR")
        observed = report["requests"][0]["provider_observation"]
        self.assertTrue(observed["sdk_iterator_exhausted"])
        self.assertFalse(observed["sdk_stream_closed"])
        self.assertTrue(observed["sdk_client_closed"])
        self.assertFalse(observed["assembly_complete"])
        self.assertEqual(report["executions"], [])

    def test_provider_error_is_recorded_once_without_retry_or_failover(self):
        for code in ("HTTP_401", "HTTP_429", "READ_TIMEOUT"):
            self.clients.clear(); self.bodies.clear()
            def fail(index, body):
                raise GatewayError(code)
            report, adapter = self.execute("low-oxygen", fail)
            self.assertEqual(report["error_code"], code)
            self.assertEqual(report["request_count"], 1)
            self.assertEqual(adapter.request_attempts, 1)
            self.assertEqual(report["executions"], [])
            observed = report["requests"][0]["provider_observation"]
            self.assertFalse(observed["available"])
            self.assertFalse(observed["sdk_iterator_exhausted"])
            self.assertTrue(observed["sdk_client_closed"])
            self.assertFalse(report["success"])

    def test_safe_observer_inherits_finite_chunk_and_buffer_limits(self):
        cases = (([chunk() for _ in range(4097)], "STREAM_CHUNK_LIMIT"),
                 (tool_frames(arguments="{" + " " * 4096), "STREAM_BUFFER_LIMIT"))
        for frames, code in cases:
            self.clients.clear(); self.bodies.clear()
            report, _ = self.execute("low-oxygen", [frames])
            self.assertEqual(report["error_code"], code)
            observed = report["requests"][0]["provider_observation"]
            self.assertLessEqual(observed["chunk_count"], 4097)
            self.assertNotIn("chunks", observed)
            self.assertFalse(observed["assembly_complete"])
            self.assertEqual(report["executions"], [])
            self.assert_closed(report)

    def test_usage_only_frame_is_latest_cumulative_not_added_twice(self):
        frame = chunk(usage=STATISTICS); frame.choices = []
        report, _ = self.execute("concept", [final_frames() + [frame]])
        self.assertTrue(report["success"])
        observed = report["requests"][0]["provider_observation"]
        self.assertEqual(observed["usage_chunks"], 2)
        self.assertEqual(report["usage"]["usage"]["total_tokens"], 5)

    def test_trace_failure_cannot_pass_commit_or_qualification(self):
        with patch.object(qualification._RunTrace, "record_assistant", side_effect=OSError("fictional-private-path")):
            report, _ = self.execute("concept", [final_frames()])
        self.assertFalse(report["success"])
        self.assertFalse(report["product_commit_gate_passed"])
        self.assertFalse(report["final_answer_present"])
        self.assertEqual(report["error_code"], "TRACE_WRITE_ERROR")

    def test_cancel_after_chunk_preserves_usage_and_prevents_execution(self):
        handle = RequestHandle()
        def cancel():
            handle.cancel()
            return chunk(content="private-pending")
        report, _ = self.execute("low-oxygen", [[chunk(content="first", usage=STATISTICS), cancel]], handle=handle)
        self.assertEqual(report["error_code"], "USER_CANCELLED")
        self.assertEqual(report["request_count"], 1)
        self.assertEqual(report["executions"], [])
        self.assertEqual(report["usage"]["usage"]["total_tokens"], 5)
        self.assertFalse(report["success"]); self.assert_closed(report)

    def test_total_deadline_failure_keeps_safe_usage_and_no_followup(self):
        ticks = [0.0]
        def expire():
            ticks[0] = 1000.0
            return chunk(content="private-pending")
        with patch("fishery_ai.execution.time.monotonic", side_effect=lambda: ticks[0]):
            report, _ = self.execute("low-oxygen", [[chunk(content="first", usage=STATISTICS), expire]])
        self.assertEqual(report["error_code"], "TOTAL_TIMEOUT")
        self.assertEqual(report["request_count"], 1)
        self.assertEqual(report["executions"], [])
        self.assertFalse(report["success"]); self.assert_closed(report)

    def test_no_fourth_request_or_automatic_retry_after_third_call(self):
        report, adapter = self.execute("low-oxygen", [tool_frames(),
            tool_frames(qualification.KNOWLEDGE, "second", '{"query":"DO"}'), tool_frames(identifier="third")])
        self.assertEqual(report["error_code"], "TOOL_ROUND_LIMIT")
        self.assertEqual(report["request_count"], 3)
        self.assertEqual(adapter.request_attempts, 3)
        self.assertEqual(len(report["executions"]), 2)
        self.assertEqual(self.bodies[-1]["tool_choice"], "none")
        self.assertFalse(report["success"])

    def test_missing_credentials_private_composition_and_source_env_never_used(self):
        with patch.object(qualification, "_credentials", return_value=CredentialStore(process_env={})) as compose, \
             patch.object(qualification, "QualificationAdapter", side_effect=AssertionError("no SDK")):
            report = qualification.run("normal", self.root, streaming=True, confirm_network=True)
        compose.assert_called_once_with(self.root)
        self.assertEqual(report["error_code"], "SECRET_MISSING")
        self.assertEqual(report["request_count"], 0)
        self.assertEqual(report["actual_network_requests"], 0)
        self.assertFalse((self.root / ".env").exists())

    def test_scope_drift_fails_before_credential_resolution(self):
        original = qualification._streaming_scope
        count = [0]
        def drift(*args):
            count[0] += 1
            scope = original(*args)
            if count[0] > 1: scope["tool_definitions_sha256"] = "0" * 64
            return scope
        with patch.object(qualification, "_streaming_scope", side_effect=drift), \
             patch.object(qualification, "_credentials", side_effect=AssertionError("no credentials")):
            report = qualification.run("normal", self.root, streaming=True, confirm_network=True)
        self.assertEqual(report["error_code"], "QUALIFICATION_STREAMING_SCOPE_MISMATCH")
        self.assertEqual(report["actual_network_requests"], 0)

    def test_sdk_normalization_mismatch_never_qualifies(self):
        from fishery_ai.development.qualification.streaming_observation import ObservedAssembler
        original = ObservedAssembler.finish
        def mismatch(assembler):
            result = original(assembler)
            assembler.row["normalized_call_consistent"] = False
            return result
        with patch.object(ObservedAssembler, "finish", mismatch):
            report, _ = self.execute("normal", [tool_frames()])
        self.assertEqual(report["error_code"], "QUALIFICATION_NORMALIZATION_MISMATCH")
        self.assertFalse(report["success"])
        self.assertEqual(report["executions"], [])

    def test_cli_single_case_default_dry_run_and_explicit_consent(self):
        spec = importlib.util.spec_from_file_location("streaming_qualification_cli",
            PROJECT_ROOT / "scripts/qualification/qualify_multi_round.py")
        cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
        with patch.object(cli, "run", side_effect=AssertionError("dry run must not send")), redirect_stdout(StringIO()) as out:
            self.assertEqual(cli.main(["--streaming", "--preset", "deepseek-flash-r1", "--case", "normal"]), 0)
        self.assertEqual(json.loads(out.getvalue())["plan"]["release_status"], "candidate")
        fake = {"run_id":"0"*32, "status":"failed", "success":False, "error_code":"READ_TIMEOUT",
                "request_count":1, "actual_network_requests":1, "qualification_verdict":"FAILED", "human_review_status":"NOT_AVAILABLE"}
        with patch.object(cli, "run", return_value=fake) as run, patch.object(cli, "write_report", return_value="fake.json"), \
             redirect_stdout(StringIO()) as out:
            self.assertEqual(cli.main(["--streaming", "--case", "normal", "--confirm-network"]), 1)
        run.assert_called_once()
        self.assertTrue(run.call_args.kwargs["streaming"])
        self.assertTrue(run.call_args.kwargs["confirm_network"])
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            cli.main(["--streaming", "--case", "normal", "--review-answer"])

    def test_wrong_tool_or_invalid_bound_arguments_still_fail_in_executor(self):
        for frames, code in ((tool_frames(qualification.SCORE), "MODEL_TOOL_CALL_MALFORMED"),
                             (tool_frames(arguments='{"extra":1}'), "INVALID_TOOL_ARGUMENTS")):
            self.clients.clear(); self.bodies.clear()
            report, _ = self.execute("low-oxygen", [frames])
            self.assertFalse(report["success"])
            self.assertEqual(report["error_code"], code)
            self.assertEqual(report["request_count"], 1)

    def test_preparation_never_changes_normal_release_or_web_public_transport_gate(self):
        config_before = qualification.load_assistant_execution_config()
        for preset in qualification.STREAMING_PRESETS:
            qualification.plan("low-oxygen", preset, streaming=True, tool_set="three-tools")
        self.execute("concept", [final_frames()])
        self.assertEqual(qualification.load_assistant_execution_config(), config_before)
        self.assertFalse((self.root / "outputs/tool-policies").exists())
        # Explicit Streaming protocol entry is internal, not permission for stream().
        adapter = self.adapter([tool_frames()])
        from fishery_ai.model_gateway import ModelMessage, ModelRequest, ProfileRegistry
        from fishery_ai.contracts import Mode
        profile = assistant_profile(qualification.DEFAULT_PRESET)
        runtime = ProfileRegistry([profile], self.credentials).snapshot(profile.profile_id)
        request = ModelRequest(Mode.CHAT, (ModelMessage("user", "offline"),), tools=adapter.registry.model_definitions())
        with self.assertRaises(GatewayError): list(adapter.stream(request, runtime))
        self.assertEqual(adapter.request_attempts, 0)


if __name__ == "__main__":
    unittest.main()
