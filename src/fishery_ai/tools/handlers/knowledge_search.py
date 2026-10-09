"""Read-only project knowledge search; no model, no I/O, no second index."""

from ...knowledge import KnowledgeService


TOP_K = 3               # Fixed server-side budget; never a model-supplied parameter.
MAX_TEXT_CHARS = 800    # Per evidence text, counted in CHARACTERS (not UTF-8 bytes).
TRUNCATION_MARK = "\u2026"


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
            # retrieval scale produced these items. Never inferred or composed here.
            "retrieval_mode": service.backend,
            "result_count": len(items),
            "evidence": items}


def _bounded_text(text: str) -> str:
    """Truncate in characters. The longest live chunk is 415 chars / 844 bytes."""
    return text if len(text) <= MAX_TEXT_CHARS else text[:MAX_TEXT_CHARS] + TRUNCATION_MARK
