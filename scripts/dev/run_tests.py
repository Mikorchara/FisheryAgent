"""Small offline unittest entry: product by default, qualification separately."""
import argparse
from pathlib import Path
import sys
import shutil
import subprocess
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
    if selection == "management":
        suite = build_suite("backend")
        # These existing test directories are namespace packages (no __init__).
        # Use the same unittest loader without changing their package structure.
        names = tuple('.'.join(path.relative_to(ROOT).with_suffix('').parts)
            for group in ("apps/monitoring/tests", "apps/simulator/tests", "apps/knowledge/tests", "apps/management_web/tests")
            for path in sorted((ROOT / group).glob('test_*.py')))
        suite.addTests(loader.loadTestsFromNames(names))
        return suite
    if selection == "backend":
        suite = unittest.TestSuite(loader.discover(str(ROOT / group), top_level_dir=str(ROOT))
            for group in ("apps/ai_backend/tests", "apps/ai_service/runtime/tests"))
        suite.addTests(loader.loadTestsFromNames(tuple("apps.ai_service.tests." + name for name in (
            "test_service", "test_execution", "test_streaming_config", "test_backend_migration", "test_business_tools",
            "test_water_history_tool", "test_management_policy", "test_history_candidate", "test_normal_selection", "test_unified_tools"))))
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
        suite.addTests(loader.loadTestsFromName("apps.ai_service.tests.test_normal_selection_qualification"))
    return suite


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline unittest tiers; no Provider requests")
    parser.add_argument("selection", nargs="?", default="product",
        choices=("fast", "product", "qualification", "all", "backend", "management", *PRODUCT_GROUPS))
    parser.add_argument("--list", action="store_true", help="Count discovery without executing tests")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    suite = build_suite(args.selection)
    count = suite.countTestCases()
    if count == 0:
        parser.error("empty test suite")
    print(f"{args.selection}: {count} unittest cases", flush=True)
    node_files = sorted((ROOT / "apps/management_web/tests").glob("*.test.mjs")) if args.selection == "management" else []
    if node_files:
        print(f"management: {len(node_files)} Node test files (offline)", flush=True)
    if args.list:
        return 0
    started = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
    print(f"{args.selection}: {result.testsRun} cases / {time.perf_counter()-started:.3f}s", flush=True)
    node_result = 0
    if node_files:
        node = shutil.which("node")
        if node is None:
            print("management: NODE_REQUIRED", flush=True)
            return 1
        node_result = subprocess.run([node, "--test", *map(str, node_files)], cwd=ROOT).returncode
    return 0 if result.wasSuccessful() and node_result == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
