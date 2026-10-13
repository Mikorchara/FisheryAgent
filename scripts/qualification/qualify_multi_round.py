"""One selected multi-round case; dry-run by default, never a batch runner."""

import argparse
import json
from pathlib import Path
import sys

from fishery_ai.development.qualification.multi_round_qualification import (
    CASES, PRODUCT_CASES, STREAMING_TOOL_SETS, DEFAULT_PRESET, QualificationError, plan, run, write_report)


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "INVALID_QUALIFICATION_ARGUMENTS\n")


def main(argv=None):
    parser = SafeParser(description="单个隔离多轮资格案例；默认 dry-run，不联网")
    parser.add_argument("--case", required=True, choices=sorted({case.case_id for case in (*CASES, *PRODUCT_CASES)} | {"current-score"}))
    parser.add_argument("--preset", default=DEFAULT_PRESET)
    parser.add_argument("--assistant-product", action="store_true", help="正式 Assistant Prompt / History / Commit Gate；Qwen candidate 专用")
    parser.add_argument("--streaming", action="store_true", help="独立 Streaming candidate；自动使用正式 Assistant，多轮预算2/2/3")
    parser.add_argument("--tool-set", choices=STREAMING_TOOL_SETS, default="water-knowledge",
                        help="Streaming 精确工具集合，默认查询水质+Knowledge；不改变产品 Policy")
    parser.add_argument("--review-answer", action="store_true", help="仅在终端 stderr 预览完整成功回答，不保存正文，不代表人工批准")
    parser.add_argument("--max-output-tokens", type=int, default=256,
                        help="每请求输出预算：Streaming 1–512，非流式 1–256；默认256")
    consent = parser.add_mutually_exclusive_group()
    consent.add_argument("--dry-run", action="store_true")
    consent.add_argument("--confirm-network", action="store_true")
    args = parser.parse_args(argv)
    if args.review_answer and (not args.assistant_product or args.streaming):
        parser.error("product review only")
    report = None
    try:
        root = Path.cwd()
        if not (root / "pyproject.toml").is_file():
            raise QualificationError("WORKSPACE_REQUIRED")
        approved = plan(args.case, args.preset, args.max_output_tokens, assistant_product=args.assistant_product,
                        streaming=args.streaming, tool_set=args.tool_set)
        if not args.confirm_network:
            print(json.dumps({"dry_run": True, "plan": approved, "actual_network_requests": 0}, ensure_ascii=True, indent=2))
            return 0
        def review(text):
            # Plain text only; strip terminal control characters. Never redirect this preview into reports.
            safe = ''.join(c for c in text if c in '\n\t' or ord(c) >= 32 and not 127 <= ord(c) <= 159)
            print("\n人工回答预览（不保存，不代表资格批准）：\n" + safe, file=sys.stderr)
        report = run(args.case, root, preset_id=args.preset, max_output_tokens=args.max_output_tokens,
            confirm_network=True, assistant_product=args.assistant_product,
            streaming=args.streaming, tool_set=args.tool_set,
            answer_reviewer=review if args.review_answer else None)
        filename = write_report(root, report)
        print(json.dumps({key: report[key] for key in (
            "run_id", "status", "success", "error_code", "request_count", "actual_network_requests")}
            | {"report": "outputs/assistant-qualification/" + filename}
            | ({"qualification_verdict": report["qualification_verdict"],
                "human_review_status": report["human_review_status"]} if args.assistant_product or args.streaming else {}), ensure_ascii=True))
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
