"""Continuous static-solid contact for opt-in liquid contract 0.4.0."""

from dataclasses import dataclass

import numpy as np


class LiquidValidityError(RuntimeError):
    """A failed physical/numerical state; never a task outcome."""


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
            raise ValueError('invalid physical solid box')
        extent = np.abs(self.rotation) @ self.half
        self.lo, self.hi = self.centre - extent, self.centre + extent

    def intersect(self, start, end, radius):
        """Swept point against radius-expanded box; conservative at rounded edges.

        The expansion is the same resolved particle radius used by SPH. No
        fictitious planes span the physical box's sides or open gaps.
        """
        a = (start - self.centre) @ self.rotation
        b = (end - self.centre) @ self.rotation
        delta = b - a
        h = self.half + radius
        # A native wall layer may already overlap the geometric radius shell.
        # A centre inside real material is an invalid initial state, not something
        # to teleport to whichever side happens to be closest.
        depth = self.half - np.abs(a)
        if np.any(np.all(depth > 2e-6, axis=1)):
            raise LiquidValidityError('particle starts inside a static solid')
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
        axes = enter.argmax(1)
        normal = np.zeros_like(a)
        normal[np.arange(len(a)), axes] = -np.sign(delta[np.arange(len(a)), axes])
        shell = np.all(np.abs(a) < h, axis=1)
        if shell.any():
            axes_shell = (h - np.abs(a)).argmin(1)
            ns = np.zeros_like(a)
            ns[np.arange(len(a)), axes_shell] = np.where(a[np.arange(len(a)), axes_shell] >= 0, 1.0, -1.0)
            inward = np.einsum('ij,ij->i', delta, ns) < 0
            hit |= shell & inward
            normal[shell & inward] = ns[shell & inward]
            t_enter[shell & inward] = 0
        return hit, np.maximum(t_enter, 0), normal @ self.rotation.T


class StaticDomain:
    """One-way continuous contact with explicit compiled static collision boxes.

    Akinci boundaries still supply SPH pressure/friction. This geometric layer
    enforces impermeability on physical solids, including their finite sides
    and the floor. Contacts remove only inward normal velocity (zero restitution,
    no added tangential damping); particles and their volumes are retained.
    """

    def __init__(self, boxes, radius):
        self.boxes = list(boxes)
        self.radius = float(radius)
        self.contacts = {}
        if not self.boxes or not np.isfinite(radius) or radius <= 0:
            raise ValueError('domain requires solids and a positive radius')

    def validate(self, points):
        points = np.asarray(points, float)
        if not len(points):
            return
        lo, hi = points.min(0), points.max(0)
        for box in self.boxes:
            if np.any(hi < box.lo) or np.any(lo > box.hi):
                continue
            ids = np.flatnonzero(np.all(points >= box.lo, axis=1) & np.all(points <= box.hi, axis=1))
            local = (points[ids] - box.centre) @ box.rotation
            if np.any(np.all(box.half - np.abs(local) > 2e-6, axis=1)):
                raise LiquidValidityError('free particle inside a static solid')

    def resolve(self, start, end, velocity):
        start = np.asarray(start, float).copy()
        end = np.asarray(end, float).copy()
        velocity = np.asarray(velocity, float).copy()
        # Broad phase against swept whole-cloud bounds, then per-particle AABBs.
        for _ in range(4):
            first = np.full(len(start), np.inf)
            normals = np.zeros_like(start)
            owner = np.full(len(start), -1, int)
            swept_lo, swept_hi = np.minimum(start, end), np.maximum(start, end)
            if not len(start):
                return end, velocity
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
            remaining -= np.minimum(np.einsum('ij,ij->i', remaining, n), 0)[:, None] * n
            # Float32 world positions need micrometre-scale outward roundoff allowance.
            contact += 1e-6 * n
            end[ids] = contact + remaining
            start[ids] = contact
            vn = np.einsum('ij,ij->i', velocity[ids], n)
            velocity[ids] -= np.minimum(vn, 0)[:, None] * n
            for k, count in zip(*np.unique(owner[ids], return_counts=True), strict=True):
                name = self.boxes[k].name
                self.contacts[name] = self.contacts.get(name, 0) + int(count)
        raise LiquidValidityError('unresolved multiple solid contacts in one SPH step')


def make_domain(env, config, radius):
    """Resolve explicit physical geometry names; never invent an enclosing grid."""
    import mujoco

    model = env.sim.model._model
    data = env.sim.data
    names = config['static_box_geoms']
    if not isinstance(names, list) or not names or len(set(names)) != len(names):
        raise ValueError('static_box_geoms must be a nonempty unique name list')
    boxes = []
    for name in names:
        gid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, name)
        if gid < 0 or model.geom_type[gid] != mujoco.mjtGeom.mjGEOM_BOX:
            raise ValueError(f'liquid domain requires an existing collision box: {name}')
        if not (model.geom_contype[gid] or model.geom_conaffinity[gid]):
            raise ValueError(f'liquid domain geom is visual only: {name}')
        bid = int(model.geom_bodyid[gid])
        while bid:
            if model.body_jntnum[bid]:
                raise ValueError(f'liquid domain geom moves: {name}')
            bid = int(model.body_parentid[bid])
        boxes.append(
            SolidBox(name, np.array(data.geom_xpos[gid]), np.array(data.geom_xmat[gid]), np.array(model.geom_size[gid]))
        )
    domain = StaticDomain(boxes, radius)
    floor = next((b for b in boxes if b.name == config['floor_geom']), None)
    if floor is None or not np.allclose(floor.rotation[:, 2], [0, 0, 1], atol=1e-8):
        raise ValueError('floor_geom must name a selected horizontal physical box')
    domain.floor = floor
    return domain
