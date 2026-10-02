---
schema_version: '1.3'
task:
  name: robouse/real-so101-block-lift
  description: 'SO-101 arm: pick up the block and hold it up'
metadata:
  source_benchmark: robouse original (real suite; real arm, hardware-in-the-loop mock by default)
  source_task: real-so101-block-lift
  suite: real
  category: pick
  difficulty: medium
  tags:
  - real-robot
  - so101
  - hil-mock
  embodiment_mode: real
  tested_on_hardware: false
agent:
  timeout_sec: 1800
verifier:
  timeout_sec: 120
robouse:
  id: real-so101-block-lift
  backend: real
  env: real-so101-block-lift
  seed: 0
  max_steps: 600
  camera: all
  cameras:
  - all
  - camera0
  - camera1
  skills: true
  success_mode: final
  frame_every: 2
  real:
    robot: so101
    driver: mock
    fixture: so101-sort-left
    cameras:
    - camera0
    - camera1
    stages:
    - name: above cube, open
      tool:
      - 0.22
      - -0.05
      - 0.08
      tol: 0.02
      gripper: open
    - name: at cube
      tool:
      - 0.22
      - -0.05
      - 0.02
      tol: 0.012
    - name: closed on cube
      tool:
      - 0.22
      - -0.05
      - 0.02
      tol: 0.015
      gripper: closed
    - name: lifted
      tool:
      - 0.22
      - -0.05
      - 0.08
      tol: 0.02
      gripper: closed
    scene_setup: one 2.5 cm cube on the table at (0.22, -0.05) m.
    goal_text: A 2.5 cm cube stands on the table at about (0.22, -0.05) m in the base frame (table at z = 0). Grasp it and lift it 8 cm off the table.
---

# SO-101 arm: pick up the block and hold it up

You control a SO-101 follower arm, a real robot arm. LeRobot calibration: 0 deg at the middle of each joint's calibrated range. Base frame (URDF base_link): +z up, metres. Gripper 0 = closed, 100 = fully open. Forward kinematics come from the vendor URDF and have not been re-measured on this bench. Cameras: `camera0`, `camera1` (`robo observe --image` shows all of them side by side; `--camera NAME` shows one).

## Task

A 2.5 cm cube stands on the table at about (0.22, -0.05) m in the base frame (table at z = 0). Grasp it and lift it 8 cm off the table.

**Success:** the operator confirms the cube is held clear of the table (mock: the stand-in operator says yes only if the tip went, in order, above the cube with the gripper open, down to the cube, closed there and lifted). Judged by the episode server after you call `robo done` and the arm has held still for 10 control steps.

**Controls.** `robo act` takes one absolute target per joint, in this order: shoulder_pan [-108, 108] deg, shoulder_lift [-98, 98] deg, elbow_flex [-94.8, 94.8] deg, wrist_flex [-93, 93] deg, wrist_roll [-155.2, 160.8] deg, gripper [2, 98] 0-100. The gripper is the last value (2 = closed, 60 = open). The target is approached at the safety speed limit over the following control steps (10 Hz); `--repeat N` keeps commanding it for N steps. Skills (`robo info` lists them with their arguments): `move_joints SHOULDER_PAN SHOULDER_LIFT ELBOW_FLEX WRIST_FLEX WRIST_ROLL [SPEED]` (interpolated move to a joint pose; SPEED is a fraction of the speed limit), `move_to X Y Z [SPEED]` (fingertips to a point in the base frame by inverse kinematics, position only), `grip VALUE`, `home` (reach-ready pose) and `park` (rest pose). Every skill checks its whole path first and is refused with the reason if the path leaves the workspace.

**Safety layer.** Every command passes the episode server's safety guard before it reaches the motors: joint targets are clamped to the joint limits; a move whose straight joint-space path would take the elbow, wrist, flange or fingertips below the table, outside the workspace box or low behind the base is vetoed before anything moves (`robo` prints the reason and no step is used); speed is limited per control step (slower within 7.6 cm of the table); a joint command never leads the measured position by more than a few degrees. A contact during a move that ends within 3 cm of the table, seen as the fingertips stopping short of a commanded descent, since this arm reports no joint torque, stops that move: the arm holds where it is and the step result reports it under `contact`; a second contact, one anywhere else, or one while the arm holds still for the 10 steps after the episode ends stops the episode. Over-temperature (also at the start), an operator e-stop, a stalled control loop, joint readings that stop arriving or a hardware fault stop the episode at once (outcome `safety_stop`, score 0); the e-stop, the joint readings and the temperatures are also checked between your requests. After a stop, every arm joint holds at its measured position and the gripper keeps its command, so a grasped object is not let go, and nothing moves until the operator has inspected the robot. When the episode ends otherwise, the arm moves slowly to its rest pose and is released there, or keeps holding if it cannot get there or is holding something. `robo info` lists the limits under `embodiment.safety`.

**Observation.** `robo observe` reports `joint_pos` (measured, by joint name), `gripper`, `tool_pos` / `tool_axis` (the fingertip point and approach direction by forward kinematics of the measured joints, base frame, metres), `target` (the current joint target), `telemetry` (maximum motor temperature, veto count, e-stop and stop state) and `mode` (`real` on hardware, `hil-mock` on the hardware-in-the-loop mock, which replays a session recorded on this arm: it follows commands the way the real arm did and shows the recorded camera view nearest to the current pose, but models no contact with objects). Remarks typed by the operator appear under `operator_notes`.

The step budget is 600 control steps.

## How to control the robot

You are the robot's policy. You act only through the `robo` command in your shell. There is no other way to move the robot, and you cannot read or change the simulator, the scoring, or other files to succeed; the episode server judges the final physical state itself.

```
robo info                          # the robot, its sensors, action groups, skills and step budget
robo observe                       # robot and scene state as numbers
robo observe --image [--camera C]  # also saves a camera image and prints its path (open it to look)
robo act V1 V2 ... [--repeat N]    # one low-level action (the action groups under Controls), applied N times (N <= 50)
robo skill NAME ARG ...            # run a skill listed by `robo info`; it runs until it finishes and reports the result
robo done "short summary"          # end the episode and ask for scoring
robo give-up "reason"              # end the episode without claiming success
```

- Positions are in metres in the world frame (+z up); angles are in degrees unless a field says otherwise.
- The episode has a fixed step budget (see `robo info`); every simulated control step counts, including the steps a skill runs.
- Skills are ordinary controllers: they can fail, stop early or be blocked by the scene. Read what they report and re-observe.
- Success is judged about 10 steps after you call `robo done`, with the robot holding still (each action group's hold value: zero for velocity and delta commands, full brake for a car), so the goal must still be true when the robot stops.
- Call `robo done` exactly once when finished.
