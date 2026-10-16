"""Startup-only, per-user project credential locations; no legacy dotenv fallback."""

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
import hashlib
import os
import re

from . import secure_files


class CredentialLocationError(Exception):
    def __init__(self):
        super().__init__("CREDENTIAL_STORAGE_UNAVAILABLE")


@dataclass(frozen=True)
class PrivateCredentialLocation:
    base: Path
    env_path: Path

    def check(self, *, create: bool = False) -> bool:
        """Validate existing objects; create protected directories only for explicit writes."""
        secure_files.guard_path(self.base)
        if not self.base.is_dir():
            raise secure_files.SecureFileError()
        secure_files.check_volume(self.base)
        secure_files.inspect_policy(self.base, directory=True, user_owned=True)
        try:
            parts = self.env_path.relative_to(self.base).parts
        except ValueError:
            raise secure_files.SecureFileError() from None
        if (len(parts) != 4 or parts[0] != "Fishery_AI_Prototype"
                or not re.fullmatch(r"project-[0-9a-f]{20}", parts[1])
                or parts[2] != "credentials" or parts[3] not in (".env", "manual.env")):
            raise secure_files.SecureFileError()
        parent = self.base
        for part in parts[:-1]:
            parent = parent / part
            secure_files.guard_path(parent)
            if not parent.exists():
                if not create:
                    return False
                secure_files.private_directory(parent)
            if not parent.is_dir():
                raise secure_files.SecureFileError()
            secure_files.inspect_policy(parent, directory=True, user_owned=True)
        secure_files.guard_path(self.env_path, regular=True)
        if self.env_path.exists():
            secure_files.inspect_policy(self.env_path)
        return True
