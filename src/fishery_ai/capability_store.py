"""Local, secret-free records for explicitly verified exact Profile capabilities."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json

from .model_gateway import ModelProfile
from .model_options import (CapabilitySource, ReasoningMode, Support, normalize_base_url)
from .evidence_resolver import (CapabilityEvidence, CapabilityIdentity, project_evidence,
                                resolve_capabilities)


class CapabilityStore:
    def __init__(self, directory: Path):
        self.directory = directory

    @staticmethod
    def _identity(profile: ModelProfile) -> dict[str, str]:
        return {"service_id": profile.service_id or profile.provider_id,
                "adapter_id": profile.adapter_id,
                "base_url": normalize_base_url(profile.base_url), "model": profile.model}

    def _path(self, profile: ModelProfile, capability: str = "streaming") -> Path:
        identity = self._identity(profile)
        identity["capability"] = capability
        key = sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return self.directory / f"{key}.json"

    @staticmethod
    def _record_matches(record: object, identity: dict[str, str], capability: str) -> bool:
        if not isinstance(record, dict) or record.get("capability") != capability:
            return False
        try:
            candidate = {key: record[key] for key in identity}
            candidate["base_url"] = normalize_base_url(candidate["base_url"])
        except (KeyError, TypeError, ValueError):
            return False
        return candidate == identity

    def _read_records(self, profile: ModelProfile, capability: str) -> list[dict]:
        identity = self._identity(profile)
        direct = self._path(profile, capability)
        candidates = [direct]
        # Keep normalized legacy records visible to the resolver as evidence,
        # including disagreements; a canonical filename is not higher authority.
        if self.directory.is_dir():
            candidates.extend(path for path in self.directory.glob("*.json") if path != direct)
        records = []
        for path in candidates:
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            if not self._record_matches(record, identity, capability):
                continue
            timestamp = record.get("observed_at" if capability == "thinking" else "verified_at")
            if timestamp is not None and not isinstance(timestamp, str):
                continue
            if capability == "thinking":
                values = record.get("values")
                valid = (record.get("source") in (CapabilitySource.MODEL_METADATA.value,
                                                  CapabilitySource.USER_VERIFIED.value)
                    and isinstance(values, list) and bool(values)
                    and all(type(item) is bool for item in values)
                    and type(record.get("default")) is bool and record["default"] in values)
            else:
                valid = (record.get("status") in ("supported", "unsupported")
                         and record.get("source") in ((CapabilitySource.EXPLICIT_PROBE.value,)
                             if capability == "tool_calling" else (CapabilitySource.USER_VERIFIED.value,)))
            if valid:
                records.append(record)
        return records

    def apply(self, profile: ModelProfile) -> ModelProfile:
        if profile.access_mode == "preset" or profile.provider_kind == "mock":
            return profile
        identity = CapabilityIdentity.for_profile(profile)
        claims = project_evidence(profile)
        for name in ("streaming", "reasoning_on", "reasoning_off", "thinking_streaming_combination", "thinking_off_streaming_combination", "tool_calling"):
            for record in self._read_records(profile, name):
                claims.append(CapabilityEvidence(identity, name, Support(record["status"]),
                    CapabilitySource.parse(record["source"]), record.get("verified_at"),
                    "explicit_probe" if name == "tool_calling" else "local_probe"))
        for metadata in self._read_records(profile, "thinking"):
            values = metadata["values"]
            source = CapabilitySource.parse(metadata["source"])
            for name, value in (("reasoning_on", True), ("reasoning_off", False)):
                claims.append(CapabilityEvidence(identity, name,
                    Support.SUPPORTED if value in values else Support.UNSUPPORTED,
                    source, metadata.get("observed_at"), "local_metadata"))
            claims.append(CapabilityEvidence(identity, "thinking_default", Support.SUPPORTED,
                source, metadata.get("observed_at"), "local_metadata", metadata["default"]))
        return resolve_capabilities(profile, claims)

    def save_streaming(self, profile: ModelProfile, status: Support, verified_at: str) -> ModelProfile:
        return self.save_probe(profile, "streaming", status, verified_at)

    def save_thinking_metadata(self, profile: ModelProfile, values: list[bool],
                               default: bool, observed_at: str) -> ModelProfile:
        if profile.access_mode == "preset":
            raise ValueError("preset contract is read-only")
        if (profile.service_id != "ollama" or profile.model != "qwen3.5:4b"
                or type(default) is not bool
                or not isinstance(values, list) or not values
                or any(type(value) is not bool for value in values)
                or default not in values):
            raise ValueError("invalid Ollama thinking metadata")
        self.directory.mkdir(parents=True, exist_ok=True)
        record = {**self._identity(profile), "capability": "thinking",
                  "values": values, "default": default,
                  "source": CapabilitySource.MODEL_METADATA.value,
                  "observed_at": observed_at}
        path = self._path(profile, "thinking")
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
        temporary.replace(path)
        return self.apply(profile)

    def save_thinking_probe(self, profile: ModelProfile, mode: ReasoningMode,
                            status: Support, verified_at: str) -> ModelProfile:
        if mode not in (ReasoningMode.ON, ReasoningMode.OFF):
            raise ValueError("invalid exact-model Thinking probe result")
        capability = "reasoning_on" if mode == ReasoningMode.ON else "reasoning_off"
        return self.save_probe(profile, capability, status, verified_at)

    def save_probe(self, profile: ModelProfile, capability: str, status: Support,
                   verified_at: str, metrics: dict | None = None) -> ModelProfile:
        if profile.access_mode == "preset":
            raise ValueError("preset contract is read-only")
        if (capability not in ("streaming", "reasoning_on", "reasoning_off",
                               "thinking_streaming_combination", "thinking_off_streaming_combination", "tool_calling")
                or status not in (Support.SUPPORTED, Support.UNSUPPORTED)):
            raise ValueError("invalid probe result")
        record = {**self._identity(profile), "capability": capability,
                  "status": status.value, "source": (CapabilitySource.EXPLICIT_PROBE.value
                    if capability == "tool_calling" else CapabilitySource.USER_VERIFIED.value),
                  "verified_at": verified_at}
        if metrics:
            record["metrics"] = {key: value for key, value in metrics.items() if key in (
                "delta_count", "reasoning_delta_count", "ttft_ms", "content_ttft_ms",
                "latency_ms", "usage", "returned_model", "error_code", "finish_reason",
                "model_requests", "request_1", "request_2", "valid_tool_call", "tool_result_status")}
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(profile, capability)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
        temporary.replace(path)
        return self.apply(profile)
