"""Physics extensions of the household simulation: generic per-control-step hooks for physics the scene's MJCF cannot
express on its own (a liquid, say). An extension is declared by a top-level key of the package's `episode.json`; the
key's value is the extension's own configuration, which only the extension validates.

    EXTENSIONS = {episode.json key: "module:Class"}   imported lazily; a package naming a key whose module does not
                                                      import is refused (PackageError) before the episode starts

The class (all methods but `__init__` optional):

    prepare(mjspec, config, root)   staticmethod/classmethod: edit the scene's `mujoco.MjSpec` before it is compiled
                                    (after the robot and cameras are added). `root` is the package directory; read
                                    only files the package's `files` lists. Must not touch names starting `robot/`.
    __init__(world, config)         constructed at every reset, after the scene and the robot's initial posture are
                                    set (mj_forward done) and before the reset settling, so the extension settles with
                                    the scene. `world` is the plugins' World (model, data, step, id(kind, ref), robot).
    before_step(world)              each control step, after Behaviour.control and the action were applied (ctrl set),
                                    before the physics substeps
    before_substep(world)           before each of the SUBSTEPS mj_step calls
    after_substep(world)            after each of them
    after_step(world)               after the substeps, before Goal.update and the state trace
    before_render(world, renderer)  before each image the backend renders (policy views, video), after the
                                    renderer's update_scene and before render; `renderer` is the mujoco.Renderer.
                                    For visual state only (e.g. uploading a deformed mesh into its GL context)
    trace_state(world) -> dict|None JSON-able state recorded in every state-trace record under the extension's key
                                    (None: nothing this record). Must only read.
    summary() -> dict               researcher-only, added to the session summary under `extensions.<key>`
    close()                         at the end of the episode

The control-step order is therefore: Behaviour.control, the action, before_step, (before_substep, mj_step,
after_substep) x SUBSTEPS, after_step, Goal.update, the trace. Reset settling steps run the same hooks (step not
counted). An exception in any hook is an infrastructure error: the episode ends as `infrastructure_error` and the
policy only sees "an internal error occurred". Extensions may write `data` (they are physics); Goal plugins may not.
Nothing an extension returns is shown to the policy. Plugins reach the constructed extensions read-only as
`world.extensions[key]` (e.g. a goal reading liquid volumes through the extension's query methods).

Interpreter: an extension may need a particular Python (liquid's pinned solver is cp312 only); run the household
simulation with ROBOUSE_HOUSEHOLD_PYTHON set to that interpreter (or a wrapper that execs it). The worker imports
robouse from the episode server's source tree, so that interpreter needs only the simulator's dependencies (numpy,
mujoco, Pillow and the extension's own).
"""

from __future__ import annotations

import importlib

EXTENSIONS: dict[str, str] = {
    "liquid": "robouse.backends.household.liquid:Extension",
}
HOOKS = ("before_step", "before_substep", "after_substep", "after_step", "before_render")


def load_class(key: str):
    """The extension class registered for `key`, or None when its module is not available."""
    entry = EXTENSIONS.get(key)
    if entry is None:
        return None
    mod, cls = entry.split(":")
    try:
        return getattr(importlib.import_module(mod), cls)
    except (ImportError, AttributeError):
        return None


class Active:
    """One constructed extension and its bound hooks (None when the class does not define one)."""

    def __init__(self, key: str, obj):
        self.key, self.obj = key, obj
        for h in (*HOOKS, "trace_state", "summary", "close"):
            fn = getattr(obj, h, None)
            setattr(self, h, fn if callable(fn) else None)
