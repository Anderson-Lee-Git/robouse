"""The task is the task.md body: the agent gets it as its prompt, not as a file in its workspace, and robouse reads
only task.md folders (the older task.toml + instruction.md layout gets a plain message naming BenchFlow's converter)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from robouse.cli import main
from robouse.tasks import TaskFormatError, find_tasks, load_task

ARC = Path(__file__).resolve().parents[1] / "tasks" / "arc-style" / "arc-gravity"


def _older_layout(d: Path) -> Path:
    """arc-gravity written the old way: task.toml + instruction.md, solution/, tests/."""
    t = load_task(ARC)
    d.mkdir(parents=True)
    (d / "task.toml").write_text(f'[task]\nname = "robouse/{t.id}"\n\n[robouse]\nid = "{t.id}"\nbackend = "tabletop"\n')
    (d / "instruction.md").write_text(t.body)
    for sub, name, src in (("solution", "solve.sh", t.oracle_script), ("tests", "test.sh", t.verifier_script)):
        (d / sub).mkdir()
        (d / sub / name).write_text(src.read_text())
    return d


def test_the_older_layout_is_not_read(tmp_path, capsys) -> None:
    old = _older_layout(tmp_path / "suite" / "arc-gravity")
    with pytest.raises(TaskFormatError) as e:
        load_task(old)
    assert "is not a task.md folder" in str(e.value) and f"bench tasks migrate {old}" in str(e.value)
    assert find_tasks(tmp_path) == []  # skipped, and said so
    assert "skipped 1 folder(s)" in capsys.readouterr().err
    # `robouse tasks check` and `robouse run` say it plainly instead of a traceback
    assert main(["tasks", "check", str(old), "--no-run"]) == 1
    assert main(["run", "--task", str(old), "--harness", "noop", "--out", str(tmp_path / "job")]) == 2
    err = capsys.readouterr().err
    assert err.count("is not a task.md folder") == 2 and "--remove-legacy" in err and not (tmp_path / "job").exists()


def test_a_folder_without_task_md(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        load_task(tmp_path)


@pytest.mark.skipif(__import__("importlib").util.find_spec("mujoco") is None, reason="needs MuJoCo")
def test_the_prompt_is_the_task_md_body_and_the_workspace_has_no_copy(tmp_path, monkeypatch) -> None:
    from robouse import harnesses
    from robouse.harnesses import Launch
    from robouse.runner import run_trial

    seen: dict = {}
    listing = tmp_path / "ls.txt"

    def build(model, prompt, workspace, task, env) -> Launch:
        seen["prompt"] = prompt
        return Launch(["bash", "-c", f"find . -type f | sort > {listing}; robo done"], env, notes={"model": "none"})

    monkeypatch.setitem(harnesses.HARNESSES, "lister", build)
    monkeypatch.setenv("ROBOUSE_SANDBOX", "0")
    task = load_task(ARC)
    res = run_trial(task, "lister", "", tmp_path / "job")
    assert seen["prompt"] == task.body == (ARC / "task.md").read_text().split("---", 2)[2].lstrip("\n")
    files = listing.read_text().split()
    assert "./.robouse/bin/robo" in files and not any(f.endswith("instruction.md") for f in files)
    cfg = json.loads((tmp_path / "job" / res["trial"] / "config.json").read_text())
    assert {".robouse/bin/robo", "observations/"} <= set(cfg["workspace_files"])
    assert not any("instruction" in f for f in cfg["workspace_files"])
