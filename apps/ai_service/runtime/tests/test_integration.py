"""Independent Assistant + Fake SDK + authoritative Monitoring/Knowledge assembly."""
from datetime import datetime, timezone
from dataclasses import replace
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from apps.ai_backend.assistant_events import AssistantEventChannel
from apps.ai_backend.contracts import Status
from apps.ai_backend.credentials import CredentialStore
from apps.ai_backend.execution import current_handle
from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.observability import JsonlTraceSink
from apps.ai_backend.openai_compatible_adapter import OpenAICompatibleAdapter
from apps.ai_backend.tool_conversation import ToolModelTransport
from apps.ai_backend.tests import test_execution as control_fixture
from apps.ai_backend.tests.support import FakeSDK, sdk_tool, sdk_final, tool_chunks, final_chunks
from apps.ai_service.runtime import assistant, sources
from apps.ai_service.runtime.assembly import IndependentAssistantService, PRESETS
from apps.ai_service.runtime.execution import load_execution_config
from apps.ai_service.runtime.streaming import load_streaming_config
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.simulator.generator import Simulator


WATER='get_current_water_quality'
KNOWLEDGE='search_fishery_knowledge'


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        control_fixture.ExecutionTests.setUp(self)
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.now=datetime(2026,10,16,tzinfo=timezone.utc)
        self.monitoring=MonitoringService(MonitoringRepository(self.root/'monitoring.sqlite3'),
            device_names={'pond-a':'A','pond-b':'B'},clock=lambda:self.now)
        batch=Simulator(start=self.now,session_id='fixture-session',device_id='pond-a').advance()
        self.now=datetime.fromisoformat(batch['timestamp'])
        batch['water']['metrics']['dissolved_oxygen_mg_l'].update(mean=2.2,min=2.2,max=2.2,latest=2.2)
        self.monitoring.ingest(batch);self.batch_id=batch['batch_id']
        self.profile=assistant.assistant_profile(PRESETS[0])
        self.traces=JsonlTraceSink(self.root/'traces.jsonl',tool_names=(WATER,KNOWLEDGE))

    def setup_service(self, path, transport, *, close=None, third_error=None):
        def plan(index, body):
            if path == 'direct': kind='final'
            elif index == 1: kind='water'
            elif index == 2:
                payloads=[json.loads(m['content']) for m in body['messages'] if m['role']=='tool']
                self.assertEqual(len(payloads),1)
                self.assertEqual(payloads[0]['device_id'],'pond-a')
                self.assertEqual(payloads[0]['batch_id'],self.batch_id)
                self.assertEqual(payloads[0]['water_quality']['dissolved_oxygen_mg_l'],2.2)
                kind='knowledge' if path == 'double' else 'final'
            else:
                self.assertEqual(index,3);self.assertEqual(body['tool_choice'],'none')
                results=[json.loads(m['content']) for m in body['messages'] if m['role']=='tool']
                self.assertEqual(len(results),2)
                self.assertIn(results[1]['status'],('OK','NO_MATCH'))
                if third_error:return third_error
                kind='final'
            if transport == ToolModelTransport.STREAMING:
                self.assertTrue(body['stream']);self.assertEqual(body['max_tokens'],512)
                return (tool_chunks(WATER) if kind=='water' else
                    tool_chunks(KNOWLEDGE,'call_2','{"query":"鳗鲡低氧表现"}') if kind=='knowledge' else final_chunks())
            self.assertNotIn('stream',body)
            return (sdk_tool(WATER) if kind=='water' else
                sdk_tool(KNOWLEDGE,'call_2','{"query":"鳗鲡低氧表现"}') if kind=='knowledge' else sdk_final())
        self.sdk=FakeSDK(plan,model=self.profile.model,on_close=close)
        self.backend=IndependentAssistantService(self.monitoring,
            credentials=CredentialStore(process_env={self.profile.credential_ref:'fictional-fixture-credential'}),
            traces=self.traces,policy_directory=self.root/'policies',
            gateway_factory=lambda:OpenAICompatibleAdapter(async_client_factory=self.sdk.factory),
            execution_config=load_execution_config(enable_trial=True),
            streaming_config=load_streaming_config(enable_trial=True))
        policy=self.backend.policy_store.default_selections()
        policy['modes']['assistant']['selected_tools']=[WATER,KNOWLEDGE]
        self.backend.policy_store.save(policy)
        self.handle=self.backend.request_registry().create()

    def envelope(self,transport):
        config=self.backend.bootstrap('pond-a')
        item=config['presets'][0]
        return {'preset_id':PRESETS[0],'question':'隔离离线问题','history':[],
            'device_id':'pond-a','epoch':config['epoch'],'confirm_network':True,
            'revision':item['streaming']['revision'] if transport==ToolModelTransport.STREAMING else item['revision']}

    def send(self, transport):
        collected=[];original=assistant.AssistantService.send
        def observe(service,request,runtime):
            self.assertIsInstance(runtime, __import__('apps.ai_backend.model_gateway',fromlist=['RuntimeSnapshot']).RuntimeSnapshot)
            self.assertIs(current_handle(),self.handle)
            result=original(service,request,runtime);collected.append(result);return result
        prepared=self.backend.prepare_turn(self.envelope(transport),transport=transport)
        with patch.object(assistant.AssistantService,'send',observe):
            value=self.backend.execute_turn(prepared,self.handle)
        return value,collected[0]

    def test_normal_and_streaming_direct_single_double_results_steps_ledger_usage(self):
        for transport in ToolModelTransport:
            for path,requests,tools in [('direct',1,0),('single',2,1),('double',3,2)]:
                with self.subTest(transport=transport,path=path):
                    self.setup_service(path,transport)
                    with patch.object(self.monitoring,'capture_water',wraps=self.monitoring.capture_water) as capture:
                        value,result=self.send(transport)
                    self.assertTrue(value['successful_turn'])
                    self.assertEqual(len(self.sdk.bodies),requests)
                    self.assertEqual(value['activity']['counts'],{'model_requests_started':requests,
                        'tool_attempts':tools,'tools_executed':tools})
                    self.assertEqual(len(result.source_ledger.entries),tools)
                    self.assertEqual(value['usage']['usage']['total_tokens'],requests*5)
                    self.assertEqual(capture.call_count,1 if tools else 0)
                    self.assertEqual(self.handle.state,'COMPLETED')
                    self.assertTrue(all(c.closed and (c.stream is None or c.stream.closed) for c in self.sdk.clients))
                    self.assertEqual(value['activity']['steps'],self.handle.public_info()['activity']['steps'])
                    self.assertNotIn('source_ledger',value)

    def test_stream_cleanup_precedes_both_handlers_and_second_model_decides_from_result(self):
        self.setup_service('double',ToolModelTransport.STREAMING)
        original=self.monitoring.capture_water
        def captured(device):
            self.assertTrue(self.sdk.clients[-1].closed and self.sdk.clients[-1].stream.closed)
            return original(device)
        with patch.object(self.monitoring,'capture_water',side_effect=captured):
            value,result=self.send(ToolModelTransport.STREAMING)
        self.assertTrue(value['successful_turn'])
        self.assertEqual([e.receipt.tool_name for e in result.source_ledger.entries],[WATER,KNOWLEDGE])
        self.assertTrue(sources.requirement_satisfied_by_ledger(
            sources.SourceRequirement.PROJECT_KNOWLEDGE_SEARCH,result.source_ledger))

    def test_stop_or_deadline_at_each_request_cleanup_never_commits_success(self):
        for transport in ToolModelTransport:
            for index in (0,1,2):
                for code in ('USER_CANCELLED','TOTAL_TIMEOUT'):
                    with self.subTest(transport=transport,index=index,code=code):
                        def close(i):
                            if i==index:
                                if code=='USER_CANCELLED':self.handle.cancel()
                                else:self.handle._deadline=0.0
                        self.setup_service('double',transport,close=close)
                        value,result=self.send(transport)
                        self.assertEqual(value['error_code'],code)
                        self.assertFalse(value['successful_turn']);self.assertEqual(value['final_text'],'')
                        self.assertLessEqual(len(self.sdk.bodies),index+1)
                        self.assertTrue(all(c.closed for c in self.sdk.clients))

    def test_stream_truncation_and_disconnect_keep_prior_receipts_not_success(self):
        for frames,code in [(final_chunks(finish='length'),'STREAM_TRUNCATED'),
                            (final_chunks()[:1],'STREAM_INCOMPLETE'),
                            ([RuntimeError('private-fixture-failure')],'MODEL_REQUEST_ERROR')]:
            self.setup_service('double',ToolModelTransport.STREAMING,third_error=frames)
            value,result=self.send(ToolModelTransport.STREAMING)
            self.assertFalse(value['successful_turn'])
            self.assertEqual(value['final_text'],'')
            self.assertEqual(len(result.source_ledger.entries),2)
            # Exact error mapping is asserted by the copied adapter protocol suite.
            self.assertIsNotNone(value['error_code'])

    def test_sse_event_order_preview_is_provisional_and_has_only_one_terminal(self):
        self.setup_service('double',ToolModelTransport.STREAMING)
        channel=AssistantEventChannel(self.handle,self.backend.epoch);self.handle._event_channel=channel
        value,_=self.send(ToolModelTransport.STREAMING)
        channel.emit('final',{'result':value},terminal=True)
        channel.emit('final',{'result':value},terminal=True)
        rows=[json.loads(frame.split('data: ',1)[1]) for frame in channel.events() if 'data: ' in frame]
        self.assertEqual([r['seq'] for r in rows],list(range(1,len(rows)+1)))
        self.assertEqual(sum(r['kind']=='final' for r in rows),1)
        self.assertTrue(all(r['provisional'] for r in rows if r['kind']=='preview'))
        public=json.dumps(rows,ensure_ascii=False)
        for forbidden in ('fictional-fixture-credential','鳗鲡低氧表现','fictional-background','arguments_json','reasoning_content'):
            self.assertNotIn(forbidden,public)

    def test_scope_policy_revision_and_replay_refused_before_new_model_request(self):
        self.setup_service('double',ToolModelTransport.STREAMING)
        envelope=self.envelope(ToolModelTransport.STREAMING)
        data=self.backend.policy_store.load();data['modes']['assistant']['selected_tools']=[WATER]
        self.backend.policy_store.save(data)
        with self.assertRaises(GatewayError) as caught:
            self.backend.prepare_turn(envelope,transport=ToolModelTransport.STREAMING)
        self.assertEqual(caught.exception.code,'ASSISTANT_EXECUTION_PROFILE_CHANGED')
        fresh=self.envelope(ToolModelTransport.STREAMING)
        with self.assertRaises(GatewayError) as caught:
            self.backend.prepare_turn(fresh,transport=ToolModelTransport.STREAMING)
        self.assertEqual(caught.exception.code,'ASSISTANT_STREAMING_NOT_RELEASED')
        self.assertEqual(self.sdk.bodies,[])
        self.setup_service('direct',ToolModelTransport.NORMAL)
        prepared=self.backend.prepare_turn(self.envelope(ToolModelTransport.NORMAL))
        execute=self.backend.claim_turn(prepared,self.handle);execute()
        with self.assertRaises(GatewayError):execute()
        with self.assertRaises(GatewayError):self.backend.claim_turn(prepared,self.handle)
        self.assertEqual(len(self.sdk.bodies),1)

    def test_fresh_business_assembly_blocks_all_legacy_llm_execution_modules(self):
        code = '''
import importlib.abc,sys,unittest
sys.path.insert(0,REPO_ROOT)
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,name,*a):
  if name.startswith(('fishery_ai.assistant','fishery_ai.model_gateway','fishery_ai.execution',
    'fishery_ai.openai_compatible_adapter','fishery_ai.tools','fishery_ai.credentials',
    'fishery_ai.presets','fishery_ai.observability','fishery_ai.protocol_specs','fishery_ai.tool_conversation')):
   raise AssertionError('old LLM Runtime forbidden: '+name)
sys.meta_path.insert(0,Block())
from apps.ai_service.runtime.tests.test_integration import IntegrationTests
result=unittest.TextTestRunner().run(unittest.TestSuite([IntegrationTests(
 'test_normal_and_streaming_direct_single_double_results_steps_ledger_usage')]))
assert result.wasSuccessful()
'''.replace('REPO_ROOT',repr(str(Path(__file__).resolve().parents[4])))
        result=subprocess.run([sys.executable,'-I','-c',code],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)

