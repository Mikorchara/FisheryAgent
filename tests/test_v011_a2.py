"""Real-validation entry tests use fake gateways and never read the local .env."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch
import os
import socket
import unittest


def _deny(*_args, **_kwargs):
    raise AssertionError("network is forbidden in offline tests")


_names = ("connect", "connect_ex", "sendto")
_original = {}


def setUpModule():
    for name in _names:
        _original[name] = getattr(socket.socket, name)
        setattr(socket.socket, name, _deny)
    _original["create_connection"] = socket.create_connection
    _original["getaddrinfo"] = socket.getaddrinfo
    socket.create_connection = _deny
    socket.getaddrinfo = _deny


def tearDownModule():
    for name in _names:
        setattr(socket.socket, name, _original[name])
    socket.create_connection = _original["create_connection"]
    socket.getaddrinfo = _original["getaddrinfo"]


from fishery_ai.contracts import Usage, UsageSource
from fishery_ai.credentials import CredentialStore
from fishery_ai.model_gateway import ModelResponse
from fishery_ai.real_validation import run_real_validation


class RealValidationEntryTests(unittest.TestCase):
    def test_explicit_confirmation_is_required_before_env_load(self):
        output = StringIO()
        with patch("fishery_ai.real_validation.CredentialStore") as loader, redirect_stdout(output):
            result = run_real_validation(check="basic", scenario="normal", confirm_network=False)
        self.assertEqual(result, 2)
        loader.assert_not_called()
        self.assertIn("no network request", output.getvalue())

    def test_missing_secret_stops_before_gateway_creation(self):
        output = StringIO()
        with patch.dict(os.environ, {}, clear=True):
            with patch("fishery_ai.real_validation.OpenAICompatibleAdapter") as factory:
                with redirect_stdout(output):
                    result = run_real_validation(check="basic", scenario="normal",
                                                 confirm_network=True, credential_store=CredentialStore())
        self.assertEqual(result, 2)
        factory.assert_not_called()
        self.assertIn("Secret: MISSING", output.getvalue())
        self.assertIn("API CALL COUNT: 0", output.getvalue())

    def test_present_secret_is_never_printed_and_fake_response_maps_usage(self):
        output = StringIO()

        class FakeGateway:
            request_attempts = 1

            def complete(self, _request, _runtime):
                return ModelResponse("收到。", Usage(3, 2, 5, source=UsageSource.PROVIDER),
                                     returned_model="deepseek-v4-flash")

        with patch.dict(
                os.environ, {"DEEPSEEK_API_KEY": "SENTINEL_SECRET"}, clear=True):
            with patch("fishery_ai.real_validation.OpenAICompatibleAdapter",
                       return_value=FakeGateway()), redirect_stdout(output):
                result = run_real_validation(check="basic", scenario="normal",
                                             confirm_network=True, credential_store=CredentialStore())
        self.assertEqual(result, 0)
        text = output.getvalue()
        self.assertIn("REAL NETWORK VALIDATION", text)
        self.assertIn("Secret: PRESENT", text)
        self.assertIn('"api_call_count": 1', text)
        self.assertIn("total_tokens: 5", text)
        self.assertNotIn("SENTINEL_SECRET", text)

    def test_unexpected_exception_is_redacted(self):
        output = StringIO()

        class FakeGateway:
            request_attempts = 1

            def complete(self, _request, _runtime):
                raise RuntimeError("SENTINEL_SECRET")

        with patch.dict(
                os.environ, {"DEEPSEEK_API_KEY": "SENTINEL_SECRET"}, clear=True):
            with patch("fishery_ai.real_validation.OpenAICompatibleAdapter",
                       return_value=FakeGateway()), redirect_stdout(output):
                result = run_real_validation(check="basic", scenario="normal",
                                             confirm_network=True, credential_store=CredentialStore())
        self.assertEqual(result, 1)
        self.assertIn("UNEXPECTED_ERROR", output.getvalue())
        self.assertNotIn("SENTINEL_SECRET", output.getvalue())


if __name__ == "__main__":
    unittest.main()


# Explicit historical fixtures; not active startup assets.
from historical_model_fixtures import install as _install_history
_install_history(globals())
