"""Named jobs owned by this launcher, with child enrollment before any service I/O."""
import ctypes
from ctypes import wintypes as wt
import re
import uuid

KERNEL=ctypes.WinDLL('kernel32',use_last_error=True)
KERNEL.CreateJobObjectW.argtypes=[wt.LPVOID,wt.LPCWSTR];KERNEL.CreateJobObjectW.restype=wt.HANDLE
KERNEL.OpenJobObjectW.argtypes=[wt.DWORD,wt.BOOL,wt.LPCWSTR];KERNEL.OpenJobObjectW.restype=wt.HANDLE
KERNEL.AssignProcessToJobObject.argtypes=[wt.HANDLE,wt.HANDLE]
KERNEL.GetCurrentProcess.restype=wt.HANDLE
KERNEL.SetInformationJobObject.argtypes=[wt.HANDLE,ctypes.c_int,wt.LPVOID,wt.DWORD]
KERNEL.TerminateJobObject.argtypes=[wt.HANDLE,wt.UINT]
KERNEL.CloseHandle.argtypes=[wt.HANDLE]

class Limits(ctypes.Structure):
    _fields_=[('process_time',ctypes.c_int64),('job_time',ctypes.c_int64),('flags',wt.DWORD),
        ('minimum',ctypes.c_size_t),('maximum',ctypes.c_size_t),('active',wt.DWORD),
        ('affinity',ctypes.c_size_t),('priority',wt.DWORD),('scheduling',wt.DWORD)]
class IO(ctypes.Structure):
    _fields_=[(name,ctypes.c_uint64) for name in ('reads','writes','other','read_bytes','write_bytes','other_bytes')]
class Extended(ctypes.Structure):
    _fields_=[('limits',Limits),('io',IO),('process_memory',ctypes.c_size_t),('job_memory',ctypes.c_size_t),
             ('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]

class ConsoleJob:
    def __init__(self):
        self.name='Local\\FisheryPrototypeStack-'+uuid.uuid4().hex
        ctypes.set_last_error(0)
        self.handle=KERNEL.CreateJobObjectW(None,self.name)
        if not self.handle or ctypes.get_last_error()==183: raise RuntimeError('STACK_JOB_UNAVAILABLE')
        limits=Extended();limits.limits.flags=0x2000
        if not KERNEL.SetInformationJobObject(self.handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):
            self.close();raise RuntimeError('STACK_JOB_UNAVAILABLE')
    def terminate(self):
        if self.handle and not KERNEL.TerminateJobObject(self.handle,1):raise RuntimeError('STACK_JOB_STOP_FAILED')
    def close(self):
        if self.handle:KERNEL.CloseHandle(self.handle);self.handle=None

_membership=None
def join(name):
    global _membership
    if not re.fullmatch(r'Local\\FisheryPrototypeStack-[a-f0-9]{32}',name):raise RuntimeError('INVALID_STACK_JOB')
    handle=KERNEL.OpenJobObjectW(0x001F003F,False,name)
    if not handle or not KERNEL.AssignProcessToJobObject(handle,KERNEL.GetCurrentProcess()):
        if handle:KERNEL.CloseHandle(handle)
        raise RuntimeError('STACK_JOB_JOIN_FAILED')
    _membership=handle
