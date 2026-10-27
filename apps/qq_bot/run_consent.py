"""Process-bound RunConsent, create-only owner and fail-closed quota journal.

No credentials, Provider, QQ, SQL or chat bodies. Local files are not an
anti-administrator trust root, nor an absolute cloud billing cap.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import hashlib
import json
import os
import threading
import time
import uuid

from apps.ai_service.channel_session_run import CONTRACT, LeaseAuthority
from apps.ai_service.channel_trial import cost_reservation, money
from apps.ai_service.runtime.release_contracts import _hash
from .contracts import BotError
from .trial_configuration import local_path

_PROCESS_NONCE=object()


@dataclass(frozen=True)
class RunLimits:
    max_turns: int = 5
    seconds: int = 1800
    total_budget_cny: str = '8.02'
    def __post_init__(self):
        if (type(self.max_turns) is not int or not 1<=self.max_turns<=5
                or type(self.seconds) is not int or not 1<=self.seconds<=1800):
            raise BotError('INVALID_RUN_LIMITS')
        try:budget=money(self.total_budget_cny)
        except Exception:raise BotError('INVALID_RUN_BUDGET') from None
        if budget<cost_reservation()*self.max_turns:raise BotError('RUN_BUDGET_INSUFFICIENT')


@dataclass(frozen=True,repr=False)
class RunConsent:
    consent_id: str
    scope_sha256: str
    bindings_sha256: str
    expires_at: datetime
    limits: RunLimits
    process_nonce: object = field(repr=False)
    pid: int


class RunOwner:
    """Persistent one-use claim held with a Windows no-write/no-delete share.

    Closing releases only the OS resource. It never removes the consumed claim.
    """
    def __init__(self,directory,consent_id,digest):
        if (type(consent_id) is not str or len(consent_id)!=32
                or any(c not in '0123456789abcdef' for c in consent_id)):
            raise BotError('INVALID_RUN_OWNER')
        self.path=local_path(directory)/('run-'+consent_id+'.used')
        local_path(self.path);self.pid=os.getpid();self._fd=None
        self._value=json.dumps({'contract':CONTRACT,'consent_sha256':digest},sort_keys=True).encode()
        try:
            if os.name=='nt':
                import ctypes
                from ctypes import wintypes
                import msvcrt
                kernel=ctypes.WinDLL('kernel32',use_last_error=True)
                create=kernel.CreateFileW
                create.argtypes=(wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,
                    wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE);create.restype=wintypes.HANDLE
                handle=create(str(self.path),0xC0000000,1,None,1,0x80,None)  # CREATE_NEW, share read only
                if handle==wintypes.HANDLE(-1).value:
                    if ctypes.get_last_error() in (32,80,183):raise BotError('RUN_APPROVAL_ALREADY_USED')
                    raise OSError('owner create failed')
                try:self._fd=msvcrt.open_osfhandle(handle,os.O_BINARY|os.O_RDWR)
                except Exception:kernel.CloseHandle(wintypes.HANDLE(handle));raise
            else:
                import fcntl
                self._fd=os.open(self.path,os.O_CREAT|os.O_EXCL|os.O_RDWR,0o600)
                fcntl.flock(self._fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            os.write(self._fd,self._value);os.fsync(self._fd)
            self.check()
        except FileExistsError:
            self.close();raise BotError('RUN_APPROVAL_ALREADY_USED') from None
        except BotError:self.close();raise
        except Exception:self.close();raise BotError('RUN_OWNER_UNAVAILABLE') from None

    def check(self):
        try:
            if self._fd is None or self.pid!=os.getpid():raise ValueError()
            stat=self.path.stat();current=os.fstat(self._fd)
            if ((stat.st_dev,stat.st_ino)!=(current.st_dev,current.st_ino)
                    or current.st_size!=len(self._value)):raise ValueError()
            os.lseek(self._fd,0,os.SEEK_SET)
            if os.read(self._fd,len(self._value)+1)!=self._value:raise ValueError()
        except Exception:raise BotError('RUN_OWNER_LOST') from None

    def close(self):
        if self._fd is not None:
            fd,self._fd=self._fd,None;os.close(fd)


class RunLedger:
    """Only this live object can mint its consent/leases. No load/resume API.

    _lock protects quota in RAM. The nonblocking _io lock serializes durable
    writes and ownership checks outside the quota lock. Any uncertain write
    permanently poisons this Run; reserved capacity is never refunded.
    """
    def __init__(self,directory,*,scope_sha256,bindings_sha256,limits=RunLimits(),clock=None,monotonic=time.monotonic):
        if type(limits) is not RunLimits:raise BotError('INVALID_RUN_LIMITS')
        self.directory=local_path(directory)
        if not self.directory.is_dir():raise BotError('RUN_STATE_DIRECTORY_REQUIRED')
        self.scope_sha256,self.bindings_sha256,self.limits=scope_sha256,bindings_sha256,limits
        self.clock=clock or (lambda:datetime.now(timezone.utc));self.now=monotonic
        self._pid=os.getpid();self._nonce=_PROCESS_NONCE;self._run_nonce=object()
        self._id=uuid.uuid4().hex;self._consent=None;self._owner=None;self._journal=None
        self._lock=threading.RLock();self._io=threading.RLock()
        self._halted=None;self._closed=False;self._messages={};self._turns=0
        self._reserved=Decimal('0');self._bytes=b'';self._deadline=None
        self.authority=LeaseAuthority(self.check_lease)
        self._plan=dict(contract=CONTRACT,status='pending_operator_approval',consent_id=self._id,
            scope_sha256=scope_sha256,bindings_sha256=bindings_sha256,limits=asdict(limits),
            requests_per_turn=2,output_tokens_per_request=512,seconds_per_turn=90,retries=0,
            reservation_per_turn_cny=str(cost_reservation()),resume=False,environment='OFFLINE_FAKE_ONLY',
            process_nonce_sha256=_hash([self._id,uuid.uuid4().hex,self._pid]))

    def plan(self):
        from copy import deepcopy
        return deepcopy(self._plan)

    def approve(self,plan,*,confirmed=False):
        """Trusted local operator action only; files/QQ cannot restore this object."""
        if confirmed is not True or plan!=self._plan or self._consent is not None or self._closed or self._halted:
            raise BotError('INVALID_RUN_APPROVAL')
        with self._io:
            try:
                self._owner=RunOwner(self.directory,self._id,_hash(self._plan))
                self._journal_path=local_path(self.directory/('run-'+self._id+'.jsonl'))
                self._journal=self._journal_path.open('x+b')
                self._append({'type':'approved','plan_sha256':_hash(self._plan)})
                self._consent=RunConsent(self._id,self.scope_sha256,self.bindings_sha256,
                    self.clock()+timedelta(seconds=self.limits.seconds),self.limits,self._run_nonce,self._pid)
                self._deadline=self.now()+self.limits.seconds
            except Exception:
                self.halt('RUN_LEDGER_FAILED');self.close();raise BotError('RUN_LEDGER_FAILED') from None
        return self._consent

    def halt(self,code):
        with self._lock:
            if self._halted is None:self._halted=code

    def _check_fast(self):
        if self._pid!=os.getpid() or self._nonce is not _PROCESS_NONCE:
            self.halt('RUN_PROCESS_MISMATCH')
        if self._halted:raise BotError(self._halted)
        if self._closed:raise BotError('RUN_CLOSED')
        if self._consent is None:raise BotError('RUN_NOT_APPROVED')
        if (self._consent.process_nonce is not self._run_nonce or self._consent.pid!=self._pid):
            self.halt('RUN_PROCESS_MISMATCH');raise BotError(self._halted)
        if self.clock()>=self._consent.expires_at or self.now()>=self._deadline:
            self.halt('RUN_EXPIRED');raise BotError(self._halted)

    def _journal_intact(self):
        if self._journal is None:return False
        stat=self._journal_path.stat();current=os.fstat(self._journal.fileno())
        self._journal.seek(0);data=self._journal.read(len(self._bytes)+1)
        return (stat.st_dev,stat.st_ino)==(current.st_dev,current.st_ino) and data==self._bytes

    def _append(self,record):
        value={**record,'previous_sha256':hashlib.sha256(self._bytes).hexdigest()}
        data=json.dumps(value,sort_keys=True,separators=(',',':')).encode()+b'\n'
        self._journal.seek(0,os.SEEK_END)
        if self._journal.write(data)!=len(data):raise OSError('short journal write')
        self._journal.flush();os.fsync(self._journal.fileno());self._bytes+=data

    def check(self):
        with self._lock:self._check_fast()
        with self._io:
            try:
                self._owner.check()
                if not self._journal_intact():raise BotError('RUN_LEDGER_FAILED')
            except Exception as error:
                code='RUN_OWNER_LOST' if getattr(error,'code',None)=='RUN_OWNER_LOST' else 'RUN_LEDGER_FAILED'
                self.halt(code);raise BotError(code) from None

    def can_admit(self):
        self.check()
        with self._lock:
            if self._turns>=self.limits.max_turns:raise BotError('RUN_TURN_LIMIT')
            if self._reserved+cost_reservation()>money(self.limits.total_budget_cny):raise BotError('RUN_BUDGET_EXHAUSTED')

    def remaining(self):
        self.check();return max(0,min(self._deadline-self.now(),(self._consent.expires_at-self.clock()).total_seconds()))

    def reserve(self,*,message_key,fingerprint,member_id,instance_id,device_id,app_id,group_id):
        if not self._io.acquire(blocking=False):raise BotError('RUN_ADMISSION_BUSY')
        try:
            self.check()
            with self._lock:
                self._check_fast()
                if message_key in self._messages:
                    raise BotError('RUN_MESSAGE_ALREADY_USED' if self._messages[message_key]==fingerprint else 'RUN_MESSAGE_CONFLICT')
                if self._turns>=self.limits.max_turns:raise BotError('RUN_TURN_LIMIT')
                if self._reserved+cost_reservation()>money(self.limits.total_budget_cny):raise BotError('RUN_BUDGET_EXHAUSTED')
                self._turns+=1;self._reserved+=cost_reservation();self._messages[message_key]=fingerprint
                sequence=self._turns
                record=dict(type='reserved',sequence=sequence,message_key_sha256=_hash(message_key),
                    fingerprint_sha256=_hash(fingerprint),reserved_cost_cny=str(self._reserved),reserved_requests=sequence*2)
            # No quota lock during any file I/O, flush/fsync or service creation.
            try:
                self._append(record);self._owner.check()
                if not self._journal_intact():raise OSError('journal changed')
            except Exception:
                self.halt('RUN_LEDGER_FAILED');raise BotError('RUN_LEDGER_FAILED') from None
            with self._lock:
                self._check_fast()
                return self.authority._issue(approval_id=self._id+'-'+str(sequence),sequence=sequence,
                    scope_sha256=self.scope_sha256,bindings_sha256=self.bindings_sha256,
                    expires_at=min(self._consent.expires_at,self.clock()+timedelta(seconds=90)),
                    instance_id=instance_id,device_id=device_id,app_id=app_id,group_id=group_id,
                    member_id=member_id,message_key=message_key)
        finally:self._io.release()

    def check_lease(self,lease):
        self.check()
        if (lease.authority is not self.authority or self.authority._issued.get(lease.ticket) is not lease
                or lease.scope_sha256!=self.scope_sha256 or lease.bindings_sha256!=self.bindings_sha256):
            raise BotError('INVALID_RUN_TURN_LEASE')
        if self.clock()>=lease.expires_at:raise BotError('RUN_TURN_EXPIRED')

    def report(self):
        with self._lock:
            return dict(contract=CONTRACT,consent_ref=_hash(self._id)[:12],
                state='HALTED' if self._halted else 'CLOSED' if self._closed else 'APPROVED' if self._consent else 'UNAPPROVED',
                stop_code=self._halted,consumed_turns=self._turns,reserved_model_requests=self._turns*2,
                reserved_cost_cny=str(self._reserved),total_budget_cny=self.limits.total_budget_cny,
                max_turns=self.limits.max_turns,billing_confirmed=False,resume=False)

    def close(self):
        with self._lock:self._closed=True
        with self._io:
            if self._journal is not None:self._journal.close();self._journal=None
            if self._owner is not None:self._owner.close()

