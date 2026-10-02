"""Fixed-path .env credential CRUD, preserving unrelated bytes and failing closed."""

from contextlib import contextmanager
from io import StringIO
from pathlib import Path
import hashlib
import os
import re
import subprocess
import uuid

from dotenv import dotenv_values
from dotenv.parser import parse_stream

from .credentials import CredentialStore
from .providers import AuthSpec
from . import secure_files


class EnvWriteError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _parse(text: str):
    bindings = list(parse_stream(StringIO(text)))
    if any(item.error for item in bindings):
        raise EnvWriteError("ENV_FORMAT_UNSUPPORTED")
    return bindings, dict(dotenv_values(stream=StringIO(text), interpolate=False))


def _value_suffix(value: str) -> str:
    if value.startswith("#"):
        return " " + value
    if value.startswith(("'", '"')):
        quote = value[0]
        escaped = False
        for index in range(1, len(value)):
            character = value[index]
            if character == quote and not escaped:
                return value[index + 1:]
            escaped = character == "\\" and not escaped
        raise EnvWriteError("ENV_FORMAT_UNSUPPORTED")
    comment = re.search(r"\s+#", value)
    if comment:
        return value[comment.start():]
    return value[len(value.rstrip()):]


def edit_env(body: bytes, name: str, action: str, secret: str | None) -> bytes:
    """Edit one single-line binding; never serialize the whole dotenv mapping."""
    bom = body.startswith(b"\xef\xbb\xbf")
    try:
        text = body.decode("utf-8-sig")
    except UnicodeError:
        raise EnvWriteError("ENV_FORMAT_UNSUPPORTED") from None
    if re.search(r"\r(?!\n)", text):
        raise EnvWriteError("ENV_FORMAT_UNSUPPORTED")
    bindings, before = _parse(text)
    matches = [item for item in bindings if item.key == name]
    if len(matches) > 1:
        raise EnvWriteError("ENV_DUPLICATE_KEY")
    if action == "create" and matches:
        raise EnvWriteError("CREDENTIAL_EXISTS")
    if action in ("replace", "remove") and not matches:
        raise EnvWriteError("CREDENTIAL_NOT_FOUND")
    if action not in ("create", "replace", "remove"):
        raise EnvWriteError("INVALID_REQUEST")
    encoded_value = ""
    if action != "remove":
        if (not isinstance(secret, str) or not secret or len(secret.encode("utf-8")) > 4096
                or any(ord(character) < 32 or ord(character) == 127 for character in secret)):
            raise EnvWriteError("INVALID_CREDENTIAL_VALUE")
        encoded_value = "'" + secret.replace("\\", "\\\\").replace("'", "\\'") + "'"
    newline = "\r\n" if re.search(r"\r?\n", text) and re.search(r"\r?\n", text)[0] == "\r\n" else "\n"
    if not matches:
        result = text + (newline if text and not text.endswith("\n") else "") + name + "=" + encoded_value + newline
    else:
        target = matches[0]
        # Leading blank lines belong to this parser binding; preserve them too.
        pattern = (r"(?P<leading>(?:\r?\n)*)(?P<prefix>[ \t]*(?:export[ \t]+)?(?:"
                   + re.escape(name) + "|'" + re.escape(name)
                   + r"')[ \t]*=[ \t]*)(?P<value>[^\r\n]*)(?P<end>\r?\n)?")
        match = re.fullmatch(pattern, target.original.string)
        if not match:
            raise EnvWriteError("ENV_FORMAT_UNSUPPORTED")
        suffix = _value_suffix(match["value"])
        if action == "remove":
            comment = suffix.lstrip(" \t")
            replacement = match["leading"] + (comment + (match["end"] or "") if comment.startswith("#") else "")
        else:
            replacement = match["leading"] + match["prefix"] + encoded_value + suffix + (match["end"] or "")
        result = "".join(replacement if item is target else item.original.string for item in bindings)
    _, after = _parse(result)
    if ({key: value for key, value in before.items() if key != name}
            != {key: value for key, value in after.items() if key != name}
            or (name in after if action == "remove" else after.get(name) != secret)):
        raise EnvWriteError("ENV_FORMAT_UNSUPPORTED")
    return (b"\xef\xbb\xbf" if bom else b"") + result.encode("utf-8")


class ProjectEnvWriter:
    """Only the startup-selected storage root/.env is writable; no Web path API."""

    def __init__(self, project_root: Path, credential_store: CredentialStore,
                 *, require_git_ignored: bool = True):
        self.root = project_root.absolute()
        self.path = self.root / ".env"
        if credential_store.project_env_path != self.path:
            raise ValueError("Writer and CredentialStore paths must match")
        self.credentials = credential_store
        if (credential_store.private_location is not None
                and (credential_store.private_location.env_path.parent != self.root
                     or require_git_ignored)):
            raise ValueError("Private storage must use its own root without project Git checks")
        self.require_git_ignored = require_git_ignored
        self._last_state = None
        self._revision = uuid.uuid4().hex

    def __repr__(self):
        return "ProjectEnvWriter(<fixed project path>)"

    def _policy(self):
        if self.credentials.private_location is not None:
            if not self.credentials.private_location.check():
                return secure_files.private_policy()
        secure_files.guard_path(self.root)
        secure_files.guard_path(self.path, regular=True)
        secure_files.check_volume(self.root)
        secure_files.inspect_policy(self.root, directory=True)
        if self.require_git_ignored:
            self._check_ignored((".env", ".env.writer.lock"))
        if self.path.exists():
            info = self.path.stat()
            # Read-only, reparse, EFS, compressed and sparse files need a separate policy.
            if getattr(info, "st_file_attributes", 0) & (1 | 0x400 | 0x4000 | 0x800 | 0x200):
                raise EnvWriteError("ENV_PERMISSION_ERROR")
            return secure_files.inspect_policy(self.path)
        return secure_files.private_policy()

    def _check_ignored(self, filenames):
        for filename in filenames:
            ignored = subprocess.run(["git", "-C", str(self.root), "check-ignore", "-q",
                "--no-index", "--", filename], capture_output=True, check=False, timeout=5)
            tracked = subprocess.run(["git", "-C", str(self.root), "ls-files", "--error-unmatch",
                "--", filename], capture_output=True, check=False, timeout=5)
            if ignored.returncode != 0 or tracked.returncode != 1:
                raise EnvWriteError("ENV_NOT_IGNORED")

    def _read(self):
        try:
            info = self.path.stat()
            if info.st_size > 512 * 1024:
                raise EnvWriteError("ENV_FORMAT_UNSUPPORTED")
            body = self.path.read_bytes()
            return body, (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        except FileNotFoundError:
            return None, None

    def _state(self):
        policy = self._policy()
        body, metadata = self._read()
        state = (metadata, hashlib.sha256(body).digest() if body is not None else None, policy)
        if state != self._last_state:
            self._last_state, self._revision = state, uuid.uuid4().hex
        return body, state, policy, self._revision

    @contextmanager
    def _safe_errors(self):
        try:
            yield
        except EnvWriteError:
            raise
        except secure_files.SecureFileError:
            raise EnvWriteError("ENV_PERMISSION_ERROR") from None
        except (OSError, UnicodeError):
            raise EnvWriteError("ENV_WRITE_FAILED") from None
        except Exception:
            raise EnvWriteError("ENV_WRITE_FAILED") from None

    def _editable(self, name, auth):
        if AuthSpec(auth) == AuthSpec.NONE:
            raise EnvWriteError("AUTH_NONE")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,127}", name):
            raise EnvWriteError("INVALID_SECRET_ENV")
        # Even an empty external value blocks fallback and writes.
        if name in self.credentials._process_env:
            raise EnvWriteError("PROCESS_ENV_READ_ONLY")

    def inspect(self, name: str, auth: AuthSpec):
        with self.credentials._lock, self._safe_errors():
            self._editable(name, auth)
            body, _, _, revision = self._state()
            _, values = _parse((body or b"").decode("utf-8-sig"))
            return {"revision": revision, "exists": name in values}

    def mutate(self, name: str, auth: AuthSpec, *, action: str,
               expected_revision: str, secret: str | None = None):
        with self.credentials._lock, self._safe_errors():
            self._editable(name, auth)
            if self.credentials.private_location is not None:
                self.credentials.private_location.check(create=True)
            self._policy()
            try:
                with secure_files.exclusive_lock(self.root / ".env.writer.lock"):
                    body, state, policy, revision = self._state()
                    if not isinstance(expected_revision, str) or expected_revision != revision:
                        raise EnvWriteError("ENV_REVISION_CONFLICT")
                    changed = edit_env(body or b"", name, action, secret)
                    self._commit(body, changed, state, policy)
                    self.credentials.invalidate(name)
                    self._last_state = None
                    return self.inspect(name, auth)
            except secure_files.FileBusyError:
                # A sharing conflict or unsafe lock is intentionally never bypassed.
                raise EnvWriteError("ENV_LOCK_UNAVAILABLE") from None

    def _commit(self, original: bytes | None, changed: bytes, state, policy):
        staging = self.root / (".env.stage-" + uuid.uuid4().hex)
        if self.require_git_ignored:
            self._check_ignored((staging.name + "/new", staging.name + "/original"))
        secure_files.private_directory(staging)
        prepared, recovery = staging / "new", staging / "original"
        keep_recovery = False
        try:
            secure_files.write_private(prepared, changed, policy)
            if original is not None:
                secure_files.write_private(recovery, original, policy)
            # Copy ACL first, then verify before allowing the replacement.
            if secure_files.inspect_policy(prepared) != policy:
                raise EnvWriteError("ENV_PERMISSION_ERROR")
            if self._state()[1] != state:
                raise EnvWriteError("ENV_REVISION_CONFLICT")
            try:
                secure_files.atomic_replace(prepared, self.path)
                if self.path.read_bytes() != changed or secure_files.inspect_policy(self.path) != policy:
                    raise EnvWriteError("ENV_WRITE_FAILED")
            except Exception:
                # Some OS operations can fail after the rename; only roll back our own bytes.
                try:
                    current = self._read()[0]
                except Exception:
                    keep_recovery = True
                    raise EnvWriteError("ENV_RECOVERY_REQUIRED") from None
                if current == changed:
                    try:
                        if original is None:
                            self.path.unlink()
                        else:
                            secure_files.atomic_replace(recovery, self.path)
                            if self.path.read_bytes() != original or secure_files.inspect_policy(self.path) != policy:
                                raise OSError("rollback verification failed")
                    except Exception:
                        keep_recovery = True
                        raise EnvWriteError("ENV_RECOVERY_REQUIRED") from None
                elif current != original:
                    keep_recovery = True
                    raise EnvWriteError("ENV_RECOVERY_REQUIRED") from None
                raise EnvWriteError("ENV_WRITE_FAILED") from None
        finally:
            if not keep_recovery:
                for owned in (prepared, recovery):
                    try:
                        owned.unlink(missing_ok=True)
                    except OSError:
                        pass  # Any residue remains inside a private, Git-ignored directory.
                try:
                    staging.rmdir()
                except OSError:
                    pass
