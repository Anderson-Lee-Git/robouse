"""Every robouse import in the package resolves, including the ones inside functions that only run in one simulator
(a module move that misses one of those fails only when that code path runs)."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
PKG = SRC / "robouse"


def _exists(module: str) -> bool:
    rel = Path(*module.split("."))
    return (SRC / rel).with_suffix(".py").is_file() or (SRC / rel / "__init__.py").is_file()


def test_every_robouse_import_resolves() -> None:
    missing = []
    for f in sorted(PKG.rglob("*.py")):
        if "gpu/worker" in str(f):  # flat worker scripts on remote machines
            continue
        parts = list(f.relative_to(SRC).with_suffix("").parts)
        pkg = parts if parts[-1] == "__init__" else parts[:-1]
        if parts[-1] == "__init__":
            pkg = parts[:-1]
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.ImportFrom) and (node.level or (node.module or "").startswith("robouse")):
                base = pkg[: len(pkg) - node.level + 1] if node.level else []
                target = ".".join(base + ([node.module] if node.module else []))
                if not target.startswith("robouse"):
                    continue
                if _exists(target):
                    continue
                if not node.module and all(_exists(f"{target}.{a.name}") for a in node.names):
                    continue
                missing.append(f"{f.relative_to(SRC)}:{node.lineno} {target}")
    assert not missing, "\n".join(missing)
