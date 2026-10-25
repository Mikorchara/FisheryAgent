"""Unvalidated Windows Job draft; the paused Adapter never constructs this class."""
import ctypes
from ctypes import wintypes as w
import os


class SDKJob:
    def __init__(self):
        if os.name!='nt':raise OSError('SDK_PROCESS_WINDOWS_REQUIRED')
        k=ctypes.WinDLL('kernel32',use_last_error=True);self.k=k;self.handle=None
        class Basic(ctypes.Structure):
            _fields_=[('user',ctypes.c_longlong),('job_user',ctypes.c_longlong),('flags',w.DWORD),
                ('min_ws',ctypes.c_size_t),('max_ws',ctypes.c_size_t),('active',w.DWORD),
                ('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
        class IO(ctypes.Structure):
            _fields_=[(n,ctypes.c_ulonglong) for n in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
        class Extended(ctypes.Structure):
            _fields_=[('basic',Basic),('io',IO),('process_memory',ctypes.c_size_t),
                ('job_memory',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
        k.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR];k.CreateJobObjectW.restype=w.HANDLE
        k.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
        k.SetInformationJobObject.restype=w.BOOL
        k.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE];k.AssignProcessToJobObject.restype=w.BOOL
        k.CloseHandle.argtypes=[w.HANDLE];k.CloseHandle.restype=w.BOOL
        handle=k.CreateJobObjectW(None,None)
        if not handle:raise OSError('SDK_PROCESS_JOB_FAILED')
        self.handle=handle
        info=Extended();info.basic.flags=0x2000|0x8|0x100  # kill on close, one process, memory cap
        info.basic.active=1;info.process_memory=512*1024*1024
        if not k.SetInformationJobObject(handle,9,ctypes.byref(info),ctypes.sizeof(info)):
            self.close();raise OSError('SDK_PROCESS_JOB_FAILED')
    def assign(self,process):
        if not self.k.AssignProcessToJobObject(self.handle,int(process._handle)):
            raise OSError('SDK_PROCESS_JOB_ASSIGN_FAILED')
    def close(self):
        if self.handle is not None:
            handle,self.handle=self.handle,None
            if not self.k.CloseHandle(handle):raise OSError('SDK_PROCESS_JOB_CLOSE_FAILED')
