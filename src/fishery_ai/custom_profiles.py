"""Small local store for developer-created Profiles; no credential values are stored."""

from __future__ import annotations

from pathlib import Path
import json
import os
import re
import uuid
from urllib.parse import urlsplit

from .model_gateway import (DEFAULT_LOCAL_READ_TIMEOUT_S,
                            DEFAULT_LOCAL_TOTAL_TIMEOUT_S, ModelProfile)
from .model_options import ProfileStatus


PROFILE_FIELDS = ("display_name", "service_id", "model_family", "adapter_id", "base_url",
                  "model", "secret_env", "provider_kind")
LEGACY_PROFILE_FIELDS = ("display_name", "provider_id", "adapter_id", "base_url",
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
            shared = {"profile_id", "profile_status", "max_retries"}
            if set(data) not in (set(PROFILE_FIELDS) | shared, set(LEGACY_PROFILE_FIELDS) | shared):
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
        fields = dict(fields)
        if "provider_id" in fields and "service_id" not in fields:
            legacy = fields.pop("provider_id")
            aliases = {"qwen": ("dashscope", "qwen"),
                       "deepseek": ("deepseek_api", "deepseek"),
                       "custom": ("custom", "unknown")}
            fallback = (legacy, "unknown") if isinstance(legacy, str) else (legacy, "unknown")
            fields["service_id"], fields["model_family"] = aliases.get(legacy, fallback) if isinstance(
                legacy, str) else fallback
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
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", values["service_id"]):
            raise ProfileFieldError("service_id", "INVALID_FORMAT", "service_id 使用小写字母开头的机器标识，可含数字、_ 和 -。")
        if not values["model_family"]:
            values["model_family"] = "unknown"
        if values["model_family"] not in ("qwen", "deepseek", "unknown"):
            raise ProfileFieldError("model_family", "UNSUPPORTED", "model_family 只能是 qwen、deepseek 或 unknown。")
        if values["provider_kind"] not in ("cloud", "local"):
            raise ProfileFieldError("provider_kind", "UNSUPPORTED", "deployment 只能选择 cloud 或 local。")
        if values["provider_kind"] == "cloud" and not values["secret_env"]:
            raise ProfileFieldError("secret_env", "REQUIRED", "Cloud Profile 必须填写 Secret 环境变量名，不是 API Key 值。")
        if values["secret_env"] and not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,127}", values["secret_env"]):
            raise ProfileFieldError("secret_env", "INVALID_FORMAT", "secret_env 只接受大写环境变量名，例如 DASHSCOPE_API_KEY，不能填写 Key 值。")
        if values["adapter_id"] not in ("openai_chat", "generic_openai_chat"):
            raise ProfileFieldError("adapter_id", "UNSUPPORTED", "adapter_id 只能选择页面提供的 OpenAI-compatible 类型。")
        if values["adapter_id"] == "generic_openai_chat" and values["service_id"] not in ("custom", "ollama"):
            raise ProfileFieldError("service_id", "CONFLICT", "generic_openai_chat 需要 service_id 为 custom 或 ollama。")
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
        legacy_provider = {"dashscope": "qwen", "deepseek_api": "deepseek"}.get(
            values["service_id"], "custom" if values["service_id"] == "custom"
            else values["service_id"])
        profile = ModelProfile(
            profile_id=profile_id, display_name=values["display_name"],
            provider_kind=values["provider_kind"], base_url=values["base_url"],
            model=values["model"], secret_env=values["secret_env"] or None,
            read_timeout_s=(DEFAULT_LOCAL_READ_TIMEOUT_S if values["provider_kind"] == "local"
                            else 30.0),
            total_timeout_s=(DEFAULT_LOCAL_TOTAL_TIMEOUT_S if values["provider_kind"] == "local"
                             else 120.0),
            adapter_id=values["adapter_id"], provider_id=legacy_provider,
            service_id=values["service_id"], model_family=values["model_family"],
            profile_status=ProfileStatus.CUSTOM, max_retries=0,
        )
        data = {"profile_id": profile.profile_id, "profile_status": "custom",
                "max_retries": 0, **values}
        data["secret_env"] = profile.secret_env
        return profile, data

    def create(self, fields: dict) -> ModelProfile:
        values = self.validate(fields)
        if any(profile.display_name.casefold() == values["display_name"].casefold()
               for profile in self.load()):
            raise ProfileFieldError("display_name", "NAME_EXISTS", "Profile 名称已存在，请使用唯一名称。")
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
        original_name = json.loads(path.read_text(encoding="utf-8"))["display_name"]
        if values["display_name"] != original_name:
            raise ProfileFieldError("display_name", "IMMUTABLE", "Profile 创建后不能改名；如需改名，请删除后重新创建。")
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
