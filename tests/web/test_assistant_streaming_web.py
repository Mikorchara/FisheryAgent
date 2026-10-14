"""Web POST SSE → real Adapter / Runtime / Handlers, fake SDK; no actual qualification."""

import asyncio
from dataclasses import replace
import json
import threading
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from fishery_ai.assistant import assistant_profile
from fishery_ai.assistant_streaming import (AssistantStreamingConfig, AssistantStreamingRelease,
    AssistantEventChannel, streaming_scope, load_assistant_streaming_config, resolve_streaming_profile)
from fishery_ai.credentials import CredentialStore
from fishery_ai.domain import DiagnosisService
from fishery_ai.history_projection import DEFAULT_HISTORY_PROJECTION
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.model_gateway import ModelRequest, ModelMessage, GatewayError
from fishery_ai.contracts import Mode
from fishery_ai.tools import ToolRegistry
from fishery_ai.tools.policy import ToolPolicy
import tests.assistant.test_assistant as fixture
import tests.security.test_execution as execution_fixture
from tests.providers.test_streaming_tool_assembler import chunk
from tests.tools.test_streaming_multi_round import tool_chunks, final_chunks


PRESET = "dashscope-qwen38-flash-r1"
SECRET = "fictional-web-stream-secret"
NAMES = (fixture.QUERY, fixture.KNOWLEDGE)
BLOCK = object()


class StreamingWebTests(fixture.AssistantWebFixture):
    make_app = fixture.AssistantWebFixture.make_app
    reading = fixture.AssistantFixture.reading

    def setUp(self):
        fixture.AssistantWebFixture.setUp(self)
        execution_fixture.ExecutionTests.setUp(self) # Windows asyncio wakeup exception, no Provider sockets.
        self.clients, self.bodies, self.remaining, self.runtimes = [], [], [], []
        self.blocked = threading.Event()

    def config(self, *, enabled=True, released=True, preset=PRESET):
        registry = ToolRegistry(self.reader, DiagnosisService(), knowledge=fixture.FakeKnowledgeService())
        scope = streaming_scope(assistant_profile(preset), ToolPolicy("assistant", True, NAMES),
                                registry, DEFAULT_HISTORY_PROJECTION)
        record = AssistantStreamingRelease(json.dumps(scope), "released" if released else "candidate",
            "OFFLINE_FIXTURE_ONLY" if released else None, "2026-10-13T00:00:00Z" if released else None)
        return AssistantStreamingConfig(enabled, (record,))

    def setup_app(self, frames, *, preset=PRESET, stored_config=False, config_override=None, **config_options):
        owner = self
        self.preset = preset
        class Stream:
            def __init__(self, items): self.items, self.closed = items, False
            def __aiter__(self): return self.events()
            async def events(self):
                for item in self.items:
                    if item is BLOCK:
                        owner.blocked.set(); await asyncio.Event().wait()
                    if isinstance(item, Exception): raise item
                    item.model = assistant_profile(preset).model
                    yield item
                    await asyncio.sleep(0)
            async def close(self): self.closed = True
        class Client:
            def __init__(self, index):
                self.index, self.closed, self.stream = index, False, None
                self.chat = NS(completions=NS(create=self.create))
            async def create(self, **body):
                owner.bodies.append(body)
                items = frames(self.index, body) if callable(frames) else frames[self.index-1]
                self.stream = Stream(items)
                return self.stream
            async def close(self): self.closed = True
        def factory(runtime, remaining):
            owner.remaining.append(remaining)
            owner.runtimes.append(runtime)
            client = Client(len(owner.clients)+1); owner.clients.append(client)
            return client
        self.factory.return_value = OpenAICompatibleAdapter(async_client_factory=factory)
        config = replace(load_assistant_streaming_config(), enabled=True) if stored_config else self.config(preset=preset, **config_options)
        if config_override is not None:
            config = config_override
        self.app = self.make_app(CredentialStore(process_env={"DASHSCOPE_API_KEY": SECRET, "DEEPSEEK_API_KEY": SECRET}),
                                 assistant_streaming_config=config)
        self.app.extensions["fishery_tool_policy_store"].save({"schema_version":1,
            "modes":{"analysis":{"selected_tools":[]},"assistant":{"selected_tools":list(NAMES)}}})
        self.client = self.app.test_client()
        csrf = self.client.get("/api/credential-session").get_json()["csrf_token"]
        self.headers = {"Origin":"http://localhost", "X-CSRF-Token":csrf}
        self.bootstrap = self.client.get("/api/assistant/bootstrap").get_json()
        self.epoch = self.bootstrap["epoch"]
        self.stream_profile = next(p for p in self.bootstrap["presets"] if p["preset_id"] == preset)["streaming_profile"]

    def payload(self, **changes):
        control = self.client.post("/api/requests", json={}, headers=self.headers).get_json()
        return {"preset_id":self.preset,"question":"offline fixture question", "history":[],"epoch":self.epoch,
            "confirm_network":True,"execution_profile_revision":self.stream_profile["revision"],
            "request_id":control["request_id"],"control_token":control["control_token"],**changes}

    def send(self, **changes):
        self.sent = self.payload(**changes)
        return self.client.post("/api/assistant/chat/stream", json=self.sent, headers=self.headers, buffered=False)

    def rows(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.content_type)
        text = response.get_data(as_text=True)
        return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]

    def assert_final(self, rows, requests, tools):
        self.assertEqual([r["seq"] for r in rows], list(range(1,len(rows)+1)))
        self.assertEqual(rows[-1]["kind"], "final")
        result = rows[-1]["result"]
        self.assertTrue(result["successful_turn"]); self.assertTrue(result["trace_recorded"])
        self.assertEqual(result["activity"]["state"], "COMPLETED")
        self.assertEqual(result["usage"]["request_count"], requests)
        self.assertEqual(result["activity"]["counts"]["tools_executed"], tools)
        self.assertEqual(len(self.bodies), requests)
        self.assertTrue(all(c.closed and c.stream.closed for c in self.clients))

    def test_default_flag_closed_and_candidate_cannot_use_normal_release(self):
        for enabled, released in ((False,True),(True,False)):
            self.setup_app([final_chunks()], enabled=enabled, released=released)
            self.assertFalse(self.stream_profile["available"])
            response = self.send()
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.get_json()["error_code"], "ASSISTANT_STREAMING_NOT_RELEASED")
            self.assertEqual(self.bodies, [])
        self.assertFalse(AssistantStreamingConfig().enabled)

    def test_release_config_is_internal_frozen_and_requires_exact_verified_metadata(self):
        from dataclasses import FrozenInstanceError
        from fishery_ai.assistant import AssistantError
        config=self.config()
        with self.assertRaises(FrozenInstanceError): config.enabled=False
        with self.assertRaises(AssistantError): replace(config.releases[0],qualification_id=None)
        scope=json.loads(config.releases[0].scope_json)
        for changes in ({"identity":["one"]},{"tools":[]},{"response_mode":"normal"}):
            with self.assertRaises(AssistantError):
                replace(config.releases[0],scope_json=json.dumps({**scope,**changes}))

    def test_direct_final_has_provisional_preview_but_only_one_terminal_answer(self):
        self.setup_app([final_chunks()])
        rows = self.rows(self.send())
        self.assert_final(rows,1,0)
        self.assertTrue(any(r["kind"] == "preview" and r["provisional"] for r in rows))
        self.assertEqual(sum(r["kind"] == "final" for r in rows), 1)
        for row in rows[:-1]: self.assertNotIn("result", row)

    def test_single_tool_events_preserve_start_finish_and_no_data(self):
        self.setup_app([tool_chunks(), final_chunks()])
        rows=self.rows(self.send()); self.assert_final(rows,2,1)
        tools=[s for r in rows if r["kind"]=="activity" and r.get("activity")
               for s in r["activity"]["steps"] if s["kind"]=="tool"]
        self.assertTrue(any(s["state"]=="ATTEMPTING" and not s["handler_started"] for s in tools))
        self.assertTrue(any(s["state"]=="RUNNING" and s["handler_started"] for s in tools))
        self.assertTrue(any(s["state"]=="COMPLETED" and s["result_status"]=="NO_DATA" for s in tools))

    def test_double_tool_web_turn_transfers_real_results_and_forces_third_final(self):
        def decide(index, body):
            if index==1: return tool_chunks()
            tools=[m for m in body["messages"] if m["role"]=="tool"]
            if index==2:
                self.assertEqual(json.loads(tools[-1]["content"])["water_quality"]["dissolved_oxygen_mg_l"], 2.2)
                self.assertTrue(all(c.closed for c in self.clients[:-1]))
                return tool_chunks(fixture.KNOWLEDGE,"second",'{"query":"低氧"}')
            self.assertEqual(index,3); self.assertEqual(len(tools),2); self.assertEqual(body["tool_choice"],"none")
            return final_chunks()
        self.setup_app(decide)
        self.app.extensions["fishery_snapshot_store"].set_current(self.reading(oxygen=2.2))
        rows=self.rows(self.send()); self.assert_final(rows,3,2)
        steps=rows[-1]["result"]["activity"]["steps"]
        self.assertEqual([s["tool_name"] for s in steps if s["kind"]=="tool"],list(NAMES))
        self.assertEqual(len(steps),5)

    def test_secret_split_preview_is_withheld_and_raw_protocol_never_public(self):
        frames=[chunk(content="safe " + SECRET[:8]),chunk(content=SECRET[8:] + " end",finish="stop")]
        self.setup_app([frames])
        rows=self.rows(self.send()); self.assert_final(rows,1,0)
        encoded=json.dumps(rows)
        self.assertNotIn(SECRET,encoded)
        self.assertNotIn(SECRET[:8],encoded)
        self.assertIn("[REDACTED]",encoded)
        for value in ("arguments_json","reasoning_content","Authorization","credential_ref"):
            self.assertNotIn(value,encoded)

    def test_reasoning_and_knowledge_arguments_are_not_event_fields(self):
        frames=[tool_chunks(),tool_chunks(fixture.KNOWLEDGE,"second",'{"query":"fictional-private-query"}'),
                [chunk(reasoning="fictional-private-reasoning"),*final_chunks()]]
        self.setup_app(frames)
        rows=self.rows(self.send());self.assert_final(rows,3,2)
        encoded=json.dumps(rows)
        self.assertNotIn("fictional-private-query",encoded)
        self.assertNotIn("fictional-private-reasoning",encoded)
        self.assertNotIn("arguments_json",encoded)

    def test_request_thread_start_failure_closes_claim_with_safe_error(self):
        self.setup_app([final_chunks()])
        with patch("fishery_ai.web.threading.Thread.start",side_effect=RuntimeError("fictional-private-path")):
            response=self.send()
        self.assertEqual(response.status_code,500)
        self.assertEqual(response.get_json()["error_code"],"INTERNAL_ERROR")
        state=self.client.post(f"/api/requests/{self.sent['request_id']}/status",
            json={"control_token":self.sent["control_token"]},headers=self.headers).get_json()
        self.assertEqual(state["state"],"FAILED")
        self.assertEqual(self.bodies,[])

    def test_truncated_or_interrupted_preview_never_final(self):
        for frames,code in (([chunk(content="partial",finish="length")],"STREAM_TRUNCATED"),
                            ([chunk(content="partial")],"STREAM_INTERRUPTED")):
            self.clients.clear();self.bodies.clear()
            self.setup_app([frames])
            rows=self.rows(self.send())
            self.assertEqual(rows[-1]["kind"],"error")
            self.assertFalse(rows[-1]["result"]["successful_turn"])
            self.assertEqual(rows[-1]["result"]["error_code"],code)
            self.assertEqual(rows[-1]["result"]["final_text"],"")

    def test_stop_closes_first_stream_without_followup_or_success(self):
        self.setup_app([[chunk(content="pending"),BLOCK]])
        response=self.send()
        self.assertTrue(self.blocked.wait(2))
        self.client.post(f"/api/requests/{self.sent['request_id']}/cancel",
            json={"control_token":self.sent["control_token"]},headers=self.headers)
        rows=self.rows(response)
        self.assertEqual(rows[-1]["kind"],"cancelled")
        self.assertFalse(rows[-1]["result"]["successful_turn"])
        self.assertEqual(len(self.bodies),1)
        self.assertTrue(self.clients[0].closed and self.clients[0].stream.closed)

    def test_disconnect_cancels_original_io_and_never_reconnects(self):
        self.setup_app([[chunk(content="pending"),BLOCK]])
        response=self.send()
        self.assertTrue(self.blocked.wait(2))
        response.close()
        until=time.monotonic()+2
        while not self.clients[0].closed and time.monotonic()<until: time.sleep(.01)
        self.assertTrue(self.clients[0].closed)
        # SDK closure precedes the final cancellation Trace. Wait for the actual
        # Turn terminal before TemporaryDirectory cleanup (Windows file race).
        state = None
        while time.monotonic()<until:
            state = self.client.post(f"/api/requests/{self.sent['request_id']}/status",
                json={"control_token":self.sent["control_token"]},headers=self.headers).get_json()
            if state["state"] == "CANCELLED": break
            time.sleep(.01)
        self.assertIsNotNone(state)
        self.assertEqual(state["state"],"CANCELLED")
        self.assertEqual(state["error_code"],"USER_CANCELLED")
        self.assertEqual(len(self.bodies),1)

    def test_stop_during_followup_streams_preserves_steps_but_never_final(self):
        for index in (2,3):
            self.clients.clear(); self.bodies.clear(); self.blocked.clear()
            frames=[tool_chunks()]
            if index==3: frames.append(tool_chunks(fixture.KNOWLEDGE,"second",'{"query":"低氧"}'))
            frames.append([chunk(content="pending"),BLOCK])
            self.setup_app(frames)
            response=self.send(); self.assertTrue(self.blocked.wait(2))
            self.client.post(f"/api/requests/{self.sent['request_id']}/cancel",
                json={"control_token":self.sent["control_token"]},headers=self.headers)
            rows=self.rows(response)
            self.assertEqual(rows[-1]["kind"],"cancelled")
            self.assertEqual(len(self.bodies),index)
            self.assertEqual(rows[-1]["result"]["activity"]["counts"]["tools_executed"],index-1)
            self.assertFalse(rows[-1]["result"]["successful_turn"])

    def test_whole_turn_deadline_and_event_budget_fail_closed(self):
        self.setup_app([[chunk(content="pending"),BLOCK]])
        from fishery_ai.assistant import AssistantService
        send=AssistantService.send
        def short_deadline(service,*args,**kwargs):
            service._turn_timeout_s=.05
            return send(service,*args,**kwargs)
        with patch.object(AssistantService,"send",short_deadline):
            rows=self.rows(self.send())
        self.assertEqual(rows[-1]["result"]["error_code"],"TOTAL_TIMEOUT")
        self.assertFalse(rows[-1]["result"]["successful_turn"])
        self.clients.clear();self.bodies.clear()
        self.setup_app([final_chunks()])
        with patch.object(AssistantEventChannel,"MAX_EVENTS",2):
            rows=self.rows(self.send())
        self.assertEqual(rows[-1]["kind"],"error")
        self.assertFalse(rows[-1]["result"]["successful_turn"])
        self.assertEqual(len(self.bodies),0)

    def test_unexposed_or_multiple_calls_fail_before_any_handler(self):
        from tests.providers.test_streaming_tool_assembler import delta
        for frames in (tool_chunks(fixture.SCORE),
            [chunk([delta("{}",name=fixture.QUERY,identifier="one",call_type="function"),
                    delta("{}",name=fixture.KNOWLEDGE,identifier="two",call_type="function",index=1)])]):
            self.clients.clear();self.bodies.clear()
            self.setup_app([frames])
            rows=self.rows(self.send())
            self.assertEqual(rows[-1]["kind"],"error")
            self.assertFalse(rows[-1]["result"]["successful_turn"])
            self.assertEqual(rows[-1]["result"]["activity"]["counts"]["tools_executed"],0)
            self.assertEqual(len(self.bodies),1)

    def test_revision_epoch_policy_and_browser_transport_overrides_block_preflight(self):
        self.setup_app([final_chunks()])
        for changes,code in (({"execution_profile_revision":"0"*64},"ASSISTANT_EXECUTION_PROFILE_CHANGED"),
            ({"epoch":"old"},"ASSISTANT_SESSION_EXPIRED"),({"mode":"BOUNDED_MULTI_ROUND"},"INVALID_ASSISTANT_REQUEST"),
            ({"budget":3},"INVALID_ASSISTANT_REQUEST"),({"confirm_network":False},"NETWORK_CONFIRMATION_REQUIRED")):
            response=self.send(**changes)
            self.assertEqual(response.get_json()["error_code"],code)
        self.assertEqual(self.bodies,[])
        self.app.extensions["fishery_tool_policy_store"].save({"schema_version":1,"modes":{
            "analysis":{"selected_tools":[]},"assistant":{"selected_tools":[fixture.QUERY]}}})
        self.assertEqual(self.send().get_json()["error_code"],"ASSISTANT_STREAMING_NOT_RELEASED")

    def test_claimed_request_cannot_generate_again(self):
        self.setup_app([final_chunks()])
        self.rows(self.send())
        response=self.client.post("/api/assistant/chat/stream",json=self.sent,headers=self.headers)
        self.assertEqual(response.status_code,409)
        self.assertEqual(response.get_json()["error_code"],"REQUEST_ALREADY_EXECUTED")
        self.assertEqual(len(self.bodies),1)

    def test_trace_failure_never_publishes_final_success(self):
        self.setup_app([final_chunks()])
        with patch("fishery_ai.observability.JsonlTraceSink.record_assistant",side_effect=OSError("fictional-private-path")):
            rows=self.rows(self.send())
        self.assertEqual(rows[-1]["kind"],"error")
        self.assertEqual(rows[-1]["result"]["error_code"],"TRACE_WRITE_ERROR")
        self.assertNotIn("fictional-private-path",json.dumps(rows))

    def test_third_tool_call_is_refused_without_fourth_request(self):
        self.setup_app([tool_chunks(),tool_chunks(fixture.KNOWLEDGE,"second",'{"query":"DO"}'),tool_chunks(identifier="third")])
        rows=self.rows(self.send())
        self.assertEqual(rows[-1]["result"]["error_code"],"TOOL_ROUND_LIMIT")
        self.assertEqual(len(self.bodies),3)

    def test_normal_remains_default_and_uses_original_complete_transport(self):
        self.setup_app([final_chunks()])
        self.assertEqual(self.bootstrap["fixed_mode"]["response_mode"],"normal")
        self.factory.return_value=fixture.RecordingGateway(fixture.final())
        payload=self.payload()
        normal=next(p["execution_profile"] for p in self.bootstrap["presets"] if p["preset_id"]==PRESET)
        payload["execution_profile_revision"]=normal["revision"]
        response=self.client.post("/api/assistant/chat",json=payload,headers=self.headers)
        self.assertTrue(response.get_json()["result"]["successful_turn"])
        self.assertEqual(len(self.bodies),0)

    def test_csrf_origin_host_and_get_reconnect_are_rejected(self):
        self.setup_app([final_chunks()])
        payload=self.payload()
        for headers in ({},{**self.headers,"Origin":"http://evil.invalid"}):
            response=self.client.post("/api/assistant/chat/stream",json=payload,headers=headers)
            self.assertGreaterEqual(response.status_code,400)
        response=self.client.post("/api/assistant/chat/stream",json=payload,headers=self.headers,base_url="http://evil.invalid")
        self.assertGreaterEqual(response.status_code,400)
        self.assertEqual(self.client.get("/api/assistant/chat/stream").status_code,405)
        self.assertEqual(len(self.bodies),0)

    def test_three_local_trials_exact_budget_direct_single_double_paths(self):
        presets = ((PRESET,512), ("deepseek-flash-r1",512), ("ollama-qwen35-4b-r1",512))
        for preset, tokens in presets:
            for count in (0,1,2):
                with self.subTest(preset=preset, tools=count):
                    self.clients.clear(); self.bodies.clear()
                    frames = ([tool_chunks()] if count else []) + ([tool_chunks(fixture.KNOWLEDGE,"second",'{"query":"DO"}')] if count == 2 else []) + [final_chunks()]
                    self.setup_app(frames, preset=preset, stored_config=True)
                    self.assertTrue(self.stream_profile["available"])
                    self.assertEqual(self.stream_profile["release_status"], "local_experimental")
                    self.assertEqual(self.stream_profile["max_output_tokens"], tokens)
                    rows = self.rows(self.send())
                    self.assert_final(rows,count+1,count)
                    self.assertEqual(rows[-1]["result"]["transport"], "streaming")
                    self.assertTrue(all(b["max_tokens"] == tokens and b["stream"] for b in self.bodies))
                    self.assertEqual(self.bodies[-1].get("tool_choice"), "none" if count == 2 else "auto")
                    for body in self.bodies:
                        self.assertEqual([t["function"]["name"] for t in body["tools"]], list(NAMES))

    def test_transport_budget_is_not_generation_capability_and_invalid_values_fail_before_io(self):
        self.setup_app([final_chunks()],stored_config=True)
        self.rows(self.send())
        runtime=self.runtimes[0]
        self.assertIsNone(runtime.default_generation.max_output_tokens)
        request=ModelRequest(Mode.CHAT,(ModelMessage("user","fixture"),))
        for value in (True,False,0,513,256.5,"256"):
            with self.assertRaises(GatewayError) as error:
                OpenAICompatibleAdapter._kwargs(request,replace(runtime,transport_output_token_limit=value),
                                                stream=True,_assemble_tools=True)
            self.assertEqual(error.exception.code,"INVALID_STREAMING_OUTPUT_BUDGET")
        with self.assertRaises(GatewayError):
            OpenAICompatibleAdapter._kwargs(request,runtime,stream=False)
        self.assertEqual(len(self.bodies),1)

    def test_score_handler_streaming_compatible_offline_but_three_tool_product_scope_stays_candidate(self):
        config=load_assistant_streaming_config()
        record=next(r for r in config.releases if json.loads(r.scope_json)["preset_id"]==PRESET
                    and r.status=="candidate")
        # Offline authorization fixture only, not a product publication or model evidence.
        temporary=AssistantStreamingConfig(True,(replace(record,status="local_experimental"),))
        self.setup_app([tool_chunks(fixture.SCORE,"score","{}"),final_chunks()],config_override=temporary)
        names=(fixture.QUERY,fixture.SCORE,fixture.KNOWLEDGE)
        self.app.extensions["fishery_tool_policy_store"].save({"schema_version":1,
            "modes":{"analysis":{"selected_tools":[]},"assistant":{"selected_tools":list(names)}}})
        self.store.set_current(self.reading())
        bootstrap=self.client.get("/api/assistant/bootstrap").get_json()
        self.stream_profile=next(p for p in bootstrap["presets"] if p["preset_id"]==PRESET)["streaming_profile"]
        rows=self.rows(self.send())
        self.assert_final(rows,2,1)
        tool=next(s for s in rows[-1]["result"]["activity"]["steps"] if s["kind"]=="tool")
        self.assertEqual(tool["tool_name"],fixture.SCORE); self.assertTrue(tool["experimental"])
        self.assertIn("score",json.loads(self.bodies[1]["messages"][-1]["content"]))
        self.assertEqual(record.status,"candidate")

    def test_trial_config_strict_budget_no_fake_qualification_and_revision(self):
        from fishery_ai.assistant import AssistantError
        config = load_assistant_streaming_config()
        self.assertFalse(config.enabled)
        self.assertEqual(len(config.releases),6)
        record=config.releases[0]
        self.assertEqual(record.status,"local_experimental")
        self.assertIsNone(record.qualification_id); self.assertIsNone(record.validated_at)
        for value in (True,False,0,513,256.0,"256",None):
            with self.assertRaises(AssistantError): replace(record,max_output_tokens=value)
        with self.assertRaises(AssistantError): replace(record,qualification_id="FAKE")
        registry=ToolRegistry(self.reader,DiagnosisService(),knowledge=fixture.FakeKnowledgeService())
        policy=ToolPolicy("assistant",True,NAMES)
        def resolved(c):
            return resolve_streaming_profile(c,assistant_profile(PRESET),policy,registry,
                epoch="fixed",projection=DEFAULT_HISTORY_PROJECTION)
        one=AssistantStreamingConfig(True,(record,))
        two=AssistantStreamingConfig(True,(replace(record,max_output_tokens=257),))
        self.assertNotEqual(resolved(one)["revision"],resolved(two)["revision"])
        self.assertFalse(resolved(replace(one,enabled=False))["available"])

    def test_three_tools_candidate_other_combinations_and_request_budget_override_blocked(self):
        self.setup_app([final_chunks()],stored_config=True)
        for names in ((fixture.QUERY,fixture.SCORE,fixture.KNOWLEDGE),(fixture.QUERY,), (fixture.SCORE,fixture.KNOWLEDGE)):
            self.app.extensions["fishery_tool_policy_store"].save({"schema_version":1,
                "modes":{"analysis":{"selected_tools":[]},"assistant":{"selected_tools":list(names)}}})
            bootstrap=self.client.get("/api/assistant/bootstrap").get_json()
            state=next(p for p in bootstrap["presets"] if p["preset_id"]==PRESET)["streaming_profile"]
            self.assertFalse(state["available"])
            response=self.send(execution_profile_revision=state["revision"])
            self.assertEqual(response.get_json()["error_code"],"ASSISTANT_STREAMING_NOT_RELEASED")
        self.assertEqual(self.bodies,[])

    def test_normal_streaming_switch_preserves_same_completed_history_without_protocol(self):
        self.setup_app([final_chunks()],stored_config=True)
        adapter=self.factory.return_value
        history=[{"user":"旧问题","assistant":"旧解释","completed_at":"2026-10-01T00:00:00Z"}]
        gateway=fixture.RecordingGateway(fixture.final())
        self.factory.return_value=gateway
        payload=self.payload(history=history)
        normal=next(p["execution_profile"] for p in self.bootstrap["presets"] if p["preset_id"]==PRESET)
        payload["execution_profile_revision"]=normal["revision"]
        result=self.client.post("/api/assistant/chat",json=payload,headers=self.headers).get_json()["result"]
        self.assertEqual(result["transport"],"normal")
        self.factory.return_value=adapter
        rows=self.rows(self.send(history=history))
        self.assert_final(rows,1,0)
        projected=gateway.requests[0].messages[1].content
        self.assertEqual(self.bodies[0]["messages"][1]["content"],projected)
        self.assertFalse(any(m["role"]=="tool" for m in self.bodies[0]["messages"]))
        self.assertEqual(history[0]["assistant"],"旧解释")

    def test_cli_trial_flag_only_explicit_web_start(self):
        from fishery_ai.__main__ import main
        with patch("sys.argv",["fishery_ai","web","--assistant-streaming-trial"]), patch("fishery_ai.web.run_web") as run:
            main()
        run.assert_called_once_with(port=8765,assistant_streaming_trial=True)
        with patch("sys.argv",["fishery_ai","web"]), patch("fishery_ai.web.run_web") as run:
            main()
        run.assert_called_once_with(port=8765,assistant_streaming_trial=False)
        from fishery_ai.web import run_web
        location=NS(env_path=self.root / "fictional-private" / ".env")
        with patch("fishery_ai.web.private_project_location",return_value=location), \
             patch("fishery_ai.web.private_manual_location",return_value=location), \
             patch("fishery_ai.web.CredentialStore"), patch("fishery_ai.web.ProjectEnvWriter"), \
             patch("fishery_ai.web.create_app") as factory, patch("builtins.print"):
            run_web(assistant_streaming_trial=True)
            config=factory.call_args.kwargs["assistant_streaming_config"]
            self.assertTrue(config.enabled)
            self.assertEqual(sum(r.status=="local_experimental" for r in config.releases),3)
            self.assertIs(factory.return_value.run.call_args.kwargs["load_dotenv"],False)
            run_web()
            self.assertFalse(factory.call_args.kwargs["assistant_streaming_config"].enabled)
