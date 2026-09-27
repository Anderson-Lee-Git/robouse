# Running robouse through BenchFlow

robouse tasks can be exported as BenchFlow-native task packages (`task.md`, schema_version 1.3) and run with `bench eval run` on the Docker sandbox. The agent harness (Claude Code, Codex, any BenchFlow agent, or the `oracle`) runs in BenchFlow's agent container; the MuJoCo simulator and the robouse episode server run in a second, trusted container. The two share only a Unix socket.

Code: [`benchflow/`](../benchflow/) (exporter, simulator image, templates). Nothing in `src/robouse` was changed for this.

## Trust model

```
 main (agent container)                         simulator (trusted container)
 ┌────────────────────────────────┐             ┌──────────────────────────────────────────┐
 │ BenchFlow agent / oracle        │  JSON over  │ robouse serve --task … --socket …          │
 │ /usr/local/bin/robo  (stdlib)   │ Unix socket │ MuJoCo + Meta-World / Gymnasium-Robotics   │
 │ ROBOUSE_SOCKET=/rpc/episode.sock│────────────►│ step + wall budgets, video, success judge │
 │ /rpc  (read-only volume)        │             │ /episode (record; not mounted in main)     │
 │ network: yes (model API)        │             │ network: none                              │
 └────────────────────────────────┘             │ verifier: test.sh → /logs/verifier/reward  │
                                                └──────────────────────────────────────────┘
```

- **Agent container (`main`).** Built from `environment/Dockerfile`: `python:3.12-slim-bookworm` plus numpy, curl/xz (so BenchFlow can install JS harnesses) and the `robo` client, a copy of `src/robouse/agent_cli.py` (standard library only). There is no simulator, no MuJoCo, no robouse source, no task definition and no episode record in this container. The shared `rpc` volume is mounted read-only: it holds the socket and the camera images that `robo observe --image` saves (`/rpc/ws/observations/obs_NNN.png`), which the agent can open.
- **Simulator container (`simulator`).** Built from `runtime/Dockerfile.sim` (image `robouse-sim:0.1.0`). It runs `robouse serve` for the task, with `network_mode: none`. The task definition (the robouse `task.toml`) is embedded in the compose file and passed as `ROBOUSE_TASK_TOML`, so no host path is mounted. The episode record (`result.json`, `trace.jsonl`, `frames.jsonl`, `recording.mp4`) is written to the `episode` volume, which only this container mounts.
- **Verifier.** `task.md` sets `verifier.service: simulator`, so BenchFlow runs `verifier/test.sh` inside the simulator container and downloads `/logs/verifier` from there. The compose file uses `volumes: !override` on `main` to drop BenchFlow's default host mount of `/logs/verifier` into the agent container, so reward files written by the agent never reach the host.
- **Closing the episode.** If the agent ended with `robo done` / `robo give-up`, or a budget ran out, the episode server has already judged the episode and exits on its own. If the agent (or the harness) just stopped, the verifier sends `shutdown` over the socket; the server then closes the episode as `agent_exited` and judges the physical state after the usual settle period, which is exactly what a local `robouse run` does when the harness exits. The verifier waits for the server to finish writing its record (`/episode/serve.exit`), copies the record to `/logs/verifier/episode/`, and writes `reward.txt` = 1 if the server judged success, else 0. `reward-details.json` keeps the outcome, steps used, `closed_by` and the agent's final message. A missing result is an infrastructure error (exit 1, no reward), not a zero.
- **Oracle.** `oracle/solve.sh` runs in the agent container like any agent and drives the robot only through the socket. It ships its own code in `oracle/vendor/` (a copy of robouse's oracle module and, for Meta-World, the one scripted expert policy it needs, which is pure numpy). BenchFlow uploads `oracle/` only in oracle mode, so agents never see it.
- **Wall clock.** The episode clock starts when the simulator container is up, which is before BenchFlow installs the harness, so the episode's wall budget is the task's agent timeout plus 900 s. The step budget (`max_steps`) is the real limit.

Probed boundaries (see the adversarial control below): the agent cannot read `/episode`, `/opt/robouse` or `/task` (they do not exist in its container), cannot write `/rpc`, has no `mujoco` module, and reward files it writes locally do not affect the score. This is a set of specific probes, not a full isolation audit: the agent container has network access (needed for the model API), and any process that can reach the socket can send the same JSON requests `robo` sends (which only gives it the same public interface).

## Build, export, check

Requirements: Docker with Compose v2.24.4 or newer (for `!override`) and the `bench` CLI. On this Mac, Docker is Colima's `default` profile; the Compose plugin was not installed, so it was added as `~/.docker/cli-plugins/docker-compose` (v5.5.1).

```sh
cd ~/benchflow/robouse

# 1. export tasks (any mix of task folders, suite folders, or all of tasks/)
.venv/bin/python benchflow/export.py --tasks tasks/metaworld/metaworld-reach tasks/metaworld/metaworld-push \
    --out benchflow/dist/robouse
#   whole suites:  --tasks tasks/metaworld tasks/gymrobotics     substring filter:  --filter push,reach
#   negative control (oracle that only looks and never calls `robo done`):  --noop-oracle

# 2. (optional) pre-build the simulator image; BenchFlow also builds it from the bundle's runtime/ on first use
docker build -f benchflow/dist/robouse/runtime/Dockerfile.sim -t robouse-sim:0.1.0 benchflow/dist/robouse/runtime

# 3. validate each package
cd benchflow/dist/robouse
bench tasks check tasks/metaworld-reach --level runtime-capability --sandbox docker
```

The export needs the dev venv only for Meta-World tasks (it copies the scripted expert policy out of the installed `metaworld` package). The bundle is self-contained; keep `runtime/` next to `tasks/` when moving it, because each task's compose file builds the simulator from `../../../runtime`. BenchFlow deletes service images at the end of every trial (`compose down --rmi all`), so the simulator image is rebuilt from the Docker build cache each time (seconds, not minutes).

Bundle layout:

```
<out>/benchmark.yaml  robouse-oracle.yaml  robouse-claude.yaml  robouse-codex.yaml
<out>/runtime/        Dockerfile.sim  requirements-sim.txt  sim-entry.sh  robouse/ (package source)
<out>/tasks/<id>/     task.md
                      environment/{Dockerfile, robo, docker-compose.yaml}
                      verifier/{verifier.md, test.sh, verify.py}
                      oracle/{solve.sh, vendor/}
```

## Run

From the bundle directory:

```sh
bench eval run --config robouse-oracle.yaml                 # reference solutions: expect 1.0 everywhere
bench eval run --tasks-dir tasks --agent oracle --sandbox docker     # same, with flags

# Claude Code as the robot policy (auth: ANTHROPIC_API_KEY, or CLAUDE_CODE_OAUTH_TOKEN)
bench eval run --config robouse-claude.yaml                 # agent: claude, model: claude-opus-5-5
bench eval run --config robouse-codex.yaml                  # agent: codex, model: gpt-6-astra
```

The configs use `concurrency: 1` because all tasks share the `robouse-sim:0.1.0` tag, which each trial's cleanup removes; higher concurrency worked for the 2-task no-op control but is not guaranteed. Results land in `jobs/<config>/<timestamp>/<task>__<id>/`: `result.json` (`rewards.reward`), `agent/` (harness trajectory, or `oracle.txt`), and `verifier/` with `reward.txt`, `reward-details.json` and `episode/` (video, trace, frames, observation images).

**Claude models newer than the pinned harness.** BenchFlow 0.7.4 (the PyPI build installed as `~/.local/bin/bench`) pins `@agentclientprotocol/claude-agent-acp@0.40.0`, which bundles Claude Code 2.1.160; the API rejects `claude-opus-5-5` from it ("version 2.1.280 or newer is required"). The BenchFlow checkout (`~/benchflow/internal-lab/benchflow/benchflow`, 0.7.6.dev0) pins 0.73.0, which bundles Claude Code 2.1.257 and is still too old. `claude-agent-acp@0.81.2` (Claude Agent SDK 0.3.280, i.e. Claude Code 2.1.280) works. For the Claude run, the checkout was installed into a separate venv and the pin was changed in that venv's installed copy only (`benchflow/agents/registry.py`, `_CLAUDE_AGENT_ACP_PACKAGE`); the BenchFlow repo itself is unchanged. BenchFlow needs that pin bump upstream:

```sh
uv venv --python 3.12 ~/.cache/robouse/bfdev-venv
uv pip install --python ~/.cache/robouse/bfdev-venv/bin/python ~/benchflow/internal-lab/benchflow/benchflow
sed -i '' 's#claude-agent-acp@0.73.0#claude-agent-acp@0.81.2#' \
    ~/.cache/robouse/bfdev-venv/lib/python3.12/site-packages/benchflow/agents/registry.py
CLAUDE_CODE_OAUTH_TOKEN=… ~/.cache/robouse/bfdev-venv/bin/bench eval run --config robouse-claude.yaml
```

## Validation (2026-09-27)

Bundle: `benchflow/dist/robouse` (metaworld-reach, metaworld-push) and `benchflow/dist/robouse-noop` (same tasks, `--noop-oracle`). Docker: Colima default profile (aarch64, 6 CPUs, 10 GiB). Simulator image `robouse-sim:0.1.0`: 1.12 GB.

| Check | Command | Result |
|---|---|---|
| Structure | `bench tasks check tasks/metaworld-{reach,push}` | valid (structural) |
| Runtime capability | `bench tasks check tasks/metaworld-{reach,push} --level runtime-capability --sandbox docker` (0.7.4 and 0.7.6.dev0) | valid |
| Oracle | `bench eval run --config robouse-oracle.yaml` | **2/2, mean reward 1.00**, errors 0, 1.7 min. reach: `success_reached` at step 51; push: `success_reached` at step 63 |
| No-op control | `bench eval run --tasks-dir tasks --agent oracle --sandbox docker --jobs-dir jobs/robouse-noop` (in `robouse-noop/`) | **0/2, mean reward 0.00**, errors 0. Both closed by the verifier (`closed_by: verifier_shutdown`, outcome `agent_exited`, 0 steps) |
| Adversarial control | a solve.sh that writes `/logs/verifier/reward.txt` = 1 and `reward.json` in the agent container, then probes `/episode`, `/rpc`, `/opt/robouse`, `/task`, `import mujoco` (metaworld-reach) | **reward 0.00**. The forged files stayed in the container; `/episode`, `/opt/robouse`, `/task` absent; `/rpc` read-only; no `mujoco`; `robo observe --image` returned `/rpc/ws/observations/obs_001.png` |
| Claude Code + claude-opus-5-5 | `bench eval run --config robouse-claude.yaml` (0.7.6.dev0, `CLAUDE_CODE_OAUTH_TOKEN`) | **2/2, mean reward 1.00**, errors 0, 2.3 min (install included). push: 4 shell calls (`robo info`, `observe`, `move-to` above the puck, `move-to` down, `grip 1`, `move-to` to the goal), `success_reached` at step 155, 83.6k tokens; reach: 2 shell calls, `success_reached` at step 36, 48.1k tokens. Each trace in `verifier/episode/trace.jsonl` shows only public `robo` requests |

The first adversarial attempt, run from a bundle copied to `/tmp`, failed at startup because the task definition was then a bind mount and Colima only shares the home directory; the task definition has been embedded in the compose file since, and the rerun from `/tmp` passed. Two earlier Claude attempts (BenchFlow 0.7.4 with Claude Code 2.1.160, then 0.7.6.dev0 with 2.1.257) were rejected by the API on the harness version before any robot request and were stopped; they are not counted.
