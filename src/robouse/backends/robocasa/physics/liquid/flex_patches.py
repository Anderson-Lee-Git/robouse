"""Liquid contract 0.6.0: piecewise-rigid patch boundaries and a shared absorber for a deformable flex cloth.

The one-way SPH coupling moves rigid boundary meshes (Akinci samples, absorber contact meshes, sleep checks). A
MuJoCo `dim=2` flex grid has no rigid body to follow, so 0.6.0 approximates it by a grid of rigid thin boxes
("patches"), each covering a block of flex cells. Before every query the patch takes the least-squares rigid pose
(Kabsch) of its block's current vertices relative to their layout at attach time, so it follows the cloth's
translation, rotation and the mean orientation of its block. Within a patch, bending and stretching are not
represented; at patch seams, a bent cloth leaves gaps or overlaps of order patch size x bend angle / 2. The fluid
still never acts on MuJoCo (no force on the cloth).

Uptake: one reservoir for the whole cloth (its declared capacity is unchanged, not divided per patch); a free
particle is absorbed when it lies within `contact_m` of any patch mesh. The per-patch split of absorbed particles
is reported (first touching patch in fixed patch order), not used as a capacity.

Contract 0.7.0 (continuous patch rotation; `FlexPatches(..., continuous=True)`): the 0.6.0 fit is a proper-rotation
Kabsch fit of a planar rest layout. Its third axis is unconstrained by planar points, so when a patch folds over (its
vertices' layout becomes mirrored) the best proper rotation can jump by up to pi between two MuJoCo steps, and the
coupling's finite-difference angular velocity (rotation increment / step) becomes non-physical (measured: 893 and
1385 rad/s on single towel patches of scene 8005 v6, liquid particles under 0.07 m/s). 0.7.0 makes the fit
well posed and continuous:
- the rest and current point sets are augmented with +-(patch size) along their oriented normals (rest: the cloth
  normal at attach; now: the area-weighted normal of the patch's triangles, oriented by the flex's vertex order), so
  the 3 x 3 cross-covariance has full rank and det(V U^T) is meaningful;
- a reflection (det < 0: the best orthogonal fit is a mirror image, a folded-over patch) is rejected, never forced
  into a proper rotation by flipping the third axis;
- a degenerate patch (reflection; second in-plane singular value below DEGENERATE_RATIO of the first, i.e. folded
  or collinear vertices; or oriented area below DEGENERATE_AREA of its rest area) holds its previous accepted
  rotation (its centroid still follows the vertices). Every degenerate fit is logged (time, patch, reason, ratios);
- the coupling's angular velocity is unchanged in form: the smallest-angle rotation increment between consecutive
  MuJoCo-step fits divided by the step (coupling.rotvec is the principal angle, <= pi), now between continuous fits.
No angular-velocity cap is applied.

Config (a liquid `boundaries` entry, contracts 0.6.0 and 0.7.0):
    "towel": {"object": "towel", "flex_patches": {"grid": [15, 11], "cells": [2, 2]}}
`grid` is the flexcomp point count (x-major vertex order, verified at attach), `cells` the flex cells per patch
along x and y (the cell counts must divide evenly). An absorber of the same name uses all of its patches.
"""

from __future__ import annotations

import numpy as np

from . import meshes

CONTRACT = "0.6.0"
CONTRACTS = ("0.6.0", "0.7.0")
CONTINUOUS_CONTRACT = "0.7.0"
DEGENERATE_RATIO = 0.25  # second / first in-plane singular value (a 2 x 2-cell patch at rest: ~1)
DEGENERATE_AREA = 0.25  # oriented area / rest area


def oriented_normal(x: np.ndarray, tris: np.ndarray) -> tuple[np.ndarray, float]:
    """Area-weighted unit normal of triangles `tris` (indices into `x`) and their signed-sum area vector's norm."""
    a, b, c = x[tris[:, 0]], x[tris[:, 1]], x[tris[:, 2]]
    n = 0.5 * np.cross(b - a, c - a).sum(axis=0)
    area = float(np.linalg.norm(n))
    return (n / area if area > 0 else np.zeros(3)), area


def kabsch_continuous(rest, now, rest_normal, now_normal, scale):
    """Orthogonal fit of `rest` (centred, K x 3) onto `now`, both augmented by +-scale along their oriented normals.
    Returns (centroid, R or None, info): R is None for a reflection or a degenerate in-plane layout."""
    c = now.mean(axis=0)
    p = np.vstack([rest, rest + scale * rest_normal, rest - scale * rest_normal])
    q0 = now - c
    q = np.vstack([q0, q0 + scale * now_normal, q0 - scale * now_normal])
    H = p.T @ q
    U, S, Vt = np.linalg.svd(H)
    det = float(np.linalg.det(Vt.T @ U.T))
    # in-plane spread of the current vertices (independent of the augmentation)
    s2 = np.linalg.svd(q0 - q0.mean(axis=0), compute_uv=False)
    ratio = float(s2[1] / s2[0]) if s2[0] > 0 else 0.0
    info = {"det": det, "ratio": ratio}
    if det < 0:
        return c, None, {**info, "reason": "reflection"}
    if ratio < DEGENERATE_RATIO:
        return c, None, {**info, "reason": "collinear_or_folded"}
    return c, Vt.T @ U.T, info


def kabsch(rest: np.ndarray, now: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Rigid (centroid, R) best mapping centred `rest` (K, 3) onto `now` (K, 3): now ~ R @ rest + centroid.
    `rest` is centred at the origin. Coplanar, non-collinear points determine R uniquely."""
    c = now.mean(axis=0)
    H = rest.T @ (now - c)
    U, _, Vt = np.linalg.svd(H)
    d = 1.0 if np.linalg.det(Vt.T @ U.T) >= 0 else -1.0
    R = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T
    return c, R


class FlexPatches:
    """Patches of one flex: names, body-frame meshes and current poses from `flexvert_xpos`."""

    def __init__(self, model, data, name: str, flex: int, grid, cells, continuous: bool = False):
        nx, ny = (int(v) for v in grid)
        self.continuous = bool(continuous)
        cx, cy = (int(v) for v in cells)
        self.name, self.flex = name, int(flex)
        self.adr, n = int(model.flex_vertadr[flex]), int(model.flex_vertnum[flex])
        self.n = n
        if int(model.flex_dim[flex]) != 2:
            raise ValueError(f"flex patches need a 2D flex ({name!r})")
        if nx * ny != n or nx < 2 or ny < 2:
            raise ValueError(f"flex {name!r} has {n} vertices, not a {nx} x {ny} grid")
        if cx < 1 or cy < 1 or (nx - 1) % cx or (ny - 1) % cy:
            raise ValueError(f"patch cells {cells} must divide the {nx - 1} x {ny - 1} flex cells evenly")
        self.radius = float(model.flex_radius[flex])
        x = self.vertices(data)
        if not np.isfinite(x).all():
            raise FloatingPointError("nonfinite flex vertices")
        # grid order check: x-major (index = ix * ny + iy), neighbours one spacing apart at attach
        g = x.reshape(nx, ny, 3)
        ex, ey = g[1:, :, :] - g[:-1, :, :], g[:, 1:, :] - g[:, :-1, :]
        lx, ly = np.linalg.norm(ex, axis=2), np.linalg.norm(ey, axis=2)
        if lx.min() <= 0 or ly.min() <= 0 or lx.max() > 1.5 * np.median(lx) or ly.max() > 1.5 * np.median(ly):
            raise ValueError(f"flex {name!r} vertices are not an ordered {nx} x {ny} grid at attach")
        # the cloth frame at attach: in-plane axes along the grid, normal by right hand
        ax = (g[-1, :, :] - g[0, :, :]).mean(axis=0)
        ax /= np.linalg.norm(ax)
        ay = (g[:, -1, :] - g[:, 0, :]).mean(axis=0)
        ay -= ax * (ax @ ay)
        ay /= np.linalg.norm(ay)
        frame = np.stack([ax, ay, np.cross(ax, ay)], axis=1)
        self.names, self.index, self.rest, self.meshes = [], [], [], []
        self.tris, self.rest_area, self.scale = [], [], []
        for i in range(0, nx - 1, cx):
            for j in range(0, ny - 1, cy):
                ids = np.array([a * ny + b for a in range(i, i + cx + 1) for b in range(j, j + cy + 1)])
                # the patch's flex-grid triangles (flexcomp grid order), as indices into `ids`
                loc = {int(v): k for k, v in enumerate(ids)}
                tris = []
                for a in range(i, i + cx):
                    for b in range(j, j + cy):
                        v0 = a * ny + b
                        tris += [(v0, v0 + ny, v0 + ny + 1), (v0, v0 + ny + 1, v0 + 1)]
                self.tris.append(np.array([[loc[t] for t in tri] for tri in tris]))
                local = (x[ids] - x[ids].mean(axis=0)) @ frame  # rest layout in the cloth frame
                half = np.abs(local).max(axis=0) + self.radius
                half[2] = self.radius
                self.names.append(f"{name}#p{i // cx:02d}{j // cy:02d}")
                self.index.append(ids)
                self.rest.append(local)
                self.meshes.append(meshes.box(half))
                n_rest, area = oriented_normal(x[ids], self.tris[-1])
                self.rest_area.append(area)
                self.scale.append(float(np.linalg.norm(half[:2])))
        self.frame0 = frame
        # rest normals in the cloth frame, oriented like the flex triangles (frame's z up to sign)
        self.rest_normal = [oriented_normal(r, t)[0] for r, t in zip(self.rest, self.tris, strict=True)]
        # contract 0.7.0: [(time, patch, reason, det, ratio, area ratio)]; a "release" record (the first regular fit
        # after a hold) stores the rotation angle accumulated while held in place of the ratio
        self.reset_hold(data)

    def reset_hold(self, data=None):
        """Forget held rotations (fluid reset): the next fit of each patch is taken as is (it must be regular)."""
        self.held = {}
        self.holding = set()
        self.degenerate = []

    def vertices(self, data) -> np.ndarray:
        d = getattr(data, "_data", data)
        return np.array(d.flexvert_xpos[self.adr : self.adr + self.n], float)

    def poses(self, data) -> dict:
        """{patch name: (pos, R)}: patch frame = Kabsch fit of its vertices to their rest layout (cloth frame)."""
        x = self.vertices(data)
        if not np.isfinite(x).all():
            raise FloatingPointError("nonfinite flex vertices")
        out = {}
        if not self.continuous:
            for name, ids, rest in zip(self.names, self.index, self.rest, strict=True):
                c, R = kabsch(rest, x[ids])
                out[name] = (c, R)
            return out
        t = float(getattr(data, "_data", data).time)
        for k, (name, ids, rest) in enumerate(zip(self.names, self.index, self.rest, strict=True)):
            now = x[ids]
            n_now, area = oriented_normal(now, self.tris[k])
            c, R, info = kabsch_continuous(rest, now, self.rest_normal[k], n_now, self.scale[k])
            area_ratio = area / self.rest_area[k] if self.rest_area[k] > 0 else 0.0
            if R is not None and area_ratio < DEGENERATE_AREA:
                R, info = None, {**info, "reason": "area"}
            if R is None:
                if name not in self.held:
                    raise FloatingPointError(f"flex patch {name} is degenerate with no previous rotation to hold")
                R = self.held[name]
                rec = (
                    round(t, 6),
                    name,
                    info["reason"],
                    round(info["det"], 4),
                    round(info["ratio"], 4),
                    round(area_ratio, 4),
                )
                if not self.degenerate or self.degenerate[-1][:2] != rec[:2]:
                    self.degenerate.append(rec)
                self.holding.add(name)
            else:
                prev = self.held.get(name)
                if name in self.holding and prev is not None:
                    # first regular fit after a hold: log the rotation accumulated while held (it enters the
                    # coupling's angular velocity over this one step)
                    angle = float(np.arccos(np.clip((np.trace(R @ prev.T) - 1) / 2, -1, 1)))
                    self.degenerate.append((round(t, 6), name, "release", 1.0, round(angle, 4), round(area_ratio, 4)))
                self.holding.discard(name)
                self.held[name] = R
            out[name] = (c, R)
        return out
