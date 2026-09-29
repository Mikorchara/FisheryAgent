"""Local, secret-free records for explicitly verified exact Profile capabilities."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import json

from .model_gateway import ModelProfile
from .model_options import CapabilitySource, Support


class CapabilityStore:
    def __init__(self, directory: Path):
        self.directory = directory

    @staticmethod
    def _identity(profile: ModelProfile) -> dict[str, str]:
        return {"service_id": profile.service_id or profile.provider_id,
                "base_url": profile.base_url, "model": profile.model}

    def _path(self, profile: ModelProfile) -> Path:
        identity = self._identity(profile)
        key = sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return self.directory / f"{key}.json"

    @staticmethod
    def _with_streaming_evidence(capabilities: ModelCapabilities) -> ModelCapabilities:
        evidence = dict(capabilities.evidence)
        evidence["streaming"] = CapabilitySource.USER_VERIFIED
        return replace(capabilities, evidence=tuple(evidence.items()))

    def apply(self, profile: ModelProfile) -> ModelProfile:
        path = self._path(profile)
        if not path.is_file():
            return profile
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if (any(record.get(key) != value for key, value in self._identity(profile).items())
                    or record.get("capability") != "streaming"
                    or record.get("status") not in ("supported", "unsupported")
                    or record.get("source") != CapabilitySource.USER_VERIFIED.value):
                return profile
            capabilities = replace(
                profile.capabilities,
                streaming=Support(record["status"]),
                evidence=self._with_streaming_evidence(profile.capabilities).evidence,
                service_id=profile.service_id,
                base_url=profile.base_url,
                model_id=profile.model,
                verified_at=record.get("verified_at"),
            )
            return replace(profile, capabilities=capabilities)
        except (OSError, ValueError, TypeError, KeyError):
            return profile

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
                               service_id=profile.service_id, base_url=profile.base_url,
                               model_id=profile.model, verified_at=verified_at)
        return replace(profile, capabilities=capabilities)
