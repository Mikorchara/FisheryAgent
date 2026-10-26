"""Explicit operator-only preparation/approval/one-turn CLI. Default QQ CLI stays disabled."""
import argparse
from dataclasses import asdict,dataclass,replace
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import sys
import threading
import time

from apps.ai_backend.execution import RequestHandle
from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.observability import JsonlTraceSink
from apps.ai_service.channel import ChannelAuthorization,ChannelBudget
from apps.ai_service.channel_trial import QwenTrialSession,TRIAL_CONTRACT,PRESET
from apps.ai_service.runtime.release_contracts import _hash
from apps.ai_service.service import ManagementAssistantService
from apps.ai_service.channel_presentation import EXPLANATION_CONTRACT,render_channel_reply
from .ai_configuration import QQAIConfig,QQAIGrant
from .configuration import project_credentials,secret_supplier
from .contracts import BotError
from .monitoring_source import InstanceMonitoring
from .trial_configuration import (ApprovalFile,TrialInputs,approve_plan,inputs_snapshot,
    local_path,make_plan,prerequisite_valid,read_json,validate_record,write_new)


ROOT=Path(__file__).resolve().parents[2]


@dataclass(repr=False)
class TrialRuntime:
    record: ApprovalFile
    monitoring: object
    access: object
    config: QQAIConfig
    session: QwenTrialSession
    service: ManagementAssistantService
    qq_outcomes: tuple = ()
    qq_stop_reason: str = 'QQ_NOT_STARTED'


def compose_trial(record,*,async_client_factory=None,clock=None):
    """No network/key access here. Explicit test factory forces fake credentials/provenance."""
    record.check()
    access,ai,config,grant,_=inputs_snapshot(record.inputs)
    monitoring=InstanceMonitoring(config,clock=clock)
    _,_,_,_,binding=inputs_snapshot(record.inputs,monitoring)
    value=record.value
    if binding!=value['bindings_sha256']:raise BotError('TRIAL_BINDINGS_CHANGED')
    if (config.instance_id,grant.device_id,access.app_id)!=(value['instance_id'],value['device_id'],value['app_id']):
        raise BotError('TRIAL_BINDINGS_CHANGED')
    capture=monitoring.capture_water(grant.device_id)
    ref=capture.analysis.observation
    if ref is not None and ref.source_kind!='simulator':raise BotError('TRIAL_SOURCE_NOT_APPROVED')
    def validate():
        if inputs_snapshot(record.inputs,monitoring)[-1]!=value['bindings_sha256']:
            raise BotError('TRIAL_BINDINGS_CHANGED')
        if value['phase']=='qq':
            required=value['prerequisite']
            if prerequisite_valid(read_json(required['path']),value['scope_sha256'],value['bindings_sha256'])!=required['sha256']:
                raise BotError('TRIAL_PROVIDER_PREREQUISITE_REQUIRED')
        # Includes fresh source/SDK Scope, approval bytes, expiry and one-use
        # marker. Run last, after binding/receipt I/O, rather than building the
        # same Scope again in this check. Every boundary still calls validate.
        record.check()
    session=QwenTrialSession(record.grant(),validate=validate,claim=record.claim,
        async_client_factory=async_client_factory,clock=clock)
    # Resolve the existing private credential location, not a key. The service
    # snapshots a key only after approval consumption and RequestHandle claim.
    credentials=project_credentials(ROOT) if async_client_factory is None else None
    traces=JsonlTraceSink(record.inputs.ai_config.parent/('qwen-trial-'+value['approval_id']+'.trace.jsonl'),
        tool_names=('get_current_water_quality',))
    service=ManagementAssistantService(monitoring,credentials=credentials,traces=traces,
        policy_directory=record.inputs.policy_directory,channel_trial=session)
    # AI permission is narrowed, never written back to the independent config or Policy.
    trial_config=QQAIConfig(True,PRESET,ChannelBudget(),(
        QQAIGrant(record.inputs.group_id,(record.inputs.member_id,),grant.device_id),))
    approved_group=next(g for g in access.groups if g.group_id==record.inputs.group_id)
    trial_access=replace(access,groups=(replace(approved_group,members=(record.inputs.member_id,)),))
    return TrialRuntime(record,monitoring,trial_access,trial_config,session,service)


def provider_turn(runtime,question):
    """One main-thread Service turn, with a bounded authorization cancellation watchdog."""
    if runtime.session.approval.phase!='provider':raise BotError('TRIAL_PROVIDER_PHASE_REQUIRED')
    session=runtime.session;handle=RequestHandle()
    authorization=ChannelAuthorization(session.approval.instance_id,session.approval.device_id,
        runtime.monitoring.binding_revision,runtime.record.digest,PRESET,
        ('get_current_water_quality',),ChannelBudget(),session.check)
    prepared=runtime.service.prepare_channel_turn(question,authorization)
    stopped=threading.Event()
    def watch():
        while not stopped.wait(.05):
            try:session.check()  # SDK owner preserves TOTAL_TIMEOUT; do not relabel it as user cancellation.
            except Exception:
                handle.cancel();handle.abort_io();return
    watcher=threading.Thread(target=watch,name='qwen-trial-authorization',daemon=False)
    watcher.start()
    try:
        result=runtime.service.execute_channel_turn(prepared,handle)
        handle.assert_resources_closed();session.check()
        return result
    except KeyboardInterrupt:
        handle.cancel();handle.abort_io();raise
    finally:
        stopped.set();watcher.join(3)
        if watcher.is_alive():raise BotError('TRIAL_WATCHDOG_STOP_FAILED')


def result_record(runtime,result=None,*,code=None):
    s=runtime.session;report=s.report();a=s.approval
    complete=bool(result is not None and result.completed and report['model_requests']==2
        and report['sdk_resources'] and report['sdk_resources']['state']=='CLOSED'
        and report['sdk_resources']['thread_exited'] and report['sdk_resources']['local_io_closed']
        and report['sdk_resources']['cleanup_error'] is None)
    if code is None:
        code=('OFFLINE_QWEN_TRIAL_TESTED' if s.offline_test else 'QWEN_PROVIDER_TRIAL_VERIFIED') if complete else 'QWEN_TRIAL_FAILED'
    explanation_code='EXPLANATION_NOT_EVALUATED';explanation_validated=False
    if complete:
        _,assessment=render_channel_reply(result,max_chars=1600-len('受控 Qwen 单轮实验 · SIMULATOR\n'))
        explanation_code=assessment.code;explanation_validated=assessment.allowed
    return dict(contract=TRIAL_CONTRACT,code=code,approval_id=a.approval_id,phase=a.phase,
        scope_sha256=a.scope_sha256,bindings_sha256=a.bindings_sha256,
        completed=complete,explanation_contract=EXPLANATION_CONTRACT,
        explanation_code=explanation_code,explanation_validated=explanation_validated,**report)


def run_qq(runtime,seconds,*,api=None,connector=None,emit=None,receipt_sink=None):
    """A separate opt-in composition. All replies share the existing PassiveReplyOwner."""
    from .adapter import QQAdapter
    from .ai_coordinator import QQAICoordinator
    from .ai_routing import TrialQQAIRouter
    from .ai_scheduler import QQAIJobScheduler
    from .ai_trial_delivery import TrialQQTransport
    from .gateway import QQGateway,audit
    from .service import ReadOnlyQueries
    from .transport import QQAPI
    if runtime.session.approval.phase!='qq':raise BotError('TRIAL_QQ_PHASE_REQUIRED')
    if type(seconds) is not int or not 1<=seconds<=600:raise BotError('INVALID_RUN_DURATION')
    runtime.session.check()
    if runtime.session.offline_test and (api is None or connector is None):
        raise BotError('TRIAL_OFFLINE_GATEWAY_REQUIRED')
    api=api if api is not None else QQAPI(runtime.access.app_id,secret_supplier(ROOT))
    scheduler=router=None
    runtime.qq_stop_reason='QQ_SESSION_ENDED'
    emit=emit or audit
    def status(code,**fields):
        if code in ('QQ_CANCELLED','QQ_RUN_DURATION_REACHED'):runtime.qq_stop_reason=code
        emit(code,**fields)
    try:
        transport=TrialQQTransport(api,runtime.session)
        coordinator=QQAICoordinator(runtime.access,runtime.monitoring,runtime.service,config=runtime.config,
            clock=runtime.session.clock)
        scheduler=QQAIJobScheduler(coordinator,transport,clock=runtime.session.clock,receipt_sink=receipt_sink)
        adapter=QQAdapter(runtime.access,ReadOnlyQueries(runtime.monitoring,None,live=True,
            instance_id=runtime.session.approval.instance_id),mode='QQ_PASSIVE_READY',clock=runtime.session.clock)
        router=TrialQQAIRouter(adapter,scheduler)
        options={'connector':connector} if connector is not None else {}
        gateway=QQGateway(runtime.access.app_id,api,adapter,trial_router=router,
            clock=runtime.session.clock,emit=status,**options)
        gateway.run(seconds)
    except KeyboardInterrupt:
        runtime.qq_stop_reason='QQ_CANCELLED';raise
    except Exception as error:
        runtime.qq_stop_reason=_error_code(error);raise
    finally:
        try:
            if router is not None:router.close()
            elif scheduler is not None:scheduler.close()
        finally:
            # Cleanup may itself fail. Retain confirmed receipts and safe task
            # states even when run() never reaches its ordinary return path.
            try:
                if scheduler is not None:
                    with scheduler._cv:
                        runtime.qq_outcomes=tuple(scheduler.snapshot(key)
                            for key in (*scheduler._finished,*scheduler._jobs))
            finally:api.close()
    for item in runtime.qq_outcomes:emit(item['code'] or 'QWEN_TRIAL_FINISHED')
    return runtime.qq_outcomes


def _error_code(error):
    code=getattr(error,'code','TRIAL_OPERATION_FAILED')
    return code if isinstance(code,str) and re.fullmatch('[A-Z0-9_]{1,80}',code) else 'TRIAL_OPERATION_FAILED'


def qq_result_record(runtime,*,code='QWEN_QQ_TRIAL_STOPPED'):
    outcomes=runtime.qq_outcomes
    report=result_record(runtime,code=code)
    report.update(delivery=outcomes,stop_reason=runtime.qq_stop_reason,
        backend_completed=bool(runtime.session.handle is not None and runtime.session.handle.state=='COMPLETED'),
        completed=any(v['state']=='DELIVERED' and v['api_accepted'] for v in outcomes),
        api_accepted=any(v['state']=='DELIVERED' and v['api_accepted'] for v in outcomes),
        client_display_confirmed=False,
        explanation_validated=any(v.get('explanation_in_payload') is True for v in outcomes),
        explanation_code=next((v['explanation_code'] for v in outcomes if v.get('explanation_code')),
            'EXPLANATION_NOT_EVALUATED'))
    error=next((v['report_error'] for v in outcomes if v.get('report_error')),None)
    if error:
        report['report_error']=error
        if code=='QWEN_QQ_TRIAL_STOPPED':report['code']=error
    return report


def delivery_checkpoint(runtime,path,receipt):
    """One create-only receipt, before waiting out the remaining QQ session.

    No chat/model/fact payload. This is delivery evidence, not a Provider
    prerequisite, final session report, client confirmation or retry permit.
    """
    approval=runtime.session.approval
    report=runtime.session.report()
    write_new(path,dict(contract='qq-trial-delivery-checkpoint@1',phase='qq',
        approval_id=approval.approval_id,scope_sha256=approval.scope_sha256,
        bindings_sha256=approval.bindings_sha256,receipt=asdict(receipt),
        model_requests=report['model_requests'],sdk_resources=report['sdk_resources'],
        client_display_confirmed=False,automatic_retry=False))
    print(json.dumps({'code':'QQ_TRIAL_DELIVERY_CHECKPOINT_SAVED','api_accepted':receipt.api_accepted}),flush=True)


def publish_result(path,report,exit_code):
    try:write_new(path,report)
    except (Exception,KeyboardInterrupt) as error:
        print(json.dumps({**report,'operation_code':report['code'],'code':'TRIAL_RESULT_WRITE_FAILED',
            'write_error':_error_code(error),'report_saved':False,'automatic_retry':False},ensure_ascii=False),flush=True)
        return 1
    print(json.dumps({**report,'report_saved':True},ensure_ascii=False),flush=True)
    return exit_code


def main(argv=None):
    parser=argparse.ArgumentParser(description='One-turn Qwen operator trial; networking requires a separate approval')
    mode=parser.add_mutually_exclusive_group(required=True)
    for name in ('prepare','approve','check','run-provider','run-qq'):mode.add_argument('--'+name,action='store_true')
    parser.add_argument('--phase',choices=('provider','qq'))
    parser.add_argument('--access-file',type=Path);parser.add_argument('--monitoring-config',type=Path)
    parser.add_argument('--ai-config',type=Path);parser.add_argument('--policy-directory',type=Path)
    parser.add_argument('--group-id');parser.add_argument('--member-id')
    parser.add_argument('--max-cost-cny');parser.add_argument('--valid-minutes',type=int,default=10)
    parser.add_argument('--provider-receipt',type=Path)
    parser.add_argument('--plan',type=Path);parser.add_argument('--approval',type=Path)
    parser.add_argument('--approval-sha256');parser.add_argument('--output',type=Path)
    parser.add_argument('--question',default='请查询当前绑定设备的水质，并说明数据时效与限制。')
    parser.add_argument('--confirm-instance-read',action='store_true')
    parser.add_argument('--confirm-provider-network',action='store_true')
    parser.add_argument('--confirm-qq-network',action='store_true')
    parser.add_argument('--run-seconds',type=int,default=120)
    args=parser.parse_args(argv)
    runtime=None;output=None
    try:
        if not args.confirm_instance_read:raise BotError('TRIAL_INSTANCE_READ_CONFIRMATION_REQUIRED')
        if args.prepare:
            if (any(v is None for v in (args.phase,args.access_file,args.monitoring_config,args.ai_config,
                    args.policy_directory,args.group_id,args.member_id,args.max_cost_cny,args.output))
                    or args.confirm_provider_network or args.confirm_qq_network):raise BotError('INVALID_TRIAL_ARGUMENTS')
            inputs=TrialInputs.parse(dict(access_file=str(args.access_file),monitoring_config=str(args.monitoring_config),
                ai_config=str(args.ai_config),policy_directory=str(args.policy_directory),group_id=args.group_id,member_id=args.member_id))
            plan=make_plan(inputs,phase=args.phase,max_cost_cny=args.max_cost_cny,minutes=args.valid_minutes,
                prerequisite=args.provider_receipt)
            write_new(args.output,plan)
            print(json.dumps({'code':'QWEN_TRIAL_PLAN_READY','plan_sha256':_hash(plan),
                'scope_sha256':plan['scope_sha256'],'reservation_cny':plan['scope']['cost']['reservation_cny'],
                'network_requests':0},ensure_ascii=False));return 0
        if args.approve:
            if (args.plan is None or args.output is None or args.confirm_provider_network or args.confirm_qq_network
                    or not sys.stdin.isatty()):raise BotError('TRIAL_INTERACTIVE_APPROVAL_REQUIRED')
            plan=read_json(args.plan);inputs=validate_record(plan)
            # Check the existing instance again before creating an approval, without any key.
            _,_,config,_,_=inputs_snapshot(inputs)
            mon=InstanceMonitoring(config)
            if inputs_snapshot(inputs,mon)[-1]!=plan['bindings_sha256']:raise BotError('TRIAL_BINDINGS_CHANGED')
            if plan['phase']=='qq':
                req=plan['prerequisite']
                if prerequisite_valid(read_json(req['path']),plan['scope_sha256'],plan['bindings_sha256'])!=req['sha256']:
                    raise BotError('TRIAL_PROVIDER_PREREQUISITE_REQUIRED')
            digest=_hash(plan)
            print('仅本机操作者审批：请先审阅计划中的 Provider/模型/实例/设备/群成员/期限/费用。',file=sys.stderr)
            print('接受 SIMULATOR 数据披露、北京区价格/上下文依据、SDK 线程无法强制退出及远端计费未知风险。',file=sys.stderr)
            print('只展示通过封闭合同的AI解释要点；不展示原始模型正文，不代表通用事实核验。',file=sys.stderr)
            expected='APPROVE '+digest[:12]
            print('确认全部以上条件请输入 '+expected+'：',file=sys.stderr,flush=True)
            if input().strip()!=expected:
                raise BotError('TRIAL_APPROVAL_NOT_CONFIRMED')
            approval=approve_plan(plan);write_new(args.output,approval)
            print(json.dumps({'code':'QWEN_TRIAL_APPROVED','approval_sha256':_hash(approval),
                'status':'local_experimental','qualification_id':None,'network_requests':0}));return 0
        if args.approval is None or args.approval_sha256 is None:raise BotError('TRIAL_APPROVAL_REQUIRED')
        # Reject missing network opt-in before reading approvals, data or credentials.
        if args.run_provider and (not args.confirm_provider_network or args.confirm_qq_network):
            raise BotError('TRIAL_PROVIDER_NETWORK_CONFIRMATION_REQUIRED')
        if args.run_qq and not (args.confirm_provider_network and args.confirm_qq_network):
            raise BotError('TRIAL_QQ_AND_PROVIDER_CONFIRMATION_REQUIRED')
        if args.check and (args.confirm_provider_network or args.confirm_qq_network):raise BotError('INVALID_TRIAL_ARGUMENTS')
        record=ApprovalFile(args.approval,args.approval_sha256)
        if not args.check and record.value['phase']!=('provider' if args.run_provider else 'qq'):
            raise BotError('TRIAL_PHASE_MISMATCH')
        runtime=compose_trial(record)
        if args.check:
            print(json.dumps({'code':'QWEN_TRIAL_APPROVAL_VALID_NETWORK_NOT_STARTED','status':'local_experimental',
                'scope_matches':True,'credential_checked':False,'network_requests':0}));return 0
        if args.output is None:raise BotError('TRIAL_RESULT_OUTPUT_REQUIRED')
        candidate_output=local_path(args.output)
        if candidate_output.exists():raise BotError('TRIAL_OUTPUT_EXISTS')
        checkpoint=candidate_output.with_name(candidate_output.stem+'.delivery.json')
        if args.run_qq and checkpoint.exists():raise BotError('TRIAL_OUTPUT_EXISTS')
        output=candidate_output
        if args.run_provider:
            result=provider_turn(runtime,args.question)
            report=result_record(runtime,result)
            return publish_result(output,report,0 if report['completed'] else 1)
        runtime.qq_outcomes=run_qq(runtime,args.run_seconds,
            receipt_sink=lambda receipt:delivery_checkpoint(runtime,checkpoint,receipt))
        cancelled=runtime.qq_stop_reason=='QQ_CANCELLED'
        report=qq_result_record(runtime,code='QWEN_TRIAL_CANCELLED' if cancelled else 'QWEN_QQ_TRIAL_STOPPED')
        return publish_result(output,report,1 if cancelled or report.get('report_error') else 0)
    except KeyboardInterrupt:
        if (runtime is not None and runtime.session.handle is not None
                and runtime.session.handle.state not in ('COMPLETED','FAILED','CANCELLED')):
            runtime.session.handle.cancel();runtime.session.handle.abort_io()
        report=({'code':'QWEN_TRIAL_CANCELLED','automatic_retry':False} if runtime is None else
            qq_result_record(runtime,code='QWEN_TRIAL_CANCELLED') if runtime.session.approval.phase=='qq' else
            result_record(runtime,code='QWEN_TRIAL_CANCELLED'))
        if output is not None:return publish_result(output,report,1)
        print(json.dumps(report,ensure_ascii=False),flush=True);return 1
    except Exception as error:
        report=({'code':_error_code(error),'automatic_retry':False} if runtime is None else
            qq_result_record(runtime,code=_error_code(error)) if runtime.session.approval.phase=='qq' else
            result_record(runtime,code=_error_code(error)))
        # Never overwrite an existing record or leak exception/request/response text.
        if output is not None:return publish_result(output,report,1)
        print(json.dumps(report,ensure_ascii=False),flush=True);return 1


if __name__=='__main__':raise SystemExit(main())
