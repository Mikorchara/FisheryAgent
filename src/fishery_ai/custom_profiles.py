"""Small local store for developer-created Profiles; no credential values are stored."""

from __future__ import annotations

from pathlib import Path
import json
import re
import uuid

from .model_gateway import ModelProfile
from .model_options import ProfileStatus


PROFILE_FIELDS = {"display_name", "provider_id", "adapter_id", "base_url",
                  "model", "secret_env", "provider_kind"}


class CustomProfileStore:
    def __init__(self, directory: Path):
        self.directory = directory

    def load(self) -> tuple[ModelProfile, ...]:
        if not self.directory.exists():
            return ()
        profiles = []
        for path in sorted(self.directory.glob("custom-*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            if set(data) != PROFILE_FIELDS | {"profile_id", "profile_status", "max_retries"}:
                raise ValueError("invalid stored custom profile fields")
            if data["profile_id"] != path.stem or data["profile_status"] != "custom":
                raise ValueError("invalid stored custom profile identity")
            profile = ModelProfile.from_dict(data)
            if profile.profile_status != ProfileStatus.CUSTOM:
                raise ValueError("stored profile must remain CUSTOM")
            profiles.append(profile)
        return tuple(profiles)

    def create(self, fields: dict) -> ModelProfile:
        if set(fields) != PROFILE_FIELDS:
            raise ValueError("invalid custom profile fields")
        values = {}
        for name in PROFILE_FIELDS:
            value = fields[name]
            if not isinstance(value, str):
                raise ValueError("profile fields must be strings")
            values[name] = value.strip()
        if (not 1 <= len(values["display_name"]) <= 80
                or not 1 <= len(values["model"]) <= 128
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", values["provider_id"])):
            raise ValueError("invalid profile identity")
        if values["provider_kind"] not in ("cloud", "local"):
            raise ValueError("invalid provider_kind")
        if values["provider_kind"] == "cloud" and not values["secret_env"]:
            raise ValueError("cloud profile requires secret_env")
        if values["adapter_id"] not in ("openai_chat", "generic_openai_chat"):
            raise ValueError("invalid adapter_id")
        if values["adapter_id"] == "generic_openai_chat" and values["provider_id"] != "custom":
            raise ValueError("generic adapter requires provider_id=custom")
        profile_id = "custom-" + uuid.uuid4().hex
        profile = ModelProfile(
            profile_id=profile_id, display_name=values["display_name"],
            provider_kind=values["provider_kind"], base_url=values["base_url"],
            model=values["model"], secret_env=values["secret_env"] or None,
            adapter_id=values["adapter_id"], provider_id=values["provider_id"],
            profile_status=ProfileStatus.CUSTOM, max_retries=0,
        )
        data = {"profile_id": profile.profile_id, "profile_status": "custom",
                "max_retries": 0, **values}
        data["secret_env"] = profile.secret_env
        self.directory.mkdir(parents=True, exist_ok=True)
        # A generated file is created once; existing user Profiles are never overwritten.
        with (self.directory / f"{profile_id}.json").open("x", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        return profile
