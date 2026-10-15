"""Management Streaming scope is independent, startup-frozen and candidate by default."""
from dataclasses import replace,FrozenInstanceError
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from fishery_ai.model_gateway import GatewayError
from apps.ai_service.streaming import ManagementStreamingConfig,load_streaming_config,STREAMING_PRESET


class StreamingConfigTests(unittest.TestCase):
    def data(self):return json.loads((Path(__file__).parents[1]/'resources/assistant_streaming.json').read_text(encoding='utf-8'))

    def test_only_qwen_candidate_default_disabled_no_prototype_loader_or_fake_qualification(self):
        with patch('fishery_ai.assistant_streaming.load_assistant_streaming_config',side_effect=AssertionError('not Prototype')):
            config=load_streaming_config()
        self.assertFalse(config.enabled);self.assertEqual(len(config.releases),1)
        record=config.releases[0].runtime;scope=json.loads(record.scope_json)
        self.assertEqual(record.status,'candidate');self.assertEqual(record.max_output_tokens,512)
        self.assertIsNone(record.qualification_id);self.assertIsNone(record.validated_at)
        self.assertEqual(scope['preset_id'],STREAMING_PRESET)
        self.assertEqual(scope['response_mode'],'streaming');self.assertEqual(scope['model_transport'],'STREAMING')
        self.assertEqual(scope['tools'],['get_current_water_quality','search_fishery_knowledge'])
        with self.assertRaises(FrozenInstanceError):config.enabled=True

    def test_invalid_config_types_budget_and_unapproved_scope_rejected(self):
        for key,value in (('enabled',1),('schema_version',True),('extra',True)):
            data=self.data();data[key]=value
            with self.assertRaises(GatewayError):ManagementStreamingConfig.from_dict(data)
        for budget in (True,False,0,513,256.5,'512'):
            data=self.data();data['releases'][0]['max_output_tokens']=budget
            with self.assertRaises(GatewayError):ManagementStreamingConfig.from_dict(data)
        for value in ('ollama-qwen35-4b-r1','deepseek-flash-r1'):
            data=self.data();data['releases'][0]['scope']['runtime']['preset_id']=value
            with self.assertRaises(GatewayError):ManagementStreamingConfig.from_dict(data)
        for key,value in (('status','released'),('qualification_id','invented'),('validated_at','invented')):
            data=self.data();data['releases'][0][key]=value
            with self.assertRaises(GatewayError):ManagementStreamingConfig.from_dict(data)
        data=self.data();data['releases'].append(data['releases'][0])
        with self.assertRaises(GatewayError):ManagementStreamingConfig.from_dict(data)
