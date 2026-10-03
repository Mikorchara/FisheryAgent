"""Experimental targets, separate from Profiles/Evidence and without secret values."""

from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlsplit
import json
import os
import re
import threading
import uuid

from .manual import ManualRequest
from .model_gateway import GatewayError, RuntimeSnapshot
from .model_options import ModelCapabilities, GenerationOptions, ReasoningOptions, ProfileStatus
from .providers import AuthSpec


TRANSPORT = "openai_chat"
FIELDS = {"name", "service_name", "transport", "base_url", "model", "credential_ref",
          "timeout", "raw_request_body", "notes"}
ID_PATTERN = r"experiment-[0-9a-f]{32}"


def prepare_experiment_request(body, *, model):
    """V2 only: inject the target model into a copy, never into the saved/editor body."""
    prepared = dict(body) if isinstance(body, dict) else body
    if isinstance(prepared, dict) and "model" not in prepared:
        prepared["model"] = model
    return ManualRequest.from_dict(prepared, model=model)


def validate_experiment(data):
    if not isinstance(data, dict) or set(data) - FIELDS:
        raise GatewayError("INVALID_EXPERIMENT")
    result = dict(data)
    for key in ("name", "service_name", "base_url", "model"):
        value = result.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 512 or any(ord(c) < 32 for c in value):
            raise GatewayError("INVALID_EXPERIMENT", option=key)
        result[key] = value.strip()
    if result.get("transport") != TRANSPORT:
        raise GatewayError("MANUAL_TRANSPORT_UNSUPPORTED")
    try:
        url = urlsplit(result["base_url"])
        if (url.scheme not in ("http", "https") or not url.hostname or url.username is not None
                or url.password is not None or url.query or url.fragment or url.port == 0
                or any(c.isspace() for c in result["base_url"]) or "\\" in result["base_url"]):
            raise ValueError()
    except ValueError:
        raise GatewayError("INVALID_BASE_URL") from None
    ref = result.get("credential_ref", "")
    if not isinstance(ref, str) or (ref and not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,127}", ref)):
        raise GatewayError("INVALID_CREDENTIAL_REF")
    result["credential_ref"] = ref
    timeout = result.get("timeout")
    if type(timeout) not in (int, float) or not 1 <= timeout <= 600:
        raise GatewayError("INVALID_TIMEOUT")
    result["timeout"] = float(timeout)
    notes = result.get("notes", "")
    if not isinstance(notes, str) or len(notes) > 2000:
        raise GatewayError("INVALID_EXPERIMENT", option="notes")
    result["notes"] = notes
    body = result.get("raw_request_body")
    manual = prepare_experiment_request(body, model=result["model"])
    result["raw_request_body"] = json.loads(manual.body_json)
    if "model" not in body:
        # Validate the effective request, but persist the user's original model omission.
        result["raw_request_body"].pop("model")
    return result


class ManualExperimentStore:
    """Fixed startup-selected outputs directory; IDs never become arbitrary paths."""
    def __init__(self, directory: Path):
        self.directory = directory
        self._lock = threading.RLock()

    def _path(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(ID_PATTERN, identifier):
            raise GatewayError("EXPERIMENT_NOT_FOUND")
        return self.directory / (identifier + ".json")

    def get(self, identifier):
        try:
            path = self._path(identifier)
            if path.is_symlink() or path.stat().st_size > 20 * 1024:
                raise GatewayError("EXPERIMENT_STORAGE_ERROR")
            data = json.loads(path.read_text(encoding="utf-8"))
            if set(data) != FIELDS | {"id", "created_at", "updated_at"} or data["id"] != identifier:
                raise GatewayError("EXPERIMENT_STORAGE_ERROR")
            validate_experiment({key: data[key] for key in FIELDS})
            return data
        except FileNotFoundError:
            raise GatewayError("EXPERIMENT_NOT_FOUND") from None
        except (OSError, ValueError, TypeError, RecursionError):
            raise GatewayError("EXPERIMENT_STORAGE_ERROR") from None

    def list(self):
        with self._lock:
            if not self.directory.exists():
                return []
            return [self.get(path.stem) for path in sorted(self.directory.glob("experiment-*.json"))]

    def save(self, data, identifier=None):
        values = validate_experiment(data)
        with self._lock:
            previous = self.get(identifier) if identifier is not None else None
            identifier = identifier or "experiment-" + uuid.uuid4().hex
            now = datetime.now(timezone.utc).isoformat()
            result = {**values, "id": identifier, "created_at": previous["created_at"] if previous else now,
                      "updated_at": now}
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                path = self._path(identifier)
                temporary = self.directory / (".experiment-" + uuid.uuid4().hex + ".tmp")
                try:
                    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                        json.dump(result, stream, ensure_ascii=False, allow_nan=False, indent=2)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
            except OSError:
                raise GatewayError("EXPERIMENT_STORAGE_ERROR") from None
            return result

    def delete(self, identifier):
        with self._lock:
            self.get(identifier)
            try:
                self._path(identifier).unlink()
            except OSError:
                raise GatewayError("EXPERIMENT_STORAGE_ERROR") from None


def experiment_runtime(data, credentials):
    """Direct immutable target; no ProfileRegistry/defaults/resolver/protocol mapping."""
    ref = data["credential_ref"] or None
    auth = AuthSpec.REQUIRED_BEARER if ref else AuthSpec.NONE
    credential = credentials.resolve(ref, auth)
    if ref and credential.status.availability != "PRESENT":
        raise GatewayError("SECRET_MISSING")
    # service_name is a label, never used to select a provider codec.
    return RuntimeSnapshot(profile_id="manual-v2", display_name=data["name"], provider_kind="manual",
        base_url=data["base_url"], model=data["model"], secret_env=ref,
        connect_timeout_s=min(5, data["timeout"]), read_timeout_s=data["timeout"],
        total_timeout_s=data["timeout"], max_retries=0, capabilities=ModelCapabilities(),
        adapter_id="generic_openai_chat", provider_id="custom", service_id="custom",
        profile_status=ProfileStatus.CUSTOM, default_generation=GenerationOptions(),
        default_reasoning=ReasoningOptions(), credential=credential, auth_spec=auth,
        access_mode="manual_expert")
