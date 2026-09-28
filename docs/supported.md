# Supported

What Robo Use 0.1.1 supports, and how each item was tested. "Docs check": run from the PyPI package for these docs. "v1 runs": used in the final v1 runs published under [Results](/runs/); trial counts are scored trials.

## Models

| Model | Harness | Status |
|---|---|---|
| `claude-sonnet-5` | `claude-code` | docs check: the [Quickstart](quickstart.md) trial |
| `gpt-6-astra` | `codex` | v1 runs: 222 trials |
| `zai-org/GLM-5.3` on Baseten | `claude-code-glm`, `codex-glm`, `mini-swe-agent-glm` | v1 runs: 221, 122 and 222 trials |
| `allenai/MolmoAct2-LIBERO-LeRobot` | `molmoact2` | v1 runs: 30 trials; needs a GPU policy server |

Other models work wherever the harness accepts them through `--model`; they were not tested.

## Harnesses

| Harness | Status |
|---|---|
| `oracle`, `noop` | docs check: 341 of 341 reference solutions score 1, 341 of 341 no-op runs score 0 |
| `claude-code` | docs check (Quickstart trial, with `CLAUDE_CODE_OAUTH_TOKEN`); v1 runs |
| `codex` | v1 runs; command line checked against Codex 0.155.1, not re-run for these docs |
| `claude-code-glm`, `codex-glm`, `mini-swe-agent-glm` | v1 runs |
| `molmoact2` | v1 runs on LIBERO; needs a GPU policy server |

What each needs: [Harnesses](harnesses.md).

## Simulators

| Backend | Suites | Tasks | Install | Status |
|---|---|---|---|---|
| tabletop (MuJoCo) | `libero-style`, `arc-style`, `robo-use-families`, `safety`, `hard`, part of `vision` | 95 | `[sim]` | docs check |
| Meta-World 3.1 | `metaworld`, part of `vision` | 74 | `[sim,metaworld]` | docs check |
| Gymnasium-Robotics | `gymrobotics` | 12 | `[gymrobotics]` | docs check |
| robosuite 1.5 | `robosuite` | 21 | `[robosuite]` | docs check |
| LIBERO | `libero` | 20 | [by hand](suites.md#libero) | docs check |
| MuJoCo Menagerie | `menagerie` | 15 | `[sim]` + `robouse fetch-assets` | docs check |
| RoboHarm scenes | `roboharm` | 80 | `[sim]` + `robouse fetch-assets` | docs check |
| Skydio X2 drone | `drone` | 10 | `[sim]` + `robouse fetch-assets` | docs check |
| DexJoCo | `dexjoco` | 14 | `[sim]` + DexJoCo, [see Suites](suites.md#dexjoco) | docs check |
| RoboCasa | `robocasa` | 7 | checkout | not in the package |

Per-suite results: [Suites](suites.md).

## Platforms

| Platform | Status |
|---|---|
| macOS on Apple silicon, Python 3.11, 3.12, 3.13, MuJoCo 3.3.0 | docs check |
| Python 3.14 | not supported: MuJoCo 3.3.0 and Meta-World have no build for it |
| Linux | not tested for these docs; offscreen rendering needs `MUJOCO_GL=egl` or `osmesa` |

## Isolation

| Mode | Status |
|---|---|
| Local runner, macOS: model harnesses under `sandbox-exec`, file access denied to `ROBOUSE_SANDBOX_DENY` paths | docs check: the profile blocks a listed path |
| Local runner, Linux | no sandbox |
| BenchFlow, Docker: agent and simulator in separate containers | needs a checkout; export and `bench tasks check` pass; `bench eval run` not re-run for these docs |

## Output formats

| Output | Status |
|---|---|
| Trial folder in BenchFlow's trial layout (`config.json`, `result.json`, `verifier/reward.txt`) | docs check |
| Agent trajectory in ATIF v1.7 (`agent/trajectory.json`) | docs check (oracle); v1 runs (model harnesses) |
| Episode trace (`episode/trace.jsonl`) and video (`artifacts/recording.mp4`) | docs check |
| Task folders in BenchFlow's native format (`task.md`, schema 1.3) | docs check |
