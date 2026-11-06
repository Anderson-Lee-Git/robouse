"""Draw the liquid in MuJoCo's own renderer: a surface mesh reconstructed from the particles (splashsurf) written into a
preallocated, visual-only mesh geom of the model and uploaded to the GPU/OSMesa context before a frame is drawn.

Why a mesh in the model: MuJoCo draws only what is in mjModel (plus decor geoms), so the policy images keep coming
from the unchanged Environment/robosuite render path, with the scene's own lights, shadows, anti-aliasing and
resolution. The mesh geom is created at model build time with a fixed capacity (vertices, faces); each frame fills
a prefix with the reconstructed surface and collapses the remaining faces onto one vertex (zero area, not drawn).
The geom has contype = conaffinity = 0 and no mass: it never touches the physics.
"""
from __future__ import annotations

import time

import numpy as np

# capacity of the drawn surface; a 250 ml pour at 1.25 mm particles reconstructs to ~30-60k triangles
MAX_VERTS = 64 * 1875 + 2  # 120002: a UV-sphere placeholder needs (V - 2) % 64 == 0
MAX_FACES = 2 * MAX_VERTS - 4
MESH_NAME = "liquid_surface_mesh"
GEOM_NAME = "liquid_surface"
MATERIAL_NAME = "liquid_surface_mat"

# Orange juice: nearly opaque, glossy. Water would be rgba ~ (0.75, 0.88, 1.0, 0.35).
JUICE_RGBA = (1.0, 0.56, 0.10, 0.93)
# Native MuJoCo alpha blending and glossy highlights; no refraction claim.
WATER_RGBA = (0.75, 0.88, 1.0, 0.28)


def placeholder(max_verts: int = MAX_VERTS):
    """A closed, valid surface with exactly max_verts vertices and 2*max_verts-4 faces (a UV sphere, 1 cm), so
    MuJoCo compiles the mesh; its contents are replaced before anything is drawn."""
    from .meshes import revolve

    seg = 64
    rings = (max_verts - 2) // seg
    assert rings * seg + 2 == max_verts, "max_verts - 2 must be a multiple of 64"
    a = np.linspace(-np.pi / 2, np.pi / 2, rings + 2)
    prof = [(0.0, -0.01)] + [(0.01 * np.cos(x), 0.01 * np.sin(x)) for x in a[1:-1]] + [(0.0, 0.01)]
    v, f = revolve(prof, seg)
    return v, f


def mjcf(max_verts: int = MAX_VERTS, rgba=JUICE_RGBA, specular=0.6, shininess=0.85, reflectance=0.0):
    """(asset elements, worldbody geom element) as XML strings for the liquid surface. The vertex data is inline so
    no file has to travel with the model."""
    v, f = placeholder(max_verts)
    vs = " ".join(f"{x:.5f}" for x in v.ravel())
    fs = " ".join(str(int(i)) for i in f.ravel())
    asset = (f'<mesh name="{MESH_NAME}" vertex="{vs}" face="{fs}" inertia="shell"/>'
             f'<material name="{MATERIAL_NAME}" rgba="{" ".join(map(str, rgba))}" specular="{specular}" '
             f'shininess="{shininess}" reflectance="{reflectance}"/>')
    geom = (f'<geom name="{GEOM_NAME}" type="mesh" mesh="{MESH_NAME}" material="{MATERIAL_NAME}" '
            f'contype="0" conaffinity="0" group="1" mass="0" density="0" pos="0 0 -5"/>')
    return asset, geom


def add_to_robosuite_model(world_model, max_verts: int = MAX_VERTS, rgba=JUICE_RGBA):
    """Append the surface mesh asset and geom to a robosuite/RoboCasa MJCF model (env.model in _load_model)."""
    import xml.etree.ElementTree as ET

    asset, geom = mjcf(max_verts, rgba)
    for el in ET.fromstring(f"<a>{asset}</a>"):
        world_model.asset.append(el)
    world_model.worldbody.append(ET.fromstring(geom))


class SurfaceRenderer:
    """Owns the liquid mesh geom of a compiled model: reconstruct(points) -> write into the model -> upload."""

    def __init__(self, model, particle_radius: float, smoothing_length: float = 2.0, cube_size: float = 0.75,
                 iso: float = 0.6, smoothing_iters: int = 15, normal_iters: int = 10, strict: bool = False):
        import mujoco

        self.model = model
        self.strict = bool(strict)
        self.mesh = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_MESH, MESH_NAME)
        self.geom = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, GEOM_NAME)
        if self.mesh < 0 or self.geom < 0:
            raise ValueError("model has no liquid surface mesh (add it with add_to_robosuite_model at build time)")
        m = self.mesh
        self.va, self.vn = int(model.mesh_vertadr[m]), int(model.mesh_vertnum[m])
        self.fa, self.fn = int(model.mesh_faceadr[m]), int(model.mesh_facenum[m])
        self.na, self.nn = int(model.mesh_normaladr[m]), int(model.mesh_normalnum[m])
        if self.nn != self.vn:
            raise RuntimeError(f"liquid mesh compiled with {self.nn} normals for {self.vn} vertices")
        # The geom frame is the world frame: vertices are written in world coordinates.
        model.geom_pos[self.geom] = 0.0
        model.geom_quat[self.geom] = (1.0, 0.0, 0.0, 0.0)
        self.r = float(particle_radius)
        self.kw = dict(particle_radius=self.r, smoothing_length=smoothing_length, cube_size=cube_size,
                       iso_surface_threshold=iso, mesh_smoothing_iters=smoothing_iters, mesh_smoothing_weights=True,
                       normals_smoothing_iters=normal_iters, compute_normals=True, mesh_cleanup=True,
                       decimate_barnacles=True, multi_threading=True, subdomain_grid=True)
        self.last = {"verts": 0, "faces": 0, "seconds": 0.0, "truncated": False}
        self.clear()

    def clear(self):
        M = self.model
        M.mesh_vert[self.va:self.va + self.vn] = 0.0
        M.mesh_normal[self.na:self.na + self.nn] = (0.0, 0.0, 1.0)
        M.mesh_face[self.fa:self.fa + self.fn] = 0
        M.mesh_facenormal[self.fa:self.fa + self.fn] = 0

    def reconstruct(self, points: np.ndarray):
        """Surface (vertices, faces, normals) of the particle cloud, float64 / int32."""
        import pysplashsurf

        pts = np.ascontiguousarray(points, dtype=np.float64)
        if len(pts) < 4:
            return np.zeros((0, 3)), np.zeros((0, 3), np.int32), np.zeros((0, 3))
        out = pysplashsurf.reconstruction_pipeline(pts, **self.kw)
        mesh_data = out[0] if isinstance(out, tuple) else out
        tri = mesh_data.mesh
        v = np.asarray(tri.vertices, dtype=np.float64)
        f = np.asarray(tri.triangles, dtype=np.int64)
        attrs = mesh_data.point_attributes
        n = np.asarray(attrs["normals"], dtype=np.float64) if "normals" in attrs else None
        if n is None or len(n) != len(v):
            n = _vertex_normals(v, f)
        return v, f, n

    def update(self, points: np.ndarray):
        """Reconstruct the surface of `points` (world frame) and write it into the model (no upload)."""
        t0 = time.perf_counter()
        v, f, n = self.reconstruct(points)
        truncated = False
        if len(v) > self.vn or len(f) > self.fn:
            if self.strict:
                raise RuntimeError(f"liquid surface exceeds mesh capacity: {len(v)}/{self.vn} vertices, "
                                   f"{len(f)}/{self.fn} faces")
            # over capacity: keep the faces whose vertices all fit (a visible hole, logged) rather than crash
            truncated = True
            keep = np.all(f < self.vn, axis=1)
            f = f[keep][: self.fn]
            v, n = v[: self.vn], n[: self.vn]
        self.write(v, f, n)
        self.last = {"verts": int(len(v)), "faces": int(len(f)), "seconds": time.perf_counter() - t0,
                     "truncated": truncated}
        return self.last

    def write(self, v, f, n):
        M = self.model
        k, j = len(v), len(f)
        self.clear()
        if k:
            M.mesh_vert[self.va:self.va + k] = v
            nn = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
            M.mesh_normal[self.na:self.na + k] = nn
            M.mesh_face[self.fa:self.fa + j] = f
            M.mesh_facenormal[self.fa:self.fa + j] = f

    def upload(self, con):
        import mujoco

        mujoco.mjr_uploadMesh(self.model, con, self.mesh)


def _vertex_normals(v, f):
    n = np.zeros_like(v)
    if len(f):
        fn = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
        for c in range(3):
            np.add.at(n, f[:, c], fn)
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
