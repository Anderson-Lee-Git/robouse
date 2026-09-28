"""robouse tasks as a BenchFlow task format, on BenchFlow's embodied layer.

A robouse task folder (``task.md`` with a ``robouse:`` block, ``oracle/solve.sh``, ``verifier/test.sh``) is the
source form. BenchFlow loads it through the ``benchflow.task_formats`` entry point. The package layout, the agent
image, the compose topology (agent + trusted ``simulator`` sidecar), the physical verifier and seeded variants come
from `benchflow.embodied.sidecar.EmbodiedTaskFormat` (BenchFlow's docs/embodied.md). robouse supplies:

  - the simulator image: templates/sim/Dockerfile + requirements.txt + this robouse package (the backends);
  - the episode factory ``robouse.embodied:episode_from_task``;
  - the reference solutions: oracle/solve.sh with the robouse oracle code vendored (and, for Meta-World, the
    scripted expert policies), driving the robot only through the socket.

``materialize_variant(noop=True)`` writes a negative-control oracle that only looks (`robo info`, `robo observe`)
and exits without `robo done`; it must score 0. ``seed=N`` writes ``<task-id>--seed-N`` (``bench eval run --seeds``).
"""
from __future__ import annotations

import io
import json
import re
import shutil
import urllib.request
import zipfile
from pathlib import Path

from benchflow.embodied.sidecar import EmbodiedTaskFormat, vendor_embodied

from ..tasks import load_task

PKG = Path(__file__).resolve().parents[1]  # the robouse package
TEMPLATES = Path(__file__).resolve().parent / "templates"
METAWORLD_VERSION = "3.1.1"  # the version pinned in templates/sim/requirements.txt
_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "bundled_tasks", "robocasa_episodes", "engine")


def _asset_manifests() -> dict[str, Path]:
    """Provenance manifests of the robot meshes (the image downloads the files at build time)."""
    shipped = PKG / "assets_provenance"
    if shipped.is_dir():
        return {p.name: p for p in sorted(shipped.glob("*.json"))}
    root = PKG.parents[1] / "assets" / "menagerie"
    return {"menagerie.json": root / "provenance.json", "skydio_x2.json": root / "skydio_x2" / "PROVENANCE.json"}


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


class RobouseTaskFormat(EmbodiedTaskFormat):
    """BenchFlow task format (entry point `benchflow.task_formats: robouse`)."""

    name = "robouse"
    block_key = "robouse"
    episode_factory = "robouse.embodied:episode_from_task"
    format_version = "3"
    task_name_prefix = "robouse/"
    sim_cpus = "2"
    sim_memory = "3G"

    @property
    def prompt_prefix(self) -> str:  # the same preamble a local robouse run gives every harness
        from ..harnesses import PROMPT_PREFIX

        return PROMPT_PREFIX

    def runtime_hash_inputs(self) -> list[Path]:
        return [PKG, TEMPLATES, *_asset_manifests().values()]

    def build_runtime(self, dst: Path) -> None:
        for name in ("Dockerfile", "requirements.txt"):
            shutil.copy2(TEMPLATES / "sim" / name, dst / name)
        pkg = dst / "robouse" / "src" / "robouse"
        shutil.copytree(PKG, pkg, ignore=_IGNORE)
        prov = pkg / "assets_provenance"
        prov.mkdir(exist_ok=True)
        for name, src in _asset_manifests().items():
            if src.exists() and not (prov / name).exists():
                shutil.copy2(src, prov / name)

    def task_id(self, task_dir: Path, meta: dict) -> str:
        return load_task(task_dir).id

    def write_oracle(self, task_dir: Path, meta: dict, dst: Path, token: str) -> None:
        task = load_task(task_dir)
        dst.mkdir(parents=True)
        vendor = dst / "vendor"
        shutil.copytree(PKG, vendor / "robouse", ignore=_IGNORE)
        vendor_embodied(vendor)  # robouse's oracles import benchflow.embodied (the socket client)
        if task.spec.get("backend") == "metaworld":
            _metaworld_policies(vendor)
        extra = task.oracle_script.parent
        for f in sorted(extra.iterdir()):  # data the oracle reads (e.g. DexJoCo demo.json, BEHAVIOR plan.json)
            if f.name != "solve.sh" and f.is_file():
                shutil.copy2(f, dst / f.name)
        body = [ln for ln in task.oracle_script.read_text().splitlines()
                if ln.strip() and not ln.startswith("#") and not ln.startswith("set ")]
        body = [re.sub(r"^python3? ", "python3 ", ln) for ln in body]
        (dst / "solve.sh").write_text("\n".join([
            "#!/bin/bash",
            "# Reference solution. Runs in the agent container and drives the robot only through the robo socket",
            "# ($ROBO_SOCKET), like an agent would. vendor/ holds the robouse oracle code and BenchFlow's embodied",
            "# client (and, for Meta-World, the scripted expert policies). BenchFlow hides /oracle from agents.",
            "set -euo pipefail",
            'export PYTHONPATH="$(cd "$(dirname "$0")" && pwd)/vendor${PYTHONPATH:+:$PYTHONPATH}"',
            f"export ROBO_ORACLE_TOKEN={token}",
            *body,
            "",
        ]))
        (dst / "solve.sh").chmod(0o755)


def materialize(task_dir: Path, out_root: Path, *, noop: bool = False, seed: int | None = None,
                timeout: float | None = None, flat: bool = False) -> Path:
    """Write (or reuse) the native BenchFlow package for one robouse task and return its folder."""
    return RobouseTaskFormat().materialize_variant(task_dir, out_root, seed=seed, noop=noop, timeout=timeout, flat=flat)


def is_robouse_task(task_dir: Path) -> bool:
    return RobouseTaskFormat().detect(Path(task_dir))


def task_format_root() -> Path:
    """The cache BenchFlow uses for robouse packages (so `robouse run` and `bench eval run` share builds)."""
    from benchflow.task.formats import task_format_cache_root

    return task_format_cache_root() / RobouseTaskFormat.name
