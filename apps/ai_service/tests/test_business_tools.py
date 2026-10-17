"""Static business Tool ownership and pre-move contract fingerprints; offline only."""
import ast
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from apps.ai_backend.tools.executor import ToolExecutor
from apps.ai_backend.tools.policy import ToolPolicy
from apps.ai_backend.model_gateway import ModelToolCall
from apps.ai_backend.tool_argument_diagnostics import ToolArgumentError
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.simulator.generator import Simulator


ROOT = Path(__file__).resolve().parents[3]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def capture_contracts(water, knowledge):
    """Same deterministic inputs before/after move; retain hashes and finite metadata."""
    definitions = (water.WATER_DEFINITION, knowledge.KNOWLEDGE_DEFINITION)
    result = {'definitions': [{'name': d.name, 'type': d.type, 'description': d.description,
        'parameters': d.parameters_dict()} for d in definitions], 'water': {}, 'knowledge': {}}
    result['definitions_sha256'] = digest(result.pop('definitions'))
    result['tool_names'] = [d.name for d in definitions]
    result['knowledge_budget'] = [knowledge.TOP_K, knowledge.MAX_TEXT_CHARS, knowledge.MAX_QUERY_CHARS]
    for case in ('no_data', 'valid', 'low_oxygen', 'partial', 'invalid', 'stale', 'offline'):
        with TemporaryDirectory() as directory:
            clock = [datetime(2026, 10, 17, tzinfo=timezone.utc)]
            service = MonitoringService(MonitoringRepository(Path(directory)/'fixture.sqlite3'),
                device_names={'pond-a': 'Fixture'}, clock=lambda: clock[0])
            if case != 'no_data':
                batch = Simulator(start=clock[0], session_id='tool-contract', device_id='pond-a', seed=42).advance()
                clock[0] = datetime.fromisoformat(batch['timestamp'])
                oxygen = 2.2 if case == 'low_oxygen' else 6.4
                batch['water']['metrics']['dissolved_oxygen_mg_l'].update(
                    mean=oxygen, min=oxygen, max=oxygen, latest=oxygen)
                if case == 'partial':
                    batch['water']['metrics']['ph'].update(mean=None, min=None, max=None,
                        latest=None, valid_samples=0, invalid_samples=0)
                if case == 'invalid':
                    batch['water']['metrics']['ph'].update(valid_samples=9, invalid_samples=1)
                service.ingest(batch)
                clock[0] += timedelta(seconds=31 if case == 'stale' else 91 if case == 'offline' else 0)
            payload = water.water_payload(service, 'pond-a')
            observation = payload['water_quality'] or {}
            result['water'][case] = {'sha256': digest(payload), 'status': payload['status'],
                'quality': observation.get('quality'), 'freshness': observation.get('freshness'),
                'connectivity': payload['connectivity']}
    for case, evidence in (
        ('no_match', []),
        ('hit', [SimpleNamespace(evidence_id='fixture-e1', category='fixture', source_id='fixture-source',
            source_version='1', text='背景资料')]),
        ('bounded_text', [SimpleNamespace(evidence_id='fixture-e1', category='fixture', source_id='fixture-source',
            source_version='1', text='背景资料'*300)]),
    ):
        service = SimpleNamespace(backend='portable', search=Mock(return_value=evidence))
        arguments = knowledge.validate_arguments({'query': ' 固定离线主题 '})
        payload = knowledge.search_fishery_knowledge(arguments, service=service)
        service.search.assert_called_once_with('固定离线主题', top_k=3)
        result['knowledge'][case] = {'sha256': digest(payload), 'status': payload['status'],
            'result_count': payload['result_count']}
    return result


class BusinessToolTests(unittest.TestCase):
    def setUp(self):
        for target in ('socket.socket.connect', 'socket.socket.connect_ex', 'socket.socket.sendto',
                       'socket.getaddrinfo', 'socket.create_connection'):
            guard = patch(target, side_effect=AssertionError('business Tool tests forbid network'))
            guard.start(); self.addCleanup(guard.stop)

    def test_definition_and_handler_dto_fingerprints_equal_pre_move_baseline(self):
        from apps.ai_service.business_tools import current_water_quality as water, fishery_knowledge as knowledge
        expected = json.loads((Path(__file__).with_name('fixtures')/'r2c2b_business_tools.json').read_text(encoding='utf-8'))
        self.assertEqual(capture_contracts(water, knowledge), expected)

    def test_registry_rebinds_only_frozen_water_handler_and_keeps_formal_knowledge(self):
        from apps.ai_service.business_tools.registry import bind_tools, KNOWN_TOOL_NAMES, WATER_QUALITY_SCORE
        from apps.ai_service.business_tools import current_water_quality as water, fishery_knowledge as knowledge
        shared = SimpleNamespace(search=Mock(return_value=[]), backend='portable')
        monitoring = SimpleNamespace(capture_water=Mock())
        formal = bind_tools(monitoring, 'pond-a', shared)
        first = bind_tools(monitoring, 'pond-a', shared, formal=formal)
        second = bind_tools(monitoring, 'pond-b', shared, formal=formal)
        for registry in (formal, first, second):
            self.assertEqual(registry.model_definitions(), formal.model_definitions())
            self.assertEqual(registry.registered_names(), (water.CURRENT_WATER_QUALITY, knowledge.SEARCH_FISHERY_KNOWLEDGE))
            self.assertIs(registry.lookup(knowledge.SEARCH_FISHERY_KNOWLEDGE), formal.lookup(knowledge.SEARCH_FISHERY_KNOWLEDGE))
            self.assertIs(registry.lookup(water.CURRENT_WATER_QUALITY).model_definition, water.WATER_DEFINITION)
            self.assertNotIn(WATER_QUALITY_SCORE, registry.registered_names())
        self.assertIn(WATER_QUALITY_SCORE, KNOWN_TOOL_NAMES)
        monitoring.capture_water.assert_not_called()
        with patch.object(water, 'project_water_tool', side_effect=lambda capture: {'status': 'NO_DATA', 'capture': capture}):
            first.lookup(water.CURRENT_WATER_QUALITY).handler()
            second.lookup(water.CURRENT_WATER_QUALITY).handler()
        self.assertEqual(monitoring.capture_water.call_args_list, [unittest.mock.call('pond-a'), unittest.mock.call('pond-b')])
        first.lookup(knowledge.SEARCH_FISHERY_KNOWLEDGE).bind({'query': '固定主题'})()
        shared.search.assert_called_once_with('固定主题', top_k=3)

    def test_arguments_and_policy_reject_before_handler_and_keep_score_unbound(self):
        from apps.ai_service.business_tools.registry import bind_tools, WATER_QUALITY_SCORE
        from apps.ai_service.business_tools import current_water_quality as water, fishery_knowledge as knowledge
        shared = SimpleNamespace(search=Mock(return_value=[]), backend='portable')
        monitoring = SimpleNamespace(capture_water=Mock())
        registry = bind_tools(monitoring, 'pond-a', shared)
        names = registry.registered_names()
        for name, arguments in ((water.CURRENT_WATER_QUALITY, '{"device_id":"pond-b"}'),
            (knowledge.SEARCH_FISHERY_KNOWLEDGE, '{"query":"x","top_k":9}'),
            (knowledge.SEARCH_FISHERY_KNOWLEDGE, '{"query":true}'),
            (knowledge.SEARCH_FISHERY_KNOWLEDGE, '{"query":"\\u0000"}'),
            (knowledge.SEARCH_FISHERY_KNOWLEDGE, '{"query":"\\ud800"}')):
            executor = ToolExecutor(registry, policy=ToolPolicy('assistant', True, names))
            result = executor.execute(ModelToolCall('call', name, arguments))
            self.assertEqual(result.error_code.value, 'INVALID_TOOL_ARGUMENTS')
        for arguments in ('{', '[]'):
            with self.assertRaises(ToolArgumentError):
                ModelToolCall('call', knowledge.SEARCH_FISHERY_KNOWLEDGE, arguments)
        for name, code in ((knowledge.SEARCH_FISHERY_KNOWLEDGE, 'TOOL_NOT_ALLOWED'),
                           (WATER_QUALITY_SCORE, 'UNKNOWN_TOOL')):
            result = ToolExecutor(registry, policy=ToolPolicy('assistant', True, (water.CURRENT_WATER_QUALITY,))).execute(
                ModelToolCall('call', name, '{"query":"x"}' if name == knowledge.SEARCH_FISHERY_KNOWLEDGE else '{}'))
            self.assertEqual(result.error_code.value, code)
        monitoring.capture_water.assert_not_called(); shared.search.assert_not_called()

    def test_new_modules_own_implementations_and_application_has_no_old_tool_entry(self):
        from apps.ai_service.business_tools import current_water_quality as water, fishery_knowledge as knowledge
        from apps.ai_service.business_tools.registry import bind_tools
        from apps.ai_service import service
        from apps.ai_service.development import streaming_qualification
        self.assertIs(service.bind_tools, bind_tools)
        self.assertIs(streaming_qualification.bind_tools, bind_tools)
        self.assertEqual(water.water_payload.__module__, water.__name__)
        self.assertEqual(water.project_water_tool.__module__, water.__name__)
        self.assertEqual(knowledge.search_fishery_knowledge.__module__, knowledge.__name__)
        self.assertEqual(knowledge.validate_arguments.__module__, knowledge.__name__)
        self.assertEqual(bind_tools.__module__, 'apps.ai_service.business_tools.registry')
        self.assertFalse((ROOT/'apps/ai_service/bindings.py').exists())
        self.assertFalse((ROOT/'apps/ai_service/runtime/tools.py').exists())
        forbidden = {'apps.ai_service.bindings', 'apps.ai_service.runtime.tools'}
        for folder in ('apps/ai_service', 'apps/management_web'):
            for path in (ROOT/folder).rglob('*.py'):
                if 'tests' in path.parts: continue
                package = '.'.join(path.relative_to(ROOT).parts[:-1])
                for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                    if isinstance(node, ast.ImportFrom):
                        import importlib.util
                        module = importlib.util.resolve_name('.'*node.level+(node.module or ''), package) if node.level else node.module
                        self.assertNotIn(module, forbidden, str(path))
                        for alias in node.names:
                            self.assertNotIn(module+'.'+alias.name, forbidden, str(path))
                    elif isinstance(node, ast.Import):
                        self.assertTrue(all(alias.name not in forbidden for alias in node.names), str(path))
