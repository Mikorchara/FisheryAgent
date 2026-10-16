"""Import closure, one-runtime type ownership and inert installation boundary."""
import ast
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[3]
BLOCKED_FLOW = '''
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.startswith(('fishery_ai','flask','apps.ai_service','apps.monitoring','apps.management_web')):
            raise AssertionError('forbidden backend dependency: '+fullname)
sys.meta_path.insert(0, Block())
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from apps.ai_backend.model_gateway import ModelProfile, ProfileRegistry, ModelMessage, ModelRequest
from apps.ai_backend.model_options import ModelCapabilities, Support
from apps.ai_backend.contracts import Mode
from apps.ai_backend.credentials import CredentialStore
from apps.ai_backend.providers import AuthSpec
from apps.ai_backend.tools import ToolRegistry, ToolDefinition
from apps.ai_backend.tools.policy import ToolPolicy
from apps.ai_backend.model_gateway import ModelToolDefinition
from apps.ai_backend.openai_compatible_adapter import OpenAICompatibleAdapter
from apps.ai_backend.observability import JsonlTraceSink
from apps.ai_backend.tool_conversation import ToolCallingService, ToolModelTransport
from apps.ai_backend.execution import RequestHandle, request_scope
from types import SimpleNamespace as NS
import socket
def deny(*a,**kw): raise AssertionError('no network')
socket.getaddrinfo=socket.create_connection=deny
caps=ModelCapabilities(tool_calling=Support.SUPPORTED,streaming=Support.SUPPORTED,
    service_id='custom',adapter_id='generic_openai_chat',model_id='fixture',base_url='http://mock.invalid/v1')
p=ModelProfile('fixture','Fixture','local','http://mock.invalid/v1','fixture',
    auth_spec=AuthSpec.NONE,max_retries=0,capabilities=caps)
runtime=ProfileRegistry([p],CredentialStore(process_env={})).snapshot('fixture')
registry=ToolRegistry([ToolDefinition(ModelToolDefinition('read_value','Read only',
    {'type':'object','properties':{},'additionalProperties':False}),lambda:{'status':'NO_DATA'})])
for transport in ToolModelTransport:
    count=[0]
    class Stream:
        def __init__(self,items):self.items=items
        def __aiter__(self):return self.events()
        async def events(self):
            for item in self.items:yield item
        async def close(self):pass
    class Client:
        def __init__(self):self.chat=NS(completions=NS(create=self.create))
        async def create(self,**body):
            count[0]+=1
            call=NS(id='call',type='function',function=NS(name='read_value',arguments='{}'))
            if count[0]==2:assert body['messages'][-1]['content']=='{"status":"NO_DATA"}'
            if body.get('stream'):
                function=NS(name='read_value',arguments='{}')
                calls=[NS(index=0,id='call',type='function',function=function)] if count[0]==1 else None
                return Stream([NS(model='fixture',usage=None,choices=[NS(index=0,
                    delta=NS(role='assistant',content=None if calls else 'final',reasoning_content=None,tool_calls=calls),
                    finish_reason='tool_calls' if calls else 'stop')])])
            return NS(model='fixture',usage=None,choices=[NS(finish_reason='tool_calls' if count[0]==1 else 'stop',
                message=NS(role='assistant',content=None if count[0]==1 else 'final',
                    tool_calls=[call] if count[0]==1 else [],reasoning_content=None))])
        async def close(self):pass
    with TemporaryDirectory() as temp:
        adapter=OpenAICompatibleAdapter(async_client_factory=lambda *_:Client())
        service=ToolCallingService(adapter,registry,JsonlTraceSink(Path(temp)/'trace'),
            policy=ToolPolicy('assistant',True,('read_value',)),model_transport=transport)
        h=RequestHandle();h.start()
        with request_scope(h):result=service.run_request(ModelRequest(Mode.CHAT,(ModelMessage('user','test'),)),runtime)
        assert result.status.value=='completed',result.error_code
        assert len(result.steps)==3 and count[0]==2
assert not any(n.startswith('fishery_ai') for n in sys.modules)
'''


class BoundaryTests(unittest.TestCase):
    def test_all_backend_modules_have_no_business_reverse_imports(self):
        base = ROOT / 'apps/ai_backend'
        for path in base.rglob('*.py'):
            if 'tests' in path.relative_to(base).parts: continue
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                names = [node.module or ''] if isinstance(node, ast.ImportFrom) else (
                    [a.name for a in node.names] if isinstance(node, ast.Import) else [])
                for name in names:
                    self.assertFalse(name.startswith(('fishery_ai','flask','apps.ai_service',
                        'apps.monitoring','apps.management_web')), (path, name))
                    if isinstance(node, ast.ImportFrom):
                        self.assertLessEqual(node.level, 2)

    def test_fresh_process_forbids_old_package_and_runs_fake_normal_and_streaming(self):
        repo = ROOT
        result = subprocess.run([sys.executable, '-I', '-c',
            f'import sys;sys.path.insert(0,{str(repo)!r})\n'+BLOCKED_FLOW],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_context_owner_and_model_calls_cannot_mix_with_legacy(self):
        from apps.ai_backend import execution as new
        from fishery_ai import execution as old
        from apps.ai_backend.model_gateway import ModelToolCall
        from fishery_ai.model_gateway import ModelToolCall as OldCall
        from apps.ai_backend.tools import ToolRegistry, ToolExecutor
        from apps.ai_backend.tools.policy import ToolPolicy
        self.assertIsNot(new._current, old._current)
        old_handle, new_handle = old.RequestHandle(), new.RequestHandle()
        with new.request_scope(new_handle):
            self.assertIsNone(old.current_handle())
            self.assertIs(new.current_handle(), new_handle)
        with self.assertRaises(TypeError), new.request_scope(old_handle): pass
        executor = ToolExecutor(ToolRegistry(()), policy=ToolPolicy('assistant',False,()))
        with self.assertRaises(TypeError): executor.execute(OldCall('call','fixture','{}'))
        self.assertIsNot(ModelToolCall, OldCall)

    def test_new_registry_rejects_old_definition_and_duplicate_binding(self):
        from apps.ai_backend.tools import ToolRegistry, ToolDefinition
        from apps.ai_backend.model_gateway import ModelToolDefinition
        from fishery_ai.tools.contracts import ToolDefinition as OldDefinition
        from fishery_ai.model_gateway import ModelToolDefinition as OldModelDefinition
        with self.assertRaises(ValueError):
            ToolRegistry((OldDefinition(OldModelDefinition('x','x',{}), lambda:{}),))
        item = ToolDefinition(ModelToolDefinition('x','x',{}), lambda:{})
        with self.assertRaises(ValueError): ToolRegistry((item,item))

