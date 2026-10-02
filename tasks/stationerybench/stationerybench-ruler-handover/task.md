---
schema_version: '1.3'
task:
  name: robocurve/stationerybench/ruler_handover
  description: Hand a ruler between arms, cup to cup
metadata:
  source_benchmark: StationeryBench (robocurve/stationerybench, MIT)
  source_task: stationerybench/ruler_handover
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
  id: stationerybench-ruler-handover
  backend: real
  env: stationerybench-ruler-handover
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
    - No purposeful contact with the ruler
    - Touches or moves the ruler deliberately
    - Ruler lifted clear of the left cup in one gripper
    - Ruler held by the other gripper after a mid-air handover
    - Ruler standing in the right cup and released
    verdict: operator
    scene_setup: 1. Stand one cup near the left arm and one near the right arm, at the same distance from the arm bases, so the ruler cannot be moved without a handover. 2. Stand the ruler in the left cup, leaning toward the far edge of the bench. 3. Leave the right cup empty.
    goal_text: Transfer the ruler from the left cup to the right cup, but you must hand it over to the other arm's gripper in mid-air.
---

# StationeryBench: Hand a ruler between arms, cup to cup

You control two SO-101 follower arms (real robots), standing at the far edge of a desk bench and facing the operator; left and right are the operator's left and right. Each arm has five joints and a gripper (LeRobot calibration: 0 deg at the middle of each joint's range; gripper 0 = closed, 100 = open). Cameras show the bench.

## Task

> Transfer the ruler from the left cup to the right cup, but you must hand it over to the other arm's gripper in mid-air.

Objects: - two paper cups (about 12 oz) - one clear plastic 12 inch (30 cm) ruler

Setup (done by the operator before the episode): 1. Stand one cup near the left arm and one near the right arm, at the same distance from the arm bases, so the ruler cannot be moved without a handover. 2. Stand the ruler in the left cup, leaning toward the far edge of the bench. 3. Leave the right cup empty.

**Success:** after you call `robo done`, the operator watching the robot reports the highest rubric stage reached; the task counts as solved at stage 4 and the stage over 4 is the progress score.

| Stage | Description |
|---|---|
| 0 | No purposeful contact with the ruler |
| 1 | Touches or moves the ruler deliberately |
| 2 | Ruler lifted clear of the left cup in one gripper |
| 3 | Ruler held by the other gripper after a mid-air handover |
| 4 | Ruler standing in the right cup and released |

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
