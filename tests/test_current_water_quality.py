"""Offline current-state queries: fixed clocks, temporary files, no credentials."""

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import socket
import unittest

from fishery_ai.composition import RESOURCE_ROOT
from fishery_ai.contracts import Freshness, Quality, WaterQualityReading, evaluate_freshness, parse_time
from fishery_ai.credentials import CredentialStore
from fishery_ai.domain import DiagnosisService
from fishery_ai.model_gateway import MockGateway
from fishery_ai.repositories import MockRepository
from fishery_ai.telemetry import CurrentSnapshotStore, CurrentWaterQualityReader, SimulationAdapter
from fishery_ai.telemetry.scenario_templates import ScenarioTemplateStore, apply_scenario_template
from fishery_ai.web import create_app


NOW = parse_time("2026-10-05T02:00:00Z")


class OfflineCurrentCase(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = NOW
        for target in ("socket.socket.connect", "socket.socket.connect_ex", "socket.create_connection",
                       "socket.getaddrinfo", "socket.socket.sendto"):
            blocker = patch(target, side_effect=AssertionError("current tests forbid network"))
            blocker.start()
            self.addCleanup(blocker.stop)

    def raw(self, **values):
        return WaterQualityReading.from_raw({"temp": 28, "ph": 7.5, "oxygen": 2.2, **values},
            observed_at=NOW, retrieved_at=NOW, source="fake:sensor", stale_after_s=300)


class FreshnessPolicyTests(OfflineCurrentCase):
    def test_fresh_boundary_stale_and_one_hour(self):
        for age, expected in ((0, Freshness.FRESH), (299, Freshness.FRESH),
                              (300, Freshness.FRESH), (301, Freshness.STALE), (3600, Freshness.STALE)):
            with self.subTest(age=age):
                self.assertEqual(evaluate_freshness(NOW, NOW + timedelta(seconds=age), 300), expected)

    def test_ingestion_and_query_share_policy(self):
        with patch("fishery_ai.contracts.evaluate_freshness", return_value=Freshness.STALE) as evaluate:
            self.assertEqual(self.raw().freshness, Freshness.STALE)
            evaluate.assert_called_once_with(NOW, NOW, 300)
        store = CurrentSnapshotStore()
        store.set_current(self.raw())
        with patch("fishery_ai.telemetry.current.evaluate_freshness", return_value=Freshness.STALE) as evaluate:
            self.assertEqual(CurrentWaterQualityReader(store, stale_after_s=42, clock=lambda: NOW).query().reading.freshness,
                             Freshness.STALE)
            evaluate.assert_called_once_with(NOW, NOW, 42)

    def test_invalid_policy_and_naive_timestamps_rejected(self):
        for threshold in (-1, float("nan"), float("inf"), True, "300", 10 ** 1000):
            with self.subTest(threshold=type(threshold).__name__), self.assertRaises(ValueError):
                evaluate_freshness(NOW, NOW, threshold)
        with self.assertRaises(ValueError):
            evaluate_freshness(NOW, NOW.replace(tzinfo=None), 300)


class CurrentReaderTests(OfflineCurrentCase):
    def setUp(self):
        super().setUp()
        self.store = CurrentSnapshotStore()
        self.reader = CurrentWaterQualityReader(self.store, stale_after_s=300, clock=lambda: self.now)

    def test_empty_returns_none_without_clock_or_fallback(self):
        reader = CurrentWaterQualityReader(self.store, stale_after_s=300,
                                          clock=lambda: self.fail("empty query does not evaluate data"))
        with patch.object(MockRepository, "water_quality", side_effect=AssertionError("no fallback")), \
             patch.object(ScenarioTemplateStore, "get_template", side_effect=AssertionError("no template")):
            self.assertIsNone(reader.query())
        self.assertIsNone(self.store.get_current())

    def test_apply_then_query_fresh(self):
        template = ScenarioTemplateStore(RESOURCE_ROOT.joinpath("scenarios/water_quality")).get_template("normal").template
        original = apply_scenario_template(template, snapshot_store=self.store,
                                          adapter=SimulationAdapter(), now=NOW)
        view = self.reader.query()
        self.assertEqual(view.reading.freshness, Freshness.FRESH)
        self.assertIsNot(view.reading, original)
        self.assertEqual(view.evaluated_at, NOW)

    def test_query_age_below_equal_above_threshold_and_hour(self):
        self.store.set_current(self.raw())
        for age, expected in ((299, Freshness.FRESH), (300, Freshness.FRESH),
                              (301, Freshness.STALE), (3600, Freshness.STALE)):
            with self.subTest(age=age):
                self.now = NOW + timedelta(seconds=age)
                self.assertEqual(self.reader.query().reading.freshness, expected)

    def test_configurable_policy_not_fixed_300(self):
        self.store.set_current(self.raw())
        self.now = NOW + timedelta(seconds=11)
        view = CurrentWaterQualityReader(self.store, stale_after_s=10, clock=lambda: self.now).query()
        self.assertEqual(view.reading.freshness, Freshness.STALE)
        self.assertEqual(self.reader.query().reading.freshness, Freshness.FRESH)

    def test_view_preserves_all_original_facts_and_store_identity(self):
        original = self.raw()
        self.store.set_current(original)
        self.now = NOW + timedelta(hours=1)
        view = self.reader.query()
        self.assertEqual(view.reading, replace(original, freshness=Freshness.STALE))
        self.assertEqual(view.evaluated_at, self.now)
        self.assertEqual(view.reading.retrieved_at, NOW)
        self.assertIs(self.store.get_current(), original)
        self.assertEqual(original.freshness, Freshness.FRESH)

    def test_partial_and_stale_are_independent(self):
        self.store.set_current(self.raw(ph=None))
        self.now = NOW + timedelta(seconds=301)
        self.assertEqual((self.reader.query().reading.quality, self.reader.query().reading.freshness),
                         (Quality.PARTIAL, Freshness.STALE))

    def test_invalid_and_stale_are_independent(self):
        self.store.set_current(self.raw(ph="invalid"))
        self.now = NOW + timedelta(seconds=301)
        self.assertEqual((self.reader.query().reading.quality, self.reader.query().reading.freshness),
                         (Quality.INVALID, Freshness.STALE))

    def test_diagnosis_uses_view_and_creates_stale_finding(self):
        original = self.raw()
        self.store.set_current(original)
        self.now = NOW + timedelta(seconds=301)
        codes = {f.code for f in DiagnosisService().diagnose(self.reader.query().reading)}
        self.assertEqual(codes, {"SENSOR_STALE", "OXYGEN_CRITICAL_LOW"})
        self.assertNotIn("SENSOR_STALE", {f.code for f in DiagnosisService().diagnose(original)})

    def test_query_captures_store_once_before_clock_changes_store(self):
        original, later = self.raw(), self.raw(oxygen=6.4)
        self.store.set_current(original)

        def changing_clock():
            self.store.set_current(later)
            return NOW + timedelta(seconds=301)

        reader = CurrentWaterQualityReader(self.store, stale_after_s=300, clock=changing_clock)
        with patch.object(self.store, "get_current", wraps=self.store.get_current) as get:
            view = reader.query()
            get.assert_called_once_with()
        self.assertEqual(view.reading.dissolved_oxygen_mg_l, 2.2)
        self.assertIs(self.store.get_current(), later)

    def test_query_has_no_scenario_template_or_repository_dependency(self):
        self.store.set_current(self.raw())
        with patch.object(MockRepository, "water_quality", side_effect=AssertionError("no generation")), \
             patch.object(ScenarioTemplateStore, "get_template", side_effect=AssertionError("no template")):
            self.assertEqual(self.reader.query().reading.dissolved_oxygen_mg_l, 2.2)

    def test_view_and_reading_frozen_reader_exposes_no_write_method(self):
        self.store.set_current(self.raw())
        view = self.reader.query()
        for target, name, value in ((view, "evaluated_at", NOW), (view.reading, "ph", 9)):
            with self.assertRaises(FrozenInstanceError):
                setattr(target, name, value)
        self.assertFalse(hasattr(self.reader, "set_current"))

    def test_demo_store_lazy_and_separate_from_current_reading(self):
        repository = MockRepository(RESOURCE_ROOT.joinpath("scenarios"), clock=lambda: NOW)
        self.assertIsNone(repository._demo_snapshots)
        generated = repository.water_quality("low_oxygen")
        self.assertIs(repository.demo_snapshots.get_current(), generated)
        self.assertIs(repository.snapshots, repository.demo_snapshots)  # legacy alias
        self.assertIsNone(self.reader.query())

    def test_network_protection(self):
        with self.assertRaisesRegex(AssertionError, "current tests forbid network"):
            socket.create_connection(("example.invalid", 443))


class CurrentWebTests(OfflineCurrentCase):
    def setUp(self):
        super().setUp()
        self.app = create_app(trace_path=self.root / "trace.jsonl", custom_profiles_dir=self.root / "profiles",
            capability_evidence_dir=self.root / "evidence", manual_experiments_dir=self.root / "experiments",
            scenario_templates_dir=self.root / "templates", credential_store=CredentialStore(process_env={}),
            scenario_clock=lambda: self.now, real_gateway_factory=lambda: self.fail("no real gateway"))
        self.client = self.app.test_client()
        token = self.client.get("/api/credential-session").get_json()["csrf_token"]
        self.headers = {"Origin": "http://localhost", "X-CSRF-Token": token}
        self.store = self.app.extensions["fishery_snapshot_store"]
        self.reader = self.app.extensions["fishery_current_water_quality_reader"]
        self.payload = {"profile_id": "mock-demo", "question": "现在水质怎么样？"}

    def apply(self, identifier):
        response = self.client.post("/api/water-quality/apply", json={"template_id": identifier}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_current_endpoint_uses_reader_and_recomputed_diagnosis(self):
        self.apply("low_oxygen")
        original = self.store.get_current()
        self.now = NOW + timedelta(hours=1)
        with patch.object(self.reader, "query", wraps=self.reader.query) as query:
            data = self.client.get("/api/water-quality/current").get_json()
            query.assert_called_once_with()
        self.assertEqual(data["snapshot"]["freshness"], "stale")
        self.assertEqual(data["snapshot"]["retrieved_at"], NOW.isoformat())
        self.assertEqual(data["evaluated_at"], self.now.isoformat())
        self.assertIn("SENSOR_STALE", {f["code"] for f in data["rule_results"]})
        self.assertIs(self.store.get_current(), original)

    def test_normal_captures_view_once_and_passes_stale_to_prompt(self):
        self.apply("low_oxygen")
        self.now = NOW + timedelta(seconds=301)
        captured_at = self.now
        complete = MockGateway.complete

        def complete_after_apply(gateway, request, runtime):
            self.assertIn("新鲜度 stale", request.messages[1].content)
            self.assertIn("SENSOR_STALE", request.messages[1].content)
            self.now = NOW + timedelta(hours=1)
            self.apply("normal")
            return complete(gateway, request, runtime)

        with patch.object(self.reader, "query", wraps=self.reader.query) as query, \
             patch.object(MockGateway, "complete", complete_after_apply):
            response = self.client.post("/api/analyze", json=self.payload)
            self.assertEqual(query.call_count, 2)  # one analysis capture + later Apply preview
        self.assertEqual(response.status_code, 200)
        result = response.get_json()["result"]
        facts = result["observed_facts"]
        self.assertEqual(facts["evaluated_at"], captured_at.isoformat())
        self.assertEqual(facts["water_quality"]["dissolved_oxygen_mg_l"], 2.2)
        self.assertEqual(facts["water_quality"]["freshness"], "stale")
        self.assertEqual(facts["water_quality"]["retrieved_at"], NOW.isoformat())
        self.assertIn("SENSOR_STALE", {f["code"] for f in result["rule_results"]})
        self.assertEqual(self.store.get_current().dissolved_oxygen_mg_l, 6.4)

    def test_stream_captures_before_iteration_and_later_apply(self):
        self.apply("low_oxygen")
        self.now = NOW + timedelta(seconds=301)
        captured_at = self.now
        with patch.object(self.reader, "query", wraps=self.reader.query) as query:
            stream = self.client.post("/api/analyze/stream", json=self.payload, buffered=False)
            self.assertEqual(query.call_count, 1)
            self.now = NOW + timedelta(hours=1)
            self.apply("normal")
            wire = stream.get_data(as_text=True)
            stream.close()
            self.assertEqual(query.call_count, 2)
        self.assertIn('"evaluated_at":"' + captured_at.isoformat() + '"', wire)
        self.assertIn('"freshness":"stale"', wire)
        self.assertIn('"dissolved_oxygen_mg_l":2.2', wire)
        self.assertIn("SENSOR_STALE", wire)
        self.assertIn("event: completed", wire)
        self.assertEqual(self.store.get_current().dissolved_oxygen_mg_l, 6.4)

    def test_current_normal_stream_do_not_generate_scenarios(self):
        self.apply("normal")
        with patch.object(MockRepository, "water_quality", side_effect=AssertionError("no fallback")), \
             patch.object(ScenarioTemplateStore, "get_template", side_effect=AssertionError("no template")):
            self.assertEqual(self.client.get("/api/water-quality/current").status_code, 200)
            self.assertEqual(self.client.post("/api/analyze", json=self.payload).status_code, 200)
            stream = self.client.post("/api/analyze/stream", json=self.payload)
            self.assertIn("event: completed", stream.get_data(as_text=True))
            stream.close()

    def test_no_data_normal_stream_never_fall_back(self):
        with patch.object(MockRepository, "water_quality", side_effect=AssertionError("no fallback")), \
             patch.object(ScenarioTemplateStore, "get_template", side_effect=AssertionError("no template")):
            self.assertEqual(self.client.get("/api/water-quality/current").get_json()["status"], "NO_DATA")
            for path in ("/api/analyze", "/api/analyze/stream"):
                response = self.client.post(path, json=self.payload)
                self.assertEqual((response.status_code, response.get_json()["error_code"]), (409, "NO_DATA"))
        self.assertIsNone(self.store.get_current())

    def test_scenario_compatibility_generates_then_queries_same_reader(self):
        for path in ("/api/analyze", "/api/analyze/stream"):
            with patch.object(self.reader, "query", wraps=self.reader.query) as query:
                response = self.client.post(path, json={**self.payload, "scenario": "partial_stale"})
                self.assertEqual(response.status_code, 200)
                response.get_data()
                response.close()
                query.assert_called_once_with()
            self.assertEqual((self.store.get_current().quality, self.store.get_current().freshness),
                             (Quality.PARTIAL, Freshness.STALE))


if __name__ == "__main__":
    unittest.main()
