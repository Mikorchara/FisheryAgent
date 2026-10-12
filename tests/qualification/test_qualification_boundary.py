"""Qualification is explicit development tooling, not a product dependency."""

import ast
import importlib
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from tests.support.paths import PROJECT_ROOT


MODULES = (
    "assistant_qualification", "qualification_adapter", "qualification_history",
    "qualification_migration", "qualification_projection",
    "preset_tool_qualification", "real_validation",
)
BOUNDARY = "fishery_ai.development.qualification"


class QualificationBoundaryTests(unittest.TestCase):
    def fresh_process(self, code):
        # Only local imports: fail before DNS or socket I/O can begin.
        guard = """
import socket
def deny(*args, **kwargs):
    raise AssertionError('boundary tests forbid network')
socket.create_connection = socket.getaddrinfo = deny
socket.socket.connect = socket.socket.connect_ex = socket.socket.sendto = deny
"""
        result = subprocess.run([sys.executable, "-c", guard + code],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_development_package_import_is_inert(self):
        self.fresh_process("""
import sys
import fishery_ai.development.qualification
assert not any(name.startswith('fishery_ai.development.qualification.') for name in sys.modules)
assert 'fishery_ai.credentials' not in sys.modules
assert 'fishery_ai.assistant' not in sys.modules
""")

    def test_formal_runtime_imports_do_not_load_qualification(self):
        self.fresh_process("""
import sys
import fishery_ai.web, fishery_ai.assistant, fishery_ai.application, fishery_ai.__main__
assert not any(name.startswith('fishery_ai.development') for name in sys.modules)
assert not any('qualification' in name for name in sys.modules if name.startswith('fishery_ai.'))
assert 'fishery_ai.real_validation' not in sys.modules
""")

    def test_legacy_aliases_preserve_module_identity(self):
        for name in MODULES:
            with self.subTest(module=name):
                legacy = importlib.import_module("fishery_ai." + name)
                canonical = importlib.import_module(BOUNDARY + "." + name)
                self.assertIs(legacy, canonical)
                self.assertEqual(canonical.__name__, BOUNDARY + "." + name)

    def test_legacy_private_symbols_and_monkeypatches_still_work(self):
        legacy = importlib.import_module("fishery_ai.real_validation")
        canonical = importlib.import_module(BOUNDARY + ".real_validation")
        self.assertIs(legacy._request, canonical._request)
        sentinel = object()
        original = canonical.RESOURCE_ROOT
        with patch("fishery_ai.real_validation.RESOURCE_ROOT", sentinel):
            self.assertIs(canonical.RESOURCE_ROOT, sentinel)
            self.assertIs(canonical.run_real_validation.__globals__["RESOURCE_ROOT"], sentinel)
        self.assertIs(canonical.RESOURCE_ROOT, original)

    def test_product_modules_have_no_development_dependency_except_lazy_cli(self):
        root = PROJECT_ROOT / "src/fishery_ai"
        imports = []
        for path in root.rglob("*.py"):
            relative = path.relative_to(root)
            if relative.parts[0] == "development" or path.stem in MODULES:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    parts = module.split(".") + [item.name for item in node.names]
                elif isinstance(node, ast.Import):
                    parts = [part for item in node.names for part in item.name.split(".")]
                else:
                    continue
                if "development" in parts or any(name in parts for name in MODULES):
                    imports.append((relative.as_posix(), node.lineno))
        cli = ast.parse((root / "__main__.py").read_text(encoding="utf-8"))
        branch = next(node for node in ast.walk(cli) if isinstance(node, ast.If)
            and ast.unparse(node.test) == "args.command == 'validate-real'")
        expected = next(node for node in branch.body if isinstance(node, ast.ImportFrom))
        self.assertEqual(imports, [("__main__.py", expected.lineno)])

    def test_validate_real_cli_dispatches_to_canonical_module_without_consent(self):
        from fishery_ai import __main__
        with patch.object(sys, "argv", ["fishery_ai", "validate-real"]), \
             patch(BOUNDARY + ".real_validation.run_real_validation", return_value=2) as run:
            with self.assertRaises(SystemExit) as error:
                __main__.main()
        self.assertEqual(error.exception.code, 2)
        run.assert_called_once_with(check="basic", scenario="low_oxygen", confirm_network=False)

    def test_maintained_scripts_import_canonical_boundary(self):
        for filename, module in (
            ("qualify_assistant_turn.py", "assistant_qualification"),
            ("qualify_preset_tools.py", "preset_tool_qualification"),
        ):
            with self.subTest(script=filename):
                path = PROJECT_ROOT / "scripts/qualification" / filename
                tree = ast.parse(path.read_text(encoding="utf-8"))
                imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
                self.assertIn(BOUNDARY + "." + module, imports)
                self.assertNotIn("fishery_ai." + module, imports)

    def test_resource_anchors_remain_in_product_package(self):
        from importlib.resources import files
        validation = importlib.import_module(BOUNDARY + ".real_validation")
        self.assertEqual(validation.RESOURCE_ROOT, files("fishery_ai").joinpath("resources"))


if __name__ == "__main__":
    unittest.main()
