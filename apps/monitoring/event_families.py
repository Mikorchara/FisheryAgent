"""Water risk associations only. Preserve code episodes and diagnosis thresholds."""

from copy import deepcopy
from dataclasses import asdict, replace
import json

from .contracts import FindingState


FAMILIES = {
    'OXYGEN_LOW': ('dissolved_oxygen_mg_l:low', '溶解氧偏低风险', 'dissolved_oxygen_mg_l', 1),
    'OXYGEN_CRITICAL_LOW': ('dissolved_oxygen_mg_l:low', '溶解氧偏低风险', 'dissolved_oxygen_mg_l', 2),
    'OXYGEN_CRITICAL_EXTREME': ('dissolved_oxygen_mg_l:low', '溶解氧偏低风险', 'dissolved_oxygen_mg_l', 3),
}
for prefix, metric, label in (('TEMP', 'temperature_c', '水温'), ('PH', 'ph', 'pH')):
    for direction, text in (('LOW', '偏低'), ('HIGH', '偏高')):
        for critical in (False, True):
            FAMILIES[prefix + ('_CRITICAL_' if critical else '_') + direction] = (
                metric + ':' + direction.lower(), label + text + '风险', metric, 2 if critical else 1)


def family_group(event):
    definition = FAMILIES.get(event.get('code')) if event.get('channel') == 'water' else None
    if not definition:
        return None
    rule = deepcopy(event.get('rule_identity') or {'version': event.get('rule_version')})
    rule.pop('rule_id', None)
    return (event['device_id'], definition[0], json.dumps(rule, sort_keys=True))


def associate_water_changes(existing, changes, batch, assessment):
    """Mirror bounded change evidence to members in the same write transaction."""
    if assessment.channel != 'water':
        return changes
    events = {e['id']: deepcopy(e) for e in existing.values()}
    events.update((e['id'], deepcopy(e)) for e in (*changes.updates, *changes.inserts))
    groups = {}
    for event in events.values():
        key = family_group(event)
        if key and not event.get('superseded_by'):
            groups.setdefault(key, []).append(event)
    for members in groups.values():
        first = min(members, key=lambda e: (e['occurred_at'], e['id']))
        definition = FAMILIES[first['code']]
        previous = max((e.get('risk_family', {}) for e in members),
            key=lambda f: (f.get('last_transition_at', ''), len(f.get('transitions', []))))
        family = deepcopy(previous) if previous else dict(key=definition[0], label=definition[1],
            metric=definition[2], episode_id=first['id'], transitions=[], omitted_transitions=0)
        finding = next((f for f in assessment.findings if f.code in {e['code'] for e in members}
            and f.state == FindingState.HIT), None)
        resolved = all(e.get('lifecycle_state') == 'RESOLVED' for e in members)
        marker = finding.code if finding else 'CLEAR' if resolved else None
        if marker and (not family['transitions'] or family['transitions'][-1]['code'] != marker):
            ref = assessment.observation
            member = next((e for e in members if e['code'] == marker), first)
            family['transitions'].append(dict(code=marker, event_id=member['id'],
                title=finding.message if finding else '规则条件已消退', severity=finding.severity if finding else None,
                observed_at=ref.observed_at, batch_id=ref.batch_id, session_id=batch['session_id'],
                sequence=batch['sequence'], observation=asdict(ref),
                metric=deepcopy(batch['water']['metrics'][definition[2]])))
            family['last_transition_at'] = ref.observed_at
            # Keep the first transition and the latest 99; disclose omitted intermediate changes.
            if len(family['transitions']) > 100:
                family['omitted_transitions'] += len(family['transitions']) - 100
                family['transitions'] = family['transitions'][:1] + family['transitions'][-99:]
        for event in members:
            event['risk_family'] = deepcopy(family)
    insert_ids = {e['id'] for e in changes.inserts}
    return replace(changes, inserts=tuple(events[e['id']] for e in changes.inserts),
        updates=tuple(e for e in events.values() if e['id'] not in insert_ids))


def project_families(events):
    """Group stored associations; infer only overlapping unresolved legacy members, read-only."""
    result = deepcopy(events)
    legacy = {}
    for event in result:
        key = family_group(event)
        if key and not event.get('risk_family') and event.get('status') != 'closed' and not event.get('superseded_by'):
            legacy.setdefault(key, []).append(event)
    for members in legacy.values():
        first = min(members, key=lambda e: (e.get('occurred_at', ''), e['id']))
        definition = FAMILIES[first['code']]
        for event in members:
            event['risk_family'] = dict(key=definition[0], label=definition[1], metric=definition[2],
                episode_id='legacy-' + first['id'], transitions=[], inferred=True)
    groups = {}
    for event in result:
        if event.get('risk_family'):
            groups.setdefault((event['device_id'], event['risk_family']['episode_id']), []).append(event)
    for members in groups.values():
        current = next((e for e in members if e.get('lifecycle_state') == 'ACTIVE' and not e.get('superseded_by')), None)
        for event in members:
            event['family_current_code'] = current['code'] if current else None
            event['family_current_event_id'] = current['id'] if current else None
            event['family_members'] = [{k: e.get(k) for k in ('id', 'code', 'title', 'severity',
                'lifecycle_state', 'state_reason', 'status', 'channel', 'source_kind',
                'occurred_at', 'last_observed_at', 'batch_id', 'resolved_at')} for e in members]
    return result
