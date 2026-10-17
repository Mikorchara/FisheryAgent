"""Management-only authorization; read-only inheritance until an explicit CAS save."""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import threading
import uuid

from apps.ai_backend.tools.policy import ToolPolicy, ToolPolicyError
from .business_tools.registry import KNOWN_TOOL_NAMES
from .business_tools.water_quality_history import WATER_QUALITY_HISTORY

MANAGEMENT_TOOL_NAMES = (*KNOWN_TOOL_NAMES, WATER_QUALITY_HISTORY)


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError()
        value[key] = item
    return value


def _check_path(path):
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if item.is_symlink() or getattr(info, 'st_file_attributes', 0) & 1024:
            raise ToolPolicyError('TOOL_POLICY_STORAGE_ERROR')
        if item == path and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise ToolPolicyError('TOOL_POLICY_STORAGE_ERROR')


@contextmanager
def _writer_lock(path):
    """OS lock covers load/CAS/replace across processes; never acquired on reads."""
    _check_path(path)
    stream = path.open('a+b')
    locked = False
    try:
        if os.name == 'nt':
            import msvcrt
            if stream.seek(0, 2) == 0:
                stream.write(b'0'); stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise ToolPolicyError('TOOL_POLICY_BUSY') from None
        else:
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise ToolPolicyError('TOOL_POLICY_BUSY') from None
        locked = True
        yield
    finally:
        if locked:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)
        stream.close()


@dataclass(frozen=True)
class ManagementPolicySnapshot:
    selected_tools: tuple[str, ...]
    source: str
    generation: int

    @property
    def revision(self):
        value = [self.source, self.generation, self.selected_tools]
        return hashlib.sha256(json.dumps(value, separators=(',', ':')).encode()).hexdigest()


class ManagementToolPolicyStore:
    """No startup migration/write and no reset endpoint or shared-file mutation."""

    def __init__(self, directory, inherited):
        self.directory = Path(directory).absolute()
        self.path = self.directory / 'management_assistant_policy.json'
        self.inherited = inherited
        self._lock = threading.RLock()
        self.snapshot()  # Invalid overrides fail closed, including on restart.

    @staticmethod
    def _names(names):
        selected = ToolPolicy('assistant', True, names).exposed_tools
        if any(name not in MANAGEMENT_TOOL_NAMES for name in selected):
            raise ToolPolicyError('UNKNOWN_POLICY_TOOL')
        return selected

    def snapshot(self):
        with self._lock:
            try:
                _check_path(self.path)
                try:
                    with self.path.open('rb') as stream:
                        raw = stream.read(8193)
                except FileNotFoundError:
                    names = self.inherited.load()['modes']['assistant']['selected_tools']
                    return ManagementPolicySnapshot(tuple(names), 'INHERITED_SHARED_POLICY', 0)
                if len(raw) > 8192:
                    raise ValueError()
                value = json.loads(raw, object_pairs_hook=_unique_object)
                if (not isinstance(value, dict) or set(value) != {'schema_version','generation','selected_tools'}
                        or type(value['schema_version']) is not int or value['schema_version'] != 1
                        or type(value['generation']) is not int or not 1 <= value['generation'] <= 2**53-1):
                    raise ValueError()
                return ManagementPolicySnapshot(self._names(value['selected_tools']),
                                                'MANAGEMENT_OVERRIDE', value['generation'])
            except ToolPolicyError:
                raise
            except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
                raise ToolPolicyError('TOOL_POLICY_STORAGE_ERROR') from None

    def public(self):
        snapshot = self.snapshot()
        return {'selected_tools': list(snapshot.selected_tools), 'source': snapshot.source,
                'revision': snapshot.revision, 'generation': snapshot.generation}

    def save(self, names, *, expected_revision):
        names = self._names(names)
        if not isinstance(expected_revision, str) or len(expected_revision) != 64:
            raise ToolPolicyError('TOOL_POLICY_REVISION_MISMATCH')
        with self._lock:
            temporary = self.directory / ('.management-policy-' + uuid.uuid4().hex + '.tmp')
            created = False
            try:
                _check_path(self.path)
                self.directory.mkdir(parents=True, exist_ok=True)
                _check_path(self.path)
                with _writer_lock(self.directory / '.management-policy.lock'):
                    current = self.snapshot()
                    if current.revision != expected_revision:
                        raise ToolPolicyError('TOOL_POLICY_REVISION_MISMATCH')
                    if current.generation >= 2**53-1:
                        raise ToolPolicyError('TOOL_POLICY_STORAGE_ERROR')
                    value = {'schema_version':1, 'generation':current.generation+1,
                             'selected_tools':list(names)}
                    with temporary.open('x', encoding='utf-8', newline='\n') as stream:
                        created = True
                        json.dump(value, stream, ensure_ascii=False, allow_nan=False)
                        stream.flush(); os.fsync(stream.fileno())
                    os.replace(temporary, self.path)
                    return self.public()
            except ToolPolicyError:
                raise
            except (OSError, ValueError):
                raise ToolPolicyError('TOOL_POLICY_STORAGE_ERROR') from None
            finally:
                if created:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass
