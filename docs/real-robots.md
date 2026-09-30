# Real robots

The `real` suite runs real arms behind the same episode server and `robo` command as the simulators. By default each task runs on a hardware-in-the-loop mock that replays a session recorded on the real arm, so the whole stack runs without hardware.

```console
$ robouse run --task real-metal-reach --harness oracle --out runs/real
```

The suite has 6 tasks on the MakerMods Metal arm, the SO-101, the AgileX Piper and a ROS arm. `robo info` reports `mode: real`. The mock follows commands with a tracking model fitted to the recording and shows the recorded camera frames closest to its pose. It models no contact with objects: on the mock, a pick-and-place verdict comes from a scripted stand-in operator.

`robouse robots` lists the robot profiles, drivers and recorded sessions. `robouse hil-check` replays the recorded sessions through the safety layer.

## Safety layer

The episode server checks every control step, in this order:

1. **E-stop.** `robouse estop [REASON]` latches a stop: the next command in any real episode ends it as `safety_stop` (score 0) and the arm holds. `robouse estop --clear` releases it.
2. **Joint limits.** Targets are clamped to the robot's limits minus a margin.
3. **Workspace.** On arms with a kinematic model, the path to a new target is checked by forward kinematics: the arm must stay above the table and inside the workspace box. A violating move is refused before anything moves, and no step is spent.
4. **Speed.** A per-step joint speed limit, lower near the table.
5. **Wind-up.** A command never leads the measured joint by more than a few degrees.
6. **Temperature.** A motor over the limit stops the episode.

Every intervention is written to `episode/session/events.jsonl`.

## The operator

A real episode waits at operator gates before anything moves: `arm` (enable torque) and `reset` (the scene is set up). A refused or unanswered gate stops the episode. The operator answers in the terminal that started the trial, or, with `operator: file` in the task's `real:` block, from another terminal with `robouse operator status` and `robouse operator answer yes|no`. `robouse operator say "..."` sends a remark the policy sees in its next `robo observe`. On the mock, a scripted operator answers.

Tasks with a measurable goal are judged from the measured joints. Tasks without one ask the operator for the verdict.
