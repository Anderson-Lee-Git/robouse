"""Akinci boundary samples of a triangle mesh: SPlisHSPlasH's RegularTriangleSampling (vertices, then edge samples
without the vertices, then face samples without the edges), at `max_distance` = 1.5 x particle radius as the
StaticBoundarySimulator calls it for samplingMode 1. Pure numpy, body frame."""
from __future__ import annotations

import numpy as np


def regular_triangle_sampling(vertices: np.ndarray, faces: np.ndarray, max_distance: float) -> np.ndarray:
    v = np.asarray(vertices, np.float64)
    f = np.asarray(faces, np.int64)
    d = float(max_distance)
    out = [v]
    # unique edges (sorted pairs), in SPlisHSPlasH's sorted order
    e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    e = np.sort(e, axis=1)
    e = np.unique(e, axis=0)
    for a, b in e:
        v0, dirv = v[a], v[b] - v[a]
        length = float(np.linalg.norm(dirv))
        n = int(np.ceil(length / d)) + 1
        if n == 1:
            out.append(v0[None])
            continue
        for i in range(1, n - 1):  # skipVertices
            out.append((v0 + (i / (n - 1)) * dirv)[None])
    for tri in f:
        l2 = 0.0
        for c in range(3):
            edge = v[tri[(c + 1) % 3]] - v[tri[c]]
            le2 = float(edge @ edge)
            if le2 > l2:
                l2, v0, base, to_top = le2, v[tri[c]], edge, v[tri[(c + 2) % 3]] - v[tri[c]]
        length = float(np.sqrt(l2))
        bn = base / length
        h = float(np.linalg.norm(to_top - (bn @ to_top) * bn))
        n_lines = int(np.ceil(h / d)) + 1
        for line in range(1, n_lines - 1):  # skipEdges
            alpha = line / (n_lines - 1)
            start = v0 + alpha * to_top
            ll = (1 - alpha) * length
            n = int(np.ceil(ll / d)) + 1
            for i in range(1, n - 1):
                out.append((start + (i * ll) / (n - 1) * bn)[None])
    return np.concatenate(out).astype(np.float64)
