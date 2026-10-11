"""R4 exact evidence fixtures, with no network or real credentials."""

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fishery_ai.capability_store import CapabilityStore
from fishery_ai.evidence_resolver import CapabilityIdentity, CapabilityEvidence, resolve_capabilities, project_evidence
from fishery_ai.model_gateway import ModelProfile, ProfileRegistry, effective_runtime_defaults
from fishery_ai.model_options import CapabilitySource, ReasoningOptions, ReasoningMode, Support
from fishery_ai.presets import preset_profiles
from fishery_ai.web import _profile_public, _builtin_profiles, create_app
import json


class EvidenceResolverTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = CapabilityStore(Path(self.temp.name) / "evidence")
        self.profile = ModelProfile("fixture", "Fixture", "local", "http://localhost:8000/v1/", "arbitrary",
            adapter_id="openai_chat", service_id="dashscope")

    def claim(self, status, source=CapabilitySource.USER_VERIFIED, profile=None):
        return CapabilityEvidence(CapabilityIdentity.for_profile(profile or self.profile), "streaming",
                                  status, source, "2026-10-02T00:00:00Z", "offline_fixture")

    def test_missing_evidence_stays_unknown_protocol_is_not_evidence(self):
        resolved = self.store.apply(self.profile)
        self.assertEqual(resolved.capabilities.streaming, Support.UNKNOWN)
        self.assertFalse(project_evidence(self.profile))

    def test_invalid_evidence_state_or_unknown_source_is_rejected(self):
        for status, source in ((True, CapabilitySource.USER_VERIFIED),
                               ("accepted", CapabilitySource.USER_VERIFIED),
                               (Support.SUPPORTED, CapabilitySource.UNKNOWN)):
            with self.assertRaises(ValueError): self.claim(status, source)

    def test_agreement_preserves_sources_and_dates(self):
        evidence = [self.claim(Support.SUPPORTED, source) for source in
                    (CapabilitySource.OFFICIAL_DOCS, CapabilitySource.MODEL_METADATA, CapabilitySource.USER_VERIFIED)]
        p = resolve_capabilities(self.profile, evidence)
        self.assertEqual(p.capabilities.streaming, Support.SUPPORTED)
        self.assertEqual(len(p.capabilities.sources_for("streaming")), 3)
        self.assertEqual(_profile_public(p, "user_custom")["capabilities"]["streaming_evidence"]["evidence"][0]["observed_at"], evidence[0].observed_at)

    def test_conflict_is_unknown_with_reason_and_safe_defaults(self):
        p = replace(self.profile, default_response_mode="streaming")
        p = resolve_capabilities(p, [self.claim(Support.SUPPORTED, CapabilitySource.OFFICIAL_DOCS), self.claim(Support.UNSUPPORTED)])
        self.assertEqual(p.capabilities.streaming, Support.UNKNOWN)
        self.assertEqual(dict(p.capabilities.resolution_details)["streaming"], "EVIDENCE_CONFLICT")
        self.assertEqual(effective_runtime_defaults(p)[1], "normal")
        self.assertEqual(p.default_response_mode, "streaming")

    def test_exact_identity_not_name_family_or_similar_url(self):
        for change in ({"service_id": "custom"}, {"adapter_id": "generic_openai_chat", "service_id": "custom"},
                       {"model": "arbitrary-latest"}, {"base_url": "http://localhost:8001/v1"}):
            self.assertEqual(resolve_capabilities(replace(self.profile, **change), [self.claim(Support.SUPPORTED)]).capabilities.streaming, Support.UNKNOWN)
        normalized = replace(self.profile, base_url="HTTP://LOCALHOST:8000/v1/")
        self.assertEqual(resolve_capabilities(normalized, [self.claim(Support.SUPPORTED)]).capabilities.streaming, Support.SUPPORTED)

    def test_reapply_does_not_turn_previous_resolution_into_evidence(self):
        p = self.store.save_streaming(self.profile, Support.UNSUPPORTED, "2026-10-02")
        p = self.store.save_streaming(p, Support.SUPPORTED, "2026-10-03")
        self.assertEqual(p.capabilities.streaming, Support.SUPPORTED)
        self.assertEqual(self.store.apply(p).capabilities.streaming, Support.SUPPORTED)

    def test_official_probe_conflict_survives_restart(self):
        p = replace(self.profile, model="qwen-plus", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
        p = self.store.save_streaming(p, Support.UNSUPPORTED, "2026-10-02")
        self.assertEqual(p.capabilities.streaming, Support.UNKNOWN)
        loaded = CapabilityStore(self.store.directory).apply(p)
        self.assertEqual(loaded.capabilities.streaming, Support.UNKNOWN)
        self.assertEqual(set(loaded.capabilities.sources_for("streaming")), {CapabilitySource.OFFICIAL_DOCS, CapabilitySource.USER_VERIFIED})

    def test_conflicting_normalized_legacy_record_is_not_hidden_by_filename(self):
        self.store.save_streaming(self.profile, Support.SUPPORTED, "2026-10-02")
        record = dict(CapabilityStore._identity(self.profile), capability="streaming", status="unsupported",
                      source="USER_VERIFIED", verified_at="2026-10-01")
        record["base_url"] += "/"
        (self.store.directory / "legacy.json").write_text(json.dumps(record), encoding="utf-8")
        loaded = self.store.apply(self.profile)
        self.assertEqual(loaded.capabilities.streaming, Support.UNKNOWN)
        self.assertEqual(dict(loaded.capabilities.resolution_details)["streaming"], "EVIDENCE_CONFLICT")

    def test_preset_fixed_contract_is_not_read_or_written_by_store(self):
        preset = preset_profiles()[0]
        self.assertIs(self.store.apply(preset), preset)
        self.assertIs(resolve_capabilities(preset, [self.claim(Support.UNSUPPORTED, profile=preset)]), preset)
        with self.assertRaises(ValueError): self.store.save_streaming(preset, Support.UNSUPPORTED, "2026-10-02")
        self.assertFalse(self.store.directory.exists())

    def test_on_off_and_defaults_resolve_independently(self):
        identity = CapabilityIdentity.for_profile(self.profile)
        on = CapabilityEvidence(identity, "reasoning_on", Support.SUPPORTED, CapabilitySource.USER_VERIFIED, None, "legacy_fixture")
        p = resolve_capabilities(self.profile, [on])
        self.assertEqual(p.capabilities.reasoning_off, Support.UNKNOWN)
        self.assertIsNone(p.capabilities.thinking_default)
        self.assertIsNone(p.capability_evidence[0].observed_at)

    def test_mock_public_streaming_contract_is_unchanged(self):
        mock = _builtin_profiles()[0]
        self.assertIs(self.store.apply(mock), mock)
        client = create_app(trace_path=Path(self.temp.name) / "trace.jsonl",
            custom_profiles_dir=Path(self.temp.name) / "profiles",
            capability_evidence_dir=self.store.directory).test_client()
        config = client.get("/api/config").get_json()
        public = next(p for p in config["profiles"] if p["profile_id"] == mock.profile_id)
        self.assertEqual(public["capabilities"]["streaming"], "supported")

    def test_json_loading_uses_same_project_resolver_without_env_reads(self):
        path = Path(self.temp.name) / "profiles.json"
        path.write_text(json.dumps({"profiles": [dict(profile_id="json", display_name="JSON", provider_kind="local",
            service_id="dashscope", adapter_id="openai_chat", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen-plus")]}), encoding="utf-8")
        registry = ProfileRegistry.from_json(path)
        runtime = registry.snapshot("json", {})
        self.assertEqual(runtime.capabilities.reasoning_on, Support.SUPPORTED)
        self.assertEqual(dict(runtime.capabilities.resolution_details)["reasoning_on"], "EVIDENCE_AGREEMENT")


# Explicit historical fixtures; not active startup assets.
from tests.support.historical_model_fixtures import install as _install_history
_install_history(globals())
