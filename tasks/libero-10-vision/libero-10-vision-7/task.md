---
schema_version: '1.3'
task:
  name: robouse/libero-10-vision-7
  description: Put both the alphabet soup and the cream cheese box in the basket.
metadata:
  source_benchmark: LIBERO (Liu et al. 2023)
  source_task: LIVING_ROOM_SCENE1_put_both_the_alphabet_soup_and_the_cream_cheese_box_in_the_basket
  suite: libero-10-vision
  libero_suite: libero_10
  libero_task_index: 7
  language_instruction: put both the alphabet soup and the cream cheese box in the basket
  category: manipulation
  difficulty: hard
  tags:
  - franka
  - mujoco
  - robosuite
  - single-arm
  - language
  - vision
  reference_solution: none (LIBERO publishes none for its benchmark start states, and robouse has none for them)
  suite_version: 1.0.0
  protocol: image-only (two 256x256 cameras and the robot's own state); LIBERO benchmark init state n for seed n (run with
    --seeds 0-9); 900 steps; as arXiv 2610.30051
agent:
  timeout_sec: 2400
verifier:
  timeout_sec: 120
robouse:
  id: libero-10-vision-7
  backend: libero
  suite: libero_10
  env: LIVING_ROOM_SCENE1_put_both_the_alphabet_soup_and_the_cream_cheese_box_in_the_basket
  task_index: 7
  seed: 0
  max_steps: 900
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
---

# Put both the alphabet soup and the cream cheese box in the basket

A Franka Panda arm with a parallel-jaw gripper works at a low table in a LIBERO scene (MuJoCo / robosuite). The task is LIBERO-Long's (`libero_10`): long-horizon tasks, most with two sub-goals.

**Goal (LIBERO's language instruction):** put both the alphabet soup and the cream cheese box in the basket

The episode ends as solved the moment LIBERO's own success check (the goal's predicates) passes; you do not need to call `robo done` after that. If you finish without the check passing, call `robo done` (or `robo give-up`).

## This robot

- The action has 7 numbers, not 4: `robo act DX DY DZ DROLL DPITCH DYAW GRIPPER`, each in [-1, 1]. It is LIBERO's delta end-effector command (robosuite's OSC_POSE controller, 20 steps per second). Holding DX/DY/DZ at 1.0 moves the hand about 1 cm per step; DROLL/DPITCH/DYAW rotate the hand about the world axes (1.0 asks for 0.5 rad); GRIPPER -1 opens, +1 closes.
- `robo move-to X Y Z [--grip G]` and `robo grip G` are available (they keep the hand's orientation).
- World frame, metres: +x points forward, away from the robot's base; +y is to the robot's left; +z is up. The table surface is at about z = 0.43.
- You see the scene only through the cameras. `robo observe` gives the robot's own state: `hand_pos` (end-effector position), `eef_quat` (orientation quaternion x, y, z, w) and `eef_axis_angle`, `gripper_qpos` (the two finger joints) and `gripper_open` (finger gap in metres, about 0.08 when fully open). It does not say where the objects are. Each `robo observe` also saves a 256x256 image from the front camera (`agentview`) and one from the wrist camera (`robot0_eye_in_hand`), and prints their paths; open them to look.
- `robo info` lists each camera with a 3x4 `projection` matrix P: for a world point (x, y, z), `[u*w, v*w, w] = P @ [x, y, z, 1]` gives its pixel (u, v) in that camera's saved image (u to the right, v down, origin at the top-left). The wrist camera moves with the hand: its matrix is for the hand's pose when you call `robo info`.
- The step budget is 900 steps (45 seconds of simulated time).

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
