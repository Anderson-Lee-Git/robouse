# Changelog

Notable changes to the `robouse` package, newest first. Versions follow [semantic versioning](https://semver.org/); while the version is below 1.0, a minor version can change interfaces. Dates are PyPI release dates (UTC).

## 0.5.0 (2026-10-20)

Day-one support for Dream Labs' Dream-1 (the `dream` harness and the `yam` suite on Dream's bimanual YAM station), agent isolation fixes, and changes for the open-source release of the repository.

### Security

- `robo` and `robo mcp` print help for `-h` or `--help` anywhere in the arguments and send nothing; `robo give-up --help` and `robo done --help` used to end the episode.
- Claude Code is offered only the Bash, Read, Write, Edit, Glob and Grep tools, plus the `robo` MCP tools with `--interface mcp` or `both`, instead of every tool but WebFetch, WebSearch and Task. Codex runs with its web search turned off.
- Each trial's Claude Code and Codex get a config folder of their own, removed when the trial ends (a Codex account pool keeps one folder per account).
- The sandbox, on macOS and Linux, denies credential and task-copy locations in the home folder: other programs' logins (`~/.ssh`, `~/.aws`, `~/.config/gh`, `~/.netrc` and others), your own Claude Code, Codex and mini-swe-agent settings, BenchFlow's settings and task cache, the uv and pip caches, and Robo Use's cache apart from the agent's own harness folder. On Linux a denied file is hidden too, not only a folder.
- The sandbox denies a source checkout's `tasks/`, `runs/` and `adapters/` folders, makes the runner's Python read-only, and refuses connections to other trials' episode sockets, to the Docker, Podman and LXD sockets and to the SSH agent. On macOS it refuses `open`, `osascript`, `shortcuts`, `security` and Apple events.
- No variable whose name marks a credential (such as `GITHUB_TOKEN`, `HF_TOKEN`, `AWS_SECRET_ACCESS_KEY` or `SSH_AUTH_SOCK`) reaches an agent; each harness adds back what its own program needs. The episode server and the verifier get no model provider key.
- The sandbox denies Dream Labs' credentials file (`~/.dreamlabs`), and no `DREAM_*` variable reaches an agent, the episode server or the verifier; the `dream` harness gives its client the key.

### Added

- The `yam` suite: 9 tasks on Dream Labs' bimanual YAM station, in Dream's own MuJoCo scene from the `dreamlabs` wheel (in a virtualenv of its own, since it needs MuJoCo 3.3.5 or later): the apple or the orange into the bowl, the banana onto the plate, each on Dream's layout and two shuffled ones. Agents see the joints and the three cameras, not the objects, and have `reach`, `set_gripper` and `home` skills. Reference solution 9/9, no-op 0/9.
- The `dream` harness: Dream Labs' Dream-1 (`dreamlabs/dream-1-beta`, `dreamlabs/dream-1-beta-flash`) through DreamAPI, with Dream's own client library and simulation loop. It runs the `yam` suite and stops at 0 steps on any other robot.
- `observe` takes `inline` (cameras, format, size, quality) and returns the camera frames encoded in the reply instead of writing image files, for policy clients that read every frame.
- `robouse doctor` checks the `yam` suite's virtualenv and the `dream` harness's client and key.

### Changed

- Credential pools are opt-in: `ROBOUSE_CLAUDE_TOKEN_FILE` (a file of Claude Code OAuth tokens) and `ROBOUSE_CODEX_AUTH_DIR` (a folder of Codex logins). Nothing is read from fixed maintainer locations any more, and no model provider's key is read from a file.
- Remote worker endpoints are read only from `~/.config/robouse/remote/<name>.json` or the file `ROBOUSE_<NAME>_REMOTE` names, never from a checkout's `runs/` folder, which agents can read.
- The local sandbox no longer denies fixed maintainer folders. List private folders in `ROBOUSE_SANDBOX_DENY`.
- The license expression is `Apache-2.0 AND MIT AND CC-BY-4.0`. NOTICE lists every third-party source of code, data and assets, and `licenses/` holds their license texts.
- The RoboHarm suite is described as a suite after Robocurve's RoboHarm, written independently, rather than a reproduction.
- Fixture metadata and docstrings no longer name local paths of the recording machine.

### Removed

- `[tool.uv.sources]`, which pinned BenchFlow to a branch that is not public, so `uv sync` and `uv run` work from a fresh clone.

### Documentation

- A README for a public audience, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY (how to report, and the sandbox's limits), MAINTAINERS, CITATION.cff, and issue and pull request templates.
- The isolation sections of Run agents and Supported, and four suite pages, say what the sandbox does not hide. The suites page lists suites with non-commercial or NVIDIA-licensed requirements.
- The CI workflow runs on pull requests from forks with a read-only token and no secrets, on Python 3.11 to 3.13, and scans the history for secrets with gitleaks.

## 0.4.1 (2026-10-14)

### Changed

- The default model of `mini-swe-agent` and `dimcode` is `glm/glm-5.3`: GLM-5.3 on the Z.ai Coding Plan through BenchFlow's `glm` provider, set up with `GLM_API_KEY` and `GLM_BASE_URL`. No provider key is loaded unless you set it.
- `ROBOUSE_PRICING` replaces the packaged price table for the spend cap. A model with no price runs only with `ROBOUSE_SPEND_CAP_USD=0` or a price you give.
- The legacy `claude-code-glm`, `codex-glm` and `mini-swe-agent-glm` harness names still read old trial folders, but a new run refuses them, and so does an explicit `baseten/` model id.
- `show-harness` and `robouse grade` have no default model: give `--model`. `show-harness` through the gateway needs a model the registry lists as reading images. The VLM grader needs its own endpoint and key (`ROBOUSE_GRADER_URL`, `ROBOUSE_GRADER_API_KEY`).
- `--resume` refuses a run folder of another harness or model.

### Fixed

- A trial in which every model request failed is an infrastructure failure, not a scored failure, so `--retries` and `--resume` rerun it.
- `mini-swe-agent` is found where `pip install mini-swe-agent` puts it, and named in the error when it is not installed.
- Provider errors say how many of the agent's requests failed and how many calls went to the provider.

### Security

- `GLM_*` and `ZAI_*` variables and the VLM grader's key are kept out of agent environments, like other provider keys. No Baseten key is read, from a file or the environment.

## 0.4.0 (2026-10-04)

### Added

- The `show-harness` harness: NUS Show Lab's Show-Harness, in which a vision-language model picks one action unit at a time and an interpreter moves the hand. It runs zero-shot through the model gateway, or against a model you serve at `ROBOUSE_SHOW_HARNESS_URL`.
- Real-robot safety: a loop watchdog and stale telemetry stop the episode, a contact watch, nothing moves on its own after a stop, parking only with a calibrated park watch, soft limits inside the mechanical stops, and a physical e-stop confirmed before arming. Verified on mocks and replays of recorded sessions, not on live hardware; the real-robot suite is not in the package.

### Security

- The model gateway's per-trial master key is no longer written to the trial folder.

## 0.3.1 (2026-10-01)

### Fixed

- Offscreen rendering: on Linux without a display, the error names the fix (install OSMesa or EGL and run `robouse doctor`); `MUJOCO_GL` is only an override.
- The backend smoke test runs each backend's check in a child interpreter where MuJoCo cannot render offscreen, so backends that render another way still pass.
- `robouse tasks check` says when the installed BenchFlow cannot read robouse task folders.

## 0.3.0 (2026-10-01)

### Added

- Provider-prefixed models (`provider/model`, from BenchFlow's provider registry) for every LLM harness, through a per-trial LiteLLM model gateway with a spend cap. Needs Python 3.12 or newer and the `llm` extra.
- The `robo mcp` front end (the `robo` operations as MCP tools) and the `dimcode` harness.
- The rle-bench, capx and capx-libero suites from RLE-Bench and CaP-X, published as hub datasets rather than bundled tasks. Their code is vendored under the MIT License (NOTICE).

### Changed

- The task is the `task.md` body, given to the agent as its prompt. Only `task.md` folders are read; older layouts get a message that names `bench tasks migrate`.
- The `benchflow` and `llm` extras pin the BenchFlow and LiteLLM builds this release was tested with.

## 0.2.0 (2026-10-01)

### Added

- 692 tasks in 31 suites in the package, each checked by the release gate: reference solution 1 and no-op control 0.
- Compose tasks from components with `robouse tasks init` (embodiment, scene and task template, with modifiers), and `robouse components`.
- The `vla` harness: one client for policies served over the openpi, OpenVLA, GR00T, XPolicyLab and HTTP-JSON protocols, with presets.
- `robouse doctor` (rendering, simulators and harnesses on this machine) and `robouse report`.
- Linux support for model harnesses under bubblewrap.

### Changed

- One package layout (`core`, `cli`, `runner`, `analysis`, backends and simulator workers) and a settings layer that declares every `ROBOUSE_*` variable.
- `result.json` records a status (completed, error or cancelled); Ctrl-C during `run-many` records running trials as cancelled, and `--resume` reruns them.

### Security

- The episode server signs its verdict with a per-trial key, and gets that key and the reference solution's token on its standard input instead of the environment.
- The macOS sandbox blocks TCP connections to localhost (except a harness's own proxy), any robouse source or install, and other trials' workspaces.

## 0.1.1 (2026-09-27)

### Changed

- Agent harnesses use your own credentials: `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` for Claude Code (default model `claude-sonnet-5`), `OPENAI_API_KEY` or an existing Codex login for Codex.
- MuJoCo is pinned to 3.3.0. The DexJoCo tasks are in the package.
- `config.json` in each trial records whether the sandbox was on.

## 0.1.0 (2026-09-27)

First release of the current package: the episode server, the `robo` command, the runner and harness launchers, tasks bundled in the wheel (`robouse tasks`), simulators as extras, and `robouse fetch-assets` for the MuJoCo Menagerie meshes.

Versions 0.0.1 (2026-09-21) and 0.0.2 (2026-09-26) were published before this repository's history begins.
