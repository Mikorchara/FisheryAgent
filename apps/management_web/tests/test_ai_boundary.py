"""Web owns access/control tokens; business backend receives only its contract."""

from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from apps.ai_service.contracts import AssistantBackend
from apps.management_web.ai_adapter import ManagementAssistant
from apps.management_web.app import create_app


class WebAIBoundaryTests(unittest.TestCase):
    def test_installed_entrypoint_keeps_workspace_identity_and_refuses_unknown_root(self):
        from apps.management_web.__main__ import project_root
        with TemporaryDirectory() as temporary:
            root=Path(temporary);workspace=root/'workspace';workspace.mkdir()
            (workspace/'pyproject.toml').write_text('[project]\nname="fixture"',encoding='utf-8')
            (workspace/'apps').mkdir()
            installed=root/'install/site-packages/apps/management_web/__main__.py'
            self.assertEqual(project_root(module_file=installed,working_directory=workspace),workspace.resolve())
            with self.assertRaisesRegex(ValueError,'WORKSPACE_REQUIRED'):
                project_root(module_file=installed,working_directory=root)
        self.assertEqual(project_root(),Path(__file__).resolve().parents[3])
    def test_local_adapter_forwards_explicit_trial_flags_only_to_business_composition(self):
        with patch('apps.management_web.ai_adapter.ManagementAssistantService.local') as local:
            adapter=ManagementAssistant.local(None,'.',streaming_trial=True)
        self.assertIs(adapter.backend,local.return_value)
        self.assertEqual(local.call_args.kwargs,{'multi_round_trial':False,'streaming_trial':True,'history_trial':False,'unified_tools_trial':False})

    def test_cli_streaming_opt_in_requires_assistant_and_preserves_local_startup(self):
        import io
        from apps.management_web.__main__ import main
        with patch('sys.argv',['management_web','--assistant-streaming-trial']), \
             patch('sys.stderr',new_callable=io.StringIO), \
             patch('apps.management_web.ai_adapter.ManagementAssistant.local') as local:
            with self.assertRaises(SystemExit):main()
        local.assert_not_called()
        with patch('sys.argv',['management_web','--assistant-history-trial']), \
             patch('sys.stderr',new_callable=io.StringIO), \
             patch('apps.management_web.ai_adapter.ManagementAssistant.local') as local:
            with self.assertRaises(SystemExit):main()
        local.assert_not_called()
        for options in ([],['--assistant-streaming-trial'],['--assistant-history-trial'],
                        ['--assistant-tools-trial','--assistant-multi-round-trial','--assistant-streaming-trial'],
                        ['--assistant-streaming-trial','--assistant-multi-round-trial','--assistant-history-trial']):
            with patch('sys.argv',['management_web','--enable-assistant',*options]), \
                 patch('apps.monitoring.repository.MonitoringRepository'), \
                 patch('apps.monitoring.service.MonitoringService'), \
                 patch('apps.management_web.ai_adapter.ManagementAssistant.local') as local, \
                 patch('apps.management_web.__main__.create_app') as factory,patch('builtins.print'):
                main()
            self.assertEqual(local.call_args.kwargs,{'multi_round_trial':'--assistant-multi-round-trial' in options,
                'streaming_trial':'--assistant-streaming-trial' in options,
                'history_trial':'--assistant-history-trial' in options,
                'unified_tools_trial':'--assistant-tools-trial' in options})
            self.assertEqual(factory.return_value.run.call_args.kwargs,
                {'host':'127.0.0.1','port':8766,'debug':False,'load_dotenv':False})

    def setUp(self):
        self.monitoring = SimpleNamespace()
        self.backend = Mock(spec=AssistantBackend)
        self.backend.monitoring = self.monitoring
        self.backend.epoch = 'fixture-epoch'
        self.backend.bootstrap.return_value = {'epoch':self.backend.epoch, 'tools':[], 'presets':[]}
        self.adapter = ManagementAssistant(self.backend)
        self.client = create_app(data_service=self.monitoring,ai=self.adapter).test_client()
        self.headers = {'X-Management-AI':self.adapter.browser_token}

    def test_bootstrap_injects_web_token_and_control_endpoints_do_not_call_business(self):
        public = self.client.get('/api/ai/bootstrap?device=pond-a').get_json()
        self.assertEqual(public['browser_token'],self.adapter.browser_token)
        self.backend.bootstrap.assert_called_once_with('pond-a')
        control = self.client.post('/api/ai/requests',headers=self.headers,json={'epoch':self.backend.epoch}).get_json()
        self.assertIn('control_token',control)
        self.client.post('/api/ai/request-state',headers=self.headers,json=control)
        self.client.post('/api/ai/cancel',headers=self.headers,json=control)
        self.assertEqual(self.adapter.handle(control).public_info()['state'],'CANCELLED')
        self.backend.prepare_turn.assert_not_called();self.backend.execute_turn.assert_not_called()

    def test_business_preparation_and_execution_share_same_handle_without_web_fields(self):
        control = self.adapter.prepare()
        body = {**control,'question':'fixture-question','epoch':self.backend.epoch,'confirm_network':True}
        self.backend.execute_turn.return_value = {'successful_turn':True,'final_text':'fixture-answer'}
        response = self.client.post('/api/ai/messages',headers=self.headers,json=body)
        self.assertEqual(response.status_code,200)
        self.backend.prepare_turn.assert_called_once_with({'question':'fixture-question',
            'epoch':self.backend.epoch,'confirm_network':True})
        self.backend.execute_turn.assert_called_once_with(self.backend.prepare_turn.return_value,
            self.adapter.handle(control))
        self.assertNotIn('control_token',self.backend.prepare_turn.call_args.args[0])
        self.assertNotIn('browser_token',self.backend.prepare_turn.call_args.args[0])

    def test_access_controls_run_before_business_and_structural_protocol_is_not_permission(self):
        for options in ({'headers':{'X-Management-AI':'wrong'}},
                        {'headers':{**self.headers,'Origin':'http://untrusted.invalid'}},
                        {'headers':self.headers,'environ_overrides':{'REMOTE_ADDR':'10.0.0.1'}}):
            response = self.client.post('/api/ai/messages',json={},**options)
            self.assertEqual(response.status_code,403)
        self.backend.prepare_turn.assert_not_called();self.backend.execute_turn.assert_not_called()
        unwrapped = create_app(data_service=self.monitoring,ai=self.backend).test_client()
        self.assertEqual(unwrapped.post('/api/ai/messages',json={}).status_code,503)

    def test_monitoring_identity_mismatch_still_rejected(self):
        with self.assertRaisesRegex(ValueError,'AI_MONITORING_SOURCE_MISMATCH'):
            create_app(data_service=SimpleNamespace(),ai=self.adapter)
