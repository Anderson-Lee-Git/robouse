# robouse

**robo-use: agent as a policy for embodied agents.** A BenchFlow extension that turns robot manipulation and navigation benchmarks into tasks an LLM agent harness solves by driving the robot itself, one shell command at a time. Think Terminal-Bench plus ARC, for robots.

- **Tasks** are BenchFlow-native task folders adapted from existing benchmarks (Meta-World, Gymnasium-Robotics, LIBERO-style scenes, ARC-style rule inference, robo-use families, RoboHarm-style safety pairs). Every task ships a reference solution that scores 1.0.
- **Harnesses** are the agents people already use (Claude Code, Codex, mini-swe-agent, ...) with any model. No harness integration is needed beyond a shell: the robot is driven through the `robo` command.
- **The episode server is trusted.** It owns the simulator, enforces the step budget, records video and judges success from the physical state. The agent never touches simulator objects.
- **Every trial is recorded** as a BenchFlow trial directory with video, so it opens in the BenchFlow viewer.

Site: [robouse.ai](https://robouse.ai). Source: [github.com/benchflow-ai/robouse](https://github.com/benchflow-ai/robouse). Status log: [STATUS.md](https://github.com/benchflow-ai/robouse/blob/main/STATUS.md).

## Install

Python 3.12 or newer. The base package gives you the task loader, the `robouse` command, the agent-facing `robo` command (standard library only) and BenchFlow, which runs every trial: the simulator runs in its own Docker container, so a BenchFlow run needs no simulator on the host (see [docs/benchflow.md](https://github.com/benchflow-ai/robouse/blob/main/docs/benchflow.md)). The simulator extras are for the local engine (`--engine local`, no Docker) and for development:

```sh
pip install robouse                  # task loader, `robouse` and `robo` commands
pip install 'robouse[sim]'           # + MuJoCo and video recording: tabletop, ARC-style, hard, safety, vision,
                                     #   robo-use families, RoboHarm, menagerie and drone suites
pip install 'robouse[metaworld]'     # + Meta-World
pip install 'robouse[gymrobotics]'   # + Gymnasium-Robotics (Fetch, PointMaze)
pip install 'robouse[robosuite]'     # + robosuite 1.5
pip install 'robouse[all]'           # all of the above
```

Meta-World (and therefore `[all]`) supports Python up to 3.13. On Python 3.14, `pip install 'robouse[metaworld]'` does not fail: pip falls back to the empty 0.0.2 placeholder and the `robouse` command disappears. Writing `'robouse[metaworld]>=0.1'` makes pip report the real error instead.

LIBERO, RoboCasa and DexJoCo need setup beyond pip; see their suite docs. The RoboCasa and DexJoCo tasks were added after 0.1.0 and are not in the 0.1.0 package; run them from a checkout (below).

**Tasks ship with the package.** All task folders (about 5 MB of text: `task.md`, reference solution, verifier) are inside the wheel, so a task can be named by its id. `robouse tasks` lists them and `robouse tasks --path` prints where they are; copy that folder if you want to edit tasks. **Robot meshes are fetched, not shipped:** the menagerie, RoboHarm and drone suites use MuJoCo Menagerie models (about 43 MB); run `robouse fetch-assets` once to download them from the pinned upstream commit into `~/.cache/robouse/menagerie`, with a SHA-256 check per file.

## Quickstart

```sh
# list the bundled tasks (id, backend, env)
robouse tasks

# check a task with its reference solution (reward should be 1); trials run on BenchFlow with Docker
robouse run --task arc-gravity --agent oracle --out jobs
robouse run --task metaworld-reach --agent noop --out jobs      # negative control: must score 0

# let an agent be the policy: any BenchFlow agent (claude, codex, gemini, openhands, ...; `bench agent list`)
robouse run --task metaworld-push --agent claude --model claude-opus-5 --out jobs
robouse run --task metaworld-push --agent codex --model gpt-6-astra --out jobs

# a whole suite, 4 at a time; `bench eval run` runs the same task folders directly
robouse run-many --tasks "$(robouse tasks --path)/metaworld" --agent codex --model gpt-6-astra --out jobs --concurrency 4
bench eval run --tasks-dir "$(robouse tasks --path)/metaworld" --agent codex --model gpt-6-astra --sandbox docker

# without Docker: the local engine (host processes, macOS Seatbelt sandbox) and its harnesses (docs/harnesses.md)
robouse run --engine local --task arc-gravity --harness oracle --out runs/try
```

To work on robouse itself, install a checkout in editable mode; it then uses the checkout's `tasks/` and `assets/`:

```sh
git clone https://github.com/benchflow-ai/robouse.git && cd robouse
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[metaworld,gymrobotics]"
```

Each trial is a BenchFlow trial, `jobs/<job>/<task>__<id>/`, with `result.json`, the agent's trajectory, `verifier/reward.txt`, the episode record in `verifier/episode/` and `artifacts/recording.mp4`.

## How it works

```
 harness (Claude Code, Codex, ...)            trusted episode server (robouse serve)
 ┌─────────────────────────────────┐   JSON    ┌────────────────────────────────────┐
 │ reads instruction.md            │  over a   │ MuJoCo simulator (Meta-World,      │
 │ runs `robo observe`, `robo act` │◄─────────►│ tabletop, Gymnasium-Robotics)      │
 │ ... `robo done`                 │  Unix     │ step + wall-clock budgets          │
 └─────────────────────────────────┘  socket   │ video + trace recording            │
                                               │ success judged from physical state │
                                               └────────────────────────────────────┘
```

The agent sees only what `robo` returns: robot and object state as numbers, and camera images on request. See [docs/robo-cli.md](https://github.com/benchflow-ai/robouse/blob/main/docs/robo-cli.md).

## Docs

- [docs/quickstart.md](https://github.com/benchflow-ai/robouse/blob/main/docs/quickstart.md): install, list tasks and run a first trial, step by step (tested against 0.1.0 from PyPI)
- [docs/task-format.md](https://github.com/benchflow-ai/robouse/blob/main/docs/task-format.md): task folders, the `robouse:` settings block in `task.md`, observation and scoring modes
- [docs/robo-cli.md](https://github.com/benchflow-ai/robouse/blob/main/docs/robo-cli.md): the agent-facing `robo` command
- [docs/harnesses.md](https://github.com/benchflow-ai/robouse/blob/main/docs/harnesses.md): supported harnesses and models, credentials, isolation
- [docs/suites/](https://github.com/benchflow-ai/robouse/blob/main/docs/suites/): each task suite and where it comes from
- [docs/results.md](https://github.com/benchflow-ai/robouse/blob/main/docs/results.md): solve rates per harness, model and suite (generated by `scripts/results.py` from the audit)
- [docs/viewer.md](https://github.com/benchflow-ai/robouse/blob/main/docs/viewer.md), [docs/audit.md](https://github.com/benchflow-ai/robouse/blob/main/docs/audit.md): looking at and checking runs
- [docs/benchflow.md](https://github.com/benchflow-ai/robouse/blob/main/docs/benchflow.md): how robo-use runs on BenchFlow (task format, simulator sidecar, trust model, commands, validation)
- [docs/molmoact2.md](https://github.com/benchflow-ai/robouse/blob/main/docs/molmoact2.md): MolmoAct2 (a VLA) runs on a remote GPU
