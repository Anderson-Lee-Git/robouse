---
schema_version: '1.3'
task:
  name: robouse/libero-10-vision-9-joint
  description: Put the yellow and white mug in the microwave and close it.
metadata:
  source_benchmark: LIBERO (Liu et al. 2023)
  source_task: KITCHEN_SCENE6_put_the_yellow_and_white_mug_in_the_microwave_and_close_it
  suite: libero-10-joint
  libero_suite: libero_10
  libero_task_index: 9
  language_instruction: put the yellow and white mug in the microwave and close it
  category: manipulation
  difficulty: hard
  tags:
  - franka
  - mujoco
  - robosuite
  - single-arm
  - language
  - vision
  - joint-control
  reference_solution: none (the scripted LIBERO solution commands the hand (OSC_POSE), and none is written for joint control)
  suite_version: 1.0.0
  protocol: image-only (two 256x256 cameras and the robot's own state); LIBERO benchmark init state n for seed n (run with
    --seeds 0-9); 900 steps; as arXiv 2610.30051
  source_suite: libero-10-vision
  control: joint
agent:
  timeout_sec: 2400
verifier:
  timeout_sec: 120
robouse:
  id: libero-10-vision-9-joint
  backend: libero
  suite: libero_10
  env: KITCHEN_SCENE6_put_the_yellow_and_white_mug_in_the_microwave_and_close_it
  task_index: 9
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
  - joint_pos
  control: joint
  joint_controller:
    kp: 150.0
    output_max: 0.2
---

# Put the yellow and white mug in the microwave and close it

A Franka Panda arm with a parallel-jaw gripper works at a low table in a LIBERO scene (MuJoCo / robosuite). The task is LIBERO-Long's (`libero_10`): long-horizon tasks, most with two sub-goals.

**Goal (LIBERO's language instruction):** put the yellow and white mug in the microwave and close it

The episode ends as solved the moment LIBERO's own success check (the goal's predicates) passes; you do not need to call `robo done` after that. If you finish without the check passing, call `robo done` (or `robo give-up`).

## This robot

- The action has 8 numbers, not 4: `robo act DQ1 DQ2 DQ3 DQ4 DQ5 DQ6 DQ7 GRIPPER`, each in [-1, 1]. It is a delta joint-position command for the arm's seven joints (robosuite's JOINT_POSITION controller, 20 steps per second): 1.0 on DQi asks for 0.2 rad on joint i in one step, and the arm lags behind, so holding one DQi at 1.0 turns that joint about 0.045 rad per step; a full command on several joints moves the hand about 1 cm per step. GRIPPER -1 opens, +1 closes.
- `robo move-joints-to Q1 Q2 Q3 Q4 Q5 Q6 Q7 [--grip G]` (absolute joint angles in rad, within the limits `robo info` lists) and `robo grip G` are available. There is no `robo move-to`: the arm is commanded only through its joints.
- World frame, metres: +x points forward, away from the robot's base; +y is to the robot's left; +z is up. The table surface is at about z = 0.43.
- You see the scene only through the cameras. `robo observe` gives the robot's own state: `hand_pos` (end-effector position), `eef_quat` (orientation quaternion x, y, z, w) and `eef_axis_angle`, `gripper_qpos` (the two finger joints), `gripper_open` (finger gap in metres, about 0.08 when fully open) and `joint_pos` (the seven arm joint angles in rad, from joint 1 at the base to joint 7, which turns the hand). It does not say where the objects are. Each `robo observe` also saves a 256x256 image from the front camera (`agentview`) and one from the wrist camera (`robot0_eye_in_hand`), and prints their paths; open them to look.
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
