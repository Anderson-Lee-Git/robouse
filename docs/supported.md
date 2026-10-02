# Supported

Robo Use 0.3.1.

## Models and harnesses

| Model · harness | Needs |
|---|---|
| `baseten/zai-org/GLM-5.3` · `claude-code`, `codex`, `mini-swe-agent`, `dimcode` | `BASETEN_API_KEY`; Python 3.12 or newer and `pip install 'robouse[llm]'` (the model gateway) |
| `baseten/moonshotai/Kimi-K3` · `claude-code` | `BASETEN_API_KEY`; Python 3.12 or newer and `pip install 'robouse[llm]'` |
| `claude-sonnet-5` · `claude-code` | `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` |
| `gpt-6-astra` · `codex` | `OPENAI_API_KEY` or a `codex login` |
| VLA presets · `vla` | a policy server, usually on a GPU |
| `allenai/MolmoAct2-LIBERO-LeRobot` · `molmoact2` | a policy server on a GPU |

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
