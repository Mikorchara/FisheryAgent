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
)


def build_suite(selection):
    loader = unittest.TestLoader()
    if selection == "fast":
        return loader.loadTestsFromNames(FAST_MODULES)
    groups = PRODUCT_GROUPS if selection == "product" else (
        (*PRODUCT_GROUPS, "qualification") if selection == "all" else (selection,))
    return unittest.TestSuite(loader.discover(str(ROOT / "tests" / group),
        top_level_dir=str(ROOT)) for group in groups)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline unittest tiers; no Provider requests")
    parser.add_argument("selection", nargs="?", default="product",
        choices=("fast", "product", "qualification", "all", *PRODUCT_GROUPS))
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
