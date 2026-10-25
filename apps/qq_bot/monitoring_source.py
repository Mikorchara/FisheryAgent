"""Explicit local Monitoring composition. Never discovers, initializes or migrates data."""
from dataclasses import dataclass
import os
import hashlib
import json
from functools import partial
from pathlib import Path
import sqlite3

from apps.ai_backend.secure_files import guard_path
from apps.management_paths import ManagementPaths
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.monitoring.service import DeviceReadContext
from apps.monitoring.contracts import METRICS
from .configuration import json_object
from .contracts import BotError, identifier


@dataclass(frozen=True)
class MonitoringSourceConfig:
    instance_id: str
    data_root: Path
    devices: tuple[str, ...]

    def check_bindings(self, access):
        if any(group.device_id not in self.devices for group in access.groups):
            raise BotError('MONITORING_DEVICE_NOT_APPROVED')


def load_monitoring_config(path):
    """Validate configuration only; do not stat/open the specified instance."""
    try:
        path = Path(path).absolute()
        guard_path(path, regular=True)
        with path.open('rb') as stream:
            value = json_object(stream.read(16385), 16384)
        if (set(value) != {'schema_version','instance_id','data_root','devices'}
                or type(value['schema_version']) is not int or value['schema_version'] != 1
                or not isinstance(value['devices'], list) or not 1 <= len(value['devices']) <= 16
                or not isinstance(value['data_root'], str)):
            raise ValueError()
        instance_id = identifier(value['instance_id'])
        devices = tuple(identifier(d) for d in value['devices'])
        root = Path(value['data_root'])
        if (len(set(devices)) != len(devices) or not root.is_absolute()
                or root.anchor.startswith(('\\\\','//')) or '..' in root.parts
                or any(ord(c)<32 for c in str(root)) or '~' == str(root)):
            raise ValueError()
        paths = ManagementPaths.resolve(Path(__file__).parents[2], data_root=root)
        return MonitoringSourceConfig(instance_id, paths.data_root, devices)
    except Exception:
        raise BotError('INVALID_MONITORING_CONFIG') from None


def _safe_database(path):
    if os.name == 'nt':
        import ctypes
        # A mapped network drive is not a trusted local SQLite instance.
        if ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor)) != 3:
            raise BotError('MONITORING_LOCAL_DISK_REQUIRED')
    try:
        guard_path(path, regular=True)
        if not path.is_file() or path.stat().st_size == 0:
            raise BotError('MONITORING_DATABASE_MISSING')
        for suffix in ('-wal','-shm','-journal'):
            guard_path(Path(str(path)+suffix), regular=True)
        info = path.stat()
        return info.st_dev, info.st_ino
    except BotError:
        raise
    except Exception:
        raise BotError('MONITORING_PATH_REJECTED') from None


class InstanceMonitoring:
    """Only read methods are exposed. Frozen instance and device allowlist per run."""
    def __init__(self, config, *, clock=None):
        self.config = config
        self.path = ManagementPaths.resolve(Path(__file__).parents[2], data_root=config.data_root).monitoring
        self.identity = _safe_database(self.path)
        try:
            repository = MonitoringRepository(self.path, read_only=True)
            with repository.connection() as db:
                if [r[0] for r in db.execute('PRAGMA integrity_check')] != ['ok']:
                    raise BotError('MONITORING_INTEGRITY_FAILED')
            options = {'clock':clock} if clock else {}
            self._service = MonitoringService(repository, device_names={d:d for d in config.devices}, **options)
        except BotError:
            raise
        except ValueError as error:
            if str(error) == 'MONITORING_SCHEMA_UPGRADE_REQUIRED':
                raise BotError('MONITORING_SCHEMA_UPGRADE_REQUIRED') from None
            raise BotError('MONITORING_SCHEMA_INVALID') from None
        except sqlite3.Error:
            raise BotError('MONITORING_DATABASE_UNAVAILABLE') from None

    def _read(self, method, device_id, **kwargs):
        if device_id not in self.config.devices:
            raise BotError('MONITORING_DEVICE_NOT_APPROVED')
        if _safe_database(self.path) != self.identity:
            raise BotError('MONITORING_DATABASE_REPLACED')
        try:
            return method(device_id, **kwargs)
        except Exception as error:
            code = getattr(error, 'code', None) or str(error)
            allowed = {'EVENT_QUERY_LIMIT','HISTORY_QUERY_BUDGET_EXCEEDED',
                       'HISTORY_STORAGE_ERROR','HISTORY_RESULT_TOO_LARGE',
                       'HISTORY_RECORD_TOO_LARGE','HISTORY_RECORD_INVALID'}
            raise BotError(code if code in allowed else 'MONITORING_READ_FAILED') from None

    def capture_water(self, device_id):
        return self._read(self._service.capture_water, device_id)

    def devices(self):
        return [d for d in self._service.devices() if d['id'] in self.config.devices]

    @property
    def binding_revision(self):
        if _safe_database(self.path) != self.identity:
            raise BotError('MONITORING_DATABASE_REPLACED')
        value = [self.config.instance_id,str(self.path),self.config.devices,self.identity]
        return hashlib.sha256(json.dumps(value).encode()).hexdigest()

    def bind(self, device_id):
        bound = self._read(self._service.bind, device_id)
        source = self
        class GuardedReader:
            def query(self):
                return source._read(lambda device: bound.water_reader.query(), device_id)
        return DeviceReadContext(device_id, GuardedReader(),
            lambda channel='water': source._read(source._service.analysis,device_id,channel=channel),
            partial(source.capture_water,device_id))

    def query_water_history(self, device_id, *, lookback_minutes, metrics=tuple(METRICS)):
        return self._read(self._service.query_water_history, device_id,
                          lookback_minutes=lookback_minutes, metrics=metrics)

    def event_cycles(self, *, device_id):
        return self._read(lambda device: self._service.event_cycles(device_id=device), device_id)
