"""Closed triangle meshes for fluid boundaries, and the files SPlisHSPlasH reads (OBJ meshes, BGEO particles).

Everything here is plain numpy, in metres, in the frame of the MuJoCo body a mesh belongs to.
"""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np


def revolve(profile, segments: int = 48):
    """A closed surface of revolution about the z axis.

    `profile` is a polyline of (r, z) points from the axis around the solid's cross-section back to the axis, e.g. for
    a cup: (0, 0) -> outer bottom rim -> outer lip -> inner lip -> inner floor -> (0, floor). Points with r == 0 become
    a single pole vertex. Faces wind counter-clockwise seen from the side the profile turns away from, which for a
    profile walked outer-bottom first is outward."""
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
    for a, b in zip(rings[:-1], rings[1:]):
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


def cup_profile(r_bottom, r_top, height, wall, base, segments_lip=3):
    """(r, z) profile of an open cup with a flat floor: outer wall tapering from r_bottom to r_top, `wall` thick, a
    `base` thick floor and a rounded lip. Interior: floor at z = base, inner radius r - wall."""
    lip = [(r_top - wall / 2 + wall / 2 * np.cos(a), height - wall / 2 + wall / 2 * np.sin(a))
           for a in np.linspace(0, np.pi, segments_lip + 2)]
    return [(0.0, 0.0), (r_bottom - 0.002, 0.0), (r_bottom, 0.002), *lip,
            (r_bottom - wall + (r_top - r_bottom) * base / height, base), (0.0, base)]


def bottle_profile(r_body, h_body, r_neck, h_shoulder, h_neck, wall, base, lip=0.0015):
    """(r, z) profile of a bottle: cylinder body (radius r_body, height h_body), a conical shoulder of height
    h_shoulder up to a neck of outer radius r_neck and length h_neck, with a slightly thicker lip ring at the mouth.
    Walls are `wall` thick, the floor `base` thick. The mouth is open."""
    top = h_body + h_shoulder + h_neck
    ri_body, ri_neck = r_body - wall, r_neck - wall
    return [
        (0.0, 0.0), (r_body - 0.003, 0.0), (r_body, 0.003),
        (r_body, h_body), (r_neck, h_body + h_shoulder), (r_neck, top - 0.006),
        (r_neck + lip, top - 0.005), (r_neck + lip, top - 0.001), (r_neck, top),
        (ri_neck, top), (ri_neck, h_body + h_shoulder + wall * 0.4), (ri_body, h_body + wall * 0.4),
        (ri_body, base + 0.002), (ri_body - 0.002, base), (0.0, base),
    ]


def write_obj(path, v, f) -> Path:
    path = Path(path)
    lines = [f"v {x:.7f} {y:.7f} {z:.7f}" for x, y, z in v] + [f"f {a + 1} {b + 1} {c + 1}" for a, b, c in f]
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(lines) + "\n")
    tmp.replace(path)
    return path


def read_bgeo(path) -> np.ndarray:
    """Positions of a BGEO written by write_bgeo (no attributes), for checks."""
    b = Path(path).read_bytes()
    n = struct.unpack(">i", b[9:13])[0]
    return np.frombuffer(b[41:41 + 16 * n], ">f4").reshape(n, 4)[:, :3].astype(np.float64)


def write_bgeo(path, positions) -> Path:
    """Houdini BGEO (version 5, uncompressed), positions only: what partio writes and SPlisHSPlasH reads as an initial
    fluid. Big-endian header, then x y z w per point."""
    p = np.asarray(positions, dtype=np.float64).reshape(-1, 3)
    n = len(p)
    magic = (((((ord("B") << 8) | ord("g")) << 8) | ord("e")) << 8) | ord("o")
    head = struct.pack(">ici", magic, b"V", 5) + struct.pack(">8i", n, 0, 0, 0, 0, 0, 0, 0)
    # cast after concatenating: np.concatenate returns native (little-endian) order whatever its inputs are
    body = np.concatenate([p, np.ones((n, 1))], axis=1).astype(">f4").tobytes()
    path = Path(path)
    path.write_bytes(head + body + b"\x00\xff")
    return path


def lattice_in_cylinder(r_in, z0, z1, spacing, centre=(0.0, 0.0), gap=None):
    """Fluid particle centres on a cubic lattice (pitch `spacing`) filling a vertical cylinder of radius r_in (the
    container's inner wall) above its floor z0 up to the fill level z1. Centres keep `gap` (default one pitch, the
    rest distance to Akinci boundary particles) from the wall and the floor. Deterministic order (z, y, x)."""
    h = spacing
    gap = h if gap is None else gap
    n = int(np.floor(r_in / h)) + 1
    xs = np.arange(-n, n + 1) * h
    zs = np.arange(z0 + gap, z1 - h / 2 + 1e-9, h)
    X, Y = np.meshgrid(xs, xs, indexing="xy")
    keep = np.hypot(X, Y) <= r_in - gap
    xy = np.stack([X[keep], Y[keep]], axis=1)
    pts = [np.column_stack([xy + np.asarray(centre), np.full(len(xy), z)]) for z in zs]
    return np.concatenate(pts, axis=0)


def mujoco_body_mesh(model, body: int, groups=(0,), include_children: bool = False, name_contains: str | None = None,
                     meshes_only: bool = False):
    """The geoms of one MuJoCo body as a single triangle mesh in that body's frame (meshes and boxes; spheres and
    cylinders are tessellated). `groups` selects geom groups (RoboCasa: 0 collision, 1 visual and regions);
    `name_contains` keeps geoms whose name contains it; `meshes_only` skips primitives (e.g. RoboCasa's region boxes)."""
    import mujoco

    bodies = {body}
    if include_children:
        for b in range(model.nbody):
            c = b
            while c > 0 and c not in bodies:
                c = int(model.body_parentid[c])
            if c in bodies:
                bodies.add(b)
    V, F = [], []
    off = 0
    for g in range(model.ngeom):
        if int(model.geom_bodyid[g]) not in bodies or int(model.geom_group[g]) not in groups:
            continue
        t = int(model.geom_type[g])
        if meshes_only and t != mujoco.mjtGeom.mjGEOM_MESH:
            continue
        if name_contains is not None and name_contains not in (mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, g) or ""):
            continue
        size = model.geom_size[g]
        if t == mujoco.mjtGeom.mjGEOM_MESH:
            m = int(model.geom_dataid[g])
            va, vn = int(model.mesh_vertadr[m]), int(model.mesh_vertnum[m])
            fa, fn = int(model.mesh_faceadr[m]), int(model.mesh_facenum[m])
            v = np.array(model.mesh_vert[va:va + vn], float)
            f = np.array(model.mesh_face[fa:fa + fn], np.int64)
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
            continue
        R = np.empty(9)
        mujoco.mju_quat2Mat(R, model.geom_quat[g])
        if int(model.geom_bodyid[g]) != body:
            raise NotImplementedError("child bodies: pass include_children only for welded children at identity")
        V.append(v @ R.reshape(3, 3).T + model.geom_pos[g])
        F.append(f + off)
        off += len(v)
    if not V:
        raise ValueError(f"body {body} has no geoms in groups {groups}")
    return np.concatenate(V), np.concatenate(F)


def plate_samples(half_x, half_y, z, spacing, layers=2):
    """Akinci boundary samples of a horizontal work surface: a square grid on its top face (and `layers`-1 more layers
    below, one spacing apart, so a fast drop cannot slip between samples). Far cheaper than sampling a whole
    counter box, whose sides and underside the liquid never reaches."""
    xs = np.arange(-half_x, half_x + 1e-9, spacing)
    ys = np.arange(-half_y, half_y + 1e-9, spacing)
    X, Y = np.meshgrid(xs, ys, indexing="xy")
    pts = [np.column_stack([X.ravel() + (k % 2) * spacing / 2, Y.ravel() + (k % 2) * spacing / 2,
                            np.full(X.size, z - k * spacing)]) for k in range(layers)]
    return np.concatenate(pts)


def polygon_contains(xy, polygon):
    """Even/odd containment, including the edge, for a simple footprint polygon."""
    xy, poly = np.asarray(xy, float), np.asarray(polygon, float)
    if poly.ndim != 2 or poly.shape[1] != 2 or len(poly) < 3 or not np.isfinite(poly).all():
        raise ValueError("footprint must contain at least three finite XY vertices")
    inside = np.zeros(len(xy), bool)
    edge = np.zeros(len(xy), bool)
    for a, b in zip(poly, np.roll(poly, -1, axis=0)):
        ab = b - a
        t = np.clip((xy - a) @ ab / max(float(ab @ ab), 1e-30), 0, 1)
        edge |= np.linalg.norm(xy - a - t[:, None] * ab, axis=1) < 1e-10
        if abs(ab[1]) > 1e-15:
            crosses = (a[1] > xy[:, 1]) != (b[1] > xy[:, 1])
            inside ^= crosses & (xy[:, 0] < a[0] + (xy[:, 1] - a[1]) * ab[0] / ab[1])
    return inside | edge


def puddle_fill(polygon, volume_ml: float, z: float, spacing: float):
    """Container-free lattice above a world-XY polygon; volume rounded to one particle.

    Bottom centres are one spacing above the support, matching Akinci wall sampling.
    Partial top layers are distributed evenly over the footprint, in deterministic order.
    """
    poly = np.asarray(polygon, float)
    polygon_contains(np.empty((0, 2)), poly)  # validate even for zero volume
    if not np.isfinite([volume_ml, z, spacing]).all() or volume_ml < 0 or spacing <= 0:
        raise ValueError("volume must be nonnegative and spacing positive, all values finite")
    n = int(np.floor(volume_ml * 1e-6 / spacing ** 3 + 0.5))
    if n == 0:
        return np.empty((0, 3))
    lo, hi = poly.min(0), poly.max(0)
    xs, ys = [np.arange(a + spacing / 2, b, spacing) for a, b in zip(lo, hi)]
    X, Y = np.meshgrid(xs, ys)
    xy = np.column_stack((X.ravel(), Y.ravel()))
    xy = xy[polygon_contains(xy, poly)]
    if not len(xy):
        raise ValueError("footprint contains no lattice centres at this spacing")
    layers, extra = divmod(n, len(xy))
    out = [np.column_stack((xy, np.full(len(xy), z + spacing * (i + 1)))) for i in range(layers)]
    if extra:
        idx = np.floor((np.arange(extra) + 0.5) * len(xy) / extra).astype(int)
        out.append(np.column_stack((xy[idx], np.full(extra, z + spacing * (layers + 1)))))
    return np.concatenate(out)
