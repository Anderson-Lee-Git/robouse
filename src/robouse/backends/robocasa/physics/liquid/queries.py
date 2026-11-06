"""Where the liquid is: particle-state queries for monitors, goals and physics checks (researcher-side only; a policy
never receives any of this).

All functions take particle positions (N, 3) in the world frame (`SPHFluid.positions()`) and return counts, volumes
in millilitres and lengths in metres. A particle stands for `particle_volume` m^3 of liquid ((2r)^3).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

ML = 1e6  # m^3 -> ml


@dataclass
class Container:
    """The inside of an open, axially symmetric container in its body frame: `profile` lists (inner radius, z) from
    the floor up to the rim, z increasing (a straight tumbler: [(r_floor, z_floor), (r_rim, z_rim)]; a bottle adds
    shoulder and neck points). A particle is inside when its height lies between the floor and the rim and its
    distance from the axis is within the radius at that height (plus `slack`, for particles touching the wall)."""

    body: str
    profile: list
    slack: float = 0.0

    def radius_at(self, z):
        prof = np.asarray(self.profile, float)
        return np.interp(z, prof[:, 1], prof[:, 0])

    @property
    def floor(self) -> float:
        return float(self.profile[0][1])

    @property
    def rim(self) -> float:
        return float(self.profile[-1][1])

    def inside(self, x, pos, R) -> np.ndarray:
        """Mask of particles inside, for the container's body at world pose (pos, R)."""
        local = (np.asarray(x, float) - np.asarray(pos, float)) @ np.asarray(R, float)
        z = local[:, 2]
        r = np.hypot(local[:, 0], local[:, 1])
        return (z >= self.floor - self.slack) & (z <= self.rim) & (r <= self.radius_at(z) + self.slack)

    def capacity_ml(self) -> float:
        prof = np.asarray(self.profile, float)
        r, z = prof[:, 0], prof[:, 1]
        # frustum segments
        return float(sum(np.pi * (z[i + 1] - z[i]) * (r[i] ** 2 + r[i] * r[i + 1] + r[i + 1] ** 2) / 3
                         for i in range(len(r) - 1)) * ML)


@dataclass
class Surface:
    """A horizontal work surface (a counter top) at world height z, over the rectangle `xy_min`..`xy_max`."""

    z: float
    xy_min: tuple = (-np.inf, -np.inf)
    xy_max: tuple = (np.inf, np.inf)
    rects: list | None = None  # optional union of (centre_xy, rotation_2x2, half_extent_xy)

    def over(self, x) -> np.ndarray:
        x = np.asarray(x, float)
        lo, hi = np.asarray(self.xy_min, float), np.asarray(self.xy_max, float)
        within = np.all((x[:, :2] >= lo) & (x[:, :2] <= hi), axis=1)
        if self.rects is not None:
            supported = np.zeros(len(x), bool)
            for c, R, h in self.rects:
                supported |= np.all(np.abs((x[:, :2] - c) @ R) <= np.asarray(h) + 1e-9, axis=1)
            within &= supported
        return within


def finite(x) -> np.ndarray:
    return np.all(np.isfinite(np.asarray(x, float)), axis=1)


def on_surface(x, surface: Surface, particle_radius: float, film: float = 0.02) -> np.ndarray:
    """Mask of particles resting on the surface: over it and within `film` metres above its top (a puddle, a film,
    drops). Particles in a container standing on the surface also match; subtract those masks (see `partition`)."""
    x = np.asarray(x, float)
    h = x[:, 2] - surface.z
    return surface.over(x) & (h >= -particle_radius) & (h <= film)


def below_surface(x, surface: Surface, particle_radius: float) -> np.ndarray:
    """Particles that went through the surface (more than one radius under its top while over it): a leak."""
    x = np.asarray(x, float)
    return surface.over(x) & (x[:, 2] < surface.z - 2 * particle_radius)


def partition(x, containers: dict, poses: dict, surface: Surface | None, particle_radius: float,
              film: float = 0.02) -> dict:
    """Disjoint labels per particle: each container's name, "surface" (on the counter, outside every container),
    "below" (through the counter), "nonfinite", and "elsewhere" (in flight, on the floor, on other things).
    `containers` {name: Container}, `poses` {name: (pos, R)} of each container's body."""
    x = np.asarray(x, float)
    n = len(x)
    label = np.full(n, "elsewhere", dtype=object)
    ok = finite(x)
    label[~ok] = "nonfinite"
    free = ok.copy()
    for name, c in containers.items():
        pos, R = poses[name]
        m = free & c.inside(np.where(ok[:, None], x, 0.0), pos, R)
        label[m] = name
        free &= ~m
    if surface is not None:
        xs = np.where(ok[:, None], x, 0.0)
        b = free & below_surface(xs, surface, particle_radius)
        label[b] = "below"
        free &= ~b
        s = free & on_surface(xs, surface, particle_radius, film)
        label[s] = "surface"
    return label


def volumes_ml(label, particle_volume: float) -> dict:
    names, counts = np.unique(np.asarray(label, dtype=str), return_counts=True)
    return {str(k): float(c) * particle_volume * ML for k, c in zip(names, counts)}


def puddle(x, mask, particle_radius: float, cell: float | None = None, surface_z: float | None = None) -> dict:
    """Extent of the liquid in `mask` (e.g. on the counter) seen from above: covered area (occupied grid cells of
    size `cell`, default 2 particle spacings), the bounding box, the largest connected patch, and how thick it is
    above the surface (95th percentile height of particle centres, plus a radius)."""
    x = np.asarray(x, float)[np.asarray(mask, bool)]
    out = {"particles": int(len(x)), "area_m2": 0.0, "largest_patch_m2": 0.0, "bbox_xy": None, "thickness_m": 0.0,
           "centroid_xy": None}
    if not len(x):
        return out
    cell = cell or 4 * particle_radius
    ij = np.floor(x[:, :2] / cell).astype(np.int64)
    occ = {tuple(v) for v in ij}
    out["area_m2"] = len(occ) * cell * cell
    out["bbox_xy"] = [float(v) for v in (*x[:, :2].min(0), *x[:, :2].max(0))]
    out["centroid_xy"] = [float(v) for v in x[:, :2].mean(0)]
    # largest 8-connected patch
    seen, best = set(), 0
    for c in occ:
        if c in seen:
            continue
        stack, size = [c], 0
        seen.add(c)
        while stack:
            a, b = stack.pop()
            size += 1
            for da in (-1, 0, 1):
                for db in (-1, 0, 1):
                    nb = (a + da, b + db)
                    if nb in occ and nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
        best = max(best, size)
    out["largest_patch_m2"] = best * cell * cell
    if surface_z is not None:
        out["thickness_m"] = float(np.percentile(x[:, 2] - surface_z, 95) + particle_radius)
    return out
