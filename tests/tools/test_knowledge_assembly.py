"""Step 8 offline tests: the Knowledge Tool is bound inside the real application.

Exactly one KnowledgeService exists per application and it is shared by the
Analysis path and the read-only Tool. No network, no real model, no real
credential: the app is built over temporary directories and the provider
factory is a mock that fails loudly if it is ever called.
"""

import ast
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from fishery_ai.credentials import CredentialStore
from fishery_ai.knowledge import KnowledgeService
from fishery_ai.tools.catalog import tool_catalog
from fishery_ai.tools.registry import SEARCH_FISHERY_KNOWLEDGE
from fishery_ai.web import create_app

KNOWLEDGE = SEARCH_FISHERY_KNOWLEDGE
WATER = "get_current_water_quality"
SCORE = "score_current_water_quality"
COMPOSITION_ROOTS = {"web.py", "composition.py",
    "development/qualification/real_validation.py",
    "development/qualification/assistant_qualification.py",
    "development/qualification/multi_round_qualification.py"}


from tests.support.paths import PROJECT_ROOT
class KnowledgeAssemblyTests(unittest.TestCase):
    def setUp(self):
        for target in ("socket.socket.connect", "socket.socket.connect_ex", "socket.socket.sendto",
                       "socket.create_connection", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("Step 8 tests forbid network"))
            guard.start(); self.addCleanup(guard.stop)
        temp = TemporaryDirectory(); self.addCleanup(temp.cleanup); self.root = Path(temp.name)
        self.instances = []
        real = KnowledgeService

        def counting(*args, **kwargs):
            service = real(*args, **kwargs)
            self.instances.append(service)
            return service

        with patch("fishery_ai.web.KnowledgeService", side_effect=counting) as factory:
            self.app = create_app(trace_path=self.root / "trace.jsonl",
                custom_profiles_dir=self.root / "profiles",
                capability_evidence_dir=self.root / "evidence",
                manual_experiments_dir=self.root / "experiments",
                scenario_templates_dir=self.root / "scenarios",
                tool_policy_dir=self.root / "policies",
                credential_store=CredentialStore(process_env={}),
                real_gateway_factory=Mock(side_effect=AssertionError("no provider calls")))
        self.builds = factory.call_count
        self.store = self.app.extensions["fishery_tool_policy_store"]
        self.client = self.app.test_client()
        csrf = self.client.get("/api/credential-session").get_json()["csrf_token"]
        self.headers = {"Origin": "http://localhost", "X-CSRF-Token": csrf}

    def catalog(self):
        return self.client.get("/api/tool-policies").get_json()["catalog"]

    def row(self, name):
        return next(item for item in self.catalog() if item["name"] == name)

    def override(self, assistant):
        return {"schema_version": 1, "modes": {"analysis": {"selected_tools": []},
                                               "assistant": {"selected_tools": list(assistant)}}}

    # -- A. one shared service ----------------------------------------------

    def test_application_builds_exactly_one_shared_service(self):
        self.assertEqual(self.builds, 1)
        self.assertEqual(len(self.instances), 1)
        # The single assembly-identity assertion: the bound handler must hold the
        # same object, not a copy. Shape of functools.partial is not asserted further.
        bound = self.store.registry.lookup(KNOWLEDGE).handler.keywords["service"]
        self.assertIs(bound, self.instances[0])

    def test_policy_store_and_http_surface_share_one_registry(self):
        # The store validates overrides against the same Registry the routes execute with.
        # If binding were reordered into a second Registry, these two projections would differ.
        http = [(item["name"], item["registered"], item["executable"]) for item in self.catalog()]
        store = [(item["name"], item["registered"], item["executable"])
                 for item in tool_catalog(self.store.registry)]
        self.assertEqual(http, store)
        self.assertIn((KNOWLEDGE, True, True), http)

    def test_no_second_service_is_constructed_in_the_package(self):
        # Structural guard: only composition roots may construct the service.
        # The qualification CLI is an independent process, not a second Web service.
        root = PROJECT_ROOT / "src/fishery_ai"
        found = {}
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            calls = sum(1 for node in ast.walk(tree) if isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name) and node.func.id == "KnowledgeService")
            if calls:
                found[str(path.relative_to(root)).replace("\\", "/")] = calls
        self.assertEqual(set(found), COMPOSITION_ROOTS)
        self.assertTrue(all(count == 1 for count in found.values()))

    # -- B. the real runtime finally marks it executable --------------------

    def test_real_runtime_marks_the_knowledge_tool_executable(self):
        item = self.row(KNOWLEDGE)
        self.assertTrue(item["registered"])
        self.assertTrue(item["executable"])
        self.assertFalse(item["dev_only"])
        self.assertEqual(item["access_type"], "READ ONLY")
        for name in (WATER, SCORE):
            self.assertTrue(self.row(name)["executable"])

    # -- C. defaults are unchanged ------------------------------------------

    def test_defaults_still_authorize_nothing_new(self):
        payload = self.client.get("/api/tool-policies").get_json()["policy"]
        self.assertEqual(payload["source"], "BUILTIN_DEFAULT")
        self.assertEqual(payload["modes"]["assistant"]["selected_tools"], [WATER])
        self.assertEqual(payload["modes"]["analysis"]["selected_tools"], [])
        effective = self.store.effective()
        self.assertEqual(effective["assistant"].exposed_tools, (WATER,))
        self.assertEqual(effective["analysis"].exposed_tools, ())
        for mode in ("analysis", "assistant"):
            self.assertFalse(effective[mode].allows(KNOWLEDGE))
        self.assertFalse(self.store.path.exists())

    # -- D. explicit opt-in through the real HTTP surface -------------------

    def test_user_opt_in_and_reset_round_trip(self):
        response = self.client.put("/api/tool-policies", json=self.override([WATER, KNOWLEDGE]),
                                   headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.store.effective()["assistant"].exposed_tools, (WATER, KNOWLEDGE))
        payload = self.client.get("/api/tool-policies").get_json()["policy"]
        self.assertEqual(payload["source"], "USER_OVERRIDE")
        self.assertEqual(payload["modes"]["assistant"]["selected_tools"], [WATER, KNOWLEDGE])
        self.assertTrue(self.store.path.exists())
        reset = self.client.delete("/api/tool-policies", json={}, headers=self.headers)
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(self.store.effective()["assistant"].exposed_tools, (WATER,))
        self.assertFalse(self.store.path.exists())

    def test_restart_keeps_the_saved_opt_in(self):
        self.client.put("/api/tool-policies", json=self.override([KNOWLEDGE]), headers=self.headers)
        before = (self.root / "policies" / "tool_policies.json").read_bytes()
        restarted = create_app(trace_path=self.root / "restart-trace.jsonl",
            custom_profiles_dir=self.root / "profiles",
            capability_evidence_dir=self.root / "evidence",
            manual_experiments_dir=self.root / "experiments",
            scenario_templates_dir=self.root / "scenarios",
            tool_policy_dir=self.root / "policies",
            credential_store=CredentialStore(process_env={}),
            real_gateway_factory=Mock(side_effect=AssertionError("no provider calls")))
        store = restarted.extensions["fishery_tool_policy_store"]
        self.assertEqual(store.effective()["assistant"].exposed_tools, (KNOWLEDGE,))
        self.assertEqual((self.root / "policies" / "tool_policies.json").read_bytes(), before)
        rows = {item["name"]: item["executable"] for item in
                restarted.test_client().get("/api/tool-policies").get_json()["catalog"]}
        self.assertEqual(rows, {WATER: True, SCORE: True, KNOWLEDGE: True})
        self.assertEqual(json.loads(before)["modes"]["assistant"]["selected_tools"], [KNOWLEDGE])
