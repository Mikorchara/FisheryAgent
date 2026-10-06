"""Experimental scoring and its read-only transport; offline, temporary fixtures."""

from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fishery_ai.contracts import Freshness, Quality, WaterQualityReading, parse_time
from fishery_ai.domain import DiagnosisService
from fishery_ai.execution import RequestHandle, request_scope
from fishery_ai.model_gateway import GatewayError, ModelToolCall
from fishery_ai.telemetry import CurrentSnapshotStore, CurrentWaterQualityReader
from fishery_ai.tools import ToolExecutor, ToolRegistry, ToolStatus
from fishery_ai.tools.catalog import tool_catalog
from fishery_ai.tools.policy import ToolPolicy, UserToolPolicyStore, load_tool_policies
from fishery_ai.water_quality_scoring import WaterQualityScoringService

NOW = parse_time("2026-10-06T07:00:00Z")
NAME = "score_current_water_quality"


class ScoringTests(unittest.TestCase):
    def setUp(self):
        for target in ("socket.socket.connect", "socket.socket.connect_ex", "socket.socket.sendto",
                       "socket.create_connection", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("offline scoring tests"))
            guard.start(); self.addCleanup(guard.stop)
        self.service = WaterQualityScoringService()
        self.store = CurrentSnapshotStore()
        self.reader = CurrentWaterQualityReader(self.store, stale_after_s=300, clock=lambda: NOW)
        self.registry = ToolRegistry(self.reader, DiagnosisService(), self.service)
        self.policy = ToolPolicy("assistant", True, (NAME,))
        temp = TemporaryDirectory(); self.addCleanup(temp.cleanup); self.root = Path(temp.name)

    def reading(self, **values):
        return WaterQualityReading.from_raw({"temp": 28, "ph": 7.5, "oxygen": 6, **values},
            observed_at=NOW, retrieved_at=NOW, source="fixture:sensor", stale_after_s=300)

    def execute(self, args="{}", **kwargs):
        return ToolExecutor(self.registry, policy=self.policy, **kwargs).execute(ModelToolCall("score-call", NAME, args))

    def test_all_normal_boundaries_are_100(self):
        for temp in (20, 28, 30):
            for ph in (7, 7.5, 8.5):
                for oxygen in (5, 6, 100):
                    r = self.service.score(self.reading(temp=temp, ph=ph, oxygen=oxygen))
                    self.assertEqual(r.score, 100); self.assertEqual(r.grade, "GOOD")

    def test_temperature_high_and_low(self):
        for value, expected in ((34, 60), (18, 80), (100, 0), (-50, 0)):
            self.assertEqual(self.service.score(self.reading(temp=value)).components["temperature"]["score"], expected)

    def test_ph_high_and_low(self):
        for value, expected in ((9, 80), (6, 60), (14, 0), (0, 0)):
            self.assertEqual(self.service.score(self.reading(ph=value)).components["ph"]["score"], expected)

    def test_oxygen_low_and_no_high_penalty(self):
        for value, expected in ((2.2, 44), (0, 0), (5, 100), (80, 100)):
            self.assertEqual(self.service.score(self.reading(oxygen=value)).components["dissolved_oxygen"]["score"], expected)

    def test_multi_abnormal_example_is_68_warning(self):
        score = self.service.score(self.reading(temp=34, ph=7.5, oxygen=2.2))
        self.assertEqual(score.score, 68.0); self.assertEqual(score.grade, "WARNING")
        self.assertEqual(score.scoring_version, "experimental-water-quality-score-v1")
        self.assertIn("NOT PROFESSIONAL STANDARD", score.standard)

    def test_partial_only_averages_available_components(self):
        score = self.service.score(self.reading(temp=None, oxygen=2.2))
        self.assertEqual(score.status, "PARTIAL"); self.assertTrue(score.partial)
        self.assertEqual(score.score, 72); self.assertEqual(score.grade, "ACCEPTABLE")
        self.assertEqual(score.missing_components, ("temperature",))
        self.assertNotIn("temperature", score.components)

    def test_invalid_and_empty_measurements_not_scorable(self):
        for reading in (self.reading(ph="invalid"), self.reading(temp=None, ph=None, oxygen=None)):
            score = self.service.score(reading)
            self.assertEqual(score.status, "NOT_SCORABLE"); self.assertIsNone(score.score)
            self.assertEqual(score.components, {}); self.assertIsNone(score.grade)

    def test_stale_and_partial_stale_do_not_reduce_score(self):
        for reading in (self.reading(), self.reading(temp=None)):
            stale = replace(reading, freshness=Freshness.STALE)
            score = self.service.score(stale)
            self.assertEqual(score.score, self.service.score(reading).score)
            self.assertEqual(score.warnings, ("SENSOR_STALE",)); self.assertEqual(score.freshness, "stale")

    def test_no_data(self):
        score = self.service.score(None)
        self.assertEqual(score.status, "NO_DATA"); self.assertIsNone(score.score)
        result = self.execute()
        self.assertEqual(result.status, ToolStatus.NO_DATA); self.assertIsNone(result.payload["water_quality"])

    def test_grade_boundaries(self):
        # Only temperature present: distance maps directly to the desired score.
        for value, grade in ((29,"GOOD"),(31,"GOOD"),(31.1,"ACCEPTABLE"),(33,"ACCEPTABLE"),
                             (33.1,"WARNING"),(35,"WARNING"),(35.1,"CRITICAL")):
            self.assertEqual(self.service.score(self.reading(temp=value,ph=None,oxygen=None)).grade,grade)

    def test_registry_catalog_and_defaults(self):
        definition = self.registry.lookup(NAME).model_definition
        self.assertEqual(definition.parameters_dict(), {"type":"object","properties":{},"additionalProperties":False})
        entry = next(e for e in tool_catalog(self.registry) if e["name"] == NAME)
        self.assertTrue(entry["experimental"]); self.assertTrue(entry["executable"])
        self.assertEqual(entry["access_type"], "READ ONLY")
        defaults = load_tool_policies()
        self.assertNotIn(NAME, defaults["analysis"].exposed_tools)
        self.assertNotIn(NAME, defaults["assistant"].exposed_tools)

    def test_user_policy_both_modes_and_unauthorized(self):
        store = UserToolPolicyStore(self.root / "policies", self.registry)
        store.save({"schema_version":1,"modes":{mode:{"selected_tools":[NAME]} for mode in ("analysis","assistant")}})
        for mode in ("analysis", "assistant"):
            self.assertEqual(store.effective()[mode].exposed_tools, (NAME,))
        result = ToolExecutor(self.registry).execute(ModelToolCall("not-authorized", NAME, "{}"))
        self.assertEqual(result.error_code.value, "TOOL_NOT_ALLOWED")

    def test_arguments_rejected(self):
        for args in ('{"unused":1}', '{"path":"fictional-private-path"}'):
            self.assertEqual(self.execute(args).error_code.value, "INVALID_TOOL_ARGUMENTS")
        for args in ('[]', 'null', '{'):
            with self.assertRaises(ValueError): ModelToolCall("bad", NAME, args)

    def test_query_time_freshness_original_store_unchanged(self):
        reading = replace(self.reading(temp=34,oxygen=2.2), observed_at=NOW-timedelta(hours=1))
        self.store.set_current(reading)
        result = self.execute(); payload = result.payload
        self.assertEqual(result.status, ToolStatus.OK)
        self.assertEqual(payload["score"], 68); self.assertEqual(payload["warnings"], ["SENSOR_STALE"])
        self.assertEqual(payload["evaluated_at"], NOW.isoformat())
        self.assertEqual(payload["water_quality"]["source"], "fixture:sensor")
        self.assertIs(self.store.get_current(), reading); self.assertEqual(reading.freshness, Freshness.FRESH)
        json.loads(result.to_json())

    def test_partial_and_invalid_tool_status_are_normal_results(self):
        for reading, status in ((self.reading(ph=None),ToolStatus.PARTIAL),(self.reading(ph="bad"),ToolStatus.NOT_SCORABLE)):
            self.store.set_current(reading); result = self.execute()
            self.assertEqual(result.status,status); self.assertIsNone(result.error_code)

    def test_size_limit_and_cancellation(self):
        self.store.set_current(self.reading())
        self.assertEqual(self.execute(max_result_bytes=256).error_code.value,"TOOL_RESULT_TOO_LARGE")
        handle = RequestHandle(); handle.start(); handle.cancel()
        with self.assertRaises(GatewayError) as error:
            with request_scope(handle): self.execute()
        self.assertEqual(error.exception.code,"USER_CANCELLED")

    def test_cancel_after_read_and_handler_failure_do_not_leak(self):
        self.store.set_current(self.reading()); handle = RequestHandle(); handle.start()
        original = self.reader.query
        def query():
            view=original();handle.cancel();return view
        with request_scope(handle), patch.object(self.reader,"query",side_effect=query), self.assertRaises(GatewayError):
            self.execute()
        with patch.object(self.service,"score",side_effect=RuntimeError("fictional-secret-private-path")):
            result=self.execute()
        self.assertEqual(result.error_code.value,"TOOL_EXECUTION_ERROR")
        self.assertNotIn("fictional-secret-private-path",result.to_json())


if __name__ == "__main__": unittest.main()
