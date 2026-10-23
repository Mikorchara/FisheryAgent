"""Explicit, revision-checked removal of an ended cycle and its ACK ledger."""

import json

from .event_handling import cycle_reference, digest
from .event_records import EventRecordError, parse_time


def deletion_plan(db, event_id):
    rows = db.execute('SELECT id,payload FROM events ORDER BY id').fetchall()
    events = {r['id']:json.loads(r['payload']) for r in rows}
    if event_id not in events:
        raise EventRecordError('EVENT_NOT_FOUND', 404)
    reference = cycle_reference(events[event_id])
    if not reference:
        raise EventRecordError('EVENT_CYCLE_UNSUPPORTED', 409)
    cycle_id = reference[0]
    handling = db.execute('SELECT * FROM event_handling WHERE cycle_id=?', (cycle_id,)).fetchone()
    actions = db.execute('SELECT * FROM event_actions WHERE cycle_id=? ORDER BY id', (cycle_id,)).fetchall()
    if not handling or not actions:
        raise EventRecordError('EVENT_CYCLE_UNSUPPORTED', 409)
    members = {key for key,e in events.items() if cycle_reference(e) == reference}
    stored = {r[0] for r in db.execute('SELECT event_id FROM event_handling_members WHERE cycle_id=?', (cycle_id,))}
    if members != stored or handling['anchor_event_id'] not in members or any(r['event_id'] not in members for r in actions):
        raise EventRecordError('EVENT_CYCLE_MEMBERS_CHANGED', 409)
    if any(events[key].get('lifecycle_state') != 'RESOLVED' or events[key].get('status') != 'closed'
           or parse_time(events[key].get('resolved_at')) is None for key in members):
        raise EventRecordError('EVENT_CYCLE_NOT_ENDED', 409)
    linked = {r[0] for r in db.execute('SELECT event_id FROM alerts')}
    outside_references = any(e.get('superseded_by') in members for key,e in events.items() if key not in members)
    outside_audit = any(r['event_id'] in members for r in db.execute(
        'SELECT event_id FROM event_actions WHERE cycle_id<>?', (cycle_id,))) or any(
        r[0] in members for r in db.execute('SELECT anchor_event_id FROM event_handling WHERE cycle_id<>?', (cycle_id,)))
    if linked & members or outside_references or outside_audit:
        raise EventRecordError('EVENT_CYCLE_REFERENCED', 409)
    candidates = [r for r in rows if r['id'] in members]
    revision = digest(['ack_cycle', event_id, [dict(r) for r in candidates], dict(handling),
                       [dict(r) for r in actions], sorted(stored)])
    return candidates, dict(scope='ack_cycle', event_id=event_id, cycle_id=cycle_id,
        count=len(candidates), ack_count=len(actions), legacy_count=0, revision=revision)


def delete_handling(db, plan):
    # RESTRICT foreign keys remain enabled; any later failure rolls back the whole transaction.
    count = db.execute('DELETE FROM event_actions WHERE cycle_id=?', (plan['cycle_id'],)).rowcount
    db.execute('DELETE FROM event_handling_members WHERE cycle_id=?', (plan['cycle_id'],))
    db.execute('DELETE FROM event_handling WHERE cycle_id=?', (plan['cycle_id'],))
    if count != plan['ack_count']:
        raise EventRecordError('EVENT_DELETE_CONFLICT', 409)
    return count
