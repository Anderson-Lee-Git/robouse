# robouse


- **Harnesses** are the agents people already use (Claude Code, Codex, mini-swe-agent, ...) with any model. No harness integration is needed beyond a shell: the robot is driven through the `robo` command.
- **The episode server is trusted.** It owns the simulator, enforces the step budget, records video and judges success from the physical state. The agent never touches simulator objects.

Private, work in progress. Status and overnight log: [STATUS.md](STATUS.md).

## Quickstart

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[metaworld]"

# list tasks
.venv/bin/robouse tasks tasks

# check a task with its reference solution (reward should be 1)
.venv/bin/robouse run --task tasks/metaworld/metaworld-reach --harness oracle --out runs/try

# let an agent be the policy
.venv/bin/robouse run --task tasks/metaworld/metaworld-push --harness claude-code --model claude-opus-5-5 --out runs/try
.venv/bin/robouse run --task tasks/metaworld/metaworld-push --harness codex --model gpt-6-astra --out runs/try

# a whole suite, 4 at a time
.venv/bin/robouse run-many --tasks tasks/metaworld --harness codex --model gpt-6-astra --out runs/mw-codex --concurrency 4
```

Each trial writes `runs/<job>/<task>__<harness>__<id>/` with `result.json`, the agent's raw output and trajectory, the episode trace, `verifier/reward.txt` and `artifacts/recording.mp4`.

## How it works

```
 harness (Claude Code, Codex, ...)          trusted episode server (robouse serve)
 ┌──────────────────────────────┐   JSON    ┌───────────────────────────────────────┐
 │ reads instruction.md          │  over a   │ MuJoCo simulator (Meta-World, tabletop,│
 │ runs `robo observe`, `robo act`│◄────────►│ Gymnasium-Robotics)                    │
 │ ... `robo done`                │  Unix    │ step + wall-clock budgets              │
 └──────────────────────────────┘  socket   │ video + trace recording                 │
                                            │ success judged from physical state      │
                                            └───────────────────────────────────────┘
```

The agent sees only what `robo` returns: robot and object state as numbers, and camera images on request. See [docs/robo-cli.md](docs/robo-cli.md).

## Docs

- [docs/task-format.md](docs/task-format.md): task folders, the `[robouse]` table, scoring modes
- [docs/robo-cli.md](docs/robo-cli.md): the agent-facing `robo` command
- [docs/harnesses.md](docs/harnesses.md): supported harnesses and models, credentials, isolation
- [docs/suites/](docs/suites/): each task suite and where it comes from
- [docs/viewer.md](docs/viewer.md), [docs/audit.md](docs/audit.md): looking at and checking runs
- [docs/benchflow.md](docs/benchflow.md): running robouse tasks through BenchFlow (`bench eval run`)
- [docs/molmoact2.md](docs/molmoact2.md): MolmoAct2 (a VLA) runs on a remote GPU
