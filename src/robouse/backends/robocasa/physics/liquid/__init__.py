"""SPH liquid (DFSPH via SPlisHSPlasH) one-way coupled to MuJoCo, for RoboCasa scenario kitchens (liquid contract 0.3.0).

Generic physics only: the solver bridge and native-backend loader (`solver`), the MuJoCo coupling (`coupling`),
boundary meshes (`meshes`), absorbers and sleep (`contact`), ledger and wetting queries (`queries`, `scene`), the
rendered surface (`surface`) and the GPU prototype (`gpu`). Scene-specific pieces (which objects are liquid
containers, their inside profiles and fill recipes) come from outside through `register_container`, usually from a
scenario plugin (scenario.py `load_plugins`, `ROBOUSE_ROBOCASA_PLUGINS`). See docs/suites/robocasa.md.

Load this package through `robouse.backends.robocasa.physics.load_liquid()` (or the worker's `scenario.load_liquid()`),
never as `robouse.backends.robocasa.physics.liquid`: the worker runs without the robouse package, and the native
solver must exist once per process, so the package always has one name, `robouse_robocasa_liquid`.
"""

from __future__ import annotations

__version__ = "0.3.0"
NAME = "robouse_robocasa_liquid"

if __name__ != NAME:
    raise ImportError(
        f"load the liquid package with robouse.backends.robocasa.physics.load_liquid(), not as {__name__!r} "
        f"(one module name, {NAME!r}, keeps one native solver per process)"
    )

# Container kinds: kind -> (inside profile factory, fill factory or None); kind -> visual geom name (its SPH boundary)
PROFILES: dict = {}
VISUAL_GEOM: dict = {}


def register_container(kind: str, profile, fill=None, visual_geom: str | None = None) -> None:
    """Make `kind` usable in a liquid config's `containers` ({object name: kind}).

    `profile()` returns a `queries.Container` (inside profile, body frame); `fill(fill_ml, spacing)` returns the
    body-frame particle lattice of a source container (None: the kind cannot be a source); `visual_geom` names the
    object's visual mesh geom(s), which become the SPH boundary. Registering the same kind again with the same
    callables is a no-op; a different definition raises (a scene's physics must not change silently)."""
    if not visual_geom:
        raise ValueError(f"liquid container {kind!r} needs the name of its visual mesh geom")
    entry = (profile, fill)
    if kind in PROFILES and (PROFILES[kind] != entry or VISUAL_GEOM[kind] != visual_geom):
        raise ValueError(f"liquid container {kind!r} is already registered with a different definition")
    PROFILES[kind] = entry
    VISUAL_GEOM[kind] = visual_geom


def container_kind(kind: str):
    """(profile, fill, visual_geom) of a registered container kind; an unknown kind raises with the fix."""
    if kind not in PROFILES:
        raise ValueError(
            f"unknown liquid container kind {kind!r} (registered: {sorted(PROFILES)}); register it with "
            "register_container, e.g. from a scenario plugin named in ROBOUSE_ROBOCASA_PLUGINS"
        )
    profile, fill = PROFILES[kind]
    return profile, fill, VISUAL_GEOM[kind]
