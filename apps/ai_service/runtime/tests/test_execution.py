"""Independent management release contracts; no Provider or private state."""

from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from apps.ai_backend.model_gateway import GatewayError
from apps.ai_service.runtime.execution import ManagementExecutionConfig, load_execution_config


class ManagementExecutionTests(unittest.TestCase):
    def config_data(self):
        return json.loads((Path(__file__).parents[2]/'resources/assistant_execution.json').read_text(encoding='utf-8'))

    def test_default_off_and_independent_explicit_scopes_no_qualification_claim(self):
        with patch('fishery_ai.assistant_execution.load_assistant_execution_config',side_effect=AssertionError('not Prototype')):
            config = load_execution_config()
        self.assertFalse(config.multi_round_enabled)
        self.assertTrue(load_execution_config(enable_trial=True).multi_round_enabled)
        self.assertFalse(load_execution_config().multi_round_enabled)
        self.assertEqual(len(config.releases),2)
        scopes = [json.loads(r.runtime.scope_json) for r in config.releases]
        self.assertEqual({s['preset_id'] for s in scopes},{'dashscope-qwen38-flash-r1','ollama-qwen35-4b-r1'})
        self.assertNotEqual(scopes[0]['identity'],scopes[1]['identity'])
        for release, scope in zip(config.releases,scopes):
            self.assertTrue(release.runtime.release_id.startswith('management-'))
            self.assertEqual(release.runtime.status,'local_experimental')
            self.assertIsNone(release.runtime.qualification_id);self.assertIsNone(release.runtime.validated_at)
            self.assertEqual(scope['prompt_id'],'ASSISTANT_BOUNDED_MULTI_ROUND@1')
            self.assertEqual(scope['thinking'],'off');self.assertEqual(scope['response_mode'],'normal')
            self.assertEqual(scope['tools'],['get_current_water_quality','search_fishery_knowledge'])

    def test_invalid_config_and_unsupported_release_claims_rejected(self):
        for field, value in [('multi_round_enabled',1),('schema_version',True),('extra',1)]:
            data=self.config_data();data[field]=value
            with self.subTest(field=field),self.assertRaises(GatewayError):ManagementExecutionConfig.from_dict(data)
        for field,value in [('status','released'),('qualification_id','invented'),('validated_at','invented')]:
            data=self.config_data();data['releases'][0][field]=value
            with self.subTest(field=field),self.assertRaises(GatewayError):ManagementExecutionConfig.from_dict(data)
        with self.assertRaises(GatewayError):load_execution_config(enable_trial=1)

    def test_config_frozen_and_duplicate_ids_rejected(self):
        data=self.config_data();data['releases'].append(data['releases'][0])
        with self.assertRaises(GatewayError):ManagementExecutionConfig.from_dict(data)
        config=load_execution_config()
        self.assertEqual(replace(config,multi_round_enabled=True).releases,config.releases)
