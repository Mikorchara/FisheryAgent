"""Step 6 offline tests: the Catalog lists the Knowledge Tool but grants nothing.

The Catalog is display metadata. It may describe a tool and report whether this
instance happens to bind it; it must never become a second source of handlers,
of schemas, or of execution permission.
"""

from dataclasses import fields
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fishery_ai.contracts import parse_time
from fishery_ai.domain import DiagnosisService
from fishery_ai.telemetry import CurrentSnapshotStore, CurrentWaterQualityReader
from fishery_ai.tools import ToolRegistry
from fishery_ai.tools.catalog import CATALOG, ToolCatalogEntry, tool_catalog
from fishery_ai.tools.policy import ToolPolicyError, UserToolPolicyStore, load_tool_policies
from fishery_ai.tools.registry import (CURRENT_WATER_QUALITY, SEARCH_FISHERY_KNOWLEDGE,
                                       WATER_QUALITY_SCORE)


NOW = parse_time("2026-10-09T06:00:00Z")
# The default an entry gets when a tool takes no parameters at all.
PARAMETERLESS_SUMMARY = ToolCatalogEntry("fixture", "Fixture", "简介", "说明").parameter_summary


class FakeKnowledgeService:
    backend = "portable"

    def search(self, query, *, top_k=5, retrieved_at=None, intent_text=None):
        return ()


class CatalogFixture(unittest.TestCase):
    def setUp(self):
        for target in ("socket.socket.connect", "socket.socket.connect_ex", "socket.socket.sendto",
                       "socket.create_connection", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("Step 6 tests forbid network"))
            guard.start()
            self.addCleanup(guard.stop)
        store = CurrentSnapshotStore()
        reader = CurrentWaterQualityReader(store, stale_after_s=300, clock=lambda: NOW)
        diagnosis = DiagnosisService()
        self.bound = ToolRegistry(reader, diagnosis, knowledge=FakeKnowledgeService())
        self.unbound = ToolRegistry(reader, diagnosis)

    def entry(self, registry, name):
        return next(item for item in tool_catalog(registry) if item["name"] == name)

    # -- A. what the Catalog lists -------------------------------------------

    def test_catalog_lists_every_known_tool_in_declared_order(self):
        expected = [CURRENT_WATER_QUALITY, WATER_QUALITY_SCORE, SEARCH_FISHERY_KNOWLEDGE]
        self.assertEqual([item["name"] for item in tool_catalog(self.bound)], expected)
        # Listing is static: an unbound instance still *describes* the tool.
        self.assertEqual([item["name"] for item in tool_catalog(self.unbound)], expected)

    def test_knowledge_entry_metadata_is_explicit(self):
        item = self.entry(self.bound, SEARCH_FISHERY_KNOWLEDGE)
        self.assertEqual(item["display_name"], "知识检索")
        self.assertEqual(item["access_type"], "READ ONLY")
        self.assertFalse(item["dev_only"])
        self.assertFalse(item["planned"])
        self.assertIn("不代表当前水质", item["short_description"])
        self.assertIn("NO_MATCH", item["detailed_description"])
        self.assertIn("legacy:eel_knowledge.json", item["detailed_description"])

    def test_knowledge_entry_is_not_flagged_as_a_scoring_standard(self):
        # "experimental" renders in the UI as "NOT PROFESSIONAL STANDARD", which is
        # a scoring claim. Knowledge search makes no scoring claim.
        self.assertFalse(self.entry(self.bound, SEARCH_FISHERY_KNOWLEDGE)["experimental"])

    def test_knowledge_parameter_summary_is_not_the_parameterless_default(self):
        item = self.entry(self.bound, SEARCH_FISHERY_KNOWLEDGE)
        self.assertNotEqual(item["parameter_summary"], PARAMETERLESS_SUMMARY)
        self.assertIn("query", item["parameter_summary"])
        for name in (CURRENT_WATER_QUALITY, WATER_QUALITY_SCORE):
            self.assertEqual(self.entry(self.bound, name)["parameter_summary"], PARAMETERLESS_SUMMARY)

    # -- B. derived flags follow the Registry, not the Catalog ---------------

    def test_executable_flag_follows_the_registry_binding(self):
        bound = self.entry(self.bound, SEARCH_FISHERY_KNOWLEDGE)
        self.assertTrue(bound["registered"])
        self.assertTrue(bound["executable"])
        unbound = self.entry(self.unbound, SEARCH_FISHERY_KNOWLEDGE)
        self.assertFalse(unbound["registered"])
        self.assertFalse(unbound["executable"])

    def test_entry_names_stay_inside_the_registry_name_allowlist(self):
        known = set(self.bound.registered_names())
        self.assertEqual({item.name for item in CATALOG}, known)

    def test_modes_have_one_authority_and_no_per_tool_rule(self):
        for registry in (self.bound, self.unbound):
            for item in tool_catalog(registry):
                self.assertEqual(item["modes"], ["analysis", "assistant"])
        # No per-entry mode field exists, so modes cannot drift per tool.
        self.assertNotIn("modes", {field.name for field in fields(ToolCatalogEntry)})

    # -- C. the Catalog never authorizes -------------------------------------

    def test_catalog_alone_cannot_grant_execution(self):
        with TemporaryDirectory() as directory:
            store = UserToolPolicyStore(Path(directory), self.unbound)
            data = store.default_selections()
            data["modes"]["assistant"]["selected_tools"] = [SEARCH_FISHERY_KNOWLEDGE]
            with self.assertRaises(ToolPolicyError):
                store.save(data)

    def test_bound_knowledge_becomes_user_selectable(self):
        with TemporaryDirectory() as directory:
            store = UserToolPolicyStore(Path(directory), self.bound)
            data = store.default_selections()
            data["modes"]["assistant"]["selected_tools"] = [SEARCH_FISHERY_KNOWLEDGE]
            store.save(data)
            effective = store.effective()
        self.assertEqual(effective["assistant"].exposed_tools, (SEARCH_FISHERY_KNOWLEDGE,))

    def test_catalog_entry_does_not_change_package_defaults(self):
        self.assertEqual(load_tool_policies()["assistant"].exposed_tools, (CURRENT_WATER_QUALITY,))
        self.assertEqual(load_tool_policies()["analysis"].exposed_tools, ())
        with TemporaryDirectory() as directory:
            store = UserToolPolicyStore(Path(directory), self.bound)
            self.assertFalse(store.path.exists())
            defaults = store.default_selections()["modes"]
            effective = store.effective()
        self.assertEqual(defaults["assistant"]["selected_tools"], [CURRENT_WATER_QUALITY])
        self.assertEqual(defaults["analysis"]["selected_tools"], [])
        self.assertEqual(effective["assistant"].exposed_tools, (CURRENT_WATER_QUALITY,))
        self.assertEqual(effective["analysis"].exposed_tools, ())
