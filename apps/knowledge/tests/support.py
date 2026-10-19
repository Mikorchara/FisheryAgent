"""Explicit isolated seed; never opens a user DB."""
from pathlib import Path
from apps.knowledge.migration import migrate, legacy_reference

LEGACY_JSON=Path(__file__).with_name('fixtures')/'eel_knowledge_v1.json'


def reference_knowledge():
    """Frozen public corpus; preserves Scope/DTO baselines without importing the old package."""
    return legacy_reference(LEGACY_JSON)


def seed(path):
    plan=migrate(None,path,LEGACY_JSON)
    return migrate(None,path,LEGACY_JSON,apply=True,approved_plan_sha256=plan['plan_sha256'])
