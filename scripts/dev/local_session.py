"""Small local launcher: own two processes, one temporary token, no Policy writes."""
import argparse
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def require_free_port(port):
    # No discovery/termination of the process occupying the port.
    with socket.socket() as connection:
        connection.settimeout(.3)
        if connection.connect_ex(('127.0.0.1',port)) == 0:
            raise RuntimeError('LOCAL_PORT_IN_USE')
    with socket.socket() as probe:
        # Allow a just-stopped server's TIME_WAIT, after rejecting live listeners.
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(('127.0.0.1',port))
        except OSError:
            raise RuntimeError('LOCAL_PORT_IN_USE') from None


def commands(python, scenario, port, seed, *, assistant=True, streaming=True, multi_round=True, history=True):
    server = [python,'-m','apps.management_web','--port',str(port),'--enable-ingestion']
    if assistant:
        server += ['--enable-assistant']
        server += [flag for enabled,flag in ((multi_round,'--assistant-multi-round-trial'),
            (streaming,'--assistant-streaming-trial'),(history,'--assistant-history-trial')) if enabled]
    return (server,[python,'-m','apps.simulator','--scenario',scenario,'--server',f'http://127.0.0.1:{port}',
                    '--seed',str(seed),'--interval','10'])


def ready(port):
    connection = HTTPConnection('127.0.0.1',port,timeout=.5)
    try:
        connection.request('GET','/api/bootstrap')
        response = connection.getresponse()
        return response.status == 200 and isinstance(json.load(response),dict)
    except (OSError,ValueError):
        return False
    finally:
        connection.close()


def run_local(scenario='normal', port=8766, seed=42, *, root=ROOT, python=None,
              assistant=True, streaming=True, multi_round=True, history=True,
              launch=subprocess.Popen, is_ready=ready, sleep=time.sleep, emit=print):
    require_free_port(port)
    child_env = os.environ.copy()
    child_env['FISHERY_SIM_INGEST_TOKEN'] = secrets.token_hex(32)
    children = []
    try:
        server,simulator = commands(python or sys.executable,scenario,port,seed,
            assistant=assistant,streaming=streaming,multi_round=multi_round,history=history)
        options = dict(cwd=root,env=child_env)
        if os.name == 'nt':
            options['creationflags'] = subprocess.CREATE_NO_WINDOW
        # Never echo command environments or child output (which may contain local paths).
        options.update(stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        children.append(launch(server,**options))
        deadline = time.monotonic()+20
        while not is_ready(port):
            if children[0].poll() is not None:
                raise RuntimeError('LOCAL_SERVER_START_FAILED')
            if time.monotonic() >= deadline:
                raise RuntimeError('LOCAL_SERVER_START_TIMEOUT')
            sleep(.1)
        if children[0].poll() is not None:
            raise RuntimeError('LOCAL_SERVER_START_FAILED')
        children.append(launch(simulator,**options))
        emit(f'本机服务 http://127.0.0.1:{port} · 场景 {scenario} · 每10秒上报。Ctrl+C 停止两进程。')
        emit('已批准功能按启动参数启用；Tool 仍须用户授权。三工具候选未开放，启动不调用模型。')
        while all(child.poll() is None for child in children):
            sleep(.2)
        raise RuntimeError('LOCAL_CHILD_EXITED')
    except KeyboardInterrupt:
        emit('正在停止本次启动的服务器和模拟器。')
        return 0
    finally:
        # Only Popen objects created here are owned. Leave every other process alone.
        for child in reversed(children):
            if child.poll() is None:
                try:
                    child.terminate()
                except ProcessLookupError:
                    pass
        for child in reversed(children):
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill(); child.wait(timeout=5)
        child_env.pop('FISHERY_SIM_INGEST_TOKEN',None)


def main(argv=None):
    parser=argparse.ArgumentParser(description='本机管理服务+模拟器；不会发起模型请求')
    parser.add_argument('--scenario',choices=('normal','low_oxygen','suspected_disease','reduced_feeding','combined_anomaly','device_offline'),default='normal')
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--seed',type=int,default=42)
    for name in ('assistant','streaming','multi-round','history'):
        parser.add_argument('--no-'+name,action='store_true')
    args=parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('INVALID_LOCAL_PORT')
    try:
        return run_local(args.scenario,args.port,args.seed,assistant=not args.no_assistant,
            streaming=not args.no_streaming,multi_round=not args.no_multi_round,history=not args.no_history)
    except RuntimeError as error:
        print(str(error)+' · 未关闭任何外部进程；请检查端口或手动使用原CLI。',file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
