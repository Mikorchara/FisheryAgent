"""Two executable business definitions; score is only a known persisted Policy name."""
from apps.ai_backend.model_gateway import ModelToolDefinition
from fishery_ai.knowledge import KnowledgeService

CURRENT_WATER_QUALITY = "get_current_water_quality"

WATER_QUALITY_SCORE = "score_current_water_quality"

SEARCH_FISHERY_KNOWLEDGE = "search_fishery_knowledge"

KNOWLEDGE_DESCRIPTION = (
    "只读检索项目内鳗鲡养殖背景知识；用于用户明确要求查询项目资料，或回答依赖项目特有资料的问题。"
    "query应表达要检索的主题。返回有限背景证据及来源，不代表当前水质或现场事实，不诊断现场疾病，不负责当前评分。"
    "NO_MATCH表示检索正常完成但无合格命中，不是执行错误；不得编造命中内容。"
)

KNOWLEDGE_PARAMETERS = {
    "type": "object",
    "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 512}},
    "required": ["query"],
    "additionalProperties": False,
}

WATER_DEFINITION = ModelToolDefinition(
            name=CURRENT_WATER_QUALITY,
            description=("只读查询当前水质数值、状态、告警；用于确认当前系统水质及其追问，不负责评分、等级或分项评分。"
                         "返回当前快照的水质观测、数据质量、新鲜度、观测与评估时间及确定性诊断。"
                         "NO_DATA表示查询完成但无快照；存在快照时OK不代表数据一定有效、完整或新鲜，须按quality/freshness说明INVALID、PARTIAL或STALE。"
                         "查询不等于重新采样。"),
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
        )
KNOWLEDGE_DEFINITION = ModelToolDefinition(SEARCH_FISHERY_KNOWLEDGE, KNOWLEDGE_DESCRIPTION, KNOWLEDGE_PARAMETERS)

KNOWN_TOOL_NAMES = (CURRENT_WATER_QUALITY, WATER_QUALITY_SCORE, SEARCH_FISHERY_KNOWLEDGE)

# Existing query validation and bounded result mapping; retrieval remains in KnowledgeService.


TOP_K = 3               # Fixed server-side budget; never a model-supplied parameter.
MAX_TEXT_CHARS = 800    # Per evidence text, counted in CHARACTERS (not UTF-8 bytes).
MAX_QUERY_CHARS = 512   # Declared parameter bound; 512 CJK chars is 1536 UTF-8 bytes.
TRUNCATION_MARK = "\u2026"


def _is_rejected_character(character: str) -> bool:
    """True for C0/C1 controls (Cc) and lone surrogates (Cs).

    Written as explicit code-point ranges so this module keeps zero imports: it
    depends only on the injected service.
    """
    code = ord(character)
    return code <= 0x1F or 0x7F <= code <= 0x9F or 0xD800 <= code <= 0xDFFF


def validate_arguments(arguments: dict) -> dict:
    """Server-side parameter contract for this tool: reject, or return normalized input.

    The Executor runs this before the handler, so anything rejected here never
    reaches retrieval. Only ``query`` is declared - never ``top_k``, a backend, a
    threshold, a path, a URL or a module name. The 4096-byte argument ceiling is
    already enforced by the Executor, so no separate byte budget is needed here.
    """
    if not isinstance(arguments, dict) or set(arguments) != {"query"}:
        raise ValueError("only the query field is accepted")
    query = arguments["query"]
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    query = query.strip()
    if not query:
        raise ValueError("query must not be blank")
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError("query is too long")
    if any(_is_rejected_character(character) for character in query):
        raise ValueError("query must not contain control or surrogate characters")
    return {"query": query}


def search_fishery_knowledge(arguments: dict, *, service: KnowledgeService) -> dict:
    """Map one validated query to bounded background evidence.

    ``arguments`` is already normalized by the tool's declared argument contract:
    exactly one key, ``query`` (rejection and normalization belong to that
    contract, not here). Retrieval itself stays inside ``KnowledgeService`` - this
    handler never re-implements indexing, expansions, thresholds or a second
    index. Evidence text is untrusted data: it is passed through as data only and
    never interpreted as instructions.

    Returns ``OK`` with bounded items, or ``NO_MATCH`` with an empty list when the
    service reports no qualifying evidence. Service failures are not caught here.
    """
    evidence = service.search(arguments["query"], top_k=TOP_K)
    items = [{"id": item.evidence_id, "category": item.category, "source": item.source_id,
              "source_version": item.source_version, "text": _bounded_text(item.text)}
             for item in evidence]
    return {"status": "OK" if items else "NO_MATCH",
            # Effective backend, passed through as-is: it tells the model which
            # retrieval backend produced these items. Never inferred or composed here.
            "retrieval_mode": service.backend,
            "result_count": len(items),
            "evidence": items}


def _bounded_text(text: str) -> str:
    """Truncate in characters. The longest live chunk is 415 chars / 844 bytes."""
    return text if len(text) <= MAX_TEXT_CHARS else text[:MAX_TEXT_CHARS] + TRUNCATION_MARK
