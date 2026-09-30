---
schema_version: '1.3'
task:
  name: robouse/real-piper-joint-pose
  description: 'Piper arm: move to a joint-space pose'
metadata:
  source_benchmark: robouse original (real suite; real arm, hardware-in-the-loop mock by default)
  source_task: real-piper-joint-pose
  suite: real
  category: reach
  difficulty: easy
  tags:
  - real-robot
  - piper
  - hil-mock
  embodiment_mode: real
  tested_on_hardware: false
agent:
  timeout_sec: 1800
verifier:
  timeout_sec: 120
robouse:
  id: real-piper-joint-pose
  backend: real
  env: real-piper-joint-pose
  seed: 0
  max_steps: 300
  camera: ''
  cameras:
  - ''
  skills: true
  success_mode: final
  frame_every: 2
  real:
    robot: piper
    driver: mock
    fixture: piper-synthetic
    goal:
      joints:
      - 20.0
      - 40.0
      - -50.0
      - 0.0
      - 20.0
      - 0.0
      tol: 3.0
    goal_text: Move the six arm joints to (20, 40, -50, 0, 20, 0) degrees and hold.
---

# Piper arm: move to a joint-space pose

You control a AgileX Piper arm, a real robot arm. Piper joint limits from the user manual. No kinematic chain yet: only joint limits and speed limits are enforced. This rig has no camera.

## Task

Move the six arm joints to (20, 40, -50, 0, 20, 0) degrees and hold.

**Success:** every measured arm joint is within 3 degrees of its target when judged. Judged by the episode server after you call `robo done` and the arm has held still for 10 control steps.

**Controls.** `robo act` takes one absolute target per joint, in this order: joint1 [-150, 150] deg, joint2 [0, 180] deg, joint3 [-170, 0] deg, joint4 [-100, 100] deg, joint5 [-70, 70] deg, joint6 [-120, 120] deg, gripper [0, 70] mm. The gripper is the last value (0 = closed, 60 = open). The target is approached at the safety speed limit over the following control steps (20 Hz); `--repeat N` keeps commanding it for N steps. Skills (`robo info` lists them with their arguments): `move_joints JOINT1 JOINT2 JOINT3 JOINT4 JOINT5 JOINT6 [SPEED]` (interpolated move to a joint pose; SPEED is a fraction of the speed limit), `grip VALUE`, `home` (reach-ready pose) and `park` (rest pose). Every skill checks its whole path first and is refused with the reason if the path leaves the workspace.

**Safety layer.** Every command passes the episode server's safety guard before it reaches the motors: joint targets are clamped to the joint limits; a move whose straight joint-space path would take the elbow, wrist, flange or fingertips below the table, outside the workspace box or low behind the base is vetoed before anything moves (`robo` prints the reason and no step is used); speed is limited per control step (slower within 7.6 cm of the table); a joint command never leads the measured position by more than a few degrees; over-temperature, an operator e-stop or a hardware fault stops the episode at once (outcome `safety_stop`, score 0). `robo info` lists the limits under `embodiment.safety`.

**Observation.** `robo observe` reports `joint_pos` (measured, by joint name), `gripper`, `target` (the current joint target), `telemetry` (maximum motor temperature, veto count, e-stop and stop state) and `mode` (`real` on hardware, `hil-mock` on the hardware-in-the-loop mock, which replays a session recorded on this arm: it follows commands the way the real arm did and shows the recorded camera view nearest to the current pose, but models no contact with objects). Remarks typed by the operator appear under `operator_notes`.

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
