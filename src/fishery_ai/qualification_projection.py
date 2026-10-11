"""Model-independent history projection for qualification only, never Web state.

This helper changes representation, not source requirements or execution rights.
The JSON envelope is untrusted model context, not an injection-proof sandbox.
"""

from dataclasses import asdict, dataclass, field
import hashlib

from .assistant import AssistantContext, AssistantContextBuilder, AssistantRequest
from .history_projection import (ProjectionId, PROJECTION_VERSION, TRANSCRIPT_KIND,
    TRANSCRIPT_NOTICE, _json, project_retained_history)


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
    context, block_bytes = project_retained_history(request, native, projection_id)
    return QualificationProjection(projection_id, native, context, block_bytes)
