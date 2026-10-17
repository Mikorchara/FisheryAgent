"""Mode restrictions over the static Registry; configuration cannot add handlers."""

from apps.ai_backend.tools.policy import ToolPolicy, ToolPolicyError
from importlib.resources import files
import json
from types import MappingProxyType
from pathlib import Path
import os
import stat
import threading
import uuid


def parse_tool_policies(data):
    from ..business_tools.registry import KNOWN_TOOL_NAMES
    if (not isinstance(data, dict) or set(data) != {"schema_version", "modes"}
            or type(data["schema_version"]) is not int or data["schema_version"] != 1
            or not isinstance(data["modes"], dict) or set(data["modes"]) != {"analysis", "assistant"}):
        raise ToolPolicyError()
    policies = {}
    for mode, record in data["modes"].items():
        if not isinstance(record, dict) or set(record) != {"llm_tool_calling", "exposed_tools"}:
            raise ToolPolicyError()
        policy = ToolPolicy(mode, record["llm_tool_calling"], record["exposed_tools"])
        if any(name not in KNOWN_TOOL_NAMES for name in policy.exposed_tools):
            raise ToolPolicyError("UNKNOWN_POLICY_TOOL")
        policies[mode] = policy
    return MappingProxyType(policies)


def load_tool_policies():
    # Fixed package resource; neither Web nor Profile can supply a path or code.
    try:
        resource = files(__package__).joinpath("resources/tool_policies.json")
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
        from ..business_tools.registry import KNOWN_TOOL_NAMES
        for mode, record in data["modes"].items():
            if not isinstance(record, dict) or set(record) != {"selected_tools"}:
                raise ToolPolicyError()
            names = record["selected_tools"]
            # Use the existing contract for name/type/duplicate validation.
            selected = ToolPolicy("assistant", True, names)
            if any(name not in KNOWN_TOOL_NAMES for name in selected.exposed_tools):
                raise ToolPolicyError("UNKNOWN_POLICY_TOOL")
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

        assistant = ToolPolicy("assistant", True,
            selections["modes"]["assistant"]["selected_tools"])

        return MappingProxyType({mode: ToolPolicy(mode, p.llm_tool_calling,
            tuple(name for name in p.exposed_tools if name in self.registry.registered_names()))
            for mode, p in (("analysis", analysis), ("assistant", assistant))})

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
