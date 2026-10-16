"""Application-private location composition; unchanged project identity, no file reads."""
from pathlib import Path
from typing import Mapping
import hashlib
import os
from apps.ai_backend.credential_paths import PrivateCredentialLocation, CredentialLocationError

def private_project_location(project_root: Path,
                             environment: Mapping[str, str] | None = None) -> PrivateCredentialLocation:
    """No filesystem access or directory creation, and no credential values inspected."""
    environment = os.environ if environment is None else environment
    if os.name == "nt":
        value = environment.get("LOCALAPPDATA", "")
        base = Path(value)
        if not value or not base.is_absolute():
            raise CredentialLocationError()
        base = Path(os.path.abspath(base))
    else:
        base = Path.home()
    identity = os.path.normcase(os.path.abspath(project_root))
    project_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    path = base / "Fishery_AI_Prototype" / ("project-" + project_id) / "credentials" / ".env"
    if path.is_relative_to(Path(identity)):
        # External-storage mode must never become a way to bypass workspace Git checks.
        raise CredentialLocationError()
    return PrivateCredentialLocation(base, path)


def private_manual_location(project_root: Path,
                            environment: Mapping[str, str] | None = None) -> PrivateCredentialLocation:
    """Same protected boundary, separate fixed file; never inspect or migrate .env."""
    location = private_project_location(project_root, environment)
    return PrivateCredentialLocation(location.base, location.env_path.with_name("manual.env"))
