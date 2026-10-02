"""Conservative offline resolution; encoding and capability evidence stay separate."""

from dataclasses import dataclass, replace

from .model_options import CapabilitySource, ModelCapabilities, Support, normalize_base_url
from .official_capabilities import DECLARATIONS, REVIEWED_AT


FIELDS = ("streaming", "temperature", "top_p", "max_output_tokens", "reasoning_on",
          "reasoning_off", "reasoning_effort", "structured_output", "tool_calling",
          "streaming_usage", "thinking_streaming_combination", "thinking_default")


@dataclass(frozen=True)
class CapabilityIdentity:
    service_id: str
    adapter_id: str
    base_url: str
    model: str

    def __post_init__(self):
        object.__setattr__(self, "base_url", normalize_base_url(self.base_url))

    @classmethod
    def for_profile(cls, profile):
        return cls(profile.service_id, profile.adapter_id, profile.base_url, profile.model)


@dataclass(frozen=True)
class CapabilityEvidence:
    identity: CapabilityIdentity
    capability: str
    status: Support
    source: CapabilitySource
    observed_at: str | None
    origin: str
    value: bool | tuple[str, ...] | None = None

    def __post_init__(self):
        object.__setattr__(self, "status", Support(self.status))
        object.__setattr__(self, "source", CapabilitySource.parse(self.source))
        if self.capability not in FIELDS or self.source == CapabilitySource.UNKNOWN:
            raise ValueError("invalid capability evidence")
        if self.capability == "thinking_default" and type(self.value) is not bool:
            raise ValueError("default evidence requires a boolean")
        if (self.capability == "reasoning_effort" and self.status == Support.SUPPORTED
                and (not isinstance(self.value, tuple) or not self.value
                     or any(not isinstance(item, str) for item in self.value))):
            raise ValueError("effort evidence requires exact values")


def project_evidence(profile):
    """Collect original bundled declarations and exact maintained official records."""
    identity = CapabilityIdentity.for_profile(profile)
    basis = profile.capability_basis or profile.capabilities
    claims = []
    scoped = (basis.service_id == identity.service_id and basis.adapter_id == identity.adapter_id
              and basis.base_url == identity.base_url and basis.model_id == identity.model)
    if scoped:
        for name in FIELDS:
            value = getattr(basis, name)
            status = Support.SUPPORTED if name == "thinking_default" and value is not None else value
            source = basis.source_for(name)
            if status not in (Support.SUPPORTED, Support.UNSUPPORTED) or source == CapabilitySource.UNKNOWN:
                continue
            payload = (basis.effort_values if name == "reasoning_effort" and status == Support.SUPPORTED
                       else value if name == "thinking_default" else None)
            claims.append(CapabilityEvidence(identity, name, status, source, basis.verified_at,
                                              "project_record", payload))
    declaration = DECLARATIONS.get((identity.service_id, identity.base_url, identity.model))
    if identity.adapter_id == "openai_chat" and declaration is not None:
        default, efforts, urls = declaration
        for name in ("streaming", "reasoning_on", "reasoning_off", "streaming_usage",
                     "thinking_streaming_combination", "thinking_default"):
            claims.append(CapabilityEvidence(identity, name, Support.SUPPORTED,
                CapabilitySource.OFFICIAL_DOCS, REVIEWED_AT, urls[0], default if name == "thinking_default" else None))
        if efforts:
            claims.append(CapabilityEvidence(identity, "reasoning_effort", Support.SUPPORTED,
                CapabilitySource.OFFICIAL_DOCS, REVIEWED_AT, urls[0], efforts))
    return claims


def resolve_capabilities(profile, evidence):
    if profile.access_mode == "preset" or profile.provider_kind == "mock":
        return profile  # Published contract cannot be rewritten by local evidence.
    identity = CapabilityIdentity.for_profile(profile)
    claims = tuple(dict.fromkeys(item for item in evidence if item.identity == identity))
    basis = profile.capability_basis or profile.capabilities
    updates = {}
    primary, history, explanations = [], [], []
    rank = {CapabilitySource.OFFICIAL_DOCS: 1, CapabilitySource.MODEL_METADATA: 2,
            CapabilitySource.USER_VERIFIED: 3}
    for name in FIELDS:
        items = [item for item in claims if item.capability == name and item.status != Support.UNKNOWN]
        conclusions = {(item.status, item.value) for item in items}
        conflict = len(conclusions) > 1
        status = Support.UNKNOWN if not items or conflict else items[0].status
        if name == "thinking_default":
            updates[name] = items[0].value if items and not conflict else None
        else:
            updates[name] = status
        if name == "reasoning_effort":
            updates["effort_values"] = items[0].value if status == Support.SUPPORTED else ()
        history.extend((name, item.source) for item in items)
        source = max((item.source for item in items), key=lambda x: rank[x], default=CapabilitySource.UNKNOWN)
        primary.append((name, source))
        explanations.append((name, "EVIDENCE_CONFLICT" if conflict else "EVIDENCE_AGREEMENT" if items else "NO_EVIDENCE"))
    cap = ModelCapabilities(**updates, max_tokens_field=basis.max_tokens_field,
        reasoning_temperature_conflict=basis.reasoning_temperature_conflict or (identity.adapter_id == "openai_chat" and
            (identity.service_id, identity.base_url, identity.model) in DECLARATIONS and identity.service_id == "deepseek_api"),
        service_id=identity.service_id, adapter_id=identity.adapter_id, base_url=identity.base_url,
        model_id=identity.model, evidence=tuple(primary), evidence_sources=tuple(history),
        resolution_details=tuple(explanations), verified_at=max(
            (item.observed_at for item in claims if item.observed_at and item.source == CapabilitySource.USER_VERIFIED), default=None))
    return replace(profile, capabilities=cap, capability_evidence=claims)
