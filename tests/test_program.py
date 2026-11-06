"""The program harnesses: code as policy, developed on fresh resets of the scored scene and scored on one explicit
submission, run once by the driver with no model in the loop.

Whole trials run a scripted stand-in for the coding agent (no model is called) on the light `cubepick` tasks: it uses
the workspace's own `robo-dev` and probes what a development run must not tell it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from robouse import harnesses
from robouse.harnesses import program

ROOT = Path(__file__).resolve().parents[1]
CUBEPICK = ROOT / "tasks" / "cubepick"

SOLVE = """
def solve(robo):
    for tick in range(60):
        s = robo.observe()["state"]
        if s["distance"] < 0.03:
            break
        dx = max(-0.1, min(0.1, float(s["cube_pos"][0]) - float(s["eef_pos"][0])))
        dy = max(-0.1, min(0.1, float(s["cube_pos"][1]) - float(s["eef_pos"][1])))
        moved = robo.act([dx, dy])
        if "episode" in moved:
            break
    return {"ticks": tick}
"""

AGENT = r'''
import json, os, subprocess, urllib.error, urllib.request
from pathlib import Path

ws = Path.cwd()
url = os.environ["ROBOUSE_PRACTICE_URL"].rstrip("/")
report = {
    "socket_env": os.environ.get("ROBOUSE_SOCKET"),
    "socket_file": (ws / ".robouse" / "socket").exists(),
    "driver_key": (ws / ".robouse" / "program" / "driver.key").exists(),
    "program_md": (ws / "PROGRAM.md").is_file(),
}
def call(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url + path, data=data), timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}
report["freeze"] = call("/freeze", {"by": "agent"})[0]
def dev(*args):
    r = subprocess.run(["robo-dev", *args], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr
(ws / "solution" / "solve.py").write_text(SOLVE)
report["look"] = dev("look")
report["run"] = dev("run", "--keyframes", "2")
report["summary"] = json.loads((ws / "dev-runs" / "0002" / "summary.json").read_text())
report["frames"] = sorted(p.name for p in (ws / "dev-runs" / "0002" / "frames").iterdir())
report["status"] = call("/status")
code, ep = call("/episodes", {"seed": 7})
report["episode_seed"] = ep.get("seed")
report["status_op"] = call(f"/episodes/{ep['id']}", {"req": {"op": "status"}})[1]
report["finish"] = call(f"/episodes/{ep['id']}/finish", {"op": "done"})[1]
report["result_file"] = call(f"/episodes/{ep['id']}/files/result.json")[0]
(ws / "bad.py").write_text("import os\ndef solve(robo):\n    return os.getcwd()\n")
report["bad"] = dev("submit", "bad.py")
report["nosolve"] = call("/submit", {"source": "x = 1\n"})
if SUBMIT:
    report["submit"] = dev("submit")
if GIVE_UP:
    report["give_up"] = dev("give-up", GIVE_UP)
(ws / "solution" / "solve.py").write_text("def solve(robo):\n    return 'the workspace file is never scored'\n")
print("PROGRAM-REPORT " + json.dumps(report), flush=True)
'''


def _scripted_agent(monkeypatch, submit: bool = True, give_up: str = "") -> None:
    def launch(agent, model, prompt, workspace, task, env):
        assert "PROGRAM.md" in prompt and "robo-dev submit" in prompt
        script = workspace / ".robouse" / "program" / "stand_in_agent.py"
        script.write_text(f"SOLVE = {SOLVE!r}\nSUBMIT = {submit!r}\nGIVE_UP = {give_up!r}\n" + AGENT)
        return harnesses.Launch([sys.executable, str(script)], env, notes={"model": "stand-in"})

    monkeypatch.setattr(program, "agent_launch", launch)


def _report(trial: Path) -> dict:
    out = (trial / "agent" / "stdout.jsonl").read_text()
    line = next(ln for ln in out.splitlines() if ln.startswith("PROGRAM-REPORT "))
    return json.loads(line[len("PROGRAM-REPORT ") :])


def test_the_driver_is_aspire_s_with_this_harness_s_words() -> None:
    src = program.driver_source()
    assert "[program]" in src and "aspire: " not in src


def test_a_trial_scores_the_last_submission_and_development_runs_tell_no_verdict(tmp_path, monkeypatch) -> None:
    pytest.importorskip("mujoco")
    from robouse.runner import run_trial
    from robouse.tasks import load_task

    _scripted_agent(monkeypatch)
    monkeypatch.setenv("ROBOUSE_SANDBOX", "0")
    res = run_trial(load_task(CUBEPICK / "cubepick-reach-layout-0"), "program", "", tmp_path / "job", timeout=900)
    assert res["exception"] is None, res
    assert res["reward"] == 1.0, res
    trial = tmp_path / "job" / res["trial"]
    rep = _report(trial)
    assert rep["socket_env"] is None and rep["socket_file"] is False and rep["driver_key"] is False
    assert rep["program_md"] and rep["freeze"] == 403
    assert rep["look"][0] == 0 and rep["run"][0] == 0, rep
    # a development run reports what the program did, never how the episode server judged it
    summary = rep["summary"]
    assert summary["ok"] and summary["steps_used"] > 0
    assert "success" not in json.dumps(summary)
    # CubePick ends at its first success, which a development run cannot hide: it ended, without the reason, and
    # takes no picture after that (the scenario tasks judge only after the program)
    assert summary["episode"] == "finished" and summary["keyframe_error"] == "episode finished"
    assert rep["frames"][0] == "k000-reset.png" and len(rep["frames"]) >= 2
    assert all(f.endswith("-act.png") for f in rep["frames"][1:])
    assert summary["keyframe_cameras"] == ["top"]
    status = rep["status"][1]
    assert set(status) == {"runs", "max_runs", "submissions", "last_submission", "frozen", "minutes_left"}
    assert 0 < status["minutes_left"] <= 15  # a 900 s trial
    assert rep["episode_seed"] is None  # the agent never picks the seed
    assert "outcome" not in rep["status_op"]["result"]
    assert rep["finish"] == {"ended": True, "steps_used": 0}
    assert rep["result_file"] == 404
    assert rep["bad"][0] == 1 and "not allowed" in rep["bad"][1]
    assert rep["nosolve"][0] == 400
    assert rep["submit"][0] == 0
    rec = json.loads((trial / "result.json").read_text())["harness_record"]
    assert rec["program"]["submitted"] and len(rec["submissions"]) == 1
    assert rec["stage2"]["ran"] and rec["stage2"]["program_ok"]
    assert rec["scored_requests_before_stage2"] == 0
    assert rec["scored_episode_lock"]["refused"] == 0
    assert (trial / "program" / "solution" / "submitted-solve.py").read_text() == SOLVE
    assert "never scored" in (trial / "program" / "solution" / "workspace-solve.py").read_text()
    assert len(list((trial / "program" / "practice").iterdir())) == 3
    cfg = json.loads((trial / "config.json").read_text())
    assert cfg["harness_config"]["dev_runs"] == 40


def test_a_trial_without_a_submission_gives_up(tmp_path, monkeypatch) -> None:
    pytest.importorskip("mujoco")
    from robouse.runner import run_trial
    from robouse.tasks import load_task

    _scripted_agent(monkeypatch, submit=False)
    monkeypatch.setenv("ROBOUSE_SANDBOX", "0")
    res = run_trial(load_task(CUBEPICK / "cubepick-reach-layout-1"), "program", "", tmp_path / "job", timeout=900)
    assert res["exception"] is None, res
    assert res["reward"] == 0.0 and res["outcome"] == "gave_up", res
    rec = json.loads((tmp_path / "job" / res["trial"] / "result.json").read_text())["harness_record"]
    assert not rec["program"]["submitted"] and rec["stage2"]["ran"] is False
    assert "nothing was submitted" in rec["stage2"]["error"]


def test_a_give_up_after_a_submission_runs_nothing_and_ends_with_the_reason(tmp_path, monkeypatch) -> None:
    pytest.importorskip("mujoco")
    from robouse.runner import run_trial
    from robouse.tasks import load_task

    _scripted_agent(monkeypatch, give_up="I will not do this")
    monkeypatch.setenv("ROBOUSE_SANDBOX", "0")
    res = run_trial(load_task(CUBEPICK / "cubepick-reach-layout-0"), "program", "", tmp_path / "job", timeout=900)
    assert res["exception"] is None, res
    assert res["reward"] == 0.0 and res["outcome"] == "gave_up", res
    rep = _report(tmp_path / "job" / res["trial"])
    assert rep["submit"][0] == 0 and rep["give_up"][0] == 0, rep
    rec = json.loads((tmp_path / "job" / res["trial"] / "result.json").read_text())["harness_record"]
    assert not rec["program"]["submitted"] and rec["program"]["gave_up"] == "I will not do this"
    assert rec["stage2"]["ran"] is False and "the agent gave up: I will not do this" in rec["stage2"]["error"]
    assert [("gave_up" in s) for s in rec["submissions"]] == [False, True]
