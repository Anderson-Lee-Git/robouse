# tools

Maintainer tools for the Robo Use repository. None of them ship in the package. Run them from the repository root with a development environment (`uv pip install -e ".[all]"` plus `pytest`), usually as `.venv/bin/python tools/<dir>/<script> --help`.

Most contributors need only `gate.py`, `setup/`, `assets/` and the `docs/` generators. The rest serves the maintainers' own runs and infrastructure: `ops/` (backups and evaluation runs), `gpu/` (Daytona GPU sandboxes), `site/` (the robouse.ai/runs viewer), `analysis/` (audits of local runs) and `benchflow/` (needs an unreleased BenchFlow build). They take their machine-specific settings from the environment, never from the repository.

| Path | What it does |
|---|---|
| `gate.py` | Release gate: reference solution (must score 1) and no-op (must score 0) on a seeded sample of every CPU suite. |
| `metrics.py` | Code-quality metrics: lines of code, duplicated lines, module count. |
| `analysis/audit.py` | Audits trial folders under `runs/` for infrastructure failures and oddities (`docs/audit.md`). |
| `analysis/results.py` | Writes a results table (Markdown) from the audit, by default to `runs/_audit/results.md`; the published results are robouse.ai/runs/. |
| `analysis/rerun_infra.py` | Reruns trials that failed for infrastructure reasons. |
| `docs/build_docs.py` | Builds the static docs site (robouse.ai/docs/) from `docs/`. |
| `docs/cli_reference.py` | Writes `docs/cli.md` from the real `--help` output. |
| `site/build_runs_site.py` | Builds the public runs viewer (robouse.ai/runs/); assets in `site/runs_site/`. |
| `site/build_gallery.py` | One local HTML page with every trial under `runs/`. |
| `site/component_stills.py` | Stills of the composable components for the hub. |
| `assets/pin_menagerie.py` | Pins the MuJoCo Menagerie robots the embodiment suites use (`assets/menagerie/embodiments.json`). |
| `assets/pin_chemlab.py` | Pins the ChemLab-Assets files the chemlab suite downloads (`assets/chemlab/provenance.json`). |
| `assets/make_hil_fixture.py` | Builds a hardware-in-the-loop fixture from a session recorded on a real arm. |
| `assets/urdf_to_chain.py` | Writes a real arm's kinematic chain from its vendor URDF. |
| `setup/setup_robocasa.sh` | Sets up the isolated RoboCasa environment. |
| `gpu/` | GPU-track sandbox lifecycle, worker upload and snapshots (Daytona). |
| `benchflow/scene_planner_operator.py` | Two roles on one robot as a BenchFlow scene (needs `robouse[benchflow]`). |
| `ops/backup.sh`, `ops/backup_all.sh` | Back up run data to a Google Cloud Storage bucket named by `ROBOUSE_BACKUP_URI` and `ROBOUSE_BACKUP_PROJECT` (environment, or `~/.config/robouse/ops.env`). |
| `ops/final_run.sh` | The final evaluation, one stream per model and harness. |
| `ops/vla_dogfood.sh` | Dogfoods the `vla` harness against mock policy servers. |
| `aspire/standin_model.py` | A scripted stand-in model (OpenAI chat completions with tool calls) that walks Claude Code through ASPIRE's workflow on a `capx` task, to check the `aspire` harness end to end without model credentials. |
