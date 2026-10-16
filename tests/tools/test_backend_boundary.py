"""Backend leaf ownership, legacy identity and installed-layout import contracts."""
import ast
import importlib
import json
import pickle
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import tomllib
import unittest
from unittest.mock import patch

from tests.support.paths import PROJECT_ROOT


CANONICAL = 'apps.ai_backend.tool_argument_diagnostics'
LEGACY = 'fishery_ai.tool_argument_diagnostics'


class BackendBoundaryTests(unittest.TestCase):
    def fresh(self, code, *, cwd=PROJECT_ROOT):
        guard = """
import socket
def deny(*args, **kwargs): raise AssertionError('backend tests forbid network')
socket.create_connection = socket.getaddrinfo = deny
socket.socket.connect = socket.socket.connect_ex = socket.socket.sendto = deny
"""
        result = subprocess.run([sys.executable, '-I', '-c', guard+code], cwd=cwd,
            capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_backend_import_is_inert_and_independent_of_product_or_business_modules(self):
        self.fresh(f"""
import sys
sys.path.insert(0,{str(PROJECT_ROOT)!r})
import {CANONICAL}
assert not any(n.startswith(('fishery_ai','flask','apps.monitoring','apps.ai_service',
    'apps.management_web','openai','httpx','sqlite3')) for n in sys.modules)
""")
        package=PROJECT_ROOT/'apps/ai_backend'
        for path in package.glob('*.py'):
            tree=ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node,ast.ImportFrom):
                    self.assertEqual(node.level,0)
                    self.assertIn(node.module,sys.stdlib_module_names,path.name)
                elif isinstance(node,ast.Import):
                    for alias in node.names:
                        self.assertIn(alias.name.split('.')[0],sys.stdlib_module_names,path.name)

    def test_old_and_new_paths_are_one_module_in_both_import_orders(self):
        for first,second in ((LEGACY,CANONICAL),(CANONICAL,LEGACY)):
            self.fresh(f"""
import importlib,sys
sys.path[:0]=[{str(PROJECT_ROOT)!r},{str(PROJECT_ROOT/'src')!r}]
a=importlib.import_module({first!r}); b=importlib.import_module({second!r})
assert a is b
for name in ('ArgumentStage','ArgumentRejection','ToolArgumentDiagnostic','ToolArgumentError',
             'public_argument_diagnostic','rejection'):
    assert getattr(a,name) is getattr(b,name)
""")

    def test_monkeypatch_class_identity_and_serialization_are_shared(self):
        old=importlib.import_module(LEGACY);new=importlib.import_module(CANONICAL)
        diagnostic=old.rejection(old.ArgumentStage.EXECUTOR,old.ArgumentRejection.NOT_OBJECT,'[]')
        self.assertIs(type(diagnostic),new.ToolArgumentDiagnostic)
        self.assertEqual(pickle.loads(pickle.dumps(diagnostic)),diagnostic)
        public=new.public_argument_diagnostic(diagnostic)
        self.assertEqual(json.dumps(public,sort_keys=True),
            '{"argument_bytes": 2, "object_member_count": null, "reason": "NOT_OBJECT", '
            '"schema_version": 1, "stage": "executor"}')
        with patch(LEGACY+'.rejection',return_value=diagnostic) as factory:
            self.assertIs(new.rejection(),diagnostic)
        factory.assert_called_once_with()
        self.assertIsNone(old.public_argument_diagnostic({'reason':'private-value'}))

    def test_packaging_selects_backend_and_excludes_management_and_test_packages(self):
        config=tomllib.loads((PROJECT_ROOT/'pyproject.toml').read_text(encoding='utf-8'))
        build=config['tool']['setuptools']
        self.assertEqual(build['packages']['find']['where'],['src','.'])
        self.assertEqual(build['packages']['find']['include'],
            ['fishery_ai','fishery_ai.*','apps','apps.ai_backend'])
        self.assertEqual(build['package-dir'],{'fishery_ai':'src/fishery_ai','apps':'apps'})
        # An install-shaped, isolated import must not obtain apps via the repository cwd.
        with TemporaryDirectory() as directory:
            stage=Path(directory)
            for name in ('apps/__init__.py','apps/ai_backend/__init__.py',
                         'apps/ai_backend/tool_argument_diagnostics.py','src/fishery_ai/__init__.py',
                         'src/fishery_ai/tool_argument_diagnostics.py'):
                target=stage/(name[4:] if name.startswith('src/') else name)
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(PROJECT_ROOT/name,target)
            self.fresh(f"""
import importlib,sys
sys.path.insert(0,{str(stage)!r})
old=importlib.import_module({LEGACY!r}); new=importlib.import_module({CANONICAL!r})
assert old is new
assert new.__file__.startswith({str(stage)!r})
assert 'apps.management_web' not in sys.modules
""",cwd=stage)


if __name__ == '__main__':
    unittest.main()
