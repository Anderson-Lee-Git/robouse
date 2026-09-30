# Supported

What Robo Use 0.1.1 supports, and how each item was tested. "Docs check": run from the PyPI package for these docs. "v1 runs": used in the final v1 runs published under [Results](/runs/); trial counts are scored trials.

## Models

| Model | Harness | Status |
|---|---|---|
| `claude-sonnet-5` | `claude-code` | docs check: the [Quickstart](quickstart.md) trial |
| `gpt-6-astra` | `codex` | v1 runs: 222 trials |
| `zai-org/GLM-5.3` on Baseten | `claude-code-glm`, `codex-glm`, `mini-swe-agent-glm` | v1 runs: 221, 122 and 222 trials |
| `allenai/MolmoAct2-LIBERO-LeRobot` | `molmoact2` | v1 runs: 30 trials; needs a GPU policy server |
| VLA presets `openpi/pi05_libero`, `lerobot/groot_n1.7_libero`, `openpi/pi0_libero`, `lerobot/evo1_libero`, `lerobot/vla_jepa_libero`, `lerobot/smolvla_libero` | `vla` | GPU runs on the 40 LIBERO tasks: 38, 38, 36, 40, 38 and 26 of 40 ([VLA policies](vla.md)); need a GPU policy server |

Other models work wherever the harness accepts them through `--model`; they were not tested.

## Harnesses

| Harness | Status |
|---|---|
| `oracle`, `noop` | docs check: 392 of 392 reference solutions score 1, 392 of 392 no-op runs score 0 |
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

BenchFlow is the environment framework whose task and trial formats Robo Use uses ([Robo Use and BenchFlow](index.md#robo-use-and-benchflow)). The released runner does not start BenchFlow; exported tasks run under `bench eval run`.

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

## Parity update (2026-09-29)

Added on the `parity` branch and tested as stated. Compared with inspect-robots (robocurve's evaluation framework for physical AI) where a comparison is useful.

### Real robots

| Capability | Status |
|---|---|
| Real-arm backend behind the same episode server and `robo` interface ([Real robots](real-robots.md)): MakerMods Metal, SO-100/SO-101 and bimanual SO-101 (LeRobot followers), AgileX Piper (`piper_sdk`), any ROS arm through rosbridge | tested on the hardware-in-the-loop mock; live hardware untested (no robot connected) |
| Safety layer on every command: e-stop latch (`robouse estop`), joint-limit clamp, forward-kinematics workspace veto before motion, per-step speed limit with a slow zone, wind-up guard, thermal stop, loop watchdog, one-controller hardware lock | `tests/test_real.py` (12 tests); `robouse hil-check` replays 842 recorded Metal commands with 0 vetoes |
| Human-attended mode: arm / reset / release gates, operator verdicts (yes / no / partial / skip or a rubric stage) over the terminal, a file channel or a mock-only script; typed feedback to the policy (`robouse operator say`) | tests (gates, file channel, feedback) and mock runs; the terminal channel on a real rig untested |
| Hardware-in-the-loop mock: recorded sessions replayed behind the LeRobot / piper_sdk seam (tracking model fitted to the recording: 0.16 deg RMS) | tested |
| Sim / real / hil-mock recorded in every episode and trial and grouped by `robouse report --by mode` and BenchFlow's seed report | tested |
| `tasks/real` (6 tasks) | reference 6/6 and no-op 0/6 on the mocks (the ROS task on a mock rosbridge server); Kimi K3 (`claude-code-glm`) 2/2 on the probe list |
| StationeryBench (5 bimanual tasks, operator rubric) on two SO-101 arms | pipeline tested on the mock (stages 0, 2 and 4 via the scripted operator); the tasks themselves need a rig |

### VLA policies

| Capability | Status |
|---|---|
| `vla` harness with the openpi, XPolicyLab, OpenVLA, GR00T and HTTP-JSON wires; presets for pi0 / pi0.5 (LIBERO), OpenVLA (LIBERO), MolmoAct2, SmolVLA and pi0.5 via LeRobot, GR00T N1.6/N1.7 (SO-101), XPolicyLab joint policies ([VLA policies](vla.md)) | every wire end to end against mock servers built on the upstream libraries: 5/5 tasks solved (`scripts/vla_dogfood.sh`); openpi and HTTP-JSON wires also with real GPU-served checkpoints (next row) |
| Real checkpoints on a GPU (openpi server; `lerobot_server.py` in LeRobot e0d50211) | LIBERO, 40 tasks, 1 episode each: pi0.5 38, GR00T N1.7 38, pi0 36, EVO1 40, VLA-JEPA 38, SmolVLA 26; upstream cross-checks: GR00T `lerobot-eval` 37/40, pi0.5 openpi evaluator libero_spatial 10/10; zero-shot probe on LIBERO-90, robosuite and Meta-World: pi0.5 1/12, GR00T 0/12 |
| Real model on CPU: SmolVLA-LIBERO (HuggingFaceVLA/smolvla_libero, Apache-2.0) behind `src/robouse/vla/lerobot_server.py` | tested end to end on an Apple-silicon CPU through the sandboxed harness: 2 of 5 LIBERO tasks solved (libero-spatial-0 in 89 steps, libero-object-0 in 136; failed libero-spatial-1, libero-goal-0, libero-10-0); about 1 s per 10-action chunk (`runs/smolvla-cpu`) |
| Chunk controllers (open loop with replanning, ACT temporal ensembling, smoothing) and a compatibility check before the first action | unit tests; the check rejected an incompatible pairing at 0 steps |

### Suites

| Suite | Tasks | Status |
|---|---|---|
| `nav`: object-goal navigation in generated homes, in the protocol of Dimensional's Can Jev Nav? ([suite](suites/nav.md)) | 40 | reference 40/40 (SPL 0.99), no-op 0/40; Kimi K3 3/3 (SPL 0.53, about 2.3 M prompt tokens and USD 7.2 per run at list price); hub export on BenchFlow 0.7.4: 40/40 |
| `cubepick`: inspect-robots' `cubepick-reach` ([suite](suites/cubepick.md)) | 5 | reference 5/5, no-op 0/5; hub export 5/5 |
| `stationerybench` ([suite](suites/stationerybench.md)) | 5 | see above |
| `real` ([suite](suites/real.md)) | 5 | see above |

### Evaluation

| Capability | Status |
|---|---|
| Episode metrics from the physical trace: success, progress, execution quality, time, speed, SPARC smoothness, jerk, path length, max contact force, safe failure; navigation SPL, SoftSPL, collisions, time to target, path ratio, excess turning ([Metrics](metrics.md)) | tested on tabletop, LIBERO, Meta-World, real-arm mock and nav trials |
| `robouse report`: any grouping, Wilson and bootstrap 95% intervals, pass@k, cost-vs-success JSON and SVG | tested |
| Cost per trial (tokens; USD from the harness or published prices) | tested on Kimi K3 probes |
| `run-many`: `--seeds`, `--epochs`, `--retries`, `--include/--exclude` globs, `--sample`, `--split`, `--mode`, `--extra-instruction`, `--prior-learnings`, `--dry-run`; provenance in `config.json` | tested (`--dry-run`, seeds, splits; placement splits: reference 8/8 on each split) |
| `robouse summarize`, `robouse grade` (VLM second opinion from video frames; `real.verdict: vlm`), `robouse doctor`, `robouse.backends` / `robouse.harnesses` / `robouse.drivers` entry points | `robouse grade` with Kimi K3 on 16 trials (cubepick and nav, reference and no-op): 16/16 agree with the trusted verdict after raising the answer budget (3 of the first 16 answers were empty at 2000 tokens); `doctor` and the entry points checked by hand; `real.verdict: vlm` untested |
