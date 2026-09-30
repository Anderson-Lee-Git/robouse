# Metrics, splits, repeats and reports

## Episode metrics

The episode server samples the physical state at every control step (`episode/physics.jsonl`: end-effector or base point, simulation time, the largest contact force on the robot's own geoms) and writes `metrics` into `episode/result.json` when the episode ends. They never change the verdict.

| Metric | Definition |
|---|---|
| `success` | the trusted verdict |
| `progress` | fraction of the task's stages reached in order, or the operator's rubric stage over the top stage; otherwise equal to success |
| `execution_time_s` | control steps used x control period (reported over successful episodes) |
| `execution_speed` | stages (or 1 task) completed per active minute (successful episodes) |
| `smoothness_sparc` | spectral arc length of the end-effector (or base) speed, fc = 10 Hz; <= 0, closer to 0 is smoother |
| `avg_jerk` | mean norm of the end-effector jerk after a 10 Hz low-pass (m/s^3) |
| `path_length_m` | end-effector (or base) path length |
| `max_contact_force_n` | largest normal contact force on the robot (MuJoCo backends) |
| `safety_events`, `safe_failure` | safety events (falls, crashes, harm, e-stops, stops); a failed episode with none is a safe failure |
| `excellent` | success with no safety event and no vetoed motion (aggregated as execution quality over successes) |
| navigation | `arrived`, `spl`, `soft_spl`, `collisions`, `time_to_target_s`, `path_ratio`, `excess_turning_rad_per_m` ([suites/nav.md](suites/nav.md)) |

Each trial's `result.json` also carries `cost`: prompt, completion and cached tokens from the ATIF trajectory, and USD from the harness (Claude Code) or `src/robouse/pricing.json` (Baseten Model API prices read 2026-09-29; override with `ROBOUSE_PRICING`). `config.json` carries provenance (Robo Use version, git commit and dirty flag, Python, simulator package versions).

## Repeats, subsets and splits

```bash
robouse run-many --harness oracle --out runs/x \
  --include 'libero-*' --exclude '*-drawer*' --sample 20 --sample-seed 1 \
  --seeds 0-4 --epochs 1 --retries 2 --split interpolation --dry-run
```

- `--seeds` (one trial per seed; pass@k in the report), `--epochs` (repeats of the same seed, e.g. real robots), `--retries` (infrastructure failures only, exponential backoff, failed trial kept in `_infra_failed/`).
- `--include` / `--exclude` (globs on task ids), `--sample N --sample-seed S`, `--limit`, `--mode sim|real`, `--dry-run`.
- `--extra-instruction TEXT`, `--prior-learnings FILE` (e.g. from `robouse summarize TRIAL`, a deterministic digest of a trial's outcome, errors and last requests).
- `--split nominal|interpolation|extrapolation`: seeded object placements, identical for every policy given (task, split, seed). Nominal: the task's placement or one of four 2 cm diagonal shifts; interpolation: unseen placements inside that square; extrapolation: 3-6 cm away. Supported by the tabletop pick-and-place scenes (68 tasks without a cell grid). Reference solutions: 8/8 on each split (4 tasks x seeds 0-1).

## Reports

```bash
robouse report runs/a runs/b --by harness,model --by suite
robouse report runs/nav-* --by model --metrics success,spl,soft_spl,collisions,cost_usd --cost-quality cq.json --svg cq.svg
```

Groups by any of harness, model, suite, category, difficulty, task, split, seed, mode (sim / real / hil-mock), job, regime (a job's training-data regime, set in its `job.json`) and released (a task's `metadata.released`, public vs held-out). Proportions get 95% Wilson score intervals (defined at 0% and 100%), means get 95% percentile bootstrap intervals (2000 resamples, fixed seed), and pass@k (unbiased) is averaged over tasks when trials repeat. `--json` writes everything; `--cost-quality` and `--svg` write cost-per-run against success for groups with a known cost.
