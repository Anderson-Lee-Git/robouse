---
schema_version: '1.3'
task:
  name: robouse/libero-pro-object-task-9
  description: Pick the chocolate pudding and place it in the basket.
metadata:
  source_benchmark: LIBERO-PRO (Zhou et al. 2025), uynitsuj/LIBERO-PRO at 47aaa80, the commit NVIDIA's ASPIRE pins
  source_task: libero_object_task/pick_up_the_orange_juice_and_place_it_in_the_basket.bddl
  suite: libero-pro
  libero_pro_suite: libero_object_task
  libero_pro_task_index: 9
  aspire_task_ref: libero_object_task:9
  language_instruction: Pick the chocolate pudding and place it in the basket
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
  id: libero-pro-object-task-9
  backend: libero
  suite: libero_object_task
  env: libero_object_task:9
  task_index: 9
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
    url: https://raw.githubusercontent.com/uynitsuj/LIBERO-PRO/47aaa8038930bcdc84ab9ea2867e2ffc8039ab4a/libero/libero/init_files/libero_object_task/pick_up_the_orange_juice_and_place_it_in_the_basket.pruned_init
    sha256: d67f7ee29ecbc78bed38293d236d9d7f8c7bff70e491b4a40d006659056107b8
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
  - 0.05000000000000001
  - -0.1
  - 0.034999999999999996
  - 0.5
  - 0.5
  - 0.5
  - 0.5
  - -0.009347608003432534
  - 0.26437806459219754
  - 0.034999999999999996
  - 0.7071067811865475
  - 0.0
  - 0.0
  - 0.7071067811865476
  - -0.11788625735864734
  - -0.24054458539999532
  - -0.005000000000000001
  - 0.0
  - 0.0
  - 0.0
  - 1.0
  - -0.15
  - 0.05999999999999999
  - 0.034999999999999996
  - 0.0
  - 0.0
  - 0.0
  - 1.0
  - 0.09370318615681388
  - -0.20395105677436762
  - 0.034999999999999996
  - 0.7071067811865475
  - 0.0
  - 0.0
  - 0.7071067811865476
  - 0.15
  - 0.03
  - 0.034999999999999996
  - 0.5
  - 0.5
  - 0.5
  - 0.5
  - -0.2
  - -0.08
  - 0.034999999999999996
  - 0.5
  - 0.5
  - 0.5
  - 0.5
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
  bddl: "(define (problem LIBERO_Floor_Manipulation)\n  (:domain robosuite)\n  (:language Pick the chocolate pudding and place it in the basket)\n    (:regions\n      (bin_region\n          (:target floor)\n          (:ranges (\n              (-0.01 0.25 0.01 0.27)\n            )\n          )\n      )\n      (target_object_region\n          (:target floor)\n          (:ranges (\n              (0.025 -0.125 0.07500000000000001 -0.07500000000000001)\n            )\n          )\n      )\n      (other_object_region_0\n          (:target floor)\n          (:ranges (\n              (-0.145 -0.265 -0.095 -0.215)\n            )\n          )\n      )\n      (other_object_region_1\n          (:target floor)\n          (:ranges (\n              (-0.175 0.034999999999999996 -0.125 0.08499999999999999)\n            )\n          )\n      )\n      (other_object_region_2\n          (:target floor)\n          (:ranges (\n              (0.07500000000000001 -0.225 0.125 -0.17500000000000002)\n            )\n          )\n      )\n      (other_object_region_3\n          (:target floor)\n          (:ranges (\n              (0.125 0.0049999999999999975 0.175 0.055)\n            )\n          )\n      )\n      (other_object_region_4\n          (:target floor)\n          (:ranges (\n              (-0.225 -0.10500000000000001 -0.17500000000000002 -0.055)\n            )\n          )\n      )\n      (contain_region\n          (:target basket_1)\n      )\n    )\n\n  (:fixtures\n    floor - floor\n  )\n\n  (:objects\n    orange_juice_1 - orange_juice\n    basket_1 - basket\n    butter_1 - butter\n    chocolate_pudding_1 - chocolate_pudding\n    bbq_sauce_1 - bbq_sauce\n    ketchup_1 - ketchup\n    salad_dressing_1 - salad_dressing\n  )\n\n  (:obj_of_interest\n  chocolate_pudding_1\n  basket_1_contain_region\n)\n\n  (:init\n    (On orange_juice_1 floor_target_object_region)\n    (On butter_1 floor_other_object_region_0)\n    (On chocolate_pudding_1 floor_other_object_region_1)\n    (On bbq_sauce_1 floor_other_object_region_2)\n    (On ketchup_1 floor_other_object_region_3)\n    (On salad_dressing_1 floor_other_object_region_4)\n    (On basket_1 floor_bin_region)\n  )\n\n  (:goal\n  (And (In chocolate_pudding_1 basket_1_contain_region))\n)\n\n)\n"
---

# Pick the chocolate pudding and place it in the basket

A Franka Panda arm with a parallel-jaw gripper works over the floor in a LIBERO scene (MuJoCo / robosuite). The task is from LIBERO-PRO's `libero_object_task` suite: LIBERO-Object's scene, where the goal is a new one (LIBERO-PRO's task perturbation).

**Goal (LIBERO-PRO's language instruction):** Pick the chocolate pudding and place it in the basket

The episode ends as solved the moment LIBERO's own success check (the goal's predicates) passes; you do not need to call `robo done` after that. If you finish without the check passing, call `robo done` (or `robo give-up`).

## This robot

- The action has 7 numbers, not 4: `robo act DX DY DZ DROLL DPITCH DYAW GRIPPER`, each in [-1, 1]. It is LIBERO's delta end-effector command (robosuite's OSC_POSE controller, 20 steps per second). Holding DX/DY/DZ at 1.0 moves the hand about 1 cm per step; DROLL/DPITCH/DYAW rotate the hand about the world axes (1.0 asks for 0.5 rad); GRIPPER -1 opens, +1 closes.
- `robo move-to X Y Z [--grip G]` and `robo grip G` are available (they keep the hand's orientation).
- World frame, metres: +x points forward, away from the robot's base; +y is to the robot's left; +z is up. The objects stand on the floor, at about z = 0.0.
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
