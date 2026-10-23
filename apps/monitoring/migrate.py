"""Explicit Monitoring-only maintenance. No migration is run by normal startup.

python -I -B apps/monitoring/migrate.py --database ABSOLUTE_PATH --dry-run
python -I -B apps/monitoring/migrate.py --database ABSOLUTE_PATH --apply --backup NEW_ABSOLUTE_PATH --writers-stopped
"""

import argparse
from contextlib import closing
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from apps.monitoring.schema import SCHEMA_VERSION, BASE_COLUMNS, add_handling_tables, validate_schema


def safe_path(value):
    path = Path(value)
    if not path.is_absolute() or str(path).startswith('\\\\'):
        raise ValueError('LOCAL_ABSOLUTE_DATABASE_PATH_REQUIRED')
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0) & 1024
                or stat.S_ISREG(info.st_mode) and info.st_nlink != 1):
            raise ValueError('UNSAFE_MIGRATION_PATH')
    if os.name == 'nt' and ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor)) != 3:
        raise ValueError('TRUSTED_LOCAL_FILESYSTEM_REQUIRED')
    return path


def business_tables(db):
    result = {}
    for name in BASE_COLUMNS:
        digest = hashlib.sha256()
        count = 0
        for row in db.execute('SELECT * FROM '+name+' ORDER BY rowid'):
            digest.update(json.dumps(tuple(row),ensure_ascii=True,separators=(',',':')).encode()+b'\n')
            count += 1
        definition = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone()[0]
        result[name] = dict(count=count,sha256=digest.hexdigest(),schema_sha256=hashlib.sha256(definition.encode()).hexdigest())
    return result


def inspect_connection(db):
    if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
        raise ValueError('MONITORING_DATABASE_CORRUPT')
    version = db.execute('PRAGMA user_version').fetchone()[0]
    validate_schema(db,version)
    return dict(status='UPGRADE_READY' if version == 1 else 'CURRENT',schema_version=version,
                business_tables=business_tables(db))


def inspect_database(value):
    path = safe_path(value)
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
        db.execute('BEGIN')
        return inspect_connection(db)


def upgrade_database(value, backup, *, writers_stopped=False):
    if not writers_stopped:
        raise ValueError('WRITERS_STOP_CONFIRMATION_REQUIRED')
    path, backup = safe_path(value), safe_path(backup)
    if path == backup:
        raise ValueError('BACKUP_MUST_BE_SEPARATE')
    with closing(sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=2)) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        try:
            before = inspect_connection(db)
            if before['schema_version'] == SCHEMA_VERSION:
                db.rollback()
                return dict(status='ALREADY_CURRENT',schema_version=SCHEMA_VERSION)
            # Exclusive creation: never replace a previous migration baseline.
            try:
                descriptor = os.open(backup,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            except FileExistsError:
                raise ValueError('BACKUP_ALREADY_EXISTS') from None
            os.close(descriptor)
            # The writer reservation freezes writes. A separate read connection can
            # back up the committed v1 snapshot without backing up an active writer.
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)) as reader, \
                    closing(sqlite3.connect(backup.as_uri()+'?mode=rw',uri=True)) as destination:
                reader.backup(destination)
            if inspect_database(backup) != before:
                raise ValueError('BACKUP_LOGICAL_MISMATCH')
            add_handling_tables(db)
            db.execute('PRAGMA user_version='+str(SCHEMA_VERSION))
            after = inspect_connection(db)
            if before['business_tables'] != after['business_tables']:
                raise ValueError('MIGRATION_LOGICAL_MISMATCH')
            db.commit()
        except BaseException:
            db.rollback()
            raise
    verified = inspect_database(path)
    if verified['business_tables'] != before['business_tables']:
        raise ValueError('POST_MIGRATION_LOGICAL_MISMATCH')
    return dict(status='UPGRADED_AND_VERIFIED',schema_version=SCHEMA_VERSION,backup=str(backup),
                business_tables=verified['business_tables'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--dry-run',action='store_true')
    modes.add_argument('--apply',action='store_true')
    parser.add_argument('--backup')
    parser.add_argument('--writers-stopped',action='store_true')
    args = parser.parse_args(argv)
    if args.apply and not args.backup:
        parser.error('--apply requires a separate new --backup path')
    try:
        result = (upgrade_database(args.database,args.backup,writers_stopped=args.writers_stopped)
                  if args.apply else inspect_database(args.database))
        print(json.dumps(result,ensure_ascii=True,sort_keys=True))
        return 0
    except (ValueError,OSError,sqlite3.Error) as error:
        code = str(error) if isinstance(error,ValueError) else 'MIGRATION_STORAGE_ERROR'
        print(json.dumps(dict(status='STOPPED',code=code,action='KEEP_BACKUP_NO_AUTOMATIC_RESTORE')))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
