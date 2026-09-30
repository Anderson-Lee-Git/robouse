"""Code-quality metrics for a checkout: lines of code, duplicated code, module count.

    python tools/metrics.py [--repo .] [--json]

Lines of code are non-blank, non-comment lines of Python. Duplicated code: every window of 6 consecutive normalised
code lines (whitespace collapsed; docstrings and comments dropped) under src/ that also appears elsewhere under src/
marks its lines as duplicated; the figure is the number of such lines.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import tokenize
from collections import defaultdict
from pathlib import Path

WINDOW = 6


def code_lines(path: Path) -> list[tuple[int, str]]:
    """(line number, normalised text) of the code lines of a Python file, without comments and docstrings."""
    src = path.read_text(errors="replace")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    doc_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(getattr(first, "value", None), ast.Constant)
                and isinstance(first.value.value, str)
            ):
                doc_lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    comment_only: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT and not tok.line[: tok.start[1]].strip():
                comment_only.add(tok.start[0])
    except (tokenize.TokenError, IndentationError):
        pass
    out = []
    for i, line in enumerate(src.splitlines(), 1):
        s = (
            " ".join(line.split("#", 1)[0].split())
            if "#" in line and "'" not in line and '"' not in line
            else " ".join(line.split())
        )
        if s and i not in doc_lines and i not in comment_only:
            out.append((i, s))
    return out


def measure(repo: Path) -> dict:
    groups = {
        "src": repo / "src",
        "tests": repo / "tests",
        "scripts": repo / "scripts",
        "tools": repo / "tools",
        "adapters": repo / "adapters",
    }
    res: dict = {"loc": {}, "files": {}}
    for name, root in groups.items():
        files = [p for p in root.rglob("*.py") if "__pycache__" not in p.parts] if root.exists() else []
        res["files"][name] = len(files)
        res["loc"][name] = sum(len(code_lines(p)) for p in files)
    src_files = sorted(p for p in (repo / "src").rglob("*.py") if "__pycache__" not in p.parts)
    res["modules"] = len(src_files)
    res["largest_modules"] = sorted(
        ((str(p.relative_to(repo)), len(code_lines(p))) for p in src_files), key=lambda x: -x[1]
    )[:10]
    windows: dict[str, list[tuple[Path, int]]] = defaultdict(list)
    lines_of: dict[Path, list[tuple[int, str]]] = {}
    for p in src_files:
        cl = lines_of[p] = code_lines(p)
        for k in range(len(cl) - WINDOW + 1):
            chunk = "\n".join(t for _, t in cl[k : k + WINDOW])
            if len(chunk) < 120:  # skip windows of trivial lines (closing brackets, returns)
                continue
            windows[hashlib.sha1(chunk.encode()).hexdigest()].append((p, k))
    dup: set[tuple[Path, int]] = set()
    for locs in windows.values():
        if len(locs) > 1:
            for p, k in locs:
                dup.update((p, lines_of[p][j][0]) for j in range(k, k + WINDOW))
    res["duplicated_lines_src"] = len(dup)
    res["duplicated_pct_src"] = round(100 * len(dup) / max(1, res["loc"]["src"]), 2)
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    m = measure(a.repo.resolve())
    print(json.dumps(m, indent=1) if a.json else "\n".join(f"{k}: {v}" for k, v in m.items()))


if __name__ == "__main__":
    main()
