"""ASPIRE's skill library in Robo Use: a per-trial copy, or an opt-in folder that persists across a suite's trials.

ASPIRE's library is the Markdown files of `.claude/skills/iterative-debugging/skills/` (grasp.md, transport.md, ...):
entries a coordinator promotes after a verifier has reproduced a fix from them, in ASPIRE's trigger, code and evidence
form. Every trial starts from a copy in its workspace; the trial's broker copies the library out of the workspace when
practice ends, and the trial folder keeps that copy (`aspire/library-after/`).

With ROBOUSE_ASPIRE_LIBRARY set, the copy comes from that folder and what the trial's coordinator changed goes back
into it when the trial ends, so later trials of the suite start from what earlier ones promoted, as later tasks of an
ASPIRE campaign do. The folder:

  library.json            the record: ASPIRE commit, and per trial its task, practice scenes, library hashes, changes
  skills/                 the library (seeded from ASPIRE's own at the pinned commit when the folder is new)
  tasks/<benchmark>/<suite>/task_<id>/   the program each task selected (fix_code.py, evosearch_best_code.py) and its
                          findings: ASPIRE's evaluation reuses a task's selected program on every held-out seed (only
                          a program the program contract accepts: one it refuses could never run)
  conflicts/<trial>/      a trial's version of a file that another trial changed meanwhile (concurrent trials)

Write-back is per file and under a lock: a file this trial changed or added is written when the folder still holds the
version the trial started from; otherwise the trial's version goes to conflicts/ and the folder keeps the other. A file
the trial's copy no longer has stays in the folder. Nothing is written back from a trial whose scored verdict is not a
verified result (signed, no integrity failure), and the skill files only when the trial's own ASPIRE verifier reported
"verified" for the task, as ASPIRE promotes only verified entries; library.json records each trial's harness and
model, and a task's program is reused only by the harness and model that selected it unless asked for.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .workspace import programs

UPSTREAM = Path(__file__).with_name("upstream")
ASPIRE_REPO = "https://github.com/NVlabs/ASPIRE"
ASPIRE_COMMIT = "fa00f0ef2bc1d91d594b9aa502c22133c9f538f7"
SEED_SKILLS = UPSTREAM / "claude" / "skills" / "iterative-debugging" / "skills"
FORMAT = "robouse-aspire-library"
# what a task's results folder keeps: the selected program, its versions, and the curation record
TASK_FILES = (".py", ".md", ".json")
# folders of recorded runs inside a task's folder (practice runs, held-out runs, evosearch evaluations): the trial
# folder keeps them; the library keeps the task's text record only
RUN_FOLDERS = frozenset({"debug", "validation", "eval", "logs", "snapshot", "media", "trace", "source", "episode"})


def now() -> str:
    return datetime.now(UTC).isoformat()


def skill_library_sha(directory: Path) -> str:
    """ASPIRE's library hash (campaign.skill_library_sha at the pinned commit): sha256 over the sorted relative paths
    and contents of every .md file but README.md, first 16 hex digits. skill_report.json records the same value."""
    digest = hashlib.sha256()
    if not directory.is_dir():
        return digest.hexdigest()[:16]
    for path in sorted(p for p in directory.rglob("*.md") if p.name != "README.md"):
        digest.update(str(path.relative_to(directory)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def file_hashes(directory: Path) -> dict[str, str]:
    """{relative path: sha256} of the regular files under `directory` (links skipped)."""
    out: dict[str, str] = {}
    if not directory.is_dir():
        return out
    for p in sorted(directory.rglob("*")):
        if p.is_file() and not p.is_symlink():
            out[str(p.relative_to(directory))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def scene_id(family: tuple[str, str, int] | list, scene: Any) -> str:
    """One practised or scored scene of a task (its campaign names: BENCHMARK, SUITE, TASK_ID), as the record keeps
    it."""
    return json.dumps([*family, scene])


class Library:
    """The library a trial starts from. `path` None: ASPIRE's own library, copied for this trial only."""

    def __init__(self, path: Path | None):
        self.path = Path(path).expanduser().resolve() if path else None

    @property
    def persistent(self) -> bool:
        return self.path is not None

    @property
    def skills(self) -> Path:
        return self.path / "skills" if self.path is not None else SEED_SKILLS

    @contextmanager
    def locked(self) -> Iterator[None]:
        if self.path is None:
            yield
            return
        self.path.mkdir(parents=True, exist_ok=True)
        with open(self.path / ".lock", "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def prepare(self) -> None:
        """A new folder gets ASPIRE's library and an empty record."""
        if self.path is None:
            return
        with self.locked():
            if not (self.path / "skills").is_dir() or not any((self.path / "skills").iterdir()):
                shutil.copytree(SEED_SKILLS, self.path / "skills", dirs_exist_ok=True)
            if not (self.path / "library.json").is_file():
                self._write_manifest(
                    {
                        "format": FORMAT,
                        "version": 1,
                        "aspire": {"repo": ASPIRE_REPO, "commit": ASPIRE_COMMIT},
                        "created_at": now(),
                        "seeded_from": f"ASPIRE's .claude/skills/iterative-debugging/skills/ at {ASPIRE_COMMIT[:12]}",
                        "trials": [],
                    }
                )

    def manifest(self) -> dict:
        if self.path is None or not (self.path / "library.json").is_file():
            return {"trials": []}
        try:
            return json.loads((self.path / "library.json").read_text())
        except (OSError, ValueError):
            return {"trials": []}

    def _write_manifest(self, data: dict) -> None:
        assert self.path is not None
        tmp = self.path / "library.json.tmp"
        tmp.write_text(json.dumps(data, indent=2) + "\n")
        tmp.replace(self.path / "library.json")

    def practised(self) -> set[str]:
        """Every scene an earlier trial practised on (scene_id strings)."""
        out: set[str] = set()
        for t in self.manifest().get("trials") or []:
            out.update((t.get("practice") or {}).get("scene_ids") or [])
        return out

    def task_dir(self, family: tuple[str, str, int]) -> Path | None:
        if self.path is None:
            return None
        b, s, i = family
        return self.path / "tasks" / b / s / f"task_{i}"

    def program_source(self, family: tuple[str, str, int], name: str) -> dict | None:
        """Which trial selected the task's program `name` (its trial, harness and model), from the record."""
        for t in self.manifest().get("trials") or []:
            if list(t.get("family") or []) == list(family) and name in (
                (t.get("task_results") or {}).get("selected") or []
            ):
                return {k: t.get(k) for k in ("trial", "harness", "model", "written_at")}
        return None

    def selected_program(self, family: tuple[str, str, int], name: str) -> Path | None:
        """The program (`fix_code.py` or `evosearch_best_code.py`) an earlier trial selected for this task."""
        d = self.task_dir(family)
        p = d / name if d is not None else None
        return p if p is not None and p.is_file() else None

    def copy_skills_to(self, dest: Path) -> dict[str, str]:
        """Copy the library into a workspace; returns the hashes it started from."""
        with self.locked():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(self.skills, dest)
            return file_hashes(dest)

    def copy_task_results_to(self, family: tuple[str, str, int], dest: Path) -> list[str]:
        """An earlier trial's results for this task (its program, versions and findings) into `dest`, where ASPIRE's
        evosearch looks for the fix loop's fix_code.py."""
        src = self.task_dir(family)
        if src is None or not src.is_dir():
            return []
        with self.locked():
            dest.mkdir(parents=True, exist_ok=True)
            copied = []
            for p in sorted(src.rglob("*")):
                rel = p.relative_to(src)
                if rel.parts and rel.parts[0] == "trials":
                    continue
                if p.is_file() and not p.is_symlink() and p.suffix in TASK_FILES:
                    (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(p, dest / rel)
                    copied.append(str(rel))
            return copied

    def write_back(
        self,
        entry: dict,
        start: dict[str, str],
        after_dir: Path,
        task_results: Path | None,
        family: tuple[str, str, int],
        skills_withheld: str | None = None,
    ) -> dict:
        """Merge this trial's library into the folder and append its record. Returns what changed. With
        `skills_withheld` (why), the skill files are not merged: what the trial changed is listed as withheld."""
        assert self.path is not None
        trial = str(entry.get("trial") or "trial")
        after = file_hashes(after_dir)
        out: dict[str, Any] = {
            "changed": [],
            "conflicts": [],
            "not_deleted": [],
            "sha_before": entry.get("library_sha_before"),
        }
        with self.locked():
            current = file_hashes(self.skills)
            for rel in sorted(set(start) | set(after)):
                a, b, c = start.get(rel), after.get(rel), current.get(rel)
                if b == a or c == b:
                    continue
                if skills_withheld:
                    out.setdefault("withheld", []).append(rel)
                elif b is None:
                    # a file the trial's copy lacks is never removed from the library: a moved or lost folder in the
                    # workspace must not empty it (ASPIRE's entries are sections of files, retired in place)
                    out["not_deleted"].append(rel)
                elif c == a:
                    target = self.skills / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(after_dir / rel, target)
                    out["changed"].append(rel)
                else:
                    keep = self.path / "conflicts" / trial / rel
                    keep.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(after_dir / rel, keep)
                    out["conflicts"].append(rel)
            if skills_withheld:
                out["skills_withheld"] = skills_withheld
            saved = self._save_task_results(trial, family, task_results)
            out["sha_after"] = skill_library_sha(self.skills)
            out["task_results"] = saved
            m = self.manifest()
            m.setdefault("trials", []).append({**entry, **out, "written_at": now()})
            self._write_manifest(m)
        return out

    def _save_task_results(self, trial: str, family: tuple[str, str, int], src: Path | None) -> dict:
        """Keep the trial's results under tasks/.../trials/<trial>/; the first selected program of a task becomes the
        task's (as ASPIRE never redoes a task that has one)."""
        d = self.task_dir(family)
        if d is None or src is None or not src.is_dir():
            return {}
        mine = d / "trials" / trial
        files = []
        for p in sorted(src.rglob("*")):
            rel = p.relative_to(src)
            if any(part in RUN_FOLDERS for part in rel.parts[:-1]):
                continue
            if p.is_file() and not p.is_symlink() and p.suffix in TASK_FILES:
                (mine / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, mine / rel)
                files.append(str(rel))
        promoted, refused = [], []
        for name in ("fix_code.py", "evosearch_best_code.py"):
            if not (src / name).is_file() or (d / name).exists():
                continue
            try:  # a program the contract refuses can never run: later trials of the task run their own Stage 1
                programs.validate((src / name).read_text())
            except programs.ProgramRejected as e:
                refused.append({"program": name, "why": str(e)})
                continue
            d.mkdir(parents=True, exist_ok=True)
            for kept in files:
                if not (d / kept).exists():
                    (d / kept).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src / kept, d / kept)
            promoted.append(name)
        out: dict[str, Any] = {
            "kept": f"tasks/{family[0]}/{family[1]}/task_{family[2]}/trials/{trial}",
            "selected": promoted,
        }
        if refused:
            out["not_selected"] = refused
        return out
