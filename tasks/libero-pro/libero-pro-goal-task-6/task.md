---
schema_version: '1.3'
task:
  name: robouse/libero-pro-goal-task-6
  description: Put the wine bottle in the bowl.
metadata:
  source_benchmark: LIBERO-PRO (Zhou et al. 2025), uynitsuj/LIBERO-PRO at 47aaa80, the commit NVIDIA's ASPIRE pins
  source_task: libero_goal_task/put_the_cream_cheese_in_the_bowl.bddl
  suite: libero-pro
  libero_pro_suite: libero_goal_task
  libero_pro_task_index: 6
  aspire_task_ref: libero_goal_task:6
  language_instruction: put the wine bottle in the bowl
  category: manipulation
  difficulty: medium
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
  id: libero-pro-goal-task-6
  backend: libero
  suite: libero_goal_task
  env: libero_goal_task:6
  task_index: 6
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
    url: https://raw.githubusercontent.com/uynitsuj/LIBERO-PRO/47aaa8038930bcdc84ab9ea2867e2ffc8039ab4a/libero/libero/init_files/libero_goal_task/put_the_cream_cheese_in_the_bowl.pruned_init
    sha256: 8beb8a6afa57c15148a5758565a5070ce1370424572a42081b6fc561be5417ee
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
  - -0.09409514170071594
  - -0.014708566181866079
  - 0.97
  - 0.7071067811865475
  - 0.0
  - 0.0
  - 0.7071067811865476
  - -0.06564203773739176
  - 0.12911176616748585
  - 0.935
  - 0.0
  - 0.0
  - 0.0
  - 1.0
  - -0.18636100334557137
  - -0.052453522987139185
  - 0.97
  - 0.0
  - 0.0
  - 0.0
  - 1.0
  - 0.05748103702137654
  - -0.01266490521466498
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
  bddl: "(define (problem LIBERO_Tabletop_Manipulation)\n  (:domain robosuite)\n  (:language put the wine bottle in the bowl)\n    (:regions\n      (plate_region\n          (:target main_table)\n          (:ranges (\n              (0.04 -0.03 0.060000000000000005 -0.01)\n            )\n          )\n      )\n      (akita_black_bowl_region\n          (:target main_table)\n          (:ranges (\n              (-0.09999999999999999 -0.01 -0.08 0.01)\n            )\n          )\n      )\n      (wine_bottle_region\n          (:target main_table)\n          (:ranges (\n              (-0.21000000000000002 -0.060000000000000005 -0.19 -0.04)\n            )\n          )\n      )\n      (cream_cheese_region\n          (:target main_table)\n          (:ranges (\n              (-0.060000000000000005 0.12000000000000001 -0.04 0.14)\n            )\n          )\n      )\n      (stove_front_region\n          (:target main_table)\n          (:ranges (\n              (-0.09 0.16999999999999998 -0.010000000000000002 0.25)\n            )\n          )\n      )\n      (cabinet_region\n          (:target main_table)\n          (:ranges (\n              (0.02 -0.25 0.04 -0.23)\n            )\n          )\n          (:yaw_rotation (\n              (3.141592653589793 3.141592653589793)\n            )\n          )\n      )\n      (stove_region\n          (:target main_table)\n          (:ranges (\n              (-0.42 0.2 -0.4 0.22)\n            )\n          )\n      )\n      (wine_rack_region\n          (:target main_table)\n          (:ranges (\n              (-0.27 -0.27 -0.25 -0.25)\n            )\n          )\n          (:yaw_rotation (\n              (3.141592653589793 3.141592653589793)\n            )\n          )\n      )\n      (top_region\n          (:target wooden_cabinet_1)\n      )\n      (middle_region\n          (:target wooden_cabinet_1)\n      )\n      (bottom_region\n          (:target wooden_cabinet_1)\n      )\n      (top_side\n          (:target wooden_cabinet_1)\n      )\n      (cook_region\n          (:target flat_stove_1)\n      )\n      (right_region\n          (:target bowl_drainer_1)\n      )\n      (left_region\n          (:target bowl_drainer_1)\n      )\n      (top_region\n          (:target wine_rack_1)\n      )\n    )\n\n  (:fixtures\n    main_table - table\n    wooden_cabinet_1 - wooden_cabinet\n    flat_stove_1 - flat_stove\n    wine_rack_1 - wine_rack\n  )\n\n  (:objects\n    akita_black_bowl_1 - akita_black_bowl\n    cream_cheese_1 - cream_cheese\n    wine_bottle_1 - wine_bottle\n    plate_1 - plate\n  )\n\n  (:obj_of_interest\n  wine_bottle_1\n  akita_black_bowl_1\n)\n\n  (:init\n    (On wine_bottle_1 main_table_wine_bottle_region)\n    (On akita_black_bowl_1 main_table_akita_black_bowl_region)\n    (On plate_1 main_table_plate_region)\n    (On cream_cheese_1 main_table_cream_cheese_region)\n    (On wooden_cabinet_1 main_table_cabinet_region)\n    (On flat_stove_1 main_table_stove_region)\n    (On wine_rack_1 main_table_wine_rack_region)\n  )\n\n  (:goal\n  (And (On wine_bottle_1 akita_black_bowl_1))\n)\n\n)\n"
---

# Put the wine bottle in the bowl

A Franka Panda arm with a parallel-jaw gripper works at a table in a LIBERO scene (MuJoCo / robosuite). The task is from LIBERO-PRO's `libero_goal_task` suite: LIBERO-Goal's scene, where the goal is a new one (LIBERO-PRO's task perturbation).

**Goal (LIBERO-PRO's language instruction):** put the wine bottle in the bowl

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
