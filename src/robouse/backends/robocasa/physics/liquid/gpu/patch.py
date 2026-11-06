"""Swap the GPU solver into the unchanged liquid package for one process.

`liquid.scene.attach` instantiates `liquid.solver.SPHFluid`; a scene builder's physics checks may too. Replacing
that module attribute (and nothing else) lets every caller - the robouse worker, the physics checks, the reference routes - run
on `WarpFluid` without editing the liquid package. The native backend selection in a scene's config is ignored and
recorded under `backend["requested"]` instead. A cleaner hook is proposed in the P2-G report (a backend registry
keyed by `cfg["native_backend"]["id"]`), which Astra's package owner would add.
"""
from __future__ import annotations

from .. import solver as cpu_solver
from .solver import WarpFluid

_ORIGINAL = cpu_solver.SPHFluid


def install():
    cpu_solver.SPHFluid = WarpFluid
    return WarpFluid


def uninstall():
    cpu_solver.SPHFluid = _ORIGINAL
