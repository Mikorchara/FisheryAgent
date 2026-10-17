"""Offline historical query contracts; all SQLite content is isolated test data."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from apps.monitoring.contracts import METRICS
from apps.monitoring.history import (HistoryQueryError, MAX_HISTORY_RESULT_BYTES,
    MAX_HISTORY_ROWS, summarize_water_history)
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService


DO = "dissolved_oxygen_mg_l"


class WaterHistoryTests(unittest.TestCase):
    def setUp(self):
        for name in ("connect", "connect_ex", "sendto"):
            guard = patch.object(socket.socket, name, side_effect=AssertionError("network forbidden"))
            guard.start()
            self.addCleanup(guard.stop)
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = MonitoringRepository(Path(temporary.name) / "history.sqlite3", history_limit=1000)
        self.now = datetime(2026, 10, 17, 0, 5, tzinfo=timezone.utc)
        self.service = MonitoringService(self.repo, device_names={"pond-a": "A", "pond-b": "B"}, clock=lambda: self.now)
        self.counter = 0

    def batch(self, end=None, *, duration=10, session="session-a", device="pond-a", value=6.4, metrics=None):
        end = self.now if end is None else end
        self.counter += 1
        stats = {key: {"unit": unit, "mean": val, "min": val, "max": val, "latest": val,
                       "valid_samples": 10, "invalid_samples": 0}
                 for (key, (_label, unit, _lo, _hi)), val in zip(METRICS.items(), (28, 7.5, value))}
        for key, override in (metrics or {}).items():
            stats[key].update(override)
        return {"schema_version": 1, "batch_id": "batch-" + str(self.counter), "device_id": device,
            "session_id": session, "sequence": self.counter, "timestamp": end.isoformat(),
            "window": {"start": (end - timedelta(seconds=duration)).isoformat(), "end": end.isoformat(), "duration_s": duration},
            "water": {"aggregation": "window_mean", "sample_count": 10, "metrics": stats}, "visual": None}

    def insert(self, batch, *, session_missing=False, received=None):
        """Fast valid storage fixtures, including old/out-of-order rows; no real DB."""
        observed = datetime.fromisoformat(batch["timestamp"]).astimezone(timezone.utc).isoformat()
        payload = {"window": batch["window"], "data": batch["water"]}
        with self.repo.connection() as db:
            if not session_missing:
                db.execute("INSERT INTO batches VALUES(?,?,?,?,?,?)", (batch["batch_id"], batch["device_id"],
                    batch["session_id"], batch["sequence"], "fixture-digest", received or observed))
            db.execute("INSERT INTO history VALUES(?,?,?,?,?,?)", (batch["batch_id"], batch["device_id"], "water",
                observed, received or observed, json.dumps(payload, allow_nan=False)))

    def query(self, **kwargs):
        return self.service.query_water_history("pond-a", lookback_minutes=kwargs.pop("lookback_minutes", 10),
                                               metrics=kwargs.pop("metrics", [DO]), **kwargs)

    def assert_error(self, code, operation):
        with self.assertRaises(HistoryQueryError) as error:
            operation()
        self.assertEqual(error.exception.code, code)
        self.assertEqual(str(error.exception), code)

    def test_supported_real_time_ranges_boundaries_and_device_isolation(self):
        for minutes in (10, 30, 60):
            with self.subTest(minutes=minutes):
                start = self.now - timedelta(minutes=minutes)
                self.insert(self.batch(start))  # End exactly at the open boundary.
                crossing = self.batch(start + timedelta(seconds=5))
                first = self.batch(start + timedelta(seconds=10), value=2.2)
                last = self.batch(self.now)
                self.insert(crossing); self.insert(first); self.insert(last)
                self.insert(self.batch(self.now, device="pond-b"))
                result = self.query(lookback_minutes=minutes)
                self.assertEqual(result["requested_range"]["start"], start.isoformat())
                self.assertEqual(result["requested_range"]["end"], self.now.isoformat())
                self.assertGreaterEqual(result["counts"]["boundary_excluded"], 1)
                self.assertTrue(all(start <= datetime.fromisoformat(d["window_start"]) for d in result["details"]))
                self.assertTrue(all(d["batch_id"] != crossing["batch_id"] for d in result["details"]))

    def test_clock_is_taken_once_and_offset_clock_crosses_utc_midnight(self):
        self.insert(self.batch(self.now))
        clock = lambda: self.now.astimezone(timezone(timedelta(hours=8)))
        with patch.object(self.service, "clock", wraps=clock) as called:
            result = self.query()
        self.assertEqual(called.call_count, 1)
        self.assertEqual(result["evaluated_at"], "2026-10-17T00:05:00+00:00")
        self.assertEqual(result["requested_range"]["start"], "2026-10-16T23:55:00+00:00")

    def test_offset_windows_are_normalized_by_ingestion_before_indexed_query(self):
        offset = self.now.astimezone(timezone(timedelta(hours=8)))
        batch = self.batch(offset)
        self.service.ingest(batch)
        result = self.query()
        self.assertEqual(result["counts"]["matching_windows"], 1)
        self.assertEqual(result["details"][0]["observed_at"], self.now.isoformat())
        self.assertEqual(result["details"][0]["window_start"], (self.now-timedelta(seconds=10)).isoformat())

    def test_subsecond_range_includes_exact_end_and_excludes_future_and_open_start(self):
        self.now = self.now.replace(microsecond=125000)
        start = self.now-timedelta(minutes=10)
        self.insert(self.batch(start))
        self.insert(self.batch(self.now))
        self.insert(self.batch(self.now+timedelta(microseconds=1)))
        result = self.query()
        self.assertEqual(result["counts"]["matching_windows"], 1)
        self.assertEqual(result["metrics"][DO]["last"]["observed_at"], self.now.isoformat())

    def test_old_retained_rows_do_not_consume_the_requested_range_budget(self):
        old = self.now-timedelta(hours=2)
        batch = self.batch(old, duration=1)
        payload = json.dumps({"window": batch["window"], "data": batch["water"]})
        with self.repo.connection() as db:
            db.executemany("INSERT INTO history VALUES(?,?,?,?,?,?)", [
                ("outside-"+str(i), "pond-a", "water", old.isoformat(), old.isoformat(), payload)
                for i in range(721)])
        self.insert(self.batch())
        self.assertEqual(self.query()["counts"]["matching_windows"], 1)

    def test_metrics_are_restricted_and_canonicalized(self):
        result = self.query(metrics=[DO, "temperature_c"])
        self.assertEqual(list(result["metrics"]), ["temperature_c", DO])
        self.assertEqual(list(self.service.query_water_history("pond-a", lookback_minutes=10)["metrics"]), list(METRICS))
        for metrics in (None, [], "ph", [DO, DO], ["unknown"], [True], [None], [[DO]], {DO}):
            with self.subTest(metrics=metrics):
                self.assert_error("INVALID_WATER_HISTORY_QUERY", lambda: self.query(metrics=metrics))

    def test_invalid_lookback_and_clock_reject_before_repository(self):
        with patch.object(self.repo, "query_water_history", side_effect=AssertionError("must not read")):
            for minutes in (True, False, 30.0, "30", None, 0, -1, 11, 61):
                self.assert_error("INVALID_WATER_HISTORY_QUERY", lambda: self.query(lookback_minutes=minutes))
            for clock in (None, "2026-10-17", datetime(2026, 10, 17), datetime.min.replace(tzinfo=timezone.utc)):
                with patch.object(self.service, "clock", return_value=clock):
                    self.assert_error("INVALID_HISTORY_QUERY_TIME", self.query)

    def test_unknown_device_and_invalid_repository_time_range(self):
        with self.assertRaisesRegex(ValueError, "UNKNOWN_MONITORING_DEVICE"):
            self.service.query_water_history("unknown", lookback_minutes=10)
        self.assert_error("INVALID_HISTORY_QUERY_TIME", lambda: self.repo.query_water_history(
            "pond-a", start=self.now, end=self.now))
        self.assertEqual(self.repo.query_water_history("' OR 1=1 --", start=self.now-timedelta(minutes=10), end=self.now), [])

    def test_no_data_is_completed_not_zero_or_current(self):
        result = self.query()
        self.assertEqual(result["status"], "NO_DATA")
        self.assertTrue(result["query_completed"])
        self.assertFalse(result["has_reliable_history"])
        self.assertIsNone(result["metrics"][DO]["first"])
        self.assertIsNone(result["metrics"][DO]["last_minus_first"])
        self.assertIsNone(result["latest_observation_lag_s"])
        self.assertEqual(result["gaps"]["total_s"], 600)
        self.assertEqual(result["gaps"]["items"][0]["reason"], "NO_RETAINED_WINDOW")
        self.assertNotIn("freshness", result)
        self.assertNotIn("connectivity", result)
        self.assertNotIn("water_quality", result)

    def test_complete_reliable_range_is_ok_even_without_retention_watermark(self):
        for i in range(10):
            self.insert(self.batch(self.now - timedelta(seconds=(9-i)*60), duration=60, value=i))
        result = self.query()
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["retention_completeness"], "UNKNOWN")
        self.assertEqual(result["coverage"]["received_coverage_ratio"], 1)
        self.assertEqual(result["metrics"][DO]["reliable_coverage_ratio"], 1)
        self.assertEqual(result["metrics"][DO]["first"]["window_mean"], 0)
        self.assertEqual(result["metrics"][DO]["last_minus_first"], 9)
        self.assertEqual(result["continuity"]["segment_count"], 1)

    def test_quality_counts_samples_and_numeric_statistics_do_not_fill_or_average(self):
        overrides = [None, {"valid_samples": 5}, {"valid_samples": 9, "invalid_samples": 1},
                     {"valid_samples": 0, "mean": None, "min": None, "max": None, "latest": None}]
        for index, override in enumerate(overrides):
            self.insert(self.batch(self.now - timedelta(seconds=(3-index)*10), value=2.2 + index,
                                   metrics={DO: override} if override else None))
        result = self.query()
        metric = result["metrics"][DO]
        self.assertEqual(metric["quality_counts"], dict(valid=1, partial=1, invalid=1, missing=1))
        self.assertEqual((metric["valid_samples"], metric["invalid_samples"], metric["missing_samples"], metric["sample_count"]), (24, 1, 15, 40))
        self.assertEqual(metric["reliable_valid_samples"], 10)
        self.assertEqual(metric["min_window_mean"]["value"], 2.2)
        self.assertEqual(metric["last_minus_first"], 0)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertFalse(any(d["metrics"][DO]["window_mean"] is not None and d["metrics"][DO]["quality"] != "valid"
                             for d in result["details"]))

    def test_all_unreliable_records_are_partial_not_no_data(self):
        self.insert(self.batch(metrics={DO: {"valid_samples": 0, "mean": None, "min": None, "max": None, "latest": None}}))
        result = self.query()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertFalse(result["has_reliable_history"])
        self.assertIsNone(result["metrics"][DO]["min_window_mean"])
        self.assertEqual(result["coverage"]["received_window_s"], 10)
        self.assertEqual(result["metrics"][DO]["reliable_window_s"], 0)

    def test_unselected_invalid_metric_does_not_discard_valid_do(self):
        self.insert(self.batch(metrics={"ph": {"valid_samples": 0, "invalid_samples": 10,
                                               "mean": None, "min": None, "max": None, "latest": None}}))
        self.assertEqual(self.query()["metrics"][DO]["reliable_windows"], 1)

    def test_minimum_is_window_mean_with_independent_extreme_references_and_ties(self):
        batches = []
        for i in range(60):
            batch = self.batch(self.now - timedelta(seconds=(59-i)*10), value=2.2 if i in (1, 2) else 6.4)
            batches.append(batch); self.insert(batch)
        result = self.query()
        extreme = result["metrics"][DO]["min_window_mean"]
        self.assertEqual(extreme["value"], 2.2)
        self.assertEqual(extreme["occurrences"], 2)
        self.assertEqual(extreme["batch_id"], batches[1]["batch_id"])
        self.assertEqual(extreme["last_occurrence"]["batch_id"], batches[2]["batch_id"])
        self.assertNotIn(extreme["batch_id"], [d["batch_id"] for d in result["details"]])
        self.assertIn("window_start", extreme)
        self.assertEqual(len(result["details"]), 12)
        self.assertEqual(result["details_omitted"], 48)
        self.assertEqual(result["metrics"][DO]["valid_samples"], 600)

    def test_sample_minimum_is_not_mislabeled_as_lowest_window_mean(self):
        self.insert(self.batch(self.now-timedelta(seconds=10), value=3.2, metrics={DO: {"min": .4}}))
        self.insert(self.batch(self.now, value=2.2, metrics={DO: {"min": 1.1}}))
        extreme = self.query()["metrics"][DO]["min_window_mean"]
        self.assertEqual(extreme["value"], 2.2)
        self.assertEqual(extreme["observed_at"], self.now.isoformat())

    def test_old_valid_history_is_usable_history_without_becoming_current(self):
        self.insert(self.batch(self.now-timedelta(minutes=20), value=2.2))
        result = self.query(lookback_minutes=30)
        self.assertTrue(result["has_reliable_history"])
        self.assertEqual(result["metrics"][DO]["quality_counts"]["valid"], 1)
        self.assertEqual(result["latest_observation_lag_s"], 1200)
        self.assertNotIn("freshness", json.dumps(result))
        self.assertIn("NOT_CURRENT_OBSERVATION", result["limitations"])

    def test_variable_windows_and_boundary_coverage_do_not_scale_mean(self):
        start = self.now-timedelta(minutes=10)
        self.insert(self.batch(start+timedelta(seconds=5), duration=10, value=1))
        self.insert(self.batch(start+timedelta(seconds=25), duration=20, value=7))
        result = self.query()
        self.assertEqual(result["counts"]["boundary_excluded"], 1)
        self.assertEqual(result["coverage"]["received_window_s"], 25)
        self.assertEqual(result["metrics"][DO]["reliable_window_s"], 20)
        self.assertEqual(result["metrics"][DO]["min_window_mean"]["value"], 7)
        self.assertEqual(result["gaps"]["total_s"], 575)

    def test_boundary_only_record_is_no_matching_data_but_retains_coverage_fact(self):
        self.insert(self.batch(self.now-timedelta(minutes=10)+timedelta(seconds=5)))
        result = self.query()
        self.assertEqual(result["status"], "NO_DATA")
        self.assertEqual(result["counts"]["candidate_windows"], 1)
        self.assertEqual(result["coverage"]["received_window_s"], 5)
        self.assertIsNone(result["metrics"][DO]["first"])

    def test_overlap_transitive_group_and_duplicate_instants_are_excluded_from_reliable_stats(self):
        for seconds, duration in ((-40, 20), (-30, 20), (-15, 20), (-15, 20), (0, 10)):
            self.insert(self.batch(self.now+timedelta(seconds=seconds), duration=duration))
        result = self.query()
        self.assertEqual(result["counts"]["ambiguous_windows"], 4)
        self.assertEqual(result["counts"]["duplicate_time_windows"], 2)
        self.assertEqual(result["counts"]["duplicate_time_groups"], 1)
        self.assertEqual(result["coverage"]["received_window_s"], 55)
        self.assertEqual(result["metrics"][DO]["reliable_window_s"], 10)
        self.assertEqual(result["metrics"][DO]["reliable_windows"], 1)

    def test_latest_time_uses_observation_end_not_variable_window_start_order(self):
        self.insert(self.batch(duration=60))
        self.insert(self.batch(self.now-timedelta(seconds=10), duration=10))
        result = self.query()
        self.assertEqual(result["latest_observation_lag_s"], 0)
        self.assertEqual(result["counts"]["ambiguous_windows"], 2)
        self.assertEqual(result["metrics"][DO]["reliable_windows"], 0)

    def test_boundary_overlap_excludes_the_complete_window_from_reliable_stats(self):
        start = self.now-timedelta(minutes=10)
        self.insert(self.batch(start+timedelta(seconds=5), duration=10))
        self.insert(self.batch(start+timedelta(seconds=10), duration=10))
        result = self.query()
        self.assertEqual(result["counts"]["boundary_excluded"], 1)
        self.assertEqual(result["counts"]["ambiguous_windows"], 1)
        self.assertEqual(result["metrics"][DO]["reliable_windows"], 0)
        self.assertEqual(result["coverage"]["received_window_s"], 10)

    def test_out_of_order_storage_is_deterministic_and_overlapping_rows_never_recover(self):
        first = self.batch(self.now-timedelta(seconds=10), value=2.2)
        second = self.batch(self.now, value=6.4)
        self.insert(second); self.insert(first)
        rows = self.repo.query_water_history("pond-a", start=self.now-timedelta(minutes=10), end=self.now)
        original = deepcopy(rows)
        a = summarize_water_history(rows, device_id="pond-a", metrics=[DO], start=self.now-timedelta(minutes=10), end=self.now)
        b = summarize_water_history(list(reversed(rows)), device_id="pond-a", metrics=[DO], start=self.now-timedelta(minutes=10), end=self.now)
        self.assertEqual(a, b)
        self.assertEqual(rows, original)
        self.assertEqual(a["metrics"][DO]["last_minus_first"], 4.2)
        self.assertEqual(a["analysis"], {"persistent_low_oxygen": "NOT_EVALUATED", "recovery": "NOT_EVALUATED"})

    def test_known_session_changes_and_unknown_session_break_continuity(self):
        self.insert(self.batch(self.now-timedelta(seconds=30), session="a"))
        self.insert(self.batch(self.now-timedelta(seconds=20), session="b"))
        self.insert(self.batch(self.now-timedelta(seconds=10)), session_missing=True)
        self.insert(self.batch(self.now, session="b"))
        result = self.query()
        self.assertEqual(result["counts"]["unknown_session_windows"], 1)
        self.assertEqual(result["sessions"]["change_count"], 1)
        self.assertEqual(result["continuity"]["segment_count"], 3)
        self.assertEqual(result["metrics"][DO]["reliable_windows"], 4)
        self.assertIn("UNKNOWN_SESSION", result["limitations"])

    def test_actual_batch_metadata_pruning_is_unknown_not_a_fabricated_session(self):
        self.repo.batch_limit = 1
        for i in (1, 0):
            batch = self.batch(self.now-timedelta(seconds=i*10))
            current_now = self.now
            self.now = datetime.fromisoformat(batch["timestamp"])
            self.service.ingest(batch)
            self.now = current_now
        result = self.query()
        self.assertEqual(result["counts"]["unknown_session_windows"], 1)
        self.assertEqual(result["continuity"]["segment_count"], 1)

    def test_long_silence_and_count_retention_do_not_become_device_offline(self):
        self.insert(self.batch(self.now-timedelta(hours=2)))
        result = self.query(lookback_minutes=60)
        self.assertEqual(result["status"], "NO_DATA")
        self.assertEqual(result["retention_completeness"], "UNKNOWN")
        self.assertNotIn("OFFLINE", json.dumps(result))
        self.repo.history_limit = 1
        for i in (1, 0):
            self.service.ingest(self.batch(self.now-timedelta(seconds=i*10)))
        retained = self.query()
        self.assertEqual(retained["counts"]["matching_windows"], 1)
        self.assertEqual(retained["status"], "PARTIAL")

    def test_query_limit_is_not_a_recent_record_count(self):
        for i in range(100):
            self.insert(self.batch(self.now-timedelta(seconds=i*5), duration=1))
        self.assertEqual(len(self.service.history("pond-a", "water")), 60)
        self.assertEqual(self.query()["counts"]["matching_windows"], 100)

    def test_720_accepted_and_721_rejected_without_truncating_range(self):
        for i in range(MAX_HISTORY_ROWS):
            self.insert(self.batch(self.now-timedelta(seconds=i*2), duration=1))
        self.assertEqual(self.query(lookback_minutes=30)["counts"]["matching_windows"], MAX_HISTORY_ROWS)
        self.insert(self.batch(self.now-timedelta(seconds=1440), duration=1))
        self.assert_error("HISTORY_QUERY_BUDGET_EXCEEDED", lambda: self.query(lookback_minutes=30))
        self.assert_error("HISTORY_QUERY_BUDGET_EXCEEDED", lambda: summarize_water_history(
            [{}] * 721, device_id="pond-a", metrics=[DO], start=self.now-timedelta(minutes=10), end=self.now))

    def test_gaps_and_segments_are_bounded_without_discarding_total_statistics(self):
        for i in range(30):
            self.insert(self.batch(self.now-timedelta(seconds=i*15), duration=10, session="s-"+str(i)))
        result = self.query()
        self.assertEqual(len(result["gaps"]["items"]), 12)
        self.assertEqual(result["gaps"]["count"], 30)
        self.assertEqual(result["gaps"]["omitted_count"], 18)
        self.assertEqual(result["gaps"]["total_s"], 300)
        self.assertEqual(result["metrics"][DO]["reliable_windows"], 30)
        self.assertEqual(len(result["continuity"]["segments"]), 12)
        self.assertEqual(result["continuity"]["omitted_count"], 18)
        self.assertEqual(len(result["sessions"]["changes"]), 12)
        self.assertEqual(result["sessions"]["omitted_changes"], 17)

    def test_concurrent_late_receipt_is_not_known_at_query_time(self):
        self.insert(self.batch(), received=(self.now+timedelta(seconds=1)).isoformat())
        result = self.query()
        self.assertEqual(result["status"], "NO_DATA")
        self.assertEqual(result["counts"]["after_query_received"], 1)

    def test_damaged_payload_and_metadata_reject_with_safe_errors(self):
        batch = self.batch(); self.insert(batch)
        with self.repo.connection() as db:
            original = db.execute("SELECT payload FROM history").fetchone()[0]
        for damaged in ("not json", '{"window":{},"window":{},"data":{}}', '{}',
                        original.replace('"mg/L"', '"wrong"'), original.replace('6.4', 'NaN'),
                        original.replace('"valid_samples": 10', '"valid_samples": true')):
            with self.subTest(payload=damaged[:20]):
                with self.repo.connection() as db:
                    db.execute("UPDATE history SET payload=?", (damaged,))
                self.assert_error("HISTORY_RECORD_INVALID", self.query)
        with self.repo.connection() as db:
            db.execute("UPDATE history SET payload=?, received_at=?", (original, "bad timestamp"))
        self.assert_error("HISTORY_RECORD_INVALID", self.query)

    def test_valid_but_mismatched_window_times_and_nonfinite_values_reject(self):
        batch = self.batch(); self.insert(batch)
        original = {"window": batch["window"], "data": batch["water"]}
        for modification in ("duration", "end", "unit", "sample_count", "nan", "extra", "received_before_observed"):
            value = deepcopy(original)
            received = self.now.isoformat()
            if modification == "duration": value["window"]["duration_s"] = 20
            if modification == "end": value["window"]["end"] = (self.now-timedelta(seconds=1)).isoformat()
            if modification == "unit": value["data"]["metrics"][DO]["unit"] = "g/L"
            if modification == "sample_count": value["data"]["sample_count"] = 0
            if modification == "nan": value["data"]["metrics"][DO]["mean"] = float("nan")
            if modification == "extra": value["data"]["metrics"][DO]["extra"] = "private"
            if modification == "received_before_observed": received = (self.now-timedelta(seconds=1)).isoformat()
            with self.repo.connection() as db:
                db.execute("UPDATE history SET payload=?,received_at=?", (json.dumps(value), received))
            self.assert_error("HISTORY_RECORD_INVALID", self.query)

    def test_mismatched_session_device_or_invalid_session_identity_rejects(self):
        self.insert(self.batch())
        for session_device, session_id in (("pond-b", "session-a"), ("pond-a", "not a session")):
            with self.repo.connection() as db:
                db.execute("UPDATE batches SET device_id=?,session_id=?", (session_device, session_id))
            self.assert_error("HISTORY_RECORD_INVALID", self.query)

    def test_selected_malformed_observation_time_rejects(self):
        self.insert(self.batch(self.now-timedelta(seconds=10)))
        with self.repo.connection() as db:
            db.execute("UPDATE history SET observed_at=?", ("2026-10-17T00:04:xx+00:00",))
        self.assert_error("HISTORY_RECORD_INVALID", self.query)

    def test_oversized_stored_record_is_not_decoded_or_exposed(self):
        self.insert(self.batch())
        with self.repo.connection() as db:
            db.execute("UPDATE history SET payload=?", ('{"private":"'+'x'*9000+'"}',))
        self.assert_error("HISTORY_RECORD_TOO_LARGE", self.query)

    def test_storage_failure_is_safe_and_does_not_include_path_or_sql(self):
        import sqlite3
        with patch.object(self.repo, "connection", side_effect=sqlite3.DatabaseError("private path and SQL")):
            self.assert_error("HISTORY_STORAGE_ERROR", self.query)

    def test_output_budget_enforced_and_regular_three_metric_dto_is_bounded(self):
        for i in range(60):
            self.insert(self.batch(self.now-timedelta(seconds=i*10)))
        result = self.query(metrics=list(METRICS))
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
        self.assertLessEqual(len(encoded), MAX_HISTORY_RESULT_BYTES)
        self.assertEqual(result["counts"]["matching_windows"], 60)
        with patch("apps.monitoring.history.MAX_HISTORY_RESULT_BYTES", len(encoded)-1):
            self.assert_error("HISTORY_RESULT_TOO_LARGE", lambda: self.query(metrics=list(METRICS)))
        with patch("apps.monitoring.history.MAX_HISTORY_RESULT_BYTES", len(encoded)):
            self.assertEqual(self.query(metrics=list(METRICS)), result)

    def test_real_24_kib_limit_rejects_large_valid_result_without_partial_json(self):
        for i in range(30):
            batch = self.batch(self.now-timedelta(seconds=i*20), session="s"*60+str(i))
            batch["batch_id"] = "b"*60+str(i)
            self.insert(batch)
        with patch("apps.monitoring.history.MAX_HISTORY_RESULT_BYTES", 100000):
            result = self.query(metrics=list(METRICS))
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
        self.assertGreater(len(encoded), 24*1024)
        self.assert_error("HISTORY_RESULT_TOO_LARGE", lambda: self.query(metrics=list(METRICS)))

    def test_read_transaction_uses_one_bounded_candidate_select(self):
        from contextlib import contextmanager
        statements = []
        connection = self.repo.connection
        @contextmanager
        def tracked():
            with connection() as db:
                db.set_trace_callback(statements.append)
                yield db
        with patch.object(self.repo, "connection", tracked):
            self.query()
        self.assertEqual(sum(s.startswith("SELECT") for s in statements), 1)
        self.assertTrue(any(s == "BEGIN" for s in statements))
        self.assertTrue(any("LIMIT 721" in s for s in statements))
        self.assertFalse(any(s.startswith(("UPDATE", "INSERT", "DELETE")) for s in statements))

    def test_query_is_read_only_and_never_calls_diagnosis_or_events(self):
        self.service.ingest(self.batch(value=2.2))
        tables = ("history", "current", "events", "alerts", "batches", "channel_contacts")
        def stored():
            with self.repo.connection() as db:
                return {name: [tuple(row) for row in db.execute("SELECT * FROM " + name)] for name in tables}
        before = stored()
        with patch.object(self.service.diagnosis, "diagnose", side_effect=AssertionError("no history diagnosis")), \
                patch.object(self.repo.event_service, "transition", side_effect=AssertionError("no event write")):
            self.query()
        self.assertEqual(stored(), before)

    def test_old_history_snapshot_and_events_remain_compatible(self):
        self.service.ingest(self.batch(value=2.2))
        before = (self.service.history("pond-a", "water"), self.service.snapshot("pond-a"), self.service.events())
        self.query()
        self.assertEqual(before, (self.service.history("pond-a", "water"), self.service.snapshot("pond-a"), self.service.events()))


if __name__ == "__main__":
    unittest.main()
