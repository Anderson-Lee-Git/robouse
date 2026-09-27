# robo-use on BenchFlow

This folder packages robo-use tasks as BenchFlow-native task packages so they run with `bench eval run`, with the simulator in its own trusted container. Full guide, trust model and recorded validation runs: [../docs/benchflow.md](../docs/benchflow.md).

| Path | What it is |
|---|---|
| `export.py` | converts task folders (any suite under `tasks/`) into a BenchFlow bundle: `task.md` packages plus `benchmark.yaml` and example eval configs |
| `runtime/Dockerfile.sim` | the trusted simulator image (`robouse-sim`): python:3.12-slim + MuJoCo + Meta-World + Gymnasium-Robotics + the `robouse` package from this checkout, OSMesa headless rendering |
| `runtime/requirements-sim.txt` | pinned simulator dependencies (same versions as the dev venv) |
| `runtime/sim-entry.sh` | simulator service entry point: runs `robouse serve`, then stays up for the verifier |
| `templates/environment/Dockerfile` | the agent (`main`) image: python + numpy + the `robo` client, nothing else |
| `templates/environment/docker-compose.yaml` | per-task topology: `main` + `simulator`, shared read-only socket volume |
| `templates/verifier/` | `verifier.md`, `test.sh`, `verify.py`: runs in the `simulator` service and writes `/logs/verifier/reward.txt` |

Quick start (from the repo root; `dist/` and `jobs/` are git-ignored):

```sh
.venv/bin/python benchflow/export.py --tasks tasks/metaworld/metaworld-reach tasks/metaworld/metaworld-push --out benchflow/dist/robouse
cd benchflow/dist/robouse
bench tasks check tasks/metaworld-reach --level runtime-capability --sandbox docker
bench eval run --config robouse-oracle.yaml        # expect reward 1.0 on every task
```
