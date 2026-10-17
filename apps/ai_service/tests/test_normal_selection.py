"""Model chooses among three definitions; admission remains closed in product."""
from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from apps.ai_backend.execution import RequestHandle
from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.tests.support import FakeSDK, sdk_tool, sdk_final
from apps.ai_backend.tool_conversation import ToolModelTransport
from apps.ai_service import service as composition
from apps.ai_service.normal_selection import (NORMAL_SELECTION_CANDIDATE, normal_selection_scope,
    load_normal_selection_candidate, resolve_normal_selection_candidate)
from apps.ai_service.runtime.release_contracts import _json
from apps.ai_service.runtime import assistant, sources
from apps.ai_service.tests import test_history_candidate as base
HISTORY, fixtures = base.HISTORY, base.fixtures
from apps.ai_service.business_tools.registry import HISTORY_CANDIDATE_TOOL_NAMES, FORMAL_TOOL_NAMES

WATER, KNOWLEDGE = FORMAL_TOOL_NAMES
ARGS = {WATER: '{}', KNOWLEDGE: '{"query":"鳗鲡低氧表现"}', HISTORY: fixtures.ARGS}


class NormalSelectionTests(unittest.TestCase):
    setUp = base.HistoryCandidateTests.setUp
    configure = base.HistoryCandidateTests.configure
    make_monitoring = base.HistoryCandidateTests.make_monitoring
    policy = base.HistoryCandidateTests.policy

    def configuration(self, **changes):
        return self.backend._configuration(changes.pop('preset', self.profile.preset_id),
            changes.pop('device_id', 'pond-a'), execution_profile=NORMAL_SELECTION_CANDIDATE, **changes)

    def body(self):
        decision = self.configuration()[2]
        return {'preset_id': self.profile.preset_id, 'device_id': 'pond-a', 'question': '离线模型选择',
            'epoch': self.backend.epoch, 'history': [], 'confirm_network': True,
            'revision': decision.profile.revision, 'execution_profile': NORMAL_SELECTION_CANDIDATE}

    def admission(self):
        original = resolve_normal_selection_candidate
        def permit(*args, **kwargs):
            decision = original(*args, **kwargs)
            return replace(decision, can_send=decision.profile.mode_reason == 'NORMAL_TOOL_CANDIDATE_NOT_RELEASED')
        return patch.object(composition, 'resolve_normal_selection_candidate', side_effect=permit)

    def test_pinned_candidate_scope_closed_and_separate_from_existing_releases(self):
        self.policy(list(HISTORY_CANDIDATE_TOOL_NAMES))
        p, policy, decision, registry = self.configuration()
        scope = normal_selection_scope(p, registry, self.backend.knowledge)
        self.assertEqual(_json(scope), load_normal_selection_candidate())
        self.assertEqual(scope['runtime']['tools'], list(HISTORY_CANDIDATE_TOOL_NAMES))
        self.assertEqual(scope['runtime']['prompt_id'], 'ASSISTANT_BOUNDED_MULTI_ROUND@1')
        self.assertEqual(scope['budget'], dict(calls=2, rounds=2, requests=3, retry=0,
                                            deadline_s=120, max_output_tokens=1024))
        self.assertEqual(decision.profile.release_status, 'candidate')
        self.assertFalse(decision.can_send)
        self.assertEqual(decision.profile.mode_reason, 'NORMAL_TOOL_CANDIDATE_NOT_RELEASED')
        with self.assertRaisesRegex(GatewayError, 'NORMAL_TOOL_CANDIDATE_NOT_RELEASED'):
            self.backend.prepare_turn(self.body())
        self.assertEqual(self.backend.formal_registry.registered_names(), FORMAL_TOOL_NAMES)
        self.assertEqual(registry.model_definitions(), self.backend.history_registry.model_definitions())
        self.assertFalse(self.sdk.bodies)

    def test_mismatch_policy_transport_identity_and_fingerprint_fail_closed(self):
        self.policy(list(FORMAL_TOOL_NAMES))
        self.assertEqual(self.configuration()[2].profile.mode_reason, 'NORMAL_TOOL_CANDIDATE_NOT_AUTHORIZED')
        self.policy(list(HISTORY_CANDIDATE_TOOL_NAMES))
        for options in ({'preset': composition.PRESETS[1]}, {'transport': ToolModelTransport.STREAMING}):
            with self.subTest(options=options), self.admission():
                self.assertFalse(self.configuration(**options)[2].can_send)
        with patch('apps.ai_service.normal_selection.load_normal_selection_candidate', return_value='{}'), self.admission():
            self.assertFalse(self.configuration()[2].can_send)
        a = self.configuration()[2].profile.revision
        self.assertNotEqual(a, self.configuration(device_id='pond-b')[2].profile.revision)
        self.assertFalse(self.sdk.bodies)

    def test_candidate_definition_order_is_frozen_independently_of_authorization_order(self):
        self.policy(list(reversed(HISTORY_CANDIDATE_TOOL_NAMES)))
        _, policy, decision, registry = self.configuration()
        self.assertEqual(tuple(d.name for d in policy.model_definitions(registry)), HISTORY_CANDIDATE_TOOL_NAMES)
        self.assertFalse(decision.can_send)
        self.assertEqual(decision.profile.mode_reason, 'NORMAL_TOOL_CANDIDATE_NOT_RELEASED')

    def test_candidate_resource_cannot_be_promoted_or_enabled_by_json(self):
        scope = json.loads(load_normal_selection_candidate())
        for status, enabled in (('local_experimental', False), ('released', False), ('candidate', True), ('candidate', 0)):
            payload = json.dumps(dict(scope=scope, status=status, enabled=enabled)).encode()
            with patch.object(Path, 'read_bytes', return_value=payload), self.assertRaisesRegex(
                    GatewayError, 'INVALID_NORMAL_TOOL_CANDIDATE'):
                load_normal_selection_candidate()

    def test_fake_model_autonomously_selects_each_tool_without_question_routing(self):
        for name in HISTORY_CANDIDATE_TOOL_NAMES:
            with self.subTest(name=name):
                self.configure('sparse'); self.policy(list(HISTORY_CANDIDATE_TOOL_NAMES))
                self.sdk = FakeSDK([sdk_tool(name, arguments=ARGS[name]), sdk_final()], model=self.profile.model)
                captured = []; original = assistant.AssistantService.send
                def capture(service, *args, **kwargs):
                    result = original(service, *args, **kwargs); captured.append(result); return result
                with self.admission(), patch.object(assistant.AssistantService, 'send', capture):
                    prepared = self.backend.prepare_turn(self.body())
                    result = self.backend.execute_turn(prepared, RequestHandle())
                self.assertTrue(result['successful_turn'])
                self.assertEqual(prepared.request.source_requirement, sources.SourceRequirement.AUTO)
                self.assertEqual([d['function']['name'] for d in self.sdk.bodies[0]['tools']],
                                 list(HISTORY_CANDIDATE_TOOL_NAMES))
                self.assertEqual([s['tool_name'] for s in result['activity']['steps'] if s['kind'] == 'tool'], [name])
                self.assertEqual([call['function']['name'] for m in self.sdk.bodies[1]['messages'] for call in m.get('tool_calls', [])], [name])
                receipt = captured[0].source_receipt
                self.assertEqual(receipt.history_query_completed, name == HISTORY)
                if name == HISTORY:
                    self.assertFalse(sources.requirement_satisfied(sources.SourceRequirement.CURRENT_OBSERVATION_QUERY, receipt))
                self.assertEqual(len(self.sdk.bodies), 2)
                self.assertTrue(all(b['max_tokens'] == 1024 for b in self.sdk.bodies))
                self.assertTrue(all(client.closed for client in self.sdk.clients))

    def test_two_tools_replan_from_real_result_and_no_fourth_request(self):
        for names in ((), (WATER, HISTORY), (HISTORY, KNOWLEDGE), (WATER, HISTORY, KNOWLEDGE)):
            with self.subTest(names=names):
                self.configure('sparse'); self.policy(list(HISTORY_CANDIDATE_TOOL_NAMES))
                plans = [sdk_tool(name, arguments=ARGS[name], identifier='c'+str(i)) for i, name in enumerate(names)]
                self.sdk = FakeSDK([*plans, sdk_final()], model=self.profile.model)
                with self.admission():
                    result = self.backend.execute_turn(self.backend.prepare_turn(self.body()), RequestHandle())
                self.assertEqual(result['successful_turn'], len(names) <= 2)
                executed = [s['tool_name'] for s in result['activity']['steps'] if s['kind'] == 'tool' and s['handler_started']]
                self.assertEqual(executed, list(names[:2]))
                self.assertLessEqual(len(self.sdk.bodies), 3)
                for i, body in enumerate(self.sdk.bodies):
                    self.assertEqual([call['function']['name'] for m in body['messages'] for call in m.get('tool_calls', [])], list(names[:i]))
                if len(names) > 2:
                    self.assertFalse(result['successful_turn'])
                    self.assertEqual(result['final_text'], '')

    def test_web_accepts_only_business_action_and_never_arbitrary_candidate_controls(self):
        self.policy(list(HISTORY_CANDIDATE_TOOL_NAMES))
        bootstrap = self.web.bootstrap('pond-a')
        self.assertNotIn('history_candidate', bootstrap)
        self.assertNotIn('execution_profile', bootstrap['history_query'])
        for extra in ({'execution_profile': NORMAL_SELECTION_CANDIDATE}, {'action': NORMAL_SELECTION_CANDIDATE},
                      {'action': 'history_query', 'budget': 3}):
            control = self.web.prepare()
            body = {**self.body(), **control}; body.pop('execution_profile')
            with self.assertRaisesRegex(GatewayError, 'INVALID_ASSISTANT_REQUEST'):
                self.web.send({**body, **extra})
        self.assertFalse(self.sdk.bodies)
