"""Targeted, fully offline checks for service/model identity and capability evidence."""

from pathlib import Path
from tempfile import TemporaryDirectory
from dataclasses import replace
from unittest.mock import patch
import json
import socket
import unittest

from fishery_ai.capability_store import CapabilityStore
from fishery_ai.custom_profiles import CustomProfileStore
from fishery_ai.contracts import Mode
from fishery_ai.model_gateway import GatewayError, ModelEvent, ModelProfile, ProfileRegistry
from fishery_ai.model_options import CapabilitySource, Support
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.web import _builtin_profiles, create_app


def _no_network(*_args, **_kwargs):
    raise AssertionError("network is forbidden in capability identity tests")


class CapabilityIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("connect", "connect_ex", "sendto"):
            patcher = patch.object(socket.socket, name, _no_network)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(socket, "getaddrinfo", _no_network)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_builtin_identity_and_streaming_evidence_are_scoped(self):
        profiles = {profile.profile_id: profile for profile in _builtin_profiles()}
        qwen = profiles["qwen-plus-experimental"]
        deepseek = profiles["deepseek-v4-flash-experimental"]
        self.assertEqual((qwen.service_id, qwen.model_family), ("dashscope", "qwen"))
        self.assertEqual(qwen.capabilities.streaming, Support.SUPPORTED)
        self.assertEqual(qwen.capabilities.source_for("streaming"), CapabilitySource.USER_VERIFIED)
        self.assertEqual((deepseek.service_id, deepseek.model_family), ("deepseek_api", "deepseek"))
        self.assertEqual(deepseek.capabilities.streaming, Support.SUPPORTED)
        self.assertEqual(deepseek.capabilities.source_for("streaming"), CapabilitySource.OFFICIAL_DOCS)

    def test_legacy_provider_id_migrates_without_model_name_capability_inheritance(self):
        base = "https://api.example.invalid/v1"
        legacy = ModelProfile.from_dict({
            "profile_id": "legacy-qwen", "display_name": "Legacy Qwen", "provider_kind": "cloud",
            "adapter_id": "openai_chat", "provider_id": "qwen", "base_url": base,
            "model": "qwen-plus", "capabilities": {"source": "experimental",
                "streaming": "supported", "model_id": "qwen-plus", "base_url": base},
        })
        self.assertEqual((legacy.service_id, legacy.model_family), ("dashscope", "qwen"))
        self.assertEqual(legacy.capabilities.service_id, "dashscope")
        with self.assertRaises(ValueError):
            replace(legacy, service_id="different_service")

        custom = ModelProfile(profile_id="similar-name", display_name="Custom Qwen name",
                              provider_kind="local", adapter_id="openai_chat", provider_id="custom",
                              service_id="school_runtime", model_family="qwen",
                              base_url="http://localhost:8800/v1", model="qwen-plus")
        self.assertEqual(custom.capabilities.streaming, Support.UNKNOWN)
        self.assertEqual(custom.capabilities.source_for("streaming"), CapabilitySource.UNKNOWN)

    def test_legacy_custom_profile_file_remains_loadable(self):
        directory = self.root / "legacy-profiles"
        directory.mkdir()
        profile_id = "custom-0123456789abcdef0123456789abcdef"
        old_data = {"profile_id": profile_id, "profile_status": "custom", "max_retries": 0,
                    "display_name": "旧 Qwen Profile", "provider_id": "qwen",
                    "adapter_id": "openai_chat", "base_url": "https://example.invalid/v1",
                    "model": "qwen-plus", "secret_env": "SOME_API_KEY",
                    "provider_kind": "cloud"}
        (directory / f"{profile_id}.json").write_text(
            json.dumps(old_data), encoding="utf-8")
        loaded = CustomProfileStore(directory).load()[0]
        self.assertEqual((loaded.service_id, loaded.model_family), ("dashscope", "qwen"))
        self.assertEqual(loaded.capabilities.streaming, Support.UNKNOWN)

    def test_explicit_probe_temporarily_bypasses_unknown_gate_then_persists_exact_identity(self):
        custom_dir = self.root / "profiles"
        profile_store = CustomProfileStore(custom_dir)
        first = profile_store.create({"display_name": "学校 Runtime A", "service_id": "school_a",
            "model_family": "qwen", "adapter_id": "openai_chat",
            "base_url": "http://localhost:8811/v1/", "model": "qwen-plus",
            "secret_env": "", "provider_kind": "local"})
        second = profile_store.create({"display_name": "学校 Runtime B", "service_id": "school_b",
            "model_family": "qwen", "adapter_id": "openai_chat",
            "base_url": "http://localhost:8811/v1/", "model": "qwen-plus",
            "secret_env": "", "provider_kind": "local"})
        evidence_dir = self.root / "capability-evidence"
        factory_mode = {"probe": False}
        sdk_client_called = []
        probe_requests = []

        class ProbeGateway:
            def stream(self, request, runtime):
                self_runtime = runtime
                if self_runtime.capabilities.streaming != Support.SUPPORTED:
                    raise AssertionError("probe must receive only a temporary streaming allowance")
                if self_runtime.max_retries != 0:
                    raise AssertionError("explicit probe must not retry")
                if (self_runtime.service_id, self_runtime.adapter_id,
                        self_runtime.base_url, self_runtime.model) != (
                        "school_a", "openai_chat", "http://localhost:8811/v1", "qwen-plus"):
                    raise AssertionError("probe identity must stay exact")
                if (request.mode != Mode.CHAT or len(request.messages) != 1
                        or request.messages[0].content != "只回复 OK"):
                    raise AssertionError("probe must send only the minimal request")
                probe_requests.append(request)
                yield ModelEvent(delta="OK")

        class Factory:
            def __call__(self):
                if factory_mode["probe"]:
                    return ProbeGateway()
                return OpenAICompatibleAdapter(lambda *_args: sdk_client_called.append(True))

        def make_client():
            return create_app(trace_path=self.root / "trace.jsonl", custom_profiles_dir=custom_dir,
                              capability_evidence_dir=evidence_dir,
                              real_gateway_factory=Factory()).test_client()

        client = make_client()
        before = client.get("/api/config").get_json()["profiles"]
        before_by_id = {item["profile_id"]: item for item in before}
        self.assertEqual(before_by_id[first.profile_id]["capabilities"]["streaming"], "unknown")
        self.assertEqual(before_by_id[second.profile_id]["capabilities"]["streaming"], "unknown")

        response = client.post("/api/analyze/stream", json={"profile_id": first.profile_id,
            "scenario": "normal", "question": "仅用于离线 gate 测试", "confirm_network": True})
        self.assertIn("OPTION_UNKNOWN", response.get_data(as_text=True))
        self.assertEqual(sdk_client_called, [])

        denied = client.post(f"/api/profiles/{first.profile_id}/probe",
                             json={"capability": "streaming", "confirm_network": False})
        self.assertEqual(denied.get_json()["error_code"], "NETWORK_CONFIRMATION_REQUIRED")
        factory_mode["probe"] = True
        probed = client.post(f"/api/profiles/{first.profile_id}/probe",
                             json={"capability": "streaming", "confirm_network": True})
        self.assertEqual(probed.status_code, 200)
        self.assertEqual(probed.get_json()["capability"]["streaming"], "supported")
        self.assertEqual(probed.get_json()["capability"]["source"], "USER_VERIFIED")
        rejected_reverify = client.post(f"/api/profiles/{first.profile_id}/probe",
            json={"capability": "streaming", "confirm_network": True})
        self.assertEqual(rejected_reverify.get_json()["error_code"], "CAPABILITY_ALREADY_KNOWN")
        factory_mode["probe"] = True
        reprobed = client.post(f"/api/profiles/{first.profile_id}/probe",
            json={"capability": "streaming", "confirm_network": True, "reverify": True})
        self.assertEqual(reprobed.status_code, 200)
        self.assertEqual(reprobed.get_json()["capability"]["source"], "USER_VERIFIED")
        self.assertEqual(len(probe_requests), 2)

        reloaded = make_client().get("/api/config").get_json()["profiles"]
        after_by_id = {item["profile_id"]: item for item in reloaded}
        self.assertEqual(after_by_id[first.profile_id]["capabilities"]["streaming"], "supported")
        self.assertEqual(after_by_id[first.profile_id]["capabilities"]["source"], "USER_VERIFIED")
        self.assertEqual(after_by_id[second.profile_id]["capabilities"]["streaming"], "unknown")
        saved_records = list(evidence_dir.glob("*.json"))
        self.assertEqual(len(saved_records), 1)
        saved = json.loads(saved_records[0].read_text(encoding="utf-8"))
        self.assertEqual((saved["service_id"], saved["adapter_id"], saved["base_url"],
                          saved["model"]),
                         ("school_a", "openai_chat", "http://localhost:8811/v1", "qwen-plus"))
        self.assertNotIn("secret", saved)

    def test_streaming_probe_network_failure_keeps_unknown(self):
        custom_dir = self.root / "profiles-network-failure"
        profile = CustomProfileStore(custom_dir).create({"display_name": "超时服务",
            "service_id": "school", "model_family": "unknown",
            "adapter_id": "openai_chat", "base_url": "http://localhost:8822/v1",
            "model": "school-model", "secret_env": "", "provider_kind": "local"})
        evidence_dir = self.root / "capability-evidence-network-failure"

        class ReadTimeoutGateway:
            def stream(self, _request, runtime):
                self_runtime = runtime
                if self_runtime.max_retries != 0:
                    raise AssertionError("explicit probe must not retry")
                raise GatewayError("READ_TIMEOUT")
                yield  # pragma: no cover

        client = create_app(trace_path=self.root / "timeout-trace.jsonl",
            custom_profiles_dir=custom_dir, capability_evidence_dir=evidence_dir,
            real_gateway_factory=ReadTimeoutGateway).test_client()
        response = client.post(f"/api/profiles/{profile.profile_id}/probe",
            json={"capability": "streaming", "confirm_network": True})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json()["error_code"], "READ_TIMEOUT")
        self.assertEqual(list(evidence_dir.glob("*.json")) if evidence_dir.exists() else [], [])
        current = {item["profile_id"]: item for item in client.get("/api/config").get_json()["profiles"]}
        self.assertEqual(current[profile.profile_id]["capabilities"]["streaming"], "unknown")
        self.assertEqual(current[profile.profile_id]["capabilities"]["source"], "UNKNOWN")

    def test_explicit_streaming_refusal_is_persisted_as_unsupported(self):
        custom_dir = self.root / "profiles-unsupported"
        profile = CustomProfileStore(custom_dir).create({"display_name": "拒绝服务",
            "service_id": "school", "model_family": "unknown",
            "adapter_id": "openai_chat", "base_url": "http://localhost:8833/v1",
            "model": "school-model", "secret_env": "", "provider_kind": "local"})
        evidence_dir = self.root / "capability-evidence-unsupported"

        class RefusingGateway:
            def stream(self, _request, _runtime):
                raise GatewayError("STREAM_UNSUPPORTED")
                yield  # pragma: no cover

        def make_client():
            return create_app(trace_path=self.root / "unsupported-trace.jsonl",
                custom_profiles_dir=custom_dir, capability_evidence_dir=evidence_dir,
                real_gateway_factory=RefusingGateway).test_client()

        response = make_client().post(f"/api/profiles/{profile.profile_id}/probe",
            json={"capability": "streaming", "confirm_network": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "unsupported")
        capability = response.get_json()["capability"]
        self.assertEqual(capability["streaming"], "unsupported")
        self.assertEqual(capability["source"], "USER_VERIFIED")
        reloaded = {item["profile_id"]: item for item in make_client().get(
            "/api/config").get_json()["profiles"]}
        self.assertEqual(reloaded[profile.profile_id]["capabilities"]["streaming"], "unsupported")
        self.assertEqual(reloaded[profile.profile_id]["capabilities"]["source"], "USER_VERIFIED")


if __name__ == "__main__":
    unittest.main()


# Explicit historical fixtures; not active startup assets.
from tests.support.historical_model_fixtures import install as _install_history
_install_history(globals())
