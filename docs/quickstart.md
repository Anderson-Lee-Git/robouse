# Quickstart

This page gets you from nothing to a scored robot trial in a few minutes, with no API keys: you install robo-use, list the tasks, and run a task's reference solution (the `oracle` harness) in simulation. The install, check and reference-solution commands below were run as written on 2026-09-27 (macOS, Apple silicon, Python 3.12); the model-harness commands at the end were not, since they need credentials and call paid model APIs.

## Is it on PyPI?

Not yet in usable form. The name [`robouse`](https://pypi.org/project/robouse/) is registered on PyPI, but versions 0.0.1 and 0.0.2 are placeholders: `pip install robouse` installs an empty package with no `robouse` or `robo` command. Publishing the real code is on hold, so install from source as shown below. Once a real release is out (0.1.0 or later), `pip install robouse` will provide the same two commands.

The source repository, `benchflow-ai/robouse` on GitHub, is private for now; you need access to clone it.

## Requirements

- Python 3.11 or newer.
- A machine that can render MuJoCo offscreen, since every trial records a video. macOS works out of the box. On a headless Linux machine MuJoCo needs a headless renderer (`MUJOCO_GL=egl` or `MUJOCO_GL=osmesa`; the simulator Docker image uses osmesa); the commands on this page were not tested on Linux.
- [uv](https://docs.astral.sh/uv/) is used below; plain `pip` works too (see the end of the next section).

## Install from source

```sh
git clone https://github.com/benchflow-ai/robouse.git && cd robouse
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[metaworld,gymrobotics]"
```

This installs two commands into `.venv/bin/`:

- `robouse`: the runner (`robouse run`, `robouse run-many`, `robouse tasks`, `robouse serve`).
- `robo`: the agent-facing command that drives the robot during an episode ([The robo command](robo-cli.md)).

The extras pick the simulators. `metaworld` and `gymrobotics` cover the Meta-World and Gymnasium-Robotics suites; the core package already includes MuJoCo, which the custom tabletop scenes need. Other suites have their own setup: see the [LIBERO](suites/libero.md), [robosuite](suites/robosuite.md) and [DexJoCo](suites/dexjoco.md) suite pages.

The task folders live in the repository (`tasks/`), not in the Python package, so keep the checkout even if you install without `-e`. With plain pip, `python3.12 -m venv .venv && .venv/bin/pip install ".[metaworld,gymrobotics]"` also works.

## Check the install

```sh
.venv/bin/robouse --help
.venv/bin/robouse tasks tasks
```

`robouse tasks <folder>` prints one line per task found under the folder: task id, backend and simulator env id (the env column is empty for tabletop tasks).

## Run a reference solution

Every task ships a reference solution that must score 1. Running it is the quickest end-to-end check, and needs no model or credentials:

```sh
.venv/bin/robouse run --task tasks/metaworld/metaworld-reach --harness oracle --out runs/try
```

It prints a summary like this after about 20 seconds:

```json
{
  "trial": "metaworld-reach__oracle__2c0a53",
  "reward": 1.0,
  "outcome": "success_reached",
  "steps": 51,
  "wall_s": 22.4,
  "exception": null
}
```

The negative control, `--harness noop`, calls `robo done` without moving and must score 0:

```sh
.venv/bin/robouse run --task tasks/metaworld/metaworld-reach --harness noop --out runs/try
```

A whole suite, 4 trials at a time (the 12 Gymnasium-Robotics tasks take about 30 seconds and end with `oracle/-: 12/12 solved`):

```sh
.venv/bin/robouse run-many --tasks tasks/gymrobotics --harness oracle --out runs/gr-oracle --concurrency 4
```

## What a trial writes

Each trial writes `<out>/<task>__<harness>__<id>/` with `config.json`, `result.json`, the agent's raw output and trajectory under `agent/`, the episode record under `episode/` (`result.json`, `trace.jsonl`, `frames.jsonl`), `verifier/reward.txt`, and `artifacts/recording.mp4` (the episode video). See [Viewing trials](viewer.md) to open them in the BenchFlow viewer.

## Let an agent be the policy

Model harnesses need the harness's CLI installed and logged in: `claude` for Claude Code, `codex` for Codex, `mini` for mini-swe-agent. Credentials and isolation are described in [Harnesses and models](harnesses.md).

```sh
.venv/bin/robouse run --task tasks/metaworld/metaworld-push --harness claude-code --model claude-opus-5-5 --out runs/try
.venv/bin/robouse run --task tasks/metaworld/metaworld-push --harness codex --model gpt-6-astra --out runs/try
.venv/bin/robouse run-many --tasks tasks/metaworld --harness codex --model gpt-6-astra --out runs/mw-codex --concurrency 4
```

## Next

- [Task format](task-format.md): what a task folder contains and how it is scored.
- [The robo command](robo-cli.md): everything the agent can do.
- [Running through BenchFlow](benchflow.md): the same tasks as BenchFlow packages, with the simulator in its own container.
