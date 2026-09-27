# Viewing trials

There are two ways to look at trials: the full BenchFlow viewer (one trial at a time, video synced to the agent's steps) and a static overview page (every trial on one page).

## Full viewer: `scripts/view.sh`

```
scripts/view.sh               # http://127.0.0.1:8768
scripts/view.sh --port 8770
```


What you get:

- **Jobs**: one job per folder under `runs/` (for example `mw-claude-opus`), with reward, cost and tokens per task. Folders starting with `_` (`_gallery`, `_audit`) are skipped.
- **Trial page** (`/jobs/<job>/tasks/_/<harness>/<provider>/<model>/<task>/trials/<trial>`):
  - **Trajectory**: the ATIF trajectory: the prompt, then every agent step with its message, reasoning (Codex reasoning summaries and Claude thinking when recorded), tool calls and their results. When the agent looked at a camera image (`robo observe --image`, then Claude's Read tool), the image is shown from `artifacts/observations/`.
  - **Recording**: the episode video with the step list beside it. Clicking a step seeks the video to the moment its robo requests ran; the playing video highlights the current step. The caption under the video is the viewer's CUA wording ("screen recording ... click point"); there are no click markers for robot trials.
  - **Verdict / Verifier**: `verifier/reward.txt` and `test-stdout.txt`.
  - **Config**: `config.json` (task, harness, model, seed, timeouts, task metadata). **Agent** and **Log**: raw `agent/stdout.jsonl` and `stderr.txt`.
- **Tasks** (home page): every task under `tasks/<suite>/`, with its description, difficulty, the oracle result and the latest Opus and Astra trial. Robot tasks are labelled `3D · <suite>` (the viewer knows only the 3D and CUA areas), and the GLM runs have no model column there (the viewer's columns are Opus, Astra and Fable); both show fully on the job and trial pages.

## Formats robouse writes for the viewer

`src/robouse/atif.py` runs at the end of every trial (`runner.py`) and writes two files. To rebuild them for existing trials:

```
.venv/bin/python -m robouse.atif runs/<job>/<trial> [...]
```

### `agent/trajectory.json`: ATIF-v1.7


1. `source: user`: the prompt the harness received (the harness prefix from `harnesses.PROMPT_PREFIX` plus the task's `instruction.md`).
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

## Overview page: `scripts/build_gallery.py`

```
.venv/bin/python scripts/audit.py          # optional: adds the audit column
.venv/bin/python scripts/build_gallery.py  # writes runs/_gallery/index.html
open runs/_gallery/index.html
```

A single self-contained HTML file (white background, system font, no network). The top shows totals (trials, tasks, harness·model pairs, solve rate, suspicious, infra failures) for the current filter. Below them is a sortable table of every trial (task, job, suite, source benchmark, harness, model, reward, outcome, env steps, wall time, audit flags, viewer link), filterable by harness, model, suite, source benchmark, job, solved or failed, audit status and free text. Under the table there is one card per trial, 48 at a time, each with the video, the agent's last message, the `robo done` message and links to the full viewer, the video and the trial folder. Videos are linked relatively (`../<job>/<trial>/artifacts/recording.mp4`), so the page works from disk or when `runs/` is served. The viewer links need `scripts/view.sh` running (change the base with `--viewer URL`).

## Open issues

- The Recording tab's caption and the tasks page's area label are CUA/3D wording from the viewer; changing them would need a viewer change (not done).
- Videos are small and short (320×320, frames every 2 env steps at 30 fps: a 150-step episode is about 2.5 s). Slow playback may be preferable for review.
- A runner process imports `robouse.atif` once at start, so jobs started before a change to `atif.py` keep the old converter. Rebuild with `python -m robouse.atif` (the audit and the gallery build a missing trajectory in memory).
