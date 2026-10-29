"""Keep this supervisor and every descendant in one Windows lifetime boundary."""
import ctypes
from ctypes import wintypes as wt
import os

# Deliberately retained until PROCESS EXIT: closing this handle would also kill
# this supervisor. Children inherit membership, never this non-inheritable handle.
_job = None


def own_process_tree():
    global _job
    if os.name != 'nt':
        raise RuntimeError('LOCAL_WINDOWS_REQUIRED')
    if _job is not None:
        return
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)

    class Limits(ctypes.Structure):
        _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                    ('flags', wt.DWORD), ('minimum', ctypes.c_size_t),
                    ('maximum', ctypes.c_size_t), ('active', wt.DWORD),
                    ('affinity', ctypes.c_size_t), ('priority', wt.DWORD),
                    ('scheduling', wt.DWORD)]

    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in
                    ('reads', 'writes', 'other', 'read_bytes', 'write_bytes', 'other_bytes')]

    class Extended(ctypes.Structure):
        _fields_ = [('limits', Limits), ('io', IO), ('process_memory', ctypes.c_size_t),
                    ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t),
                    ('peak_job', ctypes.c_size_t)]

    kernel.CreateJobObjectW.argtypes = [wt.LPVOID, wt.LPCWSTR]
    kernel.CreateJobObjectW.restype = wt.HANDLE
    kernel.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, wt.LPVOID, wt.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
    kernel.GetCurrentProcess.restype = wt.HANDLE
    kernel.CloseHandle.argtypes = [wt.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        raise RuntimeError('LOCAL_JOB_UNAVAILABLE')
    limits = Extended()
    limits.limits.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        kernel.CloseHandle(handle)
        raise RuntimeError('LOCAL_JOB_UNAVAILABLE')
    # Joining BEFORE spawning removes the create/assign race, including the
    # .venv launcher spawning a second Python. No unrelated PID is ever enrolled.
    if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        kernel.CloseHandle(handle)
        raise RuntimeError('LOCAL_JOB_UNAVAILABLE')
    _job = handle
