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

from apps.ai_backend.contracts import Mode, Usage, UsageSource
from apps.ai_backend.credentials import CredentialFileError, CredentialSnapshot, CredentialStore
from apps.ai_backend.model_gateway import (GatewayError, ModelEvent, ModelMessage, ModelProfile,
                                     ModelRequest, ModelResponse, ProfileRegistry)
from apps.ai_backend.openai_compatible_adapter import OpenAICompatibleAdapter
from apps.ai_backend.providers import AuthSpec, PROVIDERS



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