"""Discovery contract only; no nested execution of test suites or real clients."""
import unittest
from scripts.dev import run_tests


def ids(suite):
    for child in suite:
        if isinstance(child,unittest.TestSuite):yield from ids(child)
        else:yield child.id()


class ManagementTestEntryTests(unittest.TestCase):
    def test_management_covers_business_http_and_simulator_without_duplicate_collection(self):
        discovered=list(ids(run_tests.build_suite('management')))
        self.assertEqual(len(discovered),len(set(discovered)))
        for prefix in ('apps.monitoring.tests.','apps.ai_service.tests.','apps.ai_backend.tests.',
                       'apps.management_web.tests.','apps.simulator.tests.'):
            self.assertTrue(any(item.startswith(prefix) for item in discovered),prefix)
        self.assertFalse(any('test_history_qualification.' in item for item in discovered))
        self.assertFalse(any('test_normal_selection_qualification.' in item for item in discovered))
    def test_existing_tier_meanings_are_unchanged(self):
        product=list(ids(run_tests.build_suite('product')))
        self.assertFalse(any(i.startswith('apps.management_web.tests.') for i in product))
        qualification=list(ids(run_tests.build_suite('qualification')))
        self.assertTrue(any('test_normal_selection_qualification.' in i for i in qualification))
        self.assertEqual(len(qualification),len(set(qualification)))
