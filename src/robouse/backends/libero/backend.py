"""LIBERO (Liu et al. 2023) backend: a Franka Panda in LIBERO's MuJoCo / robosuite 1.4 scenes.

Uses the `hf-libero` package (the one LeRobot's LIBERO evaluation uses) with `robosuite==1.4.0`. A task is
chosen by suite (`libero_spatial`, `libero_object`, `libero_goal`, `libero_10`) and task index or name; the
scene comes from that task's BDDL file. A task can instead carry its own BDDL file as text (`bddl`), as the
LIBERO-PRO tasks do: LIBERO-PRO's perturbed scenes use LIBERO's objects and problem classes, so the same
package builds them.

Initial state: `init_state` in the task spec (a flat MuJoCo state vector, e.g. the first state of a LIBERO
demonstration) if given, otherwise LIBERO's fixed benchmark init state number `seed`. A task with `init_states`
(a LIBERO init file: its URL, SHA-256 and number of states; downloaded at first use) picks a state by seed instead,
as `init_mode` says: `saved` starts seed n from state (n - 1) mod N, the mapping ASPIRE's `--init-mode saved` uses,
so seed 1 is state 0 (`init_state` may hold a copy of state `init_index`, so that seed needs no download); `seeded`
loads no state and lets LIBERO's placement sampler draw the layout from the BDDL regions with the seed, as ASPIRE's
`--init-mode seeded` does. After loading it the robot holds still for `settle_steps` (default 50, as in LeRobot's
MolmoAct2 evaluation) so objects come to rest; these steps are not counted against the task's budget.

Action (LIBERO's own, 7-D, each in [-1, 1]): [dx, dy, dz, droll, dpitch, dyaw, gripper], a delta end-effector
pose for robosuite's OSC_POSE controller at 20 Hz. 1.0 on dx/dy/dz asks for 5 cm of motion in one step and
1.0 on droll/dpitch/dyaw for 0.5 rad (the arm lags behind large requests); gripper -1 opens, +1 closes.
The move_to/grip skills send 4-D [dx, dy, dz, grip] actions, which are padded with zero rotation.

Observation: end-effector position, quaternion (x, y, z, w) and axis-angle, finger joint positions, the
position and quaternion of each object in LIBERO's observation, the position and quaternion of each fixture
(cabinet, stove, microwave, rack, ...), and each articulated part (drawer, door, stove knob): its joint position,
joint limits, LIBERO's open/close or on/off thresholds for that fixture, and the world-frame bounding box of the
moving part. Images: `agentview` (front) and
`robot0_eye_in_hand` (wrist) cameras at 256x256, returned upright (robosuite renders them upside down).

Success is LIBERO's own `check_success()` (the task's BDDL goal predicates).

The reference solution alone (the oracle token) also gets `privileged_state()`: the goal predicates and the pose and
bounding box of everything they name, for the scripted solution in solver.py.
"""

from __future__ import annotations

import io
import os
import pickle
import re
import zipfile
from pathlib import Path

import numpy as np

from ..base import ActionSpec, Backend, G, StepInfo, arm_layout

SUITES = ("libero_spatial", "libero_object", "libero_goal", "libero_10", "libero_90")
CAMERAS = ("agentview", "robot0_eye_in_hand")
# LeRobot's per-suite step budgets (lerobot/envs/libero.py TASK_SUITE_MAX_STEPS)
SUITE_MAX_STEPS = {"libero_spatial": 280, "libero_object": 280, "libero_goal": 300, "libero_10": 520, "libero_90": 400}
DUMMY = [0, 0, 0, 0, 0, 0, -1]


def _quiet_imports():
    """Import LIBERO without its first-run prompt: point it at a config file (created here if missing)."""
    os.environ.setdefault("MUJOCO_GL", "cgl" if os.uname().sysname == "Darwin" else "egl")
    cfg_dir = os.environ.get("LIBERO_CONFIG_PATH", os.path.expanduser("~/.libero"))
    cfg = os.path.join(cfg_dir, "config.yaml")
    if not os.path.exists(cfg):
        import importlib.util

        spec = importlib.util.find_spec("libero")
        if spec is None or not spec.submodule_search_locations:
            raise ImportError(
                "LIBERO is not installed: pip install --no-deps hf-libero==0.1.4 robosuite==1.4.0 bddl==1.0.1"
            )
        root = os.path.join(list(spec.submodule_search_locations)[0], "libero")
        os.makedirs(cfg_dir, exist_ok=True)
        with open(cfg, "w") as f:
            f.write(
                "".join(
                    f"{k}: {os.path.join(root, v)}\n"
                    for k, v in (
                        ("benchmark_root", ""),
                        ("bddl_files", "bddl_files"),
                        ("init_states", "init_files"),
                        ("datasets", "../datasets"),
                        ("assets", "assets"),
                    )
                )
            )
    import logging

    logging.getLogger("robosuite").setLevel(logging.ERROR)
    from libero.libero import benchmark, get_libero_path
    from libero.libero.envs import OffScreenRenderEnv

    return benchmark, get_libero_path, OffScreenRenderEnv


def libero_task(suite: str, task: int | str):
    """(task index, LIBERO Task namedtuple, benchmark suite object) for a suite and a task index or name."""
    benchmark, _, _ = _quiet_imports()
    s = benchmark.get_benchmark_dict()[suite]()
    names = [s.get_task(i).name for i in range(s.get_num_tasks())]
    i = names.index(task) if isinstance(task, str) and not str(task).isdigit() else int(task)
    return i, s.get_task(i), s


def quat2axisangle(q) -> np.ndarray:
    """(x, y, z, w) quaternion -> axis-angle, as in robosuite / LeRobot's LIBERO processor."""
    q = np.asarray(q, dtype=np.float64)
    w = float(np.clip(q[3], -1.0, 1.0))
    den = np.sqrt(max(1.0 - w * w, 0.0))
    if np.isclose(den, 0.0):
        return np.zeros(3)
    return q[:3] * 2.0 * np.arccos(w) / den


def bddl_language(text: str) -> str:
    """The `(:language ...)` of a BDDL file as written (capitals kept, whitespace joined). LIBERO itself lowercases it,
    and LIBERO's task list derives an instruction from the file name, which is the old goal in LIBERO-PRO's task
    perturbation; this is the instruction the file states, the one ASPIRE gives its agents."""
    text = re.sub(r";[^\n]*", "", text)  # BDDL comments
    m = re.search(r"\(:language\s+([^)]*)\)", text)
    return " ".join(m.group(1).split()) if m else ""


class _ArrayUnpickler(pickle.Unpickler):
    """Unpickles only a numpy array: LIBERO init files are `torch.save`d numpy arrays, and a pickle that names any
    other callable is refused, so loading one runs no code from the file (and needs no torch)."""

    ALLOWED = {
        ("numpy.core.multiarray", "_reconstruct"),
        ("numpy._core.multiarray", "_reconstruct"),
        ("numpy", "ndarray"),
        ("numpy", "dtype"),
        ("_codecs", "encode"),  # how pickle protocol 2 (torch.save's default) writes the array's bytes
    }

    def find_class(self, module: str, name: str):
        if (module, name) not in self.ALLOWED:
            raise pickle.UnpicklingError(f"init file names {module}.{name}; only a numpy array is accepted")
        if module == "_codecs":
            import codecs

            return codecs.encode
        if name == "_reconstruct":
            try:
                from numpy._core.multiarray import _reconstruct
            except ImportError:  # numpy < 2
                from numpy.core.multiarray import _reconstruct  # type: ignore[no-redef]
            return _reconstruct
        return getattr(np, name)


def load_init_states(path: str | Path) -> np.ndarray:
    """The states of a LIBERO init file (`.pruned_init`, a torch zip archive holding one array), N x state size."""
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n.endswith("data.pkl"))
        arr = _ArrayUnpickler(io.BytesIO(z.read(name))).load()
    arr = np.asarray(arr, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError(f"{path}: expected an N x state array, got shape {arr.shape}")
    return arr


def init_states_file(ref: dict) -> Path:
    """A task's init file (`init_states`: url, sha256), downloaded once into <cache>/libero-init and checked by SHA-256."""
    from ... import config
    from ...lib.download import fetch

    dest = config.cache_dir() / "libero-init" / f"{ref['sha256']}.pruned_init"
    fetch(str(ref["url"]), dest, str(ref["sha256"]), timeout=120)
    return dest


class LiberoBackend(Backend):
    name = "libero"
    robot_name = "panda-2f"
    probe_success = False  # step() already reports success; LIBERO's reward is sparse

    def action_layout(self) -> list[G]:
        return arm_layout(
            "OSC_POSE: 1.0 asks for 5 cm per step",
            rotation="1.0 asks for 0.5 rad per step",
            grip_doc="-1 open, +1 close",
        )

    image_flipped = False  # render() returns upright images, as mujoco.Renderer would

    def __init__(self, spec: dict):
        _, get_libero_path, OffScreenRenderEnv = _quiet_imports()
        self.suite = str(spec.get("suite", "libero_spatial"))
        self._bddl_dir = None
        if spec.get("bddl"):  # the task carries its scene (LIBERO-PRO): LIBERO's task list is not consulted
            import tempfile

            from ... import config

            self.task_index, self.task, self._suite_obj = spec.get("task_index"), None, None
            self.language = bddl_language(str(spec["bddl"]))
            # the file names each object's start region (the layout a vision task hides): it goes in robouse's cache,
            # which the agent sandbox denies, not in the system's temporary folder, which agents can read on macOS
            root = config.cache_dir() / "libero-bddl"
            root.mkdir(parents=True, exist_ok=True)
            self._bddl_dir = tempfile.mkdtemp(prefix="episode-", dir=root)
            bddl = os.path.join(self._bddl_dir, "task.bddl")
            Path(bddl).write_text(str(spec["bddl"]))
        else:
            self.task_index, self.task, self._suite_obj = libero_task(
                self.suite, spec.get("env", spec.get("task_index", 0))
            )
            self.language = self.task.language
            bddl = os.path.join(get_libero_path("bddl_files"), self.task.problem_folder, self.task.bddl_file)
        self.max_steps = int(spec.get("max_steps", SUITE_MAX_STEPS.get(self.suite, 300)))
        self.camera = str(spec.get("camera", "agentview"))
        self.size = int(spec.get("image_size", 256))
        self.settle_steps = int(spec.get("settle_steps", 50))
        self._init_state = (
            np.asarray(spec["init_state"], dtype=np.float64) if spec.get("init_state") is not None else None
        )
        self._init_ref = dict(spec["init_states"]) if spec.get("init_states") else None
        self._init_index = int(spec.get("init_index", 0))
        self.init_mode = str(spec.get("init_mode", "saved"))
        if self.init_mode not in ("saved", "seeded"):
            raise ValueError(f"init_mode must be saved or seeded, not {self.init_mode!r}")
        self.init_index: int | None = None  # the saved state the episode started from
        self.env = OffScreenRenderEnv(
            bddl_file_name=bddl,
            camera_heights=self.size,
            camera_widths=self.size,
            camera_names=list(CAMERAS),
            # robosuite refuses to step past its horizon (LIBERO's default is 1000 steps): leave room for the settle
            # steps before the episode and the still steps after it
            horizon=max(1000, self.settle_steps + self.max_steps + 100),
        )
        self.action_spec = ActionSpec(
            names=["dx", "dy", "dz", "droll", "dpitch", "dyaw", "gripper"],
            low=[-1.0] * 7,
            high=[1.0] * 7,
            doc="LIBERO delta end-effector pose (OSC_POSE, 20 Hz): 1.0 on dx/dy/dz asks for 5 cm per step, "
            "1.0 on droll/dpitch/dyaw for 0.5 rad; gripper -1 open, +1 close",
        )
        self._obs: dict = {}
        self._success = False
        self._grip = -1.0

    # ---- episode ------------------------------------------------------------------------------
    def reset(self, seed: int) -> None:
        self.env.seed(int(seed))
        self._obs = self.env.reset()
        state = self._start_state(int(seed))
        if state is not None:
            self._obs = self.env.set_init_state(state)
        for _ in range(self.settle_steps):
            self._obs, _, _, _ = self.env.step(DUMMY)
        self._success = bool(self.env.check_success())
        self._grip = -1.0

    def _start_state(self, seed: int) -> np.ndarray | None:
        """The MuJoCo state the episode starts from, or None when LIBERO's seeded placement sampler (reset) set it."""
        self.init_index = None
        if self.init_mode == "seeded":
            return None
        if self._init_ref is not None:  # a LIBERO(-PRO) init file: the seed picks a saved state
            n = int(self._init_ref.get("count", 50))
            self.init_index = (seed - 1) % n
            if self._init_state is not None and self.init_index == self._init_index:
                return self._init_state
            return load_init_states(init_states_file(self._init_ref))[self.init_index]
        if self._init_state is not None:
            return self._init_state
        self.init_index = seed % 50
        return self._suite_obj.get_task_init_states(self.task_index)[self.init_index]

    def step(self, action) -> StepInfo:
        a = np.asarray(action, dtype=np.float64).ravel()
        if a.size == 4:  # skills (move_to / grip / settle) send [dx, dy, dz, grip]
            a = np.concatenate([a[:3], np.zeros(3), a[3:]])
        a = self.action_spec.clip(a)
        self._grip = float(a[6])
        self._obs, r, _done, _info = self.env.step(a)
        self._success = bool(self.env.check_success())
        return StepInfo(success=self._success, reward=float(r))

    def success(self) -> bool:
        return self._success

    # ---- observation --------------------------------------------------------------------------
    def object_names(self) -> list[str]:
        return sorted(
            {k[:-4] for k in self._obs if k.endswith("_pos") and not k.startswith("robot0") and "_to_robot0" not in k}
        )

    def observe(self) -> dict:
        o = self._obs
        r = lambda v, n=5: [round(float(x), n) for x in np.asarray(v).ravel()]
        eef_pos, eef_quat = o["robot0_eef_pos"], o["robot0_eef_quat"]
        fingers = np.asarray(o["robot0_gripper_qpos"], dtype=float)
        return {
            "hand_pos": r(eef_pos),
            "eef_quat": r(eef_quat),
            "eef_axis_angle": r(quat2axisangle(eef_quat)),
            "gripper_qpos": r(fingers),
            # finger gap: about 0.08 fully open, about 0 closed on nothing
            "gripper_open": round(float(fingers[0] - fingers[1]), 4),
            "objects": {n: {"pos": r(o[f"{n}_pos"], 4), "quat": r(o[f"{n}_quat"], 4)} for n in self.object_names()},
            **self._fixtures(),
        }

    def _fixtures(self) -> dict:
        """Fixtures (pose) and articulated parts (joint position, limits, LIBERO's thresholds, bounding box)."""
        import mujoco

        e = self.env.env
        m, d = self.mj_model_data()
        r = lambda v, n=4: [round(float(x), n) for x in np.asarray(v).ravel()]
        fixtures, parts = {}, {}
        for name, fx in getattr(e, "fixtures_dict", {}).items():
            bid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, f"{name}_main")
            if bid < 0:
                bid = e.obj_body_id.get(name, -1) if hasattr(e, "obj_body_id") else -1
            if bid >= 0:
                q = d.xquat[bid]  # MuJoCo (w, x, y, z) -> (x, y, z, w) like the objects
                fixtures[name] = {"pos": r(d.xpos[bid]), "quat": r([q[1], q[2], q[3], q[0]])}
            art = (getattr(fx, "object_properties", None) or {}).get("articulation", {})
            thresholds = {k[len("default_") :]: r(v) for k, v in art.items() if v}
            for jn in getattr(fx, "joints", None) or []:
                j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, jn)
                if j < 0:
                    continue
                gs = np.flatnonzero(m.geom_bodyid == m.jnt_bodyid[j])
                corners = []
                for g in gs:
                    c, h = m.geom_aabb[g, :3], m.geom_aabb[g, 3:]
                    R = d.geom_xmat[g].reshape(3, 3)
                    for sx in (-1, 1):
                        for sy in (-1, 1):
                            for sz in (-1, 1):
                                corners.append(d.geom_xpos[g] + R @ (c + h * np.array([sx, sy, sz])))
                part = {"qpos": round(float(d.qpos[m.jnt_qposadr[j]]), 4), "range": r(m.jnt_range[j]), **thresholds}
                if corners:
                    part["box_min"], part["box_max"] = r(np.min(corners, 0)), r(np.max(corners, 0))
                parts[jn] = part
        return {"fixtures": fixtures, "articulated": parts}

    # ---- what only the reference solution sees -----------------------------------------------------------------
    def privileged_state(self) -> dict:
        """For the reference solution alone (the session gives it only with the oracle token): the goal predicates;
        every object and fixture with its pose and the world-frame and body-frame bounding boxes of its collision
        geometry; every region site LIBERO's predicates test, with its centre, orientation and the half-size the
        predicates use; each articulated joint's axis and anchor; and the robot's base and joint angles."""
        import mujoco

        e = self.env.env
        m, d = self.mj_model_data()
        r = lambda v, n=4: [round(float(x), n) for x in np.asarray(v).ravel()]
        ents = {}
        for kind, dct in (("object", e.objects_dict), ("fixture", e.fixtures_dict)):
            for n in dct:
                bid = e.obj_body_id[n]
                q = d.xquat[bid]
                lo, hi = self._subtree_box(bid)
                llo, lhi = self._subtree_box(bid, local=True)
                ents[n] = {
                    "kind": kind,
                    "category": type(dct[n]).__name__,
                    "pos": r(d.xpos[bid]),
                    "quat": r([q[1], q[2], q[3], q[0]]),  # x, y, z, w
                    "box_min": r(lo),
                    "box_max": r(hi),
                    "local_box_min": r(llo),
                    "local_box_max": r(lhi),
                }
        sites = {}
        for n, s in getattr(e, "object_sites_dict", {}).items():
            sid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SITE, n)
            if sid < 0:
                continue
            sites[n] = {
                "parent": getattr(s, "parent_name", None),
                "pos": r(d.site_xpos[sid]),
                "xmat": r(d.site_xmat[sid]),
                "size": r(getattr(s, "size", None) if getattr(s, "size", None) is not None else m.site_size[sid]),
                "joints": list(getattr(s, "joints", None) or []),
            }
        joints = {}
        for fx in e.fixtures_dict.values():
            for jn in getattr(fx, "joints", None) or []:
                j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, jn)
                if j >= 0:
                    joints[jn] = {
                        "type": ["free", "ball", "slide", "hinge"][int(m.jnt_type[j])],
                        "axis": r(d.xaxis[j]),
                        "anchor": r(d.xanchor[j]),
                        "body_xmat": r(d.xmat[m.jnt_bodyid[j]]),  # the moving part's orientation, row-major
                    }
        goal = [[str(x) for x in g] for g in e.parsed_problem["goal_state"]]
        base = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "robot0_base")
        robot: dict = {"base": r(d.xpos[base])} if base >= 0 else {}
        arm = [mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, f"robot0_joint{i}") for i in range(1, 8)]
        if all(j >= 0 for j in arm):  # the arm's joint angles and limits (the last joint turns the hand)
            robot["qpos"] = r([d.qpos[m.jnt_qposadr[j]] for j in arm])
            robot["range"] = [r(m.jnt_range[j]) for j in arm]
        return {"privileged": {"goal": goal, "entities": ents, "sites": sites, "joints": joints, "robot": robot}}

    def _subtree_box(self, root: int, local: bool = False) -> tuple[np.ndarray, np.ndarray]:
        """Bounding box of the collision geoms of a body and its descendants, in the world frame (or the body's)."""
        m, d = self.mj_model_data()
        bodies = {root}
        for b in range(root + 1, m.nbody):  # MuJoCo numbers a body after its parent
            if m.body_parentid[b] in bodies:
                bodies.add(b)
        corners = []
        for g in np.flatnonzero(np.isin(m.geom_bodyid, list(bodies))):
            if m.geom_contype[g] == 0 and m.geom_conaffinity[g] == 0:
                continue  # visual-only geoms
            c, h = m.geom_aabb[g, :3], m.geom_aabb[g, 3:]
            R = d.geom_xmat[g].reshape(3, 3)
            for sx in (-1, 1):
                for sy in (-1, 1):
                    for sz in (-1, 1):
                        corners.append(d.geom_xpos[g] + R @ (c + h * np.array([sx, sy, sz])))
        if not corners:
            return d.xpos[root].copy(), d.xpos[root].copy()
        pts = np.asarray(corners)
        if local:
            pts = (pts - d.xpos[root]) @ d.xmat[root].reshape(3, 3)
        return pts.min(0), pts.max(0)

    @property
    def placement_record(self) -> dict | None:
        """How the episode's start was chosen, recorded in result.json for LIBERO-PRO's init files and seeded starts."""
        if self._init_ref is None and self.init_mode != "seeded":
            return None
        return {"init_mode": self.init_mode, "init_state": self.init_index}

    def render(self, width: int = 320, height: int = 320) -> np.ndarray:
        key = f"{self.camera}_image"
        img = self._obs.get(key)
        if img is None:  # a camera that is not in LIBERO's observation: render it directly
            img = self.env.sim.render(camera_name=self.camera, width=self.size, height=self.size)
        return np.ascontiguousarray(np.asarray(img)[::-1])  # robosuite images are upside down

    def record_scene_option(self):
        import mujoco

        opt = mujoco.MjvOption()
        opt.geomgroup[0] = 0  # hide collision geoms, as robosuite's own renderer does
        return opt

    def mj_model_data(self):
        return self.env.sim.model._model, self.env.sim.data._data

    # ---- skills -------------------------------------------------------------------------------
    def skills(self) -> list[str]:
        return ["move_to", "grip"]

    def hand_pos(self) -> np.ndarray:
        return np.asarray(self._obs["robot0_eef_pos"], dtype=float)

    def close(self) -> None:
        try:
            self.env.close()
        except Exception:  # noqa: BLE001 - best-effort teardown
            pass
        if self._bddl_dir:
            import shutil

            shutil.rmtree(self._bddl_dir, ignore_errors=True)


def oracle_main(env: str) -> None:
    """Reference solution: replay one LIBERO demonstration's recorded actions (`env` = path to a JSON file with
    {"actions": [[7 floats], ...]}) through the robo socket. The task's init_state is that demonstration's first
    state, so the open-loop replay reproduces the demonstration."""
    import json

    from ...agent_cli import _send

    actions = json.loads(Path(env).read_text())["actions"]
    for a in actions:
        r = _send({"op": "act", "action": [float(x) for x in a], "repeat": 1})
        if not r.get("ok") or "episode" in (r.get("result") or {}):
            return  # finished (goal reached under success_mode "first", or budget)
    # hold still a little longer in case the last placement needs to settle
    for _ in range(20):
        r = _send({"op": "act", "action": [0, 0, 0, 0, 0, 0, float(actions[-1][6])], "repeat": 1})
        if not r.get("ok") or "episode" in (r.get("result") or {}):
            return
    _send({"op": "done", "text": "demonstration replayed"})
