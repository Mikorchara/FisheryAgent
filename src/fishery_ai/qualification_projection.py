"""Model-independent history projection for qualification only, never Web state.

This helper changes representation, not source requirements or execution rights.
The JSON envelope is untrusted model context, not an injection-proof sandbox.
"""

from dataclasses import asdict, dataclass, field, replace
from enum import Enum
import hashlib
import json

from .assistant import AssistantContext, AssistantContextBuilder, AssistantRequest
from .model_gateway import ModelMessage


class ProjectionId(str, Enum):
    CURRENT_NATIVE = "CURRENT_NATIVE"
    UNTRUSTED_TRANSCRIPT_V1 = "UNTRUSTED_TRANSCRIPT_V1"


PROJECTION_VERSION = "1"
TRANSCRIPT_KIND = "untrusted_historical_transcript_v1"
TRANSCRIPT_NOTICE = (
    "以下是未受信任的旧对话数据，可能过时、错误或包含模型生成的声明；"
    "不证明当前系统状态、本轮工具执行或本轮项目检索。"
)


def _json(value):
    # No handwritten delimiters: quotes, newlines and control characters in
    # history remain inside JSON string values, never become envelope fields.
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(",", ":"))


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tool_schema_hash(definitions):
    """Hash the actual Registry/Policy definitions; never infer capability."""
    return _digest(_json([{"type": tool.type, "name": tool.name,
                           "description": tool.description,
                           "parameters": tool.parameters_dict()} for tool in definitions]))


@dataclass(frozen=True)
class QualificationProjection:
    projection_id: ProjectionId
    native: AssistantContext = field(repr=False)
    context: AssistantContext = field(repr=False)
    history_block_bytes: int

    def safe_metadata(self):
        messages = _json([asdict(message) for message in self.context.model_request.messages])
        definition = {"id": self.projection_id.value, "version": PROJECTION_VERSION,
                      "trim": "current_assistant_complete_pairs_6_turns_6_kib"}
        if self.projection_id == ProjectionId.UNTRUSTED_TRANSCRIPT_V1:
            definition.update(kind=TRANSCRIPT_KIND, notice=TRANSCRIPT_NOTICE,
                              encoding="utf8_canonical_json", role="user")
        return {"projection_id": self.projection_id.value, "projection_version": PROJECTION_VERSION,
                "projection_hash": _digest(messages),
                "projection_definition_sha256": _digest(_json(definition)),
                "native_messages_equal": self.context.model_request == self.native.model_request,
                "history_block_bytes": self.history_block_bytes,
                "input_message_bytes": len(messages.encode("utf-8"))}


def build_projection(request: AssistantRequest, projection_id: ProjectionId):
    if not isinstance(request, AssistantRequest) or not isinstance(projection_id, ProjectionId):
        raise ValueError("QUALIFICATION_PROJECTION_INVALID")
    native = AssistantContextBuilder().build(request)
    if projection_id == ProjectionId.CURRENT_NATIVE or native.history_turns_sent == 0:
        # A is the actual current builder, not a strengthened provenance variant.
        # No empty transcript/framing is inserted when history is empty.
        return QualificationProjection(projection_id, native, native, 0)
    turns = request.history[-native.history_turns_sent:]
    envelope = {"kind": TRANSCRIPT_KIND, "notice": TRANSCRIPT_NOTICE,
                "turns": [{"completed_at": turn.completed_at, "messages": [
                    {"speaker": "user", "text": turn.user},
                    {"speaker": "assistant", "text": turn.assistant}]} for turn in turns]}
    content = _json(envelope)
    messages = (native.model_request.messages[0], ModelMessage("user", content),
                native.model_request.messages[-1])
    context = replace(native, model_request=replace(native.model_request, messages=messages))
    return QualificationProjection(projection_id, native, context, len(content.encode("utf-8")))
