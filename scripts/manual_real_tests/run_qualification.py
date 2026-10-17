"""Human-run management qualification entry; delegates once, dry-run by default."""
import argparse
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
TARGETS = {
    'management-history': 'qualify_management_history.py',
    'management-streaming': 'qualify_management_streaming.py',
    'management-normal-selection': 'qualify_management_normal_selection.py',
}


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, 'INVALID_MANUAL_TEST_ARGUMENTS\n')


def main(argv=None):
    parser = SafeParser(description='人工单案例入口：默认Dry-run，真实执行必须明确确认及本次计划hash',
                        allow_abbrev=False)
    parser.add_argument('--target', choices=TARGETS, required=True)
    parser.add_argument('--case', required=True)
    consent = parser.add_mutually_exclusive_group()
    consent.add_argument('--dry-run', action='store_true')
    consent.add_argument('--confirm-network', action='store_true')
    parser.add_argument('--plan-sha256')
    parser.add_argument('--review-answer', action='store_true')
    args = parser.parse_args(argv)
    if (not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', args.case)
            or args.confirm_network and not re.fullmatch(r'[a-f0-9]{64}', args.plan_sha256 or '')
            or args.plan_sha256 is not None and not re.fullmatch(r'[a-f0-9]{64}', args.plan_sha256)
            or args.review_answer and not args.confirm_network):
        parser.error('invalid consent or case')
    if Path.cwd().resolve() != ROOT or not (ROOT / 'pyproject.toml').is_file():
        parser.exit(2, 'WORKSPACE_REQUIRED\n')
    command = [sys.executable, str(ROOT / 'scripts/qualification' / TARGETS[args.target]), '--case', args.case]
    command += (['--confirm-network', '--plan-sha256', args.plan_sha256]
                if args.confirm_network else ['--dry-run'])
    if args.review_answer:
        command.append('--review-answer')
    # The original CLI owns plan validation, credentials, limits, reports and terminal preview.
    # No capture/rewrite of answers, Provider client, retry, batch, or automatic publication.
    try:
        return subprocess.run(command, cwd=ROOT).returncode
    except KeyboardInterrupt:
        return 130
    except OSError:
        parser.exit(2, 'MANUAL_TEST_LAUNCH_FAILED\n')


if __name__ == '__main__':
    raise SystemExit(main())
