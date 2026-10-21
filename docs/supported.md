# Supported

Robo Use 0.5.0.

## Models and harnesses

| Model · harness | Needs |
|---|---|
| `glm/glm-5.3` (GLM-5.3 on the Z.ai Coding Plan) · `mini-swe-agent`, `dimcode`, `claude-code` | `GLM_API_KEY`, `GLM_BASE_URL` and `ROBOUSE_SPEND_CAP_USD=0` (or a price in `ROBOUSE_PRICING`); Python 3.12 or newer and `pip install 'robouse[llm]'` (the model gateway) |
| `gemini-4-argon` (Gemini 4 Argon on the Gemini API) · `gemini-cli` | `GEMINI_API_KEY` (a Gemini API key from Google AI Studio); Gemini CLI on `PATH` (`npm install -g @google/gemini-cli`) |
| `gemini/gemini-4-argon` · `claude-code`, `mini-swe-agent`, `dimcode` | `GEMINI_API_KEY`; Python 3.12 or newer and `pip install 'robouse[llm]'` (the model gateway) |
| `openrouter/elorian/glimpse` (Elorian's Glimpse), `openrouter/google/gemini-4-argon` · `claude-code`, `mini-swe-agent`, `dimcode` | `OPENROUTER_API_KEY`; Python 3.12 or newer and `pip install 'robouse[llm]'` |
| `claude-sonnet-5` · `claude-code` | `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` |
| `gpt-6-astra` · `codex` | `OPENAI_API_KEY` or a `codex login` |
| VLA presets · `vla` | a policy server, usually on a GPU |
| `allenai/MolmoAct2-LIBERO-LeRobot` · `molmoact2` | a policy server on a GPU |
| `dreamlabs/dream-1-beta`, `dreamlabs/dream-1-beta-flash` · `dream` | a Dream Labs API key and Dream's client library; runs the `yam` suite, which needs its own virtualenv ([Suites](suites.md)) |
| `typesafe/jev-latest`, `typesafe/jev-preview` · `jev` | a TypeSafe API key in `TYPESAFE_API_KEY`; runs the `nav` suite |

How the `glm/glm-5.3` row was checked (2026-10-14): each of its three harnesses (mini-swe-agent 2.4.6, Claude Code 2.1.285, dimcode 0.1.0-next.7) ran whole trials through the model gateway, on Linux arm64 under bubblewrap, against a scripted local stand-in for the plan's endpoint. With GLM-5.3 itself they were checked only up to the plan's usage-limit error (HTTP 429), so no trial on the plan has reached a result yet, and how these pairs do on a task is untested.

How the `jev` row was checked (2026-10-20): whole trials on nav tasks, on macOS (Apple silicon) under Seatbelt and on Linux x86_64 without a sandbox, against a scripted local stand-in for TypeSafe's System One endpoint that answers by applying the questions' criteria literally. No trial has run on Jev itself yet, so how Jev does on the nav suite is untested.

How the Gemini 4 Argon and Glimpse rows were checked (2026-10-20): each pair ran a whole trial (`arc-gravity-vision`) on Linux x86_64 without the sandbox (`ROBOUSE_SANDBOX=0`), against scripted local stand-ins for the Gemini API and for OpenRouter's chat completions endpoint (`tests/model_standin.py`), with Gemini CLI 0.64.0, Claude Code 2.1.304, mini-swe-agent 2.4.6 and dimcode 0.1.0-next.7; Claude Code on `gemini/gemini-4-argon` also ran under Seatbelt on macOS. The stand-ins check the plumbing: the routes, the signatures Gemini puts on tool calls, images in tool results, token counts and costs. No request has reached Google or OpenRouter, so how these pairs do on a task is untested, and Gemini CLI has not run under the sandbox.

## Platforms

| Platform | Notes |
|---|---|
| macOS on Apple silicon | Python 3.11 to 3.13; provider-prefixed models need 3.12 or newer |
| Linux arm64 | without a display, OSMesa (`libosmesa6`) or EGL (`libegl1 libgl1`): Robo Use picks whichever renders, and `MUJOCO_GL`, if set, overrides the choice ([Quickstart](quickstart.md#install)); bubblewrap for model harnesses; the `robosuite` extra needs a C compiler |
| Python 3.14 | not supported: MuJoCo 3.3.0 and Meta-World have no build for it |

## Isolation

| Mode | Isolation |
|---|---|
| `robouse run` on macOS | model harnesses run under Seatbelt, which hides the trial's files and the credential and task-copy locations in your home folder from the agent, but not the rest of the machine or the network ([Run agents and VLAs](run-agents.md#isolation)) |
| `robouse run` on Linux | model harnesses run under bubblewrap, with the same limits |
| `bench eval run -d` | agent and simulator in separate Docker containers; the simulator container has no network |

## Formats

- Tasks: BenchFlow task folders (`task.md`, schema 1.3).
- Trials: BenchFlow's trial layout (`config.json`, `result.json`, `verifier/reward.txt`), with the agent's steps in ATIF v1.7 (`agent/trajectory.json`).
