"""Template and Web simulation tests: temporary storage, fixed clock, zero network."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import socket
import unittest

from fishery_ai.composition import RESOURCE_ROOT
from fishery_ai.contracts import Freshness, Quality, parse_time
from fishery_ai.credentials import CredentialStore
from fishery_ai.domain import DiagnosisService
from fishery_ai.repositories import MockRepository
from fishery_ai.secure_files import SecureFileError
from fishery_ai.telemetry import CurrentSnapshotStore, SimulationAdapter
from fishery_ai.telemetry.scenario_templates import (
    ScenarioError, ScenarioTemplate, ScenarioTemplateStore, apply_scenario_template,
)
from fishery_ai.web import create_app


NOW = parse_time("2026-10-04T02:00:00Z")
BUILTINS = RESOURCE_ROOT.joinpath("scenarios/water_quality")


def draft(identifier="user-test", **changes):
    data = {"schema_version": "scenario-template-v1", "id": identifier,
            "display_name": "高温低氧测试", "device_id": "sim-test", "observed_age_s": 0,
            "water_quality": {"temperature_c": {"state": "NORMAL", "value": 34},
                              "ph": {"state": "NORMAL", "value": 7.5},
                              "dissolved_oxygen_mg_l": {"state": "NORMAL", "value": 2.2}}}
    return {**data, **changes}


class OfflineCase(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.user = self.root / "scenario_templates/water_quality"
        for target in ("socket.socket.connect", "socket.socket.connect_ex", "socket.create_connection",
                       "socket.getaddrinfo", "socket.socket.sendto"):
            blocker = patch(target, side_effect=AssertionError("scenario tests forbid network"))
            blocker.start()
            self.addCleanup(blocker.stop)
        self.store = ScenarioTemplateStore(BUILTINS, self.user)
        self.snapshots = CurrentSnapshotStore()
        self.adapter = SimulationAdapter()

    def apply(self, template):
        return apply_scenario_template(template, snapshot_store=self.snapshots,
                                       adapter=self.adapter, now=NOW)


class ScenarioTemplateTests(OfflineCase):
    def test_five_builtin_templates_keep_values_quality_freshness_and_diagnosis(self):
        expected = {"normal": (Quality.VALID, Freshness.FRESH, ()),
                    "low_oxygen": (Quality.VALID, Freshness.FRESH, ("OXYGEN_CRITICAL_LOW",)),
                    "partial": (Quality.PARTIAL, Freshness.FRESH, ("SENSOR_PARTIAL",)),
                    "stale": (Quality.VALID, Freshness.STALE, ("SENSOR_STALE",)),
                    "partial_stale": (Quality.PARTIAL, Freshness.STALE, ("SENSOR_PARTIAL", "SENSOR_STALE"))}
        self.assertEqual({item.template.id for item in self.store.list_templates()}, set(expected))
        for name, (quality, freshness, codes) in expected.items():
            with self.subTest(name=name):
                item = self.store.get_template(name)
                reading = self.apply(item.template)
                self.assertEqual(item.source, "BUILTIN")
                self.assertEqual((reading.quality, reading.freshness), (quality, freshness))
                self.assertEqual(tuple(f.code for f in DiagnosisService().diagnose(reading)), codes)
                self.assertEqual(reading.temperature_c, 28)
                self.assertEqual(reading.ph, None if "partial" in name else 7.5)
                self.assertEqual(reading.dissolved_oxygen_mg_l, 2.2 if name == "low_oxygen" else 6.4)

    def test_builtin_write_delete_and_id_collision_rejected(self):
        template = self.store.get_template("normal").template
        for operation in (lambda: self.store.update_user_template("normal", template),
                          lambda: self.store.delete_user_template("normal")):
            with self.assertRaises(ScenarioError) as raised:
                operation()
            self.assertEqual(raised.exception.code, "SCENARIO_READ_ONLY")
        with self.assertRaises(ScenarioError) as raised:
            self.store.create_user_template(template)
        self.assertEqual(raised.exception.code, "SCENARIO_ID_EXISTS")
        self.assertFalse(self.user.exists())

    def test_builtin_save_as_and_user_crud_reload(self):
        copied = self.store.save_as_user_template("low_oxygen", display_name="我的低氧模板")
        self.assertEqual(copied.source, "USER")
        self.assertNotEqual(copied.template.id, "low_oxygen")
        created = self.store.create_user_template(ScenarioTemplate.from_dict(draft()))
        changed = replace(created.template, display_name="修改后", observed_age_s=301)
        updated = self.store.update_user_template(created.template.id, changed)
        reloaded = ScenarioTemplateStore(BUILTINS, self.user).get_template(updated.template.id)
        self.assertEqual(reloaded.template, changed)
        second = self.store.save_as_user_template(updated.template.id, display_name="第二份")
        self.assertEqual(second.template.readings, changed.readings)
        self.assertNotEqual(second.template.id, updated.template.id)
        self.store.delete_user_template(updated.template.id)
        with self.assertRaises(ScenarioError) as raised:
            self.store.get_template(updated.template.id)
        self.assertEqual(raised.exception.code, "SCENARIO_NOT_FOUND")
        self.assertEqual(self.store.get_template(second.template.id).source, "USER")

    def test_duplicate_id_cannot_overwrite_existing_template(self):
        original = ScenarioTemplate.from_dict(draft())
        self.store.create_user_template(original)
        with self.assertRaises(ScenarioError) as raised:
            self.store.create_user_template(replace(original, display_name="覆盖尝试"))
        self.assertEqual(raised.exception.code, "SCENARIO_ID_EXISTS")
        self.assertEqual(self.store.get_template(original.id).template, original)

    def test_path_traversal_absolute_and_windows_invalid_filename_rejected(self):
        for identifier in ("../outside", "..", "C:\\outside", "/outside", "a/b", "a\\b", "normal.json", "con", "a:b", ""):
            with self.subTest(identifier=identifier), self.assertRaises(ScenarioError):
                self.store.get_template(identifier)
        self.assertFalse(self.user.exists())

    def test_normal_missing_invalid_and_no_string_coercion(self):
        for state, expected in (("NORMAL", Quality.VALID), ("MISSING", Quality.PARTIAL), ("INVALID", Quality.INVALID)):
            data = draft()
            data["water_quality"]["ph"] = {"state": state, **({"value": 7.5} if state == "NORMAL" else {})}
            reading = self.apply(ScenarioTemplate.from_dict(data))
            self.assertEqual(reading.quality, expected)
            self.assertEqual(reading.ph, 7.5 if state == "NORMAL" else None)
        for value in (None, "--", "7.5", True, float("nan")):
            data = draft()
            data["water_quality"]["ph"] = {"state": "NORMAL", "value": value}
            with self.subTest(value=value), self.assertRaises(ScenarioError):
                ScenarioTemplate.from_dict(data)

    def test_schema_unknown_fields_and_missing_value_rejected(self):
        for change in ({"schema_version": "hardware-v1"}, {"observed_age_s": -1},
                       {"observed_age_s": float("inf")}, {"path": "outside.json"}, {"device_id": 9}):
            with self.subTest(change=change), self.assertRaises(ScenarioError):
                ScenarioTemplate.from_dict(draft(**change))
        data = draft()
        data["water_quality"]["ph"] = {"state": "NORMAL"}
        with self.assertRaises(ScenarioError):
            ScenarioTemplate.from_dict(data)

    def test_age_conversion_and_configurable_fresh_stale_boundary(self):
        for age, freshness in ((0, Freshness.FRESH), (300, Freshness.FRESH), (301, Freshness.STALE)):
            template = ScenarioTemplate.from_dict(draft(observed_age_s=age))
            reading = self.apply(template)
            self.assertEqual(reading.observed_at, NOW - timedelta(seconds=age))
            self.assertEqual(reading.retrieved_at, NOW)
            self.assertEqual(reading.freshness, freshness)
            self.assertNotIn("observed_at", template.to_dict())
            self.assertNotIn("freshness", template.to_dict())

    def test_template_uses_simulation_adapter_and_updates_same_store(self):
        template = ScenarioTemplate.from_dict(draft())
        with patch.object(self.adapter, "to_reading", wraps=self.adapter.to_reading) as convert:
            reading = self.apply(template)
        packet = convert.call_args.args[0]
        self.assertEqual(packet.schema_version, "sim-v1")
        self.assertEqual(packet.readings["dissolved_oxygen_mg_l"], 2.2)
        self.assertIs(self.snapshots.get_current(), reading)
        self.assertEqual(tuple(f.code for f in DiagnosisService().diagnose(reading)),
                         ("TEMP_CRITICAL_HIGH", "OXYGEN_CRITICAL_LOW"))

    def test_storage_guard_and_failed_replace_preserve_original(self):
        template = ScenarioTemplate.from_dict(draft())
        with patch("fishery_ai.telemetry.scenario_templates.guard_path", side_effect=SecureFileError()):
            with self.assertRaises(ScenarioError) as raised:
                self.store.create_user_template(template)
        self.assertEqual(raised.exception.code, "SCENARIO_STORAGE_ERROR")
        self.store.create_user_template(template)
        original = (self.user / (template.id + ".json")).read_bytes()
        with patch("fishery_ai.telemetry.scenario_templates.os.replace", side_effect=OSError("fake failure")):
            with self.assertRaises(ScenarioError):
                self.store.update_user_template(template.id, replace(template, display_name="changed"))
        self.assertEqual((self.user / (template.id + ".json")).read_bytes(), original)
        self.assertFalse(list(self.user.glob(".staging-*")))

    def test_detection_resources_preserve_events_and_do_not_use_water_templates(self):
        repository = MockRepository(RESOURCE_ROOT.joinpath("scenarios"), clock=lambda: NOW)
        self.assertIsNone(repository.snapshots.get_current())
        normal, jump = repository.detection("normal"), repository.detection("count_jump")
        self.assertEqual((normal.event_id, normal.model_id, normal.source, normal.frame_id),
                         ("mock-detection-001", "mock-detector-v1", "mock:camera-1", "frame-001"))
        self.assertEqual(normal.observed_at, parse_time("2026-09-27T00:00:00Z"))
        self.assertEqual((len(normal.detections), len(jump.detections)), (2, 7))
        self.assertEqual(normal.detections[0].bbox, (10, 20, 40, 60))
        self.assertEqual(jump.observed_at, parse_time("2026-09-27T00:00:05Z"))
        self.assertIsNone(repository.snapshots.get_current())

    def test_network_protection(self):
        with self.assertRaisesRegex(AssertionError, "scenario tests forbid network"):
            socket.create_connection(("example.invalid", 443))


class ScenarioWebTests(OfflineCase):
    def app(self):
        return create_app(trace_path=self.root / "trace.jsonl", custom_profiles_dir=self.root / "profiles",
            capability_evidence_dir=self.root / "evidence", manual_experiments_dir=self.root / "experiments",
            credential_store=CredentialStore(process_env={}), scenario_templates_dir=self.user,
            scenario_clock=lambda: NOW, real_gateway_factory=lambda: self.fail("no real gateway"))

    def setUp(self):
        super().setUp()
        self.application = self.app()
        self.client = self.application.test_client()
        token = self.client.get("/api/credential-session").get_json()["csrf_token"]
        self.headers = {"Origin": "http://localhost", "X-CSRF-Token": token}

    def send(self, path, data=None, method="post"):
        return getattr(self.client, method)(path, json=data or {}, headers=self.headers)

    def test_empty_store_lifecycle_and_no_data_analysis(self):
        self.assertEqual(self.client.get("/api/water-quality/current").get_json(),
                         {"status": "NO_DATA", "snapshot": None, "rule_results": []})
        payload = {"profile_id": "mock-demo", "question": "test"}
        self.assertEqual(self.client.post("/api/analyze", json=payload).get_json()["error_code"], "NO_DATA")
        self.assertEqual(self.client.post("/api/analyze/stream", json=payload).get_json()["error_code"], "NO_DATA")
        self.send("/api/water-quality/apply", {"template_id": "low_oxygen"})
        reading = self.application.extensions["fishery_snapshot_store"].get_current()
        self.assertEqual(reading.dissolved_oxygen_mg_l, 2.2)
        response = self.client.post("/api/analyze", json=payload).get_json()
        self.assertEqual(response["result"]["observed_facts"]["water_quality"]["dissolved_oxygen_mg_l"], 2.2)
        self.assertIs(self.application.extensions["fishery_snapshot_store"].get_current(), reading)
        self.assertIsNone(self.app().extensions["fishery_snapshot_store"].get_current())

    def test_temporary_apply_creates_no_user_file_and_returns_program_findings(self):
        response = self.send("/api/water-quality/apply", {"template": draft("temporary")})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual([f["code"] for f in data["rule_results"]],
                         ["TEMP_CRITICAL_HIGH", "OXYGEN_CRITICAL_LOW"])
        self.assertEqual(data["snapshot"]["retrieved_at"], NOW.isoformat())
        self.assertFalse(self.user.exists())
        current = self.client.get("/api/water-quality/current").get_json()
        self.assertEqual(current, data)

    def test_user_save_edit_copy_delete_and_reload(self):
        created = self.send("/api/scenario-templates", {"template": draft()})
        self.assertEqual(created.status_code, 201)
        template = created.get_json()["template"]
        self.assertEqual(template.pop("source"), "USER")
        identifier = template["id"]
        template["observed_age_s"] = 301
        response = self.send("/api/scenario-templates/" + identifier, {"template": template}, method="put")
        self.assertEqual(response.status_code, 200)
        self.send("/api/water-quality/apply", {"template_id": identifier})
        self.assertEqual(self.client.get("/api/water-quality/current").get_json()["snapshot"]["freshness"], "stale")
        copied = self.send("/api/scenario-templates/" + identifier + "/copy", {"display_name": "副本"}).get_json()["template"]
        self.assertNotEqual(copied["id"], identifier)
        fresh_app = self.app()
        listed = fresh_app.test_client().get("/api/scenario-templates").get_json()["templates"]
        self.assertIn(identifier, [t["id"] for t in listed])
        self.assertEqual(self.send("/api/scenario-templates/" + identifier, method="delete").status_code, 200)
        self.assertEqual(self.application.extensions["fishery_snapshot_store"].get_current().freshness, Freshness.STALE)

    def test_builtin_readonly_copy_and_config_source(self):
        self.assertEqual(self.send("/api/scenario-templates/normal", {"template": self.store.get_template("normal").template.to_dict()}, method="put").status_code, 403)
        self.assertEqual(self.send("/api/scenario-templates/normal", method="delete").status_code, 403)
        self.assertEqual(self.send("/api/scenario-templates/normal/copy", {"display_name": "我的正常模板"}).status_code, 201)
        config = self.client.get("/api/config").get_json()
        self.assertEqual(sum(t["source"] == "BUILTIN" for t in config["scenario_templates"]), 5)
        self.assertEqual(sum(t["source"] == "USER" for t in config["scenario_templates"]), 1)

    def test_web_mutations_require_origin_csrf_and_reject_paths(self):
        payload = {"template": draft()}
        self.assertEqual(self.client.post("/api/scenario-templates", json=payload).get_json()["error_code"], "ORIGIN_NOT_ALLOWED")
        response = self.client.post("/api/water-quality/apply", json={"template_id": "normal"}, headers={"Origin": "http://localhost"})
        self.assertEqual(response.get_json()["error_code"], "CSRF_INVALID")
        response = self.send("/api/water-quality/apply", {"template_id": "../outside"})
        self.assertEqual(response.get_json()["error_code"], "SCENARIO_INVALID_ID")
        response = self.send("/api/scenario-templates", {"template": draft(path="D:/outside")})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("D:/outside", response.get_data(as_text=True))

    def test_legacy_scenario_analysis_also_updates_telemetry_snapshot(self):
        response = self.client.post("/api/analyze", json={"profile_id": "mock-demo", "question": "test", "scenario": "partial_stale"})
        self.assertEqual(response.status_code, 200)
        reading = self.application.extensions["fishery_snapshot_store"].get_current()
        self.assertEqual((reading.quality, reading.freshness), (Quality.PARTIAL, Freshness.STALE))
        self.assertTrue(reading.source.startswith("simulation:"))

    def test_stream_request_captures_reading_before_later_apply(self):
        self.send("/api/water-quality/apply", {"template_id": "low_oxygen"})
        stream = self.client.post("/api/analyze/stream", json={"profile_id": "mock-demo", "question": "test"}, buffered=False)
        self.send("/api/water-quality/apply", {"template_id": "normal"})
        wire = stream.get_data(as_text=True)
        stream.close()
        self.assertIn('"dissolved_oxygen_mg_l":2.2', wire)
        self.assertIn("OXYGEN_CRITICAL_LOW", wire)
        self.assertEqual(self.application.extensions["fishery_snapshot_store"].get_current().dissolved_oxygen_mg_l, 6.4)


if __name__ == "__main__":
    unittest.main()
