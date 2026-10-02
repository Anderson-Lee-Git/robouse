---
schema_version: '1.3'
task:
  name: robocurve/stationerybench/middle_sticky_pad
  description: Pull the middle sticky pad from a stack
metadata:
  source_benchmark: StationeryBench (robocurve/stationerybench, MIT)
  source_task: stationerybench/middle_sticky_pad
  upstream_commit: 43d5dd380eeb9f555fe691a896a076cf43d3b18b
  suite: stationerybench
  category: bimanual manipulation
  difficulty: hard
  tags:
  - real-robot
  - bimanual
  - so101
  - operator-judged
  embodiment_mode: real
  upstream_epochs: 20
  tested_on_hardware: false
agent:
  timeout_sec: 1800
verifier:
  timeout_sec: 120
robouse:
  id: stationerybench-middle-sticky-pad
  backend: real
  env: stationerybench-middle-sticky-pad
  seed: 0
  max_steps: 1200
  camera: all
  cameras:
  - all
  - camera0
  - camera1
  skills: true
  success_mode: final
  frame_every: 2
  real:
    robot: so101-bimanual
    driver: mock
    fixture: so101-bimanual-sort
    cameras:
    - camera0
    - camera1
    rubric:
    - No purposeful contact with the stack
    - Touches or moves a pad deliberately
    - Top pad lifted clear of the stack
    - Middle pad removed from the stack and released on the table
    - Middle pad on the table, top pad resting on a pad and not on the table
    verdict: operator
    scene_setup: 1. Stack the three pads vertically at the centre of the bench. 2. Offset each pad slightly (about 1 cm and a few degrees of yaw) from the one below so the edges are not flush.
    goal_text: There is a stack of three sticky notes. Take the middle one out and put it on the table. Make sure everything is at rest at the end, but do not let the top one touch the table at all, so it should rest on one of the sticky notes at the end.
---

# StationeryBench: Pull the middle sticky pad from a stack

You control two SO-101 follower arms (real robots), standing at the far edge of a desk bench and facing the operator; left and right are the operator's left and right. Each arm has five joints and a gripper (LeRobot calibration: 0 deg at the middle of each joint's range; gripper 0 = closed, 100 = open). Cameras show the bench.

## Task

> There is a stack of three sticky notes. Take the middle one out and put it on the table. Make sure everything is at rest at the end, but do not let the top one touch the table at all, so it should rest on one of the sticky notes at the end.

Objects: - three shrink-wrapped 3 x 3 inch sticky-note cubes (Post-it Super Sticky notes cube or equivalent)

Setup (done by the operator before the episode): 1. Stack the three pads vertically at the centre of the bench. 2. Offset each pad slightly (about 1 cm and a few degrees of yaw) from the one below so the edges are not flush.

**Success:** after you call `robo done`, the operator watching the robot reports the highest rubric stage reached; the task counts as solved at stage 4 and the stage over 4 is the progress score.

| Stage | Description |
|---|---|
| 0 | No purposeful contact with the stack |
| 1 | Touches or moves a pad deliberately |
| 2 | Top pad lifted clear of the stack |
| 3 | Middle pad removed from the stack and released on the table |
| 4 | Middle pad on the table, top pad resting on a pad and not on the table |

**Controls.** `robo act` takes one absolute target per joint in this order: left_shoulder_pan, left_shoulder_lift, left_elbow_flex, left_wrist_flex, left_wrist_roll, left_gripper, right_shoulder_pan, right_shoulder_lift, right_elbow_flex, right_wrist_flex, right_wrist_roll, right_gripper. Targets are approached at the safety speed limit over the following control steps (10 Hz). Skills: `move_joints` (both arms' ten arm joints, interpolated), `grip VALUE [left|right|both]`, `home`, `park`. The safety layer clamps joint limits, limits speed, bounds how far a command may lead the measured position, stops the episode on over-temperature, the operator's e-stop, a stalled control loop or joint readings that stop arriving (also checked between requests), and lets the operator gate every episode. Nothing detects an arm touching something: the arms report no joint torque and the rig has no kinematic model. After a stop the arms hold their measured positions and the grippers keep their commands, so a grasped object is not let go, and nothing moves until the operator has inspected them. When the episode ends otherwise, the arms hold where they are: their parks are not calibrated, so they park only when the operator approves.

**Observation.** `robo observe` reports `joint_pos` by name, `gripper` per arm, `target`, `telemetry` and `mode` (`real` or `hil-mock`); `robo observe --image` shows the cameras. Remarks from the operator appear under `operator_notes`.

The budget is 1200 control steps (120 s, upstream's time limit).

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
