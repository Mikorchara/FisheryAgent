"""Versioned, maintenance-owned templates; never consult local capability evidence."""

from dataclasses import replace
from importlib.resources import files
import json

from .model_gateway import ModelProfile
from .model_options import ModelCapabilities, ReasoningMode, ReasoningOptions


def preset_profiles(*, include_candidates=False) -> tuple[ModelProfile, ...]:
    root = files("fishery_ai").joinpath("resources/profiles")
    catalog = json.loads(root.joinpath("presets.json").read_text(encoding="utf-8"))
    result = []
    for template in catalog["templates"]:
        if template.get("release_status") not in ("published", "candidate"):
            raise ValueError("Preset release status must be explicit")
        if template.get("release_status") == "candidate" and not include_candidates:
            continue
        base = ModelProfile.from_dict(json.loads(root.joinpath(template["connection_resource"]).read_text(
            encoding="utf-8"))["profiles"][0])
        identity = [base.service_id, base.adapter_id, base.base_url, base.model]
        if identity != template["identity"]:
            raise ValueError("Preset connection no longer matches its fixed contract")
        caps = ModelCapabilities(**template["capabilities"], service_id=base.service_id,
            adapter_id=base.adapter_id, base_url=base.base_url, model_id=base.model)
        for variant in template["variants"]:
            mode = ReasoningMode(variant["thinking"])
            if mode != ReasoningMode.AUTO and getattr(caps, f"reasoning_{mode.value}").value != "supported":
                raise ValueError("Preset Variant is not supported by its fixed contract")
            result.append(replace(base, profile_id=f"preset-{template['id']}-{variant['id']}",
                display_name=f"{template['display_name']} · {variant['label']}",
                access_mode="preset", preset_id=template["id"], preset_variant=variant["id"],
                preset_contract_version=template["contract_version"], capabilities=caps,
                default_reasoning=ReasoningOptions(mode),
                default_response_mode="normal", max_retries=0))
    return tuple(result)
