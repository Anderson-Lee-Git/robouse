"""Regression test for CB-01 (bug hunt, 2026-09-30): an agent that rewrote episode/result.json after `robo done` scored
1, and could read the oracle token from the episode server's environment.

Reproduction, as filed: a stand-in harness finds the episode server's run folder, calls `robo done`, sets "success": true
in <run-dir>/result.json and exits; the verifier copied the forged verdict (reward 1). Here the scripted agent does the
same and more (it also looks for the token in the server's environment), and the trial must score 0.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("mujoco")

from robouse import harnesses
from robouse.harnesses import Launch
from robouse.runner import run_trial
from robouse.runner.sandbox import bwrap_works
from robouse.tasks import load_task

ROOT = Path(__file__).resolve().parents[1]

CHEAT = r"""#!/bin/bash
# a scripted cheating agent: claim success without moving, then forge the verdict and hunt for the oracle token
robo done "forged" >/dev/null
sleep 1
for f in {job}/*/episode/result.json; do
  python3 - "$f" <<'EOF'
import json, sys
p = sys.argv[1]
r = json.load(open(p))
r["success"] = True
json.dump(r, open(p, "w"))
EOF
done
found=0; server=0
for p in /proc/[0-9]*; do
  grep -qa -- "--socket" $p/cmdline 2>/dev/null && grep -qa -- "$ROBOUSE_SOCKET" $p/cmdline 2>/dev/null || continue
  server=1
  tr '\0' '\n' < $p/environ 2>/dev/null | grep -q ORACLE_TOKEN && found=1
done
echo "token_seen=$found" > {report}
echo "server_found=$server" >> {report}
cat {task}/oracle/solve.sh >/dev/null 2>&1 && echo "oracle_readable=1" >> {report} || echo "oracle_readable=0" >> {report}
"""


def _harness(monkeypatch, script: Path) -> None:
    def cheat(model, prompt, workspace, task, env) -> Launch:
        inside = workspace / ".robouse" / script.name  # in the workspace, which is all the sandbox leaves of /tmp
        inside.write_text(script.read_text())
        return Launch(["bash", str(inside)], env, notes={"model": "none"})

    monkeypatch.setitem(harnesses.HARNESSES, "cheat", cheat)


def test_a_forged_verdict_scores_zero(tmp_path, monkeypatch) -> None:
    task = load_task(ROOT / "tasks" / "arc-style" / "arc-gravity")
    job, report = tmp_path / "job", tmp_path / "report.txt"
    script = tmp_path / "cheat.sh"
    script.write_text(CHEAT.format(job=job, report=report, task=task.path))
    _harness(monkeypatch, script)
    monkeypatch.setenv("ROBOUSE_SANDBOX", "0")  # the worst case: no sandbox at all
    res = run_trial(task, "cheat", "", job)
    assert res["reward"] == 0.0
    trial = json.loads((job / res["trial"] / "result.json").read_text())
    assert trial["verifier_result"]["rewards"]["reward"] == 0.0
    seen = dict(line.split("=") for line in report.read_text().split())
    if sys.platform.startswith("linux"):
        assert seen["server_found"] == "1"  # the agent did find the episode server's process ...
        assert seen["token_seen"] == "0"  # ... but the token reached the server on its stdin, not in its environment


@pytest.mark.skipif(not (sys.platform.startswith("linux") and bwrap_works()), reason="needs working bubblewrap on Linux")
def test_the_sandbox_hides_the_reference_solution_and_the_job(tmp_path, monkeypatch) -> None:
    task = load_task(ROOT / "tasks" / "arc-style" / "arc-gravity")
    job = tmp_path / "job"
    script = tmp_path / "peek.sh"
    script.write_text(
        f"robo done x; ls {job} | grep -q . && exit 3; cat {task.path}/oracle/solve.sh && exit 4; exit 5\n"
    )
    _harness(monkeypatch, script)
    res = run_trial(task, "cheat", "", job)
    trial = json.loads((job / res["trial"] / "result.json").read_text())
    assert trial["agent_return_code"] == 5, trial


def test_the_reference_solution_still_scores_one(tmp_path) -> None:
    res = run_trial(load_task(ROOT / "tasks" / "arc-style" / "arc-gravity"), "oracle", "", tmp_path / "job")
    assert res["reward"] == 1.0 and res["exception"] is None
