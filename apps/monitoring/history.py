"""Bounded historical facts and interval statistics; no current diagnosis or I/O."""

from collections import Counter
from datetime import datetime, timedelta, timezone
import json

from .contracts import METRICS, identifier, timestamp, validate_batch, water_metric_facts


HISTORY_VERSION = "management-water-history@1"
MAX_HISTORY_ROWS = 720
MAX_HISTORY_ROW_BYTES = 8192
MAX_HISTORY_ITEMS = 12
MAX_HISTORY_RESULT_BYTES = 24 * 1024
LOOKBACK_MINUTES = (10, 30, 60)


class HistoryQueryError(ValueError):
    """Finite safe error code; never include a row, SQL or exception text."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def utc_query_time(value):
    try:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError()
        return value.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        raise HistoryQueryError("INVALID_HISTORY_QUERY_TIME") from None


def validate_history_query(lookback_minutes, metrics):
    if (type(lookback_minutes) is not int or lookback_minutes not in LOOKBACK_MINUTES
            or type(metrics) not in (list, tuple) or not 1 <= len(metrics) <= len(METRICS)
            or any(type(key) is not str or key not in METRICS for key in metrics)
            or len(set(metrics)) != len(metrics)):
        raise HistoryQueryError("INVALID_WATER_HISTORY_QUERY")
    return tuple(key for key in METRICS if key in metrics)


def history_range(evaluated_at, lookback_minutes):
    end = utc_query_time(evaluated_at)
    try:
        start = end - timedelta(minutes=lookback_minutes)
    except (ValueError, TypeError, OverflowError):
        raise HistoryQueryError("INVALID_HISTORY_QUERY_TIME") from None
    return start, end


def validate_history_range(start, end):
    start, end = utc_query_time(start), utc_query_time(end)
    if (end - start).total_seconds() not in tuple(m * 60 for m in LOOKBACK_MINUTES):
        raise HistoryQueryError("INVALID_HISTORY_QUERY_TIME")
    return start, end


def _validated_row(row, device_id):
    """Reuse ingestion's window/metric validation at the stored receipt time.

    The synthetic envelope exists only to reuse the schema validator. Its session
    placeholder is never projected; unknown session remains None. No ingestion,
    freshness evaluation, rule computation or storage write occurs here.
    """
    try:
        identifier(row["batch_id"])
        session = row["session_id"]
        if session is not None:
            identifier(session)
        if row["device_id"] != device_id or row["channel"] != "water":
            raise ValueError()
        observed, received = timestamp(row["observed_at"]), timestamp(row["received_at"])
        # The indexed text range relies on the UTC representation written by ingestion.
        if row["observed_at"] != observed.isoformat():
            raise ValueError()
        payload = row["payload"]
        if type(payload) is not dict or set(payload) != {"window", "data"} or payload["data"] is None:
            raise ValueError()
        batch = validate_batch({"schema_version": 1, "batch_id": row["batch_id"],
            "device_id": device_id, "session_id": session or "history-validation",
            "sequence": 0, "timestamp": row["observed_at"], "window": payload["window"],
            "water": payload["data"], "visual": None}, now=received, device_ids={device_id})
        begin, end = timestamp(batch["window"]["start"]), timestamp(batch["window"]["end"])
        return {"batch_id": row["batch_id"], "session_id": session,
                "start": begin, "end": end, "received": received,
                "metrics": {m.id: m for m in water_metric_facts(batch["water"])}}
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError, UnicodeError):
        raise HistoryQueryError("HISTORY_RECORD_INVALID") from None


def _union(intervals):
    result = []
    for start, end in sorted(intervals):
        if start >= end:
            continue
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return result


def _seconds(intervals):
    return sum((end - start).total_seconds() for start, end in intervals)


def _complement(intervals, start, end):
    gaps, cursor = [], start
    for left, right in _union(intervals):
        if left > cursor:
            gaps.append((cursor, left))
        cursor = max(cursor, right)
    if cursor < end:
        gaps.append((cursor, end))
    return gaps


def _gap_summary(intervals, reason):
    return {"count": len(intervals), "total_s": _seconds(intervals),
            "omitted_count": max(0, len(intervals) - MAX_HISTORY_ITEMS),
            "items": [{"start": a.isoformat(), "end": b.isoformat(), "reason": reason}
                      for a, b in intervals[:MAX_HISTORY_ITEMS]]}


def _mark_ambiguity(rows):
    """Every member of a transitively overlapping group is excluded, not just the last."""
    group, right = [], None
    for row in rows:
        if group and row["start"] >= right:
            if len(group) > 1:
                for member in group:
                    member["ambiguous"] = True
            group = []
        group.append(row)
        right = max(right, row["end"]) if len(group) > 1 else row["end"]
    if len(group) > 1:
        for member in group:
            member["ambiguous"] = True


def _ref(row):
    return {"batch_id": row["batch_id"], "session_id": row["session_id"],
            "window_start": row["start"].isoformat(), "window_end": row["end"].isoformat(),
            "observed_at": row["end"].isoformat()}


def _value_ref(row, key):
    return {"window_mean": row["metrics"][key].mean, **_ref(row)}


def _extreme(rows, key, operation):
    if not rows:
        return None
    value = operation(row["metrics"][key].mean for row in rows)
    tied = [row for row in rows if row["metrics"][key].mean == value]
    result = {"value": value, "occurrences": len(tied), **_ref(tied[0])}
    if len(tied) > 1:
        result["last_occurrence"] = _ref(tied[-1])
    return result


def _metric_summary(rows, key, start, end):
    facts = [row["metrics"][key] for row in rows]
    reliable = [row for row in rows if not row["ambiguous"] and row["metrics"][key].quality == "valid"]
    intervals = _union((row["start"], row["end"]) for row in reliable)
    return {"unit": METRICS[key][1],
        "quality_counts": {quality: sum(f.quality == quality for f in facts)
                           for quality in ("valid", "partial", "invalid", "missing")},
        # These are declarations across records, not distinct physical samples.
        "valid_samples": sum(f.valid_samples for f in facts),
        "invalid_samples": sum(f.invalid_samples for f in facts),
        "missing_samples": sum(f.sample_count - f.valid_samples - f.invalid_samples for f in facts),
        "sample_count": sum(f.sample_count for f in facts),
        "reliable_valid_samples": sum(row["metrics"][key].valid_samples for row in reliable),
        "reliable_windows": len(reliable), "reliable_window_s": _seconds(intervals),
        "reliable_coverage_ratio": _seconds(intervals) / (end - start).total_seconds(),
        "first": _value_ref(reliable[0], key) if reliable else None,
        "last": _value_ref(reliable[-1], key) if reliable else None,
        "last_minus_first": reliable[-1]["metrics"][key].mean - reliable[0]["metrics"][key].mean if reliable else None,
        "min_window_mean": _extreme(reliable, key, min),
        "max_window_mean": _extreme(reliable, key, max),
        "gaps": _gap_summary(_complement(intervals, start, end), "NO_RELIABLE_METRIC")}


def _details(rows, keys, start, end):
    selected = {}
    for row in rows:
        bucket = min(MAX_HISTORY_ITEMS - 1, int((row["end"] - start) / (end - start) * MAX_HISTORY_ITEMS))
        selected[bucket] = row
    return [{**_ref(row), "received_at": row["received"].isoformat(),
        "ambiguous": row["ambiguous"],
        "metrics": {key: {"window_mean": fact.mean if fact.quality == "valid" and not row["ambiguous"] else None,
            "quality": fact.quality, "valid_samples": fact.valid_samples,
            "sample_count": fact.sample_count, "invalid_samples": fact.invalid_samples}
            for key in keys for fact in (row["metrics"][key],)}} for row in selected.values()]


def _continuity(rows, keys):
    segments, current = [], None
    for row in rows:
        usable = (row["session_id"] is not None and not row["ambiguous"]
                  and all(row["metrics"][key].quality == "valid" for key in keys))
        if not usable:
            current = None
            continue
        if current is None or current["session_id"] != row["session_id"] or current["end"] != row["start"].isoformat():
            current = {"start": row["start"].isoformat(), "end": row["end"].isoformat(),
                       "session_id": row["session_id"], "window_count": 1}
            segments.append(current)
        else:
            current.update(end=row["end"].isoformat(), window_count=current["window_count"] + 1)
    return {"scope": "ALL_REQUESTED_METRICS_RELIABLE", "segment_count": len(segments),
            "segments": segments[:MAX_HISTORY_ITEMS], "omitted_count": max(0, len(segments) - MAX_HISTORY_ITEMS)}


def summarize_water_history(rows, *, device_id, metrics, start, end):
    """Detached JSON-safe facts over all bounded candidates, before display selection."""
    start, end = validate_history_range(start, end)
    keys = validate_history_query(int((end - start).total_seconds() / 60), metrics)
    if len(rows) > MAX_HISTORY_ROWS:
        raise HistoryQueryError("HISTORY_QUERY_BUDGET_EXCEEDED")
    candidates = [_validated_row(row, device_id) for row in rows]
    # A concurrent late arrival cannot become evidence known at an earlier query instant.
    after_query = sum(row["received"] > end for row in candidates)
    candidates = [row for row in candidates if row["received"] <= end and start < row["end"] <= end]
    candidates.sort(key=lambda row: (row["start"], row["end"], row["received"], row["batch_id"]))
    for row in candidates:
        row["ambiguous"] = False
    _mark_ambiguity(candidates)
    received_intervals = _union((max(start, row["start"]), row["end"]) for row in candidates)
    matching = [row for row in candidates if row["start"] >= start]
    # Numeric first/last refer to observation time, regardless of variable window lengths.
    matching.sort(key=lambda row: (row["end"], row["received"], row["batch_id"]))
    stats = {key: _metric_summary(matching, key, start, end) for key in keys}
    times = Counter(row["end"] for row in matching)
    changes = [{"at": row["end"].isoformat(), "from": previous["session_id"], "to": row["session_id"]}
               for previous, row in zip(matching, matching[1:])
               if previous["session_id"] is not None and row["session_id"] is not None
               and previous["session_id"] != row["session_id"]]
    unknown = sum(row["session_id"] is None for row in matching)
    ambiguous = sum(row["ambiguous"] for row in matching)
    duration = (end - start).total_seconds()
    complete = (all(stat["reliable_window_s"] == duration for stat in stats.values())
                and not unknown and not changes and not ambiguous)
    details = _details(matching, keys, start, end)
    limitations = ["NOT_CURRENT_OBSERVATION", "RETENTION_COMPLETENESS_UNKNOWN"]
    for condition, code in (
        (not matching, "NO_MATCHING_WINDOWS"),
        (_seconds(received_intervals) < duration, "INCOMPLETE_TIME_COVERAGE"),
        (any(s["reliable_window_s"] < duration for s in stats.values()), "INCOMPLETE_RELIABLE_COVERAGE"),
        (ambiguous, "AMBIGUOUS_WINDOWS"), (unknown, "UNKNOWN_SESSION"), (changes, "SESSION_CHANGED")):
        if condition:
            limitations.append(code)
    result = {"projection_version": HISTORY_VERSION, "status": "NO_DATA" if not matching else "OK" if complete else "PARTIAL",
        "device_id": device_id, "channel": "water", "source_kind": "simulator", "evaluated_at": end.isoformat(),
        "requested_range": {"start": start.isoformat(), "end": end.isoformat(), "interval": "(start,end]"},
        "aggregation": "window_mean", "query_completed": True, "retention_completeness": "UNKNOWN",
        "counts": {"candidate_windows": len(candidates), "matching_windows": len(matching),
            "boundary_excluded": len(candidates) - len(matching), "after_query_received": after_query,
            "ambiguous_windows": ambiguous, "duplicate_time_windows": sum(n for n in times.values() if n > 1),
            "duplicate_time_groups": sum(n > 1 for n in times.values()), "unknown_session_windows": unknown},
        "coverage": {"received_window_s": _seconds(received_intervals), "requested_s": duration,
                     "received_coverage_ratio": _seconds(received_intervals) / duration},
        "latest_observation_lag_s": (end - max(row["end"] for row in candidates)).total_seconds() if candidates else None,
        "metrics": stats, "has_reliable_history": any(s["reliable_windows"] for s in stats.values()),
        "details": details, "detail_selection": "last_actual_window_per_time_bucket",
        "details_omitted": len(matching) - len(details),
        "gaps": _gap_summary(_complement(received_intervals, start, end), "NO_RETAINED_WINDOW"),
        "sessions": {"known_count": len({row["session_id"] for row in matching if row["session_id"] is not None}),
                     "change_count": len(changes), "changes": changes[:MAX_HISTORY_ITEMS],
                     "omitted_changes": max(0, len(changes) - MAX_HISTORY_ITEMS)},
        "continuity": _continuity(matching, keys),
        "analysis": {"persistent_low_oxygen": "NOT_EVALUATED", "recovery": "NOT_EVALUATED"},
        "limitations": limitations}
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")) > MAX_HISTORY_RESULT_BYTES:
        raise HistoryQueryError("HISTORY_RESULT_TOO_LARGE")
    return result
