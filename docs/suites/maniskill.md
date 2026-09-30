# ManiSkill3 suite

12 tabletop manipulation tasks from [ManiSkill3](https://maniskill.readthedocs.io) (Hao Su Lab at UCSD and Hillbot; code [mani-skill/ManiSkill](https://github.com/mani-skill/ManiSkill), formerly `haosulab/ManiSkill`; `mani-skill` 3.0.1 on SAPIEN 3.0.3). A Franka Panda with its parallel gripper picks, stacks, pushes and pulls cubes, uses an L-shaped tool and a peg as tools, rolls a ball across the table, stands a peg upright, and does two tight-clearance insertions (a peg into a side hole with 3 mm clearance, a charger into a receptacle with 0.5 mm). Success is ManiSkill's own `evaluate()["success"]` for each task.

ManiSkill is usually run on a GPU (its GPU-parallel PhysX backend and a CUDA Vulkan renderer). This suite runs it on ManiSkill's CPU physics backend (`sim_backend="cpu"`, one environment, PhysX on the CPU) with SAPIEN's Vulkan renderer on whatever Vulkan device exists: MoltenVK on macOS and Mesa's lavapipe software rasteriser in the Linux image. No GPU is needed anywhere.

- Backend: `src/robouse/backends/maniskill.py` (bridge, task table `TASKS`), `maniskill_worker.py` (runs in ManiSkill's own virtualenv), `maniskill_oracles.py` (reference solutions).
- Generator: `python adapters/maniskill/generate.py --out tasks/maniskill`.
- Hub: dataset `haosulab/maniskill` 0.1 on the `maniskill` runtime (`templates/runtimes/maniskill` in robohub).

## Source and licences

- ManiSkill3 code: Apache-2.0 ([LICENSE](https://github.com/mani-skill/ManiSkill/blob/main/LICENSE); third-party notices in `LICENSE-3RD-PARTY`, PyTorch3D code under BSD).
- SAPIEN 3: Apache-2.0 (copyright UCSD SU Lab and Hillbot Inc.).
- Assets: every asset these 12 tasks use ships inside the Apache-2.0 `mani-skill` wheel: the Panda model (`panda_v2.urdf`, derived from Franka's `franka_description`, Apache-2.0), the table and simple primitives (cubes, spheres, pegs, the box with a hole, the charger and receptacle are built from boxes in code). Nothing is downloaded at run time.
- Left out on licence grounds: tasks that need ManiSkill's downloadable asset packs, e.g. `TurnFaucet` and `OpenCabinetDrawer` (PartNet-Mobility, non-commercial research terms), `PickSingleYCB` and `PickClutterYCB` (YCB objects, CC BY 4.0, a separate download), and the ReplicaCAD / AI2-THOR scenes.

## Setup (macOS or Linux, no GPU)

```
uv venv -p 3.12 ~/.cache/robouse/maniskill-venv
uv pip install --python ~/.cache/robouse/maniskill-venv/bin/python mani-skill==3.0.1 torch==2.14.0
```

- macOS: `sapien` 3.0.3 has a `macosx_12_0_universal2` wheel. SAPIEN renders through Vulkan, so it needs MoltenVK: download `MoltenVK-macos.tar` from the [MoltenVK v1.4.2 release](https://github.com/KhronosGroup/MoltenVK/releases/tag/v1.4.2) and unpack it into `~/.cache/robouse/moltenvk` (no system install). The backend sets `VK_ICD_FILENAMES` to `~/.cache/robouse/moltenvk/MoltenVK/MoltenVK/dynamic/dylib/macOS/MoltenVK_icd.json` when it exists; without a Vulkan driver even `gym.make` fails (`vk::createInstanceUnique: ErrorIncompatibleDriver`), because ManiSkill creates a render system for every scene.
- Linux arm64: SAPIEN publishes `linux_aarch64` wheels only on its [GitHub release page](https://github.com/haosulab/SAPIEN/releases/tag/3.0.3), not on PyPI ([SAPIEN issue 294](https://github.com/haosulab/SAPIEN/issues/294)). Install that wheel first, then `mani-skill==3.0.1 --no-deps` and its dependencies (the robohub runtime's `requirements-maniskill.txt`). Two fixes are needed, both in the runtime Dockerfile: the wheel's bundled `librt` (from glibc 2.28) references `GLIBC_PRIVATE` symbols of that glibc, so it is replaced by a link to the system `librt.so.1` ([SAPIEN issue 284](https://github.com/haosulab/SAPIEN/issues/284)); and the software Vulkan driver must be Mesa 23 or newer (Debian trixie ships Mesa 25), because SAPIEN requires `descriptorBindingPartiallyBound`, which Mesa 22 lavapipe (Debian bookworm) lacks (`Failed to find a supported physical device "cpu"`).
- `mplib`, which ManiSkill's own motion-planning demonstrations need, has no arm64 wheels at all (only x86_64), so the reference solutions here are this suite's own scripted controllers.
- The backend looks for the interpreter at `~/.cache/robouse/maniskill-venv/bin/python`; override with `ROBOUSE_MANISKILL_PYTHON`. `ROBOUSE_MANISKILL_QUIET=0` shows the worker's stderr.
- Speed: on an M2 Max a control step (IK plus 5 PhysX substeps) takes 5 to 15 ms and a 384 x 384 render 5 to 30 ms, so a 300-step episode with its video takes 10 to 25 s. In the Linux image on lavapipe (Colima, 6 CPUs) the first render of an episode compiles shaders (about 14 s), later renders take 0.1 to 0.5 s, and the reference-solution episodes took 18 to 118 s of episode wall time (54 to 341 steps).

## Action, observation, scoring

- **Action** (7 numbers, world frame): `robo act DX DY DZ DROLL DPITCH DYAW GRIP`, each in [-1, 1]. DX/DY/DZ move the commanded gripper position 2 cm per unit per step; DROLL/DPITCH/DYAW turn the commanded orientation 0.1 rad per unit per step about the world axes, around the fingertip point; GRIP > 0 closes, -f opens to fraction f, 0 keeps the fingers. One step is 50 ms (ManiSkill's 20 Hz control). The upstream env runs in its `pd_joint_pos` control mode; the worker keeps the commanded pose, solves damped-least-squares inverse kinematics with pytorch_kinematics (the solver ManiSkill itself uses for end-effector control on GPU; its CPU path needs SAPIEN's Pinocchio, which the macOS wheel lacks) and adds a bounded integral correction, so the hand settles on the commanded pose even while holding a load. The commanded position stays within 5 cm of the measured hand (orientation within 0.35 rad), so pushing into something stalls instead of winding up. `robo move-to` and `robo grip` work and keep the orientation.
- **Observation** (state tier): `hand_pos`, `hand_quat` (w, x, y, z), `hand_down_axis`, `finger_axis`, the commanded `hand_target_pos` / `hand_target_quat`, `gripper_open`, `gripper_width`, and per task the objects and goals ManiSkill's own state observation gives its policies (poses, sizes, goal positions and poses, `grasped` from ManiSkill's grasp test). Two derived fields make geometry explicit: axis vectors of pegs, tools, holes and the charger, and the peg head position (ManiSkill's own `peg_head_pos` ignores the peg's rotation, so the worker computes it from `peg_head_pose`). Images: `render_camera` (the task's own human-view camera, 384 x 384, default), `base_camera`, and `hand_camera` on the four tasks whose upstream robot is `panda_wristcam`.
- **Success**: ManiSkill's `evaluate()["success"]`, judged after `robo done` and a 10-step hold (success mode `final`), except RollBall, which uses `first`: the ball rolls on after crossing the target and ManiSkill's own evaluation counts success-once for it. Rules that include "robot static" (PickCube, PokeCube) or "object static and not grasped" (StackCube, StackPyramid, PlaceSphere) are checked as written. `result.json` carries ManiSkill's full `evaluate()` dictionary as `judge_detail`.

## Tasks

Object layouts are ManiSkill's own randomisation with seed 1 (the `seed` in each `task.md`); `robouse run --seed N` samples others.

| Task | ManiSkill env | Robot | What | Budget | Oracle steps |
|---|---|---|---|---|---|
| maniskill-pick-cube | PickCube-v1 | panda | hold the cube at a point in the air | 300 | 54 |
| maniskill-stack-cube | StackCube-v1 | panda_wristcam | red cube on green cube | 400 | 87 |
| maniskill-stack-pyramid | StackPyramid-v1 | panda_wristcam | red and green side by side, blue on top | 800 | 157 |
| maniskill-push-cube | PushCube-v1 | panda | push into a 10 cm target | 300 | 92 |
| maniskill-pull-cube | PullCube-v1 | panda | pull toward the robot into a 10 cm target | 300 | 54 |
| maniskill-pull-cube-tool | PullCubeTool-v1 | panda | hook an out-of-reach cube with an L-shaped tool | 500 | 125 |
| maniskill-poke-cube | PokeCube-v1 | panda | push a cube with a held peg into a 5 cm target | 500 | 72 |
| maniskill-place-sphere | PlaceSphere-v1 | panda | ball into a 4 cm bin, released | 300 | 227 |
| maniskill-roll-ball | RollBall-v1 | panda | roll a ball more than a metre into a 10 cm target | 300 | 135 |
| maniskill-lift-peg-upright | LiftPegUpright-v1 | panda | stand a lying 24 cm peg on its end | 500 | 332 |
| maniskill-peg-insertion-side | PegInsertionSide-v1 | panda_wristcam | peg into a side hole, 3 mm clearance | 600 | 335 |
| maniskill-plug-charger | PlugCharger-v1 | panda_wristcam | charger into a receptacle, 0.5 mm clearance | 600 | 165 |

## Reference solutions

`maniskill_oracles.py` drives the robot only through the episode socket and reads only public fields. Each solution servos the commanded hand pose toward goal poses and waits for the measured hand; the insertions are closed-loop on the observed peg or charger pose (align the axis with the hole, centre on the hole line 1.5 to 3 cm out, then go in a few millimetres at a time, re-centring each time). Choices that matter: grasp headings are picked so the wrist stays inside its joint range (the Panda's last joint turns about 166 degrees each way) and the open fingers do not land on a neighbouring cube; the peg is stood upright by gripping its middle and turning the hand 90 degrees about the finger axis toward the robot (the other way runs joint 6 into its limit); the charger is gripped at the back of its base with the hand tilted 15 degrees back, as in ManiSkill's own motion-planning solution; the ball is pushed through its centre at a constant 0.3 m/s from contact rather than struck. Over seeds 1 to 8 on the Mac the solutions succeed on 8/8 for most tasks, 7/8 for RollBall, and 6/8 for StackPyramid (cubes that start touching); the tasks use seed 1.

## Validation

- Local runner (`robouse run-many`, macOS, M2 Max): reference solutions **12/12** (`runs/maniskill-oracle`), no-op control **0/12** (`runs/maniskill-noop`).
- Hub image (robohub `maniskill` runtime, linux/arm64 under Colima, `bench eval run` 0.7.4 with the oracle agent): **12/12** (two trials first failed to start with a Docker `No such container` error while other agents were using the VM, and passed when rerun). No-op control (copies of two tasks whose `solve.sh` only observes and calls `robo done`): **0/2** (outcome `done`, ManiSkill says not solved). Simulator image: 3.54 GB on disk (844 MB compressed content); the build downloads the SAPIEN wheel (52 MB), mani-skill (about 200 MB with its bundled assets) and CPU torch.

## Model probe

Kimi K3 (Baseten) with the `claude-code-glm` harness on 3 tasks (`task-lists/maniskill-probe.txt`, `runs/maniskill-probe-kimi`):

| Task | Result | Steps | Wall time | What happened |
|---|---|---|---|---|
| maniskill-pick-cube | solved | 73 | 39 s | `move-to` over the cube, down, `grip 1`, `move-to` the goal point, held still, `robo done` |
| maniskill-stack-cube | solved | 60 | 30 s | Same pattern: grasp the red cube, carry it over the green one, lower to 6.8 cm, open, back off |
| maniskill-peg-insertion-side | solved | 149 | 320 s | Yawed the fingers across the peg, grasped near the tail, turned the peg onto the hole axis with DYAW (correcting for slip in the grasp), found `move-to`'s 1 cm tolerance too coarse, retracted when the head rattled on the rim, re-centred to 0.5 mm and pushed in 1 cm at a time |

The two easy tasks are solved in a few `move-to` calls; the insertion took the model 70 requests of closed-loop centring, much like the reference solution. The probe found one instruction gap, fixed afterwards: the instruction now says that `move-to` stops within 1 cm unless `--tol` is given. The harder tasks (plug charger, standing the peg upright, the pyramid, rolling the ball) were not probed.

## What was left out

- Tasks needing downloaded asset packs (PartNet-Mobility, YCB, ReplicaCAD, AI2-THOR): licences and size, see above.
- `PushT-v1`: it uses a different robot (`panda_stick`, a Panda with a rod instead of a gripper) and a 90 % area-overlap rule; left for a later version.
- `AssemblingKits-v1`: needs the `assembling_kits` asset download.
- Two-robot tasks (`TwoRobotPickCube`, `TwoRobotStackCube`), the drawing tasks and the humanoid, quadruped and mobile tasks: out of scope for a single-arm tabletop suite.
- GPU-only features: ManiSkill's GPU-parallel simulation and ray-traced rendering are not used; everything here is the single-environment CPU path.
