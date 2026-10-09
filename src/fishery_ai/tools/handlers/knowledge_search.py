"""Read-only project knowledge search; no model, no I/O, no second index."""

from ...knowledge import KnowledgeService


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
