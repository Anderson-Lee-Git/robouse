# robosuite suite

21 tasks built on [robosuite](https://robosuite.ai/) 1.5 (Zhu et al.; ARISE Initiative / Stanford): realistic robot arms (Franka Panda, UR5e, Kinova Gen3, KUKA IIWA, Rethink Sawyer), with one arm or two, in robosuite's MuJoCo manipulation scenes. The suite replaces "a floating gripper over a tabletop" with full arms driven through an operational-space controller. They have reach limits, joint limits, wrist singularities, contact-rich grasps, articulated objects and two-arm coordination. Backend: `src/robouse/backends/robosuite_backend.py`. Reference solutions: `src/robouse/backends/robosuite_oracle.py`. Generator: `python adapters/robosuite/generate.py --out tasks/robosuite`.

## Install

robosuite 1.5 conflicts with LIBERO, which pins `robosuite==1.4.0` in the same virtualenv. The backend therefore loads robosuite 1.5 from an isolated directory, `<venv>/robosuite-1.5` by default (override with `ROBOUSE_ROBOSUITE_PATH`). It prepends that directory to `sys.path` only inside the episode server process of a robosuite task, so LIBERO episodes keep seeing 1.4.0.

```
uv pip install --python .venv/bin/python --no-deps --target .venv/robosuite-1.5 robosuite==1.5.2
uv pip install --python .venv/bin/python numba scipy opencv-python pynput termcolor "qpsolvers[quadprog]" mink   # robosuite 1.5's runtime deps
```

In an environment without LIBERO, `pip install 'robouse[robosuite]'` (the `robosuite` extra in `pyproject.toml`) installs robosuite 1.5 normally, and the backend imports it from site-packages. The installed package is about 530 MB (mostly robot meshes). Tested with robosuite 1.5.2, MuJoCo 3.3.0, numpy 2.5.3 and Python 3.12 on macOS (Apple M2 Max, `MUJOCO_GL=cgl`).

Rendering uses `mujoco.Renderer` on robosuite's own model and data, not robosuite's renderer (which wants EGL/OSMesa/GLFW), with collision geoms (group 0) hidden as robosuite's renderer hides them. Images come out upright, and the camera projection matrices in `robo info` apply without a flip.

## Scene, action and observation

- **Controller:** robosuite's `BASIC` composite controller, i.e. `OSC_POSE` for each arm plus its gripper, 20 control steps per second. We change one setting: `input_ref_frame` is `"world"` (robosuite's default is each robot's base frame). All arms, including the second robot of a two-arm scene whose base faces the first, therefore take deltas in the same world frame.
- **Action (single arm with a gripper, 7 numbers):** `[dx, dy, dz, droll, dpitch, dyaw, grip]`, each in [-1, 1]. dx/dy/dz = 1.0 asks for a 5 cm move of the hand's setpoint; held at 1.0 the hand travels about 1.1 cm per step (measured on all five arms). droll/dpitch/dyaw rotate the hand about the world x/y/z axes, 1.0 asks for 0.5 rad. grip +1 closes, -1 opens, and 0 keeps the fingers as they are (robosuite's grippers integrate the sign of the command).
- **Action (Wipe):** 6 numbers, because the wiping tool has no gripper.
- **Action (two arms):** robot0's numbers first, then robot1's (robosuite's order): 14 numbers for TwoArmLift and TwoArmHandover, 12 for TwoArmPegInHole (no grippers). `robo info` lists the names (`r0_dx` ... `r1_grip`).
- **Skills:** single-arm tasks allow `robo move-to` and `robo grip`, which send `[dx, dy, dz, grip]`; the backend expands them to the full action with zero rotation. Two-arm tasks allow neither skill.
- **Observation (`robo observe`):**
  - Robot (single arm): `hand_pos` (robosuite's `eef_pos`, the grasp point between the fingertips), `hand_quat` (x, y, z, w), `gripper_open` (distance between the two finger-pad geoms, m), `gripper_yaw_deg` (direction of the fingertip line in the table plane, [-90, 90)). Two-arm tasks prefix these with `robot0_` / `robot1_`.
  - Objects: robosuite's object observables under lower-case names (`cube_pos`, `cubea_quat`, `can_pos`, `squarenut_pos`, `hinge_qpos`, `handle_qpos`, `pot_pos`, `handle0_pos`, `hammer_pos`, ...). Every `<obj>_quat` also comes with `<obj>_yaw_deg`. The robot-relative duplicates (`gripper_to_cube_pos` and the like) are dropped.
  - Task geometry that robosuite checks against but does not observe, added from the simulator: `target_bin_center`, `target_bin_x_range`, `target_bin_y_range`, `bin_floor_z` (PickPlace); `square_peg_pos`, `round_peg_pos`, `<nut>_handle_pos` (NutAssembly); `door_hinge_pos` (Door); `markers_left`, `dirt_markers_xy`, `hand_force_N` (Wipe); `peg_pos`, `peg_axis`, `hole_center`, `hole_axis` and robosuite's own alignment numbers `peg_hole_t`, `peg_hole_d`, `peg_hole_cos` (TwoArmPegInHole); `hammer_handle_axis`, `hammer_head_pos`, `hammer_handle_length` (TwoArmHandover); `table_height`. All of these are visible in the scene; none reveal anything the success check hides.
- **Cameras:** `agentview` (default), `sideview` (Door), `frontview` (two-arm tasks), plus `robot0_eye_in_hand`, at 320x320. `mj_model_data()` is provided, so the suite can be regenerated with `obs_mode: vision`.
- **Reset:** robosuite's own placement randomisation with the task's fixed `seed` (passed to `suite.make(seed=...)`), then 10 settle steps with the grippers opening. The settle steps don't count against the budget.
- **Success:** robosuite's own `_check_success()` after every step.

## Tasks

| Task id | robosuite env | Robot(s) | Seed | Budget | Mode | Oracle steps |
|---|---|---|---|---|---|---|
| robosuite-lift-panda | Lift | Panda | 0 | 400 | first | 62 |
| robosuite-lift-ur5e | Lift | UR5e | 1 | 400 | first | 57 |
| robosuite-lift-kinova3 | Lift | Kinova3 | 2 | 400 | first | 85 |
| robosuite-lift-iiwa | Lift | IIWA | 3 | 400 | first | 49 |
| robosuite-lift-sawyer | Lift | Sawyer | 4 | 400 | first | 69 |
| robosuite-stack-panda | Stack | Panda | 0 | 400 | final | 117 |
| robosuite-stack-ur5e | Stack | UR5e | 1 | 400 | final | 135 |
| robosuite-pickplace-can-panda | PickPlaceCan | Panda | 0 | 400 | final | 290 |
| robosuite-pickplace-milk-panda | PickPlaceMilk | Panda | 1 | 400 | final | 203 |
| robosuite-pickplace-bread-panda | PickPlaceBread | Panda | 2 | 400 | final | 157 |
| robosuite-pickplace-cereal-panda | PickPlaceCereal | Panda | 3 | 400 | final | 205 |
| robosuite-pickplace-can-kinova3 | PickPlaceCan | Kinova3 | 4 | 400 | final | 348 |
| robosuite-nut-square-panda | NutAssemblySquare | Panda | 2 | 500 | final | 322 |
| robosuite-nut-round-panda | NutAssemblyRound | Panda | 3 | 500 | final | 222 |
| robosuite-door-panda | Door | Panda | 1 | 400 | final | 240 |
| robosuite-door-iiwa | Door | IIWA | 2 | 400 | final | 233 |
| robosuite-wipe-panda | Wipe | Panda | 0 | 600 | first | 160 |
| robosuite-twoarm-lift-panda | TwoArmLift (opposed) | Panda x2 | 0 | 400 | first | 77 |
| robosuite-twoarm-lift-iiwa | TwoArmLift (opposed) | IIWA x2 | 1 | 400 | first | 124 |
| robosuite-twoarm-peginhole-panda | TwoArmPegInHole (opposed) | Panda x2 | 0 | 500 | final | 120 |
| robosuite-twoarm-handover-panda | TwoArmHandover (opposed) | Panda x2 | 2 | 700 | final | 226 |

What each task asks, its success rule, and why it is scored that way:

- **Lift (5 embodiments):** lift the 4 cm cube; robosuite: cube centre > table + 4 cm. Scored `first`: lifting is a transient act, and robomimic's rollouts end at the first success. The five arms differ in kinematics, grippers (Panda gripper, Robotiq 2F-85, Robotiq 2F-140, Rethink gripper) and rest pose. The Sawyer's OSC stalls when asked to keep the hand vertical over the cube, so its reference solution uses position control only, and the instruction warns about aggressive orientation commands.
- **Stack (Panda, UR5e):** put the red 4 cm cube on the green 5 cm cube; robosuite: A lifted, touching B, not grasped. Scored `final`: the stack must stand after release.
- **PickPlace Can / Milk / Bread / Cereal (Panda; Can also on Kinova3):** move the object from the right-hand bin into its compartment of the divided bin on the robot's left; robosuite: the object's centre is inside the compartment (x, y and a 10 cm height band) and the gripper is at least about 4 cm from it. Scored `final`: the object must stay in place, and robosuite itself requires the hand to have let go. Cereal is hard because the box only fits the Panda's fingers across its 6 cm side.
- **NutAssembly Square / Round (Panda):** fit the nut over its peg; robosuite: the nut centre is within 3 cm of the peg axis in x and y, below table + 5 cm, and the gripper is away. Scored `final`. The hole hangs about 5 cm from the grasped handle, the pegs sit near the edge of the reach, and the square nut must be turned to match its square peg. Budget 500 rather than robomimic's 400 for Square: the reference solution needs up to about 410 steps on some seeds.
- **Door (Panda, IIWA):** turn the spring-loaded lever past about 1.2 rad to release the latch, then swing the door toward the robot; robosuite: hinge angle > 0.3 rad (the hinge stops at 0.4). Scored `final`: the door must stay open.
- **Wipe (Panda with robosuite's wiping tool):** wipe all 100 dirt markers along a random line; a marker counts when the tool's face, pressed flat, passes over it while no other arm link touches the table and no joint is at its limit; robosuite: all markers wiped. Scored `first`: wiping is monotone, and robosuite's Wipe env terminates at the first full wipe. Budget 600.
- **TwoArmLift (2x Panda, 2x IIWA, opposed):** lift the pot by its two handles; robosuite: pot bottom > table + 10 cm. Scored `first`, as for Lift.
- **TwoArmPegInHole (2x Panda, opposed, no grippers):** the peg is fixed to robot0's hand and the plate to robot1's; robosuite: |cos| between the axes > 0.95, peg centre within 6 cm of the hole axis, and -0.12 ≤ t ≤ 0.14 along it. Scored `final`: both arms must hold still with the peg through the hole. At the start the axes are about 90 degrees apart.
- **TwoArmHandover (2x Panda, opposed):** robot0 picks the hammer up and hands it to robot1; robosuite: robot1 grasps the handle, robot0 does not touch the hammer, and the hammer is > 10 cm above the table. Scored `final`. There is no robomimic horizon for this env; budget 700 (as for robomimic's two-arm Transport).

Each instruction states the goal, the success rule, when the episode ends, the action layout, every observed field, the cameras and the budget, followed by the shared `ROBO_USAGE` text.

## Reference solutions

Scripted end-effector controllers in `robosuite_oracle.py`, run by `oracle/solve.sh` as `python -m robouse.oracle --backend robosuite --env <EnvName>[:norot]`. They talk to the episode server only through the robo socket and read only the public fields above. They never use the oracle token and never import robosuite. The shared core closes the loop on the observed hand pose: position error to dx/dy/dz; hand tilt away from vertical plus finger-line yaw error to droll/dpitch/dyaw; and stall detection, so a blocked motion stops early. Per task:

- Lift / Stack / PickPlace: turn the fingers to face the object (object yaw modulo its symmetry; cereal across its narrow side), grasp from above at an object-specific height (milk 4 cm above its reference point, which sits well below the carton's top), carry at a safe height, lower, release, retreat.
- NutAssembly: grasp the handle with the fingers across it. Turn the nut so its handle points toward the robot or sideways, never away: reaching past the peg stalls the arm. Then servo the nut's centre, not the hand, over the peg to within 2 mm (stiffer in xy), keep a square nut at yaw 0 mod 90, lower while centred, and retry if it jams.
- Door: grasp the lever from above, move along the lever's arc ((sin θ, -cos θ) in x, z) until it passes 1.35 rad, then pull along the door's circle about `door_hinge_pos` while holding the lever down until the door has opened 0.2 rad.
- Wipe: press the tool down until `hand_force_N` rises, then sweep toward the nearest remaining marker, aiming 1 cm past it to overcome friction, with the tool kept flat. A marker that makes no progress for 25 steps is skipped and retried later.
- TwoArmLift: each arm grasps its handle (fingertip line along the centre-to-handle direction), then both rise at the same rate.
- TwoArmPegInHole: both wrists turn about 45 degrees to the bisector of the two axes; then robot0 aims the peg at the plate's current axis, lines it up 15 cm in front of the hole, and pushes it through. It ends with zero actions, because re-levelling the hands would undo the alignment.
- TwoArmHandover: robot0 grasps the handle on its own side, near the (head-heavy) centre of mass, and brings the hammer to the middle. robot1 climbs, moves over, and grasps the other end of the handle from above. robot0 releases and backs away.

## Results

| Run | Solved |
|---|---|
| `--harness oracle` (`runs/_v1-oracle-robosuite`) | 21/21 |
| `--harness noop` (`runs/_v1-noop-robosuite`) | 0/21 |
| codex + gpt-6-astra probe, 6 tasks (`runs/_probe-robosuite-astra`, list `task-lists/robosuite-probe-6.txt`) | 5/6 |

The probe used one task per family: lift-panda (solved, 68 steps), stack-panda (solved, 119), pickplace-can-panda (solved, 221), nut-round-panda (solved, 199), twoarm-lift-panda (solved, 55), and door-panda (failed: budget exhausted at 400 steps, hinge 0.236 rad). Each solved trial took about one minute of wall time. The agent used only `robo` commands (`robo info`, `observe`, `move-to`, `grip`, `act`); `scripts/audit.py` flags nothing suspicious. With full state observations, the pick-and-place families are within reach of a frontier coding agent. The articulated Door, whose latch must be held while the door is pulled along its arc, is where it failed. The untested nut-square, pickplace-cereal, wipe, peg-in-hole and handover tasks are expected to be harder. Owner instruction at the time: no Claude Opus 5.5 trials, so the probe used codex + gpt-6-astra.

Reference-solution robustness across seeds, measured in-process with the same session code (the task files use one fixed seed each): Lift 6/6 on each of the five arms, Stack 6/6, PickPlace 6/6 per object, NutAssembly 19/20 (square 10/10, round 9/10), Door 4/6 (Panda) and 4/4 (IIWA), Wipe 6/6, TwoArmLift 4/4 (Panda) and 3/4 (IIWA), TwoArmPegInHole 6/6, TwoArmHandover 2/4. Each task uses a seed where the reference solution succeeds, and MuJoCo is deterministic, so the reference result per task file is reproducible.

## Limitations

- **Dropped:** ToolHang (robomimic's hardest task: insert a stand into a base, then hang a tool on it with tight tolerances) and TwoArmTransport (lid removal, payload transfer and trash disposal across two arms). I could not script either reliably in the time available, and a task without a working reference solution is not shipped.
- **Environment edits:** the only change to robosuite's environments is the controller's world input frame. Everything else (scenes, randomisation, success checks, gripper models) is robosuite 1.5.2 as installed.
- **Embodiments:** the Sawyer's OSC cannot hold a vertical hand over the Lift cube, so its reference solution uses position control only. Jaco was tried and dropped (no reliable grasp in the Lift scene).
- **Seed sensitivity:** Door and TwoArmHandover reference solutions succeed on only part of the seeds (see above), so only the fixed seed in the task files is guaranteed solvable. Running these tasks with `--seed` overrides may give an unsolved layout.
- **Observation extras** (target bin ranges, peg positions, hinge location, hammer axis, marker list) come from the simulator rather than robosuite's observables. They describe visible, static scene geometry.
- **Rendering:** `mujoco.Renderer` with collision geoms hidden, not robosuite's renderer. Pictures match robosuite's own offscreen renders; lighting and textures are robosuite's.
