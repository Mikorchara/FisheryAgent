"""Explicit live entry, offline Check, interruptible local per-Turn console approval."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys
import threading

from apps.ai_service.runtime.release_contracts import _hash
from .adapter import QQAdapter
from .ai_coordinator import QQAICoordinator
from .ai_routing import TrialQQAIRouter
from .ai_scheduler import QQAIJobScheduler
from .ai_trial_delivery import ConversationQQTransport
from .configuration import secret_supplier
from .contracts import BotError
from .conversation_trial import ConversationTrial,ROOT,check_configuration
from .gateway import QQGateway,audit
from .service import ReadOnlyQueries
from .transport import QQAPI
from .trial import _error_code
from .trial_configuration import TrialInputs,local_path,read_json,write_new


def console_approval(plan,stopped):
    """Main console only; no daemon input thread, Gateway/Service locks or raw IDs."""
    if os.name!='nt' or not sys.stdin.isatty():raise BotError('CONVERSATION_INTERACTIVE_WINDOWS_CONSOLE_REQUIRED')
    import msvcrt
    challenge='APPROVE '+_hash(plan)[:12]
    print(f"第{plan['turn']}轮独立批准：最多2请求、每请求512输出Token、90秒、零重试。",flush=True)
    print(f"本轮费用上限 {plan['max_cost_cny']} 元；有效至 {plan['expires_at']}；会话代次 {plan['state']['revision']}，已接受历史 {plan['state']['turns']} 轮。",flush=True)
    print('批准SIMULATOR及投影历史披露、原SDK线程剩余风险和北京区价格/上下文口径；不展示原始模型正文。',flush=True)
    print('请审阅本轮plan文件；取消请直接Enter，批准请输入 '+challenge,flush=True)
    return console_challenge(challenge,stopped,plan['expires_at'])


def console_challenge(challenge,stopped,expires_at):
    """Shared interruptible console reader; no business lock or input thread."""
    if os.name!='nt' or not sys.stdin.isatty():raise BotError('CONVERSATION_INTERACTIVE_WINDOWS_CONSOLE_REQUIRED')
    import msvcrt
    chars=[]
    while not stopped.wait(.05):
        if datetime.now(timezone.utc)>=datetime.fromisoformat(expires_at):return False
        if not msvcrt.kbhit():continue
        char=msvcrt.getwch()
        if char=='\x03':raise KeyboardInterrupt()
        if char in ('\x00','\xe0'):msvcrt.getwch();continue
        if char in ('\r','\n'):print('',flush=True);return ''.join(chars)==challenge
        if char=='\b':
            if chars:chars.pop();print('\b \b',end='',flush=True)
        elif char.isprintable() and len(chars)<64:chars.append(char);print(char,end='',flush=True)
    return False


def run_session(host,*,prompt=console_approval,api=None,connector=None,emit=audit):
    """One persistent Gateway/Scheduler/Store, two frozen Service/SDK owners."""
    if host.offline_test and (api is None or connector is None):raise BotError('TRIAL_OFFLINE_GATEWAY_REQUIRED')
    scheduler=router=gateway=worker=None;stopped=threading.Event();failure=[];saved=0
    code='CONVERSATION_TRIAL_STOPPED';report=None;stop_reason='QQ_SESSION_ENDED'
    try:
        api=api if api is not None else QQAPI(host.access.app_id,secret_supplier(ROOT))
        transport=ConversationQQTransport(api,host)
        coordinator=QQAICoordinator(host.access,host.monitoring,host.base_service,config=host.config,
            conversations=host.store,conversation_trial=host,clock=host.clock)
        scheduler=QQAIJobScheduler(coordinator,transport,clock=host.clock,receipt_sink=host.checkpoint)
        adapter=QQAdapter(host.access,ReadOnlyQueries(host.monitoring,None,live=True,
            instance_id=host.monitoring.config.instance_id),mode='QQ_PASSIVE_READY',clock=host.clock)
        router=TrialQQAIRouter(adapter,scheduler)
        options={'connector':connector} if connector is not None else {}
        def status(code,**fields):
            nonlocal stop_reason
            if code in ('QQ_CANCELLED','QQ_RUN_DURATION_REACHED'):stop_reason=code
            emit(code,**fields)
        gateway=QQGateway(host.access.app_id,api,adapter,trial_router=router,clock=host.clock,emit=status,**options)
        write_new(host.directory/'session.json',dict(contract=host.scope['contract'],scope=host.scope,
            scope_sha256=host.scope_sha256,run_id=host.run_id,configuration=check_configuration(host.inputs,max_cost_cny=host.max_cost)))
        def approve_next():
            plan=host.plan();write_new(host.directory/f"turn-{plan['turn']}.plan.json",plan)
            emit('CONVERSATION_TURN_APPROVAL_REQUIRED',count=plan['turn'])
            if not prompt(plan,stopped):raise BotError('CONVERSATION_OPERATOR_CANCELLED')
            host.approve(plan,host.directory/f"turn-{plan['turn']}.approval.json")
            emit('CONVERSATION_TURN_APPROVED',count=plan['turn'])
        approve_next()  # First approval precedes ANY Gateway network connection.
        def gateway_loop():
            try:
                remaining=min(host.seconds,int((host.expires-host.clock()).total_seconds()))
                if remaining<1:raise BotError('CONVERSATION_RUN_WINDOW_TOO_SHORT')
                gateway.run(remaining)
            except BaseException as error:failure.append(_error_code(error))
            finally:stopped.set()
        worker=threading.Thread(target=gateway_loop,name='qq-conversation-gateway',daemon=False);worker.start()
        second_offered=False
        while not stopped.wait(.05):
            if not host.changed.is_set():continue
            host.changed.clear()
            with host._lock:turns=list(host.turns);halted=host._halted
            for turn in turns[saved:]:
                write_new(host.directory/f"turn-{turn['turn']}.result.json",turn);saved+=1
                emit('CONVERSATION_TURN_RECORDED',count=saved)
            if halted:raise BotError(halted)
            if len(turns)==1 and not second_offered:
                if gateway.stop.is_set():continue
                second_offered=True;approve_next()  # Input holds no business lock; Gateway keeps running.
        if failure:code=failure[0]
        if host._halted:code=host._halted
    except KeyboardInterrupt:code='CONVERSATION_OPERATOR_CANCELLED'
    except Exception as error:code=_error_code(error)
    finally:
        if gateway is not None:gateway.request_stop()
        if scheduler is not None:scheduler.cancel_all(reason='AI_SHUTDOWN')
        if worker is not None:
            worker.join(15)
            if worker.is_alive():code='CONVERSATION_GATEWAY_STOP_FAILED'
            elif failure and code in ('CONVERSATION_TRIAL_STOPPED','CONVERSATION_STORE_CLOSED','CONVERSATION_RUN_EXPIRED'):
                code=failure[0]  # Gateway cleanup may close RAM before the console observes its original error.
        try:
            if router is not None:router.close()
            elif scheduler is not None:scheduler.close()
        except Exception as error:code=_error_code(error)
        finally:
            if api is not None:api.close()
            host.close()
        try:
            for turn in host.turns[saved:]:write_new(host.directory/f"turn-{turn['turn']}.result.json",turn)
        except Exception as error:code=_error_code(error)
        report={**host.report(code),'stop_reason':stop_reason}
        try:write_new(host.directory/'result.json',report);report={**report,'report_saved':True}
        except Exception as error:
            report={**report,'operation_code':code,'code':'CONVERSATION_RESULT_WRITE_FAILED',
                'write_error':_error_code(error),'report_saved':False}
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description='Per-Turn Qwen + QQ two-turn trial; Check never opens a database/key/network')
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check',action='store_true');mode.add_argument('--run',action='store_true')
    parser.add_argument('--request-file',type=Path,required=True);parser.add_argument('--directory',type=Path)
    parser.add_argument('--max-cost-cny',default='2.00');parser.add_argument('--valid-minutes',type=int,default=10)
    parser.add_argument('--run-seconds',type=int,default=300)
    for flag in ('confirm-instance-read','confirm-provider-network','confirm-qq-network','enable-mention-ai'):
        parser.add_argument('--'+flag,action='store_true')
    args=parser.parse_args(argv)
    try:
        inputs=TrialInputs.parse(read_json(local_path(args.request_file)))
        checked=check_configuration(inputs,max_cost_cny=args.max_cost_cny)
        if args.check:print(json.dumps(checked,ensure_ascii=False));return 0
        if not all((args.confirm_instance_read,args.confirm_provider_network,args.confirm_qq_network,args.enable_mention_ai)):
            raise BotError('CONVERSATION_EXPLICIT_NETWORK_AND_MENTION_CONSENT_REQUIRED')
        if args.directory is None:raise BotError('CONVERSATION_REPORT_DIRECTORY_REQUIRED')
        directory=local_path(args.directory)
        if not directory.is_relative_to(ROOT/'outputs'):raise BotError('CONVERSATION_REPORT_MUST_BE_IN_OUTPUTS')
        host=ConversationTrial(inputs,directory,max_cost_cny=args.max_cost_cny,
            minutes=args.valid_minutes,seconds=args.run_seconds)
        print(json.dumps({**checked,'instance_id':host.monitoring.config.instance_id,
            'device_id':host.device_id,'scope_sha256':host.scope_sha256},ensure_ascii=False),flush=True)
        report=run_session(host);print(json.dumps(report,ensure_ascii=False),flush=True)
        return 0 if report['code']=='CONVERSATION_TRIAL_STOPPED' and report['report_saved'] and report['completed'] else 1
    except (Exception,KeyboardInterrupt) as error:
        failure={'contract':'qq-qwen-conversation-turn-trial@1','code':_error_code(error),'automatic_retry':False}
        if args.run and args.directory is not None:
            try:
                directory=local_path(args.directory)
                if directory.is_relative_to(ROOT/'outputs') and directory.is_dir():
                    write_new(directory/'result.json',failure);failure['report_saved']=True
            except Exception:failure['report_saved']=False
        print(json.dumps(failure),flush=True);return 1


if __name__=='__main__':raise SystemExit(main())
