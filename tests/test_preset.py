"""Fixed maintenance contracts, independent of mutable local evidence."""

from pathlib import Path
from tempfile import TemporaryDirectory
from dataclasses import replace
from unittest.mock import patch
import unittest

from fishery_ai.presets import preset_profiles
from fishery_ai.model_gateway import ProfileRegistry, ModelRequest, MockGateway, GatewayError
from fishery_ai.model_options import ReasoningMode, ReasoningOptions, Support
from fishery_ai.contracts import Mode
from fishery_ai.credentials import CredentialStore
from fishery_ai.web import create_app


class PresetTests(unittest.TestCase):
    def test_template_variants_share_identity_and_version(self):
        profiles = preset_profiles()
        qwen = [p for p in profiles if p.preset_id == "qwen-plus"]
        self.assertEqual({p.preset_variant for p in qwen}, {"auto", "on", "off"})
        self.assertEqual(len({(p.service_id, p.adapter_id, p.base_url, p.model) for p in qwen}), 1)
        self.assertEqual({p.preset_contract_version for p in profiles}, {"1"})
        self.assertTrue(all(p.max_retries == 0 for p in profiles))

    def test_unverified_variants_not_published(self):
        profiles = preset_profiles()
        deepseek = [p for p in profiles if p.preset_id == "deepseek-flash"]
        self.assertEqual([p.preset_variant for p in deepseek], ["auto"])
        self.assertEqual(deepseek[0].capabilities.streaming, Support.UNKNOWN)
        self.assertFalse(any(p.preset_id == "ollama-qwen35" for p in profiles))
        ollama = [p for p in preset_profiles(include_candidates=True) if p.preset_id == "ollama-qwen35"]
        self.assertEqual([p.preset_variant for p in ollama], ["off"])
        self.assertEqual(ollama[0].capabilities.reasoning_on, Support.UNKNOWN)
        self.assertEqual(ollama[0].capabilities.streaming, Support.UNKNOWN)

    def test_fixed_variant_cannot_be_overridden(self):
        profile = next(p for p in preset_profiles() if p.preset_id == "qwen-plus" and p.preset_variant == "off")
        runtime = ProfileRegistry([profile], CredentialStore(process_env={})).snapshot(profile.profile_id)
        self.assertEqual(runtime.access_mode, "preset")
        with self.assertRaises(GatewayError) as error:
            MockGateway().complete(ModelRequest(Mode.CHAT, (), reasoning=ReasoningOptions(ReasoningMode.ON)), runtime)
        self.assertEqual(error.exception.code, "PRESET_OPTION_LOCKED")

    def test_local_evidence_cannot_change_preset_contract(self):
        from fishery_ai.capability_store import CapabilityStore
        original = CapabilityStore.apply
        calls = []
        def apply(store, profile):
            self.assertNotEqual(profile.access_mode, "preset")
            calls.append(profile.profile_id)
            return original(store, profile)
        with TemporaryDirectory() as temp, patch.object(CapabilityStore, "apply", apply):
            root = Path(temp)
            app = create_app(trace_path=root / "trace.jsonl", custom_profiles_dir=root / "profiles",
                capability_evidence_dir=root / "evidence", credential_store=CredentialStore(process_env={}))
            client = app.test_client()
            profiles = client.get("/api/config").get_json()["profiles"]
            fixed = [p for p in profiles if p["access_mode"] == "preset"]
            self.assertEqual(len(fixed), 4)
            for profile in fixed:
                response = client.post(f"/api/profiles/{profile['profile_id']}/probe",
                    json={"confirm_network": True, "capability": "streaming"})
                self.assertEqual(response.get_json()["error_code"], "PRESET_READ_ONLY")
            self.assertTrue(calls)


# Explicit historical fixtures; not active startup assets.
from historical_model_fixtures import install as _install_history
_install_history(globals())
