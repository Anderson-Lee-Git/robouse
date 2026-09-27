# Quickstart

This page gets you from nothing to a scored robot trial in a few minutes, with no API keys. You install robo-use from PyPI, list the bundled tasks, and run a task's reference solution (the `oracle` harness) in simulation.

The install, listing and reference-solution commands below were run exactly as written on 2026-09-27 against `robouse` 0.1.0 from PyPI, in fresh virtual environments on macOS (Apple silicon) with Python 3.12 (all commands) and 3.11 (the `sim` extra and `arc-gravity`). The model-harness commands near the end were not run for this page, because they need credentials and call paid model APIs.

## Install

Python 3.11 to 3.13 (3.11 and 3.12 were tested). Create a virtual environment and install the package with the simulators you need:

```sh
python3.12 -m venv .venv && source .venv/bin/activate
pip install 'robouse[sim]>=0.1'          # MuJoCo and video recording: tabletop, ARC-style, hard, safety, vision,
                                         #   robo-use families, RoboHarm, menagerie and drone suites
pip install 'robouse[metaworld]>=0.1'    # + Meta-World (includes [sim])
```

Keep the `>=0.1`. Versions 0.0.1 and 0.0.2 on PyPI are empty placeholders without extras, and when an extra cannot be installed, pip falls back to them instead of failing. This happens with `metaworld` and `all` on Python 3.14, because Meta-World 3.1 supports only Python up to 3.13: plain `pip install 'robouse[metaworld]'` then replaces robouse 0.1.0 with the empty 0.0.2, printing only `WARNING: robouse 0.0.2 does not provide the extra 'metaworld'`, and the `robouse` command disappears. With `>=0.1`, pip reports the real error instead. The `sim`, `gymrobotics` and `robosuite` extras do install on Python 3.14.

The extras:

| Extra | Adds | Suites |
|---|---|---|
| (none) | the task loader and the `robouse` and `robo` commands (numpy, PyYAML) | none: listing tasks only |
| `sim` | MuJoCo, imageio, Pillow | tabletop (`libero-style`, `arc-style`, `robo-use-families`, `safety`), `vision`, `hard`, `roboharm`, `menagerie`, `drone` |
| `metaworld` | `sim` + Meta-World | `metaworld` |
| `gymrobotics` | `sim` + Gymnasium-Robotics | `gymrobotics` |
| `robosuite` | `sim` + robosuite 1.5 | `robosuite` |
| `all` | all of the above, plus SciPy | |

Without a simulator extra, `robouse run` stops with `robouse: the simulator dependencies are not installed (missing: mujoco, imageio, PIL)` and names the extra to install.

Some suites need setup that pip cannot do: [LIBERO](suites/libero.md) (installed with `--no-deps`), [RoboCasa](suites/robocasa.md) and [DexJoCo](suites/dexjoco.md) (their own environments and downloads). The DexJoCo and RoboCasa tasks were added after the 0.1.0 release and are not in the 0.1.0 package; run them from a checkout (see [From source](#from-source)).

Rendering: every trial records a video, so MuJoCo must be able to render offscreen. macOS works out of the box. On a headless Linux machine MuJoCo needs `MUJOCO_GL=egl` or `MUJOCO_GL=osmesa` (the simulator Docker image uses osmesa); this was not tested for this page.

## Check the install

```sh
robouse --version
robouse --help
robouse tasks
robouse tasks --path
```

`robouse --version` prints `robouse 0.1.0`. `robouse tasks` lists the tasks bundled in the package, one per line: task id, backend and simulator env id (the env column is empty for tabletop tasks). 0.1.0 bundles 327 tasks. `robouse tasks --path` prints the folder they are installed in (`.../site-packages/robouse/bundled_tasks`, one subfolder per suite); copy it if you want to edit tasks. `robouse tasks <folder>` lists the tasks under any other folder.

## Run a reference solution

Every task ships a reference solution that must score 1. Running it is the quickest end-to-end check and needs no model or credentials. A task can be named by its id:

```sh
robouse run --task arc-gravity --harness oracle --out runs/try
```

After about 15 seconds it prints a summary:

```json
{
  "trial": "arc-gravity__oracle__0bc270",
  "reward": 1.0,
  "outcome": "done",
  "steps": 999,
  "wall_s": 13.0,
  "exception": null
}
```

With the `metaworld` extra installed:

```sh
robouse run --task metaworld-reach --harness oracle --out runs/try
```

This one ends with `"reward": 1.0` and `"outcome": "success_reached"` after 51 steps (about 20 seconds).

The negative control, `--harness noop`, calls `robo done` without moving the robot and must score 0:

```sh
robouse run --task metaworld-reach --harness noop --out runs/try
```

`robouse run-many` runs a set of tasks. `--tasks` takes a folder (default: all bundled tasks), so a suite is its subfolder of `robouse tasks --path`. This runs the first 4 Meta-World reference solutions, 4 at a time, in about 20 seconds (drop `--limit` for all 50):

```sh
robouse run-many --tasks "$(robouse tasks --path)/metaworld" --harness oracle --out runs/mw-oracle --concurrency 4 --limit 4
```

It prints one line per trial and ends with `oracle/-: 4/4 solved`. `--filter` (substring match on task ids) and `--task-list` (a file of task ids) pick other subsets.

## Robot meshes for menagerie, RoboHarm and drone

These suites use MuJoCo Menagerie robot models, which are downloaded rather than shipped. Run this once (about 42 MB, 93 files, checked by SHA-256, stored in `~/.cache/robouse/menagerie`):

```sh
robouse fetch-assets
robouse run --task drone-inspect-mast --harness oracle --out runs/try
```

## What a trial writes

Each trial writes `<out>/<task>__<harness>__<id>/` with `config.json`, `result.json`, the agent's raw output and trajectory under `agent/`, the episode record under `episode/` (`result.json`, `trace.jsonl`, `frames.jsonl`), `verifier/reward.txt`, and `artifacts/recording.mp4` (the episode video). See [Viewing trials](viewer.md) to open them in the BenchFlow viewer.

## Let an agent be the policy

Not run for this page. Model harnesses need the harness's CLI installed and logged in: `claude` for Claude Code, `codex` for Codex, `mini` for mini-swe-agent. Credentials and isolation are described in [Harnesses and models](harnesses.md).

```sh
robouse run --task metaworld-push --harness claude-code --model claude-opus-5-5 --out runs/try
robouse run --task metaworld-push --harness codex --model gpt-6-astra --out runs/try
robouse run-many --tasks "$(robouse tasks --path)/metaworld" --harness codex --model gpt-6-astra --out runs/mw-codex --concurrency 4
```

## From source

To work on robo-use itself, or to run tasks added since the last release, install a checkout in editable mode. It then uses the checkout's `tasks/` and `assets/` folders (`robouse tasks --path` prints the checkout's `tasks/`). The repository, `benchflow-ai/robouse` on GitHub, is private for now; you need access to clone it.

```sh
git clone https://github.com/benchflow-ai/robouse.git && cd robouse
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[metaworld,gymrobotics]"
.venv/bin/robouse tasks
.venv/bin/robouse run --task arc-gravity --harness oracle --out runs/try
```

This uses [uv](https://docs.astral.sh/uv/); `python3.12 -m venv .venv && .venv/bin/pip install -e ".[metaworld,gymrobotics]"` works too.

## Next

- [Task format](task-format.md): what a task folder contains and how it is scored.
- [The robo command](robo-cli.md): everything the agent can do.
- [Running through BenchFlow](benchflow.md): the same tasks as BenchFlow packages, with the simulator in its own container.
