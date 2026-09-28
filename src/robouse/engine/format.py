"""robouse tasks as a BenchFlow task format.

A robouse task folder (``task.md`` with a ``robouse:`` block, ``oracle/solve.sh``, ``verifier/test.sh``) is
the source form. BenchFlow loads it through the ``benchflow.task_formats`` entry point, which calls
:meth:`RobouseTaskFormat.materialize` to write an ordinary BenchFlow task package:

    <out_root>/runtime-<hash>/          simulator image build context (shared by every task built from it)
      Dockerfile  requirements.txt  sim-entry.sh  robouse/src/robouse/   (this robouse package)
    <out_root>/tasks/<key>/<task-id>/   the native package; <key> hashes the task, the runtime and the options
      task.md                           schema 1.3: the robouse block moves to metadata.robouse; verifier.service
                                        is `simulator`
      environment/Dockerfile            agent (`main`) image: python + numpy + the `robo` client only
      environment/robo                  copy of robouse/agent_cli.py (standard library only)
      environment/docker-compose.yaml   `main` + trusted `simulator` service (embeds the task definition)
      verifier/{verifier.md,test.sh,verify.py}   runs in `simulator`
      oracle/solve.sh + oracle/vendor/  reference solution; drives the robot through the socket only

The build is deterministic for the same inputs and cached: a second load of an unchanged task reuses the
package. ``noop=True`` writes a negative-control oracle that only looks (`robo info`, `robo observe`) and
exits without `robo done`; it must score 0.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import yaml

from ..tasks import load_task

PKG = Path(__file__).resolve().parents[1]  # the robouse package
TEMPLATES = Path(__file__).resolve().parent / "templates"
FORMAT_VERSION = "2"
WALL_MARGIN_S = 900  # the episode clock starts when the simulator is up, before BenchFlow installs the harness
METAWORLD_VERSION = "3.1.1"  # the version pinned in templates/sim/requirements.txt
_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "bundled_tasks", "robocasa_episodes", "engine")


def _frontmatter(task_md: Path) -> dict | None:
    text = task_md.read_text()
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    meta = yaml.safe_load(parts[1])
    return meta if isinstance(meta, dict) else None


def is_robouse_task(task_dir: Path) -> bool:
    """A robouse source task: task.md whose frontmatter has a top-level `robouse:` block."""
    md = Path(task_dir) / "task.md"
    try:
        if not md.is_file():
            return False
        meta = _frontmatter(md)
    except (OSError, yaml.YAMLError):
        return False
    return bool(meta) and isinstance(meta.get("robouse"), dict)


def _tree_files(root: Path, ignore=_IGNORE) -> list[Path]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        skip = ignore(dirpath, dirnames + filenames)
        dirnames[:] = sorted(d for d in dirnames if d not in skip)
        out += [Path(dirpath) / f for f in sorted(filenames) if f not in skip]
    return out


def _hash_tree(h, root: Path, ignore=_IGNORE) -> None:
    for f in _tree_files(root, ignore):
        h.update(str(f.relative_to(root)).encode() + b"\0" + f.read_bytes() + b"\0")


def _atomic_dir(dst: Path, build) -> Path:
    """Build a directory in a temp sibling, then rename it into place (safe under concurrent loads)."""
    if dst.exists():
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{dst.name}.", dir=dst.parent))
    try:
        build(tmp)
        try:
            tmp.rename(dst)
        except OSError:
            if not dst.exists():
                raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return dst


# ---- simulator runtime ----------------------------------------------------------------------------------

def runtime_hash() -> str:
    h = hashlib.sha256(FORMAT_VERSION.encode())
    _hash_tree(h, PKG)
    _hash_tree(h, Path(__file__).resolve().parent, shutil.ignore_patterns("__pycache__", "*.pyc"))  # this module + templates
    return h.hexdigest()[:16]


def ensure_runtime(out_root: Path) -> Path:
    """The simulator build context for this robouse package (written once per package version/content)."""
    def build(d: Path) -> None:
        for name in ("Dockerfile", "requirements.txt", "sim-entry.sh"):
            shutil.copy2(TEMPLATES / "sim" / name, d / name)
        shutil.copytree(PKG, d / "robouse" / "src" / "robouse", ignore=_IGNORE)

    return _atomic_dir(Path(out_root) / f"runtime-{runtime_hash()}", build)


# ---- oracle vendoring -----------------------------------------------------------------------------------

def _metaworld_policies(dst: Path) -> None:
    """Copy Meta-World's scripted expert policies (pure numpy) to dst/metaworld/policies.

    From the installed `metaworld` package when there is one (found without importing it, so MuJoCo is not
    needed on the host), otherwise from the pinned wheel on PyPI (cached in ~/.cache/robouse/wheels).
    """
    import importlib.util

    pol = dst / "metaworld" / "policies"
    spec = importlib.util.find_spec("metaworld")
    src = Path(spec.submodule_search_locations[0]) / "policies" if spec and spec.submodule_search_locations else None
    if src is not None and (src / "__init__.py").exists():
        shutil.copytree(src, pol, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    else:
        cache = Path.home() / ".cache" / "robouse" / "wheels"
        cache.mkdir(parents=True, exist_ok=True)
        whl = next(iter(cache.glob(f"metaworld-{METAWORLD_VERSION}-*.whl")), None)
        if whl is None:
            with urllib.request.urlopen(f"https://pypi.org/pypi/metaworld/{METAWORLD_VERSION}/json", timeout=60) as r:
                files = json.load(r)["urls"]
            url = next(f["url"] for f in files if f["filename"].endswith(".whl"))
            whl = cache / url.rsplit("/", 1)[1]
            with urllib.request.urlopen(url, timeout=300) as r:
                whl.write_bytes(r.read())
        with zipfile.ZipFile(io.BytesIO(whl.read_bytes())) as z:
            for name in z.namelist():
                if name.startswith("metaworld/policies/") and name.endswith(".py"):
                    out = dst / name
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(z.read(name))
    (dst / "metaworld" / "__init__.py").write_text(
        '"""Vendored subset of Meta-World (MIT): only the scripted expert policies (numpy only)."""\n')


NOOP_SOLVE = """#!/bin/bash
# Negative control (noop oracle): look at the robot, never move it, exit without `robo done`.
# The verifier must close the episode itself (outcome agent_exited) and the reward must be 0.
set -euo pipefail
robo info
robo observe
"""


def _write_oracle(task, dst: Path, token: str, noop: bool) -> None:
    dst.mkdir(parents=True)
    if noop:
        (dst / "solve.sh").write_text(NOOP_SOLVE)
        (dst / "solve.sh").chmod(0o755)
        return
    vendor = dst / "vendor"
    shutil.copytree(PKG, vendor / "robouse", ignore=_IGNORE)
    if task.spec.get("backend") == "metaworld":
        _metaworld_policies(vendor)
    body = [ln for ln in task.oracle_script.read_text().splitlines()
            if ln.strip() and not ln.startswith("#") and not ln.startswith("set ")]
    body = [re.sub(r"^python3? ", "python3 ", ln) for ln in body]
    (dst / "solve.sh").write_text("\n".join([
        "#!/bin/bash",
        "# Reference solution. Runs in the agent container and drives the robot only through the robo socket",
        "# ($ROBOUSE_SOCKET), like an agent would. vendor/ holds the robouse oracle code (and, for Meta-World,",
        "# the scripted expert policies). BenchFlow hides /oracle from agents.",
        "set -euo pipefail",
        'export PYTHONPATH="$(cd "$(dirname "$0")" && pwd)/vendor${PYTHONPATH:+:$PYTHONPATH}"',
        f"export ROBOUSE_ORACLE_TOKEN={token}",
        *body,
        "",
    ]))
    (dst / "solve.sh").chmod(0o755)


# ---- the native package ---------------------------------------------------------------------------------

def _dump(d: dict) -> str:
    return yaml.safe_dump(d, sort_keys=False, allow_unicode=True, width=10**6)


def native_task_md(meta: dict, instruction: str) -> str:
    rb = meta["robouse"]
    task = dict(meta.get("task") or {})
    task.setdefault("name", f"robouse/{rb.get('id')}")
    metadata = {"author_name": "benchflow", **(meta.get("metadata") or {}), "robouse": rb}
    verifier_timeout = max(300, int((meta.get("verifier") or {}).get("timeout_sec", 0) or 0))
    fm = {
        "schema_version": "1.3",
        "task": task,
        "metadata": metadata,
        "agent": {"timeout_sec": int(float((meta.get("agent") or {}).get("timeout_sec", 900)))},
        "verifier": {"service": "simulator", "user": "root", "timeout_sec": verifier_timeout},
        "sandbox": {"cpus": 1, "memory_mb": 2048, "build_timeout_sec": 1800},
    }
    # the same preamble a local robouse run gives every harness
    from ..harnesses import PROMPT_PREFIX

    return "---\n" + _dump(fm) + "---\n\n" + PROMPT_PREFIX + instruction.strip() + "\n"


def sim_task_md(meta: dict) -> str:
    """The task definition the simulator needs (frontmatter only; the prompt is not in it)."""
    fm = {k: meta[k] for k in ("schema_version", "task", "metadata", "agent", "verifier", "robouse") if k in meta}
    return "---\n" + _dump(fm) + "---\n"


def compose(meta: dict, sim_context: str, token: str) -> str:
    # compose interpolates $VARS in values; `$$` is a literal dollar sign
    block = "\n".join("        " + ln.replace("$", "$$") for ln in sim_task_md(meta).rstrip().splitlines())
    agent_timeout = float((meta.get("agent") or {}).get("timeout_sec", 900))
    text = (TEMPLATES / "docker-compose.yaml").read_text()
    return (text.replace("__SIM_CONTEXT__", json.dumps(sim_context))
                .replace("__MAX_WALL_S__", str(int(agent_timeout + WALL_MARGIN_S)))
                .replace("__ORACLE_TOKEN__", token)
                .replace("__TASK_MD__", block))


def materialize(task_dir: Path, out_root: Path, *, noop: bool = False, seed: int | None = None,
                timeout: float | None = None, flat: bool = False) -> Path:
    """Write (or reuse) the native BenchFlow package for one robouse task and return its folder.

    noop: negative-control oracle. seed / timeout: override the task's seed and agent timeout (seconds).
    flat: write <out_root>/tasks/<task-id> (replacing an older copy) instead of the content-addressed cache
    layout, for a bundle meant to be moved or published; a flat package refers to the simulator runtime by a
    relative path inside out_root, so out_root can be moved as a whole.
    """
    task_dir, out_root = Path(task_dir).resolve(), Path(out_root).resolve()
    task = load_task(task_dir)
    if "robouse" not in task.meta:
        raise ValueError(f"{task_dir}: not a robouse task (no robouse: block in task.md)")
    meta = json.loads(json.dumps(task.meta))  # deep copy
    if seed is not None:
        meta["robouse"]["seed"] = int(seed)
    if timeout is not None:
        meta.setdefault("agent", {})["timeout_sec"] = int(timeout)
    runtime = ensure_runtime(out_root)
    h = hashlib.sha256(f"{FORMAT_VERSION}|{runtime.name}|noop={noop}|seed={seed}|timeout={timeout}".encode())
    _hash_tree(h, task_dir, shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
    key = h.hexdigest()[:16]
    parent = out_root / "tasks" if flat else out_root / "tasks" / key

    def write(pkg: Path) -> None:
        env = pkg / "environment"
        env.mkdir(parents=True)
        token = secrets.token_hex(16)
        (pkg / "task.md").write_text(native_task_md(meta, task.instruction))
        shutil.copy2(TEMPLATES / "agent.Dockerfile", env / "Dockerfile")
        (env / "robo").write_text("#!/usr/bin/env python3\n" + (PKG / "agent_cli.py").read_text())
        (env / "robo").chmod(0o755)
        # absolute in the cache (BenchFlow may stage a task copy elsewhere); relative in a movable bundle
        context = os.path.relpath(runtime, parent / task.id / "environment") if flat else str(runtime)
        (env / "docker-compose.yaml").write_text(compose(meta, context, token))
        shutil.copytree(TEMPLATES / "verifier", pkg / "verifier", ignore=shutil.ignore_patterns("__pycache__"))
        _write_oracle(task, pkg / "oracle", token, noop)
        (pkg / ".robouse-source.json").write_text(json.dumps(
            {"source": str(task_dir), "key": key, "runtime": runtime.name, "noop": noop, "seed": seed,
             "timeout": timeout, "format_version": FORMAT_VERSION}, indent=2))

    if flat:
        dst = parent / task.id
        marker = dst / ".robouse-source.json"
        if marker.exists() and json.loads(marker.read_text()).get("key") == key:
            return dst
        if dst.exists():
            shutil.rmtree(dst)
        return _atomic_dir(dst, write)
    return _atomic_dir(parent, lambda d: write(d / task.id)) / task.id


class RobouseTaskFormat:
    """BenchFlow task format (entry point `benchflow.task_formats: robouse`)."""

    name = "robouse"

    def detect(self, task_dir: Path) -> bool:
        return is_robouse_task(task_dir)

    def materialize(self, task_dir: Path, out_root: Path) -> Path:
        return materialize(task_dir, out_root)


def task_format_root() -> Path:
    """The cache BenchFlow uses for robouse packages (so `robouse run` and `bench eval run` share builds)."""
    try:
        from benchflow.task.formats import task_format_cache_root

        return task_format_cache_root() / RobouseTaskFormat.name
    except ImportError:
        return Path.home() / ".cache" / "benchflow" / "task-formats" / RobouseTaskFormat.name
