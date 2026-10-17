"""Fixed 3 x 5 qualification; each child still executes one consent-bound case.

No model loop, retry, resume, Provider selection or arbitrary batch manifest.
Only new child reports are read. Default dry-run performs no I/O or network.
"""
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from apps.ai_service.development import history_qualification as q
from apps.ai_service.development.qualification_support import _code
from scripts.qualification.qualify_management_history import SafeParser

VERSION = 'management-history-batch@1'
CASE_IDS = tuple(case.case_id for case in q.CASES)
ORDER = CASE_IDS * 5
USAGE_FIELDS = ('input_tokens', 'output_tokens', 'total_tokens')


def batch_plan():
    plans = {case: q.plan(case) for case in CASE_IDS}
    return {'version': VERSION, 'plans': plans, 'order': list(ORDER),
            'repeats_per_case': 5, 'max_turns': 15, 'max_model_requests': 30,
            'max_output_tokens_per_request': q.MAX_OUTPUT_TOKENS,
            'max_output_tokens_total_ceiling': 30 * q.MAX_OUTPUT_TOKENS,
            'retry': 0, 'resume_supported': False}


def read_sample(root, completed, approved, seen, elapsed_ms):
    """Validate CLI/report identity and budgets; project only bounded safe fields."""
    try:
        summary = json.loads(completed.stdout)
        run_id = summary['run_id']
        if (completed.returncode not in (0, 1) or not re.fullmatch('[a-f0-9]{32}', run_id)
                or run_id in seen
                or summary['report'] != f'outputs/assistant-qualification/{run_id}.json'):
            raise ValueError()
        path = root / summary['report']
        # New reports only; no directory scan, arbitrary path or archived sample reuse.
        for boundary in (root / 'outputs', path.parent, path):
            info = boundary.lstat()
            if boundary.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError()
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError()
        report = json.loads(path.read_text(encoding='utf-8'))
        if (report['run_id'] != run_id or report['plan'] != approved
                or report['evidence_kind'] != 'real_provider'
                or completed.returncode != (0 if report['technical_success'] is True else 1)):
            raise ValueError()
        for key in ('request_count', 'actual_network_requests', 'transport_attempts'):
            if (type(report[key]) is not int or not 0 <= report[key] <= 2
                    or key != 'transport_attempts' and summary[key] != report[key]):
                raise ValueError()
        if report['actual_network_requests'] != report['transport_attempts']:
            raise ValueError()
        if report['status'] not in ('completed', 'failed', 'cancelled') or summary['status'] != report['status']:
            raise ValueError()
        requests = report['requests']
        if len(requests) != report['request_count']:
            raise ValueError()
        calls = requests[0].get('normalized', {}).get('calls', []) if requests else []
        count = requests[0].get('normalized', {}).get('tool_call_count') if requests else None
        executions = report['executions']
        receipts = [entry['receipt'] for entry in report['ledger']['entries']]
        usage = report.get('usage', {}).get('usage', {})
        safe_usage = {}
        for key in USAGE_FIELDS:
            value = usage.get(key)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError()
            safe_usage[key] = value
        error = report['error_code']
        if error is not None and error not in q.LOCAL_ERRORS:
            error = _code(error)
        seen.add(run_id)
        return {'run_id': run_id, 'case_id': approved['case_id'], 'report': summary['report'],
            'status': report['status'], 'error_code': error,
            'request_count': report['request_count'], 'actual_network_requests': report['actual_network_requests'],
            'transport_attempts': report['transport_attempts'], 'protocol_tool_call_count': count,
            'correct_tool_selected': any(c['function_name'] == q.WATER_QUALITY_HISTORY for c in calls),
            'arguments_valid': bool(calls) and all(c['arguments_valid'] is True for c in calls),
            'direct_no_tool': count == 0 and requests[0].get('outcome') == 'final_answer',
            'tool_statuses': [e['status'] for e in executions if e['handler_started']],
            'operation_completed': any(r.get('history_query_completed') is True for r in receipts),
            'requirement_satisfied': report['requirement_satisfied'],
            'product_commit_gate_passed': report['product_commit_gate_passed'],
            'technical_success': report['technical_success'],
            'response_truncated': any(r.get('normalized', {}).get('finish_reason', r.get('finish_reason')) == 'length'
                                      for r in requests),
            'runtime_latency_ms': report.get('total_latency_ms'), 'wall_latency_ms': elapsed_ms,
            'usage': safe_usage}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError):
        raise q.QualificationError('BATCH_REPORT_INVALID_REQUEST_COUNT_UNKNOWN') from None


def aggregate(samples):
    result = {}
    for case in CASE_IDS:
        rows = [r for r in samples if r['case_id'] == case]
        real = [r for r in rows if r['actual_network_requests'] > 0]
        counts = {key: sum(r[key] is True for r in real) for key in (
            'correct_tool_selected', 'arguments_valid', 'direct_no_tool', 'operation_completed',
            'requirement_satisfied', 'product_commit_gate_passed', 'technical_success', 'response_truncated')}
        errors, statuses = {}, {}
        for row in real:
            if row['error_code']:
                errors[row['error_code']] = errors.get(row['error_code'], 0) + 1
            for status in row['tool_statuses']:
                statuses[status] = statuses.get(status, 0) + 1
        latencies = [r['runtime_latency_ms'] for r in real if r['runtime_latency_ms'] is not None]
        result[case] = {'reported_runs': len(rows), 'real_samples': len(real), 'planned_runs': 5,
            'protocol_tool_call': sum(type(r['protocol_tool_call_count']) is int and r['protocol_tool_call_count'] > 0 for r in real),
            **counts, 'errors': errors, 'tool_statuses': statuses,
            'actual_network_requests': sum(r['actual_network_requests'] for r in rows),
            'mean_wall_latency_ms': round(sum(r['wall_latency_ms'] for r in real) / len(real), 1) if real else None,
            'mean_runtime_latency_ms': round(sum(latencies) / len(latencies), 1) if latencies else None,
            'runtime_latency_observed_runs': len(latencies),
            'usage': {key: {'known_sum': sum(r['usage'][key] for r in real if r['usage'][key] is not None),
                            'observed_runs': sum(r['usage'][key] is not None for r in real)} for key in USAGE_FIELDS}}
    return result


def main(argv=None):
    parser = SafeParser(description='固定历史资格 3 cases × 5；默认 dry-run，无重试/恢复')
    consent = parser.add_mutually_exclusive_group()
    consent.add_argument('--dry-run', action='store_true')
    consent.add_argument('--confirm-network', action='store_true')
    for case in CASE_IDS:
        parser.add_argument('--' + case + '-plan')
    parser.add_argument('--review-answer', action='store_true')
    args = parser.parse_args(argv)
    try:
        if Path.cwd().resolve() != ROOT:
            raise q.QualificationError('WORKSPACE_REQUIRED')
        approved = batch_plan()
        if not args.confirm_network:
            print(json.dumps({'dry_run': True, 'batch': approved, 'actual_network_requests': 0}, indent=2))
            return 0
        if any(getattr(args, case.replace('-', '_') + '_plan') != approved['plans'][case]['plan_sha256'] for case in CASE_IDS):
            raise q.QualificationError('QUALIFICATION_PLAN_CHANGED')
        if args.review_answer and not sys.stderr.isatty():
            raise q.QualificationError('QUALIFICATION_REVIEW_REQUIRES_TERMINAL')
    except q.QualificationError as error:
        print(json.dumps({'error_code': error.code, 'actual_network_requests': 0}))
        return 2
    except Exception:
        print(json.dumps({'error_code': 'BATCH_PREFLIGHT_FAILED', 'actual_network_requests': 0}))
        return 2
    report = {'run_id': uuid.uuid4().hex, 'kind': VERSION, 'plan': approved,
              'samples': [], 'status': 'running', 'error_code': None,
              'requests_may_be_unreported': False, 'release_eligible': False}
    seen = set()
    try:
        for index, case in enumerate(ORDER, 1):
            report['in_flight_sample'] = {'index': index, 'case_id': case}
            report['requests_may_be_unreported'] = True
            command = [sys.executable, str(ROOT / 'scripts/qualification/qualify_management_history.py'),
                '--case', case, '--confirm-network', '--plan-sha256', approved['plans'][case]['plan_sha256']]
            if args.review_answer:
                command.append('--review-answer')
            started = time.monotonic()
            child = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE,
                stderr=None if args.review_answer else subprocess.PIPE, text=True, encoding='utf-8')
            row = read_sample(ROOT, child, approved['plans'][case], seen, round((time.monotonic()-started)*1000, 1))
            report['samples'].append({'sample_index': index, 'repeat': (index-1)//3+1, **row})
            report['requests_may_be_unreported'] = False
            report['in_flight_sample'] = None
            print(f"{index}/15 {case}: {row['status']} / {row['error_code'] or '-'} / requests={row['actual_network_requests']}", file=sys.stderr)
            if row['actual_network_requests'] == 0 or row['status'] == 'cancelled' or row['error_code'] in (
                    'CREDENTIAL_FILE_ERROR', 'SECRET_MISSING', 'USER_CANCELLED'):
                raise q.QualificationError('BATCH_STOPPED_NO_AUTOMATIC_RESUME')
        report['status'] = 'completed'
    except KeyboardInterrupt:
        report.update(status='stopped', error_code='USER_CANCELLED')
    except q.QualificationError as error:
        report.update(status='stopped', error_code=error.code)
    except Exception:
        report.update(status='stopped', error_code='BATCH_STOPPED_REQUEST_COUNT_UNKNOWN')
    report['by_case'] = aggregate(report['samples'])
    report['known_actual_network_requests'] = sum(r['actual_network_requests'] for r in report['samples'])
    try:
        filename = q.write_report(ROOT, report)
    except q.QualificationError:
        print(json.dumps({'error_code': 'QUALIFICATION_REPORT_ERROR',
            'known_actual_network_requests': report['known_actual_network_requests'],
            'requests_may_be_unreported': report['requests_may_be_unreported']}))
        return 2
    print(json.dumps({'status': report['status'], 'error_code': report['error_code'],
        'report': 'outputs/assistant-qualification/' + filename, 'completed_samples': len(report['samples']),
        'known_actual_network_requests': report['known_actual_network_requests'],
        'requests_may_be_unreported': report['requests_may_be_unreported'], 'by_case': report['by_case']}))
    return 0 if report['status'] == 'completed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
