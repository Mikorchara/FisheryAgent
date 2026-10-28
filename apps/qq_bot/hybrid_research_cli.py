"""Explicit local Provider experiments. Check is offline; never starts QQ."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading
import time
import uuid

from apps.ai_backend.sdk_resources import SDK_RESOURCES
from apps.ai_service.channel_hybrid_research import CONTRACT
from apps.ai_service.runtime.release_contracts import _hash
from .contracts import BotError
from .conversation_trial_cli import console_challenge
from .hybrid_research import (ROOT, HybridResearchRun, check_configuration, experiment_plan,
    error_code, private_directory, summarize, write_csv)
from .hybrid_research_suite import DEFAULT_SUITE, load_suite
from .run_consent import RunLimits, RunOwner
from .trial_configuration import TrialInputs, local_path, read_json, write_new


def console_approval(plan, stopped):
    c, a = plan['configuration'], plan['allocation']
    challenge = 'APPROVE '+_hash(plan)[:12]
    print(f"本地Hybrid研究：{c['provider']} / {c['model']}；Prompt {c['prompt_id']}",flush=True)
    print(f"实例 {c['instance_id']} / 设备 {c['device_id']} / {c['data_root']}",flush=True)
    print(f"授权群摘要 {c['group_ref']} / 成员摘要 {c['member_ref']}（不连接QQ、不发送消息）",flush=True)
    print(f"Scope {c['scope_sha256']}",flush=True)
    print(f"{a['max_turns']} Turn / 最多{a['max_model_requests']}请求 / {a['run_count']}个独立Run；每请求512输出Token，单轮90秒，零重试。",flush=True)
    print(f"实验总预算{a['total_budget_cny']}元；各Run预算合计{a['total_run_budgets_cny']}元；每轮保守预留{a['reservation_per_turn_cny']}元。不是云平台账单硬上限。",flush=True)
    print(f"合同静态单价（北京，每百万Token）：输入{c['static_price_input_per_million_cny']}元，"
          f"输出{c['static_price_output_per_million_cny']}元；未在线核价，请自行核对。",flush=True)
    for r in a['runs']:
        print(f"Run {r['run']}: {[e['case']['id']+'#'+str(e['repetition']) for e in r['entries']]}；"
              f"{r['max_turns']}轮/{r['max_model_requests']}请求/{r['seconds']}秒/{r['budget_cny']}元。",flush=True)
    print('普通自然语言可能收费；披露SIMULATOR及最小投影历史；本地文本未经通用事实核验，不能自动发QQ。',flush=True)
    print('SDK无法强停不合作线程，远端计算/账单可能未知；失败不退许可、不自动重试，退出不恢复余额。',flush=True)
    print('本地原始模型正文保存：'+str(plan['raw_model_output_saved'])+'；仅受保护review目录，普通日志无正文。',flush=True)
    print('批准本计划逐项列出的全部独立Run请输入 '+challenge+'；Enter取消。',flush=True)
    return console_challenge(challenge, stopped, plan['approval_deadline'])


def run_experiment(inputs, plan, directory, *, prompt=console_approval, async_client_factory=None,
                   clock=None, monotonic=time.monotonic, stop_event=None, emit=lambda value:None):
    """Sequential finite experiment controller, not a new Agent or model retry loop."""
    directory=local_path(directory);stopped=stop_event or threading.Event()
    rows=[];runs=[];owner=None;host=None;code='RESEARCH_COMPLETED';approved=False;report=None
    deadline=monotonic()+plan['allocation']['experiment_seconds']
    try:
        if any(directory.iterdir()):raise BotError('RUN_DIRECTORY_NOT_EMPTY')
        write_new(directory/'plan.json',plan)
        if not plan['allocation']['budget_explicit']:raise BotError('EXPERIMENT_EXPLICIT_TOTAL_BUDGET_REQUIRED')
        digest=_hash(plan)
        if not prompt(plan,stopped):raise BotError('RESEARCH_OPERATOR_CANCELLED')
        if _hash(plan)!=digest:raise BotError('RESEARCH_PLAN_CHANGED')
        if datetime.now(timezone.utc)>=datetime.fromisoformat(plan['approval_deadline']):
            raise BotError('RESEARCH_APPROVAL_EXPIRED')
        c=plan['configuration']
        checked=check_configuration(inputs,instance_root=Path(c['data_root']),instance_id=c['instance_id'],
            device_id=c['device_id'],memory_fixture=async_client_factory is not None)
        if checked!=c:raise BotError('RESEARCH_CONFIGURATION_CHANGED')
        SDK_RESOURCES.assert_healthy()
        # A process-owned create-only claim plus a live call. Copied JSON grants nothing.
        claim_id=uuid.uuid4().hex
        owner=RunOwner(directory,claim_id,_hash(plan))
        approval=dict(contract=CONTRACT,plan_sha256=_hash(plan),
            approved_at=datetime.now(timezone.utc).isoformat(),claim_id=claim_id,
            process_only=True,resume=False,qualification_id=None,
            independent_run_count=plan['allocation']['run_count'])
        write_new(directory/'approval.json',approval)
        approval_digest=_hash(approval)
        def batch_guard():
            owner.check()
            if _hash(read_json(directory/'approval.json'))!=approval_digest:
                raise BotError('RESEARCH_BATCH_APPROVAL_CHANGED')
        approved=True
        for allocation in plan['allocation']['runs']:
            if stopped.is_set():raise BotError('RESEARCH_CANCELLED')
            if monotonic()>=deadline:raise BotError('RESEARCH_EXPERIMENT_EXPIRED')
            owner.check()
            run_dir=private_directory(directory/f"run-{allocation['run']:03d}")
            host=HybridResearchRun(inputs,run_dir,instance_root=Path(c['data_root']),
                instance_id=c['instance_id'],device_id=c['device_id'],
                limits=RunLimits(allocation['max_turns'],min(allocation['seconds'],max(1,int(deadline-monotonic()))),allocation['budget_cny']),
                async_client_factory=async_client_factory,clock=clock,monotonic=monotonic,
                batch_guard=batch_guard,allow_raw=plan['raw_model_output_saved'])
            host.approve(host.plan(),confirmed=True)  # This exact enumerated Run was in the human batch challenge.
            for entry in allocation['entries']:
                owner.check()
                if monotonic()>=deadline:stopped.set()
                row=host.execute_case(entry,save_raw=plan['raw_model_output_saved'],stop_event=stopped)
                row['run']=allocation['run'];rows.append(row)
                emit(dict(case_id=row['case_id'],repetition=row['repetition'],branch=row['actual_branch'],
                    model_requests=row.get('model_requests',0),contract_valid=row['model_contract_valid'],code=row['code']))
                if row['stop_required']:raise BotError(row['code'] or 'RESEARCH_STOPPED')
            host.close()
            run_report=host.report('RESEARCH_RUN_COMPLETED')
            write_new(run_dir/'result.json',run_report);runs.append(run_report)
            host=None
    except (Exception,KeyboardInterrupt) as error:code=error_code(error)
    finally:
        if host is not None:
            try:
                host.close();partial=host.report(code);runs.append(partial)
                write_new(host.directory/'result.json',partial)
            except Exception:code='RESEARCH_RUN_REPORT_FAILED'
        if owner is not None:owner.close()
        report=dict(contract=CONTRACT,code=code,completed=code=='RESEARCH_COMPLETED',
            report_saved=True,approved=approved,offline_test=async_client_factory is not None,
            scope_sha256=plan['configuration']['scope_sha256'],
            summary=summarize(rows,planned_turns=plan['allocation']['max_turns']),
            runs=runs,rows=rows,ram_cleared=all(r['ram_cleared'] for r in runs),
            qq_network=False,qq_api_accepted=False,client_display_confirmed=False,
            automatic_retry=False,resume=False)
        try:
            write_csv(directory/'results.csv',rows)
            write_new(directory/'manual-review.json',dict(contract=CONTRACT,rows=[dict(
                case_id=r['case_id'],repetition=r['repetition'],answering_quality_correct=None,
                context_understanding_correct=None,notes='') for r in rows]))
        except Exception:
            report.update(code='RESEARCH_AUX_REPORT_FAILED',completed=False)
        try:
            # Final result is written last, so it cannot claim success before an
            # auxiliary report failure. Never overwrite a partial existing file.
            write_new(directory/'result.json',report)
        except Exception:
            report.update(code='RESEARCH_FINAL_REPORT_FAILED',completed=False,report_saved=False)
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description='本地Hybrid科研实验；Check不打开实例/密钥/网络，不连接QQ')
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--check',action='store_true');modes.add_argument('--run',action='store_true')
    parser.add_argument('--request-file',type=Path,required=True)
    parser.add_argument('--instance-root',type=Path,required=True)
    parser.add_argument('--instance-id',required=True);parser.add_argument('--device-id',required=True)
    parser.add_argument('--suite',type=Path,default=DEFAULT_SUITE)
    parser.add_argument('--category',action='append',choices=tuple('ABCDE'))
    parser.add_argument('--case-id',action='append');parser.add_argument('--repeat',type=int,default=1)
    parser.add_argument('--total-budget-cny');parser.add_argument('--run-seconds',type=int,default=1800)
    parser.add_argument('--experiment-seconds',type=int,default=7200)
    parser.add_argument('--report-root',type=Path);parser.add_argument('--save-raw',action='store_true')
    parser.add_argument('--confirm-provider-network',action='store_true')
    parser.add_argument('--confirm-instance-read',action='store_true')
    args=parser.parse_args(argv)
    try:
        inputs=TrialInputs.parse(read_json(local_path(args.request_file)))
        cases=load_suite(local_path(args.suite))
        plan=experiment_plan(inputs,cases,instance_root=args.instance_root,instance_id=args.instance_id,
            device_id=args.device_id,categories=args.category,case_ids=args.case_id,repetitions=args.repeat,
            total_budget_cny=args.total_budget_cny,run_seconds=args.run_seconds,
            experiment_seconds=args.experiment_seconds,save_raw=args.save_raw)
        plan['approval_deadline']=(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()
        if args.check:
            # Static synthetic questions are not private chat. Identities remain hash-only.
            print(json.dumps(plan,ensure_ascii=False));return 0
        if not (args.confirm_provider_network and args.confirm_instance_read):
            raise BotError('RESEARCH_EXPLICIT_CONSENT_REQUIRED')
        if not plan['allocation']['budget_explicit']:raise BotError('EXPERIMENT_EXPLICIT_TOTAL_BUDGET_REQUIRED')
        root=local_path(args.report_root or ROOT/'outputs/hybrid-research')
        if not root.is_relative_to(ROOT/'outputs'):raise BotError('RESEARCH_OUTPUTS_REQUIRED')
        if not root.exists():private_directory(root)
        else:
            from apps.ai_backend.secure_files import inspect_policy
            inspect_policy(root,directory=True)
        directory=private_directory(root/('experiment-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:12]))
        print('实验报告目录：'+str(directory),flush=True)
        report=run_experiment(inputs,plan,directory,emit=lambda v:print(json.dumps(v,ensure_ascii=False),flush=True))
        print(json.dumps(dict(code=report['code'],report_saved=report['report_saved'],
            summary=report['summary'],result=str(directory/'result.json')),ensure_ascii=False),flush=True)
        return 0 if report['completed'] and report['report_saved'] else 1
    except (Exception,KeyboardInterrupt) as error:
        print(json.dumps(dict(contract=CONTRACT,code=error_code(error),automatic_retry=False)),flush=True);return 1


if __name__=='__main__':raise SystemExit(main())
