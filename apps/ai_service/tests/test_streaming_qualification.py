"""Management qualification uses formal service + SQLite + Fake SDK; no model sockets."""
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from io import StringIO
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from apps.ai_service.runtime.assistant import assistant_profile, MULTI_ROUND_SYSTEM_INSTRUCTION
from apps.ai_backend.credentials import CredentialStore, CredentialFileError
from apps.ai_backend.execution import RequestHandle
from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.tool_conversation import ToolModelTransport
from apps.ai_service.development import streaming_qualification as q
import apps.ai_backend.tests.test_execution as execution_fixture
from apps.ai_backend.tests.test_assembler import chunk, delta

ROOT = Path(__file__).resolve().parents[3]
SECRET = 'fictional-management-qualification-secret'
ANSWER = 'fictional-answer-do-not-save'
QUERY = 'fictional-query-do-not-save'
EVIDENCE = 'fictional-evidence-do-not-save'
USAGE = NS(prompt_tokens=2, completion_tokens=3, total_tokens=5)


def tool(name=q.WATER, call_id='first', arguments='{}'):
    n = len(arguments)//2
    return [chunk([delta(name=name, identifier=call_id, call_type='function')]),
        chunk([delta(arguments[:n])]), chunk([delta(arguments[n:])]), chunk(finish='tool_calls', usage=USAGE)]


def final(reason='stop'):
    return [chunk(content=ANSWER+' '+SECRET+'\x1b[31m', finish=reason, usage=USAGE)]


class StreamingQualificationTests(unittest.TestCase):
    def setUp(self):
        execution_fixture.ExecutionTests.setUp(self)
        temporary = TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.credentials = CredentialStore(process_env={'DASHSCOPE_API_KEY': SECRET})
        self.bodies, self.clients, self.runtimes = [], [], []

    def factory(self, frames, *, close_error=False):
        owner = self
        class Stream:
            def __init__(self, items):self.items,self.closed=items,False
            def __aiter__(self):return self.events()
            async def events(self):
                for item in self.items:
                    if callable(item):item=item()
                    if isinstance(item,Exception):raise item
                    item.model=assistant_profile(q.STREAMING_PRESET).model
                    yield item
            async def close(self):
                if close_error:raise RuntimeError('fictional-private-cleanup')
                self.closed=True
        class Client:
            def __init__(self,index):
                self.index,self.closed,self.stream=index,False,None
                self.chat=NS(completions=NS(create=self.create))
            async def create(self,**body):
                owner.bodies.append(body)
                self.stream=Stream(frames(self.index,body) if callable(frames) else frames[self.index-1])
                return self.stream
            async def close(self):self.closed=True
        def sdk(runtime,remaining):
            self.runtimes.append(runtime)
            self.assertEqual(runtime.max_retries,0);self.assertEqual(runtime.total_timeout_s,120)
            self.assertEqual(runtime.transport_output_token_limit,512);self.assertTrue(0<remaining<=120)
            client=Client(len(self.clients)+1);self.clients.append(client);return client
        return lambda *a,**k:q._Adapter(*a,**k,async_client_factory=sdk)

    def run_case(self,case,frames,**options):
        approved=q.plan(case)
        return q.run(case,self.root,confirm_network=True,approved_plan_sha256=approved['plan_sha256'],
            credential_store=self.credentials,adapter_factory=self.factory(frames,close_error=options.pop('close_error',False)),**options)

    def test_plan_is_inert_exact_local_scope_and_three_cases_are_independent(self):
        with patch.object(q,'_credentials',side_effect=AssertionError('no credentials')), \
             patch.object(q,'MonitoringRepository',side_effect=AssertionError('no SQLite')), \
             patch.object(q,'_Adapter',side_effect=AssertionError('no SDK')):
            plans=[q.plan(c.case_id) for c in q.CASES]
            report=q.run('low-oxygen',self.root)
        self.assertEqual(report['actual_network_requests'],0)
        self.assertFalse(list(self.root.iterdir()))
        self.assertEqual(len({p['plan_sha256'] for p in plans}),3)
        self.assertEqual(len({p['scope_sha256'] for p in plans}),1)
        for p in plans:
            self.assertEqual(p['scope']['runtime']['identity'],['dashscope','openai_chat',
                'https://dashscope.aliyuncs.com/compatible-mode/v1','qwen3.8-flash'])
            self.assertEqual(p['scope']['runtime']['protocol_spec']['spec_id'],'dashscope_chat')
            self.assertEqual(p['release_status'],'local_experimental');self.assertFalse(p['web_flag_enabled'])
            self.assertEqual(p['max_output_tokens'],512);self.assertEqual(p['turn_deadline_s'],120)
            self.assertEqual(p['scope']['data_bindings']['water'],'management-current-water@1')
        self.assertEqual([p['expected_requests'] for p in plans],[1,2,3])

    def test_scope_identity_protocol_prompt_history_definitions_bindings_and_budget_fail_before_credentials(self):
        config=q.load_streaming_config()
        for section,key,value in [('runtime','identity',['another','openai_chat','https://invalid.test','model']),
            ('runtime','protocol_spec',{'spec_id':'changed','version':'2'}),('runtime','prompt_sha256','0'*64),
            ('runtime','history_version','2'),('runtime','tool_definitions_sha256','0'*64),
            ('runtime','tools',[q.WATER]),('data','water','management-current-water@2')]:
            runtime=json.loads(config.releases[0].runtime.scope_json)
            data=json.loads(config.releases[0].data_bindings_json)
            (runtime if section=='runtime' else data)[key]=value
            with self.assertRaises((q.QualificationError,GatewayError)):
                record=replace(config.releases[0],runtime=replace(config.releases[0].runtime,scope_json=q._json(runtime)),
                    data_bindings_json=q._json(data))
                with patch.object(q,'load_streaming_config',return_value=replace(config,releases=(record,))):
                    q.plan('current-water')
        record=replace(config.releases[0],runtime=replace(config.releases[0].runtime,max_output_tokens=256))
        with patch.object(q,'load_streaming_config',return_value=replace(config,releases=(record,))):
            with self.assertRaisesRegex(q.QualificationError,'BUDGET_MISMATCH'):q.plan('current-water')

    def test_single_case_approval_hash_is_mandatory_and_cannot_be_reused_for_another_case(self):
        for digest in (None,'bad',q.plan('direct-final')['plan_sha256']):
            with patch.object(q,'_credentials',side_effect=AssertionError('no credentials')):
                with self.assertRaisesRegex(q.QualificationError,'PLAN_CHANGED'):
                    q.run('current-water',self.root,confirm_network=True,approved_plan_sha256=digest)
        self.assertFalse(list(self.root.iterdir()))

    def test_direct_final_uses_formal_prompt_and_never_reads_water(self):
        with patch.object(q.MonitoringService,'capture_water',side_effect=AssertionError('no proactive Tool')):
            report=self.run_case('direct-final',[final()])
        self.assertTrue(report['technical_success'],report['error_code'])
        self.assertEqual(self.bodies[0]['messages'][0]['content'],MULTI_ROUND_SYSTEM_INSTRUCTION)
        self.assertEqual(len(self.bodies[0]['messages']),2)
        self.assertEqual(report['ledger'],{'entries':[]})
        self.assertFalse(report['web_can_send_after_probe']);self.assertFalse(report['http_sse_exercised'])
        self.assertEqual(report['qualification_verdict'],'PENDING_MANUAL_REVIEW')

    def test_current_water_result_is_management_sqlite_and_received_after_sdk_cleanup(self):
        def decide(index,body):
            if index==1:return tool()
            self.assertTrue(self.clients[0].closed and self.clients[0].stream.closed)
            payload=json.loads(next(m['content'] for m in body['messages'] if m['role']=='tool'))
            self.assertEqual(payload['projection_version'],'management-current-water@1')
            self.assertEqual(payload['device_id'],q.DEVICE)
            self.assertEqual(payload['water_quality']['dissolved_oxygen_mg_l'],6.4)
            return final()
        report=self.run_case('current-water',decide)
        self.assertTrue(report['success'],report['error_code'])
        self.assertTrue(report['product_commit_gate_passed'])
        self.assertEqual(len(report['ledger']['entries']),1)
        self.assertTrue(report['executions'][0]['observation']['device_matches'])
        self.assertTrue(report['executions'][0]['executed_after_stream_cleanup'])
        self.assertTrue(report['source_binding_matches'])

    def test_internal_candidate_probe_does_not_unlock_prepare_turn_or_change_web_policy(self):
        execute=q.ManagementAssistantService.execute_turn
        def guarded(service,prepared,handle):
            public=service.bootstrap(q.DEVICE)['presets'][0]['streaming']
            self.assertFalse(public['can_send']);self.assertEqual(public['release_status'],'local_experimental')
            self.assertTrue(prepared.execution.can_send)
            value={'question':'fixture','preset_id':q.STREAMING_PRESET,'device_id':q.DEVICE,
                'epoch':service.epoch,'revision':public['revision'],'confirm_network':True,'history':[]}
            with self.assertRaisesRegex(GatewayError,'ASSISTANT_STREAMING_NOT_RELEASED'):
                service.prepare_turn(value,transport=ToolModelTransport.STREAMING)
            return execute(service,prepared,handle)
        with patch.object(q.ManagementAssistantService,'execute_turn',guarded):
            report=self.run_case('direct-final',[final()])
        self.assertTrue(report['success']);self.assertFalse((self.root/'outputs/tool-policies').exists())

    def test_low_oxygen_result_drives_second_tool_three_requests_ledger_usage_and_no_product_mutation(self):
        def decide(index,body):
            if index==1:return tool()
            results=[json.loads(m['content']) for m in body['messages'] if m['role']=='tool']
            self.assertEqual(results[0]['water_quality']['dissolved_oxygen_mg_l'],2.2)
            if index==2:return tool(q.KNOWLEDGE,'second',json.dumps({'query':QUERY}))
            self.assertEqual(len(results),2);self.assertEqual(body['tool_choice'],'none')
            return final()
        config_before=(ROOT/'apps/ai_service/resources/assistant_streaming.json').read_bytes()
        report=self.run_case('low-oxygen',decide)
        self.assertTrue(report['success'],report['error_code'])
        self.assertEqual((report['request_count'],report['transport_attempts'],report['actual_network_requests']),(3,3,0))
        self.assertEqual(report['usage']['usage']['total_tokens'],15)
        self.assertTrue(report['provider_protocol_verified']);self.assertTrue(report['result_context_matches'])
        self.assertEqual(len(report['ledger']['entries']),2)
        self.assertTrue(report['ledger']['entries'][0]['receipt']['has_observation'])
        self.assertTrue(report['ledger']['entries'][1]['receipt']['project_search_completed'])
        self.assertTrue(all(c.closed and c.stream.closed for c in self.clients))
        self.assertTrue(all(r is self.runtimes[0] for r in self.runtimes))
        self.assertTrue(all(b['stream'] and b['max_tokens']==512 for b in self.bodies))
        self.assertEqual(config_before,(ROOT/'apps/ai_service/resources/assistant_streaming.json').read_bytes())
        self.assertFalse(report['web_can_send_after_probe'])
        text=json.dumps(report)
        for excluded in (SECRET,ANSWER,QUERY,EVIDENCE,MULTI_ROUND_SYSTEM_INSTRUCTION,'Authorization','control_token'):
            self.assertNotIn(excluded,text)
        self.assertFalse(any((self.root/'outputs/assistant-qualification/.management-work').iterdir()))

    def test_no_match_is_a_completed_search_and_does_not_forge_evidence(self):
        with patch('apps.knowledge.retrieval.KnowledgeService.search',return_value=()):
            report=self.run_case('low-oxygen',[tool(),tool(q.KNOWLEDGE,'second','{"query":"x"}'),final()])
        self.assertTrue(report['success'],report['error_code'])
        receipt=report['ledger']['entries'][1]['receipt']
        self.assertTrue(receipt['project_search_completed']);self.assertFalse(receipt['has_project_evidence'])
        self.assertEqual(receipt['evidence_count'],0)

    def test_wrong_source_projection_can_never_be_a_technical_pass(self):
        from apps.ai_service.business_tools import current_water_quality
        project=current_water_quality.project_water_tool
        def wrong(capture):
            payload=project(capture);payload['device_id']='another-device';return payload
        with patch.object(current_water_quality,'project_water_tool',wrong):
            report=self.run_case('current-water',[tool(),final()])
        self.assertTrue(report['product_commit_gate_passed'])
        self.assertFalse(report['success']);self.assertFalse(report['source_binding_matches'])
        self.assertEqual(report['error_code'],'QUALIFICATION_SOURCE_BINDING_MISMATCH')

    def test_no_fourth_request_or_parallel_calls_and_no_auto_correction(self):
        for frames in ([tool(),tool(q.KNOWLEDGE,'second','{"query":"x"}'),tool(call_id='third')],
            [[chunk([delta(name=q.WATER,identifier='one',call_type='function'),
                     delta(name=q.KNOWLEDGE,identifier='two',call_type='function',index=1)])]]):
            self.clients.clear();self.bodies.clear();self.runtimes.clear()
            report=self.run_case('low-oxygen',frames)
            self.assertFalse(report['success']);self.assertFalse(report['product_commit_gate_passed'])
            self.assertLessEqual(report['request_count'],3);self.assertLessEqual(len(report['executions']),2)
            self.assertEqual(len(self.bodies),len(frames))

    def test_truncation_invalid_arguments_cleanup_failure_and_second_tool_failure_do_not_commit(self):
        cases=[([final('length')],{},'STREAM_TRUNCATED'),
            ([tool(arguments='{"device_id":"private"}')],{},'INVALID_TOOL_ARGUMENTS'),
            ([tool()],{'close_error':True},None),
            ([tool(),tool(q.KNOWLEDGE,'second','{"query":false}')],{},'INVALID_TOOL_ARGUMENTS')]
        for frames,options,code in cases:
            self.clients.clear();self.bodies.clear();self.runtimes.clear()
            report=self.run_case('low-oxygen',frames,**options)
            self.assertFalse(report['success']);self.assertFalse(report['product_commit_gate_passed'])
            if code:self.assertEqual(report['error_code'],code)
            self.assertLessEqual(report['request_count'],2)
            if len(report['executions'])==2:self.assertTrue(report['ledger']['entries'][0]['receipt']['has_observation'])

    def test_cancel_timeout_and_credential_preflight_keep_safe_failure_without_extra_requests(self):
        for code in ('USER_CANCELLED','TOTAL_TIMEOUT'):
            self.clients.clear();self.bodies.clear();self.runtimes.clear()
            report=self.run_case('current-water',[[GatewayError(code)]])
            self.assertFalse(report['success']);self.assertFalse(report['product_commit_gate_passed'])
            self.assertEqual(report['error_code'],code);self.assertEqual(report['transport_attempts'],1)
        with patch.object(q,'_credentials',side_effect=CredentialFileError()):
            report=q.run('direct-final',self.root,confirm_network=True,
                approved_plan_sha256=q.plan('direct-final')['plan_sha256'])
        self.assertEqual(report['error_code'],'CREDENTIAL_FILE_ERROR');self.assertEqual(report['actual_network_requests'],0)
        self.assertNotIn('PRIVATE_DO_NOT_PRINT',json.dumps(report))

    def test_answer_preview_is_transient_explicit_and_never_equals_manual_approval(self):
        answers=[];report=self.run_case('direct-final',[final()],answer_reviewer=answers.append)
        self.assertEqual(report['human_review_status'],'PREVIEWED_NOT_APPROVED')
        self.assertTrue(answers);self.assertNotIn(SECRET,answers[0]);self.assertIn('[REDACTED]',answers[0])
        self.assertFalse(report['release_eligible']);self.assertNotIn(ANSWER,json.dumps(report))
        name=q.write_report(self.root,report)
        data=json.loads((self.root/'outputs/assistant-qualification'/name).read_text(encoding='utf-8'))
        self.assertEqual(data['run_id'],report['run_id']);self.assertNotIn(ANSWER,json.dumps(data))
        with self.assertRaises(q.QualificationError):q.write_report(self.root,report)

    def test_trace_failure_cannot_become_completed_even_if_provider_has_final_text(self):
        with patch.object(q._Trace,'_append',side_effect=OSError('private-trace-path')):
            report=self.run_case('current-water',[tool(),final()])
        self.assertFalse(report['success']);self.assertFalse(report['product_commit_gate_passed'])
        self.assertFalse(report['trace_recorded']);self.assertFalse(report['final_answer_present'])
        self.assertEqual(len(report['ledger']['entries']),1)
        self.assertNotIn('private-trace-path',json.dumps(report))

    def test_import_boundary_cli_default_dry_run_and_non_tty_preview_refuses_before_network(self):
        spec=importlib.util.spec_from_file_location('management_qualification_cli',ROOT/'scripts/qualification/qualify_management_streaming.py')
        cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
        with redirect_stdout(StringIO()) as out,patch.object(cli,'run',side_effect=AssertionError('no run')):
            self.assertEqual(cli.main(['--case','direct-final']),0)
        self.assertEqual(json.loads(out.getvalue())['actual_network_requests'],0)
        args=['--case','direct-final','--confirm-network','--plan-sha256',q.plan('direct-final')['plan_sha256'],'--review-answer']
        with redirect_stdout(StringIO()) as out,redirect_stderr(StringIO()),patch.object(cli,'run',side_effect=AssertionError('no run')):
            self.assertEqual(cli.main(args),2)
        self.assertEqual(json.loads(out.getvalue())['error_code'],'QUALIFICATION_REVIEW_REQUIRES_TERMINAL')

    def test_formal_management_import_never_loads_qualification(self):
        code='''
import socket,sys
def deny(*args,**kwargs):raise AssertionError('no network')
socket.socket.connect=socket.socket.connect_ex=socket.getaddrinfo=deny
import apps.ai_service.service,apps.management_web.app
assert not any(n.startswith('apps.ai_service.development') or n.startswith('fishery_ai.development') for n in sys.modules)
'''
        result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_cli_review_strips_terminal_controls_and_stdout_has_only_safe_summary(self):
        spec=importlib.util.spec_from_file_location('management_review_cli',ROOT/'scripts/qualification/qualify_management_streaming.py')
        cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
        class Terminal(StringIO):
            def isatty(self):return True
        report={'run_id':'a'*32,'status':'completed','error_code':None,'success':True,'technical_success':True,
            'request_count':1,'actual_network_requests':1,'qualification_verdict':'PENDING_MANUAL_REVIEW',
            'human_review_status':'PREVIEWED_NOT_APPROVED'}
        def run(*args,**kwargs):
            kwargs['answer_reviewer']('visible-preview\x1b[31m\u202ehidden-direction')
            return report
        with patch.object(cli,'run',run),patch.object(cli,'write_report',return_value='a.json'), \
             redirect_stdout(StringIO()) as out,redirect_stderr(Terminal()) as err:
            result=cli.main(['--case','direct-final','--confirm-network','--plan-sha256',q.plan('direct-final')['plan_sha256'],'--review-answer'])
        self.assertEqual(result,0);self.assertNotIn('visible-preview',out.getvalue())
        self.assertIn('visible-preview',err.getvalue());self.assertNotIn('\x1b',err.getvalue());self.assertNotIn('\u202e',err.getvalue())
        with patch.object(cli,'run',return_value=report), \
             patch.object(cli,'write_report',side_effect=q.QualificationError('QUALIFICATION_REPORT_ERROR')),redirect_stdout(StringIO()) as out:
            result=cli.main(['--case','direct-final','--confirm-network','--plan-sha256',q.plan('direct-final')['plan_sha256']])
        self.assertEqual(result,2)
        summary=json.loads(out.getvalue())
        self.assertEqual(summary['actual_network_requests'],1);self.assertEqual(summary['run_id'],report['run_id'])


if __name__=='__main__':unittest.main()
