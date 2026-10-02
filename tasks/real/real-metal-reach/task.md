---
schema_version: '1.3'
task:
  name: robouse/real-metal-reach
  description: 'Metal arm: bring the fingertips to a point above the bead tray'
metadata:
  source_benchmark: robouse original (real suite; real arm, hardware-in-the-loop mock by default)
  source_task: real-metal-reach
  suite: real
  category: reach
  difficulty: easy
  tags:
  - real-robot
  - metal
  - hil-mock
  embodiment_mode: real
  tested_on_hardware: true
agent:
  timeout_sec: 1800
verifier:
  timeout_sec: 120
robouse:
  id: real-metal-reach
  backend: real
  env: real-metal-reach
  seed: 0
  max_steps: 300
  camera: all
  cameras:
  - all
  - gripper
  - overhead
  skills: true
  success_mode: final
  frame_every: 2
  real:
    robot: metal
    driver: mock
    fixture: metal-bowl-121853
    cameras:
    - gripper
    - overhead
    goal:
      tool:
      - 0.3
      - -0.1
      - 0.08
      tol: 0.02
    goal_text: Move the fingertips (the tool point) to (0.30, -0.10, 0.08) m in the base frame, 8 cm above the table over the bead tray, and hold them there.
---

# Metal arm: bring the fingertips to a point above the bead tray

You control a MakerMods Metal arm, a real robot arm. Joint zero is the vendor's parked pose: upper arm horizontal pointing backward, forearm folded over it. shoulder_lift 0 = horizontal backward, -90 = vertical, -180 = horizontal forward; elbow_flex 0 = folded, 180 = straight. Gripper 0 = closed. Base frame: +x forward, +y left, +z up, metres. Cameras: `gripper`, `overhead` (`robo observe --image` shows all of them side by side; `--camera NAME` shows one).

## Task

Move the fingertips (the tool point) to (0.30, -0.10, 0.08) m in the base frame, 8 cm above the table over the bead tray, and hold them there.

**Success:** the measured tool point (forward kinematics of the measured joints, `tool_pos` in `robo observe`) is within 2 cm of (0.30, -0.10, 0.08) when judged. Judged by the episode server after you call `robo done` and the arm has held still for 10 control steps.

**Controls.** `robo act` takes one absolute target per joint, in this order: shoulder_pan [-159, 159] deg, shoulder_lift [-179, -2.5] deg, elbow_flex [1, 174] deg, wrist_flex [-122, 80] deg, wrist_yaw [-84, 84] deg, wrist_roll [-144, 144] deg, gripper [2, 115] deg. The gripper is the last value (4 = closed, 60 = open). The target is approached at the safety speed limit over the following control steps (10 Hz); `--repeat N` keeps commanding it for N steps. Skills (`robo info` lists them with their arguments): `move_joints SHOULDER_PAN SHOULDER_LIFT ELBOW_FLEX WRIST_FLEX WRIST_YAW WRIST_ROLL [SPEED]` (interpolated move to a joint pose; SPEED is a fraction of the speed limit), `move_to X Y Z [SPEED]` (fingertips to a point in the base frame by inverse kinematics, position only), `grip VALUE`, `home` (reach-ready pose) and `park` (rest pose). Every skill checks its whole path first and is refused with the reason if the path leaves the workspace.

**Safety layer.** Every command passes the episode server's safety guard before it reaches the motors: joint targets are clamped to the joint limits; a move whose straight joint-space path would take the elbow, wrist, flange or fingertips below the table, outside the workspace box or low behind the base is vetoed before anything moves (`robo` prints the reason and no step is used); speed is limited per control step (slower within 7.6 cm of the table); a joint command never leads the measured position by more than a few degrees. A contact during a move that ends within 3 cm of the table, seen as a jump in joint torque or as the fingertips stopping short of a commanded descent, stops that move: the arm holds where it is and the step result reports it under `contact`; a second contact, one anywhere else, or one while the arm holds still for the 10 steps after the episode ends stops the episode. Over-temperature (also at the start), an operator e-stop, a stalled control loop, joint readings that stop arriving or a hardware fault stop the episode at once (outcome `safety_stop`, score 0); the e-stop, the joint readings and the temperatures are also checked between your requests. After a stop and when the episode ends, every arm joint is held at its measured position and the gripper keeps its command, so a grasped object is not let go; the arm then moves slowly to its rest pose and is released there, or keeps holding if it cannot get there or is holding something. `robo info` lists the limits under `embodiment.safety`.

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
