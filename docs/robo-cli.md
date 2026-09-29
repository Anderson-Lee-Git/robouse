# robo CLI

`robo` is the agent's only way to act. It is one standard-library Python file that sends one JSON request per call to the episode server at `$ROBO_SOCKET` (or `$ROBOUSE_SOCKET`). The file is BenchFlow's (`benchflow/embodied/robo.py`, see BenchFlow's `docs/embodied.md`); the runner puts a copy first on the agent's `PATH`, BenchFlow copies it into the agent container, and `pip install robouse` also installs it.

```console
$ robo help
`robo`: the only way an agent touches the robot. Standard library only; this file is copied as-is into agent images.

Finds the episode socket from $ROBO_SOCKET (or $ROBOUSE_SOCKET, or ./.robouse/socket) and sends one JSON request.

  robo info                                     the robot: action groups, skills, sensors, budgets
  robo observe [--image] [--camera C|all]       state; --image also saves camera PNGs and prints their paths
  robo act GROUP=V1,V2,... [GROUP=...] [--repeat N]
                                                one step (N steps, N <= the task's max_repeat) commanding the named
                                                action groups; groups you do not name hold (see `robo info`)
  robo act V1 V2 ... [--repeat N]               the whole flat action vector, in `robo info` order
  robo skill NAME [ARG ...] [key=value ...]     run a named skill listed by `robo info`
  robo done ["message"]                         end the episode and ask for scoring
  robo give-up ["message"]                      end the episode without claiming success
  robo move-to X Y Z [--grip G]                 shorthand for the arm's move_to skill
  robo grip G [--steps N]                       shorthand for the gripper's set skill (+1 close, -1 open)
Add --json to any command for raw JSON output.

Examples:
  robo act arm.ee_delta=0.2,0,-0.1 gripper=1 --repeat 5
  robo act left.ee_delta=0,0.3,0 right.gripper=-1
  robo skill arm.move_to 0.1 0.6 0.2 grip=1
```

## Commands

| Command | Notes |
|---|---|
| `robo info` | The robot's embodiment (action groups with components, bounds, units, control mode and hold policy; skills with typed arguments; cameras; proprioception; budgets), plus the protocol-1 keys: action names and bounds, skill names, steps used and budget. On vision tasks also the visible fields and each camera's size, intrinsics, pose and projection matrix. |
| `robo status` | Whether the episode has finished, its outcome and the steps used. |
| `robo observe` | State as numbers. `--image` also saves a PNG from the task's camera into the workspace's `observations/` and prints its path; `--camera C` picks a camera (and implies `--image`), `--camera all` saves one per camera. On vision tasks it saves one image per camera on every call. |
| `robo act GROUP=V1,V2 ...` | One step commanding one or more named action groups (e.g. `arm.ee_delta=0.2,0,-0.1 gripper=1`, or `left.ee_delta=... right.gripper=...` on ALOHA); groups not named hold (see `robo info`). `--repeat N` as below. |
| `robo act A1 A2 ...` | The whole flat action vector, applied `--repeat N` times. N is clipped to 50, or to the task's `max_repeat`. |
| `robo move-to X Y Z` | Skill (`arm.move_to`; `body.move_to` on the drone): moves the hand toward a point. `--grip G` sets the gripper during the move; stops within `--tol` metres (default 0.01) or after `--max-steps` steps (default 100, at most 150). |
| `robo grip G` | Skill (`gripper.set`; `arm.grasp` on DexJoCo hands): holds position and sets the gripper for `--steps N` steps (default 15). |
| `robo skill NAME [ARG ...] [key=value ...]` | A named skill from `robo info`, e.g. `robo skill arm.move_to 0.1 0.6 0.2 grip=1`, or a BEHAVIOR primitive such as `robo skill grasp apple_1`. Arguments are typed and checked. |
| `robo done "message"` | Ends the episode and asks for scoring. |
| `robo give-up "reason"` | Ends the episode without claiming success. |

Skills are sequences of low-level actions run by the server, and each simulated step counts against the budget. A task can turn skills off (`skills: false`), leaving only `robo act`. Without an episode, commands print an error and exit 1: `error: no episode: ROBO_SOCKET is not set`, or `error: episode server is not running (episode may have finished)`.

## Protocol

One JSON object per connection, newline-terminated, for example `{"op": "act", "action": [0, 0, -1, 1], "repeat": 5}`. The response is `{"ok": true, "result": {...}}` or `{"ok": false, "error": "..."}`. This is protocol 2 (BenchFlow's `benchflow.embodied.protocol`): `act` also takes `{"groups": {"arm.ee_delta": [0, 0, -1], "gripper": [1]}}`, `skill` takes a list or an object of arguments, and a request may carry `role` (from `ROBO_ROLE`). Operations: `info`, `status`, `observe`, `act`, `move_to`, `grip`, `skill`, `done`, `give_up` and `shutdown`. `robo` does not expose `shutdown`, which ends the episode as `agent_exited`. There is no reset, teleport or state-setting operation.
