"""Small local store for developer-created Profiles; no credential values are stored."""

from __future__ import annotations

from pathlib import Path
import json
import os
import re
import uuid
from urllib.parse import urlsplit

from .model_gateway import ModelProfile
from .model_options import ProfileStatus


PROFILE_FIELDS = ("display_name", "provider_id", "adapter_id", "base_url",
                  "model", "secret_env", "provider_kind")


class ProfileFieldError(ValueError):
    """A safe, field-specific UI error that never includes submitted values."""

    def __init__(self, field: str, reason: str, message: str):
        super().__init__(message)
        self.field = field
        self.reason = reason
        self.message = message


class CustomProfileStore:
    def __init__(self, directory: Path):
        self.directory = directory

    def load(self) -> tuple[ModelProfile, ...]:
        if not self.directory.exists():
            return ()
        profiles = []
        for path in sorted(self.directory.glob("custom-*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            if set(data) != set(PROFILE_FIELDS) | {"profile_id", "profile_status", "max_retries"}:
                raise ValueError("invalid stored custom profile fields")
            if data["profile_id"] != path.stem or data["profile_status"] != "custom":
                raise ValueError("invalid stored custom profile identity")
            profile = ModelProfile.from_dict(data)
            if profile.profile_status != ProfileStatus.CUSTOM:
                raise ValueError("stored profile must remain CUSTOM")
            profiles.append(profile)
        return tuple(profiles)

    @staticmethod
    def validate(fields: dict) -> dict[str, str]:
        for name in PROFILE_FIELDS:
            if name not in fields:
                raise ProfileFieldError(name, "REQUIRED", f"{name} 字段不可缺少。")
        if set(fields) != set(PROFILE_FIELDS):
            raise ProfileFieldError("profile", "UNKNOWN_FIELD", "只允许页面列出的配置字段，不接受 API Key 等额外字段。")
        values = {}
        for name in PROFILE_FIELDS:
            value = fields[name]
            if not isinstance(value, str):
                raise ProfileFieldError(name, "INVALID_FORMAT", f"{name} 必须是文本。")
            values[name] = value.strip()
        if not 1 <= len(values["display_name"]) <= 80 or any(ord(c) < 32 for c in values["display_name"]):
            raise ProfileFieldError("display_name", "INVALID_FORMAT", "显示名称必填，最多 80 个字符，不能包含换行。")
        if not 1 <= len(values["model"]) <= 128 or any(ord(c) < 32 for c in values["model"]):
            raise ProfileFieldError("model", "INVALID_FORMAT", "model 必填，最多 128 个字符，不能包含换行。")
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", values["provider_id"]):
            raise ProfileFieldError("provider_id", "INVALID_FORMAT", "provider_id 使用小写字母开头的机器标识，可含数字、_ 和 -。")
        if values["provider_kind"] not in ("cloud", "local"):
            raise ProfileFieldError("provider_kind", "UNSUPPORTED", "deployment 只能选择 cloud 或 local。")
        if values["provider_kind"] == "cloud" and not values["secret_env"]:
            raise ProfileFieldError("secret_env", "REQUIRED", "Cloud Profile 必须填写 Secret 环境变量名，不是 API Key 值。")
        if values["secret_env"] and not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,127}", values["secret_env"]):
            raise ProfileFieldError("secret_env", "INVALID_FORMAT", "secret_env 只接受大写环境变量名，例如 DASHSCOPE_API_KEY，不能填写 Key 值。")
        if values["adapter_id"] not in ("openai_chat", "generic_openai_chat"):
            raise ProfileFieldError("adapter_id", "UNSUPPORTED", "adapter_id 只能选择页面提供的 OpenAI-compatible 类型。")
        if values["adapter_id"] == "generic_openai_chat" and values["provider_id"] != "custom":
            raise ProfileFieldError("provider_id", "CONFLICT", "generic_openai_chat 需要 provider_id 为 custom。")
        try:
            parsed = urlsplit(values["base_url"])
            valid_url = (parsed.scheme in ("http", "https") and bool(parsed.netloc)
                         and not parsed.query and not parsed.fragment
                         and not parsed.username and not parsed.password)
        except ValueError:
            valid_url = False
        if not valid_url:
            raise ProfileFieldError("base_url", "INVALID_URL", "base_url 必须是无账号、密码、查询和片段的 HTTP(S) 地址。")
        return values

    @staticmethod
    def build(values: dict[str, str], profile_id: str) -> tuple[ModelProfile, dict]:
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
        return profile, data

    def create(self, fields: dict) -> ModelProfile:
        values = self.validate(fields)
        profile_id = "custom-" + uuid.uuid4().hex
        profile, data = self.build(values, profile_id)
        self.directory.mkdir(parents=True, exist_ok=True)
        # A generated file is created once; existing user Profiles are never overwritten.
        with (self.directory / f"{profile_id}.json").open("x", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        return profile

    def update(self, profile_id: str, fields: dict) -> ModelProfile:
        values = self.validate(fields)
        if not re.fullmatch(r"custom-[0-9a-f]{32}", profile_id):
            raise ProfileFieldError("profile", "NOT_EDITABLE", "只能编辑用户自定义 Profile。")
        path = self.directory / f"{profile_id}.json"
        if not path.is_file():
            raise FileNotFoundError(profile_id)
        profile, data = self.build(values, profile_id)
        temporary = self.directory / f".{profile_id}-{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return profile

    def delete(self, profile_id: str) -> None:
        if not re.fullmatch(r"custom-[0-9a-f]{32}", profile_id):
            raise ProfileFieldError("profile", "NOT_EDITABLE", "只能删除用户自定义 Profile。")
        source = self.directory / f"{profile_id}.json"
        if not source.is_file():
            raise FileNotFoundError(profile_id)
        archive = self.directory / "archive"
        archive.mkdir(exist_ok=True)
        source.rename(archive / f"{profile_id}-{uuid.uuid4().hex}.json")
