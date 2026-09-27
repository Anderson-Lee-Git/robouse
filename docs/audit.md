# Automatic audit

```
.venv/bin/python scripts/audit.py                       # every trial under runs/
.venv/bin/python scripts/audit.py runs/mw-codex-astra   # some jobs or trials
.venv/bin/python scripts/audit.py --out /tmp/audit
```

The audit writes `runs/_audit/audit.json` (one record per trial and a summary per harness and model) and `runs/_audit/AUDIT.md` (the summary table, flag counts, the trials flagged for review and low-severity notes). It uses the standard library only, plus `ffprobe` for video durations when it is installed. It reads the trial folders and never changes them. When a trial has no `agent/trajectory.json`, the audit builds one in memory with `robouse.atif`. `scripts/build_gallery.py` shows the audit flags when `audit.json` exists.

A flag is a lead for a human or AI reviewer, not a verdict. The heuristics are regular expressions and simple consistency checks. They over-report on purpose.

## Checks per trial

**Files.** `config.json`, `result.json`, `episode/result.json`, `episode/trace.jsonl`, `episode/frames.jsonl`, `artifacts/recording.mp4`, `verifier/reward.txt` and `agent/stdout.jsonl` must exist (high if missing). `agent/trajectory.json` and `artifacts/recording_index.json` are listed but not flagged. A trial with no `result.json` whose files changed in the last 20 minutes counts as **running**: it gets a low note and stays out of the summary counts. Without recent changes, the same trial is flagged `no_result` (the runner crashed or was killed).

**Reward and outcome.**

- `reward.txt` must equal the episode's `success` (`reward_mismatch`), and `result.json`'s reward must equal `reward.txt` (`result_reward_mismatch`).
- A reward with no episode result is flagged (`reward_without_episode`).
- The outcome must be a known value (`done`, `gave_up`, `budget_exhausted`, `success_reached`, `wall_time_exhausted`, `agent_exited`, `agent_timeout`), and `success_reached` must come with `success = true`.
- `steps_used` must not exceed `max_steps`.
- A reward after `gave_up` or a timeout is a medium flag: the final state met the goal anyway.
- A scoring **noop** trial means the task is solved at reset (high). A failing **oracle** means the reference solution does not solve the task (medium).

**Video.** The recording must not be empty. Its duration (ffprobe) must match `frames.jsonl` (frames / 30 fps, tolerance 2 frames + 0.05 s). An episode that finished with no frames is flagged.

**The agent used robo** (LLM harnesses). The trace must contain at least one motion request (`act`, `move_to` or `grip`) unless the agent gave up or refused (refusal is detected by phrases like "I can't help" or "I won't" in its last messages).

- `no_motion` is medium, or high if the trial scored.
- `success_without_motion` (high): reward 1 with no motion at all.
- `no_done` (low): the runner had to close the episode because the agent exited without `robo done` or `robo give-up`.

**Cheating heuristics.** These are scanned only over what the agent wrote: tool-call arguments (shell commands, file paths, file contents, patches). They are never scanned over tool outputs or the prompt, because outputs such as `robo info` would trigger them. The workspace path is masked first.

| id | severity | matches |
|---|---|---|
| sim_import | high | `import`/`from` mujoco, metaworld, gymnasium_robotics, dm_control, robosuite, robouse |
| robouse_module | high | `python -m robouse`, `robouse.oracle/session/backends/runner` |
| oracle | high | `solution/solve.sh`, `robouse/oracle.py`, `metaworld.policies` (the scripted experts) |
| robouse_source | high | paths under `benchflow/robouse/{src,tasks,.venv,runs,scripts}`, `site-packages/{metaworld,mujoco,...}` |
| reward_write | high | `reward.txt`, `reward.json`, `verifier/`, `ROBOUSE_EPISODE_DIR`, `ROBOUSE_VERIFIER_DIR` |
| episode_files | high | `episode/result.json`, `trace.jsonl`, `frames.jsonl`, `recording.mp4` |
| kill_server | high | `pkill`, `killall`, `kill <pid>`, `robouse.cli serve`, `lsof -U` |
| socket_direct | medium | `nc -U`, `socat`, `AF_UNIX`, `socket.socket`, `/tmp/robouse-*.sock`, `.robouse/socket` |
| network | medium | `curl`/`wget` to URLs, `pip install`, `uv pip/add`, `brew install`, `npm install` |
| home_paths | medium | `/Users/<name>/{benchflow,.claude,.codex,.config,.ssh,Library}` |
| robo_shim_read | low | reading `.robouse/bin/robo`, `which robo` |
| process_env | low | `ps aux`, `printenv`, `env`, `/proc/` |

A trial is **suspicious** if it has a high or medium cheating flag. It is also suspicious if its reward is not supported by the evidence: `success_without_motion`, a reward mismatch, a scoring noop, or a reward without an episode.

**Infrastructure.**

- **Runner:** `exception_info` in `result.json`, the agent timeout, a non-zero agent return code (LLM harnesses), and an empty `agent/stdout.jsonl`.
- **Errors in the output:** error patterns in `stderr.txt` and in structured error events of the raw output: Claude `result` events with `is_error` or an `error_*` subtype, `api_retry`, assistant `error`, blocking `rate_limit_event`; Codex `turn.failed`, `error`, and error items. The patterns are rate limits (429, "rate limit", quota), overload (overloaded, 529, 503), proxy and connection errors (502, ECONNREFUSED, "proxy error", "upstream error"), auth errors (401, invalid key) and API errors ("API Error", "stream disconnected", context length). Known stderr noise is ignored: the owner's Codex MCP servers, stdin notices and Python warnings.
- **Episode server:** errors the agent saw from the episode server (`bad request: ...` in tool results), `upstream_errors` in the GLM proxy stats, and an episode that never finished (`result.json` present but no `episode/result.json`).

An **infra failure** is a trial that did not measure the agent. That means one of these: a runner exception, empty output, an episode that never finished, or an episode-server error. It also covers any other infrastructure signal combined with an agent that never moved the robot. The summary reports the solve rate both over all finished trials and with infra failures excluded.

## Summary and review list

`AUDIT.md` starts with one row per harness and model: finished trials, running, solved, infra failures, solve rate without infra failures, suspicious, needs review, median wall time and median env steps. Next come the flag counts. Then comes the list of **trials flagged for review**: every suspicious trial, every infra failure and every trial with a high-severity flag, ordered by severity, each with its high and medium flags and their evidence. The review list is the input for a human or AI reviewer, who should open the trial in the viewer (`scripts/view.sh`) and read the trajectory around the flagged commands.

## What the first audits found (2026-09-27, 229 to 288 trials while jobs were running)

- **Episode-server bug.** Meta-World raises "You must reset the env manually once truncate==True" when an episode reaches the env's `max_path_length` (500). The server answers `bad request` and never finishes the episode, so the trial has no episode result, no video and no reward. This happened in 9 trials across Opus, Astra and GLM, all near the 500-step budget, and it is the cause of every Codex/Astra failure so far. The fix belongs in `session.py`/the Meta-World backend: finish the episode when the env truncates, or keep `max_steps` below `max_path_length`.
- **Oracle.** `solve.sh` exits 1 on Meta-World after success, because it keeps sending requests to a finished episode. The reward is unaffected.
- One codex-glm smoke trial produced no output (return code 1); it is an infra failure.
