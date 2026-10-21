---
schema_version: '1.3'
task:
  name: robouse/libero-pro-10-task-5
  description: Pick up the cup and place it in the back compartment of the caddy.
metadata:
  source_benchmark: LIBERO-PRO (Zhou et al. 2025), uynitsuj/LIBERO-PRO at 47aaa80, the commit NVIDIA's ASPIRE pins
  source_task: libero_10_task/STUDY_SCENE1_pick_up_the_book_and_place_it_in_the_back_compartment_of_the_caddy.bddl
  suite: libero-pro
  libero_pro_suite: libero_10_task
  libero_pro_task_index: 5
  aspire_task_ref: libero_10_task:5
  language_instruction: pick up the cup and place it in the back compartment of the caddy
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
  id: libero-pro-10-task-5
  backend: libero
  suite: libero_10_task
  env: libero_10_task:5
  task_index: 5
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
    url: https://raw.githubusercontent.com/uynitsuj/LIBERO-PRO/47aaa8038930bcdc84ab9ea2867e2ffc8039ab4a/libero/libero/init_files/libero_10_task/STUDY_SCENE1_pick_up_the_book_and_place_it_in_the_back_compartment_of_the_caddy.pruned_init
    sha256: 4b6feef4808e4d3882115ff0c83b343f423ed551cf9b7b3499d8d546d9461e00
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
  - -0.1846646363452435
  - 0.1281116526105533
  - 0.937
  - -0.5995089343241005
  - 0.0
  - 0.0
  - 0.8003680638716049
  - -0.09546473836622014
  - 0.010473174614608172
  - 0.937
  - -0.7071067811865475
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
  bddl: "(define (problem LIBERO_Study_Tabletop_Manipulation)\n  (:domain robosuite)\n  (:language pick up the cup and place it in the back compartment of the caddy)\n    (:regions\n      (desk_caddy_init_region\n          (:target study_table)\n          (:ranges (\n              (-0.21000000000000002 -0.15000000000000002 -0.19 -0.13)\n            )\n          )\n          (:yaw_rotation (\n              (3.141592653589793 3.141592653589793)\n            )\n          )\n      )\n      (black_book_init_region\n          (:target study_table)\n          (:ranges (\n              (-0.025 0.125 0.025 0.175)\n            )\n          )\n          (:yaw_rotation (\n              (-1.5707963267948966 -0.7853981633974483)\n            )\n          )\n      )\n      (white_yellow_mug_init_region\n          (:target study_table)\n          (:ranges (\n              (0.07500000000000001 -0.025 0.125 0.025)\n            )\n          )\n          (:yaw_rotation (\n              (0.0 0.0)\n            )\n          )\n      )\n      (desk_caddy_right_region\n          (:target study_table)\n          (:ranges (\n              (-0.25 0.09999999999999999 -0.15000000000000002 0.2)\n            )\n          )\n          (:yaw_rotation (\n              (3.141592653589793 3.141592653589793)\n            )\n          )\n      )\n      (right_contain_region\n          (:target desk_caddy_1)\n      )\n      (left_contain_region\n          (:target desk_caddy_1)\n      )\n      (back_contain_region\n          (:target desk_caddy_1)\n      )\n      (front_contain_region\n          (:target desk_caddy_1)\n      )\n    )\n\n  (:fixtures\n    study_table - study_table\n    desk_caddy_1 - desk_caddy\n  )\n\n  (:objects\n    black_book_1 - black_book\n    white_yellow_mug_1 - white_yellow_mug\n  )\n\n  (:obj_of_interest\n  white_yellow_mug_1\n  desk_caddy_1_back_contain_region\n)\n\n  (:init\n    (On desk_caddy_1 study_table_desk_caddy_init_region)\n    (On black_book_1 study_table_black_book_init_region)\n    (On white_yellow_mug_1 study_table_white_yellow_mug_init_region)\n  )\n\n  (:goal\n  (And (In white_yellow_mug_1 desk_caddy_1_back_contain_region))\n)\n\n)\n"
---

# Pick up the cup and place it in the back compartment of the caddy

A Franka Panda arm with a parallel-jaw gripper works at a desk in a LIBERO scene (MuJoCo / robosuite). The task is from LIBERO-PRO's `libero_10_task` suite: LIBERO-Long's scene, where the goal is a new one (LIBERO-PRO's task perturbation).

**Goal (LIBERO-PRO's language instruction):** pick up the cup and place it in the back compartment of the caddy

The episode ends as solved the moment LIBERO's own success check (the goal's predicates) passes; you do not need to call `robo done` after that. If you finish without the check passing, call `robo done` (or `robo give-up`).

## This robot

- The action has 7 numbers, not 4: `robo act DX DY DZ DROLL DPITCH DYAW GRIPPER`, each in [-1, 1]. It is LIBERO's delta end-effector command (robosuite's OSC_POSE controller, 20 steps per second). Holding DX/DY/DZ at 1.0 moves the hand about 1 cm per step; DROLL/DPITCH/DYAW rotate the hand about the world axes (1.0 asks for 0.5 rad); GRIPPER -1 opens, +1 closes.
- `robo move-to X Y Z [--grip G]` and `robo grip G` are available (they keep the hand's orientation).
- World frame, metres: +x points forward, away from the robot's base; +y is to the robot's left; +z is up. The desk surface is at about z = 0.88.
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
