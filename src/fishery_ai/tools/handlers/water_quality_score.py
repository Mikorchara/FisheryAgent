"""Read the canonical view and delegate scoring; no model, RAG or mutation."""

from ...telemetry.current import CurrentWaterQualityReader
from ...water_quality_scoring import WaterQualityScoringService
from .current_water_quality import water_quality_facts


def score_current_water_quality(*, reader: CurrentWaterQualityReader,
                                scoring: WaterQualityScoringService) -> dict:
    view = reader.query()
    result = scoring.score(view.reading if view else None).to_dict()
    result["water_quality"] = water_quality_facts(view.reading) if view else None
    result["evaluated_at"] = view.evaluated_at.isoformat() if view else None
    return result
