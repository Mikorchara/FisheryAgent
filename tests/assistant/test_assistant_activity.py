"""Offline cumulative activity, Handler entry and final trace/commit boundaries."""

from dataclasses import replace
import json
import threading
from unittest.mock import patch

from fishery_ai.assistant import AssistantError, AssistantService
from fishery_ai.assistant_sources import SourceRequirement
from fishery_ai.assistant_sources import ledger_from_execution
from fishery_ai.contracts import Status
from fishery_ai.execution import RequestHandle, request_scope
from fishery_ai.model_gateway import GatewayError
from fishery_ai.tool_conversation import ToolCallingService, ToolExecutionMode
from fishery_ai.tools.policy import ToolPolicy
from tests.assistant.test_assistant import (AssistantFixture, AssistantWebFixture, QUERY, SCORE, LOCAL,
                                          RecordingGateway, call, final)


class AssistantActivityTests(AssistantFixture):
    def run_with_handle(self, gateway, request=None):
        handle = RequestHandle(); handle.start()
        with request_scope(handle):
            result = self.service(gateway).send(request or self.request(), self.runtime)
        return result, handle

    def test_fast_tool_retained_after_all_phases_have_passed(self):
        result, handle = self.run_with_handle(RecordingGateway(call(), final()))
        activity = handle.public_info()["activity"]
        self.assertEqual([row["kind"] for row in activity["steps"]], ["model", "tool", "model"])
        self.assertTrue(all(row["state"] == "COMPLETED" for row in activity["steps"]))
        self.assertEqual(activity["counts"], {"model_requests_started": 2, "tool_attempts": 1, "tools_executed": 1})
        self.assertEqual(activity["steps"][1]["result_status"], "NO_DATA")
        self.assertEqual(activity["budget"], {"tool_calls": 1, "tool_rounds": 1, "model_requests": 2})
        self.assertEqual(result.to_dict()["activity"]["steps"], activity["steps"])
        self.assertEqual(result.activity_revision, activity["revision"])
        activity["steps"].clear()
        self.assertEqual(len(handle.public_info()["activity"]["steps"]), 3)

    def test_handler_entry_reports_running_before_payload_returns(self):
        handle = RequestHandle(); handle.start()
        snapshots = []
        def handler():
            snapshots.append(handle.public_info())
            return None  # Reader has no data.
        with request_scope(handle), patch.object(self.reader, "query", side_effect=handler):
            result = self.service(RecordingGateway(call(), final())).send(self.request(), self.runtime)
        tool = snapshots[0]["activity"]["steps"][-1]
        self.assertEqual(tool["state"], "RUNNING")
        self.assertTrue(tool["handler_started"])
        self.assertIsNone(tool["result_status"])
        self.assertTrue(result.to_dict()["successful_turn"])

    def test_prevalidation_attempt_then_handler_start_have_distinct_revisions(self):
        handle = RequestHandle(); handle.start()
        snapshots, report = [], handle.report_steps
        def observe(*args, **kwargs):
            report(*args, **kwargs); snapshots.append(handle.public_info()["activity"])
        with request_scope(handle), patch.object(handle, "report_steps", observe):
            self.service(RecordingGateway(call(), final())).send(self.request(), self.runtime)
        tools = [s["steps"][-1] for s in snapshots if s["steps"][-1]["kind"] == "tool"]
        self.assertEqual(tools[0]["state"], "ATTEMPTING")
        self.assertFalse(tools[0]["handler_started"])
        self.assertTrue(any(t["handler_started"] and t["state"] == "RUNNING" for t in tools))
        self.assertEqual([s["revision"] for s in snapshots], sorted({s["revision"] for s in snapshots}))

    def test_rejected_tool_attempt_is_not_handler_execution(self):
        for response, code in ((call(arguments='{"extra":1}'), "INVALID_TOOL_ARGUMENTS"),
                               (call(SCORE), "TOOL_NOT_ALLOWED"), (call("fictional_unknown"), "UNKNOWN_TOOL")):
            with self.subTest(code=code), patch.object(self.reader, "query", side_effect=AssertionError("not allowed")):
                result, handle = self.run_with_handle(RecordingGateway(response))
            activity = handle.public_info()["activity"]
            self.assertEqual(activity["steps"][-1]["state"], "REJECTED")
            self.assertEqual(activity["steps"][-1]["safe_error_code"], code)
            self.assertEqual(activity["counts"]["tools_executed"], 0)
            self.assertEqual(activity["counts"]["tool_attempts"], 1)
            self.assertFalse(result.to_dict()["successful_turn"])

    def test_handler_failure_keeps_executed_audit_and_safe_error(self):
        with patch.object(self.reader, "query", side_effect=RuntimeError("private path SECRET traceback")):
            result, handle = self.run_with_handle(RecordingGateway(call()))
        tool = handle.public_info()["activity"]["steps"][-1]
        self.assertTrue(tool["handler_started"])
        self.assertEqual(tool["state"], "FAILED")
        self.assertEqual(tool["safe_error_code"], "TOOL_EXECUTION_ERROR")
        self.assertNotIn("SECRET", json.dumps(result.to_dict()))

    def test_later_model_failure_retains_completed_tool_and_never_commits(self):
        def fail(index, *_):
            if index == 2: raise GatewayError("READ_TIMEOUT")
        result, handle = self.run_with_handle(RecordingGateway(call(), final(), callback=fail))
        rows = handle.public_info()["activity"]["steps"]
        self.assertEqual(rows[1]["state"], "COMPLETED")
        self.assertEqual(rows[2]["state"], "FAILED")
        self.assertFalse(result.to_dict()["successful_turn"])

    def test_cancel_during_handler_settles_running_step_and_preserves_attempt(self):
        handle = RequestHandle(); handle.start()
        def cancel():
            handle.cancel(); return None
        with request_scope(handle), patch.object(self.reader, "query", side_effect=cancel):
            result = self.service(RecordingGateway(call())).send(self.request(), self.runtime)
        tool = handle.public_info()["activity"]["steps"][-1]
        self.assertTrue(tool["handler_started"])
        self.assertEqual(tool["state"], "CANCELLED")
        self.assertEqual(result.status, Status.CANCELLED)
        self.assertEqual(result.final_text, "")

    def test_cancel_before_executor_does_not_claim_handler_executed(self):
        handle = RequestHandle(); handle.start()
        report = handle.report_phase
        def progress(phase):
            report(phase)
            if phase == "RUNNING_TOOL": handle.cancel()
        with request_scope(handle), patch.object(handle, "report_phase", progress), patch.object(self.reader, "query") as read:
            result = self.service(RecordingGateway(call())).send(self.request(), self.runtime)
        read.assert_not_called()
        self.assertEqual(handle.public_info()["activity"]["counts"]["tools_executed"], 0)
        self.assertEqual(result.status, Status.CANCELLED)

    def test_completed_is_not_published_before_trace_and_trace_failure_is_final(self):
        handle = RequestHandle(); handle.start()
        def broken_trace(*_, **__):
            self.assertEqual(handle.public_info()["state"], "RUNNING")
            self.assertEqual(handle.public_info()["phase"], "FINALIZING")
            raise OSError("fictional-private-path")
        with request_scope(handle), patch.object(self.traces, "record_assistant", side_effect=broken_trace):
            result = self.service(RecordingGateway(final())).send(self.request(), self.runtime)
        self.assertEqual(handle.state, "FAILED")
        self.assertEqual(result.error_code, "TRACE_WRITE_ERROR")
        self.assertFalse(result.to_dict()["successful_turn"])
        self.assertEqual(result.to_dict()["activity"]["state"], "FAILED")

    def test_success_trace_and_cancel_race_share_one_commit_boundary(self):
        handle = RequestHandle(); handle.start()
        entered, stopped = threading.Event(), threading.Event()
        trace = self.traces.record_assistant
        def cancel():
            entered.wait(2); handle.cancel(); stopped.set()
        worker = threading.Thread(target=cancel); worker.start()
        def recording(*args, **kwargs):
            entered.set()
            self.assertFalse(stopped.wait(0.02))  # Stop serializes behind final trace/commit.
            trace(*args, **kwargs)
        with request_scope(handle), patch.object(self.traces, "record_assistant", side_effect=recording):
            result = self.service(RecordingGateway(final())).send(self.request(), self.runtime)
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(handle.state, "COMPLETED")
        self.assertTrue(result.to_dict()["successful_turn"])
        self.assertEqual(json.loads(self.trace.read_text(encoding="utf-8").splitlines()[-1])["status"], "completed")

    def test_source_gate_failure_is_not_a_completed_polling_turn(self):
        request = replace(self.request(), source_requirement=SourceRequirement.CURRENT_OBSERVATION_QUERY)
        result, handle = self.run_with_handle(RecordingGateway(final()), request)
        self.assertEqual(handle.state, "FAILED")
        self.assertEqual(result.error_code, "ASSISTANT_SOURCE_REQUIREMENT_UNMET")
        self.assertEqual(handle.public_info()["activity"]["safe_error_code"], result.error_code)

    def test_cancel_before_gateway_has_no_started_request(self):
        handle = RequestHandle(); handle.start()
        report = handle.report_phase
        def cancel(phase):
            report(phase)
            if phase == "REQUEST_1": handle.cancel()
        gateway = RecordingGateway(final())
        with request_scope(handle), patch.object(handle, "report_phase", cancel):
            result = self.service(gateway).send(self.request(), self.runtime)
        self.assertFalse(gateway.requests)
        self.assertEqual(handle.public_info()["activity"]["counts"]["model_requests_started"], 0)
        self.assertEqual(result.to_dict()["activity"]["steps"][0]["state"], "CANCELLED")

    def test_reentrant_late_stop_cannot_change_traced_commit_result(self):
        handle = RequestHandle(); handle.start()
        trace = self.traces.record_assistant
        def record(*args, **kwargs):
            handle.cancel(); trace(*args, **kwargs)
        with request_scope(handle), patch.object(self.traces, "record_assistant", side_effect=record):
            result = self.service(RecordingGateway(final())).send(self.request(), self.runtime)
        self.assertEqual(handle.state, "COMPLETED")
        self.assertTrue(result.to_dict()["successful_turn"])

    def test_multi_round_remains_rejected_before_any_request(self):
        gateway = RecordingGateway(final())
        coordinator = ToolCallingService(gateway, self.registry, self.traces,
            policy=ToolPolicy("assistant", True, (QUERY,)), execution_mode=ToolExecutionMode.BOUNDED_MULTI_ROUND)
        with self.assertRaises(AssistantError) as exc: AssistantService(coordinator)
        self.assertEqual(exc.exception.code, "ASSISTANT_MULTI_ROUND_NOT_ENABLED")
        self.assertFalse(gateway.requests)

    def test_activity_trace_no_arguments_payload_prompt_source_or_secret(self):
        self.store.set_current(self.reading(source_marker="ignored"))
        result, handle = self.run_with_handle(RecordingGateway(call(), final()))
        activity = result.to_dict()["activity"]
        text = json.dumps(activity) + json.dumps(handle.public_info()["activity"])
        for key in ("arguments_json", "tool_call_id", "water_quality", "findings", "messages", "credential", "source_marker"):
            self.assertNotIn('"' + key + '":', text)
        self.assertNotIn('"source": "fictional:sensor"', text)
        self.assertEqual(activity["steps"][1]["freshness"], "fresh")
        self.assertTrue(result.trace_recorded)

    def test_future_multiple_steps_serialize_without_using_legacy_slots(self):
        template = self.service(RecordingGateway(final())).send(self.request(), self.runtime)
        gateway = RecordingGateway(call(), call(SCORE, call_id="second_call"), final())
        coordinator = ToolCallingService(gateway, self.registry, self.traces,
            policy=ToolPolicy("assistant", True, (QUERY, SCORE)), execution_mode=ToolExecutionMode.BOUNDED_MULTI_ROUND)
        run = coordinator.run_request(template.context.model_request, self.runtime)
        public = replace(template, execution=run, source_ledger=ledger_from_execution(run)).to_dict()
        self.assertEqual([step["kind"] for step in public["activity"]["steps"]], ["model", "tool", "model", "tool", "model"])
        self.assertEqual(public["activity"]["counts"]["tools_executed"], 2)
        self.assertFalse(public["legacy_projection_available"])
        for field in ("tool_activity", "request_1", "request_2"): self.assertIsNone(public[field])


class AssistantActivityWebTests(AssistantWebFixture):
    def test_final_and_status_share_safe_cumulative_projection_and_control_gate(self):
        control = self.client.post("/api/requests", json={}, headers=self.headers).get_json()
        self.factory.return_value = RecordingGateway(call(), final())
        response = self.post(request_id=control["request_id"], control_token=control["control_token"])
        self.assertEqual(response.status_code, 200)
        result = response.get_json()["result"]
        endpoint = f"/api/requests/{control['request_id']}/status"
        status = self.client.post(endpoint, json={"control_token": control["control_token"]}, headers=self.headers)
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.get_json()["activity"], result["activity"])
        self.assertEqual(status.get_json()["state"], "COMPLETED")
        self.assertEqual(len(result["activity"]["steps"]), 3)
        self.assertEqual(self.client.post(endpoint, json={"control_token": "wrong"}, headers=self.headers).status_code, 404)
        self.assertEqual(self.client.post(endpoint, json={"control_token": control["control_token"]}).status_code, 403)

    def test_web_cannot_inject_steps_budget_or_mode(self):
        for field in ("activity", "steps", "budget", "execution_mode", "multi_round_enabled"):
            with self.subTest(field=field):
                self.assertEqual(self.post(**{field: "injected"}).status_code, 400)
        self.factory.assert_not_called()

    def test_trace_write_error_agrees_between_chat_and_status(self):
        control = self.client.post("/api/requests", json={}, headers=self.headers).get_json()
        with patch("fishery_ai.observability.JsonlTraceSink.record_assistant", side_effect=OSError("fictional-private")):
            response = self.post(request_id=control["request_id"], control_token=control["control_token"])
        result = response.get_json()["result"]
        status = self.client.post(f"/api/requests/{control['request_id']}/status",
            json={"control_token": control["control_token"]}, headers=self.headers).get_json()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(status["state"], "FAILED")
        self.assertEqual(status["error_code"], result["error_code"])
        self.assertEqual(status["activity"], result["activity"])
        self.assertFalse(result["successful_turn"])
