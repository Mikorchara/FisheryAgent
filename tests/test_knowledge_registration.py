"""Step 5 offline tests: Knowledge Tool registration, injection and its validator.

Registration is not authorization: a bound tool stays unselected by the package
default Policy. The Catalog lists it (Step 6) but still grants no permission.
No network, no real model, no real index.
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fishery_ai.contracts import KnowledgeEvidence, parse_time
from fishery_ai.domain import DiagnosisService
from fishery_ai.model_gateway import ModelToolCall
from fishery_ai.telemetry import CurrentSnapshotStore, CurrentWaterQualityReader
from fishery_ai.tools import ToolError, ToolErrorCode, ToolExecutor, ToolRegistry, ToolStatus
from fishery_ai.tools.handlers.knowledge_search import MAX_QUERY_CHARS
from fishery_ai.tools.handlers.knowledge_search import validate_arguments as handler_validator
from fishery_ai.tools.policy import ToolPolicy, ToolPolicyError, UserToolPolicyStore, load_tool_policies
from fishery_ai.tools.registry import (CURRENT_WATER_QUALITY, KNOWLEDGE_PARAMETERS,
                                       SEARCH_FISHERY_KNOWLEDGE, WATER_QUALITY_SCORE)


NOW = parse_time("2026-10-09T04:00:00Z")
CALL_ID = "call_step5"


class FakeKnowledgeService:
    """Mirrors the real search() signature and records every call."""

    def __init__(self, results=(), *, backend="portable"):
        self.backend = backend
        self._results = tuple(results)
        self.calls = []

    def search(self, query, *, top_k=5, retrieved_at=None, intent_text=None):
        self.calls.append({"query": query, "top_k": top_k})
        return self._results


def evidence():
    return KnowledgeEvidence("wq_dissolved_oxygen", "溶氧适宜范围 5-8 mg/L。", "water_quality",
                             0.31, "legacy:eel_knowledge.json", NOW)


class RegistrationFixture(unittest.TestCase):
    def setUp(self):
        for target in ("socket.socket.connect", "socket.socket.connect_ex", "socket.socket.sendto",
                       "socket.create_connection", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("Step 5 tests forbid network"))
            guard.start()
            self.addCleanup(guard.stop)
        self.store = CurrentSnapshotStore()
        self.reader = CurrentWaterQualityReader(self.store, stale_after_s=300, clock=lambda: NOW)
        self.diagnosis = DiagnosisService()
        self.service = FakeKnowledgeService([evidence()])
        self.registry = ToolRegistry(self.reader, self.diagnosis, knowledge=self.service)
        self.bare = ToolRegistry(self.reader, self.diagnosis)

    def names(self, registry):
        return [definition.name for definition in registry.model_definitions()]

    def execute(self, arguments, *, policy=None):
        payload = arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False)
        policy = policy if policy is not None else ToolPolicy("assistant", True, (SEARCH_FISHERY_KNOWLEDGE,))
        executor = ToolExecutor(self.registry, max_calls=1, policy=policy)
        return executor.execute(ModelToolCall(CALL_ID, SEARCH_FISHERY_KNOWLEDGE, payload))

    def assert_rejected(self, arguments):
        before = len(self.service.calls)
        result = self.execute(arguments)
        self.assertEqual(result.status, ToolStatus.ERROR)
        self.assertEqual(result.error_code, ToolErrorCode.INVALID_TOOL_ARGUMENTS)
        self.assertEqual(len(self.service.calls), before)

    # -- A. registration and injection ---------------------------------------

    def test_name_allowlist_covers_every_known_tool(self):
        self.assertEqual(ToolRegistry.registered_names(),
                         (CURRENT_WATER_QUALITY, WATER_QUALITY_SCORE, SEARCH_FISHERY_KNOWLEDGE))

    def test_registry_without_the_service_does_not_expose_knowledge(self):
        self.assertEqual(self.names(self.bare), [CURRENT_WATER_QUALITY, WATER_QUALITY_SCORE])
        with self.assertRaises(ToolError) as caught:
            self.bare.lookup(SEARCH_FISHERY_KNOWLEDGE)
        self.assertEqual(caught.exception.code, ToolErrorCode.UNKNOWN_TOOL)

    def test_registry_binds_knowledge_once_when_the_service_is_injected(self):
        self.assertEqual(self.names(self.registry),
                         [CURRENT_WATER_QUALITY, WATER_QUALITY_SCORE, SEARCH_FISHERY_KNOWLEDGE])
        definition = self.registry.lookup(SEARCH_FISHERY_KNOWLEDGE)
        self.assertIs(definition.handler.keywords["service"], self.service)
        self.assertIs(definition.validate_arguments, handler_validator)

    def test_declared_schema_is_exactly_the_query_contract(self):
        schema = self.registry.lookup(SEARCH_FISHERY_KNOWLEDGE).model_definition.parameters_dict()
        self.assertEqual(schema, KNOWLEDGE_PARAMETERS)
        self.assertEqual(schema["required"], ["query"])
        self.assertIs(schema["additionalProperties"], False)
        self.assertEqual(schema["properties"]["query"], {"type": "string", "minLength": 1,
                                                         "maxLength": MAX_QUERY_CHARS})

    def test_advertised_names_are_always_resolvable(self):
        for registry in (self.bare, self.registry):
            with self.subTest(bound=len(self.names(registry))):
                advertised = self.names(registry)
                self.assertTrue(set(advertised) <= set(ToolRegistry.registered_names()))
                for name in advertised:
                    self.assertTrue(callable(registry.lookup(name).handler))

    def test_existing_tools_are_untouched_by_the_new_entry(self):
        self.assertEqual(self.names(self.registry)[:2], [CURRENT_WATER_QUALITY, WATER_QUALITY_SCORE])
        for name in (CURRENT_WATER_QUALITY, WATER_QUALITY_SCORE):
            definition = self.registry.lookup(name)
            self.assertEqual(definition.model_definition.parameters_dict(),
                             {"type": "object", "properties": {}, "additionalProperties": False})
            self.assertIsNone(definition.validate_arguments)
            self.assertIn("reader", definition.handler.keywords)

    # -- B. the validator, exercised through the real Executor --------------

    def test_legal_query_reaches_the_service_normalized(self):
        result = self.execute({"query": "  溶氧偏低怎么办  "})
        self.assertEqual(result.status, ToolStatus.OK)
        self.assertIsNone(result.error_code)
        self.assertEqual(self.service.calls, [{"query": "溶氧偏低怎么办", "top_k": 3}])
        self.assertEqual(result.payload["retrieval_mode"], "portable")

    def test_missing_unknown_and_extra_fields_are_rejected(self):
        for arguments in ({}, {"q": "溶氧"}, {"query": "溶氧", "top_k": 9},
                          {"query": "溶氧", "backend": "sklearn"}, {"query": "溶氧", "path": "x"}):
            with self.subTest(arguments=sorted(arguments)):
                self.assert_rejected(arguments)

    def test_wrong_type_is_rejected(self):
        for arguments in ({"query": 123}, {"query": None}, {"query": ["溶氧"]}, {"query": {"a": 1}}):
            with self.subTest(arguments=arguments):
                self.assert_rejected(arguments)

    def test_blank_query_is_rejected(self):
        for query in ("", "   ", "\t", "\n"):
            with self.subTest(query=repr(query)):
                self.assert_rejected({"query": query})

    def test_query_length_boundary(self):
        self.assertEqual(self.execute({"query": "甲" * MAX_QUERY_CHARS}).status, ToolStatus.OK)
        self.assert_rejected({"query": "甲" * (MAX_QUERY_CHARS + 1)})

    def test_control_and_surrogate_characters_are_rejected(self):
        self.assert_rejected({"query": "溶氧\n偏低"})
        self.assert_rejected({"query": "溶氧\x7f偏低"})
        self.assert_rejected('{"query": "\\ud800"}')

    def test_oversized_arguments_never_reach_validation(self):
        oversized = '{"query": "' + "甲" * 1400 + '"}'
        self.assertGreater(len(oversized.encode("utf-8")), 4096)
        self.assert_rejected(oversized)

    def test_unauthorized_knowledge_call_is_still_refused(self):
        result = self.execute({"query": "溶氧"}, policy=ToolPolicy("assistant", True, (CURRENT_WATER_QUALITY,)))
        self.assertEqual(result.error_code, ToolErrorCode.TOOL_NOT_ALLOWED)
        self.assertEqual(self.service.calls, [])

    # -- C. defaults stay closed --------------------------------------------

    def test_package_defaults_grant_nothing_new(self):
        builtin = load_tool_policies()
        self.assertEqual(builtin["assistant"].exposed_tools, (CURRENT_WATER_QUALITY,))
        self.assertEqual(builtin["analysis"].exposed_tools, ())
        self.assertFalse(builtin["analysis"].llm_tool_calling)

    def test_registration_alone_never_authorizes(self):
        # A bound tool stays unauthorized until a Policy selects it.
        self.assertFalse(load_tool_policies()["assistant"].allows(SEARCH_FISHERY_KNOWLEDGE))
        with TemporaryDirectory() as directory:
            store = UserToolPolicyStore(Path(directory), self.registry)
            selected = store.default_selections()["modes"]["assistant"]["selected_tools"]
        self.assertEqual(selected, [CURRENT_WATER_QUALITY])

    def test_override_cannot_select_an_unbound_tool(self):
        with TemporaryDirectory() as directory:
            store = UserToolPolicyStore(Path(directory), self.bare)
            data = store.default_selections()
            data["modes"]["assistant"]["selected_tools"] = [SEARCH_FISHERY_KNOWLEDGE]
            with self.assertRaises(ToolPolicyError) as caught:
                store.save(data)
        self.assertEqual(caught.exception.code, "UNKNOWN_POLICY_TOOL")


if __name__ == "__main__":
    unittest.main()
