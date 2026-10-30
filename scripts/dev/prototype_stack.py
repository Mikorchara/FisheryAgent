"""Prototype console orchestration. Existing Hybrid approval and local launcher stay owners."""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
DEMO = ROOT/'apps/data'
CONFIG = ROOT/'outputs/qq-daily-config'
SOURCE = ROOT/'outputs/qq-bot/conversation.request.json'
MARKER = 'prototype-daily-data@1'


def emit(code, **fields):
    print(json.dumps(dict(code=code, **fields), ensure_ascii=False), flush=True)


def local_output(path):
    from apps.ai_backend.secure_files import guard_path
    path = Path(os.path.abspath(path))
    guard_path(path)
    if not path.is_relative_to(ROOT/'outputs'): raise RuntimeError('PROTOTYPE_OUTPUT_PATH_REQUIRED')
    return path


def local_data(path):
    from apps.management_web.instance import safe_path
    path = Path(os.path.abspath(path))
    safe_path(path)
    if path == ROOT/'apps/data': return path
    return local_output(path)  # Explicit synthetic/test instances remain supported.


def selected(request=None):
    from apps.qq_bot.trial_configuration import TrialInputs, read_json
    from apps.qq_bot.hybrid_trial import check_configuration
    request = Path(request) if request else CONFIG/'request.json'
    inputs = TrialInputs.parse(read_json(request))
    return inputs, check_configuration(inputs)


def prepare_demo(with_bot=False):
    """Prepare the one daily instance explicitly; retain every legacy source."""
    from apps.management_paths import ManagementPaths
    from apps.management_web.instance import initialize_instance, validate_instance
    from apps.qq_bot.trial_configuration import read_json, write_new
    from dataclasses import replace
    root, cfg = local_data(DEMO), local_output(CONFIG)
    original = summary = None
    if with_bot:
        original, summary = selected(SOURCE)
        if summary['device_id'] != 'sim-pond-1': raise RuntimeError('PROTOTYPE_DEMO_DEVICE_MISMATCH')
    (ROOT/'outputs').mkdir(exist_ok=True)
    marker = dict(contract=MARKER, root=str(root))
    if root.exists():
        if read_json(root/'launcher-instance.json') != marker:
            raise RuntimeError('PROTOTYPE_DEMO_MARKER_REQUIRED')
        validate_instance(ManagementPaths.resolve(ROOT, data_root=root))
    else:
        if root == ROOT/'apps/data':
            from scripts.dev.prepare_prototype_data import prepare_daily_data
            prepare_daily_data(ROOT)
        else:
            initialize_instance(ManagementPaths.resolve(ROOT, data_root=root))
            write_new(root/'launcher-instance.json', marker)
        emit('PROTOTYPE_DEMO_CREATED', data_root=str(root))
    if with_bot:
        origin = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
        expected = dict(contract=MARKER, source_sha256=origin, data_root=str(root))
        if cfg.exists():
            if read_json(cfg/'origin.json') != expected:
                raise RuntimeError('PROTOTYPE_DEMO_CONFIG_CHANGED_REVIEW_REQUIRED')
        else:
            from apps.qq_bot.monitoring_source import load_monitoring_config
            cfg.mkdir()
            write_new(cfg/'monitoring.json', dict(schema_version=1, instance_id='prototype-daily',
                data_root=str(root), devices=list(load_monitoring_config(original.monitoring_config).devices)))
            # Reference approved metadata/Policy in place; no credentials or approvals are copied.
            inputs = replace(original, monitoring_config=cfg/'monitoring.json')
            write_new(cfg/'request.json', inputs.dictionary())
            write_new(cfg/'origin.json', expected)
        selected()
    return root


def preflight(*, request=None, data_root=None, with_bot=False, bot_only=False, port=8766):
    from scripts.dev.local_session import require_free_port
    from apps.management_web.instance import safe_path
    if os.name != 'nt': raise RuntimeError('PROTOTYPE_WINDOWS_REQUIRED')
    if not bot_only: require_free_port(port)
    summary = None
    pending = False
    if with_bot:
        chosen = Path(request) if request else CONFIG/'request.json'
        if request is None and not chosen.exists():
            _, summary = selected(SOURCE)
            root = DEMO
            pending = True
        else:
            _, summary = selected(chosen)
            root = Path(summary['data_root'])
        if data_root is not None and Path(data_root) != root:
            raise RuntimeError('PROTOTYPE_INSTANCE_MISMATCH')
    else:
        root = Path(data_root) if data_root else DEMO
    root = local_data(root)
    if not root.exists():
        if root != DEMO: raise RuntimeError('PROTOTYPE_INSTANCE_MISSING')
        pending = True
    elif not bot_only:
        safe_path(root)
        if any(not (root/name).is_file() for name in ('monitoring.sqlite3', 'knowledge.sqlite3')):
            raise RuntimeError('PROTOTYPE_WEB_INSTANCE_INCOMPLETE')
    return root, dict(code='PROTOTYPE_STACK_CHECKED', data_root=str(root), bot=with_bot,
        prepare_required=pending, summary_role='source_template' if pending and with_bot else 'run_configuration',
        summary=summary, database_opened=False, credential_checked=False,
        qq_provider_network_requests=0)


def request_stop(directory, role='all'):
    from apps.qq_bot.trial_configuration import read_json, write_new
    directory = local_output(directory)
    if not directory.is_relative_to(ROOT/'outputs/prototype-stack'):
        raise RuntimeError('PROTOTYPE_STOP_DIRECTORY_REJECTED')
    manifest = read_json(directory/'stack.json')
    if manifest.get('contract') != 'prototype-stack@1': raise RuntimeError('PROTOTYPE_STOP_DIRECTORY_REJECTED')
    value = dict(nonce=manifest['nonce'], role=role)
    path = directory/('stop-'+role+'.json')
    if path.exists():
        if read_json(path) != value: raise RuntimeError('PROTOTYPE_STOP_RECORD_INVALID')
    else: write_new(path, value)


def launch_stack(*, request=None, data_root=None, with_bot=False, bot_only=False,
                 port=8766, scenario='normal', seed=42, interactive=False, browser=False,
                 prepare=False, seconds=1800, assistant=True, demo_video=None):
    from scripts.dev.local_session import run_local
    from scripts.dev.windows_job import own_process_tree
    from scripts.dev.console_job import ConsoleJob
    from scripts.dev.prototype_console import stopped
    from apps.ai_backend.secure_files import exclusive_lock, FileBusyError
    from apps.management_web.instance import validate_instance
    from apps.management_paths import ManagementPaths
    from apps.qq_bot.trial_configuration import write_new
    own_process_tree()
    if demo_video is not None:
        from apps.management_web.demo_video import LocalDemoVideo
        LocalDemoVideo.open(demo_video)
    root, checked = preflight(request=request, data_root=data_root, with_bot=with_bot,
                              bot_only=bot_only, port=port)
    parent = local_output(ROOT/'outputs/prototype-stack'); parent.mkdir(parents=True, exist_ok=True)
    locks = parent/'locks'; locks.mkdir(exist_ok=True)
    jobs, children = {}, {}
    directory = None
    result = 0
    with ExitStack() as guards:
        try:
            identity = hashlib.sha256(str(root).casefold().encode()).hexdigest()
            guards.enter_context(exclusive_lock(locks/(identity+'.lock')))
            if with_bot:
                group = checked['summary']['group_ref']
                guards.enter_context(exclusive_lock(locks/('bot-'+group+'.lock')))
            if prepare:
                if request is not None or data_root is not None:
                    raise RuntimeError('PREPARE_DEMO_ONLY_DEFAULT_TARGETS')
                prepare_demo(with_bot)
            elif checked['prepare_required']: raise RuntimeError('PROTOTYPE_DEMO_PREPARATION_REQUIRED')
            if not bot_only: validate_instance(ManagementPaths.resolve(ROOT, data_root=root))
            request = Path(request) if request else CONFIG/'request.json'
            directory = parent/('stack-'+uuid.uuid4().hex); directory.mkdir()
            write_new(directory/'stack.json', dict(contract='prototype-stack@1', nonce=uuid.uuid4().hex,
                controller_pid=os.getpid(), data_root=str(root), with_bot=with_bot,
                web_assistant_enabled=assistant and not bot_only))
            emit('PROTOTYPE_STACK_STARTING', run_directory=str(directory))

            def spawn(role, command=None, options=None):
                job = ConsoleJob(); jobs[role] = job
                vector = [sys.executable, '-X', 'utf8', '-I', '-B', '-u',
                    str(ROOT/'scripts/dev/prototype_console.py'), '--role', role,
                    '--directory', str(directory), '--job', job.name]
                if role == 'bot': vector += ['--request-file', str(request), '--seconds', str(seconds)]
                else: vector += ['--', *command]
                kwargs = dict(options or {}); kwargs.update(cwd=ROOT, creationflags=subprocess.CREATE_NEW_CONSOLE)
                child = subprocess.Popen(vector, **kwargs); children[role] = child
                emit('PROTOTYPE_CHILD_CREATED', role=role, bootstrap_pid=child.pid)
                return child

            def launch(command, **options):
                role = command[command.index('--console-role')+1]
                child = spawn(role, command, options)
                if role == 'simulator' and with_bot: spawn('bot')
                return child

            def sleep(delay):
                if stopped(directory, 'all'): raise KeyboardInterrupt()
                time.sleep(delay)

            if bot_only:
                child = spawn('bot')
                while child.poll() is None: sleep(.1)
                result = child.returncode
            else:
                result = run_local(scenario, port, seed, assistant=assistant, data_root=root,
                    show_terminals=True, interactive_scenario=interactive, open_browser=browser,
                    launch=launch, sleep=sleep,demo_video=demo_video)
        except FileBusyError: raise RuntimeError('PROTOTYPE_INSTANCE_OR_BOT_ALREADY_RUNNING') from None
        except KeyboardInterrupt: result = 0
        except Exception:
            result = 1
            raise
        finally:
            if directory is not None:
                bot = children.get('bot')
                bot_failed = bot is not None and bot.poll() not in (None, 0)
                try: request_stop(directory)
                except Exception:
                    result = 1
                    emit('PROTOTYPE_STOP_RECORD_FAILED')
                # Worker requests cooperative interruption first. Only this run's jobs may be terminated.
                for role, child in tuple(children.items()):
                    try: child.wait(timeout=25 if role == 'bot' else 2)
                    except subprocess.TimeoutExpired:
                        try:
                            jobs[role].terminate()
                            child.wait(timeout=5)
                        except Exception:
                            result = 1
                            emit('PROTOTYPE_OWNED_JOB_STOP_FAILED', role=role)
                        emit('PROTOTYPE_OWNED_JOB_TERMINATED', role=role, report_complete=False)
                        if role == 'bot': result = 1
                    finally: jobs[role].close()
                records = {}
                for role, child in children.items():
                    path = directory/(role+'.status.json')
                    try: status = json.loads(path.read_text(encoding='utf8'))
                    except (OSError, ValueError): status = {}
                    records[role] = dict(bootstrap_pid=child.pid, pid=status.get('pid'),
                        exit_code=child.returncode, code=status.get('code'))
                if bot_failed: result = 1
                write_new(directory/'result.json', dict(code='PROTOTYPE_STACK_STOPPED', exit_code=result,
                    children=records, automatic_restart=False))
                emit('PROTOTYPE_STACK_STOPPED', exit_code=result, run_directory=str(directory))
    return result


def main(argv=None):
    from scripts.dev.local_session import DEMO_SCENARIOS
    p = argparse.ArgumentParser(description='Prototype two/three independent terminals; original Hybrid consent')
    p.add_argument('--request-file', type=Path); p.add_argument('--data-root', type=Path)
    p.add_argument('--port', type=int, default=8766); p.add_argument('--seed', type=int, default=42)
    p.add_argument('--scenario', choices=tuple(k for k, _ in DEMO_SCENARIOS), default='normal')
    for flag in ('with-bot', 'bot-only', 'check', 'prepare-demo', 'interactive-scenario', 'open-browser'):
        p.add_argument('--'+flag, action='store_true')
    p.add_argument('--seconds', type=int, default=1800)
    p.add_argument('--demo-video',type=Path)
    p.add_argument('--no-assistant', action='store_true', help='Disable Web AI and Settings; never affects QQ consent')
    p.add_argument('--stop-directory', type=Path); p.add_argument('--stop-bot', action='store_true')
    args = p.parse_args(argv)
    try:
        if args.stop_directory:
            request_stop(args.stop_directory, 'bot' if args.stop_bot else 'all')
            emit('PROTOTYPE_STACK_STOP_REQUESTED'); return 0
        if not 1 <= args.port <= 65535 or not 1 <= args.seconds <= 1800:
            raise RuntimeError('PROTOTYPE_INVALID_PORT_OR_DURATION')
        with_bot = args.with_bot or args.bot_only
        if args.check:
            if args.demo_video is not None:
                from apps.management_web.demo_video import LocalDemoVideo
                LocalDemoVideo.open(args.demo_video)
            _, summary = preflight(request=args.request_file, data_root=args.data_root,
                with_bot=with_bot, bot_only=args.bot_only, port=args.port)
            summary['web_assistant_enabled'] = not args.no_assistant and not args.bot_only
            emit(**summary); return 0
        return launch_stack(request=args.request_file, data_root=args.data_root, with_bot=with_bot,
            bot_only=args.bot_only, port=args.port, scenario=args.scenario, seed=args.seed,
            interactive=args.interactive_scenario, browser=args.open_browser,
            prepare=args.prepare_demo, seconds=args.seconds, assistant=not args.no_assistant,demo_video=args.demo_video)
    except Exception as error:
        code = getattr(error, 'code', str(error) if isinstance(error, RuntimeError) else 'PROTOTYPE_STACK_FAILED')
        if not re.fullmatch('[A-Z][A-Z0-9_]{0,80}', str(code)): code = 'PROTOTYPE_STACK_FAILED'
        emit(code); return 1


if __name__ == '__main__': raise SystemExit(main())
