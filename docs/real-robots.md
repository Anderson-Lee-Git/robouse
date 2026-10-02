# Real robots

The `real` suite runs real arms behind the same episode server and `robo` command as the simulators. By default each task runs on a hardware-in-the-loop mock that replays a session recorded on the real arm, so the whole stack runs without hardware.

```console
$ robouse run --task real-metal-reach --harness oracle --out runs/real
```

The suite has 6 tasks on the MakerMods Metal arm, the SO-101, the AgileX Piper and a ROS arm. `robo info` reports `mode: hil-mock` on the mock and `mode: real` on hardware. The mock follows commands with a tracking model fitted to the recording and shows the recorded camera frames closest to its pose. It models no contact with objects: on the mock, a pick-and-place verdict comes from a scripted stand-in operator.

`robouse robots` lists the robot profiles, drivers and recorded sessions. `robouse hil-check` replays the recorded sessions through the safety layer.

## Safety layer

The episode server checks every control step, in this order:

1. **E-stop.** `robouse estop [REASON]` latches a stop: the next command in any real episode, or the next check between requests, ends it as `safety_stop` (score 0). `robouse estop --clear` releases it.
2. **Joint limits.** Targets are clamped to the robot's limits. Where a mechanical stop has been measured, the limit sits at least 2.2 degrees inside it: on the Metal arm, elbow_flex ends at 174 (its stop is at 176.4), shoulder_lift at -2.5 (with torque off the parked arm rests at about 0) and the gripper at 2 (it closes at -0.25); on the SO-101, the gripper ends at 2 and 98 (its calibrated ends are 0 and 100) and the other joints already sat 2.5 degrees or more inside their calibrated ranges.
3. **Workspace.** On arms with a kinematic model (the Metal and the SO-101), the path to a new target is checked by forward kinematics: the arm must stay above the table and inside the workspace box. A violating move is refused before anything moves, and no step is spent.
4. **Speed.** A per-step joint speed limit, lower near the table.
5. **Wind-up.** A command never leads the measured joint by more than a few degrees.
6. **Temperature.** A motor over the limit stops the episode, also when it is still over the limit as the episode starts.
7. **Stale telemetry.** A joint reading more than 1 second old stops the episode (a cached bus keeps serving its last values when the link to the motors dies). The Piper's joints arrive in three feedback frames (joints 1-2, 3-4 and 5-6), each dated on its own: one that falls silent stops the episode, and the stop names it.
8. **Loop watchdog.** A control step slower than 2 seconds, or three in a row slower than 0.5 seconds, stops the episode. On a rig slower than about 6 control steps a second, the limits stretch to 10 and 3 control periods.
9. **Contact watch.** A move that ends within 3 cm of the table is watched: a contact stops that move, the arm holds where it is, and `robo` reports it under `contact`. A second contact, a contact anywhere else, or one during the 10 steps the arm holds still after the episode ends (`robo done`, give-up, budget or time limit) stops the episode. The Metal arm watches joint torque (thresholds from its 2026-09-05 bench sessions) and whether the fingertips stop short of a commanded descent; the SO-101 only the latter, since its driver reads no joint torque. The gripper's own torque is not watched (grasping is contact by design), but the arm joints stay watched while the gripper moves. A ROS arm watches JointState effort when its rig file sets thresholds; with no kinematic model, any contact then stops the episode.

Between requests, while the agent thinks, the episode server reads the arm at least once a second and checks the e-stop, the freshness of the joint readings and the temperatures; the motors keep the last command. A failed check stops the episode like a failed step.

The AgileX Piper and the bimanual SO-101 have no contact watch: their drivers read no joint torque and they have no kinematic model, so nothing detects them pushing against an object. The physical e-stop confirmation applies to them as to every live robot.

Limits and thresholds are in the robot profiles (`src/robouse/real/robots.py`); the `envelope:` and `contact:` blocks of a task or rig file override them.

**After a stop, and when the episode ends.** The command of every arm joint is first brought to its measured position, within the per-step speed limit, so nothing keeps pushing. The gripper keeps its command, so a grasped object is not let go. A stale reading is never used: without a fresh one, the arm keeps its last command. If the gripper holds nothing, the robot has a rest pose and the way there stays in the workspace, the arm then moves there slowly and torque is released once it is at rest (a ROS arm holds the rest pose instead: the bridge cannot turn its motors off). Otherwise it keeps holding where it is (with the e-stop latched, or with something in the gripper, it always does), and the session log and the operator are told why. The same happens when the run is interrupted. When the link to the motors is down, the arm keeps its last command and only the physical e-stop stops it.

Every intervention is written to `episode/session/events.jsonl`.

## The operator

Before a live robot is armed, the operator confirms that a physical e-stop (a power cut-off) is within reach; no setting skips this. A real episode then waits at operator gates before anything moves: `arm` (enable torque) and `reset` (the scene is set up). A refused or unanswered question stops the episode. The operator answers in the terminal that started the trial, or, with `operator: file` in the task's `real:` block, from another terminal with `robouse operator status` and `robouse operator answer yes|no`; `status` also shows how the arm was left after the last stop. `robouse operator say "..."` sends a remark the policy sees in its next `robo observe`. On the mock, a scripted operator answers and the physical e-stop is not asked.

In `robouse run-many`, a safety stop on a real robot holds the batch: the next trial waits until the operator has inspected the robot and answered `inspect`, which is recorded in the stopped trial's session log. Without an attended operator, or when the answer is no, the batch ends: `halt.json` in the run folder names the trial and the cause, and `run-many` exits with status 3. An error in the hold itself (reading the trial's result, recording the inspection, a full disk) also ends the batch with status 3, and `halt.json` gives the error when it can be written. Trials on a live robot always run one at a time, whatever `--concurrency` says.

Tasks with a measurable goal are judged from the measured joints. Tasks without one ask the operator for the verdict.
