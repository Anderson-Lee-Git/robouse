# Supported

Robo Use 0.4.1.

## Models and harnesses

| Model · harness | Needs |
|---|---|
| `glm/glm-5.3` (GLM-5.3 on the Z.ai Coding Plan) · `mini-swe-agent`, `dimcode`, `claude-code` | `GLM_API_KEY`, `GLM_BASE_URL` and `ROBOUSE_SPEND_CAP_USD=0`; Python 3.12 or newer and `pip install 'robouse[llm]'` (the model gateway) |
| `claude-sonnet-5` · `claude-code` | `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` |
| `gpt-6-astra` · `codex` | `OPENAI_API_KEY` or a `codex login` |
| VLA presets · `vla` | a policy server, usually on a GPU |
| `allenai/MolmoAct2-LIBERO-LeRobot` · `molmoact2` | a policy server on a GPU |

How `glm/glm-5.3` was checked (2026-10-14): with each of its three harnesses, whole trials through the model gateway against a scripted stand-in for the plan's endpoint, and requests to the plan itself, which answered with its usage-limit error. No scored GLM-5.3 trial on the plan is published yet.

## Platforms

| Platform | Notes |
|---|---|
| macOS on Apple silicon | Python 3.11 to 3.13; provider-prefixed models need 3.12 or newer |
| Linux arm64 | without a display, OSMesa (`libosmesa6`) or EGL (`libegl1 libgl1`): Robo Use picks whichever renders, and `MUJOCO_GL`, if set, overrides the choice ([Quickstart](quickstart.md#install)); bubblewrap for model harnesses; the `robosuite` extra needs a C compiler |
| Python 3.14 | not supported: MuJoCo 3.3.0 and Meta-World have no build for it |

## Isolation

| Mode | Isolation |
|---|---|
| `robouse run` on macOS | model harnesses run under Seatbelt ([Run agents and VLAs](run-agents.md#isolation)) |
| `robouse run` on Linux | model harnesses run under bubblewrap |
| `bench eval run -d` | agent and simulator in separate Docker containers |

## Formats

- Tasks: BenchFlow task folders (`task.md`, schema 1.3).
- Trials: BenchFlow's trial layout (`config.json`, `result.json`, `verifier/reward.txt`), with the agent's steps in ATIF v1.7 (`agent/trajectory.json`).
