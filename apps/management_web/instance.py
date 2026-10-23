"""Explicit empty-instance creation and read-only startup validation; no migration."""
from contextlib import closing
import os
import json
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile

from apps.management_paths import ManagementPaths
from apps.monitoring.schema import BASE_COLUMNS, HANDLING_COLUMNS, SCHEMA_VERSION, validate_schema


class InstanceError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def safe_path(path):
    """Business data may not traverse symlinks/Windows junctions or linked files."""
    path = Path(path)
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            raise InstanceError('INSTANCE_STORAGE_ERROR') from None
        if (stat.S_ISLNK(info.st_mode) or
                getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024) or
                stat.S_ISREG(info.st_mode) and info.st_nlink != 1):
            raise InstanceError('INSTANCE_UNSAFE_PATH')


# Validate the columns actually required by each existing Repository, without
# changing its schema or reading business records into application output.
MONITORING_COLUMNS = BASE_COLUMNS | HANDLING_COLUMNS
KNOWLEDGE_COLUMNS = {
    'knowledge_records': ('id title category body version status updated_at origin original_source_id '
        'original_source_version source_id source_version evidence_id chunk_type keywords_json text_style ordinal'),
    'knowledge_revision': 'id revision', 'knowledge_metadata': 'key value',
}


def check_database(path, kind):
    safe_path(path)
    try:
        if not path.exists():
            raise InstanceError(kind+'_DATABASE_MISSING')
        if not path.is_file():
            raise InstanceError(kind+'_DATABASE_STORAGE_ERROR')
        if path.stat().st_size == 0:
            raise InstanceError(kind+'_DATABASE_CORRUPT')
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=2)) as db:
            if db.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                raise InstanceError(kind+'_DATABASE_CORRUPT')
            expected = SCHEMA_VERSION if kind == 'MONITORING' else 2
            if kind == 'MONITORING' and db.execute('PRAGMA user_version').fetchone()[0] == 1:
                raise InstanceError('MONITORING_DATABASE_UPGRADE_REQUIRED')
            if db.execute('PRAGMA user_version').fetchone()[0] != expected:
                raise InstanceError(kind+'_DATABASE_SCHEMA_INCOMPATIBLE')
            columns = MONITORING_COLUMNS if kind == 'MONITORING' else KNOWLEDGE_COLUMNS
            for table, required in columns.items():
                actual = {row[1] for row in db.execute('PRAGMA table_info('+table+')')}
                if not set(required.split()) <= actual:
                    raise InstanceError(kind+'_DATABASE_SCHEMA_INCOMPATIBLE')
            if kind == 'KNOWLEDGE':
                marker = db.execute("SELECT value FROM knowledge_metadata WHERE key='migration_version'").fetchone()
                revision = db.execute('SELECT revision FROM knowledge_revision WHERE id=1').fetchone()
                diseases = db.execute("SELECT value FROM knowledge_metadata WHERE key='disease_names'").fetchone()
                if marker != ('unified-knowledge@2',) or revision is None or diseases is None:
                    raise InstanceError(kind+'_DATABASE_SCHEMA_INCOMPATIBLE')
                try:
                    if type(revision[0]) is not int or revision[0] < 0 or not isinstance(json.loads(diseases[0]),list):
                        raise ValueError()
                except (TypeError,ValueError):
                    raise InstanceError(kind+'_DATABASE_CORRUPT') from None
            else:
                try:
                    validate_schema(db)
                except ValueError:
                    raise InstanceError('MONITORING_DATABASE_SCHEMA_INCOMPATIBLE') from None
    except sqlite3.Error as error:
        corrupt = getattr(error, 'sqlite_errorcode', None) in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB)
        raise InstanceError(kind+('_DATABASE_CORRUPT' if corrupt else '_DATABASE_STORAGE_ERROR')) from None
    except OSError:
        raise InstanceError(kind+'_DATABASE_STORAGE_ERROR') from None


def validate_instance(paths):
    """Both databases must pass before any writable Repository is constructed."""
    if paths.data_root is None:
        raise InstanceError('EXPLICIT_DATA_ROOT_REQUIRED')
    safe_path(paths.data_root)
    check_database(paths.monitoring, 'MONITORING')
    check_database(paths.knowledge, 'KNOWLEDGE')


def initialize_instance(paths):
    """Publish a complete, empty instance. Never seed from another workspace."""
    root = paths.data_root
    if root is None:
        raise InstanceError('EXPLICIT_DATA_ROOT_REQUIRED')
    safe_path(root)
    if root.exists():
        raise InstanceError('INSTANCE_ALREADY_EXISTS')
    if not root.parent.is_dir():
        raise InstanceError('DATA_ROOT_PARENT_MISSING')
    from apps.knowledge.repository import KnowledgeRepository, KnowledgeError
    stage = None
    try:
        # Parent-local staging allows atomic publication on the same filesystem.
        stage = Path(tempfile.mkdtemp(prefix='.management-init-', dir=root.parent))
        candidate = ManagementPaths.resolve(root.parent, data_root=stage)
        from apps.monitoring.repository import MonitoringRepository
        MonitoringRepository(candidate.monitoring)
        repository = KnowledgeRepository(candidate.knowledge)
        with repository.connection(write=True) as db:
            db.execute('INSERT INTO knowledge_metadata VALUES (?,?)', ('migration_version','unified-knowledge@2'))
            db.execute('INSERT INTO knowledge_metadata VALUES (?,?)', ('initialization_version','management-instance@1'))
        candidate.policy_directory.mkdir()
        candidate.traces.parent.mkdir()
        validate_instance(candidate)
        safe_path(root)
        if root.exists():
            raise InstanceError('INSTANCE_ALREADY_EXISTS')
        # Windows rename refuses an existing target, including an empty directory.
        os.rename(stage, root)
        stage = None
    except (OSError, sqlite3.Error):
        raise InstanceError('INSTANCE_STORAGE_ERROR') from None
    except KnowledgeError as error:
        raise InstanceError(error.code) from None
    finally:
        if stage is not None:
            # Only remove the private staging directory created by this invocation.
            if stage.parent != root.parent or not stage.name.startswith('.management-init-'):
                raise InstanceError('INSTANCE_UNSAFE_PATH')
            safe_path(stage)
            try:
                shutil.rmtree(stage)
            except OSError:
                raise InstanceError('INSTANCE_CLEANUP_FAILED') from None
