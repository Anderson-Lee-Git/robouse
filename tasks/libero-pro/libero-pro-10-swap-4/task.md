---
schema_version: '1.3'
task:
  name: robouse/libero-pro-10-swap-4
  description: Put the white mug on the left plate and put the yellow and white mug on the right plate.
metadata:
  source_benchmark: LIBERO-PRO (Zhou et al. 2025), uynitsuj/LIBERO-PRO at 47aaa80, the commit NVIDIA's ASPIRE pins
  source_task: libero_10_swap/LIVING_ROOM_SCENE5_put_the_white_mug_on_the_left_plate_and_put_the_yellow_and_white_mug_on_the_right_plate.bddl
  suite: libero-pro
  libero_pro_suite: libero_10_swap
  libero_pro_task_index: 4
  aspire_task_ref: libero_10_swap:4
  language_instruction: put the white mug on the left plate and put the yellow and white mug on the right plate
  category: manipulation
  difficulty: hard
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
  timeout_sec: 2400
verifier:
  timeout_sec: 120
robouse:
  id: libero-pro-10-swap-4
  backend: libero
  suite: libero_10_swap
  env: libero_10_swap:4
  task_index: 4
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
    url: https://raw.githubusercontent.com/uynitsuj/LIBERO-PRO/47aaa8038930bcdc84ab9ea2867e2ffc8039ab4a/libero/libero/init_files/libero_10_swap/LIVING_ROOM_SCENE5_put_the_white_mug_on_the_left_plate_and_put_the_yellow_and_white_mug_on_the_right_plate.pruned_init
    sha256: 26f4ccea4e65737ffd94e5219050729d2d2a67aa8e7d13033a73bc4598e3e187
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
  - -0.0866866653768725
  - -0.1383364865015595
  - 0.48
  - -0.7071067811865476
  - 0.0
  - 0.0
  - 0.7071067811865477
  - -0.07196125287900138
  - 0.10980059384042459
  - 0.48
  - -0.7071067811865476
  - 0.0
  - 0.0
  - 0.7071067811865477
  - -0.21687557736488666
  - 0.016140686478815912
  - 0.48
  - -0.7071067811865476
  - 0.0
  - 0.0
  - 0.7071067811865477
  - -0.0156479897174416
  - -0.3137210648475632
  - 0.48
  - 0.7071067811865476
  - 0.0
  - 0.0
  - 0.7071067811865477
  - 0.011760010299773214
  - 0.28943033523239936
  - 0.48
  - 0.7071067811865476
  - 0.0
  - 0.0
  - 0.7071067811865477
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
  bddl: "(define (problem LIBERO_Living_Room_Tabletop_Manipulation)\n  (:domain robosuite)\n  (:language put the white mug on the left plate and put the yellow and white mug on the right plate)\n    (:regions\n      (plate_left_region\n          (:target living_room_table)\n          (:ranges (\n              (-0.025 -0.325 0.025 -0.27499999999999997)\n            )\n          )\n          (:yaw_rotation (\n              (0.0 0.0)\n            )\n          )\n      )\n      (plate_right_region\n          (:target living_room_table)\n          (:ranges (\n              (-0.025 0.27499999999999997 0.025 0.325)\n            )\n          )\n          (:yaw_rotation (\n              (0.0 0.0)\n            )\n          )\n      )\n      (porcelain_mug_init_region\n          (:target living_room_table)\n          (:ranges (\n              (-0.125 -0.175 -0.07500000000000001 -0.125)\n            )\n          )\n          (:yaw_rotation (\n              (0.0 0.0)\n            )\n          )\n      )\n      (white_yellow_mug_init_region\n          (:target living_room_table)\n          (:ranges (\n              (-0.07500000000000001 0.07500000000000001 -0.025 0.125)\n            )\n          )\n          (:yaw_rotation (\n              (0.0 0.0)\n            )\n          )\n      )\n      (red_coffee_mug_init_region\n          (:target living_room_table)\n          (:ranges (\n              (-0.225 -0.025 -0.17500000000000002 0.025)\n            )\n          )\n          (:yaw_rotation (\n              (0.0 0.0)\n            )\n          )\n      )\n    )\n\n  (:fixtures\n    living_room_table - living_room_table\n  )\n\n  (:objects\n    porcelain_mug_1 - porcelain_mug\n    red_coffee_mug_1 - red_coffee_mug\n    white_yellow_mug_1 - white_yellow_mug\n    plate_1 plate_2 - plate\n  )\n\n  (:obj_of_interest\n    plate_1\n    plate_2\n    white_yellow_mug_1\n    porcelain_mug_1\n  )\n\n  (:init\n    (On plate_1 living_room_table_plate_left_region)\n    (On plate_2 living_room_table_plate_right_region)\n    (On red_coffee_mug_1 living_room_table_white_yellow_mug_init_region)\n    (On white_yellow_mug_1 living_room_table_red_coffee_mug_init_region)\n    (On porcelain_mug_1 living_room_table_porcelain_mug_init_region)\n  )\n\n  (:goal\n    (And (On porcelain_mug_1 plate_1) (On white_yellow_mug_1 plate_2))\n  )\n\n)\n"
---

# Put the white mug on the left plate and put the yellow and white mug on the right plate

A Franka Panda arm with a parallel-jaw gripper works at a low table in a LIBERO scene (MuJoCo / robosuite). The task is from LIBERO-PRO's `libero_10_swap` suite: LIBERO-Long's scene, where the objects start in other places (LIBERO-PRO's position perturbation).

**Goal (LIBERO-PRO's language instruction):** put the white mug on the left plate and put the yellow and white mug on the right plate

The episode ends as solved the moment LIBERO's own success check (the goal's predicates) passes; you do not need to call `robo done` after that. If you finish without the check passing, call `robo done` (or `robo give-up`).

## This robot

- The action has 7 numbers, not 4: `robo act DX DY DZ DROLL DPITCH DYAW GRIPPER`, each in [-1, 1]. It is LIBERO's delta end-effector command (robosuite's OSC_POSE controller, 20 steps per second). Holding DX/DY/DZ at 1.0 moves the hand about 1 cm per step; DROLL/DPITCH/DYAW rotate the hand about the world axes (1.0 asks for 0.5 rad); GRIPPER -1 opens, +1 closes.
- `robo move-to X Y Z [--grip G]` and `robo grip G` are available (they keep the hand's orientation).
- World frame, metres: +x points forward, away from the robot's base; +y is to the robot's left; +z is up. The table surface is at about z = 0.43.
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
