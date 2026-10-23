"""Monitoring storage versions. Existing v1 stores require an explicit maintenance step."""

SCHEMA_VERSION = 2
BASE_COLUMNS = {
    'batches': 'batch_id device_id session_id sequence digest received_at',
    'history': 'batch_id device_id channel observed_at received_at payload',
    'current': 'device_id channel batch_id observed_at received_at payload',
    'events': 'id device_id channel code payload',
    'alerts': 'device_id channel code event_id',
    'channel_contacts': 'device_id channel last_received_at',
}
HANDLING_COLUMNS = {
    'event_handling': 'cycle_id anchor_event_id grade_code grade_rank grade_token grade_version revision acked_at',
    'event_actions': 'id request_id request_hash cycle_id event_id action acted_at grade_code grade_rank grade_version grade_token handling_revision actor_kind event_snapshot',
    'event_handling_members': 'event_id cycle_id',
}


def add_handling_tables(db):
    # Execute individual DDL statements: executescript would commit a migration early.
    for statement in (
        '''CREATE TABLE event_handling (
            cycle_id TEXT PRIMARY KEY, anchor_event_id TEXT NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
            grade_code TEXT NOT NULL, grade_rank INTEGER NOT NULL CHECK(grade_rank>0),
            grade_token TEXT NOT NULL, grade_version TEXT NOT NULL,
            revision INTEGER NOT NULL CHECK(revision>0), acked_at TEXT)''',
        '''CREATE TABLE event_actions (
            id INTEGER PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL,
            cycle_id TEXT NOT NULL REFERENCES event_handling(cycle_id) ON DELETE RESTRICT,
            event_id TEXT NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
            action TEXT NOT NULL CHECK(action='ACK'), acted_at TEXT NOT NULL,
            grade_code TEXT NOT NULL, grade_rank INTEGER NOT NULL CHECK(grade_rank>0),
            grade_version TEXT NOT NULL, grade_token TEXT NOT NULL, handling_revision INTEGER NOT NULL,
            actor_kind TEXT NOT NULL CHECK(actor_kind='local_visitor'), event_snapshot TEXT NOT NULL)''',
        'CREATE INDEX event_actions_cycle ON event_actions(cycle_id,id)',
        '''CREATE TABLE event_handling_members (
            event_id TEXT PRIMARY KEY REFERENCES events(id) ON DELETE RESTRICT,
            cycle_id TEXT NOT NULL REFERENCES event_handling(cycle_id) ON DELETE RESTRICT)''',
        'CREATE INDEX event_handling_members_cycle ON event_handling_members(cycle_id)',
    ):
        db.execute(statement)


def validate_schema(db, version=SCHEMA_VERSION):
    if version not in (1, SCHEMA_VERSION):
        raise ValueError('UNSUPPORTED_MONITORING_STORAGE_SCHEMA')
    columns = BASE_COLUMNS | (HANDLING_COLUMNS if version == SCHEMA_VERSION else {})
    for table, names in columns.items():
        actual = {row[1] for row in db.execute('PRAGMA table_info('+table+')')}
        if not set(names.split()) <= actual:
            raise ValueError('INVALID_MONITORING_STORAGE_SCHEMA')
    if db.execute('''SELECT 1 FROM alerts a LEFT JOIN events e ON e.id=a.event_id
            WHERE e.id IS NULL OR a.device_id<>e.device_id OR a.channel<>e.channel OR a.code<>e.code LIMIT 1''').fetchone():
        raise ValueError('MONITORING_EVENT_REFERENCES_INVALID')
    if version == SCHEMA_VERSION:
        for table, required in {
            'event_handling': {('events','anchor_event_id','id')},
            'event_actions': {('events','event_id','id'),('event_handling','cycle_id','cycle_id')},
            'event_handling_members': {('events','event_id','id'),('event_handling','cycle_id','cycle_id')},
        }.items():
            keys = {(r[2],r[3],r[4]) for r in db.execute('PRAGMA foreign_key_list('+table+')') if r[6] == 'RESTRICT'}
            if not required <= keys:
                raise ValueError('INVALID_MONITORING_STORAGE_SCHEMA')
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('INVALID_MONITORING_STORAGE_REFERENCES')
