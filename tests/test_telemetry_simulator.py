"""Offline simulation ingress tests; no real credentials or network."""

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from importlib.resources import files
from unittest.mock import patch
import ast
import socket
import unittest

from fishery_ai.contracts import Freshness, Quality, WaterQualityReading, parse_time
from fishery_ai.domain import DiagnosisService
from fishery_ai.repositories import MockRepository
from fishery_ai.telemetry import (
    CurrentSnapshotStore, SimulationAdapter, SimulationPacket,
    SimulationRecipe, TelemetrySimulator,
)


class TelemetrySimulatorTests(unittest.TestCase):
    def setUp(self):
        for target in ("socket.socket.connect", "socket.socket.connect_ex",
                       "socket.create_connection", "socket.getaddrinfo", "socket.socket.sendto"):
            blocker = patch(target, side_effect=AssertionError("telemetry tests forbid network"))
            blocker.start()
            self.addCleanup(blocker.stop)
        self.now = parse_time("2026-10-04T00:00:00Z")
        self.simulator = TelemetrySimulator(device_id="test-device")
        self.adapter = SimulationAdapter(stale_after_s=300)
        self.diagnosis = DiagnosisService()

    def reading(self, simulator=None, *, observed_at=None):
        packet = (simulator or self.simulator).generate(observed_at=observed_at or self.now)
        return self.adapter.to_reading(packet, retrieved_at=self.now)

    def codes(self, reading):
        return tuple(f.code for f in self.diagnosis.diagnose(reading))

    def test_baseline_is_canonical_and_not_abnormal(self):
        reading = self.reading()
        self.assertIsInstance(reading, WaterQualityReading)
        self.assertEqual((reading.temperature_c, reading.ph, reading.dissolved_oxygen_mg_l),
                         (28, 7.5, 6.4))
        self.assertEqual((reading.quality, reading.freshness), (Quality.VALID, Freshness.FRESH))
        self.assertEqual((reading.observed_at, reading.retrieved_at), (self.now, self.now))
        self.assertEqual(reading.source, "simulation:test-device")
        self.assertEqual(self.codes(reading), ())

    def test_low_oxygen_is_diagnosed_by_domain(self):
        self.assertEqual(self.codes(self.reading(self.simulator.set_do(2.2))),
                         ("OXYGEN_CRITICAL_LOW",))

    def test_combined_overrides_create_two_independent_findings(self):
        reading = self.reading(self.simulator.set_temperature(34).set_do(2.2))
        findings = self.diagnosis.diagnose(reading)
        self.assertEqual(tuple(f.code for f in findings),
                         ("TEMP_CRITICAL_HIGH", "OXYGEN_CRITICAL_LOW"))
        self.assertEqual(tuple(f.facts_used for f in findings),
                         (("temperature_c",), ("dissolved_oxygen_mg_l",)))

    def test_missing_ph_is_partial_and_never_zero(self):
        reading = self.reading(self.simulator.missing("ph"))
        self.assertIsNone(reading.ph)
        self.assertEqual(reading.quality, Quality.PARTIAL)
        self.assertEqual(self.codes(reading), ("SENSOR_PARTIAL",))

    def test_invalid_fault_retains_other_observations(self):
        reading = self.reading(self.simulator.invalid("ph").set_do(2.2))
        self.assertIsNone(reading.ph)
        self.assertEqual(reading.quality, Quality.INVALID)
        self.assertEqual(self.codes(reading), ("SENSOR_INVALID", "OXYGEN_CRITICAL_LOW"))

    def test_stale_and_partial_stale_remain_independent(self):
        old = self.now - timedelta(seconds=301)
        stale = self.reading(observed_at=old)
        self.assertEqual((stale.quality, stale.freshness), (Quality.VALID, Freshness.STALE))
        partial_stale = self.reading(self.simulator.missing("ph"), observed_at=old)
        self.assertEqual((partial_stale.quality, partial_stale.freshness),
                         (Quality.PARTIAL, Freshness.STALE))
        self.assertEqual(self.codes(partial_stale), ("SENSOR_PARTIAL", "SENSOR_STALE"))

    def test_freshness_policy_is_configurable_and_boundary_is_inclusive(self):
        packet = self.simulator.generate(observed_at=self.now - timedelta(seconds=300))
        self.assertEqual(self.adapter.to_reading(packet, retrieved_at=self.now).freshness,
                         Freshness.FRESH)
        self.assertEqual(SimulationAdapter(stale_after_s=299).to_reading(
            packet, retrieved_at=self.now).freshness, Freshness.STALE)
        for policy in (-1, float("nan"), float("inf"), True, "300"):
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                SimulationAdapter(stale_after_s=policy)

    def test_invalid_numeric_types_and_ranges_do_not_become_valid(self):
        for value in (True, "7.5", "", "--", "bad", {}, float("nan"), float("inf"),
                      -0.1, 14.1, 10 ** 400):
            with self.subTest(kind=type(value).__name__):
                packet = SimulationPacket("device", self.now,
                    {"temperature_c": 28, "ph": value, "dissolved_oxygen_mg_l": 6.4})
                reading = self.adapter.to_reading(packet, retrieved_at=self.now)
                self.assertEqual(reading.quality, Quality.INVALID)
                self.assertIsNone(reading.ph)

    def test_omitted_field_is_missing_and_all_missing_is_invalid(self):
        partial = SimulationPacket("device", self.now,
                                  {"temperature_c": 28, "dissolved_oxygen_mg_l": 6.4})
        self.assertEqual(self.adapter.to_reading(partial, retrieved_at=self.now).quality,
                         Quality.PARTIAL)
        empty = SimulationPacket("device", self.now, {})
        self.assertEqual(self.adapter.to_reading(empty, retrieved_at=self.now).quality,
                         Quality.INVALID)

    def test_packet_schema_identity_and_sequence_validation(self):
        packet = self.simulator.generate(observed_at=self.now)
        self.assertEqual((packet.schema_version, packet.sequence), ("sim-v1", 1))
        for broken in (replace(packet, schema_version="hardware-v1"),
                       replace(packet, device_id=""), replace(packet, sequence=-1),
                       replace(packet, sequence=True),
                       replace(packet, readings={"unknown": 1})):
            with self.subTest(packet=broken), self.assertRaises(ValueError):
                self.adapter.to_reading(broken, retrieved_at=self.now)

    def test_naive_future_or_malformed_times_are_rejected(self):
        packet = self.simulator.generate(observed_at=self.now)
        for observed in (self.now.replace(tzinfo=None), self.now + timedelta(seconds=1), "invalid"):
            with self.subTest(observed=observed), self.assertRaises(ValueError):
                self.adapter.to_reading(replace(packet, observed_at=observed), retrieved_at=self.now)
        with self.assertRaises(ValueError):
            self.simulator.generate(observed_at=self.now.replace(tzinfo=None))

    def test_custom_baseline_and_last_override_wins(self):
        simulator = TelemetrySimulator(baseline=SimulationRecipe(temperature_c=27, ph=8,
                                                                dissolved_oxygen_mg_l=7))
        simulator.set_ph(7.4).missing("ph").set_ph(7.2)
        reading = self.reading(simulator)
        self.assertEqual((reading.temperature_c, reading.ph, reading.dissolved_oxygen_mg_l),
                         (27, 7.2, 7))

    def test_emitted_packet_cannot_be_changed_by_later_overrides(self):
        packet = self.simulator.generate(observed_at=self.now)
        self.simulator.set_do(2.2)
        next_packet = self.simulator.generate(observed_at=self.now)
        self.assertEqual(packet.readings["dissolved_oxygen_mg_l"], 6.4)
        self.assertEqual((packet.sequence, next_packet.sequence), (1, 2))
        with self.assertRaises(TypeError):
            packet.readings["ph"] = 8
        with self.assertRaises(FrozenInstanceError):
            packet.sequence = 3

    def test_unknown_override_field_and_non_numeric_setter_are_rejected(self):
        for operation in (lambda: self.simulator.missing("oxygen"),
                          lambda: self.simulator.invalid("typo"),
                          lambda: self.simulator.set_do(True),
                          lambda: self.simulator.set_ph("7.5")):
            with self.assertRaises(ValueError):
                operation()

    def test_simulator_and_adapter_do_not_import_diagnosis_or_llm(self):
        root = files("fishery_ai.telemetry")
        for name in ("models.py", "simulator.py", "adapter.py", "snapshot.py"):
            tree = ast.parse(root.joinpath(name).read_text(encoding="utf-8"))
            imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            self.assertFalse(set(imports) & {"domain", "application", "knowledge", "model_gateway"})
        # Out-of-optimal values stay numbers; only DiagnosisService creates Findings.
        packet = self.simulator.set_temperature(34).set_do(2.2).generate(observed_at=self.now)
        self.assertEqual(packet.readings["temperature_c"], 34)
        self.assertFalse(hasattr(packet, "rule_results"))

    def test_store_starts_empty_and_returns_last_explicit_set(self):
        store = CurrentSnapshotStore()
        self.assertIsNone(store.get_current())
        first = self.reading()
        last = self.reading(self.simulator.set_do(2.2))
        store.set_current(first)
        self.assertIs(store.get_current(), first)
        store.set_current(last)
        self.assertIs(store.get_current(), last)
        self.assertIsNone(CurrentSnapshotStore().get_current())
        with self.assertRaises(ValueError):
            store.set_current(self.simulator.generate(observed_at=self.now))

    def test_existing_mock_catalog_is_not_expanded_or_replaced(self):
        path = files("fishery_ai").joinpath("resources/mock/scenarios.json")
        repository = MockRepository(path)
        self.assertEqual(set(repository.data["water_quality"]),
                         {"normal", "low_oxygen", "partial", "stale", "partial_stale"})
        self.assertEqual(self.codes(repository.water_quality("low_oxygen")),
                         ("OXYGEN_CRITICAL_LOW",))
        self.assertEqual(len(repository.detection("normal").detections), 2)

    def test_network_is_forbidden(self):
        with self.assertRaisesRegex(AssertionError, "telemetry tests forbid network"):
            socket.getaddrinfo("example.invalid", 443)


if __name__ == "__main__":
    unittest.main()
