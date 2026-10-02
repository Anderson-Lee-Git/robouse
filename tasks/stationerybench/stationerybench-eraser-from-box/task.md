---
schema_version: '1.3'
task:
  name: robocurve/stationerybench/eraser_from_box
  description: Open the box, take out an eraser, close the lid
metadata:
  source_benchmark: StationeryBench (robocurve/stationerybench, MIT)
  source_task: stationerybench/eraser_from_box
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
  id: stationerybench-eraser-from-box
  backend: real
  env: stationerybench-eraser-from-box
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
    - No purposeful contact with the box or lid
    - Touches the lid deliberately
    - Lid held open far enough to reach inside
    - Eraser lifted out of the box
    - Eraser released on the table outside the box and the lid closed
    verdict: operator
    scene_setup: 1. Place the box at the centre of the bench with the hinge at the far edge, toward the arms. 2. Put the eraser inside, resting on the floor of the box near the front-left corner. 3. Close the lid fully. (The reference photo shows the box open so the eraser is visible.)
    goal_text: Open the lid of the box, take out one eraser from the box and place it on the table, then close the box. The lid is a lift-open lid, so it may be easier to just prop it open with the gripper.
---

# StationeryBench: Open the box, take out an eraser, close the lid

You control two SO-101 follower arms (real robots), standing at the far edge of a desk bench and facing the operator; left and right are the operator's left and right. Each arm has five joints and a gripper (LeRobot calibration: 0 deg at the middle of each joint's range; gripper 0 = closed, 100 = open). Cameras show the bench.

## Task

> Open the lid of the box, take out one eraser from the box and place it on the table, then close the box. The lid is a lift-open lid, so it may be easier to just prop it open with the gripper.

Objects: - cloth-covered book-style box with a hinged lift lid (about 30 x 22 x 7 cm) - one block eraser in its paper sleeve

Setup (done by the operator before the episode): 1. Place the box at the centre of the bench with the hinge at the far edge, toward the arms. 2. Put the eraser inside, resting on the floor of the box near the front-left corner. 3. Close the lid fully. (The reference photo shows the box open so the eraser is visible.)

**Success:** after you call `robo done`, the operator watching the robot reports the highest rubric stage reached; the task counts as solved at stage 4 and the stage over 4 is the progress score.

| Stage | Description |
|---|---|
| 0 | No purposeful contact with the box or lid |
| 1 | Touches the lid deliberately |
| 2 | Lid held open far enough to reach inside |
| 3 | Eraser lifted out of the box |
| 4 | Eraser released on the table outside the box and the lid closed |

**Controls.** `robo act` takes one absolute target per joint in this order: left_shoulder_pan, left_shoulder_lift, left_elbow_flex, left_wrist_flex, left_wrist_roll, left_gripper, right_shoulder_pan, right_shoulder_lift, right_elbow_flex, right_wrist_flex, right_wrist_roll, right_gripper. Targets are approached at the safety speed limit over the following control steps (10 Hz). Skills: `move_joints` (both arms' ten arm joints, interpolated), `grip VALUE [left|right|both]`, `home`, `park`. The safety layer clamps joint limits, limits speed, bounds how far a command may lead the measured position, stops the episode on over-temperature, the operator's e-stop, a stalled control loop or joint readings that stop arriving, and lets the operator gate every episode. Nothing detects an arm touching something: the arms report no joint torque and the rig has no kinematic model. After a stop and when the episode ends, the arms hold their measured positions, then move slowly to their rest pose and are released there, or keep holding if they cannot get there.

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
