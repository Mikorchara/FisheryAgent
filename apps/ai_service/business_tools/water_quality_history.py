"""Offline candidate Tool; Monitoring owns the time query and all statistics."""
import json
import math

from apps.ai_backend.model_gateway import ModelToolDefinition
from apps.monitoring.contracts import METRICS, identifier, timestamp
from apps.monitoring.history import (HISTORY_VERSION, LOOKBACK_MINUTES, MAX_HISTORY_ROWS,
    MAX_HISTORY_ITEMS, MAX_HISTORY_RESULT_BYTES, validate_history_query)


WATER_QUALITY_HISTORY = "get_water_quality_history"
HISTORY_DEFINITION = ModelToolDefinition(
    WATER_QUALITY_HISTORY,
    "只读查询本轮绑定设备最近10、30或60分钟已留存的历史水质窗口，可选择温度、pH、溶解氧。"
    "用于回顾历史变化、窗口均值极值、数据质量及覆盖缺口；返回全部合格记录的基础统计和有限代表明细。"
    "数值是历史窗口有效样本均值，不是瞬时采样或当前观测。NO_DATA表示查询完成但无完整匹配窗口；"
    "PARTIAL表示覆盖、质量、Session或重叠歧义存在限制，不代表正常。"
    "不判断持续低氧、恢复、设备离线原因，不负责评分或知识检索。"
    "历史末值不能证明当前状态；需要当前事实时使用当前水质查询工具。",
    {"type": "object", "properties": {
        "lookback_minutes": {"type": "integer", "enum": list(LOOKBACK_MINUTES)},
        "metrics": {"type": "array", "items": {"type": "string", "enum": list(METRICS)},
                    "minItems": 1, "maxItems": 3, "uniqueItems": True}},
     "required": ["lookback_minutes"], "additionalProperties": False})


def validate_arguments(arguments):
    if (type(arguments) is not dict or "lookback_minutes" not in arguments
            or set(arguments) - {"lookback_minutes", "metrics"}
            or "metrics" in arguments and type(arguments["metrics"]) is not list):
        raise ValueError("invalid history arguments")
    metrics = validate_history_query(arguments["lookback_minutes"], arguments.get("metrics", list(METRICS)))
    return {"lookback_minutes": arguments["lookback_minutes"], "metrics": list(metrics)}


def history_payload(arguments, *, monitoring, device_id):
    """Exactly one bounded read; device is injected by the server, never the model."""
    return monitoring.query_water_history(device_id, **arguments)


def result_metadata(payload):
    """Validate finite evidence metadata, without recomputing Monitoring statistics.

    Used only after a real backend execution, for receipts and safe Activity.
    Invalid/mismatched DTOs fail closed. Values, details and raw arguments are
    never returned from this projection.
    """
    def count(value, maximum=MAX_HISTORY_ROWS):
        return type(value) is int and 0 <= value <= maximum

    def number(value, maximum):
        return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= maximum

    try:
        if (type(payload) is not dict or payload.get("projection_version") != HISTORY_VERSION
                or payload.get("status") not in ("OK", "PARTIAL", "NO_DATA")
                or payload.get("query_completed") is not True or payload.get("channel") != "water"
                or payload.get("source_kind") != "simulator" or payload.get("aggregation") != "window_mean"
                or payload.get("retention_completeness") != "UNKNOWN"
                or payload.get("analysis") != {"persistent_low_oxygen": "NOT_EVALUATED", "recovery": "NOT_EVALUATED"}
                or len(json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")) > MAX_HISTORY_RESULT_BYTES):
            return None
        identifier(payload["device_id"])
        period = payload["requested_range"]
        start, end, evaluated = timestamp(period["start"]), timestamp(period["end"]), timestamp(payload["evaluated_at"])
        duration = (end - start).total_seconds()
        if period.get("interval") != "(start,end]" or end != evaluated or duration not in tuple(m * 60 for m in LOOKBACK_MINUTES):
            return None
        counts, coverage = payload["counts"], payload["coverage"]
        if (any(not count(counts[key]) for key in ("candidate_windows", "matching_windows", "boundary_excluded",
                "after_query_received", "ambiguous_windows", "unknown_session_windows"))
                or counts["candidate_windows"] != counts["matching_windows"] + counts["boundary_excluded"]
                or counts["candidate_windows"] + counts["after_query_received"] > MAX_HISTORY_ROWS
                or counts["ambiguous_windows"] > counts["matching_windows"]
                or counts["unknown_session_windows"] > counts["matching_windows"]
                or coverage["requested_s"] != duration or not number(coverage["received_window_s"], duration)
                or not number(coverage["received_coverage_ratio"], 1)
                or abs(coverage["received_coverage_ratio"] - coverage["received_window_s"] / duration) > 1e-9):
            return None
        metrics = payload["metrics"]
        if type(metrics) is not dict or not 1 <= len(metrics) <= 3 or any(key not in METRICS for key in metrics):
            return None
        reliable = []
        for key in METRICS:
            if key not in metrics:
                continue
            stat = metrics[key]
            quality = stat["quality_counts"]
            if (set(quality) != {"valid", "partial", "invalid", "missing"}
                    or any(not count(value, counts["matching_windows"]) for value in quality.values())
                    or sum(quality.values()) != counts["matching_windows"]
                    or stat["unit"] != METRICS[key][1]
                    or not count(stat["reliable_windows"], quality["valid"])
                    or stat["reliable_windows"] > counts["matching_windows"] - counts["ambiguous_windows"]
                    or not number(stat["reliable_window_s"], coverage["received_window_s"])
                    or not number(stat["reliable_coverage_ratio"], 1)
                    or abs(stat["reliable_coverage_ratio"] - stat["reliable_window_s"] / duration) > 1e-9
                    or any(not count(stat[field], 600 * counts["matching_windows"])
                           for field in ("valid_samples", "invalid_samples", "missing_samples", "sample_count", "reliable_valid_samples"))
                    or stat["valid_samples"] + stat["invalid_samples"] + stat["missing_samples"] != stat["sample_count"]
                    or stat["sample_count"] < counts["matching_windows"]
                    or not stat["reliable_windows"] <= stat["reliable_valid_samples"] <= stat["valid_samples"]):
                return None
            if stat["reliable_windows"]:
                if (stat["reliable_window_s"] <= 0 or type(stat["last_minus_first"]) not in (int, float)
                        or not math.isfinite(stat["last_minus_first"])):
                    return None
                for field in ("first", "last", "min_window_mean", "max_window_mean"):
                    ref = stat[field]
                    identifier(ref["batch_id"])
                    if ref["session_id"] is not None:
                        identifier(ref["session_id"])
                    a, b = timestamp(ref["window_start"]), timestamp(ref["window_end"])
                    value = ref["value" if field.endswith("window_mean") else "window_mean"]
                    if (not start <= a < b <= end or timestamp(ref["observed_at"]) != b
                            or type(value) not in (int, float) or not math.isfinite(value)
                            or not METRICS[key][2] <= value <= METRICS[key][3]):
                        return None
            elif (stat["reliable_window_s"] != 0 or stat["reliable_valid_samples"] != 0
                    or any(stat[field] is not None for field in ("first", "last", "last_minus_first", "min_window_mean", "max_window_mean"))):
                return None
            reliable.append((key, stat["reliable_windows"]))
        has_data = any(value for _, value in reliable)
        if (type(payload.get("has_reliable_history")) is not bool or payload["has_reliable_history"] != has_data
                or type(payload.get("details")) is not list or len(payload["details"]) > MAX_HISTORY_ITEMS
                or not count(payload.get("details_omitted"))
                or len(payload["details"]) + payload["details_omitted"] != counts["matching_windows"]
                or (payload["status"] == "NO_DATA") != (counts["matching_windows"] == 0)):
            return None
        if payload["status"] == "OK" and (not has_data or counts["ambiguous_windows"]
                or counts["unknown_session_windows"] or payload["sessions"]["change_count"] != 0
                or any(metrics[key]["reliable_window_s"] != duration for key in metrics)):
            return None
        return {"history_query_completed": True, "history_range_start": start.isoformat(),
            "history_range_end": end.isoformat(), "evaluated_at": evaluated.isoformat(),
            "history_window_count": counts["matching_windows"], "history_reliable_windows": tuple(reliable)}
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError, UnicodeError, AttributeError):
        return None
