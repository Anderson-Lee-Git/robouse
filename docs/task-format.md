# task.md

A task folder holds `task.md`, `oracle/solve.sh` and `verifier/test.sh`. `task.md` is YAML frontmatter followed by the instruction the agent reads, in markdown. This is `metaworld-push`, trimmed:

```markdown
---
schema_version: '1.3'
task:
  name: robouse/metaworld-push
  description: Push the puck to the goal on the table.
metadata:
  source_benchmark: Meta-World MT50 (Farama, v3)
  source_task: push-v3
  suite: metaworld
  category: manipulation
  difficulty: medium
agent:
  timeout_sec: 900
verifier:
  timeout_sec: 120
robouse:
  id: metaworld-push
  backend: metaworld
  env: push-v3
  seed: 0
  max_steps: 500
  camera: corner
  skills: true
  success_mode: first
---

# Push

A Sawyer robot arm with a two-finger gripper stands at a table ...
```

`schema_version`, `task`, `metadata`, `agent` and `verifier` follow BenchFlow's native task format. Robo Use reads `agent.timeout_sec` (the harness's wall-clock limit, default 900 s) and the `robouse:` block.

## The robouse block

| Field | Default | Meaning |
|---|---|---|
| `id` | required | task id, as used by `robouse run --task` |
| `backend` | required | simulator backend: `tabletop`, `metaworld`, `gymrobotics`, `libero`, `robosuite`, `menagerie`, `roboharm`, `drone` |
| `env` | | the backend's scene or env id, e.g. `push-v3` |
| `scenario` | | tabletop only: the whole scene (objects, fixtures, goals); see [Write a task](write-a-task.md) |
| `seed` | 0 | object and goal layout; `--seed` overrides it |
| `max_steps` | backend's | step budget; every simulated step counts, including skills |
| `success_mode` | `final` | `final`: goal checked after `robo done` and 10 still steps. `first`: solved the first time the benchmark's success signal fires |
| `skills` | `true` | allow `robo move-to` and `robo grip` |
| `max_repeat` | 50 | cap on `robo act --repeat` and `robo grip --steps` |
| `obs_mode` | `state` | `state`: all state as numbers. `vision`: only `visible_fields`, plus camera images |
| `visible_fields` | `hand_pos`, `gripper_open` | state fields shown in vision mode |
| `camera` | backend's | camera used for the video |
| `cameras` | `[camera]` | cameras whose images vision mode saves |
| `uncalibrated_cameras` | | cameras `robo info` gives no projection matrix for |
| `safety` | | `refuse` (tabletop, roboharm, drone): refusing with `robo give-up`, without harmful contact, is the rewarded behaviour |

Some backends read fields of their own (robosuite: `robots`, `controller`; LIBERO: `suite`, `task_index`, `init_state`, ...); copy them from a bundled task of that backend. Scoring and observation modes are explained in [Tasks and scoring](tasks.md).

## oracle/solve.sh

The reference solution. It runs like an agent, with `robo` on its `PATH` and no access to the simulator, and it must score 1. The bundled tasks call `python -m robouse.oracle`; on vision tasks the runner gives the reference solution, and only it, the full state. Your own can be plain `robo` commands.

## verifier/test.sh

Copies the episode server's verdict, `$ROBOUSE_EPISODE_DIR/result.json`, into `$ROBOUSE_VERIFIER_DIR/reward.txt` as `1` or `0`. Every bundled task's script does the same; copy one unchanged.
