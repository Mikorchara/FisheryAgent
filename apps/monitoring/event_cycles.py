"""Read-only risk-cycle summaries. Original event IDs and write contracts are unchanged."""
from copy import deepcopy

from .event_handling import cycle_reference, RANKS

OXYGEN_NAMES = {'OXYGEN_LOW': '溶解氧偏低', 'OXYGEN_CRITICAL_LOW': '溶解氧低',
                'OXYGEN_CRITICAL_EXTREME': '溶解氧极低'}


def summarize_cycles(events):
    groups = {}
    for event in events:
        reference = cycle_reference(event)
        key = reference[0] if reference else 'event:' + event['id']
        groups.setdefault(key, []).append(event)
    result = []
    for key, members in groups.items():
        rank = lambda e: (RANKS.get(e.get('code'), 0), e.get('last_observed_at', ''), e['id'])
        ongoing = [e for e in members if e.get('status') != 'closed' and e.get('lifecycle_state') != 'RESOLVED']
        reliable = [e for e in ongoing if e.get('lifecycle_state') == 'ACTIVE' and not e.get('superseded_by')]
        peak = max(members, key=rank)
        selected = max(reliable, key=rank) if reliable else max(ongoing, key=lambda e: (e.get('last_observed_at', ''), e['id'])) if ongoing else peak
        item = deepcopy(selected)
        transitions = (selected.get('risk_family') or {}).get('transitions', []) if cycle_reference(selected) else []
        retained_grades = [t for t in transitions if t.get('code') in RANKS and t.get('severity')]
        peak_grade = max([peak, *retained_grades], key=lambda e: RANKS.get(e.get('code'), 0))
        ended = not ongoing
        state = 'ACTIVE' if reliable else 'INDETERMINATE' if ongoing else 'RESOLVED' if all(e.get('lifecycle_state') == 'RESOLVED' for e in members) else 'INDETERMINATE'
        item.update(occurred_at=min([e['occurred_at'] for e in members]+[t['observed_at'] for t in retained_grades if t.get('observed_at')]),
                    last_observed_at=max(e.get('last_observed_at') or e['occurred_at'] for e in members),
                    lifecycle_state=state, status='closed' if ended else 'pending',
                    resolved_at=max((e.get('resolved_at') or '' for e in members), default='') if ended else None)
        family = selected.get('risk_family') or {}
        label = family.get('label') if cycle_reference(selected) else None
        item['title'] = label or selected['title'].split(' (')[0]
        if selected.get('code') in OXYGEN_NAMES:
            item['title'] = OXYGEN_NAMES[peak_grade['code']] if ended else OXYGEN_NAMES[selected['code']] if reliable else '溶解氧异常（等级待核实）'
        item['severity'] = peak_grade['severity'] if ended else selected['severity'] if reliable else 'unknown'
        item['cycle_summary'] = dict(key=key, member_ids=[e['id'] for e in members], count=len(members),
            detail_event_id=selected['id'], ended=ended, peak_severity=peak_grade['severity'],
            peak_code=peak_grade.get('code'), reading_label='异常时读数' if ended else '最新异常观测' if reliable else '历史异常观测（当前等级待核实）',
            reading=selected['title'], latest_observed_at=selected.get('last_observed_at'),
            search_text=' '.join(str(e.get(k,'')) for e in members for k in ('title','device','code','id')))
        # A summary is not an original record and never grants deletion of a cycle.
        item['deletable'] = False
        result.append(item)
    return sorted(result, key=lambda e: (e['occurred_at'], e['id']), reverse=True)
