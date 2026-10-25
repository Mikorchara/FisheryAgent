"""Paused SDK process draft. Not registered or usable by Web, QQ or direct callers."""
from collections import deque
from dataclasses import dataclass,field
import hmac
import json
import os
from pathlib import Path
import secrets
import select
import socket
import subprocess
import sys
import threading
import time
import uuid
from urllib.parse import urlsplit

from openai.types.chat import ChatCompletion,ChatCompletionChunk

from .execution import RequestHandle,current_handle
from .model_gateway import GatewayError,StreamingModelError
from .openai_compatible_adapter import OpenAICompatibleAdapter
from .sdk_process_job import SDKJob
from .sdk_process_protocol import VERSION,CONTRACT,MAX_FRAME,Decoder,ProtocolError,encode,PAUSED_CODE


@dataclass(frozen=True,repr=False)
class OfflineSDKProcessScript:
    """Finite JSON fixtures, not callbacks/modules/URLs to load in the worker."""
    requests: tuple[dict,...] = field(repr=False)
    def __post_init__(self):
        if type(self.requests) is not tuple or not 1<=len(self.requests)<=3:raise ValueError('INVALID_PROCESS_SCRIPT')
        for item in self.requests:
            if (not isinstance(item,dict) or set(item)!={'mode','response','chunks','delay'}
                    or item['mode'] not in ('normal','wait','ignore_cancel','block_loop','hang_close','crash','ipc_drop','http_error')
                    or type(item['delay']) not in (int,float) or not 0<=item['delay']<=30
                    or not isinstance(item['chunks'],list) or not isinstance(item['response'],dict)):
                raise ValueError('INVALID_PROCESS_SCRIPT')
            encode({'v':VERSION,**item})
    def __repr__(self):return 'OfflineSDKProcessScript(<bounded-json>)'


@dataclass(frozen=True,repr=False)
class SDKProcessAuthorization:
    """Trusted server callback, not a qualification or a message-configurable switch."""
    identity: tuple[str,...]
    check: object = field(repr=False)
    def validate(self,runtime):
        if (self.identity!=(runtime.service_id,runtime.adapter_id,runtime.base_url,runtime.model)
                or not callable(self.check)):
            raise GatewayError('SDK_PROCESS_AUTHORIZATION_CHANGED')
        self.check()
        url=urlsplit(runtime.base_url)
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise GatewayError('SDK_PROCESS_HTTPS_REQUIRED')


class SDKProcessBudget:
    def __init__(self,limit=2):
        if type(limit) is not int or not 1<=limit<=2:raise ValueError('INVALID_SDK_PROCESS_LIMIT')
        self.limit=limit;self._lock=threading.Lock();self._active=set();self._failed=set()
    def reserve(self):
        with self._lock:
            if self._failed:raise GatewayError('SDK_PROCESS_QUARANTINED')
            if len(self._active)>=self.limit:raise GatewayError('SDK_PROCESS_LIMIT')
            lease=ProcessLease(self);self._active.add(lease);return lease
    def finish(self,lease):
        with self._lock:
            self._active.discard(lease)
            if lease.failure:self._failed.add(lease)
    def snapshot(self):
        with self._lock:return dict(limit=self.limit,active=len(self._active),quarantined=len(self._failed))


class ProcessLease:
    def __init__(self,budget):
        self.budget=budget;self.failure=None;self.manager=None
        self.started=False;self.exited=False;self.reaped=False;self.ack=False;self.forced=False
        self.abort_requested=False;self.task_done=None;self.calls=None;self.state='ADMITTED'
        self.stages=['ADMITTED'];self.timings={};self.peak_working_set_bytes=None
    def phase(self,state):
        self.state=state
        if len(self.stages)<12:self.stages.append(state)
    def snapshot(self):
        return dict(contract=CONTRACT,state='CLEANUP_FAILED' if self.failure else 'CLOSED' if self.reaped else 'RUNNING',
            process_state=self.state,stages=list(self.stages),process_started=self.started,
            process_exit_confirmed=self.exited,process_resources_closed=self.reaped,
            forced_termination=self.forced,sdk_close_acknowledged=self.ack,
            local_io_closed=self.exited,task_done=self.task_done,thread_started=False,thread_exited=True,
            cancel_signal_sent=self.abort_requested,cleanup_error=self.failure,quarantined=bool(self.failure),
            model_http_requests=self.calls,remote_compute_stopped='unknown',timings_ms=dict(self.timings),
            peak_working_set_bytes=self.peak_working_set_bytes)


PROCESS_BUDGET=SDKProcessBudget()


def _environment():
    # Do not enumerate/copy the parent's credential-bearing environment.
    return {k:os.environ[k] for k in ('SystemRoot','WINDIR','TEMP','TMP') if k in os.environ}


class ProcessSession:
    def __init__(self,lease,handle,*,startup,grace,launcher):
        self.lease=lease;lease.manager=self
        self.handle=handle;self.startup=startup;self.grace=grace;self.launcher=launcher
        self.cancel=threading.Event();self.done=threading.Event()
        self.process=None;self.job=None;self.sock=None;self.listener=None;self.decoder=Decoder()
        self.sid=uuid.uuid4().hex;self.started_at=time.monotonic();self.closed_event=False
    def guard(self):
        if self.cancel.is_set():raise GatewayError('USER_CANCELLED')
        self.handle.check()
    def _recv(self,deadline,guard):
        while True:
            guard()
            value=self.decoder.pop()
            if value is not None:return value
            if time.monotonic()>=deadline:raise GatewayError('SDK_PROCESS_IPC_TIMEOUT')
            readable,_,_=select.select([self.sock],[],[],min(.02,max(0,deadline-time.monotonic())))
            if readable:
                part=self.sock.recv(65536)
                if not part:raise GatewayError('SDK_PROCESS_IPC_LOST')
                self.decoder.feed(part)
    def send(self,value,deadline,guard):
        data=memoryview(encode(value))
        while data:
            guard()
            if time.monotonic()>=deadline:raise GatewayError('SDK_PROCESS_IPC_TIMEOUT')
            _,writable,_=select.select([],[self.sock],[],min(.02,max(0,deadline-time.monotonic())))
            if writable:
                sent=self.sock.send(data)
                if not sent:raise GatewayError('SDK_PROCESS_IPC_LOST')
                data=data[sent:]
    def start(self,deadline,delay):
        # BOT-3C-2B paused by user: retain the draft without enabling its I/O.
        raise GatewayError(PAUSED_CODE)
        self.lease.phase('SPAWNING')
        startup_deadline=min(deadline,time.monotonic()+self.startup)
        self.listener=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):self.listener.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        self.listener.bind(('127.0.0.1',0));self.listener.listen(1);self.listener.setblocking(False)
        self.job=SDKJob()
        worker=Path(__file__).with_name('sdk_process_worker.py')
        # No key, prompt, instance path or serialized Runtime in argv/env.
        self.process=self.launcher([sys.executable,'-I','-B','-u',str(worker)],stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,cwd=str(worker.parent),env=_environment(),
            close_fds=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.lease.started=True
        self.job.assign(self.process)
        nonce=secrets.token_hex(32)
        bootstrap=json.dumps(dict(port=self.listener.getsockname()[1],nonce=nonce,delay=delay)).encode()+b'\n'
        self.process.stdin.write(bootstrap);self.process.stdin.close()
        while self.sock is None:
            self.guard()
            if self.process.poll() is not None:raise GatewayError('SDK_PROCESS_CRASH')
            if time.monotonic()>=startup_deadline:raise GatewayError('SDK_PROCESS_START_TIMEOUT')
            readable,_,_=select.select([self.listener],[],[],.02)
            if readable:
                self.sock,_=self.listener.accept();self.sock.setblocking(False)
        hello=self._recv(startup_deadline,self.guard)
        if (set(hello)!={'v','kind','nonce','pid'} or hello['kind']!='hello'
                or type(hello['pid']) is not int or hello['pid']!=self.process.pid
                or not isinstance(hello['nonce'],str) or not hmac.compare_digest(hello['nonce'],nonce)):
            raise GatewayError('SDK_PROCESS_AUTH_FAILED')
        self.listener.close();self.listener=None
        self.lease.phase('CONNECTED')
        self.lease.timings['startup']=(time.monotonic()-self.started_at)*1000
    def receive(self,deadline,guard):
        value=self._recv(deadline,guard)
        if value.get('id')!=self.sid:raise GatewayError('SDK_PROCESS_PROTOCOL')
        return value
    def cleanup(self):
        started=time.monotonic();p=self.process
        try:
            if p is not None and p.poll() is None:
                if self.sock is not None and not self.closed_event:
                    self.lease.phase('CANCELLING')
                    try:
                        self.send({'v':VERSION,'kind':'cancel','id':self.sid},time.monotonic()+.1,lambda:None)
                        self.lease.abort_requested=True
                    except Exception:pass
                until=time.monotonic()+self.grace
                while p.poll() is None and time.monotonic()<until:
                    if self.sock is not None and not self.closed_event:
                        try:
                            frame=self.receive(min(until,time.monotonic()+.03),lambda:None)
                            if frame['kind']=='closed':self.accept_closed(frame)
                        except Exception:pass
                    else:time.sleep(.005)
                if p.poll() is None:
                    self.lease.forced=True;self.lease.phase('FORCE_TERMINATING')
                    try:p.terminate()
                    except OSError:pass
                    try:p.wait(timeout=1)
                    except (subprocess.TimeoutExpired,OSError):pass
            if p is not None and p.poll() is None:
                # Job close is an owned-tree backstop, not a success acknowledgement.
                if self.job is not None:self.job.close();self.job=None
                try:p.wait(timeout=1)
                except (subprocess.TimeoutExpired,OSError):pass
            self.lease.exited=p is None or p.poll() is not None
            if not self.lease.exited:self.lease.failure='SDK_PROCESS_EXIT_UNCONFIRMED'
            elif self.lease.forced:self.lease.failure='SDK_PROCESS_FORCED_EXIT'
            elif self.lease.started and (not self.lease.ack or p.returncode!=0):
                self.lease.failure='SDK_PROCESS_CLEANUP_FAILED'
            if self.lease.exited:
                if self.job is not None:self.job.close();self.job=None
                if p is not None and os.name=='nt':p._handle.Close()
                self.lease.reaped=True
                self.lease.phase('EXITED')
        except Exception:self.lease.failure=self.lease.failure or 'SDK_PROCESS_REAP_FAILED'
        finally:
            for stream in (self.sock,self.listener,getattr(p,'stdin',None)):
                if stream is not None:
                    try:stream.close()
                    except OSError:pass
            self.sock=None;self.listener=None;self.decoder.buffer.clear()
            self.lease.timings['cleanup']=(time.monotonic()-started)*1000
            self.lease.timings['total']=(time.monotonic()-self.started_at)*1000
            self.lease.budget.finish(self.lease);self.done.set()
    def accept_closed(self,frame):
        if (set(frame)!={'v','kind','id','local_io_closed','task_done','calls','remote_compute_stopped'}
                or type(frame['local_io_closed']) is not bool or frame['task_done'] is not True
                or type(frame['calls']) is not int or not 0<=frame['calls']<=1
                or frame['remote_compute_stopped']!='unknown'):
            raise GatewayError('SDK_PROCESS_PROTOCOL')
        self.closed_event=True;self.lease.ack=frame['local_io_closed']
        self.lease.task_done=True;self.lease.calls=frame['calls']


class ProcessOpenAICompatibleAdapter(OpenAICompatibleAdapter):
    """Unvalidated draft, explicitly unavailable until a separately approved task."""
    def __init__(self,*,offline=None,authorization=None,process_budget=None,startup_timeout_s=8,
                 cleanup_timeout_s=1,launcher=None):
        # Fail before base initialization, authorization, credentials or resources.
        # No environment/CLI switch bypasses this pause.
        raise GatewayError(PAUSED_CODE)
        super().__init__()
        if ((offline is not None and type(offline) is not OfflineSDKProcessScript)
                or (authorization is not None and type(authorization) is not SDKProcessAuthorization)
                or offline is not None and authorization is not None
                or process_budget is not None and type(process_budget) is not SDKProcessBudget
                or type(startup_timeout_s) not in (int,float) or not 0<startup_timeout_s<=10
                or type(cleanup_timeout_s) not in (int,float) or not 0<cleanup_timeout_s<=2):
            raise ValueError('INVALID_SDK_PROCESS_CONFIG')
        self._scripts=deque(json.loads(json.dumps(offline.requests))) if offline is not None else None
        self._authorization=authorization;self._process_budget=process_budget or PROCESS_BUDGET
        self._startup=startup_timeout_s;self._grace=cleanup_timeout_s
        self._launcher=launcher or subprocess.Popen
        self._lock=threading.Lock();self._active=set();self._stopping=False
    def _bridge(self,kwargs,runtime,*,stream,manual=False,tool_definitions=None):
        if manual:raise GatewayError('SDK_PROCESS_MANUAL_NOT_SUPPORTED')
        if runtime.max_retries!=0:raise GatewayError('SDK_PROCESS_ZERO_RETRY_REQUIRED')
        with self._lock:
            if self._stopping:raise GatewayError('SDK_PROCESS_ADAPTER_CLOSED')
            if self._scripts is None:
                if self._authorization is None:raise GatewayError('SDK_PROCESS_EXECUTION_NOT_AUTHORIZED')
                self._authorization.validate(runtime)
                script=None
            else:
                if not self._scripts:raise GatewayError('SDK_PROCESS_SCRIPT_EXHAUSTED')
                script=self._scripts.popleft()
        handle=current_handle() or RequestHandle()
        handle.check();handle.assert_resources_closed()
        if not handle._claimed:handle.start()
        deadline=handle.request_deadline(runtime.total_timeout_s)
        with handle._lock:
            count=getattr(handle,'_sdk_process_requests',0)+1
            if count>3:raise GatewayError('SDK_PROCESS_REQUEST_LIMIT')
            handle._sdk_process_requests=count
        lease=self._process_budget.reserve();handle._sdk_resource=lease;handle.io_closed=False
        session=ProcessSession(lease,handle,startup=self._startup,grace=self._grace,launcher=self._launcher)
        with self._lock:self._active.add(session)
        handle.bind(session.cancel.set)
        assembler=self._new_tool_stream_assembler(tool_definitions) if tool_definitions is not None else None
        normal=None;error=None;started=False
        def guard():
            session.guard()
            if script is None:self._authorization.validate(runtime)
        try:
            # Authorization precedes accessing credential bytes. Offline mode never reads them.
            key='offline-process-only' if script is not None else runtime.credential._for_adapter()
            payload={'v':VERSION,'kind':'init','id':session.sid,'stream':stream,'kwargs':kwargs,
                'sdk':{'base_url':runtime.base_url,'key':key,'connect':runtime.connect_timeout_s,
                       'read':runtime.read_timeout_s,'total':min(runtime.total_timeout_s,max(.001,deadline-time.monotonic()))},
                'offline':script}
            encode(payload)  # Reject oversize before creating any child.
            session.start(deadline,script['delay'] if script is not None else 0)
            guard();payload['sdk']['total']=max(.001,deadline-time.monotonic())
            session.send(payload,deadline,guard)
            while not session.closed_event:
                frame=session.receive(deadline,guard);kind=frame.get('kind')
                if kind=='started' and set(frame)=={'v','kind','id'} and not started:
                    started=True;self.request_attempts+=1;lease.phase('RUNNING')
                elif kind=='data' and set(frame)=={'v','kind','id','payload'} and started:
                    if stream:
                        chunk=ChatCompletionChunk.model_validate(frame['payload'])
                        if assembler is not None:
                            assembler.push(chunk)
                            if handle._event_channel is not None:handle.report_preview(''.join(assembler._content),key)
                        else:yield self._event(chunk)
                    else:
                        if normal is not None:raise GatewayError('SDK_PROCESS_PROTOCOL')
                        normal=self._response(ChatCompletion.model_validate(frame['payload']))
                elif kind=='error' and set(frame)=={'v','kind','id','code'}:
                    code=frame['code']
                    if not isinstance(code,str) or not code.isascii() or len(code)>64 or not code.replace('_','').isalnum():
                        raise GatewayError('SDK_PROCESS_PROTOCOL')
                    error=code
                elif kind=='closed':session.accept_closed(frame)
                else:raise GatewayError('SDK_PROCESS_PROTOCOL')
        except (OSError,ProtocolError,ValueError) as failure:
            error=str(failure) if isinstance(failure,ProtocolError) else 'SDK_PROCESS_IPC_FAILED'
        finally:
            session.cleanup();handle.unbind();handle.io_closed=lease.exited
            with self._lock:self._active.discard(session)
        if lease.failure:
            raise GatewayError(lease.failure)
        guard()
        if error:raise GatewayError(error)
        if not started or not lease.ack:raise GatewayError('SDK_PROCESS_PROTOCOL')
        if assembler is not None:yield assembler.finish()
        elif not stream:
            if normal is None:raise GatewayError('SDK_PROCESS_PROTOCOL')
            yield normal
    def close(self,timeout=4):
        with self._lock:self._stopping=True;sessions=tuple(self._active)
        for session in sessions:session.cancel.set()
        deadline=time.monotonic()+timeout
        for session in sessions:
            if not session.done.wait(max(0,deadline-time.monotonic())):
                session.lease.failure='SDK_PROCESS_EXIT_UNCONFIRMED';self._process_budget.finish(session.lease)
                raise GatewayError('SDK_PROCESS_SHUTDOWN_INCOMPLETE')
        if self._process_budget.snapshot()['quarantined']:raise GatewayError('SDK_PROCESS_RESOURCES_UNSAFE')
