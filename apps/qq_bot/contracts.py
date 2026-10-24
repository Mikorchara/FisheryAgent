"""Small, strict offline representations; not proof of QQ platform identity."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import re

CAPABILITIES = frozenset(('current', 'history', 'knowledge', 'events'))
MAX_PACKET_BYTES = 8192
MAX_QUESTION_BYTES = 2048


class BotError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
        raise BotError('INVALID_IDENTITY')
    return value


def message_identifier(value):
    # Message IDs are opaque platform values (e.g. ROBOT1.0_...), not device IDs.
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:+/=-]{1,512}', value):
        raise BotError('INVALID_MESSAGE_ID')
    return value


def utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise BotError('INVALID_TIME')
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class GroupAccess:
    group_id: str
    device_id: str
    members: tuple[str, ...]
    capabilities: tuple[str, ...]

    def __post_init__(self):
        identifier(self.group_id)
        identifier(self.device_id)
        if not isinstance(self.members, tuple) or not 1 <= len(self.members) <= 64:
            raise BotError('INVALID_ACCESS_CONFIG')
        for member in self.members:
            identifier(member)
        if len(set(self.members)) != len(self.members):
            raise BotError('INVALID_ACCESS_CONFIG')
        if (not isinstance(self.capabilities, tuple)
                or any(not isinstance(c, str) or c not in CAPABILITIES for c in self.capabilities)
                or len(set(self.capabilities)) != len(self.capabilities)):
            raise BotError('INVALID_ACCESS_CONFIG')


@dataclass(frozen=True)
class BotConfig:
    app_id: str
    groups: tuple[GroupAccess, ...]
    dedup_limit: int = 512
    session_limit: int = 128
    member_per_minute: int = 6
    group_per_minute: int = 20

    def __post_init__(self):
        identifier(self.app_id)
        if (not isinstance(self.groups, tuple) or not 1 <= len(self.groups) <= 16
                or any(not isinstance(g, GroupAccess) for g in self.groups)
                or len({g.group_id for g in self.groups}) != len(self.groups)):
            raise BotError('INVALID_ACCESS_CONFIG')
        for value, maximum in ((self.dedup_limit, 4096), (self.session_limit, 1024),
                               (self.member_per_minute, 60), (self.group_per_minute, 60)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise BotError('INVALID_ACCESS_CONFIG')


@dataclass(frozen=True)
class GroupMessage:
    message_id: str
    group_id: str
    member_id: str
    timestamp: datetime
    content: str = field(repr=False)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BotError('INVALID_PACKET')
        result[key] = value
    return result


def _constant(_value):
    raise BotError('INVALID_PACKET')


def decode(raw):
    """Only text GROUP_AT_MESSAGE_CREATE fixtures. No attachments or role input."""
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_PACKET_BYTES:
        raise BotError('INVALID_PACKET')
    try:
        packet = json.loads(raw.decode('utf-8'), object_pairs_hook=_object, parse_constant=_constant)
        if (not isinstance(packet, dict) or type(packet.get('op')) is not int or packet['op'] != 0
                or packet.get('t') != 'GROUP_AT_MESSAGE_CREATE'):
            raise BotError('UNSUPPORTED_EVENT')
        data = packet['d']
        if (not isinstance(data, dict) or set(data) - {
                'id', 'group_openid', 'author', 'timestamp', 'content', 'message_type'}
                or type(data.get('message_type', 0)) is not int or data.get('message_type', 0) != 0):
            raise BotError('INVALID_PACKET')
        author = data['author']
        if not isinstance(author, dict) or type(author.get('bot', False)) is not bool:
            raise BotError('INVALID_PACKET')
        if author.get('bot'):
            raise BotError('BOT_MESSAGE_IGNORED')
        content = data['content']
        if (not isinstance(content, str) or not content.strip()
                or len(content.encode('utf-8')) > MAX_QUESTION_BYTES
                or any(ord(c) < 32 and c not in '\n\t' or ord(c) == 127 for c in content)):
            raise BotError('INVALID_CONTENT')
        if not isinstance(data['timestamp'], str) or len(data['timestamp']) > 64:
            raise BotError('INVALID_TIME')
        timestamp = utc(datetime.fromisoformat(data['timestamp'].replace('Z', '+00:00')))
        return GroupMessage(message_identifier(data['id']), identifier(data['group_openid']),
                            identifier(author['member_openid']), timestamp, content.strip())
    except BotError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
        raise BotError('INVALID_PACKET') from None
