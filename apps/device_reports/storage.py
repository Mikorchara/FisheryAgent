"""Separate durable report inbox; never opens Monitoring or Settings databases."""
from contextlib import contextmanager,closing
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import stat
from .contracts import ReportError,validate

FILENAME='device-reports.sqlite3'


def safe_directory(directory):
    directory=Path(directory).absolute()
    for path in (directory,*directory.parents):
        if path.exists() and (path.is_symlink() or getattr(path,'is_junction',lambda:False)()):
            raise ReportError('DEVICE_REPORT_PATH_UNSAFE')
    return directory


class ReportStore:
    def __init__(self,directory,*,read_only=False):
        self.path=safe_directory(directory)/FILENAME
        self.read_only=read_only
        if not self.path.is_file():raise ReportError('DEVICE_REPORT_STORE_MISSING',503)
        status=self.path.lstat()
        if not stat.S_ISREG(status.st_mode) or status.st_nlink!=1:
            raise ReportError('DEVICE_REPORT_PATH_UNSAFE')
        self.identity=(status.st_dev,status.st_ino)
        with self.connection() as db:
            if db.execute('PRAGMA user_version').fetchone()[0]!=1:
                raise ReportError('DEVICE_REPORT_SCHEMA_UNSUPPORTED',503)
            expected={'device_id','report_id','digest','observed_at','received_at','payload','warnings'}
            if {r[1] for r in db.execute('PRAGMA table_info(reports)')}!=expected:
                raise ReportError('DEVICE_REPORT_SCHEMA_UNSUPPORTED',503)

    @classmethod
    def initialize(cls,directory):
        directory=safe_directory(directory)
        directory.mkdir(parents=True,exist_ok=True)
        path=directory/FILENAME
        try:
            with path.open('xb'):pass
        except FileExistsError:
            raise ReportError('DEVICE_REPORT_STORE_EXISTS') from None
        with closing(sqlite3.connect(path)) as db:
            db.executescript('''CREATE TABLE reports(
              device_id TEXT NOT NULL, report_id TEXT NOT NULL, digest TEXT NOT NULL,
              observed_at TEXT NOT NULL, received_at TEXT NOT NULL, payload TEXT NOT NULL,
              warnings TEXT NOT NULL, PRIMARY KEY(device_id,report_id));
              CREATE INDEX report_order ON reports(device_id,observed_at DESC,received_at DESC);
              PRAGMA user_version=1;''')
            db.commit()
        return cls(directory)

    @contextmanager
    def connection(self):
        # Always rw/ro, never implicit creation or repair. FULL commit before HTTP 2xx.
        uri=self.path.as_uri()+('?mode=ro' if self.read_only else '?mode=rw')
        db=None
        try:
            safe_directory(self.path.parent)
            current=self.path.lstat()
            if not stat.S_ISREG(current.st_mode) or current.st_nlink!=1 or (current.st_dev,current.st_ino)!=self.identity:
                raise ReportError('DEVICE_REPORT_PATH_CHANGED',503)
            db=sqlite3.connect(uri,uri=True,timeout=1.5)
            db.execute('PRAGMA query_only='+('ON' if self.read_only else 'OFF'))
            if not self.read_only:db.execute('PRAGMA synchronous=FULL')
            yield db
        except (sqlite3.Error,OSError):
            raise ReportError('DEVICE_REPORT_STORAGE_UNAVAILABLE',503) from None
        finally:
            if db is not None:db.close()

    def receive(self,raw,*,device_id,now):
        if self.read_only:raise ReportError('DEVICE_REPORT_READ_ONLY',403)
        value,payload,digest,warnings=validate(raw,device_id=device_id,now=now)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            existing=db.execute('SELECT digest FROM reports WHERE device_id=? AND report_id=?',
                                (device_id,value['report_id'])).fetchone()
            if existing:
                if existing[0]!=digest:raise ReportError('DEVICE_REPORT_ID_CONFLICT',409)
                return {'status':'duplicate','report_id':value['report_id']}
            if db.execute('SELECT count(*) FROM reports').fetchone()[0]>=5000:
                raise ReportError('DEVICE_REPORT_STORE_FULL',503)
            db.execute('INSERT INTO reports VALUES(?,?,?,?,?,?,?)',(device_id,value['report_id'],digest,
                datetime.fromisoformat(value['window']['end'].replace('Z','+00:00')).astimezone(timezone.utc).isoformat(),
                now.astimezone(timezone.utc).isoformat(),payload,json.dumps(warnings)))
            db.commit()
        return {'status':'accepted','report_id':value['report_id'],'warnings':warnings}

    def recent(self,device_id,*,now):
        with self.connection() as db:
            rows=db.execute('SELECT received_at,payload,warnings FROM reports WHERE device_id=? ORDER BY observed_at DESC,received_at DESC,report_id DESC LIMIT 20',
                            (device_id,)).fetchall()
        items=[]
        for received,payload,warnings in rows:
            value=json.loads(payload)
            observed=datetime.fromisoformat(value['window']['end'].replace('Z','+00:00'))
            age=(now-observed).total_seconds()
            items.append(dict(report=value,received_at=received,warnings=json.loads(warnings),
                              freshness='fresh' if 0<=age<=120 else 'stale' if age>120 else 'unknown'))
        return dict(device_id=device_id,source_kind='device_report',items=items,
                    semantics='RAW_REPORT_ONLY_NO_EVENT_RECOVERY',water_source='SIMULATOR',
                    connectivity='unknown',task_coverage='unknown')
