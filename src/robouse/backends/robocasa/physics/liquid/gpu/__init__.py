"""GPU (NVIDIA Warp) prototype of the liquid contract 0.3.0 solver: DFSPH with Akinci boundaries, Weiler 2018
implicit viscosity and Jeske 2023 implicit surface tension, re-implemented from the SPlisHSPlasH 2.19.0 algorithms.

`solver.WarpFluid` has the interface of `liquid.solver.SPHFluid`, so `liquid.coupling`, `liquid.contact`,
`liquid.queries`, `liquid.surface` and `liquid.scene` run unchanged on it (`patch.install()` swaps the class in).
Researcher-only prototype (row P2-G); not adopted by any scene.
"""
