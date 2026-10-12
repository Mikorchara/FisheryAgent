"""Compatibility alias; use fishery_ai.development.qualification.qualification_projection.

The alias preserves module identity and historical monkeypatch contracts.
"""
import sys
from importlib import import_module

sys.modules[__name__] = import_module(
    "fishery_ai.development.qualification.qualification_projection")
