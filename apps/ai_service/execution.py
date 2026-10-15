"""Management-only startup-frozen Scope/flag; reuse the Runtime's scope resolver."""

from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path

from fishery_ai.assistant_execution import (AssistantExecutionConfig, AssistantExecutionProfile,
    AssistantMultiRoundRelease, release_scope, resolve_execution_profile)
from fishery_ai.history_projection import DEFAULT_HISTORY_PROJECTION
from fishery_ai.model_gateway import GatewayError
from fishery_ai.tool_conversation import ToolExecutionMode, ToolModelTransport

from . import bindings


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def data_bindings(knowledge):
    return {'water': bindings.WATER_TOOL_PROJECTION, 'knowledge': bindings.KNOWLEDGE_BINDING_VERSION,
        'knowledge_source': knowledge.source_id, 'knowledge_version': knowledge.source_version,
        'retrieval_backend': knowledge.backend}


def management_scope(profile, policy, registry, knowledge):
    return {'runtime': release_scope(profile, policy, registry, DEFAULT_HISTORY_PROJECTION),
            'data_bindings': data_bindings(knowledge)}


@dataclass(frozen=True)
class ManagementRelease:
    runtime: AssistantMultiRoundRelease
    data_bindings_json: str

    def __post_init__(self):
        try:
            source=json.loads(self.data_bindings_json)
            if (not isinstance(self.runtime,AssistantMultiRoundRelease)
                    or self.runtime.status not in ('candidate','local_experimental')
                    or self.runtime.qualification_id is not None or self.runtime.validated_at is not None
                    or not isinstance(source,dict) or set(source) != {
                        'water','knowledge','knowledge_source','knowledge_version','retrieval_backend'}
                    or any(not isinstance(v,str) or not 1<=len(v)<=128 for v in source.values())):
                raise ValueError()
            object.__setattr__(self,'data_bindings_json',_json(source))
        except (ValueError,TypeError,AttributeError):
            raise GatewayError('INVALID_MANAGEMENT_EXECUTION_CONFIG') from None


@dataclass(frozen=True)
class ManagementExecutionConfig:
    multi_round_enabled: bool = False
    releases: tuple[ManagementRelease, ...] = ()

    def __post_init__(self):
        if (type(self.multi_round_enabled) is not bool or type(self.releases) is not tuple
                or len(self.releases) > 8 or any(not isinstance(r, ManagementRelease) for r in self.releases)
                or len({r.runtime.release_id for r in self.releases}) != len(self.releases)
                or len({(r.runtime.scope_json,r.data_bindings_json) for r in self.releases}) != len(self.releases)):
            raise GatewayError('INVALID_MANAGEMENT_EXECUTION_CONFIG')

    @classmethod
    def from_dict(cls, value):
        try:
            if (not isinstance(value, dict) or set(value) != {'schema_version','multi_round_enabled','releases'}
                    or type(value['schema_version']) is not int or value['schema_version'] != 1
                    or not isinstance(value['releases'], list)):
                raise ValueError()
            records = []
            for entry in value['releases']:
                if (set(entry) != {'release_id','status','scope','qualification_id','validated_at'}
                        or entry['status'] not in ('candidate','local_experimental')
                        or entry['qualification_id'] is not None or entry['validated_at'] is not None
                        or set(entry['scope']) != {'runtime','data_bindings'}):
                    raise ValueError()
                source = entry['scope']['data_bindings']
                if (not isinstance(source, dict) or set(source) != {
                        'water','knowledge','knowledge_source','knowledge_version','retrieval_backend'}
                        or any(not isinstance(v,str) or not 1 <= len(v) <= 128 for v in source.values())):
                    raise ValueError()
                record = AssistantMultiRoundRelease(entry['release_id'],entry['status'],
                    _json(entry['scope']['runtime']),None,None)
                records.append(ManagementRelease(record,_json(source)))
            return cls(value['multi_round_enabled'],tuple(records))
        except (ValueError,TypeError,KeyError,AttributeError):
            raise GatewayError('INVALID_MANAGEMENT_EXECUTION_CONFIG') from None


def load_execution_config(*, enable_trial=False):
    """Only this package's fixed file. No Web path, Prototype config or auto reload."""
    if type(enable_trial) is not bool:
        raise GatewayError('INVALID_MANAGEMENT_EXECUTION_CONFIG')
    try:
        path = Path(__file__).with_name('resources')/'assistant_execution.json'
        if path.stat().st_size > 65536:
            raise ValueError()
        config = ManagementExecutionConfig.from_dict(json.loads(path.read_text(encoding='utf-8')))
        return replace(config,multi_round_enabled=True) if enable_trial else config
    except (OSError,ValueError,TypeError,RecursionError):
        raise GatewayError('INVALID_MANAGEMENT_EXECUTION_CONFIG') from None


@dataclass(frozen=True)
class ExecutionDecision:
    profile: AssistantExecutionProfile
    can_send: bool
    model_transport: ToolModelTransport = ToolModelTransport.NORMAL
    max_output_tokens: int | None = None

    def public(self):
        multi = self.profile.mode == ToolExecutionMode.BOUNDED_MULTI_ROUND
        return {**self.profile.public(), 'can_send':self.can_send,
                'transport':self.model_transport.value.lower(),'max_output_tokens':self.max_output_tokens,
                'max_tool_calls':2 if multi else 1,'max_tool_rounds':2 if multi else 1}


def resolve_execution(config, profile, selected, policy, registry, knowledge, *, device_id, epoch):
    scope = management_scope(profile,policy,registry,knowledge)
    eligible = tuple(r.runtime for r in config.releases if r.data_bindings_json == _json(scope['data_bindings']))
    execution = resolve_execution_profile(AssistantExecutionConfig(config.multi_round_enabled,eligible),
        profile,policy,registry,epoch=epoch,projection=DEFAULT_HISTORY_PROJECTION)
    # Include the management binding and complete user selection even if some
    # selected tools are unavailable here. A client cannot reuse an old approval.
    revision = hashlib.sha256(_json({'runtime_revision':execution.revision,'config':asdict(config),
        'scope':scope,'selected':asdict(selected),'device_id':device_id,'epoch':epoch,
        'assembled_definitions':[{'name':d.name,'type':d.type,'description':d.description,
            'parameters':d.parameters_dict()} for d in registry.model_definitions()]}).encode()).hexdigest()
    execution = replace(execution,revision=revision)
    return ExecutionDecision(execution, not config.multi_round_enabled or
        execution.mode == ToolExecutionMode.BOUNDED_MULTI_ROUND)
