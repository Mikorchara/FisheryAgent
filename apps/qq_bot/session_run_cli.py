"""Offline contract inspection only. No consent loader or live execution entry."""
import argparse
import json

from apps.ai_service.channel_session_run import prepared_scope,CONTRACT
from apps.ai_service.runtime.release_contracts import _hash
from .conversations import ConversationOptions
from .contracts import BotError
from .run_consent import RunLimits


def main(argv=None):
    parser=argparse.ArgumentParser(description='BOT-3E-B 离线合同检查；不打开实例、不读取密钥、不联网')
    parser.add_argument('--check-contract',action='store_true',required=True)
    parser.add_argument('--max-turns',type=int,default=5)
    parser.add_argument('--seconds',type=int,default=1800)
    parser.add_argument('--total-budget-cny',default='8.02')
    args=parser.parse_args(argv)
    try:
        limits=RunLimits(args.max_turns,args.seconds,args.total_budget_cny)
        scope=prepared_scope(ConversationOptions(trigger_mode='mention_ai',memory_enabled=True))
        result=dict(code='BOUNDED_SESSION_CONTRACT_CHECKED',contract=CONTRACT,status='candidate',
            scope_sha256=_hash(scope),max_turns=limits.max_turns,seconds=limits.seconds,
            total_budget_cny=limits.total_budget_cny,real_execution=False,approval_created=False,
            instance_checked=False,credentials_read=False,network_requests=0)
    except BotError as error:
        print(json.dumps(dict(code=error.code,status='STOPPED')));return 1
    print(json.dumps(result,ensure_ascii=False));return 0


if __name__=='__main__':raise SystemExit(main())
