"""Qwen three-Tool candidate: one case, existing consent/report CLI, no publication."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from apps.ai_service.development import normal_selection_qualification
from scripts.qualification.qualify_management_history import main as run_cli


def main(argv=None):
    return run_cli(argv,qualification=normal_selection_qualification)

if __name__ == '__main__':
    raise SystemExit(main())
