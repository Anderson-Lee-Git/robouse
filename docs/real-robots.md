# Real robots

Real robot arms run behind the same trusted episode server and the same `robo` interface as the simulators: an agent or a VLA cannot tell the backend apart except through `robo info` (`mode: real`) and what the cameras show. Every command passes a safety layer inside the server, a human operator gates each episode, and a hardware-in-the-loop mock lets the whole stack run without hardware by replaying sessions recorded on the bench.

Code: `src/robouse/backends/real.py` (the backend), `src/robouse/real/` (robot profiles, kinematics, safety guard, operator channel, cameras, drivers, replay mock). Tasks: `tasks/real/` and `tasks/stationerybench/`.

## Robots and drivers

| Robot (`real.robot`) | Driver (`real.driver`) | Joints | Kinematics | Hardware status |
|---|---|---|---|---|
| `metal`: MakerMods Metal arm | `lerobot` (makermods-robotics/lerobot, branch arm/makermods-metal, `metal_follower`) | 6 + gripper, degrees | vendor URDF; matches 842 recorded hardware poses to 0.12 mm | driver configuration is the one used on the 2026-09-05 bench sessions; the live path has not run through Robo Use yet |
| `so101` / `so100`: SO-ARM follower | `lerobot` (`so_follower`) | 5 + gripper, LeRobot degrees, gripper 0-100 | TheRobotStudio SO-ARM100 `so101_new_calib.urdf` (Apache-2.0) | untested on hardware |
| `so101-bimanual`: two SO-101 followers | `lerobot` (`bi_so_follower`) | 2 x (5 + gripper) | joint limits only | untested on hardware |
| `piper`: AgileX Piper | `piper` (`piper_sdk`) | 6 + gripper (mm) | joint limits only | written from the SDK documentation; untested |
| `ros`: any ROS 1 / ROS 2 arm | `rosbridge` (rosbridge_suite JSON over a websocket; no ROS install needed): subscribes to `sensor_msgs/JointState` and `sensor_msgs/CompressedImage`, publishes `trajectory_msgs/JointTrajectory` or `std_msgs/Float64MultiArray`; joint names, limits and topics from the rig file | as configured, degrees (radians on the wire) | joint limits only | tested against a mock rosbridge server (`real/rosbridge_mock.py`); untested on a real ROS arm |
| any | `mock` (default in every task): hardware-in-the-loop replay | as the profile | as the profile | tested (below) |

Third-party drivers register under the `robouse.drivers` entry point. `robouse robots` lists profiles, drivers and fixtures.

## Running on hardware

Every real task runs on the mock by default. A rig file switches the same task onto live hardware (keys per robot; anything in the task's `real:` block can be overridden):

```yaml
# rig.yaml
metal:
  driver: lerobot
  port: /dev/cu.usbmodem2101          # CANable (slcan); socketcan: can_interface: socketcan, port: can0
  cameras: {gripper: "0", overhead: "1"}   # OpenCV index, device path or MJPEG URL (cam_server.py)
  operator: tty                       # or file (headless rigs)
  envelope: {table_z: -0.0088}        # from the touchdown calibration
ros:
  driver: rosbridge
  url: ws://robot:9090
  joints: [shoulder_pan_joint, shoulder_lift_joint, elbow_joint, wrist_1_joint, wrist_2_joint, wrist_3_joint]
  low: [-180, -180, -160, -180, -180, -180]
  high: [180, 0, 160, 180, 180, 180]
  command_topic: /scaled_joint_trajectory_controller/joint_trajectory
  cameras: {wrist: /wrist_camera/image_raw/compressed}
so101-bimanual:
  driver: lerobot
  left_port: /dev/cu.usbmodem5B8E1130651
  right_port: /dev/cu.usbmodem5B8E1161091
```

```bash
robouse run --task real-metal-reach --harness claude-code --rig rig.yaml --out runs/metal
robouse run-many --tasks tasks/stationerybench --harness vla --model gr00t/so101 --rig rig.yaml --epochs 20 --out runs/stationery
```

With `--rig`, `run-many` runs one trial at a time, and a hardware lock (`~/.config/robouse-operator/<robot>-<port>.lock`) refuses a second controller on the same robot.

## Safety layer

Enforced in the episode server, on every control step, in this order (a port of the harness that ran the Metal arm on the bench without damage):

1. **E-stop latch.** `robouse estop [REASON]` writes a latched flag; the next command in any real episode stops it (`outcome: safety_stop`, score 0) and the arm holds. `robouse estop --clear` releases it. The flag lives in `~/.config/robouse-operator/`, which the agent sandbox cannot read or write.
2. **Bounds clamp** to the joint limits (vendor soft limits minus a margin).
3. **Workspace envelope by forward kinematics** (arms with a kinematic chain): the straight joint-space path to a new target is sampled and the elbow, wrist, flange and fingertip must stay above the table, inside the workspace box and high enough behind the base. A violating move is vetoed before anything moves; `robo` returns the reason and no step is spent. A point already outside at the start (an arm resting on the table) may only move back toward the envelope.
4. **Per-step speed limit** (joint speed ceiling, slower within 7.6 cm of the table).
5. **Wind-up guard**: a command never leads the measured joint by more than a few degrees, so a blocked joint pushes with bounded torque.
6. **Thermal guard and watchdog**: warn above 55 C, stop above 65 C (Metal defaults); a control step slower than 0.5 s is logged.

Every intervention is written to `episode/session/events.jsonl`; every control step (target, command, measured joints, fingertip, torques, temperatures) to `episode/session/log.jsonl`. `robo info` reports the limits under `embodiment.safety`.

## Human-attended mode

Real episodes stop at operator gates: `arm` (enable torque; the arm holds its pose) and `reset` (the scene is set up; the task's setup text is shown), and optionally `release` at the end. A refused or unanswered gate stops the episode before anything moves. Channels (`real.operator`): `tty` (the terminal that started the run), `file` (answer from any terminal with `robouse operator status` / `robouse operator answer yes|no [--note ...]`), `script` (mock only; refused with a live driver). Live typed feedback: `robouse operator say "..."` reaches the policy in the next `robo observe` under `operator_notes`.

Verdicts: tasks with a measurable goal are judged from the measured joints (`verdict: pose`, fingertip by forward kinematics); tasks without one ask the operator (`verdict: operator`, yes/no/partial/skip, or a 0-N stage for tasks with a `rubric`, which also gives the progress metric). Unattended live runs need `attended: false` and `ROBOUSE_REAL_UNATTENDED=1` in the operator's environment.

## Hardware-in-the-loop mock

`driver: mock` replays a fixture recorded on the real robot (`assets/hil/`, built with `tools/assets/make_hil_fixture.py` from `recorder.py` sessions): a `ReplayRobot` with LeRobot's `Robot` shape plugs in where the SDK would, so the real driver, the safety layer and the episode server run unchanged. The arm follows commands with a per-joint tracking model fitted to the recording (lag and gravity sag), reports the recorded torques and temperatures, and shows the recorded camera frames closest to its current pose. It models no contact with objects, so manipulation outcomes on the mock come from the scripted stand-in operator (staged checkpoints on the measured pose), never from physics.

| Fixture | Recorded on | Content |
|---|---|---|
| `metal-bowl-121853` | Metal arm, 2026-09-05 (first successful bead grasp) | 842 control steps, 40 keyframes from the gripper and overhead cameras |
| `so101-sort-left`, `so101-bimanual-sort` | SO-101 pair, 2026-09-05 | recorded joint states and stills (no control log; default tracking model) |
| `piper-synthetic` | none | park pose, default tracking |
| (no fixture) `robot: ros` | none | an in-process mock rosbridge server: a simulated arm that tracks commands in real time and publishes joint states (20 Hz) and a camera (5 Hz); the real rosbridge driver talks to it over a websocket |

`robouse hil-check` replays a recorded session's commands through the safety guard with the recorded measurements and simulates the fitted tracking model. On `metal-bowl-121853`: 0 of 842 steps vetoed, the guard changed 42 gripper steps and 1 shoulder step (the same ramp the original plugin applied), tracking error 0.16 deg RMS open-loop (1.0 deg max).

## Tests

`tests/test_real.py` (14 tests; also the rosbridge driver against the mock server with both command types, radians/degrees, cameras and stale-state detection, and the ROS task end to end): kinematics against the recorded poses, strict replay, fingertip goal verdict, workspace veto with no step spent, e-stop, refused arm gate, over-temperature stop, operator feedback and the mock verdict, the scripted operator refused with a live driver, the file channel, the rig switch, the Piper driver on a mock SDK.

Dogfood on the mock: reference solutions 6/6 (`tasks/real`, including `real-ros-joint-pose` on the mock rosbridge server), no-op 0/6; StationeryBench flows in [suites/stationerybench.md](suites/stationerybench.md). Live hardware steps (the `lerobot` and `piper` factories, cameras, the `tty` gate on a real terminal) are untested because no robot was connected while this was built.
