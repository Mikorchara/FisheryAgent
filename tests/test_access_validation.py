"""Explicit real-smoke entry is offline by default and shares frozen R2 composition."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
from unittest.mock import patch
import json
import unittest

import test_execution
from scripts import validate_access_modes as validation
from fishery_ai.credentials import CredentialStore


class AccessValidationTests(unittest.TestCase):
    def setUp(self):
        test_execution.ExecutionTests.setUp(self)

    def test_default_entry_never_resolves_credentials_or_sends_network(self):
        output = StringIO()
        with patch("sys.argv", ["validate_access_modes.py"]), \
             patch.object(validation, "private_project_location") as location, \
             patch.object(validation, "run_validation") as execute, redirect_stdout(output):
            self.assertEqual(validation.main(), 2)
        location.assert_not_called()
        execute.assert_not_called()
        self.assertEqual(output.getvalue().strip(), "NETWORK_CONFIRMATION_REQUIRED")

    def run_fake(self, process):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy = root / ".env"
            legacy.write_text("DASHSCOPE_API_KEY=fictional-legacy-must-not-read\n", encoding="utf-8")
            env_file = root / "private" / ".env"
            location = NS(env_path=env_file)
            store = CredentialStore(env_file, process_env=process)
            snapshots = []
            class Client:
                def __init__(self):
                    self.chat = NS(completions=NS(create=self.create))
                    self._client = NS(event_hooks={"request":[]})
                    self.closed = False
                async def create(self, **kwargs):
                    return NS(choices=[NS(message=NS(content="OK"))], model=kwargs["model"], usage=None)
                async def post(self, _, **kwargs):
                    body = kwargs["body"]
                    return NS(model_dump=lambda **_: {"model":body["model"],"choices":[{"message":{"content":"OK"}}]}, usage=None)
                async def close(self):
                    self.closed = True
                def is_closed(self):
                    return self.closed
            def sdk(runtime, _):
                snapshots.append(runtime)
                return Client()
            original_read = Path.read_text
            def only_private_or_source(path, *args, **kwargs):
                if path == legacy:
                    raise AssertionError("legacy project dotenv must not be read")
                return original_read(path, *args, **kwargs)
            with patch.object(validation, "private_project_location", return_value=location) as fixed, \
                 patch.object(validation, "CredentialStore", return_value=store) as composition, \
                 patch.object(validation.OpenAICompatibleAdapter, "_make_async_client", sdk), \
                 patch.object(validation.time, "sleep", lambda *_:None), \
                 patch.object(Path, "read_text", only_private_or_source), \
                 patch.object(Path, "cwd", return_value=root):
                result = validation.run_validation()
            fixed.assert_called_once_with(root)
            composition.assert_called_once_with(env_file, private_location=location)
            self.assertEqual(legacy.read_text(), "DASHSCOPE_API_KEY=fictional-legacy-must-not-read\n")
            self.assertNotIn("fictional-legacy-must-not-read", json.dumps(result))
            return result, snapshots

    def test_composition_process_priority_no_legacy_and_bounded_requests(self):
        data, snapshots = self.run_fake({"DASHSCOPE_API_KEY":"fictional-process-only"})
        self.assertEqual(len(data["cases"]), 4)
        self.assertLessEqual(sum(case["sdk_attempts"] for case in data["cases"]), 4)
        cloud = next(item for item in snapshots if item.provider_kind == "cloud")
        self.assertEqual(cloud.credential.status.source, "PROCESS_ENV")
        self.assertEqual(cloud.credential._for_adapter(), "fictional-process-only")
        self.assertTrue(all(item.max_retries == 0 for item in snapshots))
        self.assertNotIn("fictional-process-only", json.dumps(data))

    def test_missing_fails_closed_despite_legacy_file(self):
        data, snapshots = self.run_fake({})
        cloud = data["cases"][0]
        self.assertEqual(cloud["error_code"], "SECRET_MISSING")
        self.assertEqual(cloud["sdk_attempts"], 0)
        self.assertTrue(all(item.provider_kind == "local" for item in snapshots))


# Explicit historical fixtures; not active startup assets.
from historical_model_fixtures import install as _install_history
_install_history(globals())
