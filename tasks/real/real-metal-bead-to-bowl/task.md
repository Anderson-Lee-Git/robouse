---
schema_version: '1.3'
task:
  name: robouse/real-metal-bead-to-bowl
  description: 'Metal arm: put a green bead into the bowl'
metadata:
  source_benchmark: robouse original (real suite; real arm, hardware-in-the-loop mock by default)
  source_task: real-metal-bead-to-bowl
  suite: real
  category: pick-and-place
  difficulty: hard
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
  id: real-metal-bead-to-bowl
  backend: real
  env: real-metal-bead-to-bowl
  seed: 0
  max_steps: 900
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
    stages:
    - name: above bead, open
      tool:
      - 0.3
      - -0.15
      - 0.06
      tol: 0.02
      gripper: open
    - name: at bead
      tool:
      - 0.3
      - -0.15
      - 0.005
      tol: 0.012
    - name: closed on bead
      tool:
      - 0.3
      - -0.15
      - 0.005
      tol: 0.015
      gripper: closed
    - name: lifted
      tool:
      - 0.3
      - -0.15
      - 0.08
      tol: 0.025
      gripper: closed
    - name: over bowl
      tool:
      - 0.42
      - -0.13
      - 0.12
      tol: 0.025
      gripper: closed
    - name: released over bowl
      tool:
      - 0.42
      - -0.13
      - 0.12
      tol: 0.03
      gripper: open
    scene_setup: one green glass bead on the table at (0.30, -0.15) m; the white ceramic bowl centred near (0.49, -0.13) m.
    goal_text: A green glass bead lies on the table at about (0.30, -0.15) m in the base frame (table surface at z = -0.009 m). The white bowl is centred near (0.49, -0.13) m, past straight-down reach; release over its near rim at about (0.42, -0.13, 0.12) m. Pick up the bead and drop it into the bowl.
---

# Metal arm: put a green bead into the bowl

You control a MakerMods Metal arm, a real robot arm. Joint zero is the vendor's parked pose: upper arm horizontal pointing backward, forearm folded over it. shoulder_lift 0 = horizontal backward, -90 = vertical, -180 = horizontal forward; elbow_flex 0 = folded, 180 = straight. Gripper 0 = closed. Base frame: +x forward, +y left, +z up, metres. Cameras: `gripper`, `overhead` (`robo observe --image` shows all of them side by side; `--camera NAME` shows one).

## Task

A green glass bead lies on the table at about (0.30, -0.15) m in the base frame (table surface at z = -0.009 m). The white bowl is centred near (0.49, -0.13) m, past straight-down reach; release over its near rim at about (0.42, -0.13, 0.12) m. Pick up the bead and drop it into the bowl.

**Success:** the operator watching the robot confirms that the bead ended up in the bowl (on the hardware-in-the-loop mock, the stand-in operator says yes only if the fingertips went, in order, above the bead with the gripper open, down to the bead, closed there, lifted, moved over the bowl and opened). Judged by the episode server after you call `robo done` and the arm has held still for 10 control steps.

**Controls.** `robo act` takes one absolute target per joint, in this order: shoulder_pan [-159, 159] deg, shoulder_lift [-179, -1] deg, elbow_flex [1, 179] deg, wrist_flex [-122, 80] deg, wrist_yaw [-84, 84] deg, wrist_roll [-144, 144] deg, gripper [0, 115] deg. The gripper is the last value (4 = closed, 60 = open). The target is approached at the safety speed limit over the following control steps (10 Hz); `--repeat N` keeps commanding it for N steps. Skills (`robo info` lists them with their arguments): `move_joints SHOULDER_PAN SHOULDER_LIFT ELBOW_FLEX WRIST_FLEX WRIST_YAW WRIST_ROLL [SPEED]` (interpolated move to a joint pose; SPEED is a fraction of the speed limit), `move_to X Y Z [SPEED]` (fingertips to a point in the base frame by inverse kinematics, position only), `grip VALUE`, `home` (reach-ready pose) and `park` (rest pose). Every skill checks its whole path first and is refused with the reason if the path leaves the workspace.

**Safety layer.** Every command passes the episode server's safety guard before it reaches the motors: joint targets are clamped to the joint limits; a move whose straight joint-space path would take the elbow, wrist, flange or fingertips below the table, outside the workspace box or low behind the base is vetoed before anything moves (`robo` prints the reason and no step is used); speed is limited per control step (slower within 7.6 cm of the table); a joint command never leads the measured position by more than a few degrees; over-temperature, an operator e-stop or a hardware fault stops the episode at once (outcome `safety_stop`, score 0). `robo info` lists the limits under `embodiment.safety`.

**Observation.** `robo observe` reports `joint_pos` (measured, by joint name), `gripper`, `tool_pos` / `tool_axis` (the fingertip point and approach direction by forward kinematics of the measured joints, base frame, metres), `target` (the current joint target), `telemetry` (maximum motor temperature, veto count, e-stop and stop state) and `mode` (`real` on hardware, `hil-mock` on the hardware-in-the-loop mock, which replays a session recorded on this arm: it follows commands the way the real arm did and shows the recorded camera view nearest to the current pose, but models no contact with objects). Remarks typed by the operator appear under `operator_notes`.

The step budget is 900 control steps.

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
