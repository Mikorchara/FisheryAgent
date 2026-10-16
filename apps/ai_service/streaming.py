"""Management-owned Streaming publication; pure scope resolution, no Tool loop."""
from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path

from fishery_ai.assistant_execution import AssistantExecutionProfile
from fishery_ai.assistant_streaming import (AssistantStreamingConfig, AssistantStreamingRelease,
    resolve_streaming_profile, streaming_scope)
from fishery_ai.history_projection import DEFAULT_HISTORY_PROJECTION
from fishery_ai.model_gateway import GatewayError
from fishery_ai.tool_conversation import ToolExecutionMode, ToolModelTransport
from .execution import ExecutionDecision, _json, data_bindings

STREAMING_PRESET = 'dashscope-qwen38-flash-r1'
STREAMING_TOOLS = ('get_current_water_quality','search_fishery_knowledge')
CONFIG_ERROR = 'INVALID_MANAGEMENT_STREAMING_CONFIG'


@dataclass(frozen=True)
class ManagementStreamingRelease:
    runtime: AssistantStreamingRelease
    data_bindings_json: str

    def __post_init__(self):
        try:
            source=json.loads(self.data_bindings_json)
            scope=json.loads(self.runtime.scope_json)
            if (not isinstance(self.runtime,AssistantStreamingRelease)
                    or self.runtime.status not in ('candidate','local_experimental')
                    or self.runtime.qualification_id is not None or self.runtime.validated_at is not None
                    or scope['preset_id'] != STREAMING_PRESET or scope['tools'] != list(STREAMING_TOOLS)
                    or not isinstance(source,dict) or set(source) != {
                        'water','knowledge','knowledge_source','knowledge_version','retrieval_backend'}
                    or any(not isinstance(v,str) or not 1<=len(v)<=128 for v in source.values())):
                raise ValueError()
            object.__setattr__(self,'data_bindings_json',_json(source))
        except (ValueError,TypeError,KeyError,AttributeError):
            raise GatewayError(CONFIG_ERROR) from None


@dataclass(frozen=True)
class ManagementStreamingConfig:
    enabled: bool = False
    releases: tuple[ManagementStreamingRelease,...] = ()

    def __post_init__(self):
        if (type(self.enabled) is not bool or type(self.releases) is not tuple or len(self.releases)>4
                or any(not isinstance(r,ManagementStreamingRelease) for r in self.releases)
                or len({(r.runtime.scope_json,r.data_bindings_json) for r in self.releases}) != len(self.releases)):
            raise GatewayError(CONFIG_ERROR)

    @classmethod
    def from_dict(cls,value):
        try:
            if (not isinstance(value,dict) or set(value) != {'schema_version','enabled','releases'}
                    or type(value['schema_version']) is not int or value['schema_version'] != 1
                    or not isinstance(value['releases'],list)):
                raise ValueError()
            records=[]
            for entry in value['releases']:
                if (not isinstance(entry,dict) or set(entry) != {
                        'scope','status','qualification_id','validated_at','max_output_tokens'}
                        or not isinstance(entry['scope'],dict) or set(entry['scope']) != {'runtime','data_bindings'}):
                    raise ValueError()
                record=AssistantStreamingRelease(_json(entry['scope']['runtime']),entry['status'],
                    entry['qualification_id'],entry['validated_at'],entry['max_output_tokens'])
                records.append(ManagementStreamingRelease(record,_json(entry['scope']['data_bindings'])))
            return cls(value['enabled'],tuple(records))
        except (ValueError,TypeError,KeyError,AttributeError,RecursionError):
            raise GatewayError(CONFIG_ERROR) from None


def load_streaming_config(*, enable_trial=False):
    """Fixed management scope; CLI opt-in enables only this app epoch, not the file."""
    if type(enable_trial) is not bool:
        raise GatewayError(CONFIG_ERROR)
    try:
        path=Path(__file__).with_name('resources')/'assistant_streaming.json'
        if path.stat().st_size>65536:raise ValueError()
        config = ManagementStreamingConfig.from_dict(json.loads(path.read_text(encoding='utf-8')))
        return replace(config, enabled=True) if enable_trial else config
    except (OSError,ValueError,TypeError,RecursionError):
        raise GatewayError(CONFIG_ERROR) from None


def resolve_streaming(config,profile,selected,policy,registry,knowledge,*,device_id,epoch):
    binding=data_bindings(knowledge)
    eligible=tuple(r.runtime for r in config.releases if r.data_bindings_json==_json(binding))
    decision=resolve_streaming_profile(AssistantStreamingConfig(config.enabled,eligible),
        profile,policy,registry,epoch=epoch,projection=DEFAULT_HISTORY_PROJECTION)
    runtime_ok=(profile.preset_id==STREAMING_PRESET and profile.total_timeout_s==120 and profile.max_retries==0)
    allowed=decision['available'] and runtime_ok
    revision=hashlib.sha256(_json({'runtime_revision':decision['revision'],'config':asdict(config),
        'scope':streaming_scope(profile,policy,registry,DEFAULT_HISTORY_PROJECTION),'data_bindings':binding,
        'selected':asdict(selected),'device_id':device_id,'epoch':epoch,'budget':[2,2,3],
        'assembled_definitions':[{'name':d.name,'type':d.type,'description':d.description,
            'parameters':d.parameters_dict()} for d in registry.model_definitions()]}).encode()).hexdigest()
    execution=AssistantExecutionProfile(ToolExecutionMode.BOUNDED_MULTI_ROUND,revision,
        decision['release_status'],decision['mode_reason'] if runtime_ok else 'runtime_constraints_mismatch')
    return ExecutionDecision(execution,allowed,ToolModelTransport.STREAMING,decision['max_output_tokens'])
