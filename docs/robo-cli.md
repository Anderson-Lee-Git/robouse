# robo CLI

`robo` is the agent's only way to act. It is one standard-library Python file that sends one JSON request per call to the episode server at `$ROBOUSE_SOCKET`. The runner puts it first on the agent's `PATH`; `pip install robouse` also installs it.

```console
$ robo help
`robo`: the only way an agent touches the robot. Standard library only.

Finds the episode socket from $ROBOUSE_SOCKET (set by the runner) and sends one JSON request.

  robo info                          action space, skills, step budget
  robo observe [--image] [--camera C] robot and object state; --image also saves a camera PNG and prints its path
  robo act A1 A2 ... [--repeat N]    apply one low-level action N times (N <= 50)
  robo move-to X Y Z [--grip G]      move the hand toward a point (skill; may be disabled per task)
  robo grip G [--steps N]            hold position and set the gripper (+1 close, -1 open)
  robo skill NAME [ARG ...]          run a named high-level skill listed by `robo info` (only some tasks have them)
  robo done ["message"]              end the episode and ask for scoring
  robo give-up ["message"]           end the episode without claiming success
Add --json to any command for raw JSON output.
```

## Commands

| Command | Notes |
|---|---|
| `robo info` | Action names and bounds, available skills, steps used and budget. On vision tasks also the visible fields and each camera's size and projection matrix. |
| `robo observe` | State as numbers. `--image` saves one PNG per camera into the workspace's `observations/` and prints the paths; `--camera C` picks one camera. |
| `robo act A1 A2 ...` | One low-level action, applied `--repeat N` times. N is clipped to 50, or to the task's `max_repeat`. |
| `robo move-to X Y Z` | Skill: moves the hand toward a point. `--grip G` sets the gripper during the move; stops within `--tol` metres (default 0.01) or after `--max-steps` steps (default 100, at most 150). |
| `robo grip G` | Skill: holds position and sets the gripper for `--steps N` steps (default 15). |
| `robo skill NAME` | A named skill, when `robo info` lists one. No task in the 0.1.0 package has them. |
| `robo done "message"` | Ends the episode and asks for scoring. |
| `robo give-up "reason"` | Ends the episode without claiming success. |

Skills are sequences of low-level actions run by the server, and each simulated step counts against the budget. A task can turn skills off (`skills: false`), leaving only `robo act`. Without a running episode, every command prints `error: no episode: ROBOUSE_SOCKET is not set` and exits 1.

## Protocol

One JSON object per connection, newline-terminated, for example `{"op": "act", "action": [0, 0, -1, 1], "repeat": 5}`. The response is `{"ok": true, "result": {...}}` or `{"ok": false, "error": "..."}`. Operations: `info`, `status`, `observe`, `act`, `move_to`, `grip`, `skill`, `done`, `give_up` and `shutdown`. `robo` does not expose `shutdown`, which ends the episode as `agent_exited`. There is no reset, teleport or state-setting operation.
