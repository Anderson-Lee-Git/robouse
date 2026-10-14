"""The task is the task.md body: the agent gets it as its prompt, not as a file in its workspace, and robouse reads
only task.md folders (the older task.toml + instruction.md layout gets a plain message naming BenchFlow's converter)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fakes import gateway_registry

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


@pytest.mark.parametrize(
    "harness,model",
    [
        ("mini-swe-agent", ""),
        ("dimcode", ""),
        ("codex", ""),
        ("claude-code", ""),
        ("codex", "stub-responses/some-model"),  # Codex through the gateway needs a Responses API, which glm lacks
        ("claude-code", "glm/glm-5.3"),
        ("show-harness", "stub-responses/vlm"),  # a model that reads images: glm/glm-5.3 is refused for it
    ],
)
def test_a_harness_puts_no_copy_of_the_prompt_in_the_workspace(harness, model, tmp_path, monkeypatch) -> None:
    """The workspace holds only robouse's internals (.robouse/) and observations/; the task reaches the agent only as
    its prompt (mini-swe-agent's harness used to write it to .robouse/task.txt as well)."""
    import os
    import shutil
    from types import SimpleNamespace

    from robouse import harnesses
    from robouse.harnesses import models
    from robouse.runner.trial import _make_workspace

    # a model gateway stand-in: the real one starts a LiteLLM proxy for the trial (harnesses/gateway.py)
    gw = SimpleNamespace(url="http://127.0.0.1:9", key="gw", model="m", stats=None, stop=None, stop_file=None)
    monkeypatch.setattr(harnesses, "_gateway", lambda ref, env, protocol: gw)
    # and a provider registry stand-in with BenchFlow's glm entry and a Responses provider, so the test runs without
    # the llm extra (BenchFlow)
    monkeypatch.setattr(models, "provider_registry", gateway_registry)
    monkeypatch.setenv("ROBOUSE_CACHE_DIR", str(tmp_path / "cache"))  # harness homes go to the cache
    stubs = tmp_path / "bin"  # the agent programs only need to exist: nothing is launched
    stubs.mkdir()
    for exe, body in (
        ("claude", ""),
        ("mini", ""),
        ("codex", '[ "$1" = login ] && echo "{}" > "$CODEX_HOME/auth.json"\n'),  # what `codex login` leaves
        ("dimcode", ""),
    ):
        (stubs / exe).write_text(f"#!/bin/sh\n{body}exit 0\n")
        (stubs / exe).chmod(0o755)
    monkeypatch.setenv("ROBOUSE_DIMCODE", str(stubs / "dimcode"))
    monkeypatch.setenv("PATH", f"{stubs}:{os.environ.get('PATH', '')}")
    for var in ("GLM_API_KEY", "STUB_RESPONSES_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.setenv(var, "not-a-real-key")
    task = load_task(ARC)
    ws = _make_workspace(task)
    try:
        launch = harnesses.build(harness, model, task.instruction, ws, task, {"PATH": os.environ.get("PATH", "")})
        assert any(task.instruction.strip() in str(arg) for arg in launch.cmd)  # the prompt
        entries = sorted(p.relative_to(ws) for p in ws.rglob("*"))
        assert all(e.parts[0] in (".robouse", "observations") for e in entries), entries
        marker = task.instruction.strip()[:80]
        copies = [p for p in ws.rglob("*") if p.is_file() and marker in p.read_text(errors="replace")]
        assert not copies, copies
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def test_mini_swe_agent_is_found_where_pip_puts_it_or_named_for_install(tmp_path, monkeypatch) -> None:
    """mini-swe-agent is not a dependency of robouse. `pip install mini-swe-agent` into Robo Use's environment puts
    `mini` next to its Python, which is on PATH only when the environment is activated: the harness finds it there too.
    Without it anywhere, the harness names the package to install, before any model gateway starts."""
    import sys
    from types import SimpleNamespace

    from robouse import harnesses
    from robouse.harnesses import models

    started: list = []
    gw = SimpleNamespace(url="http://127.0.0.1:9", key="gw", model="m", stats=None, stop=None, stop_file=None)
    monkeypatch.setattr(harnesses, "_gateway", lambda ref, env, protocol: started.append(ref) or gw)
    monkeypatch.setattr(models, "provider_registry", gateway_registry)
    venv = tmp_path / "venv" / "bin"
    venv.mkdir(parents=True)
    monkeypatch.setattr(sys, "executable", str(venv / "python"))
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "ws" / ".robouse").mkdir(parents=True)

    def build():
        return harnesses.build("mini-swe-agent", "glm/glm-5.3", "move", tmp_path / "ws", None, {"PATH": "/usr/bin"})

    with pytest.raises(RuntimeError, match=r"no `mini` on PATH, .*\(pip install mini-swe-agent\)"):
        build()
    assert started == []
    (venv / "mini").write_text("#!/bin/sh\nexit 0\n")
    (venv / "mini").chmod(0o755)
    assert build().cmd[0] == str(venv / "mini") and len(started) == 1


def test_doctor_and_the_gateway_find_litellm_next_to_this_python(tmp_path, monkeypatch, capsys) -> None:
    """The llm extra puts `litellm` next to Robo Use's Python, which is on PATH only when the environment is activated:
    the model gateway starts it from there, and `robouse doctor` reports it from there too (it looked only on PATH)."""
    import sys

    from robouse.cli import main
    from robouse.core import gl
    from robouse.harnesses import gateway

    venv = tmp_path / "venv" / "bin"
    venv.mkdir(parents=True)
    monkeypatch.setattr(sys, "executable", str(venv / "python"))
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    monkeypatch.setattr(gl, "auto_select", lambda: None)
    monkeypatch.setattr(gl, "probe", lambda p=None, python=None: None)
    assert gateway.litellm_exe() is None
    assert main(["doctor"]) == 0
    missing = "-- model gateway (provider-prefixed models) (`litellm`: pip install 'robouse[llm]')"
    assert missing in capsys.readouterr().out
    (venv / "litellm").write_text("#!/bin/sh\nexit 0\n")
    (venv / "litellm").chmod(0o755)
    assert gateway.litellm_exe() == str(venv / "litellm")
    assert main(["doctor"]) == 0
    assert f"ok model gateway (provider-prefixed models) ({venv / 'litellm'})" in capsys.readouterr().out
