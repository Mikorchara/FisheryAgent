"""ACK-only audit state; called within Repository-owned SQLite transactions."""

import hashlib
import json
import re
import uuid

from .event_families import FAMILIES, family_group
from .event_records import EventRecordError
from .rules import VISUAL_RULES


RANKS = {code: value[3] for code, value in FAMILIES.items()} | dict.fromkeys(
    (*VISUAL_RULES, 'SENSOR_INVALID', 'SENSOR_PARTIAL', 'SENSOR_MISSING', 'SENSOR_STALE', 'DEVICE_OFFLINE'), 1)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


GRADE_VERSION = 'ack-grades-v1:' + digest(RANKS)[:16]


def cycle_reference(event):
    rule = event.get('rule_identity')
    if (not isinstance(rule, dict) or rule.get('rule_id') != event.get('code')
            or not rule.get('version') or rule['version'] != event.get('rule_version')
            or not isinstance(rule.get('scope'),list) or not rule['scope'] or event.get('code') not in RANKS):
        return None
    family = event.get('risk_family')
    if event.get('code') in FAMILIES:
        if (not family or family.get('inferred') or not family.get('episode_id')
                or family['episode_id'].startswith('legacy-') or family.get('key') != FAMILIES[event['code']][0]):
            return None
        return digest(['family', family_group(event), family['episode_id']]), family['episode_id']
    return digest(['event', event['device_id'], event['channel'], event['id'], rule]), event['id']


def contexts(events, linked):
    groups = {}
    for event in events:
        reference = cycle_reference(event)
        if reference:
            groups.setdefault(reference[0], []).append(event)
    result = {}
    for cycle_id, members in groups.items():
        anchor = cycle_reference(members[0])[1]
        current = None
        transition = None
        if members[0]['code'] in FAMILIES:
            family = max((e['risk_family'] for e in members), key=lambda f:f.get('last_transition_at',''))
            transitions = family.get('transitions', [])
            transition = transitions[-1] if transitions else None
            if transition and transition.get('code') != 'CLEAR':
                current = next((e for e in members if e['id'] == transition.get('event_id')
                    and e['code'] == transition['code']), None)
        else:
            current = members[0]
        active = bool(current and current['id'] in linked and not current.get('superseded_by')
            and current.get('lifecycle_state') in ('ACTIVE','INDETERMINATE') and current.get('status') != 'closed')
        # The explicit rank registry owns ACK grades. Unknown identities remain read-only.
        code = current['code'] if current else members[0]['code']
        rank = RANKS[code]
        token = digest([GRADE_VERSION, cycle_id, code, rank, transition])
        result[cycle_id] = dict(cycle_id=cycle_id, anchor_event_id=anchor, grade_code=code,
            grade_rank=rank, grade_version=GRADE_VERSION, grade_token=token,
            current=current, active=active, members=members)
    return result


def effective(row, context):
    result = dict(row) if row else dict(revision=0, acked_at=None)
    # Resolved/unknown periods do not supply a new grade. A later reliable grade does.
    if row and context['active'] and row['grade_token'] != context['grade_token']:
        result.update(revision=row['revision']+1, acked_at=None)
    return result


def load_events(db):
    return [json.loads(r['payload']) for r in db.execute('SELECT payload FROM events ORDER BY rowid DESC')]


def sync_existing(db):
    events = load_events(db)
    linked = {r[0] for r in db.execute('SELECT event_id FROM alerts')}
    groups = contexts(events, linked)
    for row in db.execute('SELECT * FROM event_handling').fetchall():
        context = groups.get(row['cycle_id'])
        if not context:
            continue
        state = effective(row, context)
        if state['revision'] != row['revision']:
            db.execute('''UPDATE event_handling SET grade_code=?,grade_rank=?,grade_token=?,grade_version=?,
                revision=?,acked_at=NULL WHERE cycle_id=?''', (*[context[k] for k in
                ('grade_code','grade_rank','grade_token','grade_version')], state['revision'],row['cycle_id']))
        for member in context['members']:
            db.execute('INSERT OR IGNORE INTO event_handling_members VALUES (?,?)', (member['id'],row['cycle_id']))


def project_handling(db, events):
    linked = {r[0] for r in db.execute('SELECT event_id FROM alerts')}
    groups = contexts(events, linked)
    states = {r['cycle_id']:dict(r) for r in db.execute('SELECT * FROM event_handling')}
    actions = {}
    # Brief history is bounded in the DTO; the complete append-only ledger stays in SQLite.
    counts = {r[0]:r[1] for r in db.execute('SELECT cycle_id,count(*) FROM event_actions GROUP BY cycle_id')}
    for row in db.execute('''SELECT * FROM (SELECT id,cycle_id,event_id,acted_at,grade_code,grade_rank,grade_version,
            handling_revision,actor_kind,event_snapshot,
            row_number() OVER (PARTITION BY cycle_id ORDER BY id DESC) AS position
            FROM event_actions) WHERE position<=20 ORDER BY id DESC'''):
        action = dict(row)
        action['event_title'] = json.loads(action.pop('event_snapshot')).get('title','未知事件')
        action.pop('position')
        actions.setdefault(row['cycle_id'], []).append(action)
    protected = {r[0] for r in db.execute('SELECT event_id FROM event_handling_members')}
    for event in events:
        reference = cycle_reference(event)
        context = groups.get(reference[0]) if reference else None
        history = actions.get(reference[0], []) if reference else []
        state = effective(states.get(reference[0]), context) if context else dict(revision=0,acked_at=None)
        ended = event.get('lifecycle_state') == 'RESOLVED' or event.get('status') == 'closed'
        # Retired grade members expose shared history, but only the current member accepts ACK.
        can_ack = bool(context and context['active'] and context['current']['id'] == event['id']
            and not ended and not state['acked_at'] and context['anchor_event_id'] in {e['id'] for e in context['members']})
        event['handling'] = dict(state='ACKNOWLEDGED' if state['acked_at'] and not ended else 'PENDING',
            confirmed=bool(state['acked_at']),
            ended=ended, can_ack=can_ack, revision=state['revision'], acked_at=state['acked_at'] if not ended else None,
            latest_ack_at=history[0]['acted_at'] if history else None, actor_kind='local_visitor' if history else None,
            cycle_id=reference[0] if reference else None, grade_code=context['grade_code'] if context else None,
            grade_rank=context['grade_rank'] if context else None, grade_version=GRADE_VERSION,
            grade_token=context['grade_token'] if context else None,
            action_count=counts.get(reference[0],0) if reference else 0, history=history,
            unavailable_reason='LEGACY_OR_UNSUPPORTED_IDENTITY' if not context else
                'EVENT_ENDED' if ended else 'NOT_CURRENT_GRADE' if context['current'] is None or context['current']['id'] != event['id'] else None)
        if event['id'] in protected:
            event.update(deletable=False, deletion_block_reason='ACK_AUDIT_RETAINED')
        event['can_delete_ack_cycle'] = bool(event['id'] in protected and context and
            counts.get(reference[0],0) and all(e.get('lifecycle_state') == 'RESOLVED' and
                e.get('status') == 'closed' and e['id'] not in linked for e in context['members']))
    return events


def validate_ack(value):
    fields = {'event_id','cycle_id','grade_token','grade_version','revision','request_id'}
    if not isinstance(value, dict) or set(value) != fields:
        raise EventRecordError('INVALID_EVENT_ACK')
    # Null identity fields from read-only legacy projections are rejected safely below.
    if (not isinstance(value['event_id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',value['event_id'])
            or type(value['revision']) is not int or not 0 <= value['revision'] <= 2**53-1
            or not isinstance(value['grade_version'],str) or len(value['grade_version']) > 100):
        raise EventRecordError('INVALID_EVENT_ACK')
    for name in ('cycle_id','grade_token'):
        if value[name] is not None and (not isinstance(value[name],str) or not re.fullmatch('[a-f0-9]{64}',value[name])):
            raise EventRecordError('INVALID_EVENT_ACK')
    try:
        if str(uuid.UUID(value['request_id'])) != value['request_id']:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise EventRecordError('INVALID_EVENT_ACK') from None


def acknowledge(db, value, at):
    validate_ack(value)
    request_hash = digest(value)
    duplicate = db.execute('SELECT * FROM event_actions WHERE request_id=?',(value['request_id'],)).fetchone()
    if duplicate:
        if duplicate['request_hash'] != request_hash:
            raise EventRecordError('EVENT_ACK_REQUEST_CONFLICT',409)
        return dict(status='ACK_RECORDED',request_id=duplicate['request_id'],acted_at=duplicate['acted_at'],
            revision=duplicate['handling_revision'])
    events = load_events(db)
    event = next((e for e in events if e['id'] == value['event_id']),None)
    if not event:
        raise EventRecordError('EVENT_NOT_FOUND',404)
    if event.get('lifecycle_state') == 'RESOLVED' or event.get('status') == 'closed':
        raise EventRecordError('EVENT_ACK_NOT_ACTIVE',409)
    reference = cycle_reference(event)
    if not reference:
        raise EventRecordError('EVENT_ACK_UNAVAILABLE',409)
    linked = {r[0] for r in db.execute('SELECT event_id FROM alerts')}
    context = contexts(events,linked)[reference[0]]
    if not context['current'] or context['current']['id'] != event['id']:
        raise EventRecordError('EVENT_ACK_TARGET_NOT_CURRENT',409)
    if not context['active']:
        raise EventRecordError('EVENT_ACK_NOT_ACTIVE',409)
    if context['anchor_event_id'] not in {e['id'] for e in context['members']}:
        raise EventRecordError('EVENT_ACK_UNAVAILABLE',409)
    sync_existing(db)
    row = db.execute('SELECT * FROM event_handling WHERE cycle_id=?',(reference[0],)).fetchone()
    revision = row['revision'] if row else 0
    if (value['cycle_id'] != reference[0] or value['grade_token'] != context['grade_token']
            or value['grade_version'] != GRADE_VERSION or value['revision'] != revision):
        raise EventRecordError('EVENT_ACK_CONFLICT',409)
    if row and row['acked_at']:
        raise EventRecordError('EVENT_ALREADY_ACKNOWLEDGED',409)
    revision += 1
    stamp = at.isoformat()
    db.execute('''INSERT INTO event_handling VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(cycle_id) DO UPDATE SET
        grade_code=excluded.grade_code,grade_rank=excluded.grade_rank,grade_token=excluded.grade_token,
        grade_version=excluded.grade_version,revision=excluded.revision,acked_at=excluded.acked_at''',
        (reference[0],context['anchor_event_id'],context['grade_code'],context['grade_rank'],context['grade_token'],
         GRADE_VERSION,revision,stamp))
    for member in context['members']:
        db.execute('INSERT OR IGNORE INTO event_handling_members VALUES (?,?)',(member['id'],reference[0]))
    db.execute('''INSERT INTO event_actions (request_id,request_hash,cycle_id,event_id,action,acted_at,
        grade_code,grade_rank,grade_version,grade_token,handling_revision,actor_kind,event_snapshot)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',(value['request_id'],request_hash,reference[0],event['id'],'ACK',stamp,
        context['grade_code'],context['grade_rank'],GRADE_VERSION,context['grade_token'],revision,'local_visitor',
        json.dumps(event,ensure_ascii=True,sort_keys=True)))
    return dict(status='ACK_RECORDED',request_id=value['request_id'],acted_at=stamp,revision=revision)
