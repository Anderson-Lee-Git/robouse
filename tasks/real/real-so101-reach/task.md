---
schema_version: '1.3'
task:
  name: robouse/real-so101-reach
  description: 'SO-101 arm: bring the gripper tip to a point above the table'
metadata:
  source_benchmark: robouse original (real suite; real arm, hardware-in-the-loop mock by default)
  source_task: real-so101-reach
  suite: real
  category: reach
  difficulty: easy
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
  id: real-so101-reach
  backend: real
  env: real-so101-reach
  seed: 0
  max_steps: 300
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
    goal:
      tool:
      - 0.2
      - 0.05
      - 0.08
      tol: 0.02
    goal_text: Move the gripper tip (the tool point) to (0.20, 0.05, 0.08) m in the base frame and hold it there.
---

# SO-101 arm: bring the gripper tip to a point above the table

You control a SO-101 follower arm, a real robot arm. LeRobot calibration: 0 deg at the middle of each joint's calibrated range. Base frame (URDF base_link): +z up, metres. Gripper 0 = closed, 100 = fully open. Forward kinematics come from the vendor URDF and have not been re-measured on this bench. Cameras: `camera0`, `camera1` (`robo observe --image` shows all of them side by side; `--camera NAME` shows one).

## Task

Move the gripper tip (the tool point) to (0.20, 0.05, 0.08) m in the base frame and hold it there.

**Success:** the measured tool point (`tool_pos`) is within 2 cm of (0.20, 0.05, 0.08) when judged. Judged by the episode server after you call `robo done` and the arm has held still for 10 control steps.

**Controls.** `robo act` takes one absolute target per joint, in this order: shoulder_pan [-108, 108] deg, shoulder_lift [-98, 98] deg, elbow_flex [-94.8, 94.8] deg, wrist_flex [-93, 93] deg, wrist_roll [-155.2, 160.8] deg, gripper [2, 98] 0-100. The gripper is the last value (2 = closed, 60 = open). The target is approached at the safety speed limit over the following control steps (10 Hz); `--repeat N` keeps commanding it for N steps. Skills (`robo info` lists them with their arguments): `move_joints SHOULDER_PAN SHOULDER_LIFT ELBOW_FLEX WRIST_FLEX WRIST_ROLL [SPEED]` (interpolated move to a joint pose; SPEED is a fraction of the speed limit), `move_to X Y Z [SPEED]` (fingertips to a point in the base frame by inverse kinematics, position only), `grip VALUE`, `home` (reach-ready pose) and `park` (rest pose). Every skill checks its whole path first and is refused with the reason if the path leaves the workspace.

**Safety layer.** Every command passes the episode server's safety guard before it reaches the motors: joint targets are clamped to the joint limits; a move whose straight joint-space path would take the elbow, wrist, flange or fingertips below the table, outside the workspace box or low behind the base is vetoed before anything moves (`robo` prints the reason and no step is used); speed is limited per control step (slower within 7.6 cm of the table); a joint command never leads the measured position by more than a few degrees. A contact during a move that ends within 3 cm of the table, seen as the fingertips stopping short of a commanded descent, since this arm reports no joint torque, stops that move: the arm holds where it is and the step result reports it under `contact`; a second contact, one anywhere else, or one while the arm holds still for the 10 steps after the episode ends stops the episode. Over-temperature (also at the start), an operator e-stop, a stalled control loop, joint readings that stop arriving or a hardware fault stop the episode at once (outcome `safety_stop`, score 0); the e-stop, the joint readings and the temperatures are also checked between your requests. After a stop and when the episode ends, every arm joint is held at its measured position and the gripper keeps its command, so a grasped object is not let go; the arm then moves slowly to its rest pose and is released there, or keeps holding if it cannot get there or is holding something. `robo info` lists the limits under `embodiment.safety`.

**Observation.** `robo observe` reports `joint_pos` (measured, by joint name), `gripper`, `tool_pos` / `tool_axis` (the fingertip point and approach direction by forward kinematics of the measured joints, base frame, metres), `target` (the current joint target), `telemetry` (maximum motor temperature, veto count, e-stop and stop state) and `mode` (`real` on hardware, `hil-mock` on the hardware-in-the-loop mock, which replays a session recorded on this arm: it follows commands the way the real arm did and shows the recorded camera view nearest to the current pose, but models no contact with objects). Remarks typed by the operator appear under `operator_notes`.

The step budget is 300 control steps.

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
