---
schema_version: '1.3'
task:
  name: robouse/real-ros-joint-pose
  description: 'ROS arm via rosbridge: move to a joint-space pose'
metadata:
  source_benchmark: robouse original (real suite; real arm, hardware-in-the-loop mock by default)
  source_task: real-ros-joint-pose
  suite: real
  category: reach
  difficulty: easy
  tags:
  - real-robot
  - ros
  - hil-mock
  embodiment_mode: real
  tested_on_hardware: false
agent:
  timeout_sec: 1800
verifier:
  timeout_sec: 120
robouse:
  id: real-ros-joint-pose
  backend: real
  env: real-ros-joint-pose
  seed: 0
  max_steps: 300
  camera: all
  cameras:
  - all
  - wrist
  skills: true
  success_mode: final
  frame_every: 2
  real:
    robot: ros
    driver: mock
    cameras:
    - wrist
    display: 6-joint ROS arm (rosbridge)
    joints:
    - shoulder_pan_joint
    - shoulder_lift_joint
    - elbow_joint
    - wrist_1_joint
    - wrist_2_joint
    - wrist_3_joint
    low:
    - -180
    - -180
    - -160
    - -180
    - -180
    - -180
    high:
    - 180
    - 0
    - 160
    - 180
    - 180
    - 180
    units: deg
    home:
    - 0
    - -90
    - 90
    - -90
    - -90
    - 0
    park:
    - 0
    - -90
    - 90
    - -90
    - -90
    - 0
    control_hz: 10
    notes: 'Joint names follow the ROS arm''s /joint_states; positions in degrees (converted to radians on the wire). No kinematic chain: the safety layer enforces joint limits, speed and wind-up.'
    goal:
      joints:
      - 30.0
      - -70.0
      - 60.0
      - -80.0
      - -90.0
      - 20.0
      tol: 3.0
    goal_text: Move the six joints to (30, -70, 60, -80, -90, 20) degrees and hold.
---

# ROS arm via rosbridge: move to a joint-space pose

You control a 6-joint ROS arm (rosbridge), a real robot arm. Joint names follow the ROS arm's /joint_states; positions in degrees (converted to radians on the wire). No kinematic chain: the safety layer enforces joint limits, speed and wind-up. Cameras: `wrist` (`robo observe --image` shows all of them side by side; `--camera NAME` shows one).

## Task

Move the six joints to (30, -70, 60, -80, -90, 20) degrees and hold.

**Success:** every measured joint is within 3 degrees of its target when judged. Judged by the episode server after you call `robo done` and the arm has held still for 10 control steps.

**Controls.** `robo act` takes one absolute target per joint, in this order: shoulder_pan_joint [-180, 180] deg, shoulder_lift_joint [-180, 0] deg, elbow_joint [-160, 160] deg, wrist_1_joint [-180, 180] deg, wrist_2_joint [-180, 180] deg, wrist_3_joint [-180, 180] deg. The gripper is the last value (0 = closed, 0 = open). The target is approached at the safety speed limit over the following control steps (10 Hz); `--repeat N` keeps commanding it for N steps. Skills (`robo info` lists them with their arguments): `move_joints SHOULDER_PAN_JOINT SHOULDER_LIFT_JOINT ELBOW_JOINT WRIST_1_JOINT WRIST_2_JOINT WRIST_3_JOINT [SPEED]` (interpolated move to a joint pose; SPEED is a fraction of the speed limit), `grip VALUE`, `home` (reach-ready pose) and `park` (rest pose).

**Safety layer.** Every command passes the episode server's safety guard before it reaches the motors: joint targets are clamped to the joint limits; speed is limited per control step (this arm has no kinematic model, so there is no workspace check); a joint command never leads the measured position by more than a few degrees. Nothing detects this arm touching something: it has no contact thresholds and no kinematic model. Over-temperature (also at the start), an operator e-stop, a stalled control loop, joint readings that stop arriving or a hardware fault stop the episode at once (outcome `safety_stop`, score 0); the e-stop, the joint readings and the temperatures are also checked between your requests. After a stop, every arm joint holds at its measured position, and nothing moves until the operator has inspected the robot. When the episode ends otherwise, the arm holds where it is: its parks are not calibrated, so it parks only when the operator approves. `robo info` lists the limits under `embodiment.safety`.

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
