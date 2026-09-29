"""MyoSuite -> Robo Use tasks (suite "myosuite"): muscle-driven models of the human elbow, index finger and hand from MyoSuite
2.12.2 (Apache-2.0, github.com/MyoHub/myosuite). Backend, skills, judge and reference solutions:
src/robouse/backends/myosuite_backend.py (the simulator runs in its own virtualenv through
src/robouse/backends/myosuite_worker.py; setup in docs/suites/myosuite.md). The generator starts each env once to read the
joints, muscles and targets it writes into the instruction, so it needs that virtualenv too.

The key-turn task's reference solution runs MyoSuite's own NPG baseline policy for myoHandKeyTurnFixed-v0 (shipped in the
myosuite wheel under agents/baslines_NPG as an mjrl pickle). The generator converts that pickle's weights to
oracle/policy.json; reading the pickle needs torch (the robouse dev environment has it; mjrl itself is not needed).

Usage: python adapters/myosuite/generate.py [--out tasks/myosuite] [--myosuite-venv ~/.cache/robouse/myosuite-venv]
"""
from __future__ import annotations

import argparse
import glob
import json
import shutil
import sys
import types
from pathlib import Path

from robouse.backends.embodied import write_embodied_task
from robouse.backends.myosuite_backend import CONTROL_DT, TASKS, MyoSuiteBackend
from robouse.prompts import EMBODIED_USAGE

VERSION = "MyoSuite 2.12.2"
POLICY_SEED = {"myoHandKeyTurnFixed-v0": 1}  # which of the three NPG baseline seeds the reference solution runs

HAND_SCENE = ("You control MyoHand, MyoSuite's musculoskeletal model of a right human hand and forearm (MuJoCo physics), only through its "
              "39 muscles. The forearm is fixed in space. 23 joints move: the wrist (`pro_sup` pronation/supination, `deviation`, `flexion`), "
              "the thumb (`cmc_abduction`, `cmc_flexion`, `mp_flexion`, `ip_flexion`) and the four fingers, numbered 2 = index, 3 = middle, "
              "4 = ring, 5 = little, each with `mcpN_flexion` and `mcpN_abduction` (knuckle), `pmN_flexion` (middle joint) and `mdN_flexion` "
              "(end joint). Joint angles are in radians; `robo info` lists each joint's range under `joint_ranges_rad`. The muscles are the "
              "forearm muscles of the wrist and fingers (e.g. `ECRL`, `FCU`, `FDS2`..`FDS5`, `FDP2`..`FDP5`, `EDC2`..`EDC5`, `FPL`, `EPL`, `APL`) "
              "and the small hand muscles (`OP`, and per finger `RI`, `LU_RB`, `UI_UB` interossei/lumbricals). A muscle can only pull, many "
              "muscles cross several joints, and the fingers collide with each other (`contacts`), so moving one joint tends to move others. "
              "World frame in metres, +z up; the fingers point roughly along -y.")
FINGER_SCENE = ("You control MyoFinger, MyoSuite's musculoskeletal model of a single index finger (MuJoCo physics), only through its 5 muscles: "
                "`extn` (extensor), `adabR` and `adabL` (sideways, abduction/adduction), `mflx` and `dflx` (flexors). The finger's base is "
                "fixed; it has 4 joints: `IFadb` (sideways, -0.44 to 0.44 rad), `IFmcp` (knuckle flexion, -0.44 to 1.05 rad), `IFpip` and "
                "`IFdip` (middle and end joint flexion, 0 to 1.05 rad). Angles are in radians. The finger starts straight (all joints 0), "
                "pointing along +x; flexing bends it towards -z. World frame in metres, +z up. A muscle can only pull, and the flexors "
                "cross several joints.")
ELBOW_SCENE = ("You control MyoElbow, MyoSuite's musculoskeletal model of a right arm (MuJoCo physics) with one joint, the elbow "
               "(`r_elbow_flex`: 0 rad = arm straight, positive = flexed, range 0 to 2.27 rad), moved only by its 6 muscles: the three "
               "heads of the triceps (`TRIlong`, `TRIlat`, `TRImed`, which extend the elbow) and the biceps (`BIClong`, `BICshort`) and "
               "brachialis (`BRA`), which flex it. The upper arm is fixed; gravity pulls the forearm down. A muscle can only pull.")

MUSCLE_ACT = ("`robo act E1 E2 ... [--repeat N]` sets the excitation (neural drive) of every muscle, a number in [0, 1], in the order "
              "`robo info` lists them (the action names), and holds it for N steps of 20 ms. A muscle's activation follows its excitation "
              "with MuJoCo's first-order activation dynamics (about 10 ms rising, 40 ms falling); its force also depends on its length and "
              "speed. The excitations stay as you last sent them until you act again, and they are also what the muscles hold during the "
              "10-step settle after `robo done`.")
SKILLS = ("Skills (`robo info` lists them): `robo skill set_joint_targets JOINT=RAD [JOINT=RAD ...] [steps=60] [ramp=20]` runs a "
          "muscle-space controller: every step it computes the joint torques of a PD law towards the targets (MuJoCo inverse dynamics), "
          "solves a bounded least-squares problem for the muscle activations in [0, 1] that best produce those torques, and sends the "
          "matching excitations as that step's action (the steps count against the budget like `robo act`). Joints you do not name keep "
          "their previous targets (at the start: the start pose). The targets move linearly from the current pose over RAMP steps; the "
          "skill stops after STEPS steps (at most 300) or once the joints are still, and reports the remaining joint-target error and "
          "the task's error. `robo skill hold [steps=20]` sets every target to the current angle and keeps the joints there with the "
          "same controller. The controller cannot do the impossible: joints coupled by shared muscles or blocked by contact can stop "
          "short of their targets, so check the result and adjust.")
REACH_SKILL = (" `robo skill reach_tips TIP=X,Y,Z [TIP=X,Y,Z ...] [steps=60] [ramp=20]` (positions in metres, no spaces inside a "
               "position) first solves inverse kinematics for the named fingertips within the joint ranges, starting from the current "
               "pose, then runs `set_joint_targets` with the result; it also reports the kinematic residual per fingertip.")

COMMON_OBS = ("`joint_angles_rad`, `joint_velocities_rad_s` and `joint_targets_rad` (the controller's current targets) per joint; "
              "`muscle_activations` (one per muscle, in action order); `contacts` (pairs of bones or objects touching); `time_s`; and "
              "`obs_vector`, MyoSuite's own observation vector for this env (its observation keys, in order: {keys}; not printed by "
              "plain `robo observe`, shown with `robo observe --json`).")


def _pose_text(env: str, st: dict, meta: dict) -> tuple[str, str]:
    thr = st["threshold"]
    n = len(meta["joints"])
    goal = (f"Bring the joints to the target angles in `target_pose_rad` (MyoSuite env `{env}`). The target is "
            + ", ".join(f"`{k}` = {v:.3f}" for k, v in st["target_pose_rad"].items()) + " rad. "
            + f"At the start the pose error norm is {st['pose_error_norm']:.2f} rad.")
    succ = (f"MyoSuite's own `solved` check for this env: the Euclidean norm of the joint-angle error over all {n} joint(s) (target "
            f"minus current, `pose_error_norm`) must be below {thr} rad (`threshold`, the env's pose_thd), judged by the episode "
            "server from the simulated state after you call `robo done` and the 10-step settle.")
    return goal, succ


def _reach_text(env: str, st: dict, meta: dict) -> tuple[str, str]:
    n = len(meta["tips"])
    names = {"THtip": "thumb", "IFtip": "index", "MFtip": "middle", "RFtip": "ring", "LFtip": "little"}
    goal = (f"Move the fingertip{'s' if n > 1 else ''} to the target position{'s' if n > 1 else ''} (MyoSuite env `{env}`): "
            + "; ".join(f"`{k}` ({names.get(k, k)} tip) to {v}" for k, v in st["fingertip_targets"].items())
            + f" (world frame, m). The targets are also drawn as coloured spheres. At the start the error norm is {st['reach_error_norm']:.3f} m.")
    succ = (f"MyoSuite's own `solved` check for this env: the Euclidean norm of all fingertip position errors stacked together "
            f"(`reach_error_norm`, {3 * n} numbers) must be below {st['threshold']} m (12.5 mm per fingertip, `threshold`), judged by "
            "the episode server from the simulated state after you call `robo done` and the 10-step settle.")
    return goal, succ


def _key_text(env: str, st: dict, meta: dict) -> tuple[str, str]:
    goal = (f"Turn the key (MyoSuite env `{env}`). A key stands upright next to the hand, its head (`key_head`) between the thumb "
            "and the index finger; it rotates about its own axis. Pinch the key head between the thumb and index fingertips and turn it by "
            f"more than half a turn, beyond {st['key_goal_angle_rad']} rad (`key_goal_angle_rad`); `key_angle_rad` is its current "
            "rotation (0 at the start; only rotation in the positive direction counts). The hand starts open (all joints 0).")
    succ = (f"MyoSuite's own `solved` check for this env: `key_angle_rad` must be above {st['key_goal_angle_rad']} rad, judged by the "
            "episode server from the simulated state after you call `robo done` and the 10-step settle.")
    return goal, succ


TEXT = {
    "myosuite-elbow-pose": dict(title="Elbow to a target angle", difficulty="easy", scene=ELBOW_SCENE, kind="pose", category="posture",
                                intro="The arm starts at a random elbow angle and the target angle was drawn at random (MyoSuite's "
                                      "random-target elbow task, fixed here by the episode seed)."),
    "myosuite-finger-pose-fixed": dict(title="Index finger to a fixed pose", difficulty="easy", scene=FINGER_SCENE, kind="pose", category="posture",
                                       intro="Bend the middle and end joints of the straight finger while keeping the knuckle straight."),
    "myosuite-finger-pose-random": dict(title="Index finger to a random pose", difficulty="easy", scene=FINGER_SCENE, kind="pose", category="posture",
                                        intro="The target pose was drawn at random from MyoSuite's target ranges (fixed here by the episode seed)."),
    "myosuite-finger-reach-fixed": dict(title="Index fingertip to a fixed point", difficulty="easy", scene=FINGER_SCENE, kind="reach", category="reaching",
                                        intro=""),
    "myosuite-finger-reach-random": dict(title="Index fingertip to a random point", difficulty="easy", scene=FINGER_SCENE, kind="reach", category="reaching",
                                         intro="The target was drawn at random from MyoSuite's target box (fixed here by the episode seed)."),
    "myosuite-hand-reach-fixed": dict(title="All five fingertips to fixed points", difficulty="medium", scene=HAND_SCENE, kind="reach", category="reaching",
                                      intro="The targets bring all five fingertips close together in front of the palm, a pinch of all fingers. The hand starts open (all joints 0)."),
    "myosuite-hand-reach-random": dict(title="All five fingertips to random points", difficulty="medium", scene=HAND_SCENE, kind="reach", category="reaching",
                                       intro="The targets were drawn at random from MyoSuite's per-fingertip target boxes (fixed here by the episode seed). The hand starts open (all joints 0)."),
    "myosuite-hand-key-turn": dict(title="Turn a key", difficulty="hard", scene=HAND_SCENE, kind="key", category="manipulation", intro=""),
}
for k in (4, 5, 7, 8, 9):
    TEXT[f"myosuite-hand-pose-{k}"] = dict(
        title=f"Hand shape: sign pose {k}", difficulty="medium", scene=HAND_SCENE, kind="pose", category="posture",
        intro=(f"Form hand shape {k} of the ten American Sign Language hand shapes MyoSuite defines (the env's ASL_qpos table). "
               "The hand starts open (all joints 0). Some target shapes press fingers together, so an exact match of "
               "every joint is neither needed nor always possible."))


def convert_policy(pickle_path: Path, steps: int) -> dict:
    """Weights of an mjrl Gaussian MLP policy (MyoSuite NPG baseline) as plain lists (reading needs torch, not mjrl)."""
    import pickle

    import numpy as np
    import torch
    import torch.nn as nn

    class MLP:  # stand-ins for mjrl.policies.gaussian_mlp.MLP and mjrl.utils.fc_network.FCNetwork
        pass

    class FCNetwork(nn.Module):
        def __init__(self):
            nn.Module.__init__(self)

    mods = {"mjrl": types.ModuleType("mjrl"), "mjrl.policies": types.ModuleType("mjrl.policies"),
            "mjrl.policies.gaussian_mlp": types.ModuleType("mjrl.policies.gaussian_mlp"),
            "mjrl.utils": types.ModuleType("mjrl.utils"), "mjrl.utils.fc_network": types.ModuleType("mjrl.utils.fc_network")}
    mods["mjrl.policies.gaussian_mlp"].MLP = MLP
    mods["mjrl.utils.fc_network"].FCNetwork = FCNetwork
    saved = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)
    try:
        with open(pickle_path, "rb") as f:
            pol = pickle.load(f)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    net = pol.model
    w = {}
    for k in ("in_shift", "in_scale", "out_shift", "out_scale"):
        v = getattr(net, k)
        w[k] = (v.detach().numpy() if isinstance(v, torch.Tensor) else np.asarray(v)).astype(float).round(7).tolist()
    for i, layer in enumerate(net.fc_layers):
        w[f"W{i}"] = layer.weight.detach().numpy().astype(float).round(7).tolist()
        w[f"b{i}"] = layer.bias.detach().numpy().astype(float).round(7).tolist()
    return {"source": "MyoSuite NPG baseline (myosuite/agents/baslines_NPG, Apache-2.0): " + "/".join(pickle_path.parts[-4:]),
            "network": "mjrl Gaussian MLP, mean action: x = (obs - in_shift) / (in_scale + 1e-8); tanh hidden layers; "
                       "a = W_last x + b_last; a = a * out_scale + out_shift; muscle excitation = 1 / (1 + exp(-5 (a - 0.5)))",
            "steps": steps, "weights": w}


def main() -> None:
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[2]
    ap.add_argument("--out", default=str(root / "tasks" / "myosuite"))
    ap.add_argument("--myosuite-venv", default=str(Path.home() / ".cache" / "robouse" / "myosuite-venv"))
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    site = sorted(glob.glob(f"{a.myosuite_venv}/lib/python3*/site-packages/myosuite"))
    for tid, t in TASKS.items():
        x = TEXT[tid]
        be = MyoSuiteBackend({"env": tid, "seed": t["seed"]})
        be.reset(t["seed"])
        st, meta = be.observe(), be.meta
        be.close()
        goal, succ = {"pose": _pose_text, "reach": _reach_text, "key": _key_text}[x["kind"]](t["env"], st, meta)
        steps = int(t["max_steps"])
        controls = "**Controls.** " + MUSCLE_ACT + " " + SKILLS + (REACH_SKILL if x["kind"] == "reach" else "")
        extra_obs = {"pose": "`target_pose_rad` (the goal angles), `pose_error_norm` and `threshold`",
                     "reach": "`fingertips` and `fingertip_targets` (positions, m), `reach_error_norm` and `threshold`",
                     "key": "`key_angle_rad`, `key_goal_angle_rad`, the positions (m) of `key_head`, `index_tip` and `thumb_tip`"}[x["kind"]]
        obs = ("**Observation.** `robo observe` reports " + extra_obs + "; " + COMMON_OBS.format(keys=", ".join(meta["obs_keys"]))
               + " `robo observe --image` saves a picture from a fixed camera (muscle paths are not drawn).")
        parts = [f"# {x['title']}", x["scene"], "## Task\n\n" + (x["intro"] + " " if x["intro"] else "") + goal,
                 f"**Success:** {succ} Simulated time advances only when you act (one step = {CONTROL_DT * 1000:.0f} ms).",
                 controls, obs,
                 f"The step budget is {steps} steps ({steps * CONTROL_DT:.0f} s of simulated time).", EMBODIED_USAGE]
        policy = t.get("oracle") == "policy"
        note = ("runs MyoSuite's own NPG baseline policy for this env (oracle/policy.json) through `robo act`, reading `obs_vector` from "
                "`robo observe`." if policy else
                ("reads the target pose and calls the set_joint_targets skill, then hold." if t["oracle"] == "pose" else
                 "reads the fingertip targets and calls the reach_tips skill, then hold."))
        write_embodied_task(out, task_id=tid, backend="myosuite", suite="myosuite", title=x["title"],
                            instruction="\n\n".join(parts) + "\n", robot=be.decl.robot, category=x["category"],
                            difficulty=x["difficulty"], tags=["myosuite", "musculoskeletal", "muscles", x["kind"]],
                            max_steps=steps, camera="view", cameras=["view"], oracle_note=note,
                            extra_robouse={"seed": int(t["seed"])},
                            extra_metadata={"source_benchmark": f"MyoSuite ({VERSION}, MyoHub)", "source_task": t["env"],
                                            "simulator": f"{VERSION} (Apache-2.0), MuJoCo 3.6.0"})
        d = out / tid
        if policy:
            pk = sorted(glob.glob(f"{site[-1]}/agents/baslines_NPG/{t['env']}/*/*seed={POLICY_SEED[t['env']]}/iterations/best_policy.pickle"))
            if not pk:
                raise SystemExit(f"NPG baseline for {t['env']} not found under {site}")
            (d / "oracle" / "policy.json").write_text(json.dumps(convert_policy(Path(pk[0]), int(t["policy_steps"]))))
            sh = ("#!/bin/bash\n# Reference solution: " + note + " It drives the robot only through the episode socket, like an agent.\n"
                  "set -euo pipefail\npython -m robouse.oracle --backend myosuite --env \"$(cd \"$(dirname \"$0\")\" && pwd)/policy.json\"\n")
            (d / "oracle" / "solve.sh").write_text(sh)
    print(f"wrote {len(TASKS)} tasks to {out}")


if __name__ == "__main__":
    main()
