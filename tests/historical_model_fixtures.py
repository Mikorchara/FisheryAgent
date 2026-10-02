"""Explicit offline historical assets; never used by normal startup or clean-room tests."""
import json
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

FIXTURES = Path(__file__).parent / "fixtures/historical_model_assets"

class ResourceOverlay:
    def __init__(self, live):
        self.live = live
    def joinpath(self, *parts):
        relative = "/".join(str(part) for part in parts).replace("\\", "/")
        if relative == "profiles":
            return FIXTURES / "profiles"
        if relative.startswith("profiles/"):
            return FIXTURES / relative
        if relative == "resources/profiles":
            return FIXTURES / "profiles"
        return self.live.joinpath(*parts)

def activate(namespace):
    """Historical compatibility modules opt in only during their own test lifecycle."""
    from fishery_ai import web, presets, real_validation, official_capabilities
    context = ExitStack()
    for module in (web, real_validation):
        context.enter_context(patch.object(module, "RESOURCE_ROOT", ResourceOverlay(module.RESOURCE_ROOT)))
    live_files = presets.files
    context.enter_context(patch.object(presets, "files", lambda package: ResourceOverlay(live_files(package))))
    if "RESOURCE_ROOT" in namespace:
        context.enter_context(patch.object(sys.modules[namespace["__name__"]], "RESOURCE_ROOT", ResourceOverlay(namespace["RESOURCE_ROOT"])))
    records = json.loads((FIXTURES / "official_declarations.json").read_text(encoding="utf-8"))
    declarations = {(r["service_id"], r["base_url"], r["model"]):
                    (r["default"], tuple(r["efforts"]), tuple(r["urls"])) for r in records}
    context.enter_context(patch.dict(official_capabilities.DECLARATIONS, declarations, clear=True))
    return context

def install(namespace):
    """Opt in explicitly, with restoration between unittest modules."""
    old_setup = namespace.get("setUpModule")
    old_teardown = namespace.get("tearDownModule")
    context = None
    def setup():
        nonlocal context
        context = activate(namespace)
        try:
            if old_setup:
                old_setup()
        except BaseException:
            context.close()
            raise
    def teardown():
        try:
            if old_teardown:
                old_teardown()
        finally:
            context.close()
    namespace.update(setUpModule=setup, tearDownModule=teardown)
