"""Mode policies are restrictions, not registration or model capability evidence."""
import ast
from dataclasses import FrozenInstanceError
from importlib.resources import files
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import tomllib
import unittest
from unittest.mock import Mock, patch

from fishery_ai.composition import build_offline_demo
from fishery_ai.contracts import AnalysisRequest, Mode, Status
from fishery_ai.credentials import CredentialStore
from fishery_ai.domain import DiagnosisService
from fishery_ai.model_gateway import ModelCapabilities, ModelProfile, ModelResponse, ModelToolCall, MockGateway, ProfileRegistry
from fishery_ai.model_options import Support
from fishery_ai.observability import JsonlTraceSink
from fishery_ai.providers import AuthSpec
from fishery_ai.telemetry import CurrentSnapshotStore, CurrentWaterQualityReader
from fishery_ai.tool_conversation import MockToolGateway, ToolCallingService
from fishery_ai.tool_policy import ToolPolicy, ToolPolicyError, load_tool_policies, parse_tool_policies
from fishery_ai.tools import ToolExecutor, ToolRegistry
from fishery_ai.web import create_app

NAME = "get_current_water_quality"


class ToolPolicyTests(unittest.TestCase):
    def setUp(self):
        for name in ("socket.socket.connect", "socket.socket.connect_ex", "socket.socket.sendto",
                     "socket.create_connection", "socket.getaddrinfo"):
            guard = patch(name, side_effect=AssertionError("Tool Policy tests forbid network"))
            guard.start()
            self.addCleanup(guard.stop)
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.reader = CurrentWaterQualityReader(CurrentSnapshotStore(), stale_after_s=300)
        self.registry = ToolRegistry(self.reader, DiagnosisService())
        self.policies = load_tool_policies()
        self.profile = ModelProfile("policy-fixture", "Offline policy fixture", "mock", "http://mock.invalid/v1",
            "fictional-model", auth_spec=AuthSpec.NONE, capabilities=ModelCapabilities(tool_calling=Support.SUPPORTED,
                service_id="custom", adapter_id="generic_openai_chat", base_url="http://mock.invalid/v1", model_id="fictional-model"))
        self.runtime = ProfileRegistry([self.profile], CredentialStore(process_env={})).snapshot(self.profile.profile_id)
        self.traces = JsonlTraceSink(self.root / "tools.jsonl")

    def config(self):
        return json.loads(files("fishery_ai").joinpath("resources/tools/tool_policies.json").read_text(encoding="utf-8"))

    def test_analysis_exposes_no_tools_assistant_only_current_quality(self):
        self.assertEqual(self.policies["analysis"].model_definitions(self.registry), ())
        self.assertFalse(self.policies["analysis"].llm_tool_calling)
        self.assertEqual([item.name for item in self.policies["assistant"].model_definitions(self.registry)], [NAME])
        self.assertEqual(self.registry.registered_names(), (NAME,))
        self.assertFalse(hasattr(self.registry, "register"))

    def test_unknown_tool_name_fails_closed_without_echo(self):
        data = self.config()
        data["modes"]["assistant"]["exposed_tools"] = ["shell:private-unknown-function"]
        with self.assertRaises(ToolPolicyError) as error:
            parse_tool_policies(data)
        self.assertEqual(str(error.exception), "UNKNOWN_POLICY_TOOL")
        self.assertNotIn("private", str(error.exception))
        self.assertEqual(self.registry.registered_names(), (NAME,))

    def test_policy_cannot_register_handler_import_module_or_function(self):
        for name in ("module", "handler", "import", "function_path", "eval", "exec"):
            data = self.config()
            data["modes"]["assistant"][name] = "fake.private.function"
            with self.subTest(name=name), self.assertRaises(ToolPolicyError):
                parse_tool_policies(data)
        self.assertEqual([d.name for d in self.registry.model_definitions()], [NAME])

    def test_bad_schema_mode_types_and_duplicate_tools_fail_closed(self):
        for value in ("false", 1, None):
            data = self.config()
            data["modes"]["assistant"]["llm_tool_calling"] = value
            with self.subTest(value=value), self.assertRaises(ToolPolicyError):
                parse_tool_policies(data)
        for names in (NAME, [NAME, NAME], [None]):
            data = self.config()
            data["modes"]["assistant"]["exposed_tools"] = names
            with self.assertRaises(ToolPolicyError):
                parse_tool_policies(data)
        for schema in (True, 2, "1"):
            data = self.config(); data["schema_version"] = schema
            with self.assertRaises(ToolPolicyError):
                parse_tool_policies(data)

    def test_policy_is_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            self.policies["assistant"].exposed_tools = ()
        with self.assertRaises(TypeError):
            self.policies["analysis"] = self.policies["assistant"]

    def test_analysis_cannot_be_enabled_by_configuration(self):
        data = self.config()
        data["modes"]["analysis"] = {"llm_tool_calling":True, "exposed_tools":[NAME]}
        with self.assertRaises(ToolPolicyError) as error:
            parse_tool_policies(data)
        self.assertEqual(error.exception.code, "ANALYSIS_TOOL_POLICY_INVALID")

    def test_web_startup_rejects_unknown_policy_before_gateway(self):
        data = self.config(); data["modes"]["assistant"]["exposed_tools"] = ["unknown_tool"]
        resource = Mock(); resource.joinpath.return_value.read_text.return_value = json.dumps(data)
        factory = Mock(side_effect=AssertionError("no real client"))
        with patch("fishery_ai.tool_policy.files", return_value=resource), self.assertRaises(ToolPolicyError):
            create_app(credential_store=CredentialStore(process_env={}), real_gateway_factory=factory,
                custom_profiles_dir=self.root / "profiles", capability_evidence_dir=self.root / "evidence",
                scenario_templates_dir=self.root / "templates", manual_experiments_dir=self.root / "experiments")
        factory.assert_not_called()

    def test_resource_is_packaged_with_fixed_name(self):
        resource = files("fishery_ai").joinpath("resources/tools/tool_policies.json")
        self.assertTrue(resource.is_file())
        config = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn("resources/tools/*.json", config["tool"]["setuptools"]["package-data"]["fishery_ai"])

    def test_analysis_normal_and_streaming_have_empty_tool_request(self):
        app, _ = build_offline_demo(trace_path=self.root / "analysis.jsonl")
        seen = []
        class Capture(MockGateway):
            def complete(gateway, request, runtime):
                seen.append(request)
                return super().complete(request, runtime)
            def stream(gateway, request, runtime):
                seen.append(request)
                yield from super().stream(request, runtime)
        app.gateway = Capture()
        with patch("fishery_ai.tool_conversation.ToolExecutor", side_effect=AssertionError("Analysis cannot create Executor")), \
             patch("fishery_ai.tool_conversation.ToolCallingService", side_effect=AssertionError("Analysis cannot use Assistant")):
            normal = app.analyze(AnalysisRequest(Mode.CHAT, "cloud-demo", "现在水质怎么样？"))
            streaming = list(app.analyze_stream(AnalysisRequest(Mode.ADVICE, "cloud-demo", "当前建议")))
        self.assertEqual(normal.status, Status.COMPLETED)
        self.assertEqual(streaming[-1].kind, "completed")
        for request in seen:
            self.assertEqual(request.tools, ())
            self.assertIsNone(request.tool_choice)
            self.assertIn("Observed Facts", request.messages[-1].content)
            self.assertIn("Rule Results", request.messages[-1].content)
            self.assertIn("RAG Evidence", request.messages[-1].content)
        self.assertFalse(hasattr(app, "registry"))
        self.assertFalse(hasattr(app, "executor"))

    def test_analysis_unsolicited_tool_call_is_rejected(self):
        app, _ = build_offline_demo(trace_path=self.root / "analysis.jsonl")
        app.gateway = MockGateway(responses=(ModelResponse(None, tool_calls=(ModelToolCall("c1", NAME, "{}"),)),))
        result = app.analyze(AnalysisRequest(Mode.CHAT, "cloud-demo", "当前水质？"))
        self.assertEqual(result.error_code, "UNEXPECTED_TOOL_CALL")
        self.assertFalse(result.structured_parse_ok)

    def test_assistant_definitions_are_policy_filtered_registry_objects(self):
        definition = self.registry.model_definitions()[0]
        gateway = MockToolGateway()
        with patch.object(self.registry, "model_definitions", return_value=(definition,)):
            service = ToolCallingService(gateway, self.registry, self.traces)
            result = service.converse("现在水质怎么样？", self.runtime)
        self.assertEqual(result.status, Status.COMPLETED)
        self.assertEqual(result.tool_result.status.value, "NO_DATA")
        self.assertEqual(result.request_2.outcome, "final_answer")
        self.assertTrue(service.policy.allows(NAME))

    def test_registered_but_disallowed_call_never_executes(self):
        policy = ToolPolicy("assistant", True, ())
        with patch.object(self.reader, "query", side_effect=AssertionError("disallowed Tool must not read")):
            result = ToolExecutor(self.registry, policy=policy).execute(ModelToolCall("c1", NAME, "{}"))
        self.assertEqual(result.error_code.value, "TOOL_NOT_ALLOWED")
        self.assertEqual(policy.model_definitions(self.registry), ())

    def test_model_cannot_bypass_policy_even_for_registered_tool(self):
        gateway = Mock(complete=Mock(return_value=ModelResponse(None, tool_calls=(ModelToolCall("c1", NAME, "{}"),))))
        result = ToolCallingService(gateway, self.registry, self.traces,
            policy=ToolPolicy("assistant", True, ())).converse("当前水质？", self.runtime)
        self.assertEqual(result.error_code, "TOOL_NOT_ALLOWED")
        self.assertEqual(gateway.complete.call_count, 1)
        self.assertEqual(gateway.complete.call_args.args[0].tools, ())

    def test_unknown_tool_remains_registry_error(self):
        result = ToolExecutor(self.registry).execute(ModelToolCall("c1", "shell", "{}"))
        self.assertEqual(result.error_code.value, "UNKNOWN_TOOL")

    def test_safety_no_dynamic_loading_in_policy(self):
        import fishery_ai.tool_policy as module
        source = Path(module.__file__).read_text(encoding="utf-8")
        calls = [node.func for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)]
        self.assertFalse(any(isinstance(node, ast.Name) and node.id in ("exec", "eval", "__import__") for node in calls))
        self.assertFalse(any(isinstance(node, ast.Attribute) and node.attr in ("import_module", "system", "popen") for node in calls))


if __name__ == "__main__":
    unittest.main()
