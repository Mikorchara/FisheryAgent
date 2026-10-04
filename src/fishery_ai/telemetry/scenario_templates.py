"""Reusable simulation intent and a local, source-aware template catalog."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
import json
import math
import os
import re
import uuid

from ..contracts import WaterQualityReading
from ..secure_files import guard_path, SecureFileError
from .adapter import SimulationAdapter
from .models import READING_FIELDS
from .simulator import TelemetrySimulator
from .snapshot import CurrentSnapshotStore


class ScenarioError(ValueError):
    def __init__(self, code: str, field: str = "template"):
        super().__init__(code)
        self.code = code
        self.field = field


def validate_id(identifier: str) -> str:
    if not isinstance(identifier, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", identifier):
        raise ScenarioError("SCENARIO_INVALID_ID", "id")
    if identifier.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                              *(f"LPT{i}" for i in range(1, 10))}:
        raise ScenarioError("SCENARIO_INVALID_ID", "id")
    return identifier


def finite_number(value) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True)
class ReadingIntent:
    state: str
    value: float | None = None


@dataclass(frozen=True)
class ScenarioTemplate:
    id: str
    display_name: str
    readings: tuple[ReadingIntent, ReadingIntent, ReadingIntent]
    observed_age_s: float = 0
    device_id: str = "sim-device-001"
    description: str = ""
    schema_version: str = "scenario-template-v1"

    def __post_init__(self):
        validate_id(self.id)
        if self.schema_version != "scenario-template-v1":
            raise ScenarioError("SCENARIO_SCHEMA_UNSUPPORTED", "schema_version")
        for field, value, maximum, required in (
            ("display_name", self.display_name, 80, True),
            ("device_id", self.device_id, 128, True),
            ("description", self.description, 500, False),
        ):
            if (not isinstance(value, str) or len(value) > maximum
                    or (required and not value.strip()) or any(ord(c) < 32 for c in value)):
                raise ScenarioError("SCENARIO_INVALID_FIELD", field)
        if not finite_number(self.observed_age_s) or self.observed_age_s < 0:
            raise ScenarioError("SCENARIO_INVALID_FIELD", "observed_age_s")
        if not isinstance(self.readings, tuple) or len(self.readings) != 3:
            raise ScenarioError("SCENARIO_INVALID_FIELD", "water_quality")
        for field, intent in zip(READING_FIELDS, self.readings):
            if not isinstance(intent, ReadingIntent) or intent.state not in ("NORMAL", "MISSING", "INVALID"):
                raise ScenarioError("SCENARIO_INVALID_FIELD", field)
            if intent.state == "NORMAL" and not finite_number(intent.value):
                raise ScenarioError("SCENARIO_VALUE_REQUIRED", field)

    @classmethod
    def from_dict(cls, data: dict) -> ScenarioTemplate:
        allowed = {"schema_version", "id", "display_name", "description", "device_id",
                   "water_quality", "observed_age_s"}
        required = {"schema_version", "id", "display_name", "water_quality", "observed_age_s"}
        if not isinstance(data, dict) or set(data) - allowed or not required <= set(data):
            raise ScenarioError("SCENARIO_INVALID_FIELD")
        water = data["water_quality"]
        if not isinstance(water, dict) or set(water) != set(READING_FIELDS):
            raise ScenarioError("SCENARIO_INVALID_FIELD", "water_quality")
        readings = []
        for field in READING_FIELDS:
            item = water[field]
            if not isinstance(item, dict) or "state" not in item or set(item) - {"state", "value"}:
                raise ScenarioError("SCENARIO_INVALID_FIELD", field)
            readings.append(ReadingIntent(item["state"], item.get("value") if item["state"] == "NORMAL" else None))
        device_id = data.get("device_id", "sim-device-001")
        if isinstance(device_id, str) and not device_id.strip():
            device_id = "sim-device-001"
        return cls(data["id"], data["display_name"], tuple(readings), data["observed_age_s"],
                   device_id, data.get("description", ""),
                   data["schema_version"])

    def to_dict(self) -> dict:
        return {"schema_version": self.schema_version, "id": self.id,
                "display_name": self.display_name, "description": self.description,
                "device_id": self.device_id, "observed_age_s": self.observed_age_s,
                "water_quality": {field: {"state": intent.state, **(
                    {"value": intent.value} if intent.state == "NORMAL" else {})}
                    for field, intent in zip(READING_FIELDS, self.readings)}}


@dataclass(frozen=True)
class StoredScenario:
    template: ScenarioTemplate
    source: str

    def public_info(self) -> dict:
        return {**self.template.to_dict(), "source": self.source}


class ScenarioTemplateStore:
    def __init__(self, builtin_directory, user_directory: Path | None = None):
        self.user_directory = Path(user_directory).absolute() if user_directory is not None else None
        self._lock = RLock()
        self._builtins = {}
        for path in sorted(builtin_directory.iterdir(), key=lambda p: p.name):
            if path.name.endswith(".json"):
                template = ScenarioTemplate.from_dict(json.loads(path.read_text(encoding="utf-8")))
                if path.name != template.id + ".json" or template.id in self._builtins:
                    raise ScenarioError("SCENARIO_INVALID_ID")
                self._builtins[template.id] = template

    def _directory(self, *, create=False) -> Path:
        if self.user_directory is None:
            raise ScenarioError("SCENARIO_READ_ONLY")
        directory = self.user_directory
        missing = []
        ancestor = directory
        while not ancestor.exists() and not ancestor.is_symlink():
            missing.append(ancestor)
            ancestor = ancestor.parent
        try:
            guard_path(ancestor)
            if create:
                for item in reversed(missing):
                    item.mkdir(exist_ok=True)
                    guard_path(item)
            if directory.exists():
                guard_path(directory)
                if not directory.is_dir():
                    raise SecureFileError()
        except (OSError, SecureFileError):
            raise ScenarioError("SCENARIO_STORAGE_ERROR") from None
        return directory

    def _path(self, identifier) -> Path:
        validate_id(identifier)
        directory = self._directory()
        path = directory / (identifier + ".json")
        if directory.exists():
            try:
                guard_path(path, regular=True)
            except SecureFileError:
                raise ScenarioError("SCENARIO_STORAGE_ERROR") from None
        return path

    def list_templates(self) -> tuple[StoredScenario, ...]:
        with self._lock:
            result = [StoredScenario(t, "BUILTIN") for t in self._builtins.values()]
            if self.user_directory is not None:
                directory = self._directory()
                if directory.exists():
                    for path in sorted(directory.glob("*.json")):
                        if path.stem in self._builtins:
                            raise ScenarioError("SCENARIO_ID_EXISTS")
                        result.append(self.get_template(path.stem))
            return tuple(result)

    def get_template(self, identifier: str) -> StoredScenario:
        validate_id(identifier)
        with self._lock:
            if identifier in self._builtins:
                return StoredScenario(self._builtins[identifier], "BUILTIN")
            if self.user_directory is None:
                raise ScenarioError("SCENARIO_NOT_FOUND")
            path = self._path(identifier)
            try:
                template = ScenarioTemplate.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except FileNotFoundError:
                raise ScenarioError("SCENARIO_NOT_FOUND") from None
            except (OSError, ValueError):
                raise ScenarioError("SCENARIO_STORAGE_ERROR") from None
            if template.id != identifier:
                raise ScenarioError("SCENARIO_INVALID_ID")
            return StoredScenario(template, "USER")

    def _write(self, template: ScenarioTemplate, *, update: bool) -> StoredScenario:
        # Revalidate direct callers before touching the filesystem.
        template = ScenarioTemplate.from_dict(template.to_dict())
        with self._lock:
            if template.id in self._builtins:
                raise ScenarioError("SCENARIO_READ_ONLY" if update else "SCENARIO_ID_EXISTS")
            if update:
                self.get_template(template.id)
            elif self.user_directory is not None and self._path(template.id).exists():
                raise ScenarioError("SCENARIO_ID_EXISTS")
            directory = self._directory(create=True)
            path = self._path(template.id)
            temporary = directory / (".staging-" + uuid.uuid4().hex)
            try:
                with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                    stream.write(json.dumps(template.to_dict(), ensure_ascii=False, indent=2) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                if update:
                    os.replace(temporary, path)
                else:
                    os.link(temporary, path)  # Exclusive publish; never overwrite another ID.
            except FileExistsError:
                raise ScenarioError("SCENARIO_ID_EXISTS") from None
            except OSError:
                raise ScenarioError("SCENARIO_STORAGE_ERROR") from None
            finally:
                temporary.unlink(missing_ok=True)
            return StoredScenario(template, "USER")

    def create_user_template(self, template: ScenarioTemplate) -> StoredScenario:
        return self._write(template, update=False)

    def update_user_template(self, identifier: str, template: ScenarioTemplate) -> StoredScenario:
        if template.id != validate_id(identifier):
            raise ScenarioError("SCENARIO_INVALID_ID")
        return self._write(template, update=True)

    def delete_user_template(self, identifier: str) -> None:
        with self._lock:
            if self.get_template(identifier).source != "USER":
                raise ScenarioError("SCENARIO_READ_ONLY")
            try:
                self._path(identifier).unlink()
            except OSError:
                raise ScenarioError("SCENARIO_STORAGE_ERROR") from None

    def save_as_user_template(self, identifier: str, *, display_name: str) -> StoredScenario:
        original = self.get_template(identifier).template
        return self.create_user_template(replace(original, id="user-" + uuid.uuid4().hex,
                                                 display_name=display_name))


def apply_scenario_template(template: ScenarioTemplate, *, snapshot_store: CurrentSnapshotStore,
                            adapter: SimulationAdapter, now: datetime) -> WaterQualityReading:
    """One simulation ingress path for builtin, user and unsaved templates."""
    simulator = TelemetrySimulator(device_id=template.device_id)
    setters = (simulator.set_temperature, simulator.set_ph, simulator.set_do)
    for field, intent, setter in zip(READING_FIELDS, template.readings, setters):
        if intent.state == "NORMAL":
            setter(intent.value)
        elif intent.state == "MISSING":
            simulator.missing(field)
        else:
            simulator.invalid(field)
    try:
        observed_at = now - timedelta(seconds=template.observed_age_s)
    except OverflowError:
        raise ScenarioError("SCENARIO_INVALID_FIELD", "observed_age_s") from None
    packet = simulator.generate(observed_at=observed_at)
    reading = adapter.to_reading(packet, retrieved_at=now)
    snapshot_store.set_current(reading)
    return reading
