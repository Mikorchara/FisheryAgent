"""Independent expert body contract, without managed options or Fishery context."""

from dataclasses import dataclass, field
import json

from .contracts import Usage
from .model_gateway import GatewayError


FORBIDDEN = {"api_key", "authorization", "headers", "extra_headers", "base_url", "url",
             "credential_ref", "secret_env", "timeout", "max_retries", "extra_query", "extra_body"}


@dataclass(frozen=True)
class ManualRequest:
    body_json: str = field(repr=False)

    @classmethod
    def from_dict(cls, body, *, model):
        if not isinstance(body, dict) or body.get("model") != model:
            raise GatewayError("MANUAL_MODEL_MISMATCH")
        def check(value, depth=0):
            if depth > 32:
                raise GatewayError("REQUEST_TOO_COMPLEX")
            if isinstance(value, dict):
                if any(str(key).casefold() in FORBIDDEN for key in value):
                    raise GatewayError("MANUAL_RESERVED_FIELD")
                for item in value.values():
                    check(item, depth + 1)
            elif isinstance(value, list):
                for item in value:
                    check(item, depth + 1)
        check(body)
        if type(body.get("stream", False)) is not bool:
            raise GatewayError("INVALID_REQUEST")
        if not isinstance(body.get("messages"), list) or not body["messages"]:
            raise GatewayError("INVALID_REQUEST")
        try:
            value = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            size = len(value.encode("utf-8"))
        except (TypeError, ValueError, UnicodeError):
            raise GatewayError("INVALID_REQUEST") from None
        if size > 12 * 1024:
            raise GatewayError("REQUEST_TOO_LARGE")
        return cls(value)

    @property
    def streaming(self):
        return json.loads(self.body_json).get("stream", False)


@dataclass(frozen=True)
class ManualResponse:
    raw: dict = field(repr=False)
    usage: Usage = field(default_factory=Usage)
