---
schema_version: '1.3'
task:
  name: robouse/robocasa-vision-turn-on-toaster-kitchen8
  description: Turn on the toaster in RoboCasa kitchen layout 8 (Franka Panda on a mobile base).
metadata:
  source_benchmark: RoboCasa (RoboCasa365, robosuite 1.5)
  source_task: TurnOnToaster
  suite: robocasa-vision
  category: manipulation
  difficulty: medium
  tags:
  - mujoco
  - robocasa
  - kitchen
  - panda
  - mobile-manipulator
  - appliance
  - lever
  - toaster
  - vision
  suite_version: 1.0.0
agent:
  timeout_sec: 2400
verifier:
  timeout_sec: 120
robouse:
  id: robocasa-vision-turn-on-toaster-kitchen8
  backend: robocasa
  env: robocasa-turn-on-toaster-kitchen8
  seed: 0
  max_steps: 300
  camera: robot0_agentview_left
  cameras:
  - robot0_agentview_left
  - robot0_agentview_right
  - robot0_eye_in_hand
  skills: true
  success_mode: final
  obs_mode: vision
  visible_fields:
  - hand_pos
  - hand_target
  - gripper_open
  - robot_base_pos
  - robot_forward
  - task_instruction
---

# Turn on the toaster (RoboCasa kitchen 8)

A household kitchen from RoboCasa (kitchen layout 8, style 8): counters, cabinets, drawers, a sink and appliances, simulated in MuJoCo. The robot is a Franka Panda arm on a mobile base (RoboCasa's PandaOmron), parked where RoboCasa's task set-up puts it, facing the relevant fixture; the base and torso do not move in this task, only the arm and its two-finger gripper (fingers open to 8 cm). World frame in metres, z up; `robot_forward` in `robo observe` is the horizontal direction the robot faces. The arm's reach from the parked base is limited (about 0.7 m forward of `robot_base_pos` at counter height, less low down or far to the side), and the arm and hand can collide with the counter and fixtures.

**Goal:** A slice of bread is in the toaster. Push the toaster's lever down to turn it on.

**Success:** RoboCasa's own check for TurnOnToaster: the toaster slot holding the bread is on. The toaster switches on when its lever is pushed down to at least 90 % of its travel (about 6 cm), then holds the lever down by itself for 500 steps (25 s) and pops it back up, so call `robo done` soon after it is on. Success is judged by the episode server after you call `robo done` and the robot has held still for about 10 steps.

**Controls.** `robo act DX DY DZ GRIP` moves the gripper's commanded target by DX, DY, DZ times 2 cm per step along the WORLD x, y, z axes (each in [-1, 1]); the gripper keeps its orientation (pointing straight down). GRIP 0 keeps the fingers as they are, any positive value closes them, and a negative value -f opens them to fraction f (-1 fully open). One step is 50 ms (RoboCasa's 20 Hz control rate). The arm follows the target through RoboCasa's operational-space controller; the target stays within 5 cm of the hand. `robo move-to X Y Z` and `robo grip G` work as described below.

**Observation.** You see the kitchen only through the cameras. `robo observe` gives the robot's own state and the instruction: `hand_pos` (the point between the fingertips), `hand_target` (the commanded target), `gripper_open` (0 closed .. 1 open), `robot_base_pos`, `robot_forward` and `task_instruction` (RoboCasa's own language instruction). It does not say where the objects, handles, knobs or other fixtures are, or what state they are in. Each `robo observe` also saves a 384x288 image from each camera and prints their paths; open them to look: `robot0_agentview_left` and `robot0_agentview_right` (on the robot's left and right shoulders, looking forward and down) and `robot0_eye_in_hand` (on the wrist, moving with the hand). The counter top is at about z = 0.92.

`robo info` lists each camera with a 3x4 `projection` matrix P: for a world point (x, y, z), `[u*w, v*w, w] = P @ [x, y, z, 1]` gives its pixel (u, v) in that camera's saved image (u to the right, v down, origin at the top-left). The wrist camera moves with the hand: its matrix is for the hand's pose when you call `robo info`.

The step budget is 300 steps (15 s of simulated time).

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
