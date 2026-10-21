# Recorded practice runs

Robo Use's version of ASPIRE's `docs/run-artifacts.md` for this trial: what `cap-harness run` records. Each run is one Robo Use practice episode (`docs/robouse.md`); the layout and the field names are cap-harness's, so ASPIRE's scripts read them as written.

```text
<output-root>/<benchmark>/<suite>/<task-id>-<task>/<seed>/<run-id>/    # default
<output-root>/<seed>/<run-id>/                                        # with --flat-run-dir
```

Seeds use four digits. Run ids are a UTC timestamp and a random suffix; every run gets a new folder. A seed the practice broker refuses gets no folder: the command prints the reason and exits 3, and `run-batch` reports it as `NO ARTIFACT`.

- `run.json`: identity (benchmark, suite, task id, the Robo Use task, seed, `init_mode`), `capture` (the `--max-steps`, camera size and video settings asked for), `status` (`in_progress`, then `finalized`), timestamps, and under `robouse` the practice episode's id and scene.
- `outcome.json`: `program_ok`, `task_success` (the episode server's verdict after `robo done` and 10 still steps), `termination_reason`, `steps_executed` (control steps the episode used), `error`, `wall_duration_s` and a `timing` block (buckets `setup`, `program`, `judge`, `finalize`). `cumulative_reward` and `protocol_success` are always null: Robo Use scores the final state only. `robouse` holds the episode's own outcome (`done`, `budget_exhausted`, `success_reached`, ...), its step count and the judge's detail.
- `manifest.json`: path, size and SHA-256 of every file.
- `source/program.py` (the exact program) and `source/program-result.json` (`ok`, the program's `result`, the error).
- `logs/program.stdout` (what the program and the API printed) and `logs/program.stderr` (empty).
- `trace/events.jsonl`: one `span_end` record per tool call (name, `ok`, `error`, `duration_s`, the control steps it took and the episode's step count after it), and `trace/calls/call-NNNNNN-<tool>/{input,output}.json` with its arguments and its reply without the robot state.
- `episode/result.json` (the episode server's verdict), `episode/robo-trace.jsonl` (every request the episode got, with its reply) and `episode/physics.jsonl` (the hand position, time and largest contact force at every control step).
- `media/videos/<camera>.mp4`: the episode's video from the task's camera (not with `--no-videos`), with `media/frames.jsonl` giving the time and step of each frame.
- `media/keyframes/<NNNNNN>-after-<tool>/<camera>.png`: one camera image at the start (`after-reset`) and after every tool call that moved the robot (not with `--no-keyframes`).

There are no SAM3 overlays, depth arrays or provider spans: the task has no perception service.

## Termination reasons

| Code | Meaning here |
|---|---|
| `program_completed` | the program returned normally |
| `task_succeeded` | the task ended the episode on success while the program ran (tasks judged at the first success) |
| `environment_truncated` | the episode's wall-clock limit ended it |
| `step_limit` | the task's step budget ran out |
| `program_error` | the program was refused by the syntax check or raised |
