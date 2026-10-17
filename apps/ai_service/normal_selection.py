"""Closed three-Tool Normal candidate. Never inherits existing trial approval."""

from dataclasses import asdict
import json
from pathlib import Path

from apps.ai_backend.history_projection import TRANSCRIPT_NOTICE
from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.tool_conversation import ToolExecutionMode, ToolModelTransport
from apps.ai_backend.tools.policy import ToolPolicy
from apps.monitoring.history import HISTORY_VERSION, MAX_HISTORY_ROWS, MAX_HISTORY_ITEMS, MAX_HISTORY_RESULT_BYTES
from .business_tools.registry import HISTORY_CANDIDATE_TOOL_NAMES
from .execution import management_scope, ExecutionDecision
from .runtime.release_contracts import AssistantExecutionProfile, _hash, _json
from .runtime.sources import HISTORY_SOURCE_CONTRACT_VERSION

NORMAL_SELECTION_CANDIDATE = 'management-normal-three-tools@1'


def normal_selection_scope(profile, registry, knowledge):
    policy = ToolPolicy('assistant', True, HISTORY_CANDIDATE_TOOL_NAMES)
    return {**management_scope(profile, policy, registry, knowledge),
        'transport': 'NORMAL', 'history_framing_sha256': _hash(TRANSCRIPT_NOTICE),
        'generation': asdict(profile.default_generation),
        'history_binding': {'version': HISTORY_VERSION, 'device': 'FROZEN_PER_TURN',
            'max_rows': MAX_HISTORY_ROWS, 'max_items': MAX_HISTORY_ITEMS,
            'max_result_bytes': MAX_HISTORY_RESULT_BYTES, 'source_version': HISTORY_SOURCE_CONTRACT_VERSION},
        'budget': {'calls': 2, 'rounds': 2, 'requests': 3, 'retry': profile.max_retries,
                   'deadline_s': profile.total_timeout_s, 'max_output_tokens': 1024}}


def load_normal_selection_candidate():
    """Fixed maintainer plan, not an enable switch or a Web-controlled file path."""
    try:
        path = Path(__file__).with_name('resources') / 'assistant_normal_candidate.json'
        value = json.loads(path.read_bytes() if path.stat().st_size <= 16384 else b'')
        if (set(value) != {'scope', 'status', 'enabled'} or value['status'] != 'candidate'
                or value['enabled'] is not False or not isinstance(value['scope'], dict)):
            raise ValueError()
        return _json(value['scope'])
    except (OSError, ValueError, TypeError, RecursionError):
        raise GatewayError('INVALID_NORMAL_TOOL_CANDIDATE') from None


def resolve_normal_selection_candidate(profile, selected, registry, knowledge, *, device_id, epoch,
                                        policy_revision, transport=ToolModelTransport.NORMAL):
    scope = normal_selection_scope(profile, registry, knowledge)
    matched = (transport == ToolModelTransport.NORMAL and scope['runtime']['thinking'] == 'off'
        and scope['budget']['retry'] == 0 and scope['budget']['deadline_s'] == 120
        and _json(scope) == load_normal_selection_candidate())
    authorized = set(selected.exposed_tools) == set(HISTORY_CANDIDATE_TOOL_NAMES)
    reason = ('NORMAL_TOOL_CANDIDATE_SCOPE_MISMATCH' if not matched else
              'NORMAL_TOOL_CANDIDATE_NOT_AUTHORIZED' if not authorized else
              'NORMAL_TOOL_CANDIDATE_NOT_RELEASED')
    revision = _hash({'candidate': NORMAL_SELECTION_CANDIDATE, 'scope': scope,
                     'device_id': device_id, 'epoch': epoch, 'policy_revision': policy_revision})
    # Offline qualification may explicitly stub admission. Product cannot enable it.
    return ExecutionDecision(AssistantExecutionProfile(ToolExecutionMode.BOUNDED_MULTI_ROUND,
        revision, 'candidate', reason), False, max_output_tokens=1024)
