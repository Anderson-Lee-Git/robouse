# Task format

A robo-use task is a folder in BenchFlow's native task format:

```
tasks/<suite>/<task-id>/
  task.md              YAML frontmatter (settings) + the instruction the agent reads (markdown body)
  oracle/solve.sh      reference solution; must score 1.0
  verifier/test.sh     turns the episode server's verdict into reward.txt
```

Task folders are a BenchFlow task format: BenchFlow loads them as they are and generates the `environment/` folder (agent image and simulator service), the BenchFlow verifier and the packaged oracle from the installed robouse package (`robouse.engine.format`); see [benchflow.md](benchflow.md). Adapters write task folders with `robouse.tasks.write_task`, directly or through `robouse.tasks.to_native`.

The loader (`robouse.tasks.load_task`) also reads the older layout (`task.toml` + `instruction.md` + `solution/solve.sh` + `tests/test.sh`) until every folder is migrated. As of 2026-09-27 every folder under `tasks/` is in the layout above; the older-layout reader is kept for external task folders.

## task.md

```markdown
---
schema_version: '1.3'
task:
  name: robouse/metaworld-push
  description: Push the puck to the goal on the table.
metadata:
  source_benchmark: Meta-World MT50 (Farama, v3)   # where the task comes from
  source_task: push-v3
  suite: metaworld
  category: manipulation                           # manipulation, navigation, rule-inference, safety, ...
  difficulty: medium
  tags: [sawyer, mujoco, single-arm]
agent:
  timeout_sec: 900          # wall-clock limit for the harness
verifier:
  timeout_sec: 120
robouse:
  id: metaworld-push
  backend: metaworld        # metaworld | tabletop | gymrobotics
  env: push-v3              # backend-specific scene/env id
  seed: 0                   # picks the object/goal layout
  max_steps: 500            # simulated step budget; every step counts, including skills
  camera: corner
  skills: true              # allow the move_to / grip helpers (default true)
  success_mode: first       # "first" or "final" (default; below)
  obs_mode: state           # "state" (default) or "vision" (below)
---

# Push

A Sawyer robot arm with a two-finger gripper stands at a table ...
```

Tabletop tasks also carry the whole scene in `robouse.scenario` (objects, fixtures, goal predicate), so every folder describes itself.

## Observation modes

- `obs_mode: state` (default): `robo observe` returns every public state field (robot, objects, goals).
- `obs_mode: vision`: `robo observe` returns only `visible_fields` (by default the robot's own `hand_pos` and `gripper_open`) and saves one image per camera in `cameras`. `robo info` gives each camera's 3x4 projection matrix P, with `[u*w, v*w, w] = P @ [x, y, z, 1]` in the saved image's pixels (v down), so the agent can locate what it sees. The reference solution still gets full state: the runner gives it a per-episode oracle token that model harnesses never see.

## Scoring

The episode server judges success from the physical state; the agent's claim in `robo done` never counts.

- `success_mode: final` (default): after `robo done`, the robot holds still for 10 steps, then the goal predicate is checked. The goal must still hold when the robot stops.
- `success_mode: first`: the episode ends as solved the first time the backend's own success signal fires. This matches Meta-World's evaluation protocol, where a task is solved once `info["success"]` is 1. The agent is told in the `robo` response that the episode finished.

Other endings: `robo give-up`, the step budget running out, the wall-clock budget running out, or the harness exiting without `robo done` (the runner closes the episode as given up). All of these score 0, except on safety tasks marked `safety: refuse`, where refusing with `robo give-up` and no harmful contact is the correct, rewarded behaviour.

`verifier/test.sh` reads the trusted `result.json` from `$ROBOUSE_EPISODE_DIR` and writes `1` or `0` to `$ROBOUSE_VERIFIER_DIR/reward.txt` (default `/logs/verifier/reward.txt`, BenchFlow's convention).

## Reference solutions

`oracle/solve.sh` drives the robot through the same socket interface an agent uses (`python -m robouse.oracle --backend ... --env ...`). For Meta-World it is Meta-World's own scripted expert reading `obs_vector`; for the other backends it is the backend module's `oracle_main`. Running every task's reference solution through the real runner is the first audit step: a task whose reference solution does not score 1 is broken. The no-op control (`--harness noop`) must score 0 on every task.

## Adding a suite

Write an adapter under `adapters/<suite>/generate.py` that writes task folders with `robouse.tasks.write_task`, and, if the scene is new, a backend under `src/robouse/backends/` (registered in `backends/__init__.py`). `backends/base.py` defines the required methods: `reset`, `step`, `observe`, `render` and `success`. `session.py` also uses these optional ones when a backend has them: `skills` and `hand_pos` for the `move_to`/`grip` helpers, `mj_model_data` for the camera projection matrices of vision mode, and `judge(outcome, text)` for a verdict that depends on how the episode ended (the safety tasks use it). Then run the suite with `--harness oracle` (must be 100%) and `--harness noop` (must be 0%).
