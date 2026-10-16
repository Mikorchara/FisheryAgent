"""Versioned, maintenance-owned templates; never consult local capability evidence."""

from dataclasses import replace
from importlib.resources import files
import json

from apps.ai_backend.model_gateway import ModelProfile
from apps.ai_backend.model_options import ModelCapabilities, ReasoningMode, ReasoningOptions
from apps.ai_backend.protocol_specs import ProtocolSpec, protocol_for


def _catalog():
    return json.loads(files(__package__).joinpath("resources").joinpath("presets.json").read_text(encoding="utf-8"))


def default_preset_id() -> str | None:
    catalog = _catalog()
    value = catalog.get("default_preset_id")
    if value is not None and not any(t["id"] == value and t["release_status"] == "published"
                                     for t in catalog["templates"]):
        raise ValueError("Default Preset must be published")
    return value


def preset_profiles(*, include_candidates=False) -> tuple[ModelProfile, ...]:
    root = files(__package__).joinpath("resources")
    catalog = _catalog()
    result = []
    for template in catalog["templates"]:
        if template.get("release_status") not in ("published", "candidate"):
            raise ValueError("Preset release status must be explicit")
        if template.get("release_status") == "candidate" and not include_candidates:
            continue
        base = ModelProfile.from_dict(template["connection"] if "connection" in template else
            json.loads(root.joinpath(template["connection_resource"]).read_text(
                encoding="utf-8"))["profiles"][0])
        identity = [base.service_id, base.adapter_id, base.base_url, base.model]
        if identity != template["identity"]:
            raise ValueError("Preset connection no longer matches its fixed contract")
        caps = ModelCapabilities(**template["capabilities"], service_id=base.service_id,
            adapter_id=base.adapter_id, base_url=base.base_url, model_id=base.model)
        fixed_protocol = ProtocolSpec(**template["protocol_spec"]) if "protocol_spec" in template else None
        if fixed_protocol is not None and fixed_protocol != protocol_for(base):
            raise ValueError("Preset protocol does not match the maintained encoding")
        defaults = template.get("defaults", {})
        combinations = set()
        for variant in template["variants"]:
            mode = ReasoningMode(variant["thinking"])
            if mode != ReasoningMode.AUTO and getattr(caps, f"reasoning_{mode.value}").value != "supported":
                raise ValueError("Preset Variant is not supported by its fixed contract")
            responses = tuple(variant.get("response_modes", ()))
            if fixed_protocol is not None:
                if (not responses or len(responses) != len(set(responses))
                        or any(r not in ("normal", "streaming") for r in responses)):
                    raise ValueError("Preset requires explicit response combinations")
                for response in responses:
                    if (mode.value, response) in combinations:
                        raise ValueError("Duplicate Preset combination")
                    combinations.add((mode.value, response))
                    if response == "streaming" and (caps.streaming.value != "supported" or
                            mode == ReasoningMode.ON and caps.thinking_streaming_combination.value != "supported" or
                            mode == ReasoningMode.OFF and caps.thinking_off_streaming_combination.value != "supported"):
                        raise ValueError("Unvalidated Preset streaming combination")
            is_default = defaults.get("thinking") == mode.value
            result.append(replace(base, profile_id=f"preset-{template['id']}-{variant['id']}",
                display_name=f"{template['display_name']} · {variant['label']}",
                access_mode="preset", preset_id=template["id"], preset_variant=variant["id"],
                preset_contract_version=template["contract_version"], capabilities=caps,
                capability_basis=caps, capability_evidence=(),
                default_reasoning=ReasoningOptions(mode),
                default_response_mode=defaults.get("response_mode", "normal") if is_default else
                    (responses[0] if responses else "normal"), max_retries=0,
                preset_response_modes=responses, preset_protocol_spec=fixed_protocol,
                preset_is_default=is_default))
        if fixed_protocol is not None and (defaults.get("thinking"), defaults.get("response_mode")) not in combinations:
            raise ValueError("Preset default must be a published combination")
    if len({p.profile_id for p in result}) != len(result):
        raise ValueError("Duplicate Preset profile")
    return tuple(result)
