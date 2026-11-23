"""The liquid's physical domain: explicit static collision boxes of the compiled scene (room floor, walls, counter
slabs, shelves) with continuous swept contact, and the validity guards that keep liquid out of solid material.

Akinci boundary samples supply SPH pressure and friction; this geometric layer enforces impermeability of the
declared static solids, including their finite sides and the floor. A contact removes only the inward normal
velocity (zero restitution, no added tangential damping); particles and their volume are kept. Nothing invents an
enclosing grid: a domain is only what the package names.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SOLID_TOLERANCE_M = 2e-6  # a free particle centre deeper than this inside a static box is invalid
CONTACT_OFFSET_M = 1e-6  # outward offset of a resolved contact (float32 world positions)


class LiquidValidityError(RuntimeError):
    """A failed physical or numerical liquid state: an infrastructure error, never a task outcome."""


@dataclass
class SolidBox:
    name: str
    centre: np.ndarray
    rotation: np.ndarray
    half: np.ndarray

    def __post_init__(self):
        self.centre = np.asarray(self.centre, float)
        self.rotation = np.asarray(self.rotation, float).reshape(3, 3)
        self.half = np.asarray(self.half, float)
        if (
            self.centre.shape != (3,)
            or self.half.shape != (3,)
            or not np.isfinite(self.centre).all()
            or not np.isfinite(self.rotation).all()
            or not np.isfinite(self.half).all()
            or np.any(self.half <= 0)
            or not np.allclose(self.rotation.T @ self.rotation, np.eye(3), atol=1e-8)
        ):
            raise ValueError("invalid static solid box")
        extent = np.abs(self.rotation) @ self.half
        self.lo, self.hi = self.centre - extent, self.centre + extent

    def intersect(self, start, end, radius):
        """Swept point against the radius-expanded box (conservative at rounded edges): (hit, t, world normal)."""
        a = (start - self.centre) @ self.rotation
        b = (end - self.centre) @ self.rotation
        delta = b - a
        h = self.half + radius
        depth = self.half - np.abs(a)
        if np.any(np.all(depth > SOLID_TOLERANCE_M, axis=1)):
            raise LiquidValidityError("a particle starts inside a static solid")
        parallel = np.abs(delta) < 1e-15
        inv = np.divide(1.0, delta, out=np.zeros_like(delta), where=~parallel)
        t0 = (-h - a) * inv
        t1 = (h - a) * inv
        enter = np.where(parallel, -np.inf, np.minimum(t0, t1))
        leave = np.where(parallel, np.inf, np.maximum(t0, t1))
        t_enter = enter.max(1)
        t_leave = leave.min(1)
        hit = (t_enter >= -1e-7) & (t_enter <= 1) & (t_leave >= np.maximum(t_enter, 0))
        hit &= ~np.any(parallel & (np.abs(a) > h), axis=1)
        rows = np.arange(len(a))
        axes = enter.argmax(1)
        normal = np.zeros_like(a)
        normal[rows, axes] = -np.sign(delta[rows, axes])
        shell = np.all(np.abs(a) < h, axis=1)
        if shell.any():
            axes_shell = (h - np.abs(a)).argmin(1)
            ns = np.zeros_like(a)
            ns[rows, axes_shell] = np.where(a[rows, axes_shell] >= 0, 1.0, -1.0)
            inward = np.einsum("ij,ij->i", delta, ns) < 0
            hit |= shell & inward
            normal[shell & inward] = ns[shell & inward]
            t_enter[shell & inward] = 0
        return hit, np.maximum(t_enter, 0), normal @ self.rotation.T


class StaticDomain:
    def __init__(self, boxes, radius, floor_name: str):
        self.boxes = list(boxes)
        self.radius = float(radius)
        self.contacts: dict[str, int] = {}
        if not self.boxes or not np.isfinite(radius) or radius <= 0:
            raise ValueError("a liquid domain needs static boxes and a positive radius")
        self.floor = next((b for b in self.boxes if b.name == floor_name), None)
        if self.floor is None or not np.allclose(self.floor.rotation[:, 2], [0, 0, 1], atol=1e-8):
            raise ValueError("the floor geom must be a horizontal box of the domain")

    def validate(self, points) -> None:
        """Raise when a point lies inside a static box or outside the floor's footprint (one radius of reach) or
        below the floor top."""
        points = np.asarray(points, float)
        if not len(points):
            return
        lo, hi = points.min(0), points.max(0)
        for box in self.boxes:
            if np.any(hi < box.lo) or np.any(lo > box.hi):
                continue
            ids = np.flatnonzero(np.all(points >= box.lo, axis=1) & np.all(points <= box.hi, axis=1))
            local = (points[ids] - box.centre) @ box.rotation
            if np.any(np.all(box.half - np.abs(local) > SOLID_TOLERANCE_M, axis=1)):
                raise LiquidValidityError(f"free liquid inside static solid {box.name}")
        f = self.floor
        local = (points - f.centre) @ f.rotation
        if np.any(np.abs(local[:, :2]) > f.half[:2] + self.radius):
            raise LiquidValidityError("free liquid left the floor's footprint")
        if np.any(local[:, 2] < f.half[2] - SOLID_TOLERANCE_M):
            raise LiquidValidityError("free liquid passed below the floor")

    def resolve(self, start, end, velocity):
        """Continuous contact of the motion start -> end with every box (up to four sequential contacts per step)."""
        start = np.asarray(start, float).copy()
        end = np.asarray(end, float).copy()
        velocity = np.asarray(velocity, float).copy()
        for _ in range(4):
            if not len(start):
                return end, velocity
            first = np.full(len(start), np.inf)
            normals = np.zeros_like(start)
            owner = np.full(len(start), -1, int)
            swept_lo, swept_hi = np.minimum(start, end), np.maximum(start, end)
            cloud_lo, cloud_hi = swept_lo.min(0), swept_hi.max(0)
            for k, box in enumerate(self.boxes):
                lo = box.lo - self.radius
                hi = box.hi + self.radius
                if np.any(cloud_hi < lo) or np.any(cloud_lo > hi):
                    continue
                ix = np.flatnonzero(np.all(swept_hi >= lo, axis=1) & np.all(swept_lo <= hi, axis=1))
                if not len(ix):
                    continue
                hit, t, n = box.intersect(start[ix], end[ix], self.radius)
                update = hit & (t < first[ix])
                ids = ix[update]
                first[ids] = t[update]
                normals[ids] = n[update]
                owner[ids] = k
            ids = np.flatnonzero(owner >= 0)
            if not len(ids):
                return end, velocity
            n = normals[ids]
            contact = start[ids] + first[ids, None] * (end[ids] - start[ids])
            remaining = end[ids] - contact
            remaining -= np.minimum(np.einsum("ij,ij->i", remaining, n), 0)[:, None] * n
            contact += CONTACT_OFFSET_M * n
            end[ids] = contact + remaining
            start[ids] = contact
            vn = np.einsum("ij,ij->i", velocity[ids], n)
            velocity[ids] -= np.minimum(vn, 0)[:, None] * n
            for k, count in zip(*np.unique(owner[ids], return_counts=True), strict=True):
                name = self.boxes[k].name
                self.contacts[name] = self.contacts.get(name, 0) + int(count)
        raise LiquidValidityError("unresolved multiple static contacts in one SPH step")


def make_domain(model, data, names: list[str], floor: str, radius: float) -> StaticDomain:
    """The domain of the named compiled collision boxes, which must not move (no joint above them)."""
    import mujoco

    boxes = []
    for name in names:
        gid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, name)
        if gid < 0 or model.geom_type[gid] != mujoco.mjtGeom.mjGEOM_BOX:
            raise ValueError(f"liquid domain geom {name!r} must be an existing box")
        if not (model.geom_contype[gid] or model.geom_conaffinity[gid]):
            raise ValueError(f"liquid domain geom {name!r} is visual only")
        b = int(model.geom_bodyid[gid])
        while b:
            if model.body_jntnum[b] or model.body_mocapid[b] >= 0:
                raise ValueError(f"liquid domain geom {name!r} can move")
            b = int(model.body_parentid[b])
        boxes.append(
            SolidBox(name, np.array(data.geom_xpos[gid]), np.array(data.geom_xmat[gid]), np.array(model.geom_size[gid]))
        )
    return StaticDomain(boxes, radius, floor)
