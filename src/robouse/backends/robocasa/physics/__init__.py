"""Generic simulation physics for RoboCasa scenario kitchens, beside MuJoCo: `liquid/` (SPH liquid).

Standard library only, so the RoboCasa worker (which runs without the robouse package) can load this file by path.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys

LIQUID = "robouse_robocasa_liquid"


def load_liquid(submodule: str | None = None):
    """The liquid package (or one of its submodules, e.g. "scene"), loaded once per process as `robouse_robocasa_liquid`.

    One name everywhere (worker, scenario predicates, host-side scripts, the omni-safety re-export) means one copy of
    the solver bridge and of its native singleton."""
    pkg = sys.modules.get(LIQUID)
    if pkg is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "liquid", "__init__.py")
        spec = importlib.util.spec_from_file_location(LIQUID, path, submodule_search_locations=[os.path.dirname(path)])
        pkg = importlib.util.module_from_spec(spec)
        sys.modules[LIQUID] = pkg
        try:
            spec.loader.exec_module(pkg)
        except BaseException:
            sys.modules.pop(LIQUID, None)
            raise
    return importlib.import_module(f"{LIQUID}.{submodule}") if submodule else pkg
