"""One-time migration parity: two independent turns share only detached fixture JSON."""
from dataclasses import asdict, replace
import importlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest

from apps.ai_backend.tests import test_execution as offline_guard
from apps.ai_backend.tests.support import FakeSDK, sdk_tool, sdk_final, tool_chunks, final_chunks
from . import test_foundation as fixture


def load(side, backend_name, business_name=None):
    return importlib.import_module(('fishery_ai.'+backend_name) if side=='old' else (
        'apps.ai_service.runtime.'+business_name if business_name else 'apps.ai_backend.'+backend_name))


def stable(value):
    """Only nondeterministic execution IDs and wall-clock timings are excluded."""
    if isinstance(value, dict):
        return {k:stable(v) for k,v in value.items() if k not in (
            'request_id','trace_id','total_latency_ms','duration_ms','started_at','finished_at','completed_at','total_ms')}
    if isinstance(value, (list,tuple)):return [stable(v) for v in value]
    return value


class DifferentialTests(unittest.TestCase):
    def setUp(self):
        offline_guard.ExecutionTests.setUp(self)
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)

    def run_side(self, side, path, transport, mode='BOUNDED_MULTI_ROUND', water=None, knowledge=None):
        a=load(side,'assistant','assistant'); g=load(side,'model_gateway')
        c=load(side,'tool_conversation'); execution=load(side,'execution')
        p=load(side,'tools.policy'); tc=load(side,'tools.contracts'); trace=load(side,'observability')
        if side=='old':
            definitions=load(side,'tools.registry')
            formal=definitions.ToolRegistry(None,None,knowledge=NS())
            water_def=formal.lookup(fixture.WATER).model_definition
            knowledge_def=formal.lookup(fixture.KNOWLEDGE).model_definition
            validate=importlib.import_module('fishery_ai.tools.handlers.knowledge_search').validate_arguments
            summarize=importlib.import_module('fishery_ai.assistant_activity').tool_summary
        else:
            water_module=importlib.import_module('apps.ai_service.business_tools.current_water_quality')
            knowledge_module=importlib.import_module('apps.ai_service.business_tools.fishery_knowledge')
            water_def=water_module.WATER_DEFINITION;knowledge_def=knowledge_module.KNOWLEDGE_DEFINITION
            validate=knowledge_module.validate_arguments
            summarize=importlib.import_module('apps.ai_service.runtime.activity').tool_summary
        water=fixture.water_payload() if water is None else water
        knowledge=fixture.knowledge_payload() if knowledge is None else knowledge
        class Registry:
            entries={fixture.WATER:tc.ToolDefinition(water_def,lambda:json.loads(json.dumps(water))),
                fixture.KNOWLEDGE:tc.ToolDefinition(knowledge_def,lambda args:json.loads(json.dumps(knowledge)),validate)}
            def lookup(self,name):
                if name not in self.entries:raise tc.ToolError(tc.ToolErrorCode.UNKNOWN_TOOL)
                return self.entries[name]
            def model_definitions(self):return tuple(item.model_definition for item in self.entries.values())
        registry=Registry()
        plans=([sdk_final()] if path=='direct' else [sdk_tool(fixture.WATER),sdk_final()] if path=='single' else
            [sdk_tool(fixture.WATER),sdk_tool(fixture.KNOWLEDGE,'call_2','{"query":"固定"}'),sdk_final()])
        if path=='invalid':plans=[sdk_tool(fixture.WATER,arguments='{"extra":"private-fixture"}')]
        if path=='provider-error':plans=[sdk_tool(fixture.WATER),g.GatewayError('HTTP_429')]
        if path=='truncated':plans=[sdk_final(finish='length')]
        if transport=='STREAMING':
            plans=([final_chunks()] if path=='direct' else [tool_chunks(fixture.WATER),final_chunks()] if path=='single' else
                [tool_chunks(fixture.WATER),tool_chunks(fixture.KNOWLEDGE,'call_2','{"query":"固定"}'),final_chunks()])
            if path=='invalid':plans=[tool_chunks(fixture.WATER,arguments='{"extra":"private-fixture"}')]
            if path=='provider-error':plans=[tool_chunks(fixture.WATER),g.GatewayError('HTTP_429')]
            if path=='truncated':plans=[final_chunks(finish='length')]
        profile=a.assistant_profile(fixture.QWEN)
        cred=load(side,'credentials').CredentialStore(process_env={profile.credential_ref:'fictional-diff-key'})
        runtime=g.ProfileRegistry([profile],cred).snapshot(profile.profile_id)
        # The old product only applied this cost override to Tool Streaming.
        # Normal migration parity must exercise its real, unbounded-default path,
        # rather than comparing two INVALID_STREAMING_OUTPUT_BUDGET preflights.
        if transport=='STREAMING':
            runtime=replace(runtime,transport_output_token_limit=512)
        sdk=FakeSDK(plans,model=profile.model)
        adapter=load(side,'openai_compatible_adapter').OpenAICompatibleAdapter(async_client_factory=sdk.factory)
        traces=trace.JsonlTraceSink(self.root/(side+'.jsonl'),**({} if side=='old' else {'tool_names':(fixture.WATER,fixture.KNOWLEDGE)}))
        coordinator=c.ToolCallingService(adapter,registry,traces,policy=p.ToolPolicy('assistant',True,(fixture.WATER,fixture.KNOWLEDGE)),
            execution_mode=c.ToolExecutionMode(mode),model_transport=c.ToolModelTransport(transport))
        h=execution.RequestHandle(**({} if side=='old' else {'summarize_tool':summarize}));h.start()
        request=a.AssistantRequest(fixture.QWEN,'固定迁移输入',(a.AssistantHistoryTurn('旧问题','旧答案',fixture.STAMP),))
        with execution.request_scope(h):
            result=a.AssistantService(coordinator,execution_mode=c.ToolExecutionMode(mode)).send(request,runtime)
        self.assertGreaterEqual(len(sdk.bodies),1,'parity must exercise the SDK, not just matching preflight failures')
        return {'bodies':sdk.bodies,'dto':stable(result.to_dict()),'ledger':result.source_ledger.to_dict(),
            'steps':stable([asdict(s) for s in result.execution.steps]),'closed':[client.closed for client in sdk.clients],
            'handle':stable(h.public_info())}

    def test_normal_and_streaming_protocol_results_steps_usage_receipts_and_commit_parity(self):
        for transport in ('NORMAL','STREAMING'):
            for mode,paths in [('SINGLE_ROUND',('direct','single','invalid')),
                               ('BOUNDED_MULTI_ROUND',('direct','single','double','invalid','provider-error','truncated'))]:
                for path in paths:
                    with self.subTest(transport=transport,mode=mode,path=path):
                        self.assertEqual(self.run_side('old',path,transport,mode),self.run_side('new',path,transport,mode))

    def test_negative_business_results_have_identical_protocol_and_receipts(self):
        for water in [fixture.water_payload(status='NO_DATA'),fixture.water_payload(quality='partial'),
                      fixture.water_payload(quality='invalid'),fixture.water_payload(freshness='stale')]:
            for transport in ('NORMAL','STREAMING'):
                self.assertEqual(self.run_side('old','double',transport,water=water,knowledge=fixture.knowledge_payload(False)),
                    self.run_side('new','double',transport,water=water,knowledge=fixture.knowledge_payload(False)))

    def test_management_published_scopes_still_match_exact_fixed_definitions(self):
        from apps.ai_service import execution, streaming
        from apps.ai_service.business_tools import current_water_quality, fishery_knowledge
        from apps.ai_service.runtime.assistant import assistant_profile
        from apps.ai_backend.tools import ToolRegistry, ToolDefinition
        from apps.ai_backend.tools.policy import ToolPolicy
        from apps.ai_service.runtime.streaming_contracts import streaming_scope
        config=streaming.load_streaming_config()
        binding=json.loads(config.releases[0].data_bindings_json)
        knowledge=NS(source_id=binding['knowledge_source'],source_version=binding['knowledge_version'],backend=binding['retrieval_backend'])
        registry=ToolRegistry((ToolDefinition(current_water_quality.WATER_DEFINITION,lambda:{}),
            ToolDefinition(fishery_knowledge.KNOWLEDGE_DEFINITION,lambda a:{},fishery_knowledge.validate_arguments)))
        policy=ToolPolicy('assistant',True,(fixture.WATER,fixture.KNOWLEDGE))
        for record in execution.load_execution_config().releases:
            published=json.loads(record.runtime.scope_json)
            actual=execution.management_scope(assistant_profile(published['preset_id']),policy,registry,knowledge)
            self.assertEqual(actual['runtime'],published)
            self.assertEqual(actual['data_bindings'],json.loads(record.data_bindings_json))
        actual=streaming_scope(assistant_profile(fixture.QWEN),policy,registry,execution.DEFAULT_HISTORY_PROJECTION)
        self.assertEqual(actual,json.loads(config.releases[0].runtime.scope_json))
