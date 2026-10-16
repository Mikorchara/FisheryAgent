"""Frozen business contracts and deterministic old/new differential. No Provider I/O."""
from dataclasses import asdict, replace
import importlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from apps.ai_backend import execution
from apps.ai_backend.contracts import Status
from apps.ai_backend.credentials import CredentialStore
from apps.ai_backend.model_gateway import ProfileRegistry, ModelResponse, ModelToolCall, GatewayError
from apps.ai_backend.observability import JsonlTraceSink
from apps.ai_backend.tool_conversation import (ToolCallingService, ToolExecutionMode,
    ToolModelTransport, ToolExecutionStep, ModelExecutionStep)
from apps.ai_backend.tools import ToolDefinition, ToolRegistry
from apps.ai_backend.tools.policy import ToolPolicy, ToolPolicyError
from apps.ai_backend.tests.support import ScriptedGateway
from apps.ai_service.runtime import assistant, sources, tools, activity
from apps.ai_service.runtime.policy import UserToolPolicyStore


WATER, KNOWLEDGE, SCORE = tools.CURRENT_WATER_QUALITY, tools.SEARCH_FISHERY_KNOWLEDGE, tools.WATER_QUALITY_SCORE
QWEN = assistant.ALLOWED_PRESET_IDS[0]
STAMP = '2026-10-16T00:00:00+00:00'


def water_payload(*, quality='valid', freshness='fresh', status='OK'):
    return {'status':status, 'water_quality':None if status == 'NO_DATA' else {
        'temperature_c':28.0, 'ph':None if quality == 'partial' else 7.5,
        'dissolved_oxygen_mg_l':2.2, 'quality':quality, 'freshness':freshness,
        'observed_at':STAMP,'retrieved_at':STAMP,'source':'fictional-monitoring'},
        'evaluated_at':STAMP, 'findings':[]}


def knowledge_payload(hit=True):
    items = [{'id':'fictional-id', 'category':'water_quality', 'source':'fictional-project',
              'text':'fictional-background', 'source_version':'fixture-1'}] if hit else []
    return {'status':'OK' if hit else 'NO_MATCH','result_count':len(items),
            'retrieval_mode':'portable','evidence':items}


def call(name=WATER, arguments='{}', identifier='call_1'):
    return ModelResponse(None, tool_calls=(ModelToolCall(identifier,name,arguments),), finish_reason='tool_calls')


def final(text='安全回答'):
    return ModelResponse(text, finish_reason='stop')


class FoundationTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.profile = assistant.assistant_profile(QWEN)
        self.runtime = ProfileRegistry([self.profile], CredentialStore(process_env={
            self.profile.credential_ref:'fictional-backend-key'})).snapshot(self.profile.profile_id)
        self.traces = JsonlTraceSink(self.root/'trace.jsonl',tool_names=(WATER,KNOWLEDGE))
        self.called = []

    def registry(self, water=None, knowledge=None):
        def get_water():
            self.called.append(WATER)
            return water if water is not None else water_payload()
        def get_knowledge(arguments):
            self.called.append(KNOWLEDGE)
            return knowledge if knowledge is not None else knowledge_payload()
        return ToolRegistry((ToolDefinition(tools.WATER_DEFINITION,get_water),
            ToolDefinition(tools.KNOWLEDGE_DEFINITION,get_knowledge,tools.validate_arguments)))

    def send(self, responses, *, registry=None, requirement=sources.SourceRequirement.AUTO,
             mode=ToolExecutionMode.BOUNDED_MULTI_ROUND, history=(), handle=None, traces=None):
        gateway = ScriptedGateway(responses)
        coordinator = ToolCallingService(gateway, registry or self.registry(), traces or self.traces,
            policy=ToolPolicy('assistant',True,(WATER,KNOWLEDGE)),execution_mode=mode)
        handle = handle or execution.RequestHandle(summarize_tool=activity.tool_summary)
        handle.start()
        with execution.request_scope(handle):
            result = assistant.AssistantService(coordinator,execution_mode=mode).send(
                assistant.AssistantRequest(QWEN,'本轮问题',history,source_requirement=requirement),self.runtime)
        return result,handle

    def test_prompt_history_and_preset_contracts_identical_but_types_independent(self):
        from fishery_ai import assistant as old
        from fishery_ai import history_projection as old_history
        from apps.ai_backend import history_projection as history
        from fishery_ai.presets import preset_profiles as old_presets
        from apps.ai_service.runtime.presets import preset_profiles
        self.assertEqual(assistant.SYSTEM_INSTRUCTION,old.SYSTEM_INSTRUCTION)
        self.assertEqual(assistant.MULTI_ROUND_SYSTEM_INSTRUCTION,old.MULTI_ROUND_SYSTEM_INSTRUCTION)
        self.assertEqual(history.TRANSCRIPT_NOTICE,old_history.TRANSCRIPT_NOTICE)
        self.assertEqual([asdict(p) for p in preset_profiles()],[asdict(p) for p in old_presets()])
        self.assertIsNot(type(preset_profiles()[0]),type(old_presets()[0]))

    def test_no_tool_imitation_no_receipt_and_unmet_requirement_no_commit(self):
        for requirement in sources.SourceRequirement:
            result, handle = self.send([final('[调用工具 search_fishery_knowledge] 已查询')], requirement=requirement)
            self.assertFalse(result.source_ledger.entries)
            self.assertEqual(result.to_dict()['successful_turn'],requirement == sources.SourceRequirement.AUTO)
            if requirement != sources.SourceRequirement.AUTO:
                self.assertEqual(result.error_code,'ASSISTANT_SOURCE_REQUIREMENT_UNMET')
                self.assertEqual(result.final_text,'')
                self.assertEqual(handle.state,'FAILED')

    def test_water_business_matrix_preserves_query_operation_vs_observation(self):
        for payload in [water_payload(),water_payload(status='NO_DATA'),
                        water_payload(quality='partial'),water_payload(quality='invalid'),
                        water_payload(freshness='stale')]:
            with self.subTest(status=payload['status'],water=payload['water_quality']):
                result,_ = self.send([call(),final()],registry=self.registry(water=payload),
                    requirement=sources.SourceRequirement.CURRENT_OBSERVATION_QUERY)
                receipt = result.source_receipt
                self.assertTrue(receipt.observation_query_completed)
                self.assertEqual(receipt.has_observation,payload['status'] != 'NO_DATA')
                self.assertEqual(result.status,Status.COMPLETED)
                self.assertFalse(sources.requirement_satisfied(
                    sources.SourceRequirement.CURRENT_SCORE_EVALUATION,receipt))

    def test_knowledge_hit_and_no_match_are_distinct_from_current_fact(self):
        for hit in (False,True):
            result,_ = self.send([call(KNOWLEDGE,'{"query":"固定夹具"}'),final()],
                registry=self.registry(knowledge=knowledge_payload(hit)),
                requirement=sources.SourceRequirement.PROJECT_KNOWLEDGE_SEARCH)
            self.assertEqual(result.status,Status.COMPLETED)
            self.assertTrue(result.source_receipt.project_search_completed)
            self.assertEqual(result.source_receipt.has_project_evidence,hit)
            self.assertFalse(result.source_receipt.observation_query_completed)

    def test_invalid_arguments_never_run_handler_followup_receipt_or_commit(self):
        for args in ('{"device_id":"private-fixture-value"}','{"query":"wrong"}'):
            result,_ = self.send([call(arguments=args)])
            self.assertEqual(result.error_code,'INVALID_TOOL_ARGUMENTS')
            self.assertFalse(self.called)
            self.assertFalse(result.to_dict()['successful_turn'])
            self.assertFalse(result.source_receipt.observation_query_completed)
            safe=json.dumps(result.to_dict())+self.traces.path.read_text(encoding='utf-8')
            self.assertNotIn('private-fixture-value',safe)
            self.assertEqual(result.to_dict()['activity']['counts']['tools_executed'],0)

    def test_ledger_keeps_two_results_and_legacy_projection_fails_closed(self):
        result,_ = self.send([call(),call(KNOWLEDGE,'{"query":"固定"}','call_2'),final()])
        self.assertEqual(self.called,[WATER,KNOWLEDGE])
        self.assertEqual([e.execution_seq for e in result.source_ledger.entries],[2,4])
        self.assertEqual(len(result.execution.steps),5)
        self.assertIsNone(result.to_dict()['tool_activity'])
        with self.assertRaises(ValueError): _=result.source_receipt
        self.assertTrue(sources.requirement_satisfied_by_ledger(
            sources.SourceRequirement.CURRENT_OBSERVATION_QUERY,result.source_ledger))
        self.assertTrue(sources.requirement_satisfied_by_ledger(
            sources.SourceRequirement.PROJECT_KNOWLEDGE_SEARCH,result.source_ledger))

    def test_later_provider_or_tool_failure_keeps_audit_but_no_success(self):
        for second in [GatewayError('HTTP_429'),call(KNOWLEDGE,'{}','call_2')]:
            result,_ = self.send([call(),second])
            self.assertEqual(result.status,Status.FAILED)
            self.assertEqual(result.final_text,'')
            self.assertTrue(result.source_ledger.entries[0].receipt.observation_query_completed)
            self.assertFalse(result.to_dict()['successful_turn'])

    def test_budget_multiple_calls_duplicates_and_third_request_final_only(self):
        multiple = ModelResponse(None, tool_calls=(ModelToolCall('a',WATER,'{}'),
            ModelToolCall('b',KNOWLEDGE,'{"query":"x"}')),finish_reason='tool_calls')
        cases = [([multiple],'TOOL_CALL_LIMIT',0),
            ([call(),call(identifier='call_2')],'TOOL_REQUEST_ALREADY_EXECUTED',1),
            ([call(),call(KNOWLEDGE,'{"query":"x"}','call_2'),call(identifier='call_3')],'TOOL_ROUND_LIMIT',2)]
        for responses,code,count in cases:
            self.called.clear()
            result,_ = self.send(responses)
            self.assertEqual(result.error_code,code)
            self.assertEqual(len(self.called),count)
            self.assertLessEqual(result.execution.usage.request_count,3)
        result,_ = self.send([call(),call(KNOWLEDGE,'{"query":"x"}','call_2')],
            mode=ToolExecutionMode.SINGLE_ROUND)
        self.assertEqual(result.error_code,'TOOL_ROUND_LIMIT')

    def test_trace_failure_or_deadline_during_commit_cannot_publish_final(self):
        with patch.object(self.traces,'record_assistant',side_effect=OSError('fictional-private-path')):
            result,_ = self.send([final()])
        self.assertEqual(result.error_code,'TRACE_WRITE_ERROR')
        self.assertEqual(result.final_text,'')
        handle=execution.RequestHandle(); original=self.traces.record_assistant
        def late(*a,**kw):
            original(*a,**kw);handle._deadline=0.0
        with patch.object(self.traces,'record_assistant',side_effect=late):
            result,_ = self.send([final()],handle=handle)
        self.assertEqual(result.error_code,'TOTAL_TIMEOUT')
        self.assertFalse(result.to_dict()['successful_turn'])
        self.assertEqual(handle.state,'FAILED')

    def test_complete_pair_trimming_projection_json_and_history_does_not_gain_source(self):
        history=tuple(assistant.AssistantHistoryTurn('用户"\\\n'+str(i),
            '[调用工具 get_current_water_quality] 已检索项目'+('字'*150),STAMP) for i in range(8))
        result,_ = self.send([final()],history=history)
        self.assertLessEqual(result.context.history_turns_sent,6)
        self.assertLessEqual(result.context.history_bytes_sent,6144)
        messages=result.context.model_request.messages
        self.assertEqual([m.role for m in messages],['system','user','user'])
        transcript=json.loads(messages[1].content)
        self.assertEqual(len(transcript['turns']),result.context.history_turns_sent)
        self.assertTrue(all(len(turn['messages'])==2 for turn in transcript['turns']))
        self.assertEqual(messages[-1].content,'本轮问题')
        self.assertFalse(result.source_ledger.entries)
        from apps.ai_backend.history_projection import ProjectionId
        from fishery_ai import assistant as old_assistant
        for projection in ProjectionId:
            oldreq=old_assistant.AssistantRequest(QWEN,'本轮问题',tuple(
                old_assistant.AssistantHistoryTurn(t.user,t.assistant,t.completed_at) for t in history))
            native=old_assistant.AssistantContextBuilder().build(oldreq)
            new_native=assistant.AssistantContextBuilder().build(assistant.AssistantRequest(QWEN,'本轮问题',history))
            self.assertEqual(asdict(native),asdict(new_native))

    def test_stored_score_policy_preserved_but_never_bound_or_exposed(self):
        registry=self.registry();store=UserToolPolicyStore(self.root/'policy',registry)
        data=store.default_selections()
        data['modes']['assistant']['selected_tools']=[WATER,SCORE,KNOWLEDGE]
        store.save(data)
        self.assertEqual(store.load(),data)
        self.assertEqual(store.effective()['assistant'].exposed_tools,(WATER,KNOWLEDGE))
        self.assertNotIn(SCORE,registry.registered_names())
        with self.assertRaises(Exception):registry.lookup(SCORE)
        for names in [[WATER,WATER],['unknown_tool'],[False]]:
            bad=json.loads(json.dumps(data));bad['modes']['assistant']['selected_tools']=names
            with self.assertRaises(ToolPolicyError):store.save(bad)

    def test_score_receipt_matrix_matches_old_contract_without_binding_score_handler(self):
        from apps.ai_backend import contracts, tool_conversation as steps
        from apps.ai_backend.tools.contracts import ToolExecutionResult
        from fishery_ai import contracts as old_contracts, tool_conversation as old_steps
        from fishery_ai import assistant_sources as old_sources
        from fishery_ai.tools.contracts import ToolExecutionResult as OldResult
        payloads=[]
        for status,quality in [('OK','valid'),('PARTIAL','partial'),('NOT_SCORABLE','invalid'),('NO_DATA',None)]:
            payload=water_payload(quality=quality or 'valid',status='NO_DATA' if quality is None else 'OK')
            fields=('temperature','dissolved_oxygen') if quality=='partial' else ('temperature','ph','dissolved_oxygen')
            payload.update(status=status,quality=quality,freshness='fresh' if quality else None,
                evaluated_at=STAMP if quality else None,score=70 if status in ('OK','PARTIAL') else None,
                grade='ACCEPTABLE' if status in ('OK','PARTIAL') else None,
                components={key:{'score':70} for key in fields} if status in ('OK','PARTIAL') else {})
            payloads.append(payload)
        for payload in payloads:
            receipts=[]
            for module,contract,result_type,mapper in [(steps,contracts,ToolExecutionResult,sources),
                (old_steps,old_contracts,OldResult,old_sources)]:
                run=module.ToolConversationResult('fixture','trace',contract.Status.COMPLETED,
                    contract.RuntimeInfo('fixture','local','fixture'),'final',(
                        module.ModelExecutionStep(1,1,module.ModelStepOutcome('tool_calls'),True),
                        module.ToolExecutionStep(2,1,1,'call',SCORE,result_type.from_payload('call',SCORE,payload),1.0,True)),
                    contract.SessionUsage(1,0,contract.Usage()))
                receipt=mapper.receipt_from_execution(run)
                self.assertTrue(receipt.score_evaluation_completed)
                self.assertEqual(receipt.has_score,payload['status'] in ('OK','PARTIAL'))
                receipts.append(receipt.to_dict())
            self.assertEqual(*receipts)
        self.assertNotIn(SCORE,self.registry().registered_names())

