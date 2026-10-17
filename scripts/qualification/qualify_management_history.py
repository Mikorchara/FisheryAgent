"""Management Qwen history candidate: one fixed case, dry-run unless approved."""
import argparse
import json
from pathlib import Path
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from apps.ai_service.development.history_qualification import CASES, QualificationError, plan, run, write_report


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2,'INVALID_QUALIFICATION_ARGUMENTS\n')


def main(argv=None, *, qualification=None):
    # Share only CLI consent/report plumbing; each qualification owns its plan/run.
    cases, make_plan, execute, save_report = CASES, plan, run, write_report
    if qualification is not None:
        cases, make_plan, execute, save_report = (qualification.CASES, qualification.plan,
                                                qualification.run, qualification.write_report)
    parser = SafeParser(description='管理 Qwen 单案例资格；默认 dry-run，不自动重试')
    parser.add_argument('--case',required=True,choices=[case.case_id for case in cases])
    consent = parser.add_mutually_exclusive_group()
    consent.add_argument('--dry-run',action='store_true')
    consent.add_argument('--confirm-network',action='store_true')
    parser.add_argument('--plan-sha256',help='本案例获批的 dry-run 计划 hash；真实请求必填')
    parser.add_argument('--review-answer',action='store_true',help='仅交互式 stderr 预览；不保存、不代表审核批准')
    args = parser.parse_args(argv)
    report = None
    execution_started = False
    try:
        if Path.cwd().resolve() != ROOT or not (ROOT/'pyproject.toml').is_file():
            raise QualificationError('WORKSPACE_REQUIRED')
        approved = make_plan(args.case)
        if not args.confirm_network:
            print(json.dumps({'dry_run':True,'plan':approved,'actual_network_requests':0},ensure_ascii=True,indent=2))
            return 0
        if args.plan_sha256 != approved['plan_sha256']:
            raise QualificationError('QUALIFICATION_PLAN_CHANGED')
        if args.review_answer and not sys.stderr.isatty():
            raise QualificationError('QUALIFICATION_REVIEW_REQUIRES_TERMINAL')
        def review(text):
            safe = ''.join(c for c in text if c in '\n\t' or unicodedata.category(c)[0] != 'C')
            print('\n隔离业务夹具 · 人工回答预览（不保存、未批准）：\n'+safe,file=sys.stderr)
        execution_started = True
        report = execute(args.case,ROOT,confirm_network=True,approved_plan_sha256=args.plan_sha256,
                     answer_reviewer=review if args.review_answer else None)
        filename = save_report(ROOT,report)
        summary = {k:report[k] for k in ('run_id','status','error_code','technical_success','request_count',
            'actual_network_requests','qualification_verdict','human_review_status')}
        print(json.dumps({**summary,'report':'outputs/assistant-qualification/'+filename},ensure_ascii=True))
        return 0 if report['success'] else 1
    except QualificationError as error:
        code = error.code
    except Exception:
        code = 'QUALIFICATION_FAILED'
    print(json.dumps({'error_code':code,**({k:report[k] for k in ('run_id','request_count','actual_network_requests')}
        if report else {'request_count':None if execution_started else 0,
                       'actual_network_requests':None if execution_started else 0})},ensure_ascii=True))
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
