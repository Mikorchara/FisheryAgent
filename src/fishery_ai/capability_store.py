"""Local, secret-free records for explicitly verified exact Profile capabilities."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import json

from .model_gateway import ModelProfile
from .model_options import (CapabilitySource, ModelCapabilities, ReasoningMode, Support,
                            ReasoningOptions, normalize_base_url)


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
    def _with_streaming_evidence(capabilities: ModelCapabilities) -> ModelCapabilities:
        evidence = dict(capabilities.evidence)
        evidence["streaming"] = CapabilitySource.USER_VERIFIED
        return replace(capabilities, evidence=tuple(evidence.items()))

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

    def _read_record(self, profile: ModelProfile, capability: str) -> dict | None:
        identity = self._identity(profile)
        direct = self._path(profile, capability)
        candidates = [direct]
        # Older records hashed the original URL spelling. Search allows a trailing slash
        # migration while still requiring the full service/adapter/model identity.
        if self.directory.is_dir():
            candidates.extend(path for path in self.directory.glob("*.json") if path != direct)
        for path in candidates:
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            if self._record_matches(record, identity, capability):
                if capability == "streaming":
                    if (record.get("status") in ("supported", "unsupported")
                            and record.get("source") == CapabilitySource.USER_VERIFIED.value):
                        return record
                elif capability == "thinking":
                    values = record.get("values")
                    if (record.get("source") in (CapabilitySource.MODEL_METADATA.value,
                                                   CapabilitySource.USER_VERIFIED.value)
                            and isinstance(values, list)
                            and all(type(item) is bool for item in values)
                            and type(record.get("default")) is bool
                            and record["default"] in values):
                        return record
                elif (record.get("status") in ("supported", "unsupported")
                      and record.get("source") == CapabilitySource.USER_VERIFIED.value):
                    return record
        return None

    @staticmethod
    def _replace_capabilities(profile: ModelProfile,
                              capabilities: ModelCapabilities) -> ModelProfile:
        default = profile.default_reasoning
        if ((default.mode == ReasoningMode.ON and capabilities.reasoning_on == Support.UNSUPPORTED)
                or (default.mode == ReasoningMode.OFF
                    and capabilities.reasoning_off == Support.UNSUPPORTED)):
            # A newly verified rejection makes the old default unusable. AUTO leaves
            # the parameter unset and preserves access to the model's own default.
            default = ReasoningOptions(ReasoningMode.AUTO)
        return replace(profile, capabilities=capabilities, default_reasoning=default)

    def apply(self, profile: ModelProfile) -> ModelProfile:
        updated = profile
        stream = self._read_record(profile, "streaming")
        if stream:
            evidence = dict(updated.capabilities.evidence)
            evidence["streaming"] = CapabilitySource.USER_VERIFIED
            updated = self._replace_capabilities(updated, replace(
                updated.capabilities, streaming=Support(stream["status"]),
                evidence=tuple(evidence.items()), service_id=profile.service_id,
                adapter_id=profile.adapter_id, base_url=profile.base_url,
                model_id=profile.model, verified_at=stream.get("verified_at")))
        metadata = self._read_record(profile, "thinking")
        if metadata:
            values = metadata["values"]
            evidence = dict(updated.capabilities.evidence)
            source = CapabilitySource.parse(metadata["source"])
            evidence.setdefault("reasoning_on", source)
            evidence.setdefault("reasoning_off", source)
            updated = self._replace_capabilities(updated, replace(
                updated.capabilities,
                reasoning_on=Support.SUPPORTED if True in values else Support.UNSUPPORTED,
                reasoning_off=Support.SUPPORTED if False in values else Support.UNSUPPORTED,
                thinking_default=metadata["default"], evidence=tuple(evidence.items()),
                service_id=profile.service_id, adapter_id=profile.adapter_id,
                base_url=profile.base_url, model_id=profile.model))
        for option, field_name in (("reasoning_on", "reasoning_on"),
                                   ("reasoning_off", "reasoning_off")):
            record = self._read_record(profile, option)
            if record:
                evidence = dict(updated.capabilities.evidence)
                evidence[field_name] = CapabilitySource.USER_VERIFIED
                updated = self._replace_capabilities(updated, replace(
                    updated.capabilities, **{field_name: Support(record["status"])},
                    evidence=tuple(evidence.items()), service_id=profile.service_id,
                    adapter_id=profile.adapter_id, base_url=profile.base_url,
                    model_id=profile.model, verified_at=record.get("verified_at")))
        return updated

    def save_streaming(self, profile: ModelProfile, status: Support, verified_at: str) -> ModelProfile:
        if status not in (Support.SUPPORTED, Support.UNSUPPORTED):
            raise ValueError("only an explicit probe result can be saved")
        self.directory.mkdir(parents=True, exist_ok=True)
        record = {**self._identity(profile), "capability": "streaming",
                  "status": status.value, "source": CapabilitySource.USER_VERIFIED.value,
                  "verified_at": verified_at}
        path = self._path(profile)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
        temporary.replace(path)
        capabilities = replace(profile.capabilities, streaming=status,
                               evidence=self._with_streaming_evidence(profile.capabilities).evidence,
                               service_id=profile.service_id, adapter_id=profile.adapter_id,
                               base_url=profile.base_url,
                               model_id=profile.model, verified_at=verified_at)
        return replace(profile, capabilities=capabilities)

    def save_thinking_metadata(self, profile: ModelProfile, values: list[bool],
                               default: bool, observed_at: str) -> ModelProfile:
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
        if (profile.service_id != "ollama" or profile.model != "qwen3.5:4b"
                or mode not in (ReasoningMode.ON, ReasoningMode.OFF)
                or status not in (Support.SUPPORTED, Support.UNSUPPORTED)):
            raise ValueError("invalid exact-model Thinking probe result")
        capability = "reasoning_on" if mode == ReasoningMode.ON else "reasoning_off"
        record = {**self._identity(profile), "capability": capability,
                  "status": status.value, "source": CapabilitySource.USER_VERIFIED.value,
                  "verified_at": verified_at}
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(profile, capability)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
        temporary.replace(path)
        return self.apply(profile)
