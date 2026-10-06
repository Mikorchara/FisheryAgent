"""Mode restrictions over the static Registry; configuration cannot add handlers."""

from dataclasses import dataclass
from importlib.resources import files
import json
from types import MappingProxyType
from pathlib import Path
import os
import stat
import threading
import uuid


class ToolPolicyError(ValueError):
    def __init__(self, code="INVALID_TOOL_POLICY"):
        self.code = code
        super().__init__(code)  # Never echo config content or file paths.


@dataclass(frozen=True)
class ToolPolicy:
    mode: str
    llm_tool_calling: bool
    exposed_tools: tuple[str, ...]

    def __post_init__(self):
        if (self.mode not in ("analysis", "assistant") or type(self.llm_tool_calling) is not bool
                or not isinstance(self.exposed_tools, (tuple, list))
                or any(not isinstance(name, str) or not name for name in self.exposed_tools)
                or len(set(self.exposed_tools)) != len(self.exposed_tools)
                or (not self.llm_tool_calling and self.exposed_tools)):
            raise ToolPolicyError()
        object.__setattr__(self, "exposed_tools", tuple(self.exposed_tools))

    def validate_registry(self, registry):
        from .contracts import ToolError
        for name in self.exposed_tools:
            try:
                registry.lookup(name)
            except ToolError:
                raise ToolPolicyError("UNKNOWN_POLICY_TOOL") from None

    def allows(self, name: str) -> bool:
        return self.llm_tool_calling and name in self.exposed_tools

    def model_definitions(self, registry):
        self.validate_registry(registry)
        # Definitions remain Registry-owned; no second JSON Schema or handler map.
        return tuple(definition for definition in registry.model_definitions()
                     if self.allows(definition.name) and callable(registry.lookup(definition.name).handler))


def parse_tool_policies(data):
    from .registry import ToolRegistry
    if (not isinstance(data, dict) or set(data) != {"schema_version", "modes"}
            or type(data["schema_version"]) is not int or data["schema_version"] != 1
            or not isinstance(data["modes"], dict) or set(data["modes"]) != {"analysis", "assistant"}):
        raise ToolPolicyError()
    policies = {}
    for mode, record in data["modes"].items():
        if not isinstance(record, dict) or set(record) != {"llm_tool_calling", "exposed_tools"}:
            raise ToolPolicyError()
        policy = ToolPolicy(mode, record["llm_tool_calling"], record["exposed_tools"])
        if any(name not in ToolRegistry.registered_names() for name in policy.exposed_tools):
            raise ToolPolicyError("UNKNOWN_POLICY_TOOL")
        policies[mode] = policy
    return MappingProxyType(policies)


def load_tool_policies():
    # Fixed package resource; neither Web nor Profile can supply a path or code.
    try:
        resource = files("fishery_ai").joinpath("resources/tools/tool_policies.json")
        return parse_tool_policies(json.loads(resource.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as exc:
        if isinstance(exc, ToolPolicyError):
            raise
        raise ToolPolicyError() from None


class UserToolPolicyStore:
    """Fixed startup path; capture frozen Analysis/Assistant authorization per request."""
    def __init__(self, directory: Path, registry):
        self.directory = Path(directory).absolute()
        self.path = self.directory / "tool_policies.json"
        self.registry = registry
        self.defaults = load_tool_policies()
        self._lock = threading.RLock()
        self.load()  # Corrupt/unknown overrides fail closed at startup.

    def _check_paths(self):
        for path in (self.path, self.directory, *self.directory.parents):
            try:
                info = path.lstat()
            except FileNotFoundError:
                continue
            if path.is_symlink() or getattr(info, "st_file_attributes", 0) & 1024:
                raise ToolPolicyError("TOOL_POLICY_STORAGE_ERROR")
            if path == self.path and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
                raise ToolPolicyError("TOOL_POLICY_STORAGE_ERROR")

    def _validate(self, data):
        if (not isinstance(data, dict) or set(data) != {"schema_version", "modes"}
                or type(data["schema_version"]) is not int or data["schema_version"] != 1
                or not isinstance(data["modes"], dict) or set(data["modes"]) != {"analysis", "assistant"}):
            raise ToolPolicyError()
        result = {"schema_version": 1, "modes": {}}
        from .catalog import tool_catalog
        executable = {item["name"] for item in tool_catalog(self.registry) if item["executable"]}
        for mode, record in data["modes"].items():
            if not isinstance(record, dict) or set(record) != {"selected_tools"}:
                raise ToolPolicyError()
            names = record["selected_tools"]
            # Use the existing contract for name/type/duplicate validation.
            selected = ToolPolicy("assistant", True, names)
            selected.validate_registry(self.registry)
            if any(name not in executable for name in selected.exposed_tools):
                raise ToolPolicyError("TOOL_NOT_EXECUTABLE")
            result["modes"][mode] = {"selected_tools": list(selected.exposed_tools)}
        return result

    def default_selections(self):
        return {"schema_version": 1, "modes": {mode: {"selected_tools": list(policy.exposed_tools)}
                for mode, policy in self.defaults.items()}}

    def load(self):
        with self._lock:
            try:
                self._check_paths()
                if self.path.stat().st_size > 8192:
                    raise ToolPolicyError("TOOL_POLICY_STORAGE_ERROR")
                return self._validate(json.loads(self.path.read_text(encoding="utf-8")))
            except FileNotFoundError:
                return self.default_selections()
            except ToolPolicyError:
                raise
            except (OSError, ValueError, TypeError, RecursionError):
                raise ToolPolicyError("TOOL_POLICY_STORAGE_ERROR") from None

    def effective(self):
        selections = self.load()
        analysis_names = selections["modes"]["analysis"]["selected_tools"]
        analysis = ToolPolicy("analysis", bool(analysis_names), analysis_names)
        analysis.validate_registry(self.registry)
        assistant = ToolPolicy("assistant", True,
            selections["modes"]["assistant"]["selected_tools"])
        assistant.validate_registry(self.registry)
        return MappingProxyType({"analysis": analysis, "assistant": assistant})

    def public(self):
        with self._lock:
            selections = self.load()
            return {**selections, "defaults": self.default_selections()["modes"],
                    "source": "USER_OVERRIDE" if self.path.exists() else "BUILTIN_DEFAULT",
                    "runtime_consumed": {"analysis": True, "assistant": True}}

    def save(self, data):
        values = self._validate(data)
        with self._lock:
            temporary = self.directory / (".tool-policy-" + uuid.uuid4().hex + ".tmp")
            created = False
            try:
                self._check_paths()
                self.directory.mkdir(parents=True, exist_ok=True)
                self._check_paths()
                with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                    created = True
                    json.dump(values, stream, ensure_ascii=False, allow_nan=False, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            except (OSError, ValueError):
                raise ToolPolicyError("TOOL_POLICY_STORAGE_ERROR") from None
            finally:
                try:
                    if created:
                        temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            return self.public()

    def reset(self):
        with self._lock:
            try:
                self._check_paths()
                self.path.unlink(missing_ok=True)
            except OSError:
                raise ToolPolicyError("TOOL_POLICY_STORAGE_ERROR") from None
            return self.public()
