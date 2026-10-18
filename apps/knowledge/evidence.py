"""Read-only retrieval evidence, independent of Prototype domain contracts."""
from dataclasses import dataclass
from datetime import datetime, timezone
import math


def utcnow():
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class KnowledgeEvidence:
    evidence_id: str
    text: str
    category: str
    score: float
    source_id: str
    retrieved_at: datetime
    source_title: str | None = None
    source_version: str | None = None

    def __post_init__(self):
        if (self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None
                or not self.evidence_id or not self.source_id or not math.isfinite(self.score)):
            raise ValueError('invalid evidence identity or score')
