"""Closed triangle meshes for fluid boundaries, initial particle lattices, and the files SPlisHSPlasH reads (OBJ meshes,
BGEO particles). Plain numpy, metres; a boundary mesh is in the frame of the MuJoCo body that carries it.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np


def revolve(profile, segments: int = 48):
    """A closed surface of revolution about z from a (r, z) polyline that starts and ends on the axis (r = 0 points
    become one pole vertex). Faces are wound outward."""
    prof = [(float(r), float(z)) for r, z in profile]
    th = np.linspace(0.0, 2 * np.pi, segments, endpoint=False)
    verts, rings = [], []
    for r, z in prof:
        if r <= 1e-12:
            rings.append([len(verts)])
            verts.append((0.0, 0.0, z))
        else:
            rings.append(list(range(len(verts), len(verts) + segments)))
            verts.extend((r * np.cos(t), r * np.sin(t), z) for t in th)
    faces = []
    for a, b in zip(rings[:-1], rings[1:], strict=False):
        if len(a) == 1 and len(b) == 1:
            continue
        for k in range(segments):
            k1 = (k + 1) % segments
            if len(a) == 1:
                faces.append((a[0], b[k1], b[k]))
            elif len(b) == 1:
                faces.append((a[k], a[k1], b[0]))
            else:
                faces.append((a[k], a[k1], b[k1]))
                faces.append((a[k], b[k1], b[k]))
    v, f = np.asarray(verts, float), np.asarray(faces, np.int64)
    if signed_volume(v, f) < 0:
        f = f[:, ::-1].copy()
    return v, f


def box(half):
    """An axis-aligned box mesh centred at the origin, outward faces."""
    hx, hy, hz = map(float, half)
    v = np.array([[sx * hx, sy * hy, sz * hz] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)])
    q = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    f = np.array([t for a, b, c, d in q for t in ((a, b, c), (a, c, d))], np.int64)
    if signed_volume(v, f) < 0:
        f = f[:, ::-1].copy()
    return v, f


def signed_volume(v, f) -> float:
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def write_obj(path, v, f) -> Path:
    path = Path(path)
    lines = [f"v {x:.7f} {y:.7f} {z:.7f}" for x, y, z in v] + [f"f {a + 1} {b + 1} {c + 1}" for a, b, c in f]
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(lines) + "\n")
    tmp.replace(path)
    return path


def read_bgeo(path) -> np.ndarray:
    """Positions of a BGEO written by write_bgeo."""
    b = Path(path).read_bytes()
    n = struct.unpack(">i", b[9:13])[0]
    return np.frombuffer(b[41 : 41 + 16 * n], ">f4").reshape(n, 4)[:, :3].astype(np.float64)


def write_bgeo(path, positions) -> Path:
    """Houdini BGEO (version 5, uncompressed), positions only: what SPlisHSPlasH reads as an initial fluid or a
    custom boundary sampling. Big-endian header, then x y z w per point."""
    p = np.asarray(positions, dtype=np.float64).reshape(-1, 3)
    n = len(p)
    magic = (((((ord("B") << 8) | ord("g")) << 8) | ord("e")) << 8) | ord("o")
    head = struct.pack(">ici", magic, b"V", 5) + struct.pack(">8i", n, 0, 0, 0, 0, 0, 0, 0)
    body = np.concatenate([p, np.ones((n, 1))], axis=1).astype(">f4").tobytes()
    path = Path(path)
    path.write_bytes(head + body + b"\x00\xff")
    return path


def radius_at(profile, z):
    prof = np.asarray(profile, float)
    return np.interp(z, prof[:, 1], prof[:, 0], left=-1.0, right=-1.0)


def profile_fill(profile, n: int, spacing: float) -> np.ndarray:
    """The `n` lowest centres of a cubic lattice (pitch `spacing`, one lattice point on the axis) inside an axially
    symmetric container's inside profile [(r, z), ...] (body frame). Centres keep one pitch from the floor and the
    wall (the rest distance to Akinci boundary samples) and stay half a pitch below the rim. Deterministic order
    (z, y, x). Raises when the container cannot hold `n`."""
    prof = np.asarray(profile, float)
    h = float(spacing)
    rmax = float(prof[:, 0].max())
    k = int(np.floor(rmax / h)) + 1
    xs = np.arange(-k, k + 1) * h
    zs = np.arange(prof[0, 1] + h, prof[-1, 1] - h / 2 + 1e-12, h)
    X, Y = np.meshgrid(xs, xs, indexing="xy")
    rr = np.hypot(X, Y).ravel()
    out, have = [], 0
    for z in zs:
        keep = rr <= radius_at(prof, z) - h + 1e-12
        if keep.any():
            layer = np.column_stack([X.ravel()[keep], Y.ravel()[keep], np.full(int(keep.sum()), z)])
            out.append(layer)
            have += len(layer)
        if have >= n:
            break
    if have < n:
        raise ValueError(f"the container holds {have} particles at this spacing, the source needs {n}")
    return np.concatenate(out)[:n]


def plate_samples(half_x, half_y, z, spacing, layers=2):
    """Akinci boundary samples of a horizontal work surface: a square grid on its top face and `layers`-1 more
    layers below, one spacing apart and offset by half a pitch (so a fast drop cannot slip between samples)."""
    xs = np.arange(-half_x, half_x + 1e-9, spacing)
    ys = np.arange(-half_y, half_y + 1e-9, spacing)
    X, Y = np.meshgrid(xs, ys, indexing="xy")
    pts = [
        np.column_stack(
            [
                X.ravel() + (k % 2) * spacing / 2,
                Y.ravel() + (k % 2) * spacing / 2,
                np.full(X.size, z - k * spacing),
            ]
        )
        for k in range(layers)
    ]
    return np.concatenate(pts)


def polygon_contains(xy, polygon):
    """Even/odd containment, including the edge, for a simple footprint polygon."""
    xy, poly = np.asarray(xy, float).reshape(-1, 2), np.asarray(polygon, float)
    if poly.ndim != 2 or poly.shape[1] != 2 or len(poly) < 3 or not np.isfinite(poly).all():
        raise ValueError("footprint must contain at least three finite XY vertices")
    inside = np.zeros(len(xy), bool)
    edge = np.zeros(len(xy), bool)
    for a, b in zip(poly, np.roll(poly, -1, axis=0), strict=True):
        ab = b - a
        t = np.clip((xy - a) @ ab / max(float(ab @ ab), 1e-30), 0, 1)
        edge |= np.linalg.norm(xy - a - t[:, None] * ab, axis=1) < 1e-10
        if abs(ab[1]) > 1e-15:
            crosses = (a[1] > xy[:, 1]) != (b[1] > xy[:, 1])
            inside ^= crosses & (xy[:, 0] < a[0] + (xy[:, 1] - a[1]) * ab[0] / ab[1])
    return inside | edge


def puddle_fill(polygon, n: int, z: float, spacing: float) -> np.ndarray:
    """`n` container-free lattice centres above a world-XY polygon on a support at height z: bottom centres one
    spacing above it; a partial top layer is spread evenly over the footprint, in deterministic order."""
    poly = np.asarray(polygon, float)
    polygon_contains(np.empty((0, 2)), poly)
    if n <= 0:
        raise ValueError("a puddle needs at least one particle")
    lo, hi = poly.min(0), poly.max(0)
    xs, ys = [np.arange(a + spacing / 2, b, spacing) for a, b in zip(lo, hi, strict=True)]
    X, Y = np.meshgrid(xs, ys)
    xy = np.column_stack((X.ravel(), Y.ravel()))
    xy = xy[polygon_contains(xy, poly)]
    if not len(xy):
        raise ValueError("the puddle footprint contains no lattice centre at this spacing")
    layers, extra = divmod(n, len(xy))
    out = [np.column_stack((xy, np.full(len(xy), z + spacing * (i + 1)))) for i in range(layers)]
    if extra:
        idx = np.floor((np.arange(extra) + 0.5) * len(xy) / extra).astype(int)
        out.append(np.column_stack((xy[idx], np.full(extra, z + spacing * (layers + 1)))))
    return np.concatenate(out)


def geoms_mesh(model, data, body: int, geoms: list[int]):
    """The named geoms as one triangle mesh in `body`'s frame (meshes as compiled; boxes, cylinders and spheres
    tessellated). Each geom must belong to `body` or to a body welded under it (no joint in between): the mesh then
    moves rigidly with `body`. Uses the current `data` poses (after mj_forward)."""
    import mujoco

    bp = np.asarray(data.xpos[body], float)
    bR = np.asarray(data.xmat[body], float).reshape(3, 3)
    V, F, off = [], [], 0
    for g in geoms:
        b = int(model.geom_bodyid[g])
        while b != body:
            if b == 0 or model.body_jntnum[b]:
                raise ValueError("a boundary geom must be welded to its boundary body")
            b = int(model.body_parentid[b])
        t = int(model.geom_type[g])
        size = model.geom_size[g]
        if t == mujoco.mjtGeom.mjGEOM_MESH:
            m = int(model.geom_dataid[g])
            va, vn = int(model.mesh_vertadr[m]), int(model.mesh_vertnum[m])
            fa, fn = int(model.mesh_faceadr[m]), int(model.mesh_facenum[m])
            v = np.array(model.mesh_vert[va : va + vn], float)
            f = np.array(model.mesh_face[fa : fa + fn], np.int64)
        elif t == mujoco.mjtGeom.mjGEOM_BOX:
            v, f = box(size)
        elif t == mujoco.mjtGeom.mjGEOM_CYLINDER:
            r, hh = float(size[0]), float(size[1])
            v, f = revolve([(0, -hh), (r, -hh), (r, hh), (0, hh)], 32)
        elif t == mujoco.mjtGeom.mjGEOM_SPHERE:
            r = float(size[0])
            a = np.linspace(-np.pi / 2, np.pi / 2, 12)
            v, f = revolve([(r * np.cos(x), r * np.sin(x)) for x in a], 24)
        else:
            raise ValueError("a boundary geom must be a mesh, box, cylinder or sphere")
        gR = np.asarray(data.geom_xmat[g], float).reshape(3, 3)
        w = v @ gR.T + np.asarray(data.geom_xpos[g], float)
        V.append((w - bp) @ bR)
        F.append(f + off)
        off += len(v)
    return np.concatenate(V), np.concatenate(F)
