"""Small transactional content store. No model, Web or retrieval dependencies."""
from contextlib import contextmanager
from pathlib import Path
import re
import sqlite3
import uuid

MAX_USER_RECORDS = 200
MAX_TOTAL_BODY_CHARS = 256 * 1024


class KnowledgeError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:user-[a-f0-9]{32}|builtin-[a-f0-9]{24})', value):
        raise KnowledgeError('INVALID_KNOWLEDGE_ID')
    return value


class KnowledgeRepository:
    def __init__(self, path):
        self.path = Path(path)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.connection() as db:
                db.executescript('''
                    CREATE TABLE IF NOT EXISTS knowledge_records (
                        id TEXT PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL,
                        body TEXT NOT NULL, version INTEGER NOT NULL, status TEXT NOT NULL,
                        updated_at TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS builtin_state (
                        id TEXT PRIMARY KEY, version INTEGER NOT NULL,
                        status TEXT NOT NULL, updated_at TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS knowledge_revision (id INTEGER PRIMARY KEY, revision INTEGER NOT NULL);
                    INSERT OR IGNORE INTO knowledge_revision VALUES (1, 0);
                ''')
        except OSError:
            raise KnowledgeError('KNOWLEDGE_STORAGE_ERROR') from None

    @contextmanager
    def connection(self, *, write=False):
        db = None
        try:
            db = sqlite3.connect(self.path, timeout=2, isolation_level=None)
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
            users = [dict(row) for row in db.execute('SELECT * FROM knowledge_records ORDER BY id LIMIT ?', (MAX_USER_RECORDS+1,))]
            states = {row['id']: dict(row) for row in db.execute('SELECT * FROM builtin_state LIMIT 512')}
        if len(users) > MAX_USER_RECORDS:
            raise KnowledgeError('KNOWLEDGE_LIMIT')
        return revision, users, states

    def create(self, value, timestamp):
        key = 'user-' + uuid.uuid4().hex
        with self.connection(write=True) as db:
            if db.execute('SELECT count(*) FROM knowledge_records').fetchone()[0] >= MAX_USER_RECORDS:
                raise KnowledgeError('KNOWLEDGE_LIMIT')
            if db.execute('SELECT 1 FROM knowledge_records WHERE id=?', (key,)).fetchone():
                raise KnowledgeError('KNOWLEDGE_CONFLICT')
            if db.execute('SELECT coalesce(sum(length(body)),0) FROM knowledge_records').fetchone()[0]+len(value['body']) > MAX_TOTAL_BODY_CHARS:
                raise KnowledgeError('KNOWLEDGE_LIMIT')
            db.execute('INSERT INTO knowledge_records VALUES (?, ?, ?, ?, 1, ?, ?)',
                       (key, value['title'], value['category'], value['body'], 'ACTIVE', timestamp))
            db.execute('UPDATE knowledge_revision SET revision=revision+1 WHERE id=1')
        return key

    def update(self, key, version, changes, timestamp, *, builtin=False):
        # Column/table identifiers come only from this fixed code, never request input.
        table = 'builtin_state' if builtin else 'knowledge_records'
        with self.connection(write=True) as db:
            row = db.execute(f'SELECT * FROM {table} WHERE id=?', (key,)).fetchone()
            if row is None and not builtin: raise KnowledgeError('KNOWLEDGE_NOT_FOUND')
            current = dict(row) if row is not None else {'version':1, 'status':'ACTIVE'}
            if current['version'] != version: raise KnowledgeError('KNOWLEDGE_CONFLICT')
            if builtin:
                db.execute('INSERT INTO builtin_state VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET '
                           'version=excluded.version, status=excluded.status, updated_at=excluded.updated_at',
                           (key, version+1, changes['status'], timestamp))
            else:
                value = {**current, **changes}
                if db.execute('SELECT coalesce(sum(length(body)),0) FROM knowledge_records WHERE id<>?',(key,)).fetchone()[0]+len(value['body']) > MAX_TOTAL_BODY_CHARS:
                    raise KnowledgeError('KNOWLEDGE_LIMIT')
                db.execute('UPDATE knowledge_records SET title=?, category=?, body=?, version=?, status=?, updated_at=? WHERE id=?',
                           (value['title'], value['category'], value['body'], version+1, value['status'], timestamp, key))
            db.execute('UPDATE knowledge_revision SET revision=revision+1 WHERE id=1')
