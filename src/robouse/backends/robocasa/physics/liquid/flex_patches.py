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

Config (a liquid `boundaries` entry, contract 0.6.0 only):
    "towel": {"object": "towel", "flex_patches": {"grid": [15, 11], "cells": [2, 2]}}
`grid` is the flexcomp point count (x-major vertex order, verified at attach), `cells` the flex cells per patch
along x and y (the cell counts must divide evenly). An absorber of the same name uses all of its patches.
"""

from __future__ import annotations

import numpy as np

from . import meshes

CONTRACT = "0.6.0"


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

    def __init__(self, model, data, name: str, flex: int, grid, cells):
        nx, ny = (int(v) for v in grid)
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
        for i in range(0, nx - 1, cx):
            for j in range(0, ny - 1, cy):
                ids = np.array([a * ny + b for a in range(i, i + cx + 1) for b in range(j, j + cy + 1)])
                local = (x[ids] - x[ids].mean(axis=0)) @ frame  # rest layout in the cloth frame
                half = np.abs(local).max(axis=0) + self.radius
                half[2] = self.radius
                self.names.append(f"{name}#p{i // cx:02d}{j // cy:02d}")
                self.index.append(ids)
                self.rest.append(local)
                self.meshes.append(meshes.box(half))
        self.frame0 = frame

    def vertices(self, data) -> np.ndarray:
        d = getattr(data, "_data", data)
        return np.array(d.flexvert_xpos[self.adr : self.adr + self.n], float)

    def poses(self, data) -> dict:
        """{patch name: (pos, R)}: patch frame = Kabsch fit of its vertices to their rest layout (cloth frame)."""
        x = self.vertices(data)
        if not np.isfinite(x).all():
            raise FloatingPointError("nonfinite flex vertices")
        out = {}
        for name, ids, rest in zip(self.names, self.index, self.rest, strict=True):
            c, R = kabsch(rest, x[ids])
            out[name] = (c, R)
        return out
