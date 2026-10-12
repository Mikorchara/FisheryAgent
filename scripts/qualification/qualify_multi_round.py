"""One selected multi-round case; dry-run by default, never a batch runner."""

import argparse
import json
from pathlib import Path

from fishery_ai.development.qualification.multi_round_qualification import (
    CASES, DEFAULT_PRESET, QualificationError, plan, run, write_report)


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "INVALID_QUALIFICATION_ARGUMENTS\n")


def main(argv=None):
    parser = SafeParser(description="单个隔离多轮资格案例；默认 dry-run，不联网")
    parser.add_argument("--case", required=True, choices=[case.case_id for case in CASES])
    parser.add_argument("--preset", default=DEFAULT_PRESET)
    parser.add_argument("--max-output-tokens", type=int, default=256)
    consent = parser.add_mutually_exclusive_group()
    consent.add_argument("--dry-run", action="store_true")
    consent.add_argument("--confirm-network", action="store_true")
    args = parser.parse_args(argv)
    report = None
    try:
        root = Path.cwd()
        if not (root / "pyproject.toml").is_file():
            raise QualificationError("WORKSPACE_REQUIRED")
        approved = plan(args.case, args.preset, args.max_output_tokens)
        if not args.confirm_network:
            print(json.dumps({"dry_run": True, "plan": approved, "actual_network_requests": 0}, ensure_ascii=True, indent=2))
            return 0
        report = run(args.case, root, preset_id=args.preset, max_output_tokens=args.max_output_tokens, confirm_network=True)
        filename = write_report(root, report)
        print(json.dumps({key: report[key] for key in (
            "run_id", "status", "success", "error_code", "request_count", "actual_network_requests")}
            | {"report": "outputs/assistant-qualification/" + filename}, ensure_ascii=True))
        return 0 if report["success"] else 1
    except QualificationError as error:
        print(json.dumps({"error_code": error.code} | ({key: report[key] for key in (
            "run_id", "request_count", "actual_network_requests")} if report is not None else {}), ensure_ascii=True))
        return 2
    except Exception:
        print(json.dumps({"error_code": "QUALIFICATION_FAILED"} | ({key: report[key] for key in (
            "run_id", "request_count", "actual_network_requests")} if report is not None else {}), ensure_ascii=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
