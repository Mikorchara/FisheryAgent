"""R1 credentials use temporary files, fake values and a strict socket guard."""

from collections.abc import Mapping
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import FrozenInstanceError, asdict, replace
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import copy
import json
import os
import pickle
import socket
import sys
import unittest

from fishery_ai.contracts import Mode, Usage, UsageSource
from fishery_ai.credentials import CredentialFileError, CredentialSnapshot, CredentialStore
from fishery_ai.model_gateway import (GatewayError, ModelEvent, ModelMessage, ModelProfile,
                                     ModelRequest, ModelResponse, ProfileRegistry)
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.providers import AuthSpec, PROVIDERS
from fishery_ai.web import _builtin_profiles, create_app


FAKE_A = "fake-secret-123"
FAKE_B = "test-dashscope-key-B"
REF = "TEST_FAKE_KEY"


def deny_network(*_args, **_kwargs):
    raise AssertionError("R1 tests cannot access real network")


class NoEnvironment(Mapping):
    def __getitem__(self, _key):
        raise AssertionError("auth NONE must not inspect the process environment")

    def __iter__(self):
        raise AssertionError("auth NONE must not inspect the process environment")

    def __len__(self):
        raise AssertionError("auth NONE must not inspect the process environment")


class OfflineCredentialTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env_file = self.root / ".env"
        self.process = {}
        self.store = CredentialStore(self.env_file, self.process)
        for name in ("connect", "connect_ex", "sendto"):
            guard = patch.object(socket.socket, name, deny_network)
            guard.start()
            self.addCleanup(guard.stop)
        for name in ("getaddrinfo", "create_connection"):
            guard = patch.object(socket, name, deny_network)
            guard.start()
            self.addCleanup(guard.stop)
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        original_read = Path.read_text

        def only_temporary_env(path, *args, **kwargs):
            if path.name == ".env" and not path.absolute().is_relative_to(self.root.absolute()):
                raise AssertionError("tests must never read the real project .env")
            return original_read(path, *args, **kwargs)

        read_guard = patch.object(Path, "read_text", only_temporary_env)
        read_guard.start()
        self.addCleanup(read_guard.stop)

    def write(self, value=FAKE_A, *, name=REF):
        self.env_file.write_text(f"{name}={value}\n", encoding="utf-8")

    def profile(self, **changes):
        values = dict(profile_id="fixture", display_name="Fixture", provider_kind="local",
                      base_url="http://example.invalid/v1", model="fake-model", secret_env=REF,
                      max_retries=0)
        values.update(changes)
        return ModelProfile(**values)


class WebStartupCredentialTests(OfflineCredentialTest):
    def setUp(self):
        super().setUp()
        from fishery_ai import secure_files
        from fishery_ai.credential_paths import private_project_location
        self.base = self.root / "localappdata"
        secure_files.private_directory(self.base)
        self.project = self.root / "source"
        self.project.mkdir()
        with patch("fishery_ai.credential_paths.Path.home", return_value=self.base):
            self.location = private_project_location(self.project, {"LOCALAPPDATA": str(self.base)})
        self.location.check(create=True)
        self.env_file = self.location.env_path

    def start_cli_without_server(self):
        from flask import Flask
        from fishery_ai.__main__ import main

        # Exercise real Flask.run, but prohibit dotenv loading and socket serving.
        app = Flask("credential-startup-regression")
        with patch("fishery_ai.web.Path.cwd", return_value=self.project), \
                patch.dict(os.environ, {"LOCALAPPDATA": str(self.base)}), \
                patch("fishery_ai.credential_paths.Path.home", return_value=self.base), \
                patch("fishery_ai.web.create_app", return_value=app) as factory, \
                patch.object(app, "run", wraps=app.run) as run, \
                patch("flask.cli.load_dotenv", side_effect=AssertionError(
                    "Flask must not load any environment file")) as loader, \
                patch("werkzeug.serving.run_simple") as server, \
                patch.object(sys, "argv", ["fishery_ai", "web", "--port", "8765"]), \
                redirect_stdout(StringIO()):
            main()
        loader.assert_not_called()
        server.assert_called_once()
        self.assertIs(run.call_args.kwargs["load_dotenv"], False)
        return factory.call_args.kwargs["credential_store"]

    def test_cli_startup_keeps_project_source_and_hot_reload_without_environment_mutation(self):
        name = "TEST_API_KEY"
        self.assertNotIn(name, os.environ)
        from fishery_ai import secure_files
        secure_files.write_private(self.env_file, f"{name}={FAKE_A}\n".encode())
        store = self.start_cli_without_server()
        self.assertNotIn(name, os.environ)
        first = store.resolve(name)
        self.assertEqual(first.status.source, "PROJECT_ENV")
        self.assertEqual(first.status.availability, "PRESENT")
        self.assertTrue(first.status.editable)
        self.assertTrue(first._for_adapter() == FAKE_A)

        self.env_file.write_text(f"{name}={FAKE_B}\n", encoding="utf-8")
        second = store.resolve(name)
        self.assertEqual(second.status.source, "PROJECT_ENV")
        self.assertTrue(second._for_adapter() == FAKE_B)
        self.assertTrue(first._for_adapter() == FAKE_A)
        self.assertNotEqual(first.revision, second.revision)
        self.assertNotIn(name, os.environ)

    def test_cli_startup_preserves_external_process_environment_priority(self):
        name = "TEST_API_KEY"
        from fishery_ai import secure_files
        secure_files.write_private(self.env_file, f"{name}={FAKE_B}\n".encode())
        with patch.dict(os.environ, {name: FAKE_A}):
            store = self.start_cli_without_server()
            with patch.object(store, "_project_values", side_effect=AssertionError("no fallback")):
                snapshot = store.resolve(name)
            self.assertEqual(snapshot.status.source, "PROCESS_ENV")
            self.assertFalse(snapshot.status.editable)
            self.assertTrue(snapshot._for_adapter() == FAKE_A)
            self.assertTrue(os.environ[name] == FAKE_A)

    def test_cli_never_reads_or_migrates_legacy_project_env(self):
        legacy = self.project / ".env"
        legacy.write_text(f"TEST_API_KEY={FAKE_A}\n", encoding="utf-8")
        before = legacy.read_bytes()
        original_read = Path.read_text
        def no_legacy_read(path, *args, **kwargs):
            if path == legacy:
                raise AssertionError("legacy project .env must not be read")
            return original_read(path, *args, **kwargs)
        with patch.object(Path, "read_text", no_legacy_read):
            store = self.start_cli_without_server()
            self.assertEqual(store.status("TEST_API_KEY").availability, "MISSING")
        self.assertFalse(self.env_file.exists())
        self.assertTrue(legacy.read_bytes() == before)


class CredentialStoreTests(OfflineCredentialTest):
    def test_process_nonempty_has_priority_without_reading_project_file(self):
        self.write(FAKE_B)
        self.process[REF] = FAKE_A
        with patch.object(self.store, "_project_values", side_effect=AssertionError("no fallback")):
            snapshot = self.store.resolve(REF)
        self.assertEqual(snapshot._for_adapter(), FAKE_A)
        self.assertEqual(snapshot.status.public_info(), dict(
            availability="PRESENT", source="PROCESS_ENV", editable=False))

    def test_process_empty_blocks_project_fallback(self):
        self.write()
        self.process[REF] = ""
        with patch.object(self.store, "_project_values", side_effect=AssertionError("no fallback")):
            snapshot = self.store.resolve(REF)
        self.assertIsNone(snapshot._for_adapter())
        self.assertEqual(snapshot.status.public_info(), dict(
            availability="MISSING", source="PROCESS_ENV", editable=False))

    def test_project_utf8_bom_crlf_does_not_change_os_environ(self):
        before = dict(os.environ)
        self.env_file.write_bytes((f"\ufeff{REF}='{FAKE_A}'\r\n# 注释\r\n").encode("utf-8"))
        snapshot = self.store.resolve(REF)
        self.assertEqual(snapshot._for_adapter(), FAKE_A)
        self.assertEqual(snapshot.status.public_info(), dict(
            availability="PRESENT", source="PROJECT_ENV", editable=True))
        self.assertEqual(dict(os.environ), before)

    def test_missing_file_and_missing_reference_have_safe_status(self):
        self.assertEqual(self.store.status(REF).source, "MISSING")
        self.assertEqual(self.store.status(None).availability, "MISSING")
        self.write(name="OTHER_FAKE_KEY")
        self.assertEqual(self.store.status(REF).availability, "MISSING")

    def test_empty_project_value_is_project_missing(self):
        self.write("")
        snapshot = self.store.resolve(REF)
        self.assertEqual(snapshot.status.public_info(), dict(
            availability="MISSING", source="PROJECT_ENV", editable=True))
        self.assertIsNone(snapshot._for_adapter())

    def test_auth_none_never_reads_any_credential_source(self):
        store = CredentialStore(self.env_file, NoEnvironment())
        with patch.object(store, "_project_values", side_effect=AssertionError("no file read")):
            snapshot = store.resolve(REF, AuthSpec.NONE)
        self.assertEqual(snapshot.status.availability, "NONE_REQUIRED")
        self.assertEqual(snapshot.status.source, "NONE_REQUIRED")
        self.assertFalse(snapshot.status.editable)
        self.assertIsNone(snapshot._for_adapter())

    def test_values_are_literal_without_interpolation(self):
        self.process["OTHER_FAKE_KEY"] = FAKE_B
        self.write("${OTHER_FAKE_KEY}")
        self.assertEqual(self.store.resolve(REF)._for_adapter(), "${OTHER_FAKE_KEY}")

    def test_hot_reload_creates_new_snapshot_and_preserves_inflight_one(self):
        self.write()
        profile = self.profile()
        registry = ProfileRegistry([profile], self.store)
        first = registry.snapshot(profile.profile_id)
        self.write(FAKE_B)
        second = registry.snapshot(profile.profile_id)
        self.assertEqual(first.api_key, FAKE_A)
        self.assertEqual(second.api_key, FAKE_B)
        self.assertEqual(first.public_info(), second.public_info())
        with self.assertRaises(FrozenInstanceError):
            first.model = "changed"

    def test_credential_snapshot_is_private_immutable_and_not_serializable(self):
        self.write()
        runtime = ProfileRegistry([self.profile()], self.store).snapshot("fixture")
        credential = runtime.credential
        for text in (repr(credential), str(credential), repr(runtime)):
            self.assertNotIn(FAKE_A, text)
        for operation in (lambda: json.dumps(credential), lambda: asdict(credential),
                          lambda: asdict(runtime), lambda: copy.deepcopy(runtime),
                          lambda: pickle.dumps(credential)):
            with self.subTest(operation=operation.__name__), self.assertRaises(TypeError):
                operation()
        with self.assertRaises(AttributeError):
            credential.status = None
        with self.assertRaises(AttributeError):
            del credential.status
        with self.assertRaises(FrozenInstanceError):
            credential.status.source = "MISSING"
        self.assertNotIn(FAKE_A, json.dumps(asdict(runtime.public_info())))

    def test_invalid_dotenv_syntax_is_redacted_and_emits_no_parser_warning(self):
        self.env_file.write_text(f'{REF}="{FAKE_A}\n', encoding="utf-8")
        stderr = StringIO()
        with redirect_stderr(stderr), self.assertRaises(CredentialFileError) as caught:
            self.store.resolve(REF)
        self.assertEqual(str(caught.exception), "CREDENTIAL_FILE_ERROR")
        self.assertEqual(stderr.getvalue(), "")

    def test_unreadable_and_invalid_encoding_return_safe_file_error(self):
        with patch.object(Path, "read_text", side_effect=PermissionError(FAKE_A)):
            with self.assertRaises(CredentialFileError) as caught:
                self.store.resolve(REF)
        self.assertEqual(str(caught.exception), "CREDENTIAL_FILE_ERROR")
        self.env_file.write_bytes(b"\xff\xfe\xff")
        with self.assertRaises(CredentialFileError):
            self.store.resolve(REF)

    def test_default_store_never_discovers_or_reads_real_project_env(self):
        with patch.object(Path, "read_text", side_effect=AssertionError("no implicit .env")):
            self.assertEqual(CredentialStore().status(REF).availability, "MISSING")

    def test_explicit_legacy_environ_override_never_falls_back_to_project(self):
        self.write()
        registry = ProfileRegistry([self.profile()], self.store)
        self.assertIsNone(registry.snapshot("fixture", {}).api_key)
        self.assertEqual(registry.snapshot("fixture").api_key, FAKE_A)


class ProviderAuthTests(OfflineCredentialTest):
    def test_four_services_register_without_credentials(self):
        self.assertEqual({spec.service_id for spec in PROVIDERS.all()},
                         {"dashscope", "deepseek_api", "ollama", "generic_openai"})
        self.assertEqual(PROVIDERS.get("ollama").auth_spec, AuthSpec.NONE)
        self.assertEqual(PROVIDERS.get("custom").service_id, "generic_openai")
        self.assertIsNone(PROVIDERS.get("generic_openai").default_base_url)
        self.assertNotIn(FAKE_A, json.dumps([asdict(spec) for spec in PROVIDERS.all()]))

    def test_credential_ref_and_legacy_secret_env_are_compatible(self):
        profile = ModelProfile.from_dict(dict(profile_id="new", display_name="New",
            provider_kind="cloud", adapter_id="generic_openai_chat", service_id="generic_openai",
            base_url="https://example.invalid/v1", model="fake-model", credential_ref=REF))
        self.assertEqual(profile.secret_env, REF)
        self.assertEqual(profile.credential_ref, REF)
        with self.assertRaises(ValueError):
            replace(profile, credential_ref="DIFFERENT_FAKE_KEY")

    def test_local_deployment_does_not_infer_no_auth(self):
        profile = self.profile()
        self.assertEqual(profile.auth_spec, AuthSpec.REQUIRED_BEARER)
        self.assertEqual(self.profile(secret_env=None).auth_spec, AuthSpec.OPTIONAL_BEARER)
        self.assertEqual(self.profile(secret_env=None, provider_kind="cloud",
                                      auth_spec=AuthSpec.OPTIONAL_BEARER).auth_spec,
                         AuthSpec.OPTIONAL_BEARER)

    def test_builtin_ollama_none_uses_only_adapter_sdk_placeholder(self):
        profile = next(p for p in _builtin_profiles() if p.service_id == "ollama")
        runtime = ProfileRegistry([profile], CredentialStore(self.env_file, NoEnvironment())).snapshot(
            profile.profile_id)
        self.assertEqual(runtime.auth_spec, AuthSpec.NONE)
        self.assertIsNone(runtime.api_key)
        with patch("fishery_ai.openai_compatible_adapter.OpenAI") as sdk:
            OpenAICompatibleAdapter._make_client(runtime, 20)
        self.assertEqual(sdk.call_args.kwargs["api_key"], "local-no-key")
        self.assertEqual(sdk.call_args.kwargs["max_retries"], 0)
        self.assertNotIn("local-no-key", repr(runtime))

    def test_required_missing_stops_before_sdk_and_optional_is_allowed(self):
        runtime = ProfileRegistry([self.profile()], self.store).snapshot("fixture")
        adapter = OpenAICompatibleAdapter(lambda *_: self.fail("SDK must not open"))
        request = ModelRequest(Mode.CHAT, (ModelMessage("user", "test"),))
        with self.assertRaises(GatewayError) as caught:
            adapter.complete(request, runtime)
        self.assertEqual(caught.exception.code, "SECRET_MISSING")
        self.assertEqual(adapter.request_attempts, 0)
        optional = replace(runtime, auth_spec=AuthSpec.OPTIONAL_BEARER)
        OpenAICompatibleAdapter._check_secret(optional)


class WebCredentialTests(OfflineCredentialTest):
    def client(self, factory=None):
        kwargs = dict(credential_store=self.store, trace_path=self.root / "trace.jsonl",
                      custom_profiles_dir=self.root / "profiles",
                      capability_evidence_dir=self.root / "evidence")
        if factory is not None:
            kwargs["real_gateway_factory"] = factory
        return create_app(**kwargs).test_client()

    @staticmethod
    def payload():
        return dict(profile_id="qwen-plus-experimental", scenario="low_oxygen",
                    question="当前水质怎么样？", confirm_network=True)

    def test_safe_dtos_do_not_depend_on_present_credentials(self):
        self.write(name="DASHSCOPE_API_KEY")
        client = self.client()
        for url in ("/api/config", "/api/profiles/qwen-plus-experimental"):
            response = client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(FAKE_A, response.get_data(as_text=True))
        config = client.get("/api/config").get_json()
        self.assertEqual(len(config["providers"]), 4)
        self.assertEqual(len(config["profiles"]), 4)
        self.write("", name="DASHSCOPE_API_KEY")
        self.assertEqual(client.get("/api/config").get_json(), config)
        self.assertEqual(client.get("/api/profiles/qwen-plus-experimental").get_json()[
            "fields"]["auth_spec"], "REQUIRED_BEARER")

    def test_project_status_reports_source_editability_and_name_only(self):
        self.write(name="DASHSCOPE_API_KEY")
        response = self.client().post("/api/secret-status", json=dict(profile_id="qwen-plus-experimental"))
        self.assertEqual(response.get_json(), dict(secret_env="DASHSCOPE_API_KEY", status="PRESENT",
            availability="PRESENT", source="PROJECT_ENV", editable=True, storage="PROJECT_DIRECTORY"))
        self.assertNotIn(FAKE_A, response.get_data(as_text=True))

    def test_process_present_or_empty_reports_external_readonly(self):
        self.write(name="DASHSCOPE_API_KEY")
        client = self.client()
        for value, availability in ((FAKE_B, "PRESENT"), ("", "MISSING")):
            self.process["DASHSCOPE_API_KEY"] = value
            data = client.post("/api/secret-status", json=dict(profile_id="qwen-plus-experimental")).get_json()
            self.assertEqual((data["availability"], data["source"], data["editable"]),
                             (availability, "PROCESS_ENV", False))
            self.assertNotIn(FAKE_B, json.dumps(data))

    def test_builtin_ollama_has_no_credential_field_and_does_not_read_sources(self):
        self.store._process_env = NoEnvironment()
        client = self.client()
        with patch.object(self.store, "_project_values", side_effect=AssertionError("no file read")):
            data = client.post("/api/secret-status", json=dict(profile_id="ollama-qwen35-4b-local")).get_json()
        self.assertEqual((data["availability"], data["secret_env"]), ("NONE_REQUIRED", ""))
        fields = client.get("/api/profiles/ollama-qwen35-4b-local").get_json()["fields"]
        self.assertEqual((fields["auth_spec"], fields["secret_env"]), ("NONE", ""))

    def test_missing_and_file_errors_stop_before_gateway_safely(self):
        client = self.client(lambda: self.fail("gateway must not be constructed"))
        missing = client.post("/api/analyze", json=self.payload())
        self.assertEqual(missing.get_json()["error_code"], "SECRET_MISSING")
        self.env_file.write_text(f'DASHSCOPE_API_KEY="{FAKE_A}\n', encoding="utf-8")
        for url, body in (("/api/analyze", self.payload()),
                          ("/api/secret-status", dict(profile_id="qwen-plus-experimental"))):
            response = client.post(url, json=body)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.get_json()["error_code"], "CREDENTIAL_FILE_ERROR")
            self.assertNotIn(FAKE_A, response.get_data(as_text=True))

    def test_web_request_resolves_once_and_hot_reload_preserves_inflight_key(self):
        self.write(name="DASHSCOPE_API_KEY")
        seen = []
        owner = self

        class Gateway:
            def complete(self, _request, runtime):
                owner.write(FAKE_B, name="DASHSCOPE_API_KEY")
                seen.append(runtime.api_key)
                return ModelResponse('{"inference":"fixture","recommendations":[],"uncertainty":[]}',
                                     Usage(1, 1, 2, source=UsageSource.PROVIDER))

        client = self.client(Gateway)
        with patch.object(self.store, "resolve", wraps=self.store.resolve) as resolver:
            for _ in range(2):
                response = client.post("/api/analyze", json=self.payload())
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(FAKE_A, response.get_data(as_text=True))
                self.assertNotIn(FAKE_B, response.get_data(as_text=True))
        self.assertEqual(resolver.call_count, 2)
        self.assertEqual(seen, [FAKE_A, FAKE_B])
        trace = (self.root / "trace.jsonl").read_text(encoding="utf-8")
        self.assertNotIn(FAKE_A, trace)
        self.assertNotIn(FAKE_B, trace)

    def test_streaming_uses_one_private_snapshot_and_safe_result_and_trace(self):
        self.write(name="DASHSCOPE_API_KEY")
        seen = []

        class Gateway:
            def stream(self, _request, runtime):
                seen.append(runtime.credential.status.source)
                yield ModelEvent(delta='{"inference":"fixture","recommendations":[],"uncertainty":[]}')
                yield ModelEvent(usage=Usage(1, 1, 2, source=UsageSource.PROVIDER))

        client = self.client(Gateway)
        with patch.object(self.store, "resolve", wraps=self.store.resolve) as resolver:
            response = client.post("/api/analyze/stream", json=self.payload())
            text = response.get_data(as_text=True)
        self.assertEqual(resolver.call_count, 1)
        self.assertEqual(seen, ["PROJECT_ENV"])
        self.assertIn("event: completed", text)
        self.assertNotIn(FAKE_A, text)
        self.assertNotIn(FAKE_A, (self.root / "trace.jsonl").read_text(encoding="utf-8"))

    def test_probe_resolves_once_and_evidence_never_contains_credentials(self):
        self.write(name="DASHSCOPE_API_KEY")

        class Gateway:
            def stream(self, _request, runtime):
                self.runtime = runtime
                yield ModelEvent(delta="OK")

        gateway = Gateway()
        client = self.client(lambda: gateway)
        with patch.object(self.store, "resolve", wraps=self.store.resolve) as resolver:
            response = client.post("/api/profiles/qwen-plus-experimental/probe", json=dict(
                capability="streaming", confirm_network=True, reverify=True))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resolver.call_count, 1)
        self.assertEqual(gateway.runtime.api_key, FAKE_A)
        self.assertNotIn(FAKE_A, response.get_data(as_text=True))
        paths = list((self.root / "evidence").glob("*.json"))
        self.assertTrue(paths)
        for path in paths:
            self.assertNotIn(FAKE_A, path.read_text(encoding="utf-8"))

    def test_no_credential_writer_is_disabled_and_bad_status_inputs_are_safe(self):
        client = self.client()
        for method in ("put", "delete"):
            self.assertEqual(getattr(client, method)("/api/secret-status", json={}).status_code, 405)
        self.assertEqual(client.post("/api/credentials", json={}).get_json()["error_code"], "ORIGIN_NOT_ALLOWED")
        invalid = client.post("/api/secret-status", json=["invalid"])
        self.assertEqual(invalid.get_json()["error_code"], "INVALID_REQUEST")
        invalid = client.post("/api/secret-status", json=dict(secret_env=REF, auth_spec="invalid"))
        self.assertEqual(invalid.get_json()["error_code"], "INVALID_AUTH_SPEC")


if __name__ == "__main__":
    unittest.main()
