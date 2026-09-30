# Supported

What Robo Use 0.2.0 supports and how each item was tested. "Docs check": run from the 0.2.0 package for these docs. "v1 runs": the runs published on the [leaderboard](/hub/leaderboard/).

## Models

| Model · harness | Status |
|---|---|
| `moonshotai/Kimi-K3` · `claude-code-glm` | docs check: the [Quickstart](quickstart.md) trial |
| `claude-sonnet-5` · `claude-code` | docs check on 0.1.1; v1 runs |
| `gpt-6-astra` · `codex` | v1 runs |
| `zai-org/GLM-5.3` · `claude-code-glm`, `codex-glm`, `mini-swe-agent-glm` | v1 runs |
| VLA presets · `vla` | GPU runs on LIBERO, see the leaderboard; not run for these docs (needs a GPU policy server) |
| `allenai/MolmoAct2-LIBERO-LeRobot` · `molmoact2` | v1 runs on LIBERO; needs a GPU policy server |

Other models work wherever the harness accepts them through `--model`; they were not tested.

## Tasks

| Item | Status |
|---|---|
| Reference solutions and no-op controls of the tasks in the package | docs check: see the last two columns of [Suites](suites.md) |
| Real-robot tasks on the hardware-in-the-loop mock | docs check |
| Real-robot tasks on live hardware | not tested |

## Platforms

| Platform | Status |
|---|---|
| macOS on Apple silicon, Python 3.12, MuJoCo 3.3.0 | docs check |
| Python 3.11 and 3.13 | supported; docs check on 0.1.1 |
| Python 3.14 | not supported: MuJoCo 3.3.0 and Meta-World have no build for it |
| Linux | not tested for these docs; offscreen rendering needs `MUJOCO_GL=egl` or `osmesa` |

## Isolation

| Mode | Status |
|---|---|
| `robouse run`, macOS: model harnesses under `sandbox-exec` | docs check: the profile blocks a listed path and the package |
| `robouse run`, Linux | no sandbox |
| `bench eval run -d`: agent and simulator in separate Docker containers | docs check with `bench` 0.7.4 |

## Output formats

| Output | Status |
|---|---|
| Trial folder in BenchFlow's trial layout (`config.json`, `result.json`, `verifier/reward.txt`) | docs check |
| Agent trajectory in ATIF v1.7 (`agent/trajectory.json`) | docs check |
| Task folders in BenchFlow's task format (`task.md`, schema 1.3) | docs check |
