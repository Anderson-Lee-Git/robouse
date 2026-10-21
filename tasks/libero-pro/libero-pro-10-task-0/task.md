---
schema_version: '1.3'
task:
  name: robouse/libero-pro-10-task-0
  description: Put both the cream cheese and the tomato sauce in the basket.
metadata:
  source_benchmark: LIBERO-PRO (Zhou et al. 2025), uynitsuj/LIBERO-PRO at 47aaa80, the commit NVIDIA's ASPIRE pins
  source_task: libero_10_task/LIVING_ROOM_SCENE2_put_both_the_alphabet_soup_and_the_tomato_sauce_in_the_basket.bddl
  suite: libero-pro
  libero_pro_suite: libero_10_task
  libero_pro_task_index: 0
  aspire_task_ref: libero_10_task:0
  language_instruction: put both the cream cheese and the tomato sauce in the basket
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
  id: libero-pro-10-task-0
  backend: libero
  suite: libero_10_task
  env: libero_10_task:0
  task_index: 0
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
    url: https://raw.githubusercontent.com/uynitsuj/LIBERO-PRO/47aaa8038930bcdc84ab9ea2867e2ffc8039ab4a/libero/libero/init_files/libero_10_task/LIVING_ROOM_SCENE2_put_both_the_alphabet_soup_and_the_tomato_sauce_in_the_basket.pruned_init
    sha256: 26c7d1bd640ae4d06a68c0b04bbfed789264226d290e33c3fa148b0a38b02b13
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
  - -0.1020351429728217
  - -0.15506133819686085
  - 0.45999999999999996
  - 0.0
  - 0.0
  - 0.7071067811865475
  - 0.7071067811865476
  - 0.0988386618413047
  - -0.1899496196332774
  - 0.445
  - 0.0
  - 0.0
  - 0.0
  - 1.0
  - -0.1025164694828232
  - 0.042753290874628466
  - 0.48
  - 0.0
  - 0.0
  - 0.7071067811865475
  - 0.7071067811865476
  - -0.24041870429595208
  - -0.14667993731124668
  - 0.48
  - 0.5
  - 0.5
  - 0.5
  - 0.5
  - 0.022495478707812024
  - -0.22556934099687076
  - 0.48
  - 0.5
  - 0.5
  - 0.5
  - 0.5
  - 0.048251263215106005
  - -0.0926385578602685
  - 0.48
  - 0.5
  - 0.5
  - 0.5
  - 0.5
  - 0.03858919287833464
  - 0.07349897678683753
  - 0.44
  - 0.0
  - 0.0
  - 0.0
  - 1.0
  - 0.0012674589496917531
  - 0.2631358437290998
  - 0.48
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
  bddl: "(define (problem LIBERO_Living_Room_Tabletop_Manipulation)\n  (:domain robosuite)\n  (:language put both the cream cheese and the tomato sauce in the basket)\n    (:regions\n      (basket_init_region\n          (:target living_room_table)\n          (:ranges (\n              (-0.01 0.25 0.01 0.27)\n            )\n          )\n          (:yaw_rotation (\n              (0.0 0.0)\n            )\n          )\n      )\n      (milk_init_region\n          (:target living_room_table)\n          (:ranges (\n              (0.025 -0.125 0.07500000000000001 -0.07500000000000001)\n            )\n          )\n          (:yaw_rotation (\n              (0.0 0.0)\n            )\n          )\n      )\n      (cream_cheese_init_region\n          (:target living_room_table)\n          (:ranges (\n              (0.07500000000000001 -0.225 0.125 -0.17500000000000002)\n            )\n          )\n          (:yaw_rotation (\n              (0.0 0.0)\n            )\n          )\n      )\n      (orange_juice_init_region\n          (:target living_room_table)\n          (:ranges (\n              (-0.025 -0.275 0.025 -0.225)\n            )\n          )\n          (:yaw_rotation (\n              (0.0 0.0)\n            )\n          )\n      )\n      (tomato_sauce_init_region\n          (:target living_room_table)\n          (:ranges (\n              (-0.125 0.025 -0.07500000000000001 0.07500000000000001)\n            )\n          )\n          (:yaw_rotation (\n              (0.0 0.0)\n            )\n          )\n      )\n      (alphabet_soup_init_region\n          (:target living_room_table)\n          (:ranges (\n              (-0.125 -0.175 -0.07500000000000001 -0.125)\n            )\n          )\n          (:yaw_rotation (\n              (0.0 0.0)\n            )\n          )\n      )\n      (butter_init_region\n          (:target living_room_table)\n          (:ranges (\n              (0.025 0.025 0.07500000000000001 0.07500000000000001)\n            )\n          )\n          (:yaw_rotation (\n              (0.0 0.0)\n            )\n          )\n      )\n      (ketchup_init_region\n          (:target living_room_table)\n          (:ranges (\n              (-0.275 -0.175 -0.225 -0.125)\n            )\n          )\n          (:yaw_rotation (\n              (0.0 0.0)\n            )\n          )\n      )\n      (contain_region\n          (:target basket_1)\n      )\n    )\n\n  (:fixtures\n    living_room_table - living_room_table\n  )\n\n  (:objects\n    alphabet_soup_1 - alphabet_soup\n    cream_cheese_1 - cream_cheese\n    tomato_sauce_1 - tomato_sauce\n    ketchup_1 - ketchup\n    orange_juice_1 - orange_juice\n    milk_1 - milk\n    butter_1 - butter\n    basket_1 - basket\n  )\n\n  (:obj_of_interest\n  cream_cheese_1\n  basket_1_contain_region\n  tomato_sauce_1\n)\n\n  (:init\n    (On alphabet_soup_1 living_room_table_alphabet_soup_init_region)\n    (On cream_cheese_1 living_room_table_cream_cheese_init_region)\n    (On tomato_sauce_1 living_room_table_tomato_sauce_init_region)\n    (On ketchup_1 living_room_table_ketchup_init_region)\n    (On milk_1 living_room_table_milk_init_region)\n    (On orange_juice_1 living_room_table_orange_juice_init_region)\n    (On butter_1 living_room_table_butter_init_region)\n    (On basket_1 living_room_table_basket_init_region)\n  )\n\n  (:goal\n  (And (In cream_cheese_1 basket_1_contain_region) (In tomato_sauce_1 basket_1_contain_region))\n)\n\n)\n"
---

# Put both the cream cheese and the tomato sauce in the basket

A Franka Panda arm with a parallel-jaw gripper works at a low table in a LIBERO scene (MuJoCo / robosuite). The task is from LIBERO-PRO's `libero_10_task` suite: LIBERO-Long's scene, where the goal is a new one (LIBERO-PRO's task perturbation).

**Goal (LIBERO-PRO's language instruction):** put both the cream cheese and the tomato sauce in the basket

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
