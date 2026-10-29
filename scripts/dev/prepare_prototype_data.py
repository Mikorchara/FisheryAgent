"""Explicit, non-overwriting copy of legacy daily data into Prototype apps/data.

No schema migration, credentials, model calls or implicit runtime fallback.
Original files remain intact. Reports contain counts and digests, never records.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
CONTRACT = 'prototype-daily-data@1'


def legacy_paths(root):
    from apps.management_paths import ManagementPaths
    return ManagementPaths(root/'outputs/management_web/monitoring.sqlite3',
        root/'apps/knowledge_data/knowledge.sqlite3', root/'outputs/management_web/settings.json',
        root/'outputs/tool-policies', root/'outputs/management_web/assistant-traces.jsonl')


def digest(path):
    from apps.management_web.instance import safe_path
    safe_path(path)
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def database_summary(path, kind):
    from apps.management_web.instance import check_database
    check_database(path, kind)
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=2)) as db:
        db.execute('PRAGMA query_only=ON')
        names = sorted(row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
        counts = {name:db.execute('SELECT count(*) FROM "'+name.replace('"','""')+'"').fetchone()[0]
                  for name in names}
        logical = hashlib.sha256()
        for line in db.iterdump(): logical.update(line.encode('utf8')+b'\n')
        schema = hashlib.sha256(json.dumps(list(db.execute(
            'SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name'))).encode()).hexdigest()
        foreign_keys = list(db.execute('PRAGMA foreign_key_check'))
        if foreign_keys: raise RuntimeError('DAILY_DATA_FOREIGN_KEY_ERROR')
        return dict(version=db.execute('PRAGMA user_version').fetchone()[0], counts=counts,
                    logical_sha256=logical.hexdigest(), schema_sha256=schema,
                    foreign_key_errors=0)


def prepare_daily_data(root=ROOT):
    from apps.management_paths import ManagementPaths
    from apps.management_web.instance import safe_path, initialize_instance, validate_instance
    root = Path(root).resolve()
    target = root/'apps/data'
    safe_path(target)
    if target.exists(): raise RuntimeError('DAILY_DATA_TARGET_EXISTS')
    original = legacy_paths(root)
    legacy = [original.monitoring, original.knowledge, original.settings, original.policy_directory]
    if not any(p.exists() for p in legacy):
        initialize_instance(ManagementPaths.resolve(root))
        (target/'launcher-instance.json').write_text(json.dumps(dict(contract=CONTRACT,root=str(target))),encoding='utf8')
        return dict(code='PROTOTYPE_DAILY_CREATED_EMPTY', data_root=str(target))
    if not original.monitoring.is_file() or not original.knowledge.is_file():
        raise RuntimeError('DAILY_DATA_LEGACY_INCOMPLETE')
    summaries = {kind:database_summary(path, kind) for kind,path in (
        ('MONITORING',original.monitoring), ('KNOWLEDGE',original.knowledge))}
    files = [(original.settings,'settings.json')] if original.settings.exists() else []
    # Known non-secret authorization documents only; never copy locks or private stores.
    files += [(original.policy_directory/name,'tool-policies/'+name)
              for name in ('tool_policies.json','management_assistant_policy.json')
              if (original.policy_directory/name).exists()]
    before = {str(path):digest(path) for path in (original.monitoring,original.knowledge,
                                                 *(item[0] for item in files))}
    stage = Path(tempfile.mkdtemp(prefix='.prototype-data-',dir=target.parent))
    try:
        candidate = ManagementPaths.resolve(root,data_root=stage)
        for source,destination in ((original.monitoring,candidate.monitoring),(original.knowledge,candidate.knowledge)):
            with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,timeout=2)) as src, \
                 closing(sqlite3.connect(destination)) as dst:
                src.backup(dst)
        candidate.policy_directory.mkdir(); candidate.traces.parent.mkdir()
        for source,name in files: shutil.copyfile(source,stage/name)
        validate_instance(candidate)
        after = {kind:database_summary(path,kind) for kind,path in (
            ('MONITORING',candidate.monitoring),('KNOWLEDGE',candidate.knowledge))}
        if after != summaries or any(digest(Path(path)) != value for path,value in before.items()):
            raise RuntimeError('DAILY_DATA_SOURCE_CHANGED_OR_COPY_MISMATCH')
        if any(digest(stage/name) != before[str(source)] for source,name in files):
            raise RuntimeError('DAILY_DATA_CONFIG_COPY_MISMATCH')
        report = dict(code='PROTOTYPE_DAILY_DATA_COPIED',contract=CONTRACT,data_root=str(target),
            at=datetime.now(timezone.utc).isoformat(),databases=after,source_file_digests=before,
            original_files_preserved=True,old_logs_preserved_in_original_location=True,
            schema_changed=False,credentials_copied=False)
        (stage/'data-preparation.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        (stage/'launcher-instance.json').write_text(json.dumps(dict(contract=CONTRACT,root=str(target))),encoding='utf8')
        safe_path(target)
        if target.exists(): raise RuntimeError('DAILY_DATA_TARGET_EXISTS')
        os.rename(stage,target)
        return report
    except Exception:
        # Preserve the unpublished stage for inspection; never remove user sources or restore over them.
        raise RuntimeError('DAILY_DATA_COPY_FAILED_STAGE_PRESERVED') from None


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--copy-legacy',action='store_true',required=True,
                        help='Explicitly prepare new apps/data; all sources must be stopped first')
    parser.parse_args()
    try:
        print(json.dumps(prepare_daily_data(),ensure_ascii=False))
    except Exception as error:
        code = str(error) if isinstance(error,RuntimeError) else getattr(error,'code','DAILY_DATA_PREPARATION_FAILED')
        print(json.dumps(dict(code=code))); raise SystemExit(1)
