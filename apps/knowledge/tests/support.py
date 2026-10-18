"""Explicit isolated seed; never opens a user DB."""
from pathlib import Path
from apps.knowledge.migration import migrate

LEGACY_JSON=Path(__file__).resolve().parents[3]/'src/fishery_ai/resources/knowledge/eel_knowledge.json'


def seed(path):
    plan=migrate(None,path,LEGACY_JSON)
    return migrate(None,path,LEGACY_JSON,apply=True,approved_plan_sha256=plan['plan_sha256'])
