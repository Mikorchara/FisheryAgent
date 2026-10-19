"""Real management HTTP, private temporary files and fictional credentials only."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
import logging
import unittest
from unittest.mock import patch

from apps.ai_backend import secure_files
from apps.ai_backend.credentials import CredentialStore
from apps.ai_backend.project_env import EnvWriteError, edit_env
from apps.ai_backend.tool_conversation import ToolModelTransport
from apps.ai_backend.model_gateway import ProfileRegistry
from apps.ai_backend.tests.support import FakeSDK, sdk_final
from apps.ai_backend.openai_compatible_adapter import OpenAICompatibleAdapter
from apps.ai_service.runtime.locations import private_project_location
from apps.ai_service.settings import ManagementSettingsService, SettingsError
from apps.ai_service.tests import test_unified_tools as fixture
from apps.management_web.app import create_app


class ManagementSettingsTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.UnifiedToolsTests(methodName='runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.root = self.f.root
        base = self.root/'private'
        secure_files.private_directory(base)
        location = private_project_location(self.root/'workspace',{'LOCALAPPDATA':str(base)})
        self.f.backend.credentials = CredentialStore(location.env_path,{},private_location=location)
        self.probe_sdk=FakeSDK(lambda *_:sdk_final(model=self.f.profile.model),model=self.f.profile.model)
        self.service = ManagementSettingsService(self.f.backend,self.root/'settings.json',
            probe_gateway_factory=lambda:OpenAICompatibleAdapter(async_client_factory=self.probe_sdk.factory))
        self.client = create_app(data_service=self.f.monitoring,ai=self.f.web,settings_service=self.service).test_client()
        self.headers = self.f.headers
        self.ref = self.f.profile.credential_ref
        self.f.sdk = FakeSDK([],model=self.f.profile.model)

    def read(self):
        response = self.client.get('/api/settings')
        self.assertEqual(response.status_code,200,response.get_json())
        return response.get_json()

    def save(self, preferences, *, current=None, **extra):
        current = current or self.read()
        return self.client.post('/api/settings',headers=self.headers,json={
            'epoch':current['epoch'],'revision':current['revision'],'preferences':preferences,**extra})

    def change(self, *, provider='dashscope',secret='fictional-settings-key-A',action='save',revision=None,confirm_clear=False):
        status = next(v for v in self.read()['credentials'] if v['provider']==provider)
        test_token=None
        if action=='save':
            probe=self.client.post('/api/settings/credentials/test',headers=self.headers,json={
                'epoch':self.f.web.epoch,'provider':provider,'source':'input','secret':secret,
                'revision':revision or status['revision'],'confirm_network':True})
            if probe.status_code!=200:return probe
            test_token=probe.get_json()['test']['test_token']
        return self.client.post('/api/settings/credentials',headers=self.headers,json={
            'epoch':self.f.web.epoch,'provider':provider,'action':action,'revision':revision or status['revision'],
            'secret':secret,'confirm_clear':confirm_clear,'test_token':test_token})

    def test_defaults_persist_restart_and_bootstrap_without_model_request(self):
        value=self.read(); prefs={**value['preferences'],'device_id':'pond-b','transport':'streaming','show_details':False}
        response=self.save(prefs,current=value)
        self.assertEqual(response.status_code,200,response.get_json())
        restarted=ManagementSettingsService(self.f.backend,self.service.store.path)
        self.assertEqual(restarted.preferences(),prefs)
        self.assertEqual(self.client.get('/api/bootstrap').get_json()['preferences'],prefs)
        self.assertEqual(self.f.sdk.bodies,[])
        self.assertFalse(self.f.backend.credentials.project_env_path.exists())

    def test_modes_devices_and_budget_injection_rejected_without_storage_or_io(self):
        value=self.read(); prefs=value['preferences']
        for change in ({'preset_id':'custom-model'},{'device_id':'unknown'},{'show_details':1},
                       {'transport':'invalid'},{'preset_id':'ollama-qwen35-4b-r1','transport':'streaming'},
                       *({'max_output_tokens':token} for token in (True,512,0,2048,'512',512.0))):
            with self.subTest(change=change):
                response=self.save({**prefs,**change})
                self.assertEqual(response.status_code,409)
        self.assertFalse(self.service.store.path.exists())
        self.assertEqual(self.f.sdk.bodies,[])
        budgets=value['models'][0]['modes']
        self.assertEqual(budgets['normal']['max_output_tokens'],1024)
        self.assertEqual(budgets['streaming']['max_output_tokens'],512)
        self.assertEqual(budgets['streaming']['approved_token_options'],[512,1024,2048,4096])
        self.assertTrue(budgets['normal']['editable'])

    def test_settings_consumes_one_bootstrap_projection_for_budget_metadata(self):
        configuration = self.f.backend._configuration
        with patch.object(self.f.backend,'_configuration',wraps=configuration) as configure, \
                patch.object(self.f.backend,'bootstrap',wraps=self.f.backend.bootstrap) as bootstrap:
            value = self.service.public(credentials=False)
        bootstrap.assert_called_once()
        # bootstrap composes two presets in two transports plus its history
        # candidate view. Settings must not do another private configuration pass.
        self.assertEqual(configure.call_count,5)
        qwen = next(model for model in value['models'] if model['preset_id']==self.f.profile.preset_id)
        self.assertEqual(qwen['modes']['normal']['max_output_tokens'],1024)
        self.assertEqual(qwen['modes']['normal']['default_output_tokens'],1024)
        self.assertEqual(qwen['modes']['normal']['approved_token_options'],[512,1024,2048,4096])
        self.assertTrue(qwen['modes']['normal']['editable'])
        self.assertEqual(qwen['modes']['streaming']['max_output_tokens'],512)
        self.assertEqual(qwen['modes']['streaming']['default_output_tokens'],512)
        self.assertTrue(qwen['modes']['streaming']['editable'])
        # The Settings response keeps its existing flattened API shape; the
        # extra internal projection remains scoped to the AI bootstrap DTO.
        self.assertNotIn('output_budget',qwen['modes']['normal'])
        with patch.object(self.service.store,'document',wraps=self.service.store.document) as read_budget, \
                patch.object(self.f.backend.management_policy,'snapshot',
                    wraps=self.f.backend.management_policy.snapshot) as read_policy:
            bootstrap_value = self.f.backend.bootstrap('pond-a')
        read_budget.assert_called_once()
        read_policy.assert_called_once()
        normal = bootstrap_value['presets'][0]['execution']['output_budget']
        streaming = bootstrap_value['presets'][0]['streaming']['output_budget']
        self.assertEqual(normal['default_output_tokens'],1024)
        self.assertEqual(streaming['default_output_tokens'],512)

    def test_stale_revision_epoch_policy_and_concurrent_save(self):
        value=self.read();prefs={**value['preferences'],'show_details':False}
        self.assertEqual(self.save(prefs,current=value).status_code,200)
        self.assertEqual(self.save(prefs,current=value).get_json()['error_code'],'SETTINGS_CHANGED')
        current=self.read()
        self.f.policy(['get_current_water_quality'])
        self.assertEqual(self.save(current['preferences'],current=current).get_json()['error_code'],'SETTINGS_CHANGED')
        self.assertEqual(self.save(current['preferences'],epoch='expired').get_json()['error_code'],'SETTINGS_CHANGED')
        current=self.read()
        body={'epoch':current['epoch'],'revision':current['revision'],'preferences':{**current['preferences'],'show_details':True}}
        def write(_):
            try:self.service.save(body);return 'ok'
            except SettingsError as e:return e.code
        with ThreadPoolExecutor(2) as pool: results=list(pool.map(write,range(2)))
        self.assertEqual(results.count('ok'),1)
        self.assertEqual(results.count('SETTINGS_CHANGED'),1)

    def test_credential_create_replace_clear_redaction_and_snapshot(self):
        logs=io.StringIO();handler=logging.StreamHandler(logs);logging.getLogger().addHandler(handler)
        self.addCleanup(logging.getLogger().removeHandler,handler)
        first=self.change();self.assertEqual(first.status_code,200,first.get_json())
        old=ProfileRegistry([self.f.profile],self.f.backend.credentials).snapshot(self.f.profile.profile_id)
        initial=old.credential.revision
        stale=first.get_json()['credential']['revision']
        self.assertEqual(self.change(secret='fictional-settings-key-B').status_code,200)
        fresh=ProfileRegistry([self.f.profile],self.f.backend.credentials).snapshot(self.f.profile.profile_id)
        self.assertNotEqual(initial,fresh.credential.revision)
        self.assertEqual(initial,old.credential.revision)
        # Only fake values, accessed here to prove snapshot isolation; never returned by API.
        self.assertEqual(old.credential._for_adapter(),'fictional-settings-key-A')
        self.assertEqual(fresh.credential._for_adapter(),'fictional-settings-key-B')
        rejected=self.change(secret='fictional-settings-key-C',revision=stale)
        self.assertEqual(rejected.get_json()['error_code'],'ENV_REVISION_CONFLICT')
        self.assertEqual(self.change(action='remove',secret=None).get_json()['error_code'],'CREDENTIAL_CLEAR_CONFIRMATION_REQUIRED')
        last=self.change(action='remove',secret=None,confirm_clear=True)
        self.assertEqual(last.get_json()['credential']['availability'],'MISSING')
        rendered=json.dumps([self.read(),first.get_json(),rejected.get_json(),last.get_json()])+logs.getvalue()
        for key in ('fictional-settings-key-A','fictional-settings-key-B','fictional-settings-key-C'):
            self.assertNotIn(key,rendered)
        self.assertEqual(self.f.sdk.bodies,[])
        secure_files.inspect_policy(self.f.backend.credentials.project_env_path)

    def test_environment_precedence_input_errors_permissions_and_atomic_failure(self):
        self.f.backend.credentials._process_env[self.ref]='fictional-environment-key'
        self.assertFalse(self.read()['credentials'][0]['editable'])
        self.assertEqual(self.change().get_json()['error_code'],'CREDENTIAL_READ_ONLY')
        self.f.backend.credentials._process_env.clear()
        for invalid in ('','newline\nkey',True,512,'x'*4097):
            self.assertEqual(self.change(secret=invalid).get_json()['error_code'],'INVALID_CREDENTIAL_VALUE')
        self.change()
        path=self.f.backend.credentials.project_env_path;before=path.read_bytes()
        with patch('apps.ai_backend.project_env.secure_files.atomic_replace',side_effect=OSError('fictional-private-message')):
            response=self.change(secret='fictional-replacement')
        self.assertEqual(response.get_json()['error_code'],'ENV_WRITE_FAILED')
        self.assertEqual(before,path.read_bytes())
        with patch('apps.ai_backend.project_env.secure_files.inspect_policy',side_effect=secure_files.SecureFileError()):
            self.assertEqual(self.read()['credentials'][0]['availability'],'UNAVAILABLE')
        self.assertNotIn('fictional-private-message',response.get_data(as_text=True))

    def test_access_control_never_allows_anonymous_or_foreign_writes(self):
        for path in ('/api/settings','/api/settings/credentials'):
            self.assertEqual(self.client.post(path,json={}).status_code,403)
            self.assertEqual(self.client.post(path,json={},headers={**self.headers,'Origin':'https://example.invalid'}).status_code,403)
        self.assertEqual(self.client.get('/api/settings',environ_overrides={'REMOTE_ADDR':'192.0.2.5'}).status_code,403)
        self.assertEqual(self.client.get('/api/settings',headers={'Host':'untrusted.local'}).status_code,403)

    def test_settings_do_not_mutate_running_turn_or_scope(self):
        self.change()
        old_body=self.f.envelope(streaming=True)
        prepared=self.f.backend.prepare_turn({k:v for k,v in old_body.items() if k not in ('request_id','control_token')},
            transport=ToolModelTransport.STREAMING)
        before=self.f.backend.bootstrap('pond-a')
        prefs={**self.read()['preferences'],'show_details':False}
        self.assertEqual(self.save(prefs).status_code,200)
        self.change(secret='fictional-other-key')
        self.assertEqual(before,self.f.backend.bootstrap('pond-a'))
        self.assertEqual(prepared.device_id,'pond-a')
        self.assertEqual(prepared.execution.max_output_tokens,512)
        self.assertEqual(prepared.registry.model_definitions(),self.f.backend._configuration(self.f.profile.preset_id,'pond-a',transport=prepared.execution.model_transport)[3].model_definitions())

    def test_forked_writer_preserves_unrelated_values_and_rejects_duplicate_keys(self):
        body=b"OTHER='fictional-unrelated'\n"
        changed=edit_env(body,self.ref,'create','fictional-key')
        self.assertTrue(changed.startswith(body))
        with self.assertRaises(EnvWriteError):edit_env(changed+changed,self.ref,'replace','fictional-next')

    def test_inflight_http_double_tool_keeps_device_credential_and_budget_snapshot(self):
        self.change()
        observed=[]
        def update(index):
            if index != 0:return
            current=self.service.public()
            self.service.save({'epoch':current['epoch'],'revision':current['revision'],
                'preferences':{**current['preferences'],'device_id':'pond-b','show_details':False}})
            credential=self.service.credential_status('dashscope')
            proof=self.service.connection_tests.run({'epoch':self.f.web.epoch,'provider':'dashscope',
                'source':'input','secret':'fictional-midturn-key','revision':credential['revision'],'confirm_network':True})
            self.service.change_credential({'epoch':self.f.web.epoch,'provider':'dashscope',
                'action':'save','revision':credential['revision'],'secret':'fictional-midturn-key','confirm_clear':False,
                'test_token':proof['test_token']})
        self.f.sdk=FakeSDK(self.f.plans((fixture.WATER,fixture.KNOWLEDGE)),model=self.f.profile.model,on_close=update)
        original=self.f.sdk.factory
        def factory(runtime,remaining):
            observed.append((runtime.credential.revision,runtime.credential._for_adapter()))
            return original(runtime,remaining)
        self.f.backend.gateway_factory=lambda:fixture.OpenAICompatibleAdapter(async_client_factory=factory)
        result=self.client.post('/api/ai/messages',json=self.f.envelope(),headers=self.headers).get_json()['result']
        self.assertTrue(result['successful_turn'],result)
        self.assertEqual(len(observed),3)
        self.assertTrue(all(row==observed[0] for row in observed))
        self.assertEqual(observed[0][1],'fictional-settings-key-A')
        self.assertEqual(self.service.preferences()['device_id'],'pond-b')
        self.assertTrue(all(body['max_tokens']==1024 for body in self.f.sdk.bodies))
        water=json.loads(next(m['content'] for m in self.f.sdk.bodies[1]['messages'] if m['role']=='tool'))
        self.assertEqual(water['device_id'],'pond-a')
        public=json.dumps(result)+self.f.backend.traces.path.read_text(encoding='utf-8')
        self.assertNotIn('fictional-midturn-key',public)
        self.assertNotIn('fictional-settings-key-A',public)

    def test_storage_error_is_bounded_and_previous_preferences_remain(self):
        current=self.read();self.save(current['preferences']);before=self.service.store.path.read_bytes()
        with patch('apps.ai_service.settings_store.os.replace',side_effect=OSError('private details')):
            result=self.save({**current['preferences'],'show_details':False})
        self.assertEqual(result.get_json()['error_code'],'SETTINGS_STORAGE_ERROR')
        self.assertEqual(before,self.service.store.path.read_bytes())
