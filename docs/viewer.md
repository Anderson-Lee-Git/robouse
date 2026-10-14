# Viewing trials

Maintainers' notes on the trial viewers. Every trial folder has `agent/trajectory.json` (an ATIF trajectory) and `artifacts/recording_index.json` (video time per step), which the BenchFlow trial viewer (not public yet) reads; this page describes those two formats, the static overview page (every trial on one page) and the builder of the public viewer at [robouse.ai/runs](https://robouse.ai/runs/).

## Formats Robo Use writes for the viewer

`src/robouse/runner/atif.py` runs at the end of every trial (`runner/trial.py`) and writes two files. To rebuild them for existing trials:

```
.venv/bin/python -m robouse.runner.atif runs/<job>/<trial> [...]
```

### `agent/trajectory.json`: ATIF-v1.7

ATIF is the Agent Trajectory Interchange Format that the BenchFlow viewer and trainer read (validated against the viewer's trajectory models). Steps:

1. `source: user`: the prompt the harness received (the harness prefix from `harnesses.PROMPT_PREFIX` plus the task's instruction, the body of `task.md`).
2. One `source: agent` step per model turn:
   - **claude-code** (and the earlier claude-code-glm; Claude Code `--output-format stream-json`): one step per assistant message id. `text` blocks become `message`, `thinking` blocks `reasoning_content`, `tool_use` blocks `tool_calls` (`function_name` = the tool, `arguments` = its input), and the matching `tool_result` blocks from the following user events become `observation.results` (by `tool_use_id`). Per-message usage becomes `metrics`; the final `result` event gives `final_metrics` (tokens, cost, turns).
   - **codex** (and the earlier codex-glm; `codex exec --json`): one step per item. `agent_message` is a message step; `command_execution` a step with one `shell` tool call (the `/bin/zsh -lc '...'` wrapper removed) and its `aggregated_output` and exit code; `reasoning` items attach to the next step as `reasoning_content`; `file_change`, `mcp_tool_call`, `web_search` and `todo_list` are kept too. `turn.completed` usage gives `final_metrics`.
   - **mini-swe-agent** (and the earlier mini-swe-agent-glm; `agent/mini_traj.json`, mini-swe-agent 1.x format): one step per assistant message with its bash tool calls; tool messages are the observations. mini's own timestamps become step timestamps.
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

A single self-contained HTML file (white background, system font, no network). The top shows totals (trials, tasks, harness·model pairs, solve rate, suspicious, infra failures) for the current filter. Below them is a sortable table of every trial (task, job, suite, source benchmark, harness, model, reward, outcome, env steps, wall time, audit flags, viewer link), filterable by harness, model, suite, source benchmark, job, solved or failed, audit status and free text. Under the table there is one card per trial, 48 at a time, each with the video, the agent's last message, the `robo done` message and links to the full viewer, the video and the trial folder. Videos are linked relatively (`../<job>/<trial>/artifacts/recording.mp4`), so the page works from disk or when `runs/` is served. The viewer links need a BenchFlow trial viewer serving `runs/` (its base URL is `--viewer URL`, default http://127.0.0.1:8768).

## Public viewer: `tools/site/build_runs_site.py`

```
.venv/bin/python tools/site/build_runs_site.py --out <site checkout>/site/runs   # then deploy the site
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

- Timing is one span: Robo Use records no per-phase timing, so the whole run (`wall_time_s`) is shown as Agent Execution. Writing phase timings to `result.json` (`timing: {environment_setup, agent_setup, agent_execution, verifier}` in seconds) would split it.
- The Recording's simulator name is inferred from text (`source`, benchmark, backend). Adding `"simulator": "MuJoCo"` to `recording_index.json` would make it explicit; the viewer reads that field first.
- Videos are small and short (320×320, frames every 2 env steps at 30 fps: a 150-step episode is about 2.5 s). Slow playback may be preferable for review.
- A runner process imports `robouse.runner.atif` once at start, so jobs started before a change to `atif.py` keep the old converter. Rebuild with `python -m robouse.runner.atif` (the audit and the gallery build a missing trajectory in memory).
