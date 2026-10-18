"""Explicit, non-overwriting migration. Product reads only the resulting SQLite."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid

from .legacy_import import chunk_knowledge
from .repository import (KnowledgeError, KnowledgeRepository, identifier,
                         MAX_USER_RECORDS, MAX_IMPORTED_RECORDS, MAX_TOTAL_BODY_CHARS)
from .service import content, version, CATEGORIES
from .retrieval import KnowledgeService


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def read_legacy(path):
    """Only migration/isolated qualification fixtures may read the old JSON."""
    try:
        path=Path(path)
        if path.stat().st_size>1024*1024: raise ValueError()
        raw=path.read_bytes();kg=json.loads(raw.decode('utf-8'))
        chunks=chunk_knowledge(kg)
        names=[item['name'] for item in kg['diseases']]
        if len(chunks)>MAX_IMPORTED_RECORDS or len(names)>100: raise ValueError()
        return kg,chunks,names,hashlib.sha256(raw).hexdigest()
    except (OSError,ValueError,TypeError,KeyError,IndexError,UnicodeError):
        raise KnowledgeError('KNOWLEDGE_MIGRATION_SOURCE_INVALID') from None


def legacy_reference(path):
    """Explicit legacy fixture for frozen historical qualification plans, not Web."""
    kg,chunks,names,_=read_legacy(path)
    return KnowledgeService(chunks,disease_names=names,source_version=str(kg.get('version','unknown')))


def _source_rows(source):
    if source is None: return 0,[],{}
    source=Path(source)
    if not source.is_file(): raise KnowledgeError('KNOWLEDGE_MIGRATION_SOURCE_MISSING')
    try:
        with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row;db.execute('BEGIN')
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError()
            if db.execute('PRAGMA user_version').fetchone()[0]!=0: raise ValueError()
            rows=[dict(r) for r in db.execute('SELECT * FROM knowledge_records ORDER BY id LIMIT ?', (MAX_USER_RECORDS+1,))]
            states={r['id']:dict(r) for r in db.execute('SELECT * FROM builtin_state LIMIT ?', (MAX_IMPORTED_RECORDS+1,))}
            revision=db.execute('SELECT revision FROM knowledge_revision WHERE id=1').fetchone()[0]
        if type(revision) is not int or revision<0 or len(rows)>MAX_USER_RECORDS or len(states)>MAX_IMPORTED_RECORDS: raise ValueError()
        return revision,rows,states
    except (sqlite3.Error,ValueError,TypeError):
        raise KnowledgeError('KNOWLEDGE_MIGRATION_SOURCE_INVALID') from None


def prepare(source, legacy_json):
    """Read-only, bounded source snapshot; report never contains text/paths."""
    kg,chunks,names,resource_hash=read_legacy(legacy_json)
    revision,users,states=_source_rows(source)
    rows=[]
    for ordinal,chunk in enumerate(chunks):
        key='builtin-'+hashlib.sha256(chunk['id'].encode()).hexdigest()[:24]
        state=states.pop(key,{'version':1,'status':'ACTIVE','updated_at':None})
        rows.append(dict(id=key,title=chunk['text'].split('。')[0][:120],category=CATEGORIES.get(chunk['type'],'养殖知识'),
            body=chunk['text'],version=state['version'],status=state['status'],updated_at=state['updated_at'],origin='builtin',
            original_source_id='legacy:eel_knowledge.json',original_source_version=str(kg.get('version','unknown')),
            source_id='legacy:eel_knowledge.json',source_version=str(kg.get('version','unknown')),
            evidence_id=chunk['id'],chunk_type=chunk['type'],keywords=chunk.get('keywords',[]),text_style='body',ordinal=ordinal))
    if states: raise KnowledgeError('KNOWLEDGE_MIGRATION_SOURCE_INVALID')
    for item in users:
        key=identifier(item['id'])
        if not key.startswith('user-'): raise KnowledgeError('KNOWLEDGE_MIGRATION_SOURCE_INVALID')
        rows.append(dict(**item,origin='user',original_source_id='management:knowledge/'+key,
            original_source_version='1',source_id='management:knowledge/'+key,source_version=str(item['version']),
            evidence_id=key,chunk_type=item['category'],keywords=[item['title']],text_style='titled',ordinal=len(rows)))
    for row in rows:
        content({k:row[k] for k in ('title','category','body')});version(row['version'])
        if row['status'] not in ('ACTIVE','DISABLED','DELETED'): raise KnowledgeError('KNOWLEDGE_MIGRATION_SOURCE_INVALID')
        if row['updated_at'] is not None:
            try:
                when=datetime.fromisoformat(row['updated_at'])
                if when.tzinfo is None or when.utcoffset() is None: raise ValueError()
            except (ValueError,TypeError):raise KnowledgeError('KNOWLEDGE_MIGRATION_SOURCE_INVALID') from None
    if len({r['id'] for r in rows})!=len(rows) or sum(len(r['body']) for r in rows)>MAX_TOTAL_BODY_CHARS:
        raise KnowledgeError('KNOWLEDGE_LIMIT')
    # Legacy builtins had no update time; keep that fact rather than invent one.
    payload={'rows':rows,'disease_names':names,'source_revision':revision,'legacy_json_sha256':resource_hash}
    plan={'migration_version':'unified-knowledge@2','builtin_count':len(chunks),'user_count':len(users),
          'total_count':len(rows),'statuses':{s:sum(r['status']==s for r in rows) for s in ('ACTIVE','DISABLED','DELETED')},
          'content_sha256':digest(payload),'source_database_present':source is not None}
    plan['plan_sha256']=digest(plan)
    return plan,payload


def _backup_database(source, destination):
    # SQLite backup includes committed WAL content; byte-copying the main DB does not.
    source_db=target_db=None
    try:
        source_db=sqlite3.connect(Path(source).resolve().as_uri()+'?mode=ro',uri=True)
        target_db=sqlite3.connect(destination)
        source_db.backup(target_db)
    finally:
        if target_db:target_db.close()
        if source_db:source_db.close()


def backup(source, destination):
    """SQLite online backup to a new file, with integrity check and no overwrite."""
    source,destination=Path(source),Path(destination)
    if not source.is_file():raise KnowledgeError('KNOWLEDGE_MIGRATION_SOURCE_MISSING')
    if destination.exists() or source.resolve()==destination.resolve():
        raise KnowledgeError('KNOWLEDGE_BACKUP_TARGET_EXISTS')
    stage=None
    try:
        destination.parent.mkdir(parents=True,exist_ok=True)
        stage=destination.parent/('.backup-'+uuid.uuid4().hex+'.sqlite3')
        _backup_database(source,stage)
        with closing(sqlite3.connect(stage.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                raise KnowledgeError('KNOWLEDGE_MIGRATION_VERIFY_FAILED')
        os.link(stage,destination)
        return {'status':'BACKED_UP','integrity':'ok'}
    except (OSError,sqlite3.Error):
        raise KnowledgeError('KNOWLEDGE_MIGRATION_STORAGE_ERROR') from None
    finally:
        if stage is not None and stage.is_file():stage.unlink()


def migrate(source, target, legacy_json, *, apply=False, approved_plan_sha256=None):
    target=Path(target);legacy_json=Path(legacy_json)
    if source is not None and Path(source).resolve()==target.resolve():
        raise KnowledgeError('KNOWLEDGE_MIGRATION_SAME_PATH')
    plan,payload=prepare(source,legacy_json)
    if target.exists():
        # No constructor: even an invalid existing target must remain byte-for-byte intact.
        try:
            with closing(sqlite3.connect(target.resolve().as_uri()+'?mode=ro',uri=True)) as db:
                valid=db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
                marker=db.execute("SELECT value FROM knowledge_metadata WHERE key='migration_content_sha256'").fetchone()
            if valid and marker and marker[0]==plan['content_sha256']:
                return {**plan,'status':'ALREADY_MIGRATED','applied':False}
        except sqlite3.Error:pass
        raise KnowledgeError('KNOWLEDGE_MIGRATION_TARGET_EXISTS')
    if not apply:return {**plan,'status':'DRY_RUN','applied':False}
    if approved_plan_sha256!=plan['plan_sha256']:
        raise KnowledgeError('KNOWLEDGE_MIGRATION_PLAN_CHANGED')
    stage=None
    try:
        target.parent.mkdir(parents=True,exist_ok=True)
        operation=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:12]
        backup=target.parent/'backups'/operation;backup.mkdir(parents=True)
        if source is not None:
            _backup_database(source,backup/'previous-knowledge.sqlite3')
            if prepare(backup/'previous-knowledge.sqlite3',legacy_json)[0]!=plan:
                raise KnowledgeError('KNOWLEDGE_MIGRATION_PLAN_CHANGED')
        raw=legacy_json.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=payload['legacy_json_sha256']:
            raise KnowledgeError('KNOWLEDGE_MIGRATION_PLAN_CHANGED')
        with (backup/'eel_knowledge.json').open('xb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        stage=target.parent/('.migration-'+operation+'.sqlite3')
        repository=KnowledgeRepository(stage)
        with repository.connection(write=True) as db:
            for row in payload['rows']:
                # Schema permits NULL only for legacy records without an observed update time.
                repository.insert(db,row)
            db.execute('UPDATE knowledge_revision SET revision=? WHERE id=1',(payload['source_revision'],))
            db.executemany('INSERT OR REPLACE INTO knowledge_metadata VALUES (?,?)',[
                ('disease_names',json.dumps(payload['disease_names'],ensure_ascii=False)),
                ('migration_content_sha256',plan['content_sha256']),('migration_version',plan['migration_version'])])
        _,actual,metadata=repository.snapshot()
        if actual!=payload['rows'] or metadata['disease_names']!=payload['disease_names']:
            raise KnowledgeError('KNOWLEDGE_MIGRATION_VERIFY_FAILED')
        with repository.connection() as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                raise KnowledgeError('KNOWLEDGE_MIGRATION_VERIFY_FAILED')
        if prepare(source,legacy_json)[0]!=plan:raise KnowledgeError('KNOWLEDGE_MIGRATION_PLAN_CHANGED')
        # Atomic no-replace publication, including a concurrent migration process.
        os.link(stage,target)
        return {**plan,'status':'MIGRATED','applied':True,'backup_id':operation,'integrity':'ok'}
    except (OSError,sqlite3.Error):
        raise KnowledgeError('KNOWLEDGE_MIGRATION_STORAGE_ERROR') from None
    finally:
        if stage is not None and stage.is_file():stage.unlink()
