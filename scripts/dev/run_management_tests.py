"""Independent offline management suite; invoke with python -I, no Prototype allowed."""
import importlib.abc
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


class NoPrototype(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'fishery_ai' or fullname.startswith('fishery_ai.'):
            raise ImportError('PROTOTYPE_IMPORT_FORBIDDEN: '+fullname)


def main():
    if not sys.flags.isolated:
        raise SystemExit('ISOLATED_PYTHON_REQUIRED: use python -I scripts/dev/run_management_tests.py')
    if any(name == 'fishery_ai' or name.startswith('fishery_ai.') for name in sys.modules):
        raise SystemExit('PROTOTYPE_ALREADY_IMPORTED')
    sys.meta_path.insert(0, NoPrototype())
    sys.path.insert(0, str(ROOT))
    import apps
    if Path(apps.__file__).resolve() != ROOT/'apps/__init__.py':
        raise SystemExit('WRONG_MANAGEMENT_INSTALLATION')
    # Reuse existing discovery and Node execution; do not build a second runner.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from run_tests import main as run
    return run(['management-independent', *sys.argv[1:]])


if __name__ == '__main__':
    raise SystemExit(main())
