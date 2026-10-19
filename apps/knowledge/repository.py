"""Bounded transactional authoritative text store; no Web or retrieval dependencies."""
from contextlib import contextmanager, closing
from pathlib import Path
import json
import re
import sqlite3
import uuid

MAX_USER_RECORDS = 200
MAX_IMPORTED_RECORDS = 512
MAX_TOTAL_BODY_CHARS = 256 * 1024
SCHEMA_VERSION = 2


class KnowledgeError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:user-[a-f0-9]{32}|builtin-[a-f0-9]{24})', value):
        raise KnowledgeError('INVALID_KNOWLEDGE_ID')
    return value


class KnowledgeRepository:
    def __init__(self, path, *, require_existing=False):
        self.path = Path(path)
        self.require_existing = require_existing
        if require_existing and not self.path.is_file():
            raise KnowledgeError('KNOWLEDGE_MIGRATION_REQUIRED')
        if require_existing:
            # Startup must not initialize/rewrite an empty, legacy or partially
            # prepared target. Only explicit migration/new-instance initialization
            # publishes the unified-format marker.
            try:
                with closing(sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
                    schema=db.execute('PRAGMA user_version').fetchone()[0]
                    marker=db.execute("SELECT value FROM knowledge_metadata WHERE key='migration_version'").fetchone()
                    if schema!=SCHEMA_VERSION or not marker or marker[0]!='unified-knowledge@2':
                        raise KnowledgeError('KNOWLEDGE_MIGRATION_REQUIRED')
            except sqlite3.Error:
                raise KnowledgeError('KNOWLEDGE_MIGRATION_REQUIRED') from None
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.connection(write=True) as db:
                existing = db.execute("SELECT 1 FROM sqlite_master WHERE name='knowledge_records'").fetchone()
                if existing and db.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
                    raise KnowledgeError('KNOWLEDGE_MIGRATION_REQUIRED')
                # Fixed statements keep schema initialization in the same transaction.
                db.execute('''CREATE TABLE IF NOT EXISTS knowledge_records (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL,
                    body TEXT NOT NULL, version INTEGER NOT NULL, status TEXT NOT NULL,
                    updated_at TEXT, origin TEXT NOT NULL,
                    original_source_id TEXT NOT NULL, original_source_version TEXT NOT NULL,
                    source_id TEXT NOT NULL, source_version TEXT NOT NULL,
                    evidence_id TEXT NOT NULL UNIQUE, chunk_type TEXT NOT NULL,
                    keywords_json TEXT NOT NULL, text_style TEXT NOT NULL, ordinal INTEGER NOT NULL UNIQUE)''')
                db.execute('CREATE TABLE IF NOT EXISTS knowledge_revision (id INTEGER PRIMARY KEY, revision INTEGER NOT NULL)')
                db.execute('INSERT OR IGNORE INTO knowledge_revision VALUES (1,0)')
                db.execute('CREATE TABLE IF NOT EXISTS knowledge_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
                db.execute('INSERT OR IGNORE INTO knowledge_metadata VALUES (?,?)', ('disease_names','[]'))
                db.execute('PRAGMA user_version=2')
        except OSError:
            raise KnowledgeError('KNOWLEDGE_STORAGE_ERROR') from None

    @contextmanager
    def connection(self, *, write=False):
        db = None
        try:
            db = (sqlite3.connect(self.path.resolve().as_uri()+'?mode=rw', uri=True, timeout=2, isolation_level=None)
                  if self.require_existing else sqlite3.connect(self.path, timeout=2, isolation_level=None))
            db.row_factory = sqlite3.Row
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield db
            if db.in_transaction: db.commit()
        except sqlite3.Error:
            if db is not None and db.in_transaction: db.rollback()
            raise KnowledgeError('KNOWLEDGE_STORAGE_ERROR') from None
        finally:
            if db is not None: db.close()

    def snapshot(self):
        with self.connection() as db:
            revision = db.execute('SELECT revision FROM knowledge_revision WHERE id=1').fetchone()[0]
            records = [dict(row) for row in db.execute("SELECT * FROM knowledge_records ORDER BY CASE origin WHEN 'builtin' THEN 0 ELSE 1 END, CASE origin WHEN 'builtin' THEN ordinal END, id LIMIT ?",
                                                     (MAX_USER_RECORDS+MAX_IMPORTED_RECORDS+1,))]
            metadata = dict(db.execute('SELECT key,value FROM knowledge_metadata'))
        if len(records)>MAX_USER_RECORDS+MAX_IMPORTED_RECORDS:
            raise KnowledgeError('KNOWLEDGE_LIMIT')
        try:
            for row in records: row['keywords'] = json.loads(row.pop('keywords_json'))
            metadata['disease_names'] = json.loads(metadata['disease_names'])
        except (ValueError,KeyError,TypeError):
            raise KnowledgeError('KNOWLEDGE_STORAGE_ERROR') from None
        return revision, records, metadata

    @staticmethod
    def insert(db, row):
        keys=('id','title','category','body','version','status','updated_at','origin',
              'original_source_id','original_source_version','source_id','source_version',
              'evidence_id','chunk_type','keywords_json','text_style','ordinal')
        db.execute('INSERT INTO knowledge_records VALUES ('+','.join('?' for _ in keys)+')',
                   tuple(json.dumps(row['keywords'],ensure_ascii=False) if key=='keywords_json' else row[key] for key in keys))

    def create(self, value, timestamp):
        key = 'user-' + uuid.uuid4().hex
        with self.connection(write=True) as db:
            if db.execute("SELECT count(*) FROM knowledge_records WHERE origin='user'").fetchone()[0] >= MAX_USER_RECORDS:
                raise KnowledgeError('KNOWLEDGE_LIMIT')
            if db.execute('SELECT 1 FROM knowledge_records WHERE id=?', (key,)).fetchone():
                raise KnowledgeError('KNOWLEDGE_CONFLICT')
            if db.execute('SELECT coalesce(sum(length(body)),0) FROM knowledge_records').fetchone()[0]+len(value['body']) > MAX_TOTAL_BODY_CHARS:
                raise KnowledgeError('KNOWLEDGE_LIMIT')
            ordinal=db.execute('SELECT coalesce(max(ordinal),-1)+1 FROM knowledge_records').fetchone()[0]
            self.insert(db, {**value,'id':key,'version':1,'status':'ACTIVE','updated_at':timestamp,
                'origin':'user','original_source_id':'management:knowledge/'+key,'original_source_version':'1',
                'source_id':'management:knowledge/'+key,'source_version':'1','evidence_id':key,
                'chunk_type':value['category'],'keywords':[value['title']],'text_style':'titled','ordinal':ordinal})
            db.execute('UPDATE knowledge_revision SET revision=revision+1 WHERE id=1')
        return key

    def update(self, key, version, changes, timestamp):
        with self.connection(write=True) as db:
            row=db.execute('SELECT * FROM knowledge_records WHERE id=?',(key,)).fetchone()
            if row is None: raise KnowledgeError('KNOWLEDGE_NOT_FOUND')
            current=dict(row)
            if current['version']!=version: raise KnowledgeError('KNOWLEDGE_CONFLICT')
            value={**current,**changes}
            if db.execute('SELECT coalesce(sum(length(body)),0) FROM knowledge_records WHERE id<>?',(key,)).fetchone()[0]+len(value['body']) > MAX_TOTAL_BODY_CHARS:
                raise KnowledgeError('KNOWLEDGE_LIMIT')
            # Status changes preserve the indexed content's provenance. A content
            # edit gets a managed source/version; immutable original provenance stays.
            source_id=current['source_id'];source_version=current['source_version']
            keywords=current['keywords_json'];chunk_type=current['chunk_type'];style=current['text_style']
            if 'body' in changes:
                source_id='management:knowledge/'+key;source_version=str(version+1)
                keywords=json.dumps([value['title']],ensure_ascii=False)
                chunk_type=value['category'];style='titled'
            elif current['origin']=='user':
                source_version=str(version+1)
            db.execute('''UPDATE knowledge_records SET title=?,category=?,body=?,version=?,status=?,updated_at=?,
                source_id=?,source_version=?,keywords_json=?,chunk_type=?,text_style=? WHERE id=?''',
                (value['title'],value['category'],value['body'],version+1,value['status'],timestamp,
                 source_id,source_version,keywords,chunk_type,style,key))
            db.execute('UPDATE knowledge_revision SET revision=revision+1 WHERE id=1')
