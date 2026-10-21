# ASPIRE in this Robo Use trial

This workspace runs NVIDIA's ASPIRE ({{aspire_repo}} at commit `{{aspire_commit}}`, Apache-2.0) inside one Robo Use trial, on one task. The skill files under `.claude/skills/` and `.codex/skills/` are ASPIRE's own, unchanged. This page is Robo Use's: it says how ASPIRE's terms map onto this trial. Where it says something different from a skill file, follow this page.

## Who does what

- You are the campaign's coordinator, and your subagents are its workers and verifiers, exactly as ASPIRE's guides describe: Stage 0 and Stage 1 for the task, a verifier for any proposed skills, and the promotion of verified proposals into the library.
- Robo Use runs the practice episodes your programs run on (through `cap-harness`, below) and judges each one.
- Robo Use runs Stage 2 itself. When you exit, it runs `{{program}}` once on the scored episode: a held-out scene of this task that no practice seed shows, with the skill library frozen as you left it. That one run is the trial's score; you never see it. The scored episode is locked: a trial in which anything but Stage 2 sends it a request is not scored. Do not run `run_validation.py`, and do not wait for Stage 2.
- There is no human. Never stop to report a plan and wait for confirmation; when the guides say to ask the user, decide yourself and write down why.

## This campaign

| Variable | Value here |
|---|---|
| `BENCHMARK`, `SUITE`, `TASK_ID` | `{{benchmark}}`, `{{suite}}`, `{{task_id}}` (Robo Use task `{{task}}`; its text and API: `docs/task.md`) |
| `RUN_ROOT` | `{{run_root}}` (already initialized; do not run `init_run.py` again) |
| `TASK_DIR` | `{{task_dir}}` |
| `DEV_SEEDS` | {{dev}} |
| `UNSEEN_SEEDS` | {{unseen}} (each runs once) |
| `HELDOUT_COUNT` | {{heldout_count}}: a number `init_run.py` needs; the held-out evaluation is the scored episode only |
| `MAX_STEPS` | {{max_steps}}, the task's step budget (`--max-steps` cannot raise it) |
| `CAP_HARNESS` | `cap-harness` (on PATH) |
| `INIT_MODE` | `saved` (accepted and recorded; here the seed alone picks the scene: {{seed_rule}}) |
| `GPU` | none: write `GPU: none` where a template asks for one |
| `SERVICE_PORTS`, `RUN_ENV` | none, empty |
| Selected program | `{{program}}` |

## Practice episodes: cap-harness

`cap-harness run` and `cap-harness run-batch` take ASPIRE's options and write ASPIRE's run layout (`docs/run-artifacts.md`), so the guides' commands and scripts (`evosearch_eval.py`, `analyze_evosearch_traces.py`, the scoring one-liners) work as written. The differences:

- Each run is a fresh Robo Use practice episode of this task on one seed: the task's own episode server, started for that run and stopped after it (a reset). Only `--benchmark {{benchmark}} --suite {{suite}} --task-id {{task_id}}` runs, and only on the seeds above. A seed outside them, or one that would show the scored scene, is refused: the run prints `NO ARTIFACT` with the reason.
- The practice budget is {{max_episodes}} episodes for this trial, {{workers}} at a time (`run-batch` queues the rest). A refused or rejected program uses none. A practice episode of this task takes about a minute, so a sweep of many seeds can outlast one shell command's time limit: run it in the background and read its `results.jsonl`, which grows as seeds finish, as ASPIRE's evosearch guide does.
- Success is Robo Use's judge, the one Stage 2 gets: after your program returns, the episode ends with `robo done`, the robot holds still for 10 control steps, and then the task's own check runs ({{success_rule}}). `task_success` in `outcome.json` is that verdict. `termination_reason` is `step_limit` when the step budget ran out, `task_succeeded` when the task ended the episode on success, `program_error` when the program was refused or raised, else `program_completed`.
- `--init-mode`, `--camera-width` and `--camera-height` are recorded but change nothing; images come at the task's own size.

## Programs

`docs/api-reference.md` is the contract, for practice runs and Stage 2 alike. It is ASPIRE's (one syntax check, a short list of builtins, a top-level `result`), with two differences: programs may also `import numpy`, and the tools are this task's own API instead of cap-harness's. There is no `get_task_context`, `segment_text`, `localize_object`, `move_to_pose`, `Pose`, `RobotAction` or `ArmCommand` here; what the robot perceives is what the task's API returns ({{perception}}). ASPIRE's provenance rule holds as written: never copy a coordinate, dimension or seed identity you observed on a practice seed into a program; derive it at run time through the API.

To look at a scene, run `docs/scene_snapshot.py` on the first development seed (copy it into `TASK_DIR/code/` to probe more). ASPIRE's own `scripts/scene_snapshot.py` uses cap-harness's perception tools and cannot run here.

## The skill library

- The library is `.claude/skills/iterative-debugging/skills/`. {{library_sentence}}
- Its entries were written for cap-harness's perception API on LIBERO-Pro and Robosuite. Grade every section you open as ASPIRE asks (`not-applicable` when it does not apply to this task's API), and write new proposals against this task's API.
- Promote only proposals a verifier returned `verified` on, as ASPIRE's coordinator guide says; the promotion route is unchanged. `lint_skills.py` and `campaign.py --validate-skill-report` work here: `src/cap_harness/runtime.py` is Robo Use's program contract under the name the lint imports, and `docs/api-reference.md` lists this task's tools. On ASPIRE's own entries the full lint fails: it lists the cap-harness tools they call (`localize_object`, `move_to_pose`, `Pose` and others) as defined nowhere, which is true of this task's API. After a promotion, check that it lists nothing from the entries you promoted; `lint_skills.py --proposal` (which `dispatch.py verify` runs) reports only a proposal's own problems.

## Subagents

- Dispatch workers and verifiers as the coordinator guide says: Claude Code's Agent tool (`subagent_type: "general-purpose"`) or Codex's own agents. Run one job at a time: the practice pool is shared, so a second job only queues.
- Without a subagent tool, play each role yourself in order, and keep the verifier's reading rules while you verify.

## Not here

- GPUs and the perception and planning services (SAM3, Contact-GraspNet, PyRoki and cuRobo on ports 8114 to 8118): skip every service check, `nvidia-smi`, `supervise_services.sh`, `CUDA_VISIBLE_DEVICES` and `MUJOCO_EGL_DEVICE_ID`. The ledger has one row, `GPU none`.
- `run_validation.py` (Stage 2 is Robo Use's), `audit_seeding.py` (cap-harness's LIBERO adapter), `cap-harness doctor`, `manifest` and `validate`, `examples/`, `docs/libero-pro.md` and `docs/robosuite.md` (this page replaces them).
- `docs/task.md` is the task as Robo Use gives it to an agent that drives the robot directly. Here your programs drive practice episodes and Stage 2 instead: ignore what it says about `robo done`, `robo give-up` and saving `capx_api.py`.
