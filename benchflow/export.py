"""Export robouse task folders as BenchFlow-native task packages.

    python benchflow/export.py --tasks tasks/metaworld --out benchflow/dist/robouse [--filter reach,push]

`--tasks` may point at one task folder, a suite (tasks/metaworld) or the whole tasks/ tree. The output is a
self-contained bundle; move it as a whole (tasks share runtime/):

    <out>/
      benchmark.yaml                 BenchFlow benchmark descriptor
      robouse-oracle.yaml            example `bench eval run --config` files (run them from <out>)
      robouse-claude.yaml, robouse-codex.yaml
      runtime/                       build context of the trusted simulator image (robouse-sim)
        Dockerfile.sim  requirements-sim.txt  sim-entry.sh  robouse/{pyproject.toml,README.md,src/robouse}
      tasks/<task-id>/
        task.md                      schema_version 1.3 frontmatter + the task's instruction.md as the prompt
        environment/Dockerfile       agent (`main`) image: python + the `robo` client only
        environment/robo             copy of src/robouse/agent_cli.py (stdlib only)
        environment/docker-compose.yaml   `main` + trusted `simulator` services (embeds the robouse task definition)
        verifier/{verifier.md,test.sh,verify.py}   runs in `simulator` (verifier.service)
        oracle/solve.sh + oracle/vendor/     reference solution; drives the robot through `robo`'s socket only

With --noop-oracle, oracle/solve.sh only looks (`robo info`, `robo observe`) and exits without `robo done`:
a negative control that must score 0 and exercises the verifier's close-the-episode path.

Only the Python standard library is needed to export, except Meta-World tasks, whose oracle vendors
Meta-World's scripted expert policies (pure numpy) out of the installed `metaworld` package.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SRC = REPO / "src" / "robouse"
sys.path.insert(0, str(SRC.parent))  # import robouse.tasks from this checkout
TEMPLATES = HERE / "templates"
RUNTIME = HERE / "runtime"
SIM_TAG = "0.1.0"
WALL_MARGIN_S = 900  # the episode clock starts when the simulator is up, before the harness is installed


def _yaml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)  # JSON strings are valid YAML scalars


def _yaml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_yaml_value(x) for x in v) + "]"
    return _yaml_str(str(v))


def find_tasks(root: Path) -> list[Path]:
    from robouse.tasks import find_tasks as _find

    if (root / "task.md").exists() or (root / "task.toml").exists():
        return [root]
    return [t.path for t in _find(root)]


def _sim_task_md(meta: dict) -> str:
    """The task definition the simulator container needs (frontmatter only; the prompt is not in it)."""
    import yaml

    fm = {k: meta[k] for k in ("schema_version", "task", "metadata", "agent", "verifier", "robouse") if k in meta}
    return "---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, width=10**6) + "---\n"


def write_runtime(out: Path) -> None:
    rt = out / "runtime"
    if rt.exists():
        shutil.rmtree(rt)
    rt.mkdir(parents=True)
    for name in ("Dockerfile.sim", "requirements-sim.txt", "sim-entry.sh"):
        shutil.copy2(RUNTIME / name, rt / name)
    pkg = rt / "robouse"
    pkg.mkdir()
    for name in ("pyproject.toml", "README.md"):
        shutil.copy2(REPO / name, pkg / name)
    shutil.copytree(SRC, pkg / "src" / "robouse", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def task_md(toml: dict, instruction: str) -> str:
    t, meta, rb = toml.get("task", {}), toml.get("metadata", {}), toml["robouse"]
    agent_timeout = float(toml.get("agent", {}).get("timeout_sec", 900))
    lines = [
        "---",
        'schema_version: "1.3"',
        "task:",
        f"  name: {_yaml_str(t.get('name') or 'robouse/' + rb['id'])}",
        f"  description: {_yaml_str(t.get('description', ''))}",
        "metadata:",
        "  author_name: benchflow",
    ]
    for k in ("category", "difficulty", "tags", "source_benchmark", "source_task", "suite"):
        if k in meta:
            lines.append(f"  {k}: {_yaml_value(meta[k])}")
    for k in ("backend", "env", "seed", "max_steps", "success_mode", "skills"):
        if k in rb:
            lines.append(f"  robouse_{k}: {_yaml_value(rb[k])}")
    lines += [
        "agent:",
        f"  timeout_sec: {int(agent_timeout)}",
        "verifier:",
        "  service: simulator",
        "  user: root",
        "  timeout_sec: 300",
        "sandbox:",
        "  cpus: 1",
        "  memory_mb: 2048",
        "  build_timeout_sec: 1800",
        "---",
        "",
    ]
    return "\n".join(lines) + instruction.rstrip() + "\n"


def compose(toml: dict, toml_text: str) -> str:
    # compose interpolates $VARS in values; `$$` is a literal dollar sign
    block = "\n".join("        " + ln.replace("$", "$$") for ln in toml_text.rstrip().splitlines())
    agent_timeout = float(toml.get("agent", {}).get("timeout_sec", 900))
    text = (TEMPLATES / "environment" / "docker-compose.yaml").read_text()
    return (text.replace("__SIM_TAG__", SIM_TAG)
                .replace("__MAX_WALL_S__", str(int(agent_timeout + WALL_MARGIN_S)))
                .replace("__SEED_ARGS__", "")
                .replace("__TASK_MD__", block))


def _metaworld_vendor(env: str, vendor: Path) -> None:
    """Copy Meta-World's scripted expert for `env` (numpy only) so the oracle runs without the simulator."""
    from metaworld.policies import ENV_POLICY_MAP  # needs the dev venv

    cls = ENV_POLICY_MAP[env]
    src_dir = Path(sys.modules[cls.__module__].__file__).parent
    dst = vendor / "metaworld" / "policies"
    dst.mkdir(parents=True)
    (vendor / "metaworld" / "__init__.py").write_text(
        '"""Vendored subset of Meta-World (MIT): only the scripted expert policy this task needs."""\n')
    mod = cls.__module__.rsplit(".", 1)[1]
    for name in ("action.py", "policy.py", f"{mod}.py"):
        shutil.copy2(src_dir / name, dst / name)
    (dst / "__init__.py").write_text(
        f"from metaworld.policies.{mod} import {cls.__name__}\n\nENV_POLICY_MAP = {{{env!r}: {cls.__name__}}}\n")


NOOP_SOLVE = """#!/bin/bash
# Negative control (export.py --noop-oracle): look at the robot, never move it, exit without `robo done`.
# The verifier must close the episode itself (outcome agent_exited) and the reward must be 0.
set -euo pipefail
robo info
robo observe
"""


def write_oracle(task_dir: Path, toml: dict, dst: Path, noop: bool = False) -> None:
    rb = toml["robouse"]
    if noop:
        dst.mkdir(parents=True)
        (dst / "solve.sh").write_text(NOOP_SOLVE)
        (dst / "solve.sh").chmod(0o755)
        return
    vendor = dst / "vendor"
    shutil.copytree(SRC, vendor / "robouse", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if rb.get("backend") == "metaworld":
        _metaworld_vendor(rb["env"], vendor)
    from robouse.tasks import load_task

    body = [ln for ln in load_task(task_dir).oracle_script.read_text().splitlines()
            if ln.strip() and not ln.startswith("#") and not ln.startswith("set ")]
    body = [re.sub(r"^python3? ", "python3 ", ln) for ln in body]
    (dst / "solve.sh").write_text("\n".join([
        "#!/bin/bash",
        "# Reference solution. Runs in the agent container and drives the robot only through the robo socket",
        "# ($ROBOUSE_SOCKET), like an agent would. vendor/ holds the robouse oracle code (and, for Meta-World,",
        "# the scripted expert policy); none of it is visible to agents.",
        "set -euo pipefail",
        'export PYTHONPATH="$(cd "$(dirname "$0")" && pwd)/vendor${PYTHONPATH:+:$PYTHONPATH}"',
        *body,
        "",
    ]))
    (dst / "solve.sh").chmod(0o755)


def export_task(task_dir: Path, tasks_out: Path, noop: bool = False) -> str:
    from robouse.tasks import load_task

    task = load_task(task_dir)
    toml = task.meta
    if "robouse" not in toml:
        raise ValueError(f"{task_dir}: task has no robouse block")
    tid = toml["robouse"].get("id") or task_dir.name
    dst = tasks_out / tid
    if dst.exists():
        shutil.rmtree(dst)
    (dst / "environment").mkdir(parents=True)
    (dst / "task.md").write_text(task_md(toml, task.instruction))
    env = dst / "environment"
    shutil.copy2(TEMPLATES / "environment" / "Dockerfile", env / "Dockerfile")
    shutil.copy2(SRC / "agent_cli.py", env / "robo")
    robo = env / "robo"
    robo.write_text("#!/usr/bin/env python3\n" + robo.read_text())
    robo.chmod(0o755)
    (env / "docker-compose.yaml").write_text(compose(toml, _sim_task_md(toml)))
    shutil.copytree(TEMPLATES / "verifier", dst / "verifier")
    write_oracle(task_dir, toml, dst / "oracle", noop)
    return tid


def write_bundle_files(out: Path, ids: list[str], suites: list[str]) -> None:
    (out / "benchmark.yaml").write_text(f"""\
# benchmark.yaml — BenchFlow benchmark descriptor for robouse (generated by robouse/benchflow/export.py)
name: robouse
description: "robouse — agent as a policy: an agent harness drives a simulated robot only through the `robo` CLI; a trusted episode server judges the physical outcome"
url: https://github.com/benchflow-ai/robouse
author: BenchFlow
converted_by: BenchFlow

# ── Tasks ────────────────────────────────────────────────────────────
tasks:
  count: {len(ids)}
  categories: 1             # robotics / manipulation
  tags: [robotics, simulation, mujoco, agent-as-policy, {", ".join(suites)}]
  splits:
    main: {len(ids)}

# ── Conversion ───────────────────────────────────────────────────────
conversion:
  script: robouse/benchflow/export.py
  source_format: robouse task folders (task.md with a robouse block)
  has_oracle_solutions: true      # oracle/solve.sh: scripted controllers through the robo socket
  docker_image_pinned: false      # python:3.12-slim-bookworm + pinned pip requirements (runtime/requirements-sim.txt)

# ── Verification ─────────────────────────────────────────────────────
verification:
  method: trusted-simulator       # episode server in the `simulator` service judges success from physical state
  reward: binary                  # 1 if the episode server judged success, else 0
  aggregation: mean
  notes: "verifier.service = simulator; the agent container has only the robo client and a read-only socket volume"

# ── Parity ───────────────────────────────────────────────────────────
parity:
  end_to_end:
    agent: oracle
    notes: "see robouse/docs/benchflow.md for recorded oracle / no-op / model runs"
""")
    configs = {
        "robouse-oracle.yaml": ("Sanity job: every task's oracle/solve.sh must score 1.0.",
                                "agent: oracle\n"),
        "robouse-claude.yaml": ("Claude Code as the robot policy (needs ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN).",
                                "agent: claude\nmodel: claude-opus-5-5\n"),
        "robouse-codex.yaml": ("Codex as the robot policy (needs OPENAI_API_KEY / CODEX_API_KEY or host login).",
                               "agent: codex\nmodel: gpt-6-astra\n"),
    }
    for name, (doc, agent) in configs.items():
        stem = name.removesuffix(".yaml")
        (out / name).write_text(
            f"# bench eval run --config {name}   (run from this directory)\n# {doc}\n"
            f"tasks_dir: tasks\njobs_dir: jobs/{stem}\n{agent}environment: docker\n"
            "concurrency: 1   # tasks share the robouse-sim image tag, which BenchFlow removes after each trial\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks", required=True, nargs="+", help="task folders, suite folders, or the tasks/ root")
    ap.add_argument("--out", required=True, help="output bundle directory")
    ap.add_argument("--noop-oracle", action="store_true", help="write a do-nothing oracle (negative control)")
    ap.add_argument("--filter", default="", help="comma-separated substrings; keep tasks whose id matches one")
    a = ap.parse_args(argv)
    out = Path(a.out).resolve()
    tasks = [t for root in a.tasks for t in find_tasks(Path(root).resolve())]
    if a.filter:
        keys = [k for k in a.filter.split(",") if k]
        tasks = [t for t in tasks if any(k in t.name for k in keys)]
    if not tasks:
        print("no tasks found", file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)
    write_runtime(out)
    ids, suites = [], set()
    for t in tasks:
        ids.append(export_task(t, out / "tasks", a.noop_oracle))
        from robouse.tasks import load_task

        suites.add(load_task(t).metadata.get("suite", "robouse"))
        print("exported", ids[-1])
    write_bundle_files(out, ids, sorted(suites))
    print(f"{len(ids)} task(s) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
