"""Compatibility alias for the single backend argument diagnostic implementation.

Keep module/type identity and historical monkeypatches; no second contract copy.
"""
import sys
from importlib import import_module

sys.modules[__name__] = import_module("apps.ai_backend.tool_argument_diagnostics")
