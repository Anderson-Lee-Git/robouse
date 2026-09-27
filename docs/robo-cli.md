# The `robo` command

`robo` is the agent's only way to act. It is a single standard-library Python file that sends one JSON request per call over the episode's Unix socket (`$ROBOUSE_SOCKET`). The runner puts it first on the agent's `PATH`.

| Command | What it does |
|---|---|
| `robo info` | Action space (names, bounds, meaning), available skills, steps used and budget |
| `robo observe` | Robot and object state as numbers |
| `robo observe --image [--camera C]` | Also saves a camera image into `observations/` in the workspace and prints its path; `--camera` picks one of the task's cameras |
| `robo act A1 A2 ... [--repeat N]` | Apply one low-level action N times (N ≤ 50, or the task's `max_repeat`) |
| `robo move-to X Y Z [--grip G] [--max-steps N] [--tol T]` | Skill: move the gripper toward a point with a proportional controller; stops within `--tol` metres (default 0.01) or after `--max-steps` steps (default 100, at most 150) |
| `robo grip G [--steps N]` | Skill: hold position and set the gripper (+1 close, -1 open) for N steps (default 15) |
| `robo done "summary"` | End the episode and ask for scoring |
| `robo give-up "reason"` | End the episode without claiming success |

Add `--json` to any command for the raw response. `robo help` prints the command list.

Skills are ordinary sequences of low-level actions executed by the server; each simulated step counts against the budget. A task can disable them (`skills: false` in the `robouse:` block of `task.md`), in which case only `robo act` moves the robot. A task can also lower the limit on `--repeat` (and on `grip --steps`) with `max_repeat`; larger values are clipped to the limit, not rejected.

## Protocol

Request: one JSON object per connection, newline-terminated, e.g. `{"op": "act", "action": [0, 0, -1, 1], "repeat": 5}`. Response: `{"ok": true, "result": {...}}` or `{"ok": false, "error": "..."}`. When an action ends the episode (goal reached in `first` mode, budget exhausted), the result carries `"episode": "finished: ..."` and further motion requests are rejected.

Operations: `info`, `status`, `observe`, `act`, `move_to`, `grip`, `done`, `give_up`, and `shutdown`, which `robo` does not expose: it stops the server, which closes an unfinished episode as `agent_exited` and judges it like any other ending (the BenchFlow verifier uses it). There is no reset, teleport, state-setting or code-evaluation operation.

## Example session

```
$ robo observe
state:
  hand_pos: [0.0046, 0.6014, 0.1951]
  gripper_open: 1.0
  obj1_pos: [-0.0125, 0.6892, 0.02]
  goal_pos: [-0.0233, 0.8792, 0.1822]
steps_used: 0
max_steps: 500
$ robo move-to -0.0125 0.6892 0.05 --grip -1
reached: True
...
$ robo done "placed the puck at the goal"
```
