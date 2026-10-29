"""One local RunConsent, original live Gateway/SDK paths; Check is always offline."""
import argparse
from pathlib import Path
import json
import threading

from apps.ai_service.runtime.release_contracts import _hash
from .adapter import QQAdapter
from .ai_coordinator import QQAICoordinator
from .ai_routing import TrialQQAIRouter
from .ai_scheduler import QQAIJobScheduler
from .ai_trial_delivery import SessionQQTransport
from .configuration import secret_supplier
from .contracts import BotError
from .conversation_trial_cli import console_challenge
from .gateway import QQGateway,audit
from .run_consent import RunLimits
from .service import ReadOnlyQueries
from .session_run_trial import SessionTrialRun,check_configuration,ROOT,CONTRACT
from .transport import QQAPI
from .trial import _error_code
from .trial_configuration import TrialInputs,read_json,local_path,write_new


def console_approval(plan,stopped):
    budget=plan['limits'];summary=plan['configuration'];challenge='APPROVE '+_hash(plan)[:12]
    if summary.get('general_publication_requires_operator_consent'):
        challenge='APPROVE HYBRID '+_hash(plan)[:12]
        print('单独批准实验性General自动发布：'+summary['residual_risk'],flush=True)
    print(f"持续会话一次审批：{summary['provider']} / {summary['model']}；Scope {plan['scope_sha256']}",flush=True)
    print('展示模式：'+summary['presentation_mode']+'（仅本机配置，无群聊切换指令）',flush=True)
    print(f"实例 {summary['instance_id']} / 设备 {summary['device_id']}；群摘要 {summary['group_ref']}；成员摘要 {summary['member_refs']}",flush=True)
    print('明确数据根：'+summary['data_root'],flush=True)
    print(f"最长 {budget['seconds']} 秒 / 最多 {budget['max_turns']} Turn / {plan['max_model_requests']} 请求；每请求512输出Token、每轮90秒、零重试。",flush=True)
    print(f"每轮保守预留 {plan['reservation_per_turn_cny']} 元；总预留 {summary['total_reservation_cny']} 元；总预算 {budget['total_budget_cny']} 元。不是云平台账单硬上限。",flush=True)
    print('批准Provider与QQ网络、SIMULATOR及投影历史披露、Scope/静态价格与预算；接受SDK线程不能强停及远端费用未知的剩余风险。',flush=True)
    print('仅本进程有效；失败不退许可、不自动重试；退出后不能恢复余额。审批截止 '+plan['approval_deadline'],flush=True)
    print('取消请Enter；批准请输入 '+challenge,flush=True)
    return console_challenge(challenge,stopped,plan['approval_deadline'])


def run_session(host,*,prompt=console_approval,api=None,connector=None,emit=audit):
    from .hybrid_trial import HybridTrialRun
    if type(host) not in (SessionTrialRun,HybridTrialRun):raise BotError('SESSION_TRIAL_COMPOSITION_REQUIRED')
    if host.offline_test and (api is None or connector is None):raise BotError('TRIAL_OFFLINE_GATEWAY_REQUIRED')
    gateway=router=scheduler=worker=None;stopped=threading.Event();failure=[]
    code='SESSION_TRIAL_STOPPED';stop_reason='QQ_SESSION_ENDED';recorded=0;exhausted=False
    try:
        plan=host.plan();write_new(host.directory/'plan.json',plan)
        write_new(host.directory/'session.json',dict(contract=host.contract,scope=host.scope,scope_sha256=host.scope_sha256))
        # No QQAPI, credential supplier or worker before this single local approval.
        if not prompt(plan,stopped):raise BotError('SESSION_OPERATOR_CANCELLED')
        host.approve(plan,confirmed=True)
        api=api if api is not None else QQAPI(host.access.app_id,secret_supplier(ROOT))
        transport=SessionQQTransport(api,host)
        coordinator=QQAICoordinator(host.access,host.monitoring,host.base_service,config=host.config,
            conversations=host.store,session_run=host,clock=host.clock)
        scheduler=QQAIJobScheduler(coordinator,transport,clock=host.clock)
        adapter=QQAdapter(host.access,ReadOnlyQueries(host.monitoring,None,live=True,
            instance_id=host.monitoring.config.instance_id),mode='QQ_PASSIVE_READY',clock=host.clock)
        router=TrialQQAIRouter(adapter,scheduler)
        def status(value,**fields):
            nonlocal stop_reason
            if value in ('QQ_RUN_DURATION_REACHED','QQ_CANCELLED') and stop_reason not in ('OPERATOR_INTERRUPTED','RUN_EXPIRED'):
                stop_reason=value
            emit(value,**fields)
        options={'connector':connector} if connector is not None else {}
        gateway=QQGateway(host.access.app_id,api,adapter,trial_router=router,clock=host.clock,emit=status,**options)
        def work():
            try:gateway.run(max(1,int(host.remaining())))
            except BaseException as error:failure.append(_error_code(error))
            finally:stopped.set()
        worker=threading.Thread(target=work,name='qq-session-trial-gateway',daemon=False);worker.start()
        while not stopped.wait(.05):
            host.check()
            with host._lock:count=len(host.turns)
            if count!=recorded:
                recorded=count;emit('SESSION_RUN_TURN_RECORDED',count=count)
                quota=host.ledger.report()
                emit('SESSION_RUN_REMAINING_TURNS',count=quota['max_turns']-quota['consumed_turns'])
            if not exhausted and host.ledger.report()['consumed_turns']>=host.ledger.limits.max_turns:
                exhausted=True;emit('SESSION_RUN_QUOTA_EXHAUSTED',count=0)
        if failure:code=failure[0]
        if host.ledger.report()['stop_code']:code=host.ledger.report()['stop_code']
    except KeyboardInterrupt:
        stop_reason='OPERATOR_INTERRUPTED'
        if host._authorization is None:code='SESSION_OPERATOR_CANCELLED'
    except Exception as error:code=_error_code(error)
    finally:
        if code=='RUN_EXPIRED':code='SESSION_TRIAL_STOPPED';stop_reason='RUN_EXPIRED'
        if gateway is not None:gateway.request_stop()
        if scheduler is not None:scheduler.cancel_all(reason='AI_SHUTDOWN')
        if worker is not None:
            worker.join(15)
            if worker.is_alive():code='SESSION_GATEWAY_STOP_FAILED'
            elif failure and failure[0] not in ('RUN_EXPIRED',) and code=='SESSION_TRIAL_STOPPED':code=failure[0]
        try:
            if router is not None:router.close()
            elif scheduler is not None:scheduler.close()
        except Exception as error:code=_error_code(error)
        finally:
            try:
                if api is not None:api.close()
            except Exception:code='SESSION_NETWORK_CLOSE_FAILED'
            try:host.close()
            except Exception:code='RUN_CLOSE_FAILED'
        quota=host.ledger.report()
        if quota['stop_code'] not in (None,'RUN_EXPIRED') and code=='SESSION_TRIAL_STOPPED':code=quota['stop_code']
        report={**host.report(code),'stop_reason':stop_reason,'report_saved':True,
            'completed':code=='SESSION_TRIAL_STOPPED',
            'verified_turns':sum(t.get('verified',False) for t in host.turns),
            'api_accepted_turns':sum(t.get('outcome',{}).get('api_accepted',False) for t in host.turns),
            'delivery_unknown_turns':sum(t.get('outcome',{}).get('state')=='DELIVERY_UNKNOWN' for t in host.turns)}
        try:write_new(host.directory/'result.json',report)
        except Exception as error:
            host.ledger.halt('RUN_REPORT_FAILED')
            report={**report,'operation_code':code,'code':'RUN_REPORT_FAILED','report_saved':False,
                'completed':False,'write_error':_error_code(error)}
    return report


def main(argv=None,*,hybrid=False):
    parser=argparse.ArgumentParser(description='Bounded Qwen/QQ session trial; Check never reads keys/instances/network')
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check',action='store_true');mode.add_argument('--run',action='store_true')
    parser.add_argument('--request-file',type=Path,required=True);parser.add_argument('--directory',type=Path)
    parser.add_argument('--max-turns',type=int,default=5);parser.add_argument('--run-seconds',type=int,default=1800)
    parser.add_argument('--total-budget-cny',default='8.02');parser.add_argument('--valid-minutes',type=int,default=10)
    parser.add_argument('--member',action='append')
    parser.add_argument('--presentation',choices=('chat','detailed'),default='chat')
    if hybrid:parser.add_argument('--confirm-general-experimental',action='store_true')
    for flag in ('confirm-instance-read','confirm-provider-network','confirm-qq-network','enable-mention-ai'):
        parser.add_argument('--'+flag,action='store_true')
    args=parser.parse_args(argv)
    host_type,check,contract=SessionTrialRun,check_configuration,CONTRACT
    if hybrid:
        from .hybrid_trial import HybridTrialRun,check_configuration as hybrid_check
        host_type,check,contract=HybridTrialRun,hybrid_check,HybridTrialRun.contract
    try:
        inputs=TrialInputs.parse(read_json(local_path(args.request_file)))
        limits=RunLimits(args.max_turns,args.run_seconds,args.total_budget_cny)
        members=tuple(args.member) if args.member is not None else None
        checked=check(inputs,limits=limits,members=members,presentation_mode=args.presentation)
        if args.check:print(json.dumps(checked,ensure_ascii=False));return 0
        if not all((args.confirm_instance_read,args.confirm_provider_network,args.confirm_qq_network,args.enable_mention_ai)):
            raise BotError('SESSION_EXPLICIT_NETWORK_AND_MENTION_CONSENT_REQUIRED')
        if hybrid and not args.confirm_general_experimental:raise BotError('HYBRID_GENERAL_CONSENT_REQUIRED')
        if args.directory is None:raise BotError('SESSION_REPORT_DIRECTORY_REQUIRED')
        directory=local_path(args.directory)
        if not directory.is_relative_to(ROOT/'outputs'):raise BotError('SESSION_REPORT_MUST_BE_IN_OUTPUTS')
        host=host_type(inputs,directory,limits=limits,members=members,valid_minutes=args.valid_minutes,
                             presentation_mode=args.presentation)
        print(json.dumps(checked,ensure_ascii=False),flush=True)
        report=run_session(host);print(json.dumps(report,ensure_ascii=False),flush=True)
        return 0 if report['completed'] and report['report_saved'] else 1
    except (Exception,KeyboardInterrupt) as error:
        failure=dict(contract=contract,code=_error_code(error),report_saved=False,automatic_retry=False)
        if args.run and args.directory is not None:
            try:
                directory=local_path(args.directory)
                if directory.is_relative_to(ROOT/'outputs') and directory.is_dir():
                    write_new(directory/'result.json',{**failure,'report_saved':True});failure['report_saved']=True
            except Exception:pass
        print(json.dumps(failure),flush=True);return 1


if __name__=='__main__':raise SystemExit(main())
