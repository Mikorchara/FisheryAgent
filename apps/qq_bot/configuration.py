"""Fixed QQ credential ref over the existing private Store; no new secret backend."""
import json
from pathlib import Path
import re

from apps.ai_backend.credentials import CredentialStore
from apps.ai_backend.project_env import ProjectEnvWriter
from apps.ai_backend.providers import AuthSpec
from apps.ai_backend import secure_files
from apps.ai_service.runtime.locations import private_project_location
from .contracts import BotConfig, GroupAccess, BotError, _object, _constant

SECRET_REF = 'FISHERY_QQ_APP_SECRET'


def app_identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{5,32}', value):
        raise BotError('INVALID_QQ_APP_ID')
    return value


def json_object(raw, limit=65536):
    try:
        if not isinstance(raw, (str, bytes)):
            raise BotError('INVALID_PACKET')
        body = raw.encode('utf-8') if isinstance(raw, str) else raw
        if not 0 < len(body) <= limit:
            raise BotError('PACKET_SIZE_LIMIT')
        value = json.loads(body.decode('utf-8'), object_pairs_hook=_object, parse_constant=_constant)
        if not isinstance(value, dict):
            raise BotError('INVALID_PACKET')
        return value
    except BotError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise BotError('INVALID_PACKET') from None


def load_access(path):
    try:
        path = Path(path).absolute()
        secure_files.guard_path(path, regular=True)
        with path.open('rb') as stream:
            value = json_object(stream.read(16385), 16384)
        if (set(value) != {'schema_version', 'app_id', 'groups'}
                or type(value['schema_version']) is not int or value['schema_version'] != 1
                or not isinstance(value['groups'], list) or not 1 <= len(value['groups']) <= 16):
            raise BotError('INVALID_ACCESS_CONFIG')
        groups = []
        for item in value['groups']:
            if (not isinstance(item, dict) or set(item) != {'group_id', 'device_id', 'members', 'capabilities'}
                    or not isinstance(item['members'], list) or not isinstance(item['capabilities'], list)):
                raise BotError('INVALID_ACCESS_CONFIG')
            groups.append(GroupAccess(item['group_id'], item['device_id'], tuple(item['members']), tuple(item['capabilities'])))
        return BotConfig(app_identifier(value['app_id']), tuple(groups))
    except BotError:
        raise
    except Exception:
        raise BotError('ACCESS_CONFIG_UNAVAILABLE') from None


def project_credentials(root):
    # Compose only. Reading is deferred until explicit configure/live operation.
    location = private_project_location(Path(root))
    return CredentialStore(location.env_path, private_location=location)


def save_secret(root, secret, *, replace=False, store=None):
    if (not isinstance(secret, str) or not 1 <= len(secret) <= 4096
            or not secret.isascii() or any(not c.isprintable() or c.isspace() for c in secret)):
        raise BotError('INVALID_QQ_SECRET')
    store = store if store is not None else project_credentials(root)
    location = store.private_location
    if location is None:
        raise BotError('PRIVATE_CREDENTIAL_LOCATION_REQUIRED')
    writer = ProjectEnvWriter(location.env_path.parent, store, require_git_ignored=False)
    state = writer.inspect(SECRET_REF, AuthSpec.REQUIRED_BEARER)
    writer.mutate(SECRET_REF, AuthSpec.REQUIRED_BEARER,
        action='replace' if replace else 'create', expected_revision=state['revision'], secret=secret)


def secret_supplier(root):
    store = project_credentials(root)
    return lambda: store.resolve(SECRET_REF)
