"""Independent local AI permission/budget config. Existing access grants are unchanged."""
from dataclasses import asdict,dataclass,field
from pathlib import Path

from apps.ai_backend.secure_files import guard_path
from apps.ai_service.channel import ChannelBudget
from apps.ai_service.business_tools.current_water_quality import CURRENT_WATER_QUALITY
from apps.ai_service.runtime.release_contracts import _hash
from .configuration import json_object
from .contracts import BotError,identifier

PRESET='dashscope-qwen38-flash-r1'


@dataclass(frozen=True)
class QQAIGrant:
    group_id: str = field(repr=False)
    members: tuple[str,...] = field(repr=False)
    device_id: str
    tools: tuple[str,...] = (CURRENT_WATER_QUALITY,)

    def __post_init__(self):
        identifier(self.group_id);identifier(self.device_id)
        if (type(self.members) is not tuple or not 1<=len(self.members)<=64
                or len(set(self.members))!=len(self.members) or self.tools!=(CURRENT_WATER_QUALITY,)):
            raise BotError('INVALID_QQ_AI_CONFIG')
        for member in self.members:identifier(member)


@dataclass(frozen=True)
class QQAIConfig:
    enabled: bool = False
    preset_id: str = PRESET
    budget: ChannelBudget = ChannelBudget()
    grants: tuple[QQAIGrant,...] = field(default=(),repr=False)

    def __post_init__(self):
        if (type(self.enabled) is not bool or self.preset_id!=PRESET
                or type(self.budget) is not ChannelBudget or type(self.grants) is not tuple
                or len(self.grants)>16 or any(type(g) is not QQAIGrant for g in self.grants)
                or len({g.group_id for g in self.grants})!=len(self.grants)):
            raise BotError('INVALID_QQ_AI_CONFIG')

    @property
    def revision(self):
        return _hash(asdict(self))

    @classmethod
    def from_dict(cls,value):
        try:
            if (set(value)!={'schema_version','enabled','preset_id','budget','grants'}
                    or type(value['schema_version']) is not int or value['schema_version']!=1
                    or set(value['budget'])!={'max_output_tokens','turn_timeout_s'}
                    or type(value['grants']) is not list):
                raise ValueError()
            grants=[]
            for record in value['grants']:
                if (set(record)!={'group_id','members','device_id','tools'}
                        or type(record['members']) is not list or type(record['tools']) is not list):
                    raise ValueError()
                grants.append(QQAIGrant(record['group_id'],tuple(record['members']),record['device_id'],tuple(record['tools'])))
            return cls(value['enabled'],value['preset_id'],ChannelBudget(**value['budget']),tuple(grants))
        except Exception:
            raise BotError('INVALID_QQ_AI_CONFIG') from None


def load_ai_config(path):
    try:
        path=Path(path).absolute();guard_path(path,regular=True)
        with path.open('rb') as stream:
            return QQAIConfig.from_dict(json_object(stream.read(16385),16384))
    except Exception:
        raise BotError('INVALID_QQ_AI_CONFIG') from None
