"""Single-manifest maintainer entry; default dry-run, explicit per-run consent."""

import argparse
from dataclasses import replace
import json
from pathlib import Path

from fishery_ai.assistant_qualification import (
    QualificationError, QualificationManifest, run_qualification, write_report)


class _SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "INVALID_QUALIFICATION_ARGUMENTS\n")  # Never echo unexpected input values.


def main(argv=None):
    parser = _SafeParser(description="Assistant 单次资格验证；默认不联网，最多两次请求")
    parser.add_argument("--manifest", required=True)
    consent = parser.add_mutually_exclusive_group()
    consent.add_argument("--dry-run", action="store_true")
    consent.add_argument("--confirm-network", action="store_true")
    args = parser.parse_args(argv)
    actual_requests = 0
    try:
        root = Path.cwd()
        if not (root / "pyproject.toml").is_file():
            raise QualificationError("WORKSPACE_REQUIRED")
        path = Path(args.manifest).resolve()
        if path.suffix.lower() != ".json" or not path.is_relative_to(root.resolve()):
            raise QualificationError("INVALID_QUALIFICATION_MANIFEST_PATH")
        manifest = QualificationManifest.from_json(path)
        if not args.confirm_network:
            print(json.dumps({"dry_run": True, "plan": manifest.safe_plan(), "actual_network_requests": 0},
                             ensure_ascii=True, indent=2))
            return 0
        manifest = replace(manifest, confirm_network=True)  # In-memory only; never persist consent.
        report = run_qualification(manifest, root)
        actual_requests = report["actual_network_requests"]
        filename = write_report(root, report)
        print(json.dumps({"run_id": report["run_id"], "status": report["status"], "success": report["success"],
            "error_code": report["error_code"], "request_count": report["request_count"],
            "actual_network_requests": report["actual_network_requests"],
            "report": "outputs/assistant-qualification/" + filename}, ensure_ascii=True))
        return 0 if report["success"] else 1
    except QualificationError as exc:
        print(json.dumps({"error_code": exc.code, "actual_network_requests": actual_requests}, ensure_ascii=True))
        return 2
    except Exception:
        print(json.dumps({"error_code": "QUALIFICATION_FAILED", "actual_network_requests": actual_requests}, ensure_ascii=True))
        return 2
    except KeyboardInterrupt:
        # Actual in-flight cancellation belongs to the shared RequestHandle. The
        # CLI runner installs it below through run_qualification's lifecycle.
        print(json.dumps({"error_code": "USER_CANCELLED"}, ensure_ascii=True))
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
