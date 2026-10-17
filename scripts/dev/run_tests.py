"""Small offline unittest entry: product by default, qualification separately."""
import argparse
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PRODUCT_GROUPS = ("assistant", "domain", "providers", "security", "tools", "web")
FAST_MODULES = (
    "tests.assistant.test_history_projection",
    "tests.assistant.test_assistant_sources",
    "tests.domain.test_current_water_quality",
    "tests.domain.test_water_quality_scoring",
    "tests.domain.test_telemetry_simulator",
    "tests.providers.test_protocol_specs",
    "tests.tools.test_tool_argument_contract",
    "tests.tools.test_tool_status_no_match",
    "tests.tools.test_tool_policy",
    "apps.ai_backend.tests.test_protocol_specs",
    "apps.ai_service.runtime.tests.test_foundation",
)


def build_suite(selection):
    loader = unittest.TestLoader()
    if selection == "fast":
        return loader.loadTestsFromNames(FAST_MODULES)
    if selection == "backend":
        suite = unittest.TestSuite(loader.discover(str(ROOT / group), top_level_dir=str(ROOT))
            for group in ("apps/ai_backend/tests", "apps/ai_service/runtime/tests"))
        suite.addTests(loader.loadTestsFromNames(tuple("apps.ai_service.tests." + name for name in (
            "test_service", "test_execution", "test_streaming_config", "test_backend_migration", "test_business_tools",
            "test_water_history_tool", "test_management_policy", "test_history_candidate", "test_normal_selection"))))
        return suite
    groups = PRODUCT_GROUPS if selection == "product" else (
        (*PRODUCT_GROUPS, "qualification") if selection == "all" else (selection,))
    suite = unittest.TestSuite(loader.discover(str(ROOT / "tests" / group),
        top_level_dir=str(ROOT)) for group in groups)
    if selection in ("product", "all"):
        suite.addTests(build_suite("backend"))
    if selection in ("qualification", "all"):
        suite.addTests(loader.loadTestsFromName("apps.ai_service.tests.test_streaming_qualification"))
        suite.addTests(loader.loadTestsFromName("apps.ai_service.tests.test_history_qualification"))
        suite.addTests(loader.loadTestsFromName("apps.ai_service.tests.test_history_batch"))
    return suite


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline unittest tiers; no Provider requests")
    parser.add_argument("selection", nargs="?", default="product",
        choices=("fast", "product", "qualification", "all", "backend", *PRODUCT_GROUPS))
    parser.add_argument("--list", action="store_true", help="Count discovery without executing tests")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    suite = build_suite(args.selection)
    count = suite.countTestCases()
    if count == 0:
        parser.error("empty test suite")
    print(f"{args.selection}: {count} unittest cases", flush=True)
    if args.list:
        return 0
    started = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
    print(f"{args.selection}: {result.testsRun} cases / {time.perf_counter()-started:.3f}s", flush=True)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
