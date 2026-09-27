"""Task folders in BenchFlow's native task format.

  <task>/task.md            YAML frontmatter (schema_version, task, metadata, agent, verifier, robouse) + the
                            instruction the agent reads as the markdown body
  <task>/oracle/solve.sh    reference solution; must score 1.0
  <task>/verifier/test.sh   turns the episode server's verdict into reward.txt

The `robouse:` block names the backend and its parameters (env, seed, budgets, scoring and observation modes,
and for tabletop tasks the `scenario`). `write_task` writes this layout; adapters use it.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SCHEMA_VERSION = "1.3"


@dataclass
class Task:
    path: Path
    meta: dict  # the frontmatter
    body: str = field(default="")

    @property
    def id(self) -> str:
        return self.meta.get("robouse", {}).get("id") or self.path.name

    @property
    def spec(self) -> dict:
        s = dict(self.meta.get("robouse", {}))
        s.setdefault("id", self.path.name)
        return s

    @property
    def instruction(self) -> str:
        return self.body

    @property
    def agent_timeout_s(self) -> float:
        return float(self.meta.get("agent", {}).get("timeout_sec", 900))

    @property
    def metadata(self) -> dict:
        return self.meta.get("metadata", {})

    @property
    def oracle_script(self) -> Path:
        p = self.path / "oracle" / "solve.sh"
        return p if p.exists() else self.path / "solution" / "solve.sh"

    @property
    def verifier_script(self) -> Path:
        p = self.path / "verifier" / "test.sh"
        return p if p.exists() else self.path / "tests" / "test.sh"


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        raise ValueError("task.md has no YAML frontmatter")
    _, fm, body = text.split("---", 2)
    return yaml.safe_load(fm) or {}, body.lstrip("\n")


def load_task(path: str | Path) -> Task:
    p = Path(path).resolve()
    if (p / "task.md").exists():
        meta, body = _split_frontmatter((p / "task.md").read_text())
        return Task(p, meta, body)
    # legacy layout (task.toml + instruction.md), read only until every folder is migrated
    t = tomllib.loads((p / "task.toml").read_text())
    meta = {"schema_version": SCHEMA_VERSION, "task": t.get("task", {}), "metadata": t.get("metadata", {}),
            "agent": t.get("agent", {}), "verifier": t.get("verifier", {}), "robouse": t.get("robouse", {})}
    return Task(p, meta, (p / "instruction.md").read_text())


def find_tasks(root: str | Path) -> list[Task]:
    root = Path(root)
    dirs = {p.parent for p in root.rglob("task.md")} | {p.parent for p in root.rglob("task.toml") if (p.parent / "instruction.md").exists()}
    return [load_task(d) for d in sorted(dirs) if "_legacy" not in d.parts]


def write_task(d: Path, meta: dict, instruction: str, oracle_sh: str, verifier_sh: str) -> None:
    """Write one task folder in BenchFlow's native layout."""
    d = Path(d)
    (d / "oracle").mkdir(parents=True, exist_ok=True)
    (d / "verifier").mkdir(parents=True, exist_ok=True)
    fm = {"schema_version": SCHEMA_VERSION, **{k: meta[k] for k in ("task", "metadata", "agent", "verifier", "robouse") if k in meta}}
    text = "---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, width=10**6) + "---\n\n" + instruction.lstrip("\n")
    (d / "task.md").write_text(text)
    for rel, body in (("oracle/solve.sh", oracle_sh), ("verifier/test.sh", verifier_sh)):
        f = d / rel
        f.write_text(body)
        f.chmod(0o755)


def to_native(d: Path, keep_legacy: bool = False) -> None:
    """Rewrite a task folder written in the older layout (task.toml, instruction.md, solution/, tests/) as task.md +
    oracle/ + verifier/. The older files are removed unless keep_legacy is set."""
    import shutil

    d = Path(d)
    if not (d / "task.toml").exists():
        return
    t = load_task(d)
    old_oracle = (d / "solution" / "solve.sh").read_text()
    old_verifier = (d / "tests" / "test.sh").read_text()
    write_task(d, t.meta, t.body, old_oracle, old_verifier)
    if not keep_legacy:
        for name in ("task.toml", "instruction.md"):
            (d / name).unlink(missing_ok=True)
        for name in ("solution", "tests"):
            shutil.rmtree(d / name, ignore_errors=True)
