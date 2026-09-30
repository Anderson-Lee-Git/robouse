# Real robots

Real arms run behind the same episode server and the same `robo` command as the simulators. Every command passes a safety layer in the server, and a human operator gates each episode. By default every real task runs on a hardware-in-the-loop mock that replays sessions recorded on a real arm, so the whole stack runs without hardware.

Live hardware has not been run through Robo Use yet. Everything on this page was tested on the mock.

## Run on the mock

```console
$ robouse run --task real-metal-reach --harness oracle --out runs/real
```

The `real` suite has 6 tasks: reaching and pick-and-place on the MakerMods Metal arm and the SO-101, and joint-pose tasks for the AgileX Piper and a ROS arm. `robo info` reports `mode: real`. The mock follows commands with a tracking model fitted to the recording and shows the recorded camera frames closest to its pose. It models no contact with objects: on the mock, a manipulation task's verdict comes from a scripted stand-in operator, not from physics.

`robouse robots` lists the robot profiles, drivers and recorded sessions. `robouse hil-check` replays recorded sessions through the safety layer.

## Robots and drivers

| `real.robot` | `real.driver` |
|---|---|
| `metal`: MakerMods Metal arm | `lerobot` (MakerMods' LeRobot fork, `metal_follower`) |
| `so101`, `so100`: SO-ARM follower | `lerobot` (`so_follower`) |
| `so101-bimanual`: two SO-101 followers | `lerobot` (`bi_so_follower`) |
| `piper`: AgileX Piper | `piper` (`piper_sdk`) |
| `ros`: any ROS 1 or ROS 2 arm | `rosbridge` (JSON over a websocket to rosbridge_suite; no ROS install needed) |
| any | `mock` (the default): hardware-in-the-loop replay |

## Live hardware

A rig file switches a task from the mock to hardware. Its keys are robot names; any field of the task's `real:` block can be overridden:

```yaml
# rig.yaml
metal:
  driver: lerobot
  port: /dev/ttyACM0
  cameras: {gripper: "0", overhead: "1"}   # OpenCV index, device path or MJPEG URL
  operator: tty                            # or file
```

```sh
robouse run --task real-metal-reach --harness claude-code --rig rig.yaml --out runs/metal
```

This command has not been run on a robot. The switch itself is covered by the test suite. With `--rig`, `run-many` runs one trial at a time, and a lock refuses a second controller on the same robot.

## Safety layer

The episode server checks every control step, in this order:

1. **E-stop.** `robouse estop [REASON]` latches a stop: the next command in any real episode ends it as `safety_stop` (score 0) and the arm holds. `robouse estop --clear` releases it.
2. **Joint limits.** Targets are clamped to the robot's limits minus a margin.
3. **Workspace.** On arms with a kinematic model, the path to a new target is checked by forward kinematics: the arm must stay above the table and inside the workspace box. A violating move is refused before anything moves, `robo` returns the reason, and no step is spent.
4. **Speed.** A per-step joint speed limit, lower near the table.
5. **Wind-up.** A command never leads the measured joint by more than a few degrees.
6. **Temperature.** A motor over the limit stops the episode.

Every intervention is written to `episode/session/events.jsonl`.

## The operator

A real episode waits at operator gates before anything moves: `arm` (enable torque) and `reset` (the scene is set up). A refused or unanswered gate stops the episode. The operator answers in the terminal that started the run (`operator: tty`), or from any terminal (`operator: file`) with `robouse operator status` and `robouse operator answer yes|no`. `robouse operator say "..."` sends a remark the policy sees in its next `robo observe`.

Tasks with a measurable goal are judged from the measured joints. Tasks without one ask the operator for the verdict.
