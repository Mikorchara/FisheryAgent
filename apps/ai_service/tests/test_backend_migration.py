"""Phase II HTTP equivalence, strict runtime ownership and qualification boundary."""
import ast
import importlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from .capture_migration import capture


ROOT=Path(__file__).resolve().parents[3]
BLOCK_OLD='''
import importlib.abc,sys
class BlockOld(importlib.abc.MetaPathFinder):
 def find_spec(self,name,*args):
  if name.startswith(('fishery_ai.assistant','fishery_ai.model_gateway','fishery_ai.openai_compatible_adapter',
    'fishery_ai.execution','fishery_ai.credentials','fishery_ai.credential_paths','fishery_ai.observability',
    'fishery_ai.tool_conversation','fishery_ai.tools','fishery_ai.presets','fishery_ai.history_projection',
    'fishery_ai.protocol_specs','fishery_ai.providers','fishery_ai.development','fishery_ai.manual')):
   raise AssertionError('legacy LLM execution forbidden: '+name)
sys.meta_path.insert(0,BlockOld())
'''


class BackendMigrationTests(unittest.TestCase):
    def fresh(self, code):
        result=subprocess.run([sys.executable,'-I','-c',
            f'import sys;sys.path.insert(0,{str(ROOT)!r})\n'+code],cwd=ROOT,capture_output=True,text=True,timeout=45)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_six_http_sdk_paths_match_pre_switch_protocol_steps_ledger_usage_and_dto(self):
        before=json.loads((Path(__file__).with_name('fixtures')/'r2c1d_http_baseline.json').read_text(encoding='utf-8'))
        self.assertEqual(capture(),before)

    def test_management_http_sse_and_qualification_work_when_legacy_llm_modules_are_blocked(self):
        # The same actual HTTP/POST SSE fixtures run with the old LLM layer unavailable.
        self.fresh(BLOCK_OLD+'''
import unittest
from apps.ai_service.tests.capture_migration import capture
result=capture()
assert len(result)==6 and all(row['committed'] for row in result.values())
from apps.ai_service.tests.test_streaming_qualification import StreamingQualificationTests
suite=unittest.defaultTestLoader.loadTestsFromTestCase(StreamingQualificationTests)
run=unittest.TextTestRunner().run(suite)
assert run.wasSuccessful()
''')

    def test_management_product_source_does_not_import_legacy_package(self):
        for directory in (ROOT/'apps'/name for name in (
                'monitoring','simulator','knowledge','ai_backend','ai_service','management_web')):
            for path in directory.rglob('*.py'):
                if 'tests' in path.parts or 'development' in path.parts:continue
                for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                    names=([node.module or ''] if isinstance(node,ast.ImportFrom) else
                           [a.name for a in node.names] if isinstance(node,ast.Import) else [])
                    for name in names:
                        self.assertFalse(name=='fishery_ai' or name.startswith('fishery_ai.'),(path,name))

    def test_management_http_and_three_tools_run_with_entire_legacy_package_blocked(self):
        self.fresh('''
import importlib.abc,sys,unittest
class BlockOld(importlib.abc.MetaPathFinder):
 def find_spec(self,name,*args):
  if name=='fishery_ai' or name.startswith('fishery_ai.'):
   raise AssertionError('legacy package forbidden: '+name)
sys.meta_path.insert(0,BlockOld())
from apps.ai_service.tests.capture_migration import capture
result=capture()
assert len(result)==6 and all(row['committed'] and row['resources_closed'] for row in result.values())
from apps.ai_service.tests.test_unified_tools import UnifiedToolsTests
from apps.monitoring.tests.test_water_capture import WaterCaptureTests
from apps.management_web.tests.test_knowledge_content import KnowledgeHTTPTests
suite=unittest.TestSuite()
suite.addTests(unittest.defaultTestLoader.loadTestsFromNames([
 'test_normal_all_selections_and_sequential_current_history',
 'test_streaming_history_and_two_results_reach_final_and_real_frontend_parser',
 'test_revocation_rejects_old_confirmation_and_unauthorized_model_call'],UnifiedToolsTests))
suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(WaterCaptureTests))
suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(KnowledgeHTTPTests))
run=unittest.TextTestRunner().run(suite)
assert run.wasSuccessful()
assert not any(name=='fishery_ai' or name.startswith('fishery_ai.') for name in sys.modules)
''')

    def test_all_active_execution_classes_and_qualification_adapter_are_new(self):
        from apps.ai_service import service,contracts
        from apps.ai_backend import execution,model_gateway,tool_conversation
        from apps.ai_service.development import streaming_qualification as qualification
        from apps.ai_backend.openai_compatible_adapter import OpenAICompatibleAdapter
        self.assertIs(service.RequestHandle,execution.RequestHandle)
        self.assertIs(contracts.RequestHandle,execution.RequestHandle)
        self.assertIs(service.ProfileRegistry,model_gateway.ProfileRegistry)
        self.assertIs(service.ToolCallingService,tool_conversation.ToolCallingService)
        self.assertIs(service.request_scope,execution.request_scope)
        self.assertTrue(issubclass(qualification._Adapter,OpenAICompatibleAdapter))
        self.assertEqual(qualification.plan('low-oxygen')['backend_implementation'],'apps.ai_backend@1')
        self.assertEqual(qualification.plan('low-oxygen')['experiment_version'],'management-streaming-qualification@2')
        for removed in ('assembly','contracts','bindings','execution','streaming'):
            self.assertFalse((ROOT/'apps/ai_service/runtime'/(removed+'.py')).exists())

    def test_qualification_frozen_scope_preserved_but_old_runtime_consent_is_rejected(self):
        from apps.ai_service.development import streaming_qualification as qualification
        baseline=json.loads((Path(__file__).with_name('fixtures')/'r2c1d_plan_baseline.json').read_text(encoding='utf-8'))
        for case,old in baseline.items():
            current=qualification.plan(case)
            for key in ('scope_sha256','history_framing_sha256','config_sha256','question_sha256'):
                self.assertEqual(current[key],old[key])
            self.assertNotEqual(current['plan_sha256'],old['plan_sha256'])
            with patch.object(qualification,'_credentials',side_effect=AssertionError('no credentials')), \
                 self.assertRaises(qualification.QualificationError) as caught:
                qualification.run(case,ROOT,confirm_network=True,approved_plan_sha256=old['plan_sha256'])
            self.assertEqual(caught.exception.code,'QUALIFICATION_PLAN_CHANGED')

    def test_prototype_can_execute_without_importing_the_new_backend(self):
        self.fresh('''
import importlib.abc,sys
class BlockNew(importlib.abc.MetaPathFinder):
 def find_spec(self,name,*a):
  if name.startswith('apps.ai_backend'):raise AssertionError('Prototype independence')
sys.meta_path.insert(0,BlockNew())
from tempfile import TemporaryDirectory
from pathlib import Path
from fishery_ai.assistant import AssistantService,AssistantRequest,assistant_profile
from fishery_ai.model_gateway import ProfileRegistry,MockGateway,ModelResponse
from fishery_ai.credentials import CredentialStore
from fishery_ai.domain import DiagnosisService
from fishery_ai.telemetry import CurrentSnapshotStore,CurrentWaterQualityReader
from fishery_ai.tools.registry import ToolRegistry
from fishery_ai.tools.policy import ToolPolicy
from fishery_ai.tool_conversation import ToolCallingService
from fishery_ai.execution import RequestHandle,request_scope
from fishery_ai.observability import JsonlTraceSink
p=assistant_profile('ollama-qwen35-4b-r1')
runtime=ProfileRegistry([p],CredentialStore(process_env={})).snapshot(p.profile_id)
with TemporaryDirectory() as temp:
 registry=ToolRegistry(CurrentWaterQualityReader(CurrentSnapshotStore(),stale_after_s=300),DiagnosisService())
 coordinator=ToolCallingService(MockGateway(responses=[ModelResponse('offline final',finish_reason='stop')]),registry,
   JsonlTraceSink(Path(temp)/'trace'),policy=ToolPolicy('assistant',True,('get_current_water_quality',)))
 h=RequestHandle();h.start()
 with request_scope(h):result=AssistantService(coordinator).send(AssistantRequest(p.preset_id,'concept'),runtime)
 assert result.to_dict()['successful_turn']
assert not any(n.startswith('apps.ai_backend') for n in sys.modules)
''')
