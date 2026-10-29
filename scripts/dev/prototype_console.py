"""Owned Prototype console; Bot delegates unchanged Hybrid CLI with its own approval."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import uuid

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))


def stopped(directory, role):
    manifest = json.loads((directory/'stack.json').read_text(encoding='utf8'))
    for name in ('all', role):
        path = directory/('stop-'+name+'.json')
        if path.exists():
            if json.loads(path.read_text(encoding='utf8')) != dict(nonce=manifest['nonce'], role=name):
                raise RuntimeError('PROTOTYPE_STOP_RECORD_INVALID')
            return True
    return False


def status(directory, role, **fields):
    import ctypes
    ctypes.windll.kernel32.GetConsoleWindow.restype = ctypes.c_void_p
    target = directory/(role+'.status.json'); temp = directory/('.'+uuid.uuid4().hex+'.tmp')
    with temp.open('x', encoding='utf8') as stream:
        json.dump(dict(pid=os.getpid(), console_hwnd=ctypes.windll.kernel32.GetConsoleWindow(),
            role=role, **fields), stream); stream.flush(); os.fsync(stream.fileno())
    os.replace(temp, target)


class Tee:
    def __init__(self, console, log): self.console, self.log = console, log
    def write(self, text): self.log.write(text); self.log.flush(); return self.console.write(text)
    def flush(self): self.log.flush(); self.console.flush()
    def __getattr__(self, key): return getattr(self.console, key)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--role', choices=('web', 'simulator', 'bot'), required=True)
    p.add_argument('--directory', type=Path, required=True); p.add_argument('--job', required=True)
    p.add_argument('--request-file', type=Path); p.add_argument('--seconds', type=int, default=1800)
    p.add_argument('command', nargs=argparse.REMAINDER); args = p.parse_args(argv)
    from scripts.dev.console_job import join
    join(args.job)
    import ctypes
    ctypes.windll.kernel32.SetConsoleTitleW('Prototype · '+args.role+' · '+args.directory.name)
    stop = threading.Event(); watcher = None; code = 1; reason = 'PROTOTYPE_SERVICE_FAILED'
    try:
        status(args.directory, args.role, state='RUNNING', code='PROTOTYPE_SERVICE_RUNNING')
        if args.role == 'bot':
            import _thread
            import signal
            # A launcher can inherit an ignored console Ctrl+C disposition.
            # Install Python's cooperative handler in this owned worker only.
            signal.signal(signal.SIGINT, signal.default_int_handler)
            from apps.qq_bot.hybrid_trial_cli import main as run_hybrid
            def watch():
                while not stop.wait(.1):
                    try: requested = stopped(args.directory, 'bot')
                    except Exception: requested = True
                    if requested:
                        _thread.interrupt_main(); return
            watcher = threading.Thread(target=watch, name='prototype-stop', daemon=False); watcher.start()
            report = args.directory/'bot-run'; report.mkdir()
            # Confirmation flags select the original operator workflow, not its approval.
            # run_hybrid still shows and requires a fresh APPROVE HYBRID challenge.
            code = run_hybrid(['--request-file', str(args.request_file), '--run', '--directory', str(report),
                '--run-seconds', str(args.seconds), '--confirm-instance-read', '--confirm-provider-network',
                '--confirm-qq-network', '--enable-mention-ai', '--confirm-general-experimental'])
        else:
            command = args.command[1:] if args.command[:1] == ['--'] else args.command
            if str(ROOT/'scripts/dev/local_session.py') not in command or '--console-role' not in command:
                raise RuntimeError('INVALID_PROTOTYPE_SERVICE_COMMAND')
            at = command.index('--console-role')
            if command[at+1] != args.role: raise RuntimeError('INVALID_PROTOTYPE_SERVICE_COMMAND')
            from scripts.dev.local_session import console_role
            with (args.directory/(args.role+'.log')).open('a', encoding='utf8') as log:
                out, err = sys.stdout, sys.stderr
                try:
                    sys.stdout, sys.stderr = Tee(out, log), Tee(err, log)
                    code = console_role(command[at+1:])
                finally: sys.stdout, sys.stderr = out, err
        reason = 'PROTOTYPE_SERVICE_EXITED'
    except KeyboardInterrupt:
        code = 0; reason = 'PROTOTYPE_SERVICE_INTERRUPTED'
    except BaseException:
        print(json.dumps(dict(code=reason)), flush=True)
    finally:
        stop.set()
        if watcher: watcher.join(2)
        status(args.directory, args.role, state='EXITED', code=reason, exit_code=code)
    return code


if __name__ == '__main__': raise SystemExit(main())
