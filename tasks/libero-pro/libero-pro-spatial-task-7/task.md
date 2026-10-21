---
schema_version: '1.3'
task:
  name: robouse/libero-pro-spatial-task-7
  description: Pick the akita black bowl on the top of the cabinet and place it on the plate.
metadata:
  source_benchmark: LIBERO-PRO (Zhou et al. 2025), uynitsuj/LIBERO-PRO at 47aaa80, the commit NVIDIA's ASPIRE pins
  source_task: libero_spatial_task/pick_up_the_black_bowl_on_the_stove_and_place_it_on_the_plate.bddl
  suite: libero-pro
  libero_pro_suite: libero_spatial_task
  libero_pro_task_index: 7
  aspire_task_ref: libero_spatial_task:7
  language_instruction: Pick the akita black bowl on the top of the cabinet and place it on the plate
  category: manipulation
  difficulty: easy
  tags:
  - franka
  - mujoco
  - robosuite
  - single-arm
  - language
  - vision
  - libero-pro
  reference_solution: scripted solution on the privileged scene state (robouse.backends.libero.solver, oracle kind libero_scripted)
agent:
  timeout_sec: 1800
verifier:
  timeout_sec: 120
robouse:
  id: libero-pro-spatial-task-7
  backend: libero
  suite: libero_spatial_task
  env: libero_spatial_task:7
  task_index: 7
  seed: 1
  max_steps: 1000
  camera: agentview
  cameras:
  - agentview
  - robot0_eye_in_hand
  image_size: 256
  settle_steps: 10
  skills: true
  success_mode: first
  obs_mode: vision
  visible_fields:
  - hand_pos
  - eef_quat
  - eef_axis_angle
  - gripper_qpos
  - gripper_open
  init_mode: saved
  init_states:
    url: https://raw.githubusercontent.com/uynitsuj/LIBERO-PRO/47aaa8038930bcdc84ab9ea2867e2ffc8039ab4a/libero/libero/init_files/libero_spatial_task/pick_up_the_black_bowl_on_the_stove_and_place_it_on_the_plate.pruned_init
    sha256: 8026fd8590bfe784b5d01a902cb49a8dd341e0dd000998f0338510f40828dca4
    count: 50
  init_index: 0
  init_state:
  - 0.0
  - 0.0
  - -0.161037389
  - 0.0
  - -2.44459747
  - 0.0
  - 2.2267522
  - 0.7853981633974483
  - 0.020833
  - -0.020833
  - -0.26874982154945626
  - -0.13646276085881948
  - 1.01
  - 0.7071067811865475
  - 0.0
  - 0.0
  - 0.7071067811865476
  - 0.03774802904010868
  - -0.2717425970597773
  - 1.2315200000000002
  - 0.7071067811865475
  - 0.0
  - 0.0
  - 0.7071067811865476
  - 0.06752928664376731
  - 0.022707087082726667
  - 0.97
  - 0.7071067811865475
  - 0.0
  - 0.0
  - 0.7071067811865476
  - -0.2103192760192386
  - 0.21267816153584643
  - 0.97
  - 0.7071067811865475
  - 0.0
  - 0.0
  - 0.7071067811865476
  - 0.0471099137009143
  - 0.18922803785728626
  - 0.97
  - 0.7071067811865475
  - 0.0
  - 0.0
  - 0.7071067811865476
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  - 0.0
  bddl: "(define (problem LIBERO_Tabletop_Manipulation)\n  (:domain robosuite)\n  (:language Pick the akita black bowl on the top of the cabinet and place it on the plate)\n    (:regions\n      (plate_region\n          (:target main_table)\n          (:ranges (\n              (0.05 0.19 0.07 0.21)\n            )\n          )\n      )\n      (next_to_plate_region\n          (:target main_table)\n          (:ranges (\n              (0.0 0.3 0.02 0.32)\n            )\n          )\n      )\n      (box_region\n          (:target main_table)\n          (:ranges (\n              (0.06 0.02 0.08 0.04)\n            )\n          )\n      )\n      (next_to_box_region\n          (:target main_table)\n          (:ranges (\n              (0.12 -0.08 0.14 -0.06)\n            )\n          )\n      )\n      (between_plate_ramekin_region\n          (:target main_table)\n          (:ranges (\n              (-0.06 0.19 -0.04 0.21)\n            )\n          )\n      )\n      (ramekin_region\n          (:target main_table)\n          (:ranges (\n              (-0.21 0.19 -0.19 0.21)\n            )\n          )\n      )\n      (next_to_ramekin_region\n          (:target main_table)\n          (:ranges (\n              (-0.19 0.31 -0.17 0.33)\n            )\n          )\n      )\n      (table_center\n          (:target main_table)\n          (:ranges (\n              (-0.1 -0.01 -0.05 0.01)\n            )\n          )\n      )\n      (table_front\n          (:target main_table)\n          (:ranges (\n              (0.19 -0.01 0.21 0.01)\n            )\n          )\n      )\n      (cabinet_region\n          (:target main_table)\n          (:ranges (\n              (0.02 -0.28 0.04 -0.26)\n            )\n          )\n          (:yaw_rotation (\n              (2.6613777765410678 2.7242096296128633)\n            )\n          )\n      )\n      (stove_region\n          (:target main_table)\n          (:ranges (\n              (-0.42 -0.15 -0.4 -0.13)\n            )\n          )\n      )\n      (top_region\n          (:target wooden_cabinet_1)\n      )\n      (middle_region\n          (:target wooden_cabinet_1)\n      )\n      (bottom_region\n          (:target wooden_cabinet_1)\n      )\n      (top_side\n          (:target wooden_cabinet_1)\n      )\n      (cook_region\n          (:target flat_stove_1)\n      )\n    )\n\n  (:fixtures\n    main_table - table\n    wooden_cabinet_1 - wooden_cabinet\n    flat_stove_1 - flat_stove\n  )\n\n  (:objects\n    akita_black_bowl_1 akita_black_bowl_2 - akita_black_bowl\n    cookies_1 - cookies\n    glazed_rim_porcelain_ramekin_1 - glazed_rim_porcelain_ramekin\n    plate_1 - plate\n  )\n\n  (:obj_of_interest\n  akita_black_bowl_2\n  plate_1\n)\n\n  (:init\n    (On akita_black_bowl_1 flat_stove_1_cook_region)\n    (On akita_black_bowl_2 wooden_cabinet_1_top_side)\n    (On plate_1 main_table_plate_region)\n    (On cookies_1 main_table_box_region)\n    (On glazed_rim_porcelain_ramekin_1 main_table_ramekin_region)\n    (On wooden_cabinet_1 main_table_cabinet_region)\n    (On flat_stove_1 main_table_stove_region)\n  )\n\n  (:goal\n  (And (On akita_black_bowl_2 plate_1))\n)\n\n)\n"
---

# Pick the akita black bowl on the top of the cabinet and place it on the plate

A Franka Panda arm with a parallel-jaw gripper works at a table in a LIBERO scene (MuJoCo / robosuite). The task is from LIBERO-PRO's `libero_spatial_task` suite: LIBERO-Spatial's scene, where the goal is a new one (LIBERO-PRO's task perturbation).

**Goal (LIBERO-PRO's language instruction):** Pick the akita black bowl on the top of the cabinet and place it on the plate

The episode ends as solved the moment LIBERO's own success check (the goal's predicates) passes; you do not need to call `robo done` after that. If you finish without the check passing, call `robo done` (or `robo give-up`).

## This robot

- The action has 7 numbers, not 4: `robo act DX DY DZ DROLL DPITCH DYAW GRIPPER`, each in [-1, 1]. It is LIBERO's delta end-effector command (robosuite's OSC_POSE controller, 20 steps per second). Holding DX/DY/DZ at 1.0 moves the hand about 1 cm per step; DROLL/DPITCH/DYAW rotate the hand about the world axes (1.0 asks for 0.5 rad); GRIPPER -1 opens, +1 closes.
- `robo move-to X Y Z [--grip G]` and `robo grip G` are available (they keep the hand's orientation).
- World frame, metres: +x points forward, away from the robot's base; +y is to the robot's left; +z is up. The table surface is at about z = 0.90.
- You see the scene only through the cameras. `robo observe` gives the robot's own state: `hand_pos` (end-effector position), `eef_quat` (orientation quaternion x, y, z, w) and `eef_axis_angle`, `gripper_qpos` (the two finger joints) and `gripper_open` (finger gap in metres, about 0.08 when fully open). It does not say where the objects are. Each `robo observe` also saves a 256x256 image from the front camera (`agentview`) and one from the wrist camera (`robot0_eye_in_hand`), and prints their paths; open them to look.
- `robo info` lists each camera with a 3x4 `projection` matrix P: for a world point (x, y, z), `[u*w, v*w, w] = P @ [x, y, z, 1]` gives its pixel (u, v) in that camera's saved image (u to the right, v down, origin at the top-left). The wrist camera moves with the hand: its matrix is for the hand's pose when you call `robo info`.
- The step budget is 1000 steps (50 seconds of simulated time).

## How to control the robot

You are the robot's policy. You act only through the `robo` command in your shell. There is no other way to move the robot, and you cannot read or change the simulator, the scoring, or other files to succeed; the episode server judges the final physical state itself.

```
robo info                         # action space, available skills, step budget
robo observe                      # robot and object state as numbers
robo observe --image              # also saves a camera image and prints its path (open it to look)
robo act DX DY DZ GRIP [--repeat N]   # low-level action, applied N times (N <= 50)
robo move-to X Y Z [--grip G]     # skill: move the gripper toward a point (if enabled for this task)
robo grip G [--steps N]           # skill: hold position and set the gripper (+1 close, -1 open)
robo done "short summary"         # end the episode and ask for scoring
robo give-up "reason"             # end the episode without claiming success
```

- Positions are in metres in the world frame (x, y on the table plane, z up).
- The episode has a fixed step budget (see `robo info`); every simulated step counts, including skills.
- Unless the task says otherwise, success is judged about 10 steps after you call `robo done`, with the robot holding still, so the goal must still be true when the robot stops.
- Work in small steps and re-observe after each motion. Call `robo done` exactly once when finished.
