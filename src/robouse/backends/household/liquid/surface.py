"""Draw the liquid in MuJoCo's own renderer: a surface reconstructed from the free particles (splashsurf) written into
a preallocated, visual-only mesh geom of the model and uploaded into a renderer's context before it draws.

The mesh is added to the scene's MjSpec before compilation with a fixed capacity; each reconstruction fills a prefix
and collapses the remaining faces onto one vertex (zero area, not drawn). The geom has contype = conaffinity = 0 and
no mass: it never touches the physics, and the scene's own lights, shadows, anti-aliasing and resolution apply.

Reconstruction parameters are part of liquid contract 1.0.0 (they decide what the policy sees): smoothing length 2,
cube size 0.75, iso-surface 0.6, 15 mesh and 10 normal smoothing iterations (all in particle radii where SPlisHSPlasH
and splashsurf define them so). A surface over capacity is an error (a truncated surface is never shown).
"""

from __future__ import annotations

import time

import numpy as np

MAX_VERTS = 64 * 1875 + 2  # 120002: a UV-sphere placeholder needs (V - 2) % 64 == 0
MESH = "liquid/surface"
GEOM = "liquid/surface"
MATERIAL = "liquid/surface"
RECONSTRUCTION = {
    "smoothing_length": 2.0,
    "cube_size": 0.75,
    "iso_surface_threshold": 0.6,
    "mesh_smoothing_iters": 15,
    "mesh_smoothing_weights": True,
    "normals_smoothing_iters": 10,
    "compute_normals": True,
    "mesh_cleanup": True,
    "decimate_barnacles": True,
    "multi_threading": True,
    "subdomain_grid": True,
}


def placeholder(max_verts: int = MAX_VERTS):
    """A closed surface with exactly max_verts vertices (a 1 cm UV sphere), so MuJoCo compiles the mesh."""
    from .meshes import revolve

    seg = 64
    rings = (max_verts - 2) // seg
    a = np.linspace(-np.pi / 2, np.pi / 2, rings + 2)
    prof = [(0.0, -0.01)] + [(0.01 * np.cos(x), 0.01 * np.sin(x)) for x in a[1:-1]] + [(0.0, 0.01)]
    return revolve(prof, seg)


def add_to_spec(spec, rgba) -> None:
    """Add the surface mesh, its material and its visual-only world geom to a scene MjSpec (before compile)."""
    import mujoco

    for coll in (spec.meshes, spec.geoms, spec.materials):
        if any((el.name or "") == MESH for el in coll):
            raise ValueError("the scene already has a liquid/surface element")
    v, f = placeholder()
    mesh = spec.add_mesh()
    mesh.name = MESH
    mesh.uservert = v.ravel().astype(np.float32).tolist()
    mesh.userface = f.ravel().astype(np.int32).tolist()
    mesh.inertia = mujoco.mjtMeshInertia.mjMESH_INERTIA_SHELL
    mat = spec.add_material()
    mat.name = MATERIAL
    mat.rgba = list(rgba)
    mat.specular = 0.6
    mat.shininess = 0.85
    mat.reflectance = 0.0
    spec.worldbody.add_geom(
        name=GEOM,
        type=mujoco.mjtGeom.mjGEOM_MESH,
        meshname=MESH,
        material=MATERIAL,
        contype=0,
        conaffinity=0,
        group=1,
        density=0,
        pos=[0, 0, -5],
    )


class SurfaceRenderer:
    """Owns the liquid mesh geom of a compiled model: update(points) writes it into the model; upload(renderer)."""

    def __init__(self, model, particle_radius: float):
        import mujoco

        self.model = model
        self.mesh = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_MESH, MESH)
        self.geom = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, GEOM)
        if self.mesh < 0 or self.geom < 0:
            raise ValueError("the model has no liquid surface mesh")
        m = self.mesh
        self.va, self.vn = int(model.mesh_vertadr[m]), int(model.mesh_vertnum[m])
        self.fa, self.fn = int(model.mesh_faceadr[m]), int(model.mesh_facenum[m])
        self.na, self.nn = int(model.mesh_normaladr[m]), int(model.mesh_normalnum[m])
        if self.nn != self.vn:
            raise RuntimeError(f"liquid mesh compiled with {self.nn} normals for {self.vn} vertices")
        # the geom frame is the world frame: vertices are written in world coordinates
        model.geom_pos[self.geom] = 0.0
        model.geom_quat[self.geom] = (1.0, 0.0, 0.0, 0.0)
        self.kw = dict(particle_radius=float(particle_radius), **RECONSTRUCTION)
        self.last = {"verts": 0, "faces": 0, "seconds": 0.0}
        self.clear()

    def clear(self):
        M = self.model
        M.mesh_vert[self.va : self.va + self.vn] = 0.0
        M.mesh_normal[self.na : self.na + self.nn] = (0.0, 0.0, 1.0)
        M.mesh_face[self.fa : self.fa + self.fn] = 0
        M.mesh_facenormal[self.fa : self.fa + self.fn] = 0

    def reconstruct(self, points: np.ndarray):
        import pysplashsurf

        pts = np.ascontiguousarray(points, dtype=np.float64)
        if len(pts) < 4:
            return np.zeros((0, 3)), np.zeros((0, 3), np.int64), np.zeros((0, 3))
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

    def update(self, points: np.ndarray) -> dict:
        t0 = time.perf_counter()
        v, f, n = self.reconstruct(points)
        if len(v) > self.vn or len(f) > self.fn:
            raise RuntimeError(f"the liquid surface exceeds the mesh capacity ({len(v)}/{self.vn} vertices)")
        M = self.model
        self.clear()
        if len(v):
            M.mesh_vert[self.va : self.va + len(v)] = v
            M.mesh_normal[self.na : self.na + len(v)] = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
            M.mesh_face[self.fa : self.fa + len(f)] = f
            M.mesh_facenormal[self.fa : self.fa + len(f)] = f
        self.last = {"verts": int(len(v)), "faces": int(len(f)), "seconds": time.perf_counter() - t0}
        return self.last

    def upload(self, renderer) -> None:
        import mujoco

        con = getattr(renderer, "_mjr_context", None)
        if con is None:
            raise RuntimeError("the renderer has no MuJoCo rendering context")
        gl = getattr(renderer, "_gl_context", None)
        if gl is not None:
            gl.make_current()
        mujoco.mjr_uploadMesh(self.model, con, self.mesh)


def _vertex_normals(v, f):
    n = np.zeros_like(v)
    if len(f):
        fn = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
        for c in range(3):
            np.add.at(n, f[:, c], fn)
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
