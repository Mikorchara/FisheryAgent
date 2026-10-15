"""Web owns access/control tokens; business backend receives only its contract."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from apps.ai_service.contracts import AssistantBackend
from apps.management_web.ai_adapter import ManagementAssistant
from apps.management_web.app import create_app


class WebAIBoundaryTests(unittest.TestCase):
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
