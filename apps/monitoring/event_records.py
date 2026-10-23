"""Event record query/deletion contracts; no Web, database or risk thresholds."""

from datetime import datetime, timedelta
import re


class EventRecordError(ValueError):
    def __init__(self, code, status=400):
        super().__init__(code)
        self.code, self.status = code, status


def deletable(event, linked=False, referenced=False, audited=False):
    if linked or referenced or audited or event.get('status') != 'closed':
        return False
    end = parse_time(event.get('resolved_at'))
    if event.get('lifecycle_state') == 'RESOLVED':
        return end is not None
    if not legacy_closed_record(event):
        return False
    # An old recorded closure permits cleanup, never a new recovery assertion.
    # Missing, naive or contradictory historical timestamps remain protected.
    start = parse_time(event.get('occurred_at'))
    last = parse_time(event.get('last_observed_at'))
    return bool(start and end and start <= end and (
        event.get('last_observed_at') is None or last and start <= last <= end))


def legacy_closed_record(event):
    """Use stored structure, never a UI flag, to identify an old recorded closure."""
    return 'lifecycle_state' not in event and event.get('status') == 'closed'


def parse_time(value):
    try:
        result = datetime.fromisoformat(value)
        return result if result.utcoffset() is not None else None
    except (TypeError, ValueError):
        return None


def validate_delete(scope, event_id):
    if scope not in ('single', 'all_resolved', 'ack_cycle') or (scope == 'all_resolved' and event_id is not None) or (
            scope in ('single', 'ack_cycle') and (not isinstance(event_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', event_id))):
        raise EventRecordError('INVALID_EVENT_DELETE')


def query_records(events, *, now, lookback_minutes=None, q='', severity='', status='', limit=50, offset=0):
    if (lookback_minutes not in (None, 5, 10, 30, 60) or lookback_minutes is not None and type(lookback_minutes) is not int
            or not isinstance(q, str) or len(q) > 128 or severity not in ('', 'critical', 'warning', 'info')
            or status not in ('', 'ACTIVE', 'INDETERMINATE', 'RESOLVED', 'pending', 'closed')
            or type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0):
        raise EventRecordError('INVALID_EVENT_FILTER')
    cutoff = now - timedelta(minutes=lookback_minutes) if lookback_minutes else None
    result = []
    for event in events:
        if q.strip().casefold() not in (' '.join(str(event.get(k, '')) for k in ('title', 'device', 'code'))+' '+event.get('cycle_summary', {}).get('search_text','')).casefold():
            continue
        if severity and event.get('severity') != severity or status and status not in (event.get('status'), event.get('lifecycle_state')):
            continue
        if cutoff:
            start = parse_time(event.get('occurred_at'))
            closed = event.get('lifecycle_state') == 'RESOLVED' or event.get('status') == 'closed'
            end = parse_time(event.get('resolved_at')) if closed else None
            if start is None or start > now or closed and (end is None or end < cutoff):
                continue
        result.append(event)
    return dict(items=result[offset:offset+limit], total=len(result), offset=offset, limit=limit,
        evaluated_at=now.isoformat(), time_basis='attention_interval_overlap')
