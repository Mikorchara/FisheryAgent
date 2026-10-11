"""Fixed repository paths for relocated offline tests."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = PROJECT_ROOT / "tests"
