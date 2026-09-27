"""Task folders.


  <task>/instruction.md   what the agent is told (includes how to use `robo`)
  <task>/solution/solve.sh  reference solution; must score 1.0
  <task>/tests/test.sh    verifier: turns the episode result into /logs/verifier/reward.txt
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Task:
    path: Path
    toml: dict

    @property
    def id(self) -> str:
        return self.toml.get("robouse", {}).get("id") or self.path.name

    @property
    def spec(self) -> dict:
        s = dict(self.toml.get("robouse", {}))
        s.setdefault("id", self.path.name)
        return s

    @property
    def instruction(self) -> str:
        return (self.path / "instruction.md").read_text()

    @property
    def agent_timeout_s(self) -> float:
        return float(self.toml.get("agent", {}).get("timeout_sec", 900))

    @property
    def metadata(self) -> dict:
        return self.toml.get("metadata", {})


def load_task(path: str | Path) -> Task:
    p = Path(path).resolve()
    return Task(p, tomllib.loads((p / "task.toml").read_text()))


def find_tasks(root: str | Path) -> list[Task]:
    return [load_task(p.parent) for p in sorted(Path(root).rglob("task.toml")) if (p.parent / "instruction.md").exists()]
