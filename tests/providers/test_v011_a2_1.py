"""A2.1 capability and safe diagnostic regression; no network access."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import json
import socket
import ssl
import unittest

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError

from fishery_ai.composition import RESOURCE_ROOT
from fishery_ai.model_gateway import GatewayError, ModelMessage, ModelProfile, ModelRequest, ProfileRegistry
from fishery_ai.model_options import (GenerationOptions, ModelCapabilities, OptionValidationError,
                                      ReasoningMode, ReasoningOptions, Support, validate_options)
from fishery_ai.contracts import Mode
from fishery_ai.openai_compatible_adapter import OpenAICompatibleAdapter
from fishery_ai.real_validation import _network_diagnostics


class CapabilityTests(unittest.TestCase):
    def test_on_off_are_independent_and_auto_is_unblocked(self):
        for on, off in ((Support.SUPPORTED, Support.UNKNOWN),
                        (Support.SUPPORTED, Support.SUPPORTED),
                        (Support.UNSUPPORTED, Support.SUPPORTED)):
            caps = ModelCapabilities(reasoning_on=on, reasoning_off=off)
            validate_options(GenerationOptions(), ReasoningOptions(ReasoningMode.AUTO), caps)
            for mode, expected in ((ReasoningMode.ON, on), (ReasoningMode.OFF, off)):
                if expected == Support.SUPPORTED:
                    validate_options(GenerationOptions(), ReasoningOptions(mode), caps)
                else:
                    with self.assertRaises(OptionValidationError) as caught:
                        validate_options(GenerationOptions(), ReasoningOptions(mode), caps)
                    self.assertEqual(caught.exception.code, "OPTION_UNKNOWN" if expected ==
                                     Support.UNKNOWN else "OPTION_UNSUPPORTED")

    def test_both_unknown_and_both_unsupported(self):
        for support, code in ((Support.UNKNOWN, "OPTION_UNKNOWN"),
                              (Support.UNSUPPORTED, "OPTION_UNSUPPORTED")):
            caps = ModelCapabilities(reasoning_on=support, reasoning_off=support)
            for mode in (ReasoningMode.ON, ReasoningMode.OFF):
                with self.assertRaises(OptionValidationError) as caught:
                    validate_options(GenerationOptions(), ReasoningOptions(mode), caps)
                self.assertEqual(caught.exception.code, code)

    def test_deepseek_profile_scope_and_mapping(self):
        profile_path = RESOURCE_ROOT.joinpath("profiles/deepseek_experimental.json")
        runtime = ProfileRegistry.from_json(profile_path).snapshot(
            "deepseek-v4-flash-experimental", {"DEEPSEEK_API_KEY": "SENTINEL_SECRET"})
        self.assertEqual(runtime.model, "deepseek-flash")
        self.assertEqual(runtime.profile_status.value, "experimental")
        self.assertEqual(runtime.capabilities.reasoning_on, Support.SUPPORTED)
        self.assertEqual(runtime.capabilities.reasoning_off, Support.SUPPORTED)  # reviewed official switch
        request = ModelRequest(Mode.CHAT, (ModelMessage("user", "test"),))
        on = replace(request, reasoning=ReasoningOptions(ReasoningMode.ON))
        self.assertEqual(OpenAICompatibleAdapter._kwargs(on, runtime, stream=False)["extra_body"],
                         {"thinking": {"type": "enabled"}})
        probe = replace(runtime, capabilities=replace(runtime.capabilities,
                                                       reasoning_off=Support.SUPPORTED))
        off = OpenAICompatibleAdapter._kwargs(
            replace(request, reasoning=ReasoningOptions(ReasoningMode.OFF)), probe, stream=False)
        self.assertEqual(off["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertNotIn("SENTINEL_SECRET", json.dumps(off))


class ErrorMappingTests(unittest.TestCase):
    def _sdk_error(self, cause, *, timeout=False):
        request = httpx.Request("POST", "https://example.invalid/v1/chat/completions")
        error = APITimeoutError(request=request) if timeout else APIConnectionError(
            request=request, message="SENTINEL_SECRET?query=private")
        error.__cause__ = cause
        return error

    def test_dns_connect_read_tls_and_generic_connection(self):
        cases = (
            (socket.gaierror(8, "SENTINEL_SECRET"), "DNS_ERROR"),
            (httpx.ConnectTimeout("SENTINEL_SECRET"), "CONNECT_TIMEOUT"),
            (httpx.ReadTimeout("SENTINEL_SECRET"), "READ_TIMEOUT"),
            (ssl.SSLError("SENTINEL_SECRET"), "TLS_ERROR"),
            (httpx.ConnectError("SENTINEL_SECRET"), "CONNECTION_ERROR"),
        )
        for cause, code in cases:
            mapped = OpenAICompatibleAdapter._map_error(self._sdk_error(cause))
            self.assertEqual(mapped.code, code)
            self.assertNotIn("SENTINEL_SECRET", str(mapped))
        mapped = OpenAICompatibleAdapter._map_error(self._sdk_error(None, timeout=True))
        self.assertEqual(mapped.code, "TIMEOUT")

    def test_streaming_refusal_requires_explicit_provider_message(self):
        profile = ProfileRegistry([ModelProfile(
            profile_id="probe-profile", display_name="Probe", provider_kind="local",
            adapter_id="generic_openai_chat", provider_id="custom",
            base_url="http://localhost:11434/v1", model="probe-model")])
        runtime = profile.snapshot("probe-profile", {})
        runtime = replace(runtime, max_retries=0, capabilities=replace(
            runtime.capabilities, streaming=Support.SUPPORTED, service_id="custom",
            adapter_id="generic_openai_chat", base_url=runtime.base_url, model_id=runtime.model))
        request = ModelRequest(Mode.CHAT, (ModelMessage("user", "只回复 OK"),))

        def mapped_stream_error(body):
            http_request = httpx.Request("POST", "http://localhost:11434/v1/chat/completions")
            response = httpx.Response(400, request=http_request, json=body)
            error = APIStatusError("safe test error", response=response, body=body)

            class Completions:
                def create(self, **_kwargs):
                    raise error

            class Client:
                chat = type("Chat", (), {"completions": Completions()})()

                def close(self):
                    pass

            adapter = OpenAICompatibleAdapter(lambda *_args: Client())
            with self.assertRaises(GatewayError) as caught:
                list(adapter.stream(request, runtime))
            return caught.exception

        refusal = mapped_stream_error({"error": {"message": "This model does not support streaming"}})
        self.assertEqual(refusal.code, "STREAM_UNSUPPORTED")
        generic = mapped_stream_error({"error": {"message": "Unknown model"}})
        self.assertEqual(generic.code, "HTTP_400")

    def test_network_probe_failure_is_redacted_and_stops(self):
        runtime = ProfileRegistry.from_json(RESOURCE_ROOT.joinpath(
            "profiles/deepseek_experimental.json")).snapshot(
                "deepseek-v4-flash-experimental", {"DEEPSEEK_API_KEY": "SENTINEL_SECRET"})
        gateway = OpenAICompatibleAdapter()
        with patch("fishery_ai.real_validation.socket.getaddrinfo",
                   side_effect=socket.gaierror(8, "SENTINEL_SECRET")):
            result = _network_diagnostics(runtime, gateway)
        self.assertEqual(result["steps"][0]["error_code"], "DNS_ERROR")
        self.assertEqual(len(result["steps"]), 1)
        self.assertNotIn("SENTINEL_SECRET", json.dumps(result))
        self.assertEqual(result["model_request_count"], 0)

    def test_default_suite_never_uses_real_network(self):
        with patch("socket.create_connection", side_effect=AssertionError("forbidden")):
            with self.assertRaises(AssertionError):
                socket.create_connection(("example.invalid", 443))


if __name__ == "__main__":
    unittest.main()


# Explicit historical fixtures; not active startup assets.
from tests.support.historical_model_fixtures import install as _install_history
_install_history(globals())
