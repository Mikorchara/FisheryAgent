"""SQLite authoritative current state and bounded history. No secrets or device I/O."""

from contextlib import contextmanager
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
from threading import RLock

from .contracts import IngestionError, ChannelAnalysis, strict_json
from .events import EventService, interrupt_visual
from .rules import VISUAL_RULES
from .history import (HistoryQueryError, MAX_HISTORY_ROWS, MAX_HISTORY_ROW_BYTES,
                      validate_history_range)


class MonitoringRepository:
    def __init__(self, path, *, history_limit=360, batch_limit=1440, event_limit=300, event_service=None,
                 require_existing=False):
        for limit in (history_limit, batch_limit, event_limit):
            if type(limit) is not int or not 1 <= limit <= 10000:
                raise ValueError("INVALID_STORAGE_LIMIT")
        self.path = Path(path)
        self.require_existing = require_existing
        if not require_existing:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.history_limit, self.batch_limit, self.event_limit = history_limit, batch_limit, event_limit
        self.event_service = event_service if event_service is not None else EventService()
        self.lock = RLock()
        with self.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if require_existing:
                if version != 1:
                    raise ValueError("UNSUPPORTED_MONITORING_STORAGE_SCHEMA")
                return
            if version not in (0, 1):
                raise ValueError("UNSUPPORTED_MONITORING_STORAGE_SCHEMA")
            db.executescript('''
                CREATE TABLE IF NOT EXISTS batches (
                    batch_id TEXT PRIMARY KEY, device_id TEXT NOT NULL, session_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL, digest TEXT NOT NULL, received_at TEXT NOT NULL,
                    UNIQUE(device_id, session_id, sequence));
                CREATE TABLE IF NOT EXISTS history (
                    batch_id TEXT NOT NULL, device_id TEXT NOT NULL, channel TEXT NOT NULL,
                    observed_at TEXT NOT NULL, received_at TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(batch_id, channel));
                CREATE INDEX IF NOT EXISTS history_lookup ON history(device_id, channel, observed_at);
                CREATE TABLE IF NOT EXISTS current (
                    device_id TEXT NOT NULL, channel TEXT NOT NULL, batch_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL, received_at TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(device_id, channel));
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY, device_id TEXT NOT NULL, channel TEXT NOT NULL, code TEXT NOT NULL,
                    payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS alerts (
                    device_id TEXT NOT NULL, channel TEXT NOT NULL, code TEXT NOT NULL,
                    event_id TEXT NOT NULL, PRIMARY KEY(device_id, channel, code));
                CREATE TABLE IF NOT EXISTS channel_contacts (
                    device_id TEXT NOT NULL, channel TEXT NOT NULL, last_received_at TEXT NOT NULL,
                    PRIMARY KEY(device_id, channel));
            ''')
            db.execute("PRAGMA user_version=1")

    @contextmanager
    def connection(self):
        # One short-lived connection per operation, so Flask threads never share a connection.
        with self.lock:
            db = (sqlite3.connect(self.path.resolve().as_uri()+'?mode=rw', uri=True, timeout=5)
                  if self.require_existing else sqlite3.connect(self.path, timeout=5))
            db.row_factory = sqlite3.Row
            try:
                with db:
                    yield db
            finally:
                db.close()

    def ingest(self, batch, received_at, assessments, *, stale_after_s=None):
        if (not isinstance(assessments, dict) or any(not isinstance(a, ChannelAnalysis)
                or a.device_id != batch["device_id"] or a.channel != channel
                or batch[channel] is not None and (a.observation is None or a.observation.batch_id != batch["batch_id"])
                for channel, a in assessments.items()) or set(assessments) != {"water", "visual"}):
            raise ValueError("INVALID_EVENT_ASSESSMENT")
        text = json.dumps(batch, sort_keys=True, separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256(text.encode()).hexdigest()
        device = batch["device_id"]
        updated = []
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            duplicate = db.execute("SELECT digest FROM batches WHERE batch_id=? OR (device_id=? AND session_id=? AND sequence=?)",
                (batch["batch_id"], device, batch["session_id"], batch["sequence"])).fetchone()
            if duplicate:
                if duplicate["digest"] != digest:
                    raise IngestionError("BATCH_ID_CONFLICT", 409)
                self._contact(db, batch, received_at)
                return {"status": "duplicate", "updated_channels": []}
            for channel in ("water", "visual"):
                payload = batch[channel]
                if payload is None:
                    if channel == "visual":
                        current = db.execute("SELECT observed_at FROM current WHERE device_id=? AND channel=?", (device, channel)).fetchone()
                        if current is None or batch["timestamp"] > current["observed_at"]:
                            self._interrupt_visual(db, device, received_at.isoformat(), batch["timestamp"])
                    continue
                current = db.execute("SELECT * FROM current WHERE device_id=? AND channel=?", (device, channel)).fetchone()
                if current and current["observed_at"] == batch["timestamp"]:
                    raise IngestionError("OBSERVATION_CONFLICT", 409)
                encoded = json.dumps({"window": batch["window"], "data": payload}, allow_nan=False)
                args = (batch["batch_id"], device, channel, batch["timestamp"], received_at.isoformat(), encoded)
                db.execute("INSERT INTO history VALUES(?,?,?,?,?,?)", args)
                if not current or batch["timestamp"] > current["observed_at"]:
                    db.execute("INSERT OR REPLACE INTO current VALUES(?,?,?,?,?,?)",
                        (device, channel, batch["batch_id"], batch["timestamp"], received_at.isoformat(), encoded))
                    updated.append(channel)
                    self._events(db, batch, channel, assessments[channel], stale_after_s=stale_after_s)
                db.execute("DELETE FROM history WHERE device_id=? AND channel=? AND batch_id NOT IN (SELECT batch_id FROM history WHERE device_id=? AND channel=? ORDER BY observed_at DESC LIMIT ?)",
                           (device, channel, device, channel, self.history_limit))
            db.execute("INSERT INTO batches VALUES(?,?,?,?,?,?)", (batch["batch_id"], device, batch["session_id"], batch["sequence"], digest, received_at.isoformat()))
            self._contact(db, batch, received_at)
            db.execute("DELETE FROM batches WHERE device_id=? AND batch_id NOT IN (SELECT batch_id FROM batches WHERE device_id=? ORDER BY received_at DESC, rowid DESC LIMIT ?)",
                       (device, device, self.batch_limit))
            # Keep every linked unresolved episode, plus the latest bounded unlinked history.
            db.execute("""DELETE FROM events WHERE id NOT IN (SELECT event_id FROM alerts)
                AND id NOT IN (SELECT id FROM events WHERE id NOT IN (SELECT event_id FROM alerts)
                    ORDER BY rowid DESC LIMIT ?)""", (self.event_limit,))
            db.execute("DELETE FROM alerts WHERE event_id NOT IN (SELECT id FROM events)")
        return {"status": "accepted" if updated else "out_of_order", "updated_channels": updated}

    @staticmethod
    def _contact(db, batch, received_at):
        for channel in ("water", "visual"):
            if batch[channel] is not None:
                db.execute("INSERT INTO channel_contacts VALUES(?,?,?) ON CONFLICT(device_id,channel) DO UPDATE SET last_received_at=MAX(last_received_at,excluded.last_received_at)",
                           (batch["device_id"], channel, received_at.isoformat()))

    @staticmethod
    def _interrupt_visual(db, device_id, at, observed_at):
        rows = db.execute("SELECT e.payload FROM alerts a JOIN events e ON a.event_id=e.id WHERE a.device_id=? AND a.channel='visual'", (device_id,)).fetchall()
        for row in rows:
            event = json.loads(row["payload"])
            if event["code"] in VISUAL_RULES:
                previous = event.get("visual_recovery", {}).get("interrupted_through")
                if previous and datetime.fromisoformat(observed_at) <= datetime.fromisoformat(previous):
                    continue
                interrupt_visual(event, "VISUAL_OBSERVATION_MISSING", at)
                event["visual_recovery"]["interrupted_through"] = observed_at
                db.execute("UPDATE events SET payload=? WHERE id=?", (json.dumps(event), event["id"]))

    def _events(self, db, batch, channel, assessment, *, stale_after_s):
        rows = db.execute("SELECT e.payload FROM alerts a JOIN events e ON a.event_id=e.id WHERE a.device_id=? AND a.channel=?",
                          (batch["device_id"], channel))
        existing = {e["code"]: e for e in (json.loads(r["payload"]) for r in rows)}
        fresh_until = (datetime.fromisoformat(batch["timestamp"]) + timedelta(seconds=stale_after_s)).isoformat() if stale_after_s is not None else None
        changes = self.event_service.transition(existing, assessment, session_id=batch["session_id"],
            sequence=batch["sequence"], fresh_until=fresh_until)
        for event in changes.updates:
            db.execute("UPDATE events SET payload=? WHERE id=?", (json.dumps(event), event["id"]))
        for event in changes.inserts:
            db.execute("INSERT INTO events VALUES(?,?,?,?,?)", (event["id"], event["device_id"], channel, event["code"], json.dumps(event)))
        for code, event_id in changes.active_links:
            db.execute("INSERT OR REPLACE INTO alerts VALUES(?,?,?,?)", (batch["device_id"], channel, code, event_id))
        for code in changes.resolved_codes:
            db.execute("DELETE FROM alerts WHERE device_id=? AND channel=? AND code=?", (batch["device_id"], channel, code))

    def read(self, device_id, channel):
        with self.connection() as db:
            row = db.execute("SELECT c.*,h.last_received_at AS last_reported_at FROM current c LEFT JOIN channel_contacts h ON c.device_id=h.device_id AND c.channel=h.channel WHERE c.device_id=? AND c.channel=?", (device_id, channel)).fetchone()
            return self._decode(row) if row else None

    def capture(self, device_id, channel):
        """Current and history use the same read transaction, never a mixed update."""
        with self.connection() as db:
            db.execute("BEGIN")
            row = db.execute("SELECT c.*,h.last_received_at AS last_reported_at FROM current c LEFT JOIN channel_contacts h ON c.device_id=h.device_id AND c.channel=h.channel WHERE c.device_id=? AND c.channel=?", (device_id, channel)).fetchone()
            history = self._history(db, device_id, channel)
            return self._decode(row) if row else None, history

    def history(self, device_id, channel):
        with self.connection() as db:
            return self._history(db, device_id, channel)

    def query_water_history(self, device_id, *, start, end):
        """One indexed read transaction, with a sentinel instead of silent truncation."""
        start, end = validate_history_range(start, end)
        try:
            with self.connection() as db:
                db.execute("BEGIN")
                rows = db.execute("""SELECT h.batch_id,h.device_id,h.channel,h.observed_at,h.received_at,
                    b.session_id,b.device_id AS session_device_id,length(CAST(h.payload AS BLOB)) AS payload_bytes,
                    CASE WHEN length(CAST(h.payload AS BLOB))<=? THEN h.payload END AS payload
                    FROM history h LEFT JOIN batches b ON h.batch_id=b.batch_id
                    WHERE h.device_id=? AND h.channel='water' AND h.observed_at>? AND h.observed_at<=?
                    ORDER BY h.observed_at,h.received_at,h.batch_id LIMIT ?""",
                    (MAX_HISTORY_ROW_BYTES, device_id, start.isoformat(), end.isoformat(), MAX_HISTORY_ROWS + 1)).fetchall()
                if len(rows) > MAX_HISTORY_ROWS:
                    raise HistoryQueryError("HISTORY_QUERY_BUDGET_EXCEEDED")
                result = []
                for row in rows:
                    item = dict(row)
                    if item.pop("session_device_id") not in (None, device_id) or type(item["payload_bytes"]) is not int:
                        raise HistoryQueryError("HISTORY_RECORD_INVALID")
                    if item["payload_bytes"] > MAX_HISTORY_ROW_BYTES:
                        raise HistoryQueryError("HISTORY_RECORD_TOO_LARGE")
                    try:
                        item["payload"] = strict_json(item["payload"])
                    except (ValueError, TypeError):
                        raise HistoryQueryError("HISTORY_RECORD_INVALID") from None
                    item.pop("payload_bytes")
                    result.append(item)
                return result
        except sqlite3.Error:
            raise HistoryQueryError("HISTORY_STORAGE_ERROR") from None

    def _history(self, db, device_id, channel):
        # Session metadata is read-only and optional for legacy/pruned batch records.
        return [self._decode(r) for r in db.execute("""SELECT h.*, b.session_id FROM history h
            LEFT JOIN batches b ON h.batch_id=b.batch_id
            WHERE h.device_id=? AND h.channel=?
            ORDER BY h.observed_at, h.received_at, h.batch_id""", (device_id, channel))]

    def events(self):
        with self.connection() as db:
            result = [json.loads(r["payload"]) for r in db.execute("SELECT payload FROM events ORDER BY rowid DESC")]
        return [self.event_service.legacy_projection(event) for event in result]

    @staticmethod
    def _decode(row):
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        return result
