"""Small OS boundary for private, same-volume credential staging (no dependencies)."""

from contextlib import contextmanager
from pathlib import Path
import ctypes
import os
import stat


class SecureFileError(Exception):
    def __init__(self):
        super().__init__("ENV_PERMISSION_ERROR")


class FileBusyError(SecureFileError):
    pass


def guard_path(path: Path, *, regular: bool = False) -> None:
    """Reject links/junctions, including ancestors, and multi-link credential files."""
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            if item == path:
                continue
            raise SecureFileError() from None
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise SecureFileError()
        if item == path and regular and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise SecureFileError()


if os.name == "nt":
    from ctypes import wintypes as wt
    import msvcrt

    _adv = ctypes.WinDLL("advapi32", use_last_error=True)
    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    def _api(dll, name, args, result=wt.BOOL):
        function = getattr(dll, name)
        function.argtypes, function.restype = args, result
        return function

    _open_token = _api(_adv, "OpenProcessToken", [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)])
    _token_info = _api(_adv, "GetTokenInformation", [wt.HANDLE, ctypes.c_int, wt.LPVOID,
                                                   wt.DWORD, ctypes.POINTER(wt.DWORD)])
    _sid_string = _api(_adv, "ConvertSidToStringSidW", [wt.LPVOID, ctypes.POINTER(wt.LPWSTR)])
    _get_security = _api(_adv, "GetNamedSecurityInfoW", [wt.LPWSTR, ctypes.c_int, wt.DWORD,
        ctypes.POINTER(wt.LPVOID), wt.LPVOID, ctypes.POINTER(wt.LPVOID), wt.LPVOID,
        ctypes.POINTER(wt.LPVOID)], wt.DWORD)
    _sd_string = _api(_adv, "ConvertSecurityDescriptorToStringSecurityDescriptorW",
        [wt.LPVOID, wt.DWORD, wt.DWORD, ctypes.POINTER(wt.LPWSTR), wt.LPVOID])
    _string_sd = _api(_adv, "ConvertStringSecurityDescriptorToSecurityDescriptorW",
        [wt.LPCWSTR, wt.DWORD, ctypes.POINTER(wt.LPVOID), wt.LPVOID])
    _get_ace = _api(_adv, "GetAce", [wt.LPVOID, wt.DWORD, ctypes.POINTER(wt.LPVOID)])
    _close = _api(_kernel, "CloseHandle", [wt.HANDLE])
    _free = _api(_kernel, "LocalFree", [wt.LPVOID], wt.LPVOID)
    _process = _api(_kernel, "GetCurrentProcess", [], wt.HANDLE)
    _volume_path = _api(_kernel, "GetVolumePathNameW", [wt.LPCWSTR, wt.LPWSTR, wt.DWORD])
    _drive_type = _api(_kernel, "GetDriveTypeW", [wt.LPCWSTR], wt.UINT)
    _volume_info = _api(_kernel, "GetVolumeInformationW", [wt.LPCWSTR, wt.LPWSTR, wt.DWORD,
        wt.LPVOID, wt.LPVOID, ctypes.POINTER(wt.DWORD), wt.LPWSTR, wt.DWORD])
    _move = _api(_kernel, "MoveFileExW", [wt.LPCWSTR, wt.LPCWSTR, wt.DWORD])

    class _SA(ctypes.Structure):
        _fields_ = [("length", wt.DWORD), ("descriptor", wt.LPVOID), ("inherit", wt.BOOL)]

    class _ACL(ctypes.Structure):
        _fields_ = [("revision", wt.BYTE), ("reserved", wt.BYTE), ("size", wt.WORD),
                    ("count", wt.WORD), ("reserved2", wt.WORD)]

    _create_file = _api(_kernel, "CreateFileW", [wt.LPCWSTR, wt.DWORD, wt.DWORD,
        ctypes.POINTER(_SA), wt.DWORD, wt.DWORD, wt.HANDLE], wt.HANDLE)
    _create_dir = _api(_kernel, "CreateDirectoryW", [wt.LPCWSTR, ctypes.POINTER(_SA)])

    def _sid(pointer):
        value = wt.LPWSTR()
        if not _sid_string(pointer, ctypes.byref(value)):
            raise SecureFileError()
        try:
            return value.value
        finally:
            _free(ctypes.cast(value, wt.LPVOID))

    def _current_sid():
        handle, needed = wt.HANDLE(), wt.DWORD()
        if not _open_token(_process(), 8, ctypes.byref(handle)):
            raise SecureFileError()
        try:
            _token_info(handle, 1, None, 0, ctypes.byref(needed))
            buffer = ctypes.create_string_buffer(needed.value)
            if not _token_info(handle, 1, buffer, len(buffer), ctypes.byref(needed)):
                raise SecureFileError()
            return _sid(ctypes.cast(buffer, ctypes.POINTER(wt.LPVOID))[0])
        finally:
            _close(handle)

    def private_policy():
        sid = _current_sid()
        return f"O:{sid}D:P(A;;FA;;;{sid})(A;;FA;;;SY)"

    def inspect_policy(path: Path, *, directory: bool = False, user_owned: bool = False):
        owner, dacl, descriptor = wt.LPVOID(), wt.LPVOID(), wt.LPVOID()
        if _get_security(str(path), 1, 5, ctypes.byref(owner), None,
                         ctypes.byref(dacl), None, ctypes.byref(descriptor)):
            raise SecureFileError()
        try:
            if not dacl.value or not owner.value:
                raise SecureFileError()
            trusted = {_current_sid(), "S-1-5-18", "S-1-5-32-544"}
            if _sid(owner) not in trusted:
                raise SecureFileError()
            # A credential file must be owned by this process user, not another account.
            if (not directory or user_owned) and _sid(owner) != _current_sid():
                raise SecureFileError()
            acl = ctypes.cast(dacl, ctypes.POINTER(_ACL)).contents
            for index in range(acl.count):
                ace = wt.LPVOID()
                if not _get_ace(dacl, index, ctypes.byref(ace)):
                    raise SecureFileError()
                header = ctypes.string_at(ace, 4)
                kind, flags = header[0], header[1]
                if flags & 8:  # INHERIT_ONLY does not grant access to this object.
                    continue
                if kind == 1:  # Explicit deny is conservative and need not be weakened.
                    continue
                if kind != 0:
                    raise SecureFileError()
                mask = ctypes.c_uint32.from_address(ace.value + 4).value
                if _sid(ace.value + 8) not in trusted:
                    unsafe_grant = (mask & 0x500D0156) if directory else mask
                    if unsafe_grant:
                        raise SecureFileError()
            value = wt.LPWSTR()
            if not _sd_string(descriptor, 1, 5, ctypes.byref(value), None):
                raise SecureFileError()
            try:
                return value.value
            finally:
                _free(ctypes.cast(value, wt.LPVOID))
        finally:
            if descriptor.value:
                _free(descriptor)

    def check_volume(root: Path):
        volume = ctypes.create_unicode_buffer(32768)
        flags = wt.DWORD()
        if (not _volume_path(str(root), volume, len(volume)) or _drive_type(volume.value) != 3
                or not _volume_info(volume.value, None, 0, None, None,
                                    ctypes.byref(flags), None, 0) or not flags.value & 8):
            raise SecureFileError()

    @contextmanager
    def _attributes(policy):
        descriptor = wt.LPVOID()
        if not _string_sd(policy, 1, ctypes.byref(descriptor), None):
            raise SecureFileError()
        try:
            yield _SA(ctypes.sizeof(_SA), descriptor, False)
        finally:
            _free(descriptor)

    def private_directory(path: Path):
        with _attributes(private_policy()) as attributes:
            if not _create_dir(str(path), ctypes.byref(attributes)):
                raise SecureFileError()
        inspect_policy(path, directory=True)

    def _file_handle(path: Path, policy, creation):
        with _attributes(policy) as attributes:
            handle = _create_file(str(path), 0xC0000000, 0, ctypes.byref(attributes),
                                  creation, 0x80 | 0x200000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise SecureFileError()
        return handle

    def write_private(path: Path, body: bytes, policy=None):
        handle = _file_handle(path, policy or private_policy(), 1)  # CREATE_NEW, no sharing.
        try:
            fd = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
        except Exception:
            _close(handle)
            raise SecureFileError() from None
        with os.fdopen(fd, "wb") as output:
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
        inspect_policy(path)

    @contextmanager
    def exclusive_lock(path: Path):
        guard_path(path, regular=True)
        if path.exists():
            inspect_policy(path)
        try:
            handle = _file_handle(path, private_policy(), 4)  # OPEN_ALWAYS, share mode 0.
        except SecureFileError:
            if ctypes.get_last_error() == 32:
                raise FileBusyError() from None
            raise
        try:
            yield
        finally:
            _close(handle)

    def atomic_replace(source: Path, destination: Path):
        # Never COPY_ALLOWED: both files must stay on this volume with their ACLs.
        if not _move(str(source), str(destination), 1 | 8):
            raise OSError("atomic credential replacement failed")

else:
    import fcntl

    def private_policy():
        return 0o600

    def inspect_policy(path: Path, *, directory: bool = False, user_owned: bool = False):
        info = path.stat()
        mask = 0o022 if directory else 0o077
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & mask:
            raise SecureFileError()
        return stat.S_IMODE(info.st_mode)

    def check_volume(root: Path):
        pass

    def private_directory(path: Path):
        path.mkdir(mode=0o700)

    def write_private(path: Path, body: bytes, policy=None):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, policy or 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
        inspect_policy(path)

    @contextmanager
    def exclusive_lock(path: Path):
        guard_path(path, regular=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            inspect_policy(path)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise FileBusyError() from None
            yield
        finally:
            os.close(fd)

    def atomic_replace(source: Path, destination: Path):
        os.replace(source, destination)
        fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
