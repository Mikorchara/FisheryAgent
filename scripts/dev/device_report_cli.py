"""Isolated Python bootstrap bound to this repository, no installed-package fallback."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))

from apps.device_reports.__main__ import main

if __name__=='__main__':raise SystemExit(main())
