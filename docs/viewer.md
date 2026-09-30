# Viewing trials

There are two ways to look at trials: the full BenchFlow viewer (one trial at a time, video synced to the agent's steps) and a static overview page (every trial on one page).

## Full viewer: `tools/ops/view.sh`

```
tools/ops/view.sh               # http://127.0.0.1:8768
tools/ops/view.sh --port 8770
```

It runs the BenchFlow viewer from the `robouse` branch of the private repo `benchflow-ai/trial-viewer` (https://github.com/benchflow-ai/trial-viewer/tree/robouse), checked out at `~/benchflow/trial-viewer`, with `--root robouse=<repo>/runs --tasks robotics=<repo>/tasks/*`. One-time setup: `gh repo clone benchflow-ai/trial-viewer ~/benchflow/trial-viewer && git -C ~/benchflow/trial-viewer checkout robouse`; the first start installs the Python environment and builds the frontend (about a minute; needs `uv` and Node.js 20+). That branch adds what Robo Use needs on top of the viewer at `~/benchflow/data/viewer`: robot trials, `task.md` task folders and a column per harness and model. The default port is 8768 because 8765 and 8766 usually serve the 3D/CUA runs on this Mac; set `VIEWER=/path/to/viewer` to use another checkout. The viewer is read-only and binds to 127.0.0.1.

What you get:

- **Jobs**: one job per folder under `runs/` (for example `mw-claude-opus`), with reward, cost and tokens per task. Folders starting with `_` (`_gallery`, `_audit`) are skipped.
- **Trial page** (`/jobs/<job>/tasks/_/<harness>/<provider>/<model>/<task>/trials/<trial>`). A trial counts as a robot trial when it has `episode/result.json` (or an `episode` object in `result.json`) or its `config.json` `task_path` names a task with a `robouse:` block. It opens on Recording; the header adds the outcome and steps used against the budget.
  - **Trajectory**: the ATIF trajectory: the prompt, then every agent step with its message, reasoning (Codex reasoning summaries and Claude thinking when recorded), tool calls and their results. When the agent looked at a camera image (`robo observe --image`, then Claude's Read tool), the image is shown from `artifacts/observations/`.
  - **Recording**: the episode video with the step list beside it. Clicking a step seeks the video to the moment its robo requests ran; the playing video highlights the current step. The caption reads "Simulation recording of the episode (MuJoCo), synced to the agent's steps" (the simulator is taken from `recording_index.json`'s `source`, the benchmark or the backend; the index's `time_axis` is shown on hover), with no click markers. Below the video is a strip of the camera images the agent looked at (`artifacts/observations/*.png`), each labelled with the step that took it.
  - **Verdict**: the episode's outcome (reward, outcome, steps used / budget, success mode, observation mode), the episode facts (robot requests, episode wall time, backend and env, simulator, camera, skills, seed, source), `verifier/test-stdout.txt`, the agent's `robo done` message (or its last message), the camera images and the task prompt.
  - **Files**: the trial folder. Under **More**: **Run details** (Outcome, Tokens, and Timing, which shows the whole run from `wall_time_s` when there is no per-phase timing), **Config** (`config.json`), **Agent** and **Log** (raw `agent/stdout.jsonl` and `stderr.txt`).
- **Tasks** (home page): every task under `tasks/<suite>/`, in either layout (`task.md` + `oracle/` + `verifier/`, or the older `task.toml` + `instruction.md`), labelled `Robotics · <suite>` with its category, description, difficulty, source benchmark and item, a **Robot · env** column (backend, env, observation mode, success mode, step budget), the oracle result and one column per harness and model with a trial (Opus 5.5 / claude-code, GPT-6 Astra / codex, noop, claude-code-glm · GLM-5.3, codex-glm · GLM-5.3, mini-swe-agent-glm · GLM-5.3, lerobot-eval · MolmoAct2-LIBERO-LeRobot, ...). A task page shows the `task.md` body as the instruction and the whole `task.md` under Reviews.

## Formats Robo Use writes for the viewer

`src/robouse/atif.py` runs at the end of every trial (`runner.py`) and writes two files. To rebuild them for existing trials:

```
.venv/bin/python -m robouse.atif runs/<job>/<trial> [...]
```

### `agent/trajectory.json`: ATIF-v1.7

ATIF is the Agent Trajectory Interchange Format that the BenchFlow viewer and trainer read (validated against the viewer's trajectory models). Steps:

1. `source: user`: the prompt the harness received (the harness prefix from `harnesses.PROMPT_PREFIX` plus the task's instruction, the body of `task.md`).
2. One `source: agent` step per model turn:
   - **claude-code, claude-code-glm** (Claude Code `--output-format stream-json`): one step per assistant message id. `text` blocks become `message`, `thinking` blocks `reasoning_content`, `tool_use` blocks `tool_calls` (`function_name` = the tool, `arguments` = its input), and the matching `tool_result` blocks from the following user events become `observation.results` (by `tool_use_id`). Per-message usage becomes `metrics`; the final `result` event gives `final_metrics` (tokens, cost, turns).
   - **codex, codex-glm** (`codex exec --json`): one step per item. `agent_message` is a message step; `command_execution` a step with one `shell` tool call (the `/bin/zsh -lc '...'` wrapper removed) and its `aggregated_output` and exit code; `reasoning` items attach to the next step as `reasoning_content`; `file_change`, `mcp_tool_call`, `web_search` and `todo_list` are kept too. `turn.completed` usage gives `final_metrics`.
   - **mini-swe-agent-glm** (`agent/mini_traj.json`, mini-swe-agent 1.x format): one step per assistant message with its bash tool calls; tool messages are the observations. mini's own timestamps become step timestamps.
   - **oracle, noop** (no LLM): steps are built from `episode/trace.jsonl`: up to 10 motion requests (plus the observes around them) per step, one tool call `robo` per request with the request as arguments and the response as observation; `llm_call_count: 0`.
3. A final `source: system` step: requests the runner made itself (the closing `give_up` when the agent did not call `robo done`), any robo requests that could not be matched to a tool call, the episode outcome and the verifier reward.

Tool results are clipped to 4,000 characters (head and tail kept, with a note of what was dropped); messages to 20,000. Claude image results are not embedded as base64; they point to the saved copy (`../artifacts/observations/obs_NNN.png`, relative to `agent/`, which is how the viewer resolves image paths). Each step's `extra.video` holds its video span, the env steps it covered and the trace lines it came from. `notes` says which file the trajectory was converted from and lists anything skipped (malformed JSON lines, unmatched requests).

Robustness: every input is optional. Missing or empty output gives a trajectory with the prompt and the system step; malformed JSON lines are skipped and counted; commands that never finished are kept with a "did not finish" result.

### `artifacts/recording_index.json`: step → video time

The viewer's recording index (the format of `cua/harness/recording.py`, read by `benchviewer/evidence.py`):

```json
{
  "synthesised": false,
  "source": "robouse episode server: MuJoCo offscreen render ...",
  "time_axis": "video time runs only while the simulator steps; ...",
  "fps": 30, "size": [320, 320], "n_frames": 91, "duration_s": 3.033,
  "recording_start_epoch": 1790488709.141, "harness": "claude-code",
  "steps": [
    {"index": 3, "action": "robo move-to 0.059 0.7124 0.19; robo observe",
     "t_video_start_s": 0.033, "t_video_end_s": 0.7, "real_duration_s": 0.21,
     "episode_t_s": 4.38, "env_steps": [0, 36], "robo_requests": 2}
  ]
}
```

`index` is the ATIF `step_id`; every trajectory step has a row. `action` is the command (or `task`, `message: ...`, `system: ...`).

How video time is computed. The episode server records one frame every `frame_every` env steps (and during the settle period after `robo done`), with its wall time since the episode started (`episode/frames.jsonl`), and the video plays those frames at 30 fps. So the video contains only the moments the robot moved; the agent's thinking time is not in it. For a step whose robo requests start at episode time `t0` and are followed by the next request at `t1`, the span is from the last frame recorded at or before `t0` (the state the agent acted on) to the last frame recorded before `t1`, divided by 30. Steps without robo requests (messages, file reads) sit at the end of the previous step, so the step list is ordered in video time.

How tool calls are matched to the trace. Claude Code and Codex do not timestamp their events, so shell commands are matched to `episode/trace.jsonl` entries in order. A command owns as many consecutive entries as it made robo requests: the larger of the `robo <subcommand>` invocations in the command text and the robo result blocks in its output (a loop prints one block per call). Then the last result the command printed (the `hand_pos` and `steps_used` of a state, or an error line) is looked up in the trace to correct the end point. A script (python, bash) whose output shows no robo results gets the entries between the previous and the next matched command; a loop that ran more requests than it printed gets the unmatched ones after it. On the trials of 2026-09-27 (177 LLM trials), no request was left unmatched and 860 of 861 printed states matched an entry of their own step; the exception is a response that the server never wrote to the trace (see open issues).

## Overview page: `tools/site/build_gallery.py`

```
.venv/bin/python tools/analysis/audit.py          # optional: adds the audit column
.venv/bin/python tools/site/build_gallery.py  # writes runs/_gallery/index.html
open runs/_gallery/index.html
```

A single self-contained HTML file (white background, system font, no network). The top shows totals (trials, tasks, harness·model pairs, solve rate, suspicious, infra failures) for the current filter. Below them is a sortable table of every trial (task, job, suite, source benchmark, harness, model, reward, outcome, env steps, wall time, audit flags, viewer link), filterable by harness, model, suite, source benchmark, job, solved or failed, audit status and free text. Under the table there is one card per trial, 48 at a time, each with the video, the agent's last message, the `robo done` message and links to the full viewer, the video and the trial folder. Videos are linked relatively (`../<job>/<trial>/artifacts/recording.mp4`), so the page works from disk or when `runs/` is served. The viewer links need `tools/ops/view.sh` running (change the base with `--viewer URL`).

## Public viewer: `tools/site/build_runs_site.py`

```
.venv/bin/python tools/site/build_runs_site.py --out ~/benchflow/roboharm/site/runs   # then deploy the site
```

This builds https://robouse.ai/runs/, a static viewer for the final runs: every `runs/final-*` job, including jobs that are still running (their finished trials are in; rerun the command to add more). Unfinished trials are left out, except in jobs listed in `PARTIAL_JOBS`, where they are shown as partial. A job counts as running while a `robouse` process writes into it (checked with `ps` on the build machine); suites with a running job get a dot in the matrix. A rebuild takes about four minutes; videos and filmstrips that are already up to date are not encoded again.

Pages (plain HTML plus one script, `tools/site/runs_site/runs.js`, and one stylesheet, `tools/site/runs_site/runs.css`, on top of the site's shared header, footer, palette and type from the site repo's `tools/chrome.py`):

- `/runs/`: the results matrix (suites down, harness + model across; each cell is % solved and solved / scored, tinted by the solve rate, and opens that suite with the column highlighted), then every task with one column per harness + model, filterable by suite, model, outcome (solved, not solved, infra, partial, not run, split) and text. The counting rule is `tools/analysis/results.py`'s: per task the latest trial that was not an infrastructure failure. Opus 5.5 is tagged partial.
- `/runs/<suite>/`: the same task table for one suite (`?m=<column>` highlights a column).
- `/runs/task/<task>/`: the task's title, description, facts, every trial of it (other attempts are listed as not counted), a compare picker, the `task.md` instruction and its `robouse:` spec.
- `/runs/t/<trial>/`: one trial, with tabs. **Recording**: the video with a step lane, previous / next step (arrow keys), 0.25× / 0.5× / 1× speed, and the step list beside it (click a step to seek; the current step highlights while playing; steps that share a video time keep the one you clicked), then a filmstrip of the camera images the agent looked at (click to seek). **Trajectory**: prompt, messages, reasoning, commands, outputs and the camera images inline, each step with a seek button. **Verdict**: what the agent said (robo done, give-up, or nothing) against what the simulator checked, the verifier output and the episode facts. **Timing & tokens**: wall time, episode time, env steps against the budget, tokens and, where the harness reports them, per-step input and output tokens; a bar of the wall clock between steps. **Files**: the trial folder, with result.json and config.json shown (raw logs, the trace and server logs are not published).
- `/runs/compare/?a=<trial>&b=<trial>`: two trials of one task side by side, each video synced to its own step list.
- `/runs/jobs/` and `/runs/jobs/<job>/`: the jobs and their trials.

Data: `d/<trial>.json` (the trajectory clipped: messages 6,000 characters, outputs 2,000; workspace paths shown as `<workspace>`), `d/trials.json` (index for the compare picker), `v/<trial>.mp4` (re-encoded to H.264 Main, CRF 30, faststart, no audio) and `f/<trial>.webp` (the camera images as one sprite of 112 px tiles, at most 60 per trial, sampled evenly). Claude Code prices every model as Claude, so costs are shown only for Opus 5.5.

Publishing safety: the build replaces secret-shaped strings with `[redacted]`, withholds the trajectory of trials whose agent looked at files outside its workspace (the page says so and still shows the video, camera images and reward), then scans the output for secret shapes and banned words, checks every internal link and data reference, and exits non-zero if anything fails.

## Open issues

- Fixed on the viewer's `robouse` branch (2026-09-27): the CUA wording on the Recording tab and the `3D ·` area label, `task.md` folders missing from the Tasks page, the fixed Opus/Astra/Fable model columns, and "No timing data". The copy at `~/benchflow/data/viewer` (what 8765 and 8766 serve) does not have these changes until the branch is merged there.
- Timing is one span: Robo Use records no per-phase timing, so the whole run (`wall_time_s`) is shown as Agent Execution. Writing phase timings to `result.json` (`timing: {environment_setup, agent_setup, agent_execution, verifier}` in seconds) would split it.
- The Recording's simulator name is inferred from text (`source`, benchmark, backend). Adding `"simulator": "MuJoCo"` to `recording_index.json` would make it explicit; the viewer reads that field first.
- The /review queue's model filter still offers only Opus, Astra and Fable (other models are "other").
- Videos are small and short (320×320, frames every 2 env steps at 30 fps: a 150-step episode is about 2.5 s). Slow playback may be preferable for review.
- A runner process imports `robouse.atif` once at start, so jobs started before a change to `atif.py` keep the old converter. Rebuild with `python -m robouse.atif` (the audit and the gallery build a missing trajectory in memory).
