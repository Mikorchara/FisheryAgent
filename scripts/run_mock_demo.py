"""Run the V0.1 demo without installing the package."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fishery_ai.__main__ import main


if __name__ == "__main__":
    main()
