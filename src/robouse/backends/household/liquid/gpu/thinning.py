"""Household boundary-sample thinning for the GPU liquid backend `warp-1.19.0-dfsph-cuda-f32-v2`.

The vendored `sampling.regular_triangle_sampling` (SPlisHSPlasH's RegularTriangleSampling) samples every vertex, every
edge and every face of a mesh independently. Where many thin triangles meet (the pole of a revolved vessel, where a
ring of coincident vertices and zero-length edges closes the floor) it stacks samples on the same point: a fluid
particle just above a bottle floor sees 339-435 boundary samples within its support, against a p99 of about 52, and
overflows the fixed 128-neighbour boundary list. Away from poles the per-element sampling is also denser than the
configured spacing (median nearest-neighbour distance about 0.4 x spacing).

`thin_samples` keeps a deterministic minimum-distance (Poisson-disc style) subset of one body's samples, in the
vendored order (vertices, then edge samples, then face samples): a sample is kept when no already kept sample of the
same body lies closer than `min_distance`. This works across triangle boundaries and collapses stacked samples to one.
`ThinnedWarpFluid` is `solver.WarpFluid` with its mesh-sampled boundaries thinned at
`boundary_min_spacing` x (1.5 x particle radius), the fraction pinned in the backend descriptor. Boundaries that bring
their own samples (the work-surface plate grid) are used as given. The Warp kernels, the vendored sampler and
`solver.py` are unchanged; Akinci boundary volumes are computed from the thinned samples as from any other set.
"""

from __future__ import annotations

import numpy as np

from ..solver import BoundaryMesh, pin
from .sampling import regular_triangle_sampling
from .solver import WarpFluid

_NB = np.array([(i, j, k) for i in (-1, 0, 1) for j in (-1, 0, 1) for k in (-1, 0, 1)], np.int64)


def thin_samples(samples: np.ndarray, min_distance: float) -> np.ndarray:
    """The greedy minimum-distance subset of `samples` (N, 3), in input order: sample i is kept when every kept sample
    before it is at least `min_distance` away. Deterministic; no two kept samples are closer than `min_distance`, and
    every dropped sample has a kept one within `min_distance`."""
    x = np.asarray(samples, np.float64)
    d = float(min_distance)
    if x.ndim != 2 or x.shape[1] != 3 or not len(x):
        return x.reshape(-1, 3)
    if not d > 0:
        raise ValueError("thin_samples needs a positive min_distance")
    d2 = d * d
    cells = np.floor((x - x.min(axis=0)) / d).astype(np.int64)
    grid: dict[tuple[int, int, int], list[int]] = {}
    keep = np.zeros(len(x), bool)
    pts = x.tolist()
    for i, c in enumerate(cells.tolist()):
        px, py, pz = pts[i]
        ok = True
        for ox, oy, oz in _NB.tolist():
            for j in grid.get((c[0] + ox, c[1] + oy, c[2] + oz), ()):
                qx, qy, qz = pts[j]
                if (px - qx) ** 2 + (py - qy) ** 2 + (pz - qz) ** 2 < d2:
                    ok = False
                    break
            if not ok:
                break
        if ok:
            keep[i] = True
            grid.setdefault((c[0], c[1], c[2]), []).append(i)
    return x[keep]


def thinned_boundary_samples(b: BoundaryMesh, particle_radius: float, fraction: float) -> np.ndarray:
    """One mesh boundary's body-frame samples: the vendored sampling at 1.5 r, thinned at fraction x 1.5 r."""
    spacing = 1.5 * particle_radius
    return thin_samples(regular_triangle_sampling(b.vertices, b.faces, spacing), fraction * spacing)


class ThinnedWarpFluid(WarpFluid):
    """`WarpFluid` whose mesh-sampled boundaries are thinned (backend descriptors with `boundary_min_spacing`)."""

    def _build(self, boundaries, particles):
        frac = float(pin(self.backend["id"])["boundary_min_spacing"])
        r = self.mat.particle_radius
        out = []
        for b in boundaries:
            s = b.samples if b.samples is not None else thinned_boundary_samples(b, r, frac)
            out.append(BoundaryMesh(b.name, b.vertices, b.faces, b.pos, b.R, b.animated, samples=s))
        return super()._build(out, particles)


__all__ = ["ThinnedWarpFluid", "thin_samples", "thinned_boundary_samples"]
