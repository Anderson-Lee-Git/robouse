# tools

Maintainer tools for the Robo Use repository. None of them ship in the package. Run them from the repository root with a development environment (`uv pip install -e ".[all]"` plus `pytest`), usually as `.venv/bin/python tools/<dir>/<script> --help`.

| Path | What it does |
|---|---|
| `gate.py` | Release gate: reference solution (must score 1) and no-op (must score 0) on a seeded sample of every CPU suite. |
| `ci/ci.yml` | The GitHub Actions workflow (lint, format, types, tests on Python 3.11 and 3.12, the wheel). To turn it on, copy it to `.github/workflows/ci.yml`; pushing a workflow needs a GitHub token with the `workflow` scope. |
| `metrics.py` | Code-quality metrics: lines of code, duplicated lines, module count. |
| `analysis/audit.py` | Audits trial folders under `runs/` for infrastructure failures and oddities (`docs/audit.md`). |
| `analysis/results.py` | Writes the results tables in `docs/results.md` from the audit. |
| `analysis/rerun_infra.py` | Reruns trials that failed for infrastructure reasons. |
| `docs/build_docs.py` | Builds the static docs site (robouse.ai/docs/) from `docs/`. |
| `docs/cli_reference.py` | Writes `docs/cli.md` from the real `--help` output. |
| `site/build_runs_site.py` | Builds the public runs viewer (robouse.ai/runs/); assets in `site/runs_site/`. |
| `site/build_gallery.py` | One local HTML page with every trial under `runs/`. |
| `site/component_stills.py` | Stills of the composable components for the hub. |
| `assets/pin_menagerie.py` | Pins the MuJoCo Menagerie robots the embodiment suites use (`assets/menagerie/embodiments.json`). |
| `assets/make_hil_fixture.py` | Builds a hardware-in-the-loop fixture from a session recorded on a real arm. |
| `assets/urdf_to_chain.py` | Writes a real arm's kinematic chain from its vendor URDF. |
| `setup/setup_robocasa.sh` | Sets up the isolated RoboCasa environment. |
| `gpu/` | GPU-track sandbox lifecycle, worker upload and snapshots (Daytona). |
| `benchflow/scene_planner_operator.py` | Two roles on one robot as a BenchFlow scene (needs `robouse[benchflow]`). |
| `ops/backup.sh` | Backs up run data to the maintainers' bucket. |
| `ops/final_run.sh` | The final evaluation, one stream per model and harness. |
| `ops/view.sh` | Opens trials in the BenchFlow viewer. |
| `ops/vla_dogfood.sh` | Dogfoods the `vla` harness against mock policy servers. |
