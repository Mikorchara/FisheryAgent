"""Read-only credentials, resolved per request without changing os.environ."""

from dataclasses import dataclass, asdict
from io import StringIO
from pathlib import Path
from typing import Mapping
import os
import re
import threading
import hashlib
import hmac
import secrets
import uuid

from dotenv import dotenv_values
from dotenv.parser import parse_stream

from .providers import AuthSpec
from .credential_paths import PrivateCredentialLocation
from .secure_files import SecureFileError


class CredentialFileError(Exception):
    code = "CREDENTIAL_FILE_ERROR"

    def __init__(self):
        super().__init__(self.code)


@dataclass(frozen=True)
class CredentialStatus:
    availability: str
    source: str
    editable: bool

    def public_info(self) -> dict:
        return asdict(self)


class CredentialSnapshot:
    """Private immutable object, deliberately not a dataclass or JSON value."""

    __slots__ = ("__secret", "status", "revision")

    def __init__(self, secret: str | None, status: CredentialStatus, revision: str | None = None):
        object.__setattr__(self, "_CredentialSnapshot__secret", secret)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "revision", revision)

    def __setattr__(self, _name, _value):
        raise AttributeError("CredentialSnapshot is immutable")

    def __delattr__(self, _name):
        raise AttributeError("CredentialSnapshot is immutable")

    def __repr__(self):
        return "CredentialSnapshot(<redacted>)"

    __str__ = __repr__

    def __deepcopy__(self, _memo):
        raise TypeError("Private credentials cannot be serialized; use public_info")

    def __reduce_ex__(self, _protocol):
        raise TypeError("Private credentials cannot be serialized")

    def _for_adapter(self) -> str | None:
        return self.__secret

    @classmethod
    def none_required(cls):
        return cls(None, CredentialStatus("NONE_REQUIRED", "NONE_REQUIRED", False))


class CredentialStore:
    """Read per request; only opaque generations are cached, never secret values."""

    def __init__(self, project_env_path: Path | None = None,
                 process_env: Mapping[str, str] | None = None, *,
                 private_location: PrivateCredentialLocation | None = None):
        self.project_env_path = project_env_path.absolute() if project_env_path is not None else None
        if private_location is not None and private_location.env_path != self.project_env_path:
            raise ValueError("Private location and CredentialStore paths must match")
        self.private_location = private_location
        self._process_env = os.environ if process_env is None else process_env
        self._lock = threading.RLock()
        self._revision_key = secrets.token_bytes(32)
        self._revisions: dict[str, tuple[bytes, str]] = {}

    def invalidate(self, credential_ref: str) -> None:
        with self._lock:
            self._revisions.pop(credential_ref, None)

    def _snapshot(self, ref: str, value: str | None, status: CredentialStatus):
        # Keyed internal fingerprint is never returned; revision is random and opaque.
        digest = hmac.digest(self._revision_key,
                             (status.source + "\0" + (value or "")).encode("utf-8"), hashlib.sha256)
        previous = self._revisions.get(ref)
        revision = previous[1] if previous and hmac.compare_digest(previous[0], digest) else uuid.uuid4().hex
        self._revisions[ref] = (digest, revision)
        return CredentialSnapshot(value or None, status, revision)

    def _project_values(self) -> dict[str, str | None]:
        if self.project_env_path is None:
            return {}
        try:
            if self.private_location is not None and not self.private_location.check():
                return {}
            text = self.project_env_path.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            return {}
        except (OSError, UnicodeError, SecureFileError):
            raise CredentialFileError() from None
        try:
            if any(binding.error for binding in parse_stream(StringIO(text))):
                raise CredentialFileError()
            return dict(dotenv_values(stream=StringIO(text), interpolate=False))
        except CredentialFileError:
            raise
        except Exception:
            raise CredentialFileError() from None

    def resolve(self, credential_ref: str | None, auth_spec: AuthSpec = AuthSpec.REQUIRED_BEARER
                ) -> CredentialSnapshot:
        auth_spec = AuthSpec(auth_spec)
        if auth_spec == AuthSpec.NONE:
            return CredentialSnapshot.none_required()
        if credential_ref is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", credential_ref):
            raise ValueError("credential_ref must be an environment variable name")
        if not credential_ref:
            return CredentialSnapshot(None, CredentialStatus("MISSING", "MISSING", True))
        with self._lock:
            if credential_ref in self._process_env:
                value = self._process_env[credential_ref]
                return self._snapshot(credential_ref, value,
                    CredentialStatus("PRESENT" if value else "MISSING", "PROCESS_ENV", False))
            values = self._project_values()
            if credential_ref in values:
                value = values[credential_ref]
                return self._snapshot(credential_ref, value,
                    CredentialStatus("PRESENT" if value else "MISSING", "PROJECT_ENV", True))
            return self._snapshot(credential_ref, None, CredentialStatus("MISSING", "MISSING", True))

    def status(self, credential_ref: str | None, auth_spec: AuthSpec = AuthSpec.REQUIRED_BEARER
               ) -> CredentialStatus:
        return self.resolve(credential_ref, auth_spec).status
