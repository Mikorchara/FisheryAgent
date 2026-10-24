"""Operator closure of interrupted observations, separate from rule recovery.

Stored in existing event JSON. No schema migration, monitoring-state rewrite or
alert-link removal. Repository owns transactions; assessment is a local callback.
"""
from copy import deepcopy
import json
import re
import uuid

from .event_handling import cycle_reference, digest
from .event_records import EventRecordError


def key(event):
    reference = cycle_reference(event)
    return reference[0] if reference else 'event:' + event['id']


def cursor(members):
    return digest(sorted((e['id'], e.get('last_observed_at'), e.get('last_batch_id'),
                          digest(e.get('rule_identity'))) for e in members))


def history(members):
    # A cycle mirrors its ledger into members so retention never loses a grade.
    records = {a['request_id']:a for e in members for a in e.get('manual_ends', [])}
    # Wall-clock corrections must not resurrect an older operator decision.
    # Old v2 JSON has no revision and remains a readable prefix of the ledger.
    return sorted(records.values(), key=lambda a:(a.get('revision',0),a['acted_at'],a['request_id']))


def sync_history(db):
    """New grades in an existing cycle retain its audit; new cycles inherit none."""
    groups={}
    for row in db.execute('SELECT payload FROM events'):
        event=json.loads(row['payload'])
        groups.setdefault(key(event),[]).append(event)
    for members in groups.values():
        records=history(members)
        if not records:
            continue
        for event in members:
            if event.get('manual_ends') != records:
                event['manual_ends']=records
                db.execute('UPDATE events SET payload=? WHERE id=?',(json.dumps(event),event['id']))


def interrupted(event):
    quality = event.get('current_data_quality', {})
    return (event.get('lifecycle_state') == 'INDETERMINATE' and event.get('status') != 'closed'
            and bool(quality) and (quality.get('freshness') != 'fresh'
                or quality.get('connectivity') != 'online' or quality.get('quality') in ('missing','invalid','partial')))


def can_end_group(members):
    pending=[e for e in members if e.get('status')!='closed' and e.get('lifecycle_state')!='RESOLVED']
    return bool(pending) and all(interrupted(e) for e in pending)


def project(events):
    groups = {}
    for e in events:
        groups.setdefault(key(e), []).append(e)
    for members in groups.values():
        records = history(members)
        latest = records[-1] if records else None
        ended_by_rule = all(e.get('lifecycle_state') == 'RESOLVED' or e.get('status') == 'closed' for e in members)
        active = bool(latest and latest['cursor'] == cursor(members) and not ended_by_rule)
        eligible = bool(not active and len(records) < 50 and can_end_group(members))
        brief = [{k:a[k] for k in ('request_id','acted_at','reason','actor_kind','event_ids')} for a in records]
        for e in members:
            e['manual_end'] = dict(active=active, can_end=eligible,
                acted_at=latest['acted_at'] if active else None, history=brief)
            if records:
                e.update(deletable=False, can_delete_ack_cycle=False, deletion_block_reason='MANUAL_END_AUDIT_RETAINED')
            if active and e.get('handling'):
                e['handling']['can_ack'] = False
            # Keep full evidence/request digests in storage, not every Bootstrap DTO.
            e.pop('manual_ends',None)
    return events


def validate_id(event_id):
    if not isinstance(event_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',event_id):
        raise EventRecordError('INVALID_EVENT_END')


def plan(db, event_id, assessed):
    validate_id(event_id)
    rows = {r['id']:json.loads(r['payload']) for r in db.execute('SELECT id,payload FROM events')}
    if event_id not in rows:
        raise EventRecordError('EVENT_NOT_FOUND',404)
    members = [e for e in rows.values() if key(e) == key(rows[event_id])]
    projected = {e['id']:e for e in assessed()}
    if not all(e['id'] in projected for e in members) or not can_end_group([projected[e['id']] for e in members]):
        raise EventRecordError('EVENT_END_REQUIRES_INTERRUPTION',409)
    records = history(members)
    if records and records[-1]['cursor'] == cursor(members):
        raise EventRecordError('EVENT_ALREADY_MANUALLY_ENDED',409)
    if len(records) >= 50:
        raise EventRecordError('EVENT_END_HISTORY_LIMIT',409)
    # Include the authoritative channel snapshot/contact in the compare-and-set.
    device,channel = members[0]['device_id'],members[0]['channel']
    observations = [tuple(r) for r in db.execute('SELECT * FROM current WHERE device_id=? AND channel=?',(device,channel))]
    contacts = [tuple(r) for r in db.execute('SELECT * FROM channel_contacts WHERE device_id=? AND channel=?',(device,channel))]
    revision = digest([sorted(members,key=lambda e:e['id']),observations,contacts])
    return members,dict(event_id=event_id,count=len(members),revision=revision)


def commit(db, value, at, assessed):
    if not isinstance(value,dict) or set(value) != {'event_id','revision','request_id','reason'}:
        raise EventRecordError('INVALID_EVENT_END')
    validate_id(value['event_id'])
    try:
        if str(uuid.UUID(value['request_id'])) != value['request_id']:
            raise ValueError()
    except (TypeError,ValueError,AttributeError):
        raise EventRecordError('INVALID_EVENT_END') from None
    if (not isinstance(value['reason'],str) or not 1 <= len(value['reason'].strip()) <= 200
            or any(ord(c)<32 for c in value['reason']) or not isinstance(value['revision'],str)
            or not re.fullmatch('[a-f0-9]{64}',value['revision'])):
        raise EventRecordError('INVALID_EVENT_END')
    request_hash = digest(value)
    for row in db.execute('SELECT payload FROM events'):
        for action in json.loads(row['payload']).get('manual_ends',[]):
            if action['request_id'] == value['request_id']:
                if action['request_hash'] != request_hash:
                    raise EventRecordError('EVENT_END_REQUEST_CONFLICT',409)
                return dict(status='MANUALLY_ENDED',acted_at=action['acted_at'],count=len(action['event_ids']))
    members, preview = plan(db,value['event_id'],assessed)
    if preview['revision'] != value['revision']:
        raise EventRecordError('EVENT_END_CONFLICT',409)
    records = history(members)
    revision=max((a.get('revision',0) for a in records),default=0)+1
    records.append(dict(request_id=value['request_id'],request_hash=request_hash,acted_at=at.isoformat(),revision=revision,
        reason=value['reason'].strip(),actor_kind='local_visitor',cursor=cursor(members),
        event_ids=sorted(e['id'] for e in members),
        evidence=[{k:e.get(k) for k in ('id','code','rule_identity','observation','title','occurred_at',
            'last_observed_at','last_batch_id','lifecycle_state','state_reason','status')} for e in members]))
    for e in members:
        stored=deepcopy(e)
        stored['manual_ends']=records
        db.execute('UPDATE events SET payload=? WHERE id=?',(json.dumps(stored),e['id']))
    return dict(status='MANUALLY_ENDED',acted_at=at.isoformat(),count=len(members))
