"""Private mesh-contact queries and finite-capacity absorption (liquid contract 0.2).

Absorption transfers resolved liquid particles to a separately accounted reservoir.
It is a contact/capacity abstraction, not a textile capillarity or evaporation model.
"""

from __future__ import annotations

import numpy as np


def triangle_distance(tri, points):
    """Distance to each corresponding triangle: plane projection or nearest edge."""
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    ab, ac, ap = b - a, c - a, points - a
    dot = lambda x, y: np.einsum('ij,ij->i', x, y)
    d00, d01, d11 = dot(ab, ab), dot(ab, ac), dot(ac, ac)
    d20, d21 = dot(ap, ab), dot(ap, ac)
    denom = d00 * d11 - d01 * d01
    valid = denom > 1e-30
    u = (d11 * d20 - d01 * d21) / np.where(valid, denom, 1)
    v = (d00 * d21 - d01 * d20) / np.where(valid, denom, 1)
    projection = a + u[:, None] * ab + v[:, None] * ac
    interior = valid & (u >= 0) & (v >= 0) & (u + v <= 1)
    dist = np.where(interior, np.linalg.norm(points - projection, axis=1), np.inf)
    for start, end in ((a, b), (b, c), (c, a)):
        edge = end - start
        t = np.clip(dot(points - start, edge) / np.maximum(dot(edge, edge), 1e-30), 0, 1)
        dist = np.minimum(dist, np.linalg.norm(points - start - t[:, None] * edge, axis=1))
    return dist


class MeshContact:
    """Exact point-to-triangle distances after a conservative KD-tree broad phase.

    The mesh and query poses share the boundary body's frame. Hollow containers
    remain hollow; a bounding box or convex hull never stands in for their mesh.
    """

    def __init__(self, vertices, faces):
        from scipy.spatial import cKDTree

        self.tri = np.asarray(vertices, float)[np.asarray(faces, int)]
        if not len(self.tri) or not np.isfinite(self.tri).all():
            raise ValueError("contact mesh must contain finite triangles")
        centres = self.tri.mean(1)
        self.radius = float(np.linalg.norm(self.tri - centres[:, None, :], axis=2).max())
        self.tree = cKDTree(centres)
        self.lo = self.tri.min(axis=(0, 1))
        self.hi = self.tri.max(axis=(0, 1))

    def within(self, points, pos, rotation, distance):
        if distance < 0 or not np.isfinite(distance):
            raise ValueError("contact distance must be finite and nonnegative")
        x = (np.asarray(points, float) - np.asarray(pos)) @ np.asarray(rotation)
        if not np.isfinite(x).all():
            raise FloatingPointError("nonfinite liquid in contact query")
        result = np.zeros(len(x), bool)
        ids = np.flatnonzero(np.all((x >= self.lo - distance) & (x <= self.hi + distance), axis=1))
        # Chunking limits allocations for detailed meshes and large wet areas.
        for start in range(0, len(ids), 128):
            ix = ids[start : start + 128]
            candidates = self.tree.query_ball_point(x[ix], self.radius + distance + 1e-12)
            counts = np.asarray([len(c) for c in candidates])
            if not counts.sum():
                continue
            rows = np.repeat(ix, counts)
            tris = self.tri[np.concatenate(candidates).astype(int)]
            hit = triangle_distance(tris, x[rows]) <= distance + 1e-12
            result[rows[hit]] = True
        return result


class Absorber:
    """Absorbs only particles touching its mesh, up to capacity; no remote clearing."""

    def __init__(self, name, mesh, capacity_ml, contact_m):
        if not np.isfinite([capacity_ml, contact_m]).all() or capacity_ml <= 0 or contact_m < 0:
            raise ValueError("absorber needs a positive finite capacity and nonnegative contact distance")
        self.name, self.mesh = name, mesh
        self.capacity_ml, self.contact_m = float(capacity_ml), float(contact_m)
        self.reset()

    def reset(self):
        self.particles = 0
        self.contacts = 0

    def update(self, fluid, pos, rotation):
        ml = fluid.params.particle_volume * 1e6
        remaining = int(np.floor(self.capacity_ml / ml + 1e-9)) - self.particles
        if remaining <= 0:
            return 0
        ids = np.flatnonzero(fluid.free_mask)
        hit = self.mesh.within(fluid.positions()[ids], pos, rotation, self.contact_m)
        chosen = ids[hit][:remaining]
        if len(chosen):
            fluid.absorb(chosen, self.name)
            self.particles += len(chosen)
            self.contacts += 1
        return len(chosen)

    def update_poses(self, fluid, poses):
        """Uptake at the boundary poses {name: (pos, R, ...)}; the coupling and substep paths call this."""
        pos, rotation = poses[self.name][:2]
        return self.update(fluid, pos, rotation)

    def pose_names(self):
        return (self.name,)

    def report(self, particle_volume):
        return {
            "absorbed_ml": self.particles * particle_volume * 1e6,
            "capacity_ml": self.capacity_ml,
            "contact_updates": self.contacts,
        }


class PatchAbsorber(Absorber):
    """One finite reservoir whose contact geometry is several rigid patch meshes (contract 0.6.0 flex cloth).

    The capacity is shared by the whole cloth, not divided between patches. A free particle within `contact_m` of
    any patch is absorbed (lowest particle ids first, as `Absorber`). The patch split is attribution only: each
    absorbed particle counts for the first patch, in fixed order, that touched it.
    """

    def __init__(self, name, patch_meshes: dict, capacity_ml, contact_m):
        if not patch_meshes:
            raise ValueError("a patch absorber needs at least one patch mesh")
        self.patches = list(patch_meshes)
        self.patch_meshes = dict(patch_meshes)
        super().__init__(name, None, capacity_ml, contact_m)

    def reset(self):
        super().reset()
        self.by_patch = {p: 0 for p in getattr(self, "patches", [])}

    def pose_names(self):
        return tuple(self.patches)

    def update(self, fluid, pos, rotation):
        raise TypeError("a patch absorber needs every patch pose: call update_poses")

    def update_poses(self, fluid, poses):
        ml = fluid.params.particle_volume * 1e6
        remaining = int(np.floor(self.capacity_ml / ml + 1e-9)) - self.particles
        if remaining <= 0:
            return 0
        ids = np.flatnonzero(fluid.free_mask)
        x = fluid.positions()[ids]
        first = np.full(len(ids), -1)
        for k, name in enumerate(self.patches):
            pos, rotation = poses[name][:2]
            open_ = first < 0
            if not open_.any():
                break
            hit = np.zeros(len(ids), bool)
            hit[open_] = self.patch_meshes[name].within(x[open_], pos, rotation, self.contact_m)
            first[hit] = k
        touched = np.flatnonzero(first >= 0)[:remaining]
        chosen = ids[touched]
        if len(chosen):
            fluid.absorb(chosen, self.name)
            self.particles += len(chosen)
            self.contacts += 1
            for k in first[touched]:
                self.by_patch[self.patches[int(k)]] += 1
        return len(chosen)

    def report(self, particle_volume):
        out = super().report(particle_volume)
        out["patches"] = len(self.patches)
        out["by_patch_ml"] = {p: n * particle_volume * 1e6 for p, n in self.by_patch.items() if n}
        return out


class PuddleSleep:
    """Explicit, deterministic freeze-until-disturbed approximation for initial puddles.

    It wakes permanently when a moving boundary touches the liquid's neighbourhood.
    No automatic re-freezing masks continuing flow. Frozen states must be authored
    as resting supported puddles, never as airborne particles or container fills.
    """

    def __init__(self, meshes, poses, spacing, motion_m=1e-6):
        self.meshes = meshes
        self.initial = {k: (p.copy(), R.copy()) for k, (p, R) in poses.items()}
        self.spacing, self.motion_m = spacing, motion_m
        self.reset()

    def reset(self):
        self.sleeping = True
        self.wake_time = None
        self.wake_body = None

    def update(self, fluid, poses):
        if not self.sleeping:
            return
        for name, (pos, R) in poses.items():
            p0, R0 = self.initial[name]
            extent = max(np.linalg.norm(self.meshes[name].hi), np.linalg.norm(self.meshes[name].lo))
            movement = np.linalg.norm(pos - p0) + extent * np.linalg.norm(R - R0)
            if movement <= self.motion_m:
                continue
            if self.meshes[name].within(fluid.positions()[fluid.free_mask], pos, R, 2 * self.spacing).any():
                self.sleeping = False
                self.wake_time, self.wake_body = fluid.time, name
                return


class ContainerSleep(PuddleSleep):
    """Opt-in initial rest for an entirely contained fill; permanent wake on motion.

    Moving any owning container wakes the solver even when the wall is farther
    than the contact band from the liquid. Other nearby moving boundaries also
    wake it. This does not freeze a spill or re-freeze an active pour.
    """

    def __init__(self, meshes, poses, spacing, owners, motion_m=1e-5):
        super().__init__(meshes, poses, spacing, motion_m)
        self.owners = frozenset(owners)
        if not self.owners or not self.owners <= set(poses):
            raise ValueError("container sleep requires known owning containers")

    def update(self, fluid, poses):
        if not self.sleeping:
            return
        for name in self.owners:
            pos, R = poses[name]
            p0, R0 = self.initial[name]
            extent = max(np.linalg.norm(self.meshes[name].hi), np.linalg.norm(self.meshes[name].lo))
            if np.linalg.norm(pos - p0) + extent * np.linalg.norm(R - R0) > self.motion_m:
                self.sleeping = False
                self.wake_time, self.wake_body = fluid.time, name
                return
        super().update(fluid, poses)
