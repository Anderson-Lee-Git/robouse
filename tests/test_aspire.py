"""The aspire harnesses: ASPIRE's skills (vendored unchanged), the program contract, practice episodes on other seeds
than the scored one, the skill library across trials, and Stage 2 on the scored episode.

Whole trials run a scripted stand-in for the coding agent (no model is called): it follows ASPIRE's worker steps with
the workspace's own tools (`cap-harness run-batch` on development seeds, a refused seed, the unseen-check seed once, a
selected fix_code.py, a library edit) on the light `cubepick` tasks, under a practice profile registered for the test.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import runpy
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from robouse import harnesses
from robouse.harnesses import aspire, models
from robouse.harnesses.aspire import broker as broker_mod
from robouse.harnesses.aspire import library as library_mod
from robouse.harnesses.aspire.workspace import programs

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "src" / "robouse" / "harnesses" / "aspire" / "upstream"
CUBEPICK = ROOT / "tasks" / "cubepick"

# reaches the cube with the robot's own state: the CubePick world reports eef_pos and cube_pos
REACH = """
for tick in range(60):
    s = robo.observe()["state"]
    if s["distance"] < 0.03:
        break
    dx = max(-0.1, min(0.1, float(s["cube_pos"][0]) - float(s["eef_pos"][0])))
    dy = max(-0.1, min(0.1, float(s["cube_pos"][1]) - float(s["eef_pos"][1])))
    moved = robo.act([dx, dy])
    if "episode" in moved:
        break
result = {"ticks": tick}
"""


# ---- vendored files -------------------------------------------------------------------------------------------------
def test_vendored_aspire_files_are_unchanged() -> None:
    text = (UPSTREAM / "VENDORED.md").read_text()
    block = re.search(r"```text\n(.*?)```", text, flags=re.S)
    assert block is not None
    listed = dict(reversed(line.split("  ", 1)) for line in block.group(1).strip().splitlines())
    on_disk = {
        str(p.relative_to(UPSTREAM)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in UPSTREAM.rglob("*")
        if p.is_file() and p.name != "VENDORED.md"
    }
    assert on_disk == listed
    assert "fa00f0ef2bc1d91d594b9aa502c22133c9f538f7" in text and library_mod.ASPIRE_COMMIT in text
    # no worked solutions for the tasks Robo Use scores, no real-robot parts
    assert not any("fix_code" in p or "/behavior/" in p or "yam_real" in p or "AGENTS" in p for p in on_disk)
    assert (UPSTREAM / "LICENSE").read_text().startswith("Copyright (c) 2026 NVIDIA CORPORATION")


def test_the_library_hash_is_aspire_s() -> None:
    ns = runpy.run_path(str(UPSTREAM / "claude/skills/iterative-debugging/scripts/campaign.py"))
    assert library_mod.skill_library_sha(library_mod.SEED_SKILLS) == ns["skill_library_sha"](library_mod.SEED_SKILLS)


def test_programs_get_aspire_s_builtins() -> None:
    ns = runpy.run_path(str(UPSTREAM / "claude/skills/iterative-debugging/scripts/campaign.py"))
    assert set(programs.BUILTIN_NAMES) == set(ns["PROGRAM_BUILTINS"]) | set(ns["PROGRAM_EXCEPTIONS"])


# ---- the program contract -------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "source",
    [
        "import os\n",
        "from math import pi\n",
        "import numpy as n\n",
        "class A:\n    pass\n",
        "with open('x') as f:\n    pass\n",
        "x = robo._api\n",
        "_hidden = 1\n",
        "global x\n",
        "",
    ],
)
def test_the_contract_refuses(source: str) -> None:
    with pytest.raises(programs.ProgramRejected):
        programs.validate(source)


def test_the_contract_allows_math_and_numpy() -> None:
    programs.validate("import math\nimport numpy\nimport numpy as np\nresult = math.pi + float(np.zeros(1)[0])\n")


class FakeEpisode:
    """An episode server's replies, for the program executor."""

    def __init__(self) -> None:
        self.reqs: list[dict] = []
        self.steps = 0

    def send(self, req: dict) -> dict:
        self.reqs.append(req)
        if req["op"] == "skill" and req["name"] == "goto_pose":
            self.steps += 40
            return {"ok": True, "result": {"running": True, "steps_used": self.steps}}
        if req["op"] == "skill" and req["name"] == "capx_continue":
            self.steps += 7
            return {"ok": True, "result": {"return": None, "stdout": "moved\n", "steps_used": self.steps}}
        if req["op"] == "skill" and req["name"] == "get_object_pose":
            return {"ok": True, "result": {"return": [[0.5, 0.0, 0.1], [1, 0, 0, 0]], "steps_used": self.steps}}
        if req["op"] == "skill":
            return {"ok": True, "result": {"error": "ValueError: no such object", "steps_used": self.steps}}
        return {"ok": False, "error": f"unexpected {req}"}


def test_a_program_calls_the_task_s_api_by_name() -> None:
    ep = FakeEpisode()
    spans: list[dict] = []
    moved: list[str] = []
    info = {"skills": ["get_object_pose", "goto_pose", "open_gripper", "capx_continue"], "steps_used": 0}
    api = programs.Api(ep.send, info, on_call=spans.append, after_motion=moved.append)
    src = (
        "import numpy as np\n"
        "pos, quat = get_object_pose('red cube')\n"
        "goto_pose(pos + np.array([0, 0, 0.1]), quat, z_approach=0.1)\n"
        "try:\n    open_gripper()\nexcept Exception as e:\n    failed = str(e)\n"
        "result = {'z': float(pos[2]), 'failed': failed}\n"
    )
    ex = programs.execute(src, api)
    assert ex.ok, ex.error
    assert ex.result == {"z": 0.1, "failed": "open_gripper: ValueError: no such object"}
    assert "moved" in ex.stdout
    goto = next(r for r in ep.reqs if r.get("name") == "goto_pose")
    assert json.loads(goto["args"][0]) == pytest.approx([0.5, 0.0, 0.2]) and goto["args"][2] == "z_approach=0.1"
    assert [r["name"] for r in ep.reqs if r["op"] == "skill"].count("capx_continue") == 1  # a long call goes on
    assert api.steps_used == 47 and moved == ["goto_pose"]
    assert [s["name"] for s in spans] == ["get_object_pose", "goto_pose", "open_gripper"]
    assert spans[2]["ok"] is False and spans[1]["steps"] == 47


def test_a_failing_program_is_a_result_not_a_crash() -> None:
    api = programs.Api(FakeEpisode().send, {"skills": ["open_gripper"]})
    ex = programs.execute("open_gripper()\n", api)
    assert not ex.ok and "no such object" in ex.error["message"]
    ex = programs.execute("import os\n", api)
    assert not ex.ok and ex.error["type"] == "ProgramRejected"


def test_numpy_s_imports_on_first_use_work_from_a_program() -> None:
    # numpy's compiled code imports some of its modules on first use, through the builtins of the calling frame, the
    # program's: `.mean()` in a fresh process imports numpy._core._methods (a vision program failed on it)
    code = (
        "from robouse.harnesses.aspire.workspace import programs\n"
        "api = programs.Api(lambda req: {'ok': True, 'result': {}}, {})\n"
        "ex = programs.execute('import numpy as np\\nresult = float(np.ones((4, 4, 3)).mean())', api)\n"
        "print(ex.ok, ex.result, ex.error)\n"
    )
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=120)
    assert out.stdout.strip() == "True 1.0 None", out.stdout + out.stderr
    with pytest.raises(ImportError):  # the hook serves numpy and math, nothing else
        programs.safe_builtins()["__import__"]("os")


# ---- seeds and scenes -----------------------------------------------------------------------------------------------
def test_capx_libero_seeds_are_saved_initial_states() -> None:
    p = aspire.PROFILES["capx_libero"]
    assert p.scene(1) == p.scene(51) == 0  # ASPIRE's LIBERO development band would replay the scored scene
    assert 0 not in {p.scene(s) for s in (*p.dev, *p.unseen)}
    assert len({p.scene(s) for s in (*p.dev, *p.unseen)}) == len(p.dev) + len(p.unseen)


def test_bands_drop_the_scored_scene(monkeypatch) -> None:
    p = aspire.PROFILES["capx"]
    assert (p.dev[0], p.dev[-1], p.unseen[0], p.unseen[-1]) == (101, 125, 126, 130)  # ASPIRE's Robosuite bands
    dev, unseen, dropped = aspire.bands(p, {105})
    assert 105 not in dev and dropped == [105] and unseen == list(range(126, 131))
    monkeypatch.setenv("ROBOUSE_ASPIRE_DEV_SEEDS", "101-103")
    monkeypatch.setenv("ROBOUSE_ASPIRE_UNSEEN_SEEDS", "126")
    assert aspire.bands(p, {1})[:2] == ([101, 102, 103], [126])
    monkeypatch.setenv("ROBOUSE_ASPIRE_DEV_SEEDS", "1-3")
    with pytest.raises(ValueError, match="start at 2"):
        aspire.bands(p, set())
    monkeypatch.setenv("ROBOUSE_ASPIRE_DEV_SEEDS", "126")
    with pytest.raises(ValueError, match="overlap"):
        aspire.bands(p, set())


def _libero_pro_task(**robouse):
    """A task as the libero-pro suite's generator writes it: ASPIRE's libero_goal_task:8, saved start states."""
    from robouse.tasks import Task

    spec = {
        "id": "libero-pro-goal-task-8",
        "backend": "libero",
        "suite": "libero_goal_task",
        "env": "libero_goal_task:8",
        "task_index": 8,
        "seed": 1,
        "obs_mode": "vision",
        "init_mode": "saved",
        "init_states": {"url": "https://example.invalid/x.pruned_init", "sha256": "0" * 64, "count": 50},
        **robouse,
    }
    return Task(Path("/nonexistent/libero-pro-goal-task-8"), {"metadata": {"suite": "libero-pro"}, "robouse": spec})


def test_the_libero_pro_suite_s_tasks_practise_on_other_saved_states() -> None:
    # the suite as shipped: 50 saved start states per task, the scored one state 0 (seed 1)
    from robouse.tasks import load_task

    task = load_task(ROOT / "tasks" / "libero-pro" / "libero-pro-10-task-6")
    p = aspire.profile_for(task)
    assert p.family(task) == ("libero-pro", "libero_10_task", 6)  # ASPIRE's libero_10_task:6
    scored = p.scene(int(task.spec["seed"]))
    dev, unseen, dropped = aspire.bands(p, {scored})
    assert scored == 0 and dev == list(range(36, 51)) and unseen == list(range(21, 36)) and dropped == []
    assert 0 not in {p.scene(s) for s in dev + unseen} and p.scene(51) == 0  # ASPIRE's band would replay state 0


def test_libero_pro_tasks_get_aspire_s_names_and_their_own_seed_rule() -> None:
    t = _libero_pro_task()
    p = aspire.profile_for(t)
    assert p.family(t) == ("libero-pro", "libero_goal_task", 8)  # ASPIRE's libero-pro/libero_goal_task/task_8
    assert p.scene(1) == p.scene(51) == 0 and 0 not in {p.scene(s) for s in (*p.dev, *p.unseen)}
    assert (p.dev, p.unseen) == (tuple(range(36, 51)), tuple(range(21, 36)))
    assert "camera images" in p.perception
    seeded = aspire.profile_for(_libero_pro_task(init_mode="seeded"))  # ASPIRE's --init-mode seeded and its bands
    assert (seeded.dev[0], seeded.dev[-1], seeded.unseen[0], seeded.unseen[-1]) == (51, 65, 66, 80)
    assert seeded.scene(51) != seeded.scene(1)
    with pytest.raises(ValueError, match="one fixed state"):
        aspire.profile_for(_libero_pro_task(init_states=None, init_state=[0.0]))
    assert aspire.saved_state_bands(10) == ((7, 8, 9, 10), (3, 4, 5, 6))


def test_a_program_gets_camera_images_as_arrays() -> None:
    import base64
    import io

    import numpy as np
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(np.full((4, 6, 3), 200, dtype=np.uint8)).save(buf, format="PNG")
    sent: list[dict] = []

    def send(req: dict) -> dict:
        sent.append(req)
        return {"ok": True, "result": {"images": {"agentview": base64.b64encode(buf.getvalue()).decode()}}}

    ex = programs.execute(
        "img = robo.image('agentview')\nresult = [int(img.shape[0]), int(img[0, 0, 1])]\n", programs.Api(send, {})
    )
    assert ex.ok, ex.error
    assert ex.result == [4, 200]
    assert sent == [{"op": "observe", "inline": {"format": "png", "cameras": ["agentview"]}}]


def test_tasks_without_a_practice_profile_are_refused() -> None:
    from robouse.tasks import load_task

    with pytest.raises(ValueError, match="distinct scenes"):
        aspire.profile_for(load_task(ROOT / "tasks" / "arc-style" / "arc-gravity"))


# ---- the library ----------------------------------------------------------------------------------------------------
def test_a_new_library_is_aspire_s_and_write_back_keeps_concurrent_changes(tmp_path) -> None:
    lib = library_mod.Library(tmp_path / "lib")
    lib.prepare()
    assert library_mod.file_hashes(lib.skills) == library_mod.file_hashes(library_mod.SEED_SKILLS)
    assert lib.manifest()["aspire"]["commit"] == library_mod.ASPIRE_COMMIT
    a = tmp_path / "a" / "skills"
    start = lib.copy_skills_to(a)
    (a / "transport.md").write_text((a / "transport.md").read_text() + "\n## Verified entry from trial a\n")
    (a / "grasp.md").write_text("trial a's grasp\n")
    (a / "localize.md").unlink()  # a file the trial's copy lost stays in the library
    # meanwhile another trial changed grasp.md in the library
    (lib.skills / "grasp.md").write_text("trial b's grasp\n")
    entry = {"trial": "t-a", "practice": {"scene_ids": [library_mod.scene_id(("capx", "cube_stack", 0), 101)]}}
    out = lib.write_back(entry, start, a, None, ("capx", "cube_stack", 0))
    assert out["changed"] == ["transport.md"] and out["conflicts"] == ["grasp.md"]
    assert out["not_deleted"] == ["localize.md"] and (lib.skills / "localize.md").is_file()
    assert "trial a" in (lib.skills / "transport.md").read_text()
    assert (lib.skills / "grasp.md").read_text() == "trial b's grasp\n"
    assert (tmp_path / "lib" / "conflicts" / "t-a" / "grasp.md").read_text() == "trial a's grasp\n"
    assert library_mod.scene_id(("capx", "cube_stack", 0), 101) in lib.practised()
    # a selected program the contract refuses is kept with the trial but not adopted for the task's other scenes
    results = tmp_path / "results"
    results.mkdir()
    (results / "fix_code.py").write_text("x, _ = get_object_pose('red cube')\n")
    saved = lib.write_back({"trial": "t-b"}, start, a, results, ("capx", "cube_stack", 0))["task_results"]
    assert saved["selected"] == [] and "dunder" in saved["not_selected"][0]["why"]
    assert lib.selected_program(("capx", "cube_stack", 0), "fix_code.py") is None
    assert lib.manifest()["trials"][0]["sha_after"] == library_mod.skill_library_sha(lib.skills)


def _library_with_program(tmp_path: Path, harness: str, model: str) -> library_mod.Library:
    lib = library_mod.Library(tmp_path / "library")
    lib.prepare()
    task_dir = tmp_path / "library" / "tasks" / "cubepick" / "reach" / "task_0"
    task_dir.mkdir(parents=True)
    (task_dir / "fix_code.py").write_text(REACH)
    m = lib.manifest()
    m["trials"].append(
        {
            "trial": "first",
            "family": ["cubepick", "reach", 0],
            "harness": harness,
            "model": model,
            "task_results": {"selected": ["fix_code.py"]},
        }
    )
    (tmp_path / "library" / "library.json").write_text(json.dumps(m))
    return lib


def test_a_task_s_program_is_reused_only_by_the_harness_and_model_that_selected_it(tmp_path, monkeypatch) -> None:
    lib = _library_with_program(tmp_path, "aspire", "claude-opus-5-5")
    fam = ("cubepick", "reach", 0)
    monkeypatch.delenv("ROBOUSE_ASPIRE_REUSE", raising=False)
    path, source, why = aspire.library_program(lib, fam, "fix_code.py", "aspire", "claude-opus-5-5")
    assert path is not None and source is not None and why is None
    assert (source["trial"], source["harness"], source["model"]) == ("first", "aspire", "claude-opus-5-5")
    for harness, model in (("aspire", "claude-sonnet-5"), ("aspire-codex", "claude-opus-5-5")):
        path, source, why = aspire.library_program(lib, fam, "fix_code.py", harness, model)
        assert path is None and why and "ROBOUSE_ASPIRE_REUSE=any" in why
    monkeypatch.setenv("ROBOUSE_ASPIRE_REUSE", "any")  # asked for explicitly
    assert aspire.library_program(lib, fam, "fix_code.py", "aspire-codex", "gpt-6-astra")[0] is not None
    monkeypatch.setenv("ROBOUSE_ASPIRE_REUSE", "0")
    assert aspire.library_program(lib, fam, "fix_code.py", "aspire", "claude-opus-5-5") == (None, None, None)
    # a program whose selection the record does not show is not reused either
    monkeypatch.delenv("ROBOUSE_ASPIRE_REUSE")
    (tmp_path / "library" / "library.json").write_text(json.dumps({**lib.manifest(), "trials": []}))
    assert aspire.library_program(lib, fam, "fix_code.py", "aspire", "claude-opus-5-5")[0] is None


def test_the_library_takes_only_verified_results_and_verified_entries(tmp_path) -> None:
    lib = library_mod.Library(tmp_path / "library")
    lib.prepare()
    fam = ("cubepick", "reach", 0)
    start = library_mod.file_hashes(lib.skills)
    after = tmp_path / "after"
    shutil.copytree(lib.skills, after)
    (after / "transport.md").write_text((after / "transport.md").read_text() + "\n## A new entry\n")
    rec = tmp_path / "rec"
    results = rec / "outputs" / "runs" / "r1" / "cubepick" / "reach" / "task_0"
    results.mkdir(parents=True)
    (results / "fix_code.py").write_text(REACH)
    (rec / "record.json").write_text("{}")
    entry = {"trial": "t1", "family": list(fam), "harness": "aspire", "model": "m", "library_sha_before": "x"}
    args = dict(entry=entry, start=start, after=after, results=results, record=rec / "record.json")
    # ASPIRE's verifier: no report, a refuted one, then a verified one
    assert aspire.aspire_verified(rec, fam)[0] is False
    vdir = rec / "outputs" / "runs" / "r1" / "verification" / "cubepick__reach__task_0"
    vdir.mkdir(parents=True)
    (vdir / "verification_report.json").write_text(json.dumps({"verdict": "refuted"}))
    assert aspire.aspire_verified(rec, fam)[0] is False
    # not a verified result (an integrity failure): nothing at all
    out = aspire.write_library(lib, fam, False, skills_withheld=None, **args)
    assert (
        out["written"] is False and lib.manifest()["trials"] == [] and lib.selected_program(fam, "fix_code.py") is None
    )
    # a result, without a verified report: the program is kept, the entry is withheld
    out = aspire.write_library(lib, fam, True, skills_withheld=aspire.aspire_verified(rec, fam)[1], **args)
    assert out["written"] and out["withheld"] == ["transport.md"] and out["changed"] == []
    assert "A new entry" not in (lib.skills / "transport.md").read_text()
    assert lib.selected_program(fam, "fix_code.py") is not None
    assert json.loads((rec / "record.json").read_text())["library"]["withheld"] == ["transport.md"]
    (vdir / "verification_report.json").write_text(json.dumps({"verdict": "verified"}))
    ok, where = aspire.aspire_verified(rec, fam)
    assert ok and where.endswith("verification_report.json")
    out = aspire.write_library(lib, fam, True, skills_withheld=None, **{**args, "entry": {**entry, "trial": "t2"}})
    assert out["changed"] == ["transport.md"] and "A new entry" in (lib.skills / "transport.md").read_text()


# ---- the practice broker --------------------------------------------------------------------------------------------
def _cubepick_broker(tmp_path: Path, **kw) -> broker_mod.PracticeBroker:
    args = dict(
        task_path=CUBEPICK / "cubepick-reach-layout-0",
        record_dir=tmp_path / "rec",
        dev=[101, 102],
        unseen=[103],
        scene=lambda s: s,
        protected={0},
        max_episodes=3,
        workers=2,
        episode_wall_s=120,
    )
    args.update(kw)
    b = broker_mod.PracticeBroker(**args)  # type: ignore[arg-type]
    b.start()
    return b


def test_the_broker_runs_practice_episodes_and_refuses_the_rest(tmp_path) -> None:
    pytest.importorskip("mujoco")
    b = _cubepick_broker(tmp_path)
    try:
        assert programs.http_json(b.url.rsplit("/", 1)[0] + "/wrong-token/status")[0] == 403
        status, started = programs.http_json(f"{b.url}/episodes", {"seed": 101})
        assert status == 200 and started["info"]["task"] == "cubepick-reach-layout-0"
        eid = started["id"]
        send = programs.practice_transport(b.url, eid)
        # a privileged request is not privileged here, and the runner's marks are dropped
        reply = send({"op": "observe", "token": "guess", "runner": True})
        assert reply["ok"] and "secret" not in reply["result"]["state"]
        assert not send({"op": "done"})["ok"]  # ending goes through finish
        ex = programs.execute(REACH, programs.Api(send, started["info"]))
        assert ex.ok, ex.error
        status, done = programs.http_json(f"{b.url}/episodes/{eid}/finish", {"op": "done"})
        assert status == 200 and done["verdict"]["success"] is True and "trace.jsonl" in done["files"]
        assert "signature" not in done["verdict"]
        assert programs.http_json(f"{b.url}/episodes", {"seed": 0})[0] == 409  # the scored seed
        assert programs.http_json(f"{b.url}/episodes", {"seed": 7})[0] == 409  # not a practice seed
        assert programs.http_json(f"{b.url}/episodes", {"seed": 103})[0] == 200
        status, again = programs.http_json(f"{b.url}/episodes", {"seed": 103})
        assert status == 409 and "once" in again["error"]  # an unseen-check seed runs once
        status, over = programs.http_json(f"{b.url}/episodes", {"seed": 102})
        assert status == 200
        assert programs.http_json(f"{b.url}/episodes", {"seed": 101})[0] == 409  # budget: 3 episodes
        frozen = programs.http_json(f"{b.url}/freeze", {"by": "test", "key": b.freeze_key})
        assert frozen[0] == 200
        assert programs.http_json(f"{b.url}/episodes", {"seed": 101})[0] == 409
        rec = b.record()
        assert rec["episodes"] == 3 and rec["successes"] == 1 and rec["unseen_used"] == [103]
        assert all(r["outcome"] for r in rec["runs"])  # running episodes were ended at freeze
    finally:
        b.stop()


def _slow_servers(monkeypatch, commands: list | None = None) -> list[subprocess.Popen]:
    """Episode servers that never get ready: a request is still starting its episode when practice ends."""
    real, started = subprocess.Popen, []

    def slow(cmd, **kw):
        if commands is not None:
            commands.append(list(cmd))
        p = real([sys.executable, "-c", "import time; time.sleep(120)"], **kw)
        started.append(p)
        return p

    monkeypatch.setattr(broker_mod.subprocess, "Popen", slow)
    return started


def _start_in_background(b: broker_mod.PracticeBroker, started: list) -> tuple[threading.Thread, dict]:
    out: dict = {}
    t = threading.Thread(target=lambda: out.update(reply=b.start_episode(101)), daemon=True)
    t.start()
    deadline = time.time() + 30
    while not started and time.time() < deadline:
        time.sleep(0.05)
    assert started, "the episode server did not start"
    return t, out


def test_an_episode_still_starting_when_practice_freezes_is_stopped(tmp_path, monkeypatch) -> None:
    started = _slow_servers(monkeypatch)
    b = _cubepick_broker(tmp_path)
    try:
        t, out = _start_in_background(b, started)
        b.freeze("driver")
        t.join(10)
        assert out["reply"][0] == 409 and "frozen" in out["reply"][1]["error"]
        assert started[0].poll() is not None
    finally:
        b.stop()


def test_practice_sockets_are_named_like_episode_sockets(tmp_path, monkeypatch) -> None:
    # robouse-<hex>.sock: the macOS sandbox refuses those to every agent but the trial's own scored one, so no trial's
    # agent can drive another's (or its own) practice episodes directly
    from robouse.runner import sandbox

    commands: list = []
    started = _slow_servers(monkeypatch, commands)
    b = _cubepick_broker(tmp_path)
    t, out = _start_in_background(b, started)
    b.stop()
    t.join(10)
    sock = commands[0][commands[0].index("--socket") + 1]
    assert re.fullmatch(r"/tmp/robouse-[0-9a-f]+\.sock", sock), sock
    own = "/tmp/robouse-0123456789.sock"
    profile = sandbox.sandbox_profile(tmp_path, socket=own)
    denied = re.search(r'\(deny network-outbound \(remote unix-socket \(path-regex #"(.+?)"\)\)\)', profile)
    assert denied and re.match(denied.group(1), os.path.realpath(sock))


def test_only_the_driver_ends_practice(tmp_path) -> None:
    b = _cubepick_broker(tmp_path)
    try:
        assert programs.http_json(f"{b.url}/freeze", {"by": "agent"})[0] == 403  # the agent's broker token alone
        assert programs.http_json(f"{b.url}/freeze", {"by": "agent", "key": "guess"})[0] == 403
        assert b.frozen is None
        assert programs.http_json(f"{b.url}/freeze", {"by": "driver", "key": b.freeze_key})[0] == 200
        assert b.frozen_by == "driver"
    finally:
        b.stop()


def test_stopping_the_broker_leaves_no_episode_server_behind(tmp_path, monkeypatch) -> None:
    # the runner stops the broker and exits; a request thread still starting an episode dies with the process, so
    # stop() itself must end the server it started (the first real pilot left one running after its trial ended)
    started = _slow_servers(monkeypatch)
    b = _cubepick_broker(tmp_path)
    t, out = _start_in_background(b, started)
    b.stop()
    assert started[0].poll() is not None
    t.join(10)
    assert out["reply"][0] == 409


def test_the_copy_out_never_follows_a_link_swapped_in_later(tmp_path) -> None:
    # the reader opens the workspace before the agent starts; then each folder and file relative to its parent with
    # O_NOFOLLOW, checked with fstat: a path swapped for a link (or a FIFO) at any time is not followed
    ws, outside = tmp_path / "ws", tmp_path / "outside"
    (ws / "skills").mkdir(parents=True)
    (ws / "skills" / "grasp.md").write_text("entry\n")
    (ws / "skills" / "keep.md").write_text("kept\n")
    outside.mkdir()
    (outside / "grasp.md").write_text("a file outside the workspace\n")
    reader = broker_mod.WorkspaceReader(ws)
    try:
        # the file becomes a link, a FIFO takes another's place
        (ws / "skills" / "grasp.md").unlink()
        (ws / "skills" / "grasp.md").symlink_to(outside / "grasp.md")
        (ws / "skills" / "keep.md").unlink()
        os.mkfifo(ws / "skills" / "keep.md")
        assert reader.read(ws / "skills" / "grasp.md") is None and reader.read(ws / "skills" / "keep.md") is None
        assert reader.copy(ws / "skills", tmp_path / "out1", (".md",)) == []
        # a folder becomes a link
        (ws / "skills").rename(ws / "old")
        (ws / "skills").symlink_to(outside)
        assert reader.copy(ws / "skills", tmp_path / "out2", (".md",)) == []
        assert reader.read(ws / "skills" / "grasp.md") is None
        # the workspace itself is moved and a link put in its place: the reader still reads the real one
        (ws / "old" / "real.md").write_text("in the workspace\n")
        ws.rename(tmp_path / "moved")
        ws.symlink_to(outside)
        assert reader.read(ws / "old" / "real.md") == b"in the workspace\n"
        assert reader.read(ws / "grasp.md") is None  # the outside folder's file, by the link's name: not there
        assert reader.read(ws / ".." / "outside" / "grasp.md") is None
    finally:
        reader.close()


def test_the_broker_copies_nothing_through_a_link(tmp_path) -> None:
    ws = tmp_path / "ws"
    (ws / "skills").mkdir(parents=True)
    (ws / "skills" / "grasp.md").write_text("entry\n")
    secret = tmp_path / "outside.md"
    secret.write_text("a file outside the workspace\n")
    (ws / "skills" / "leak.md").symlink_to(secret)
    (ws / "linked").symlink_to(tmp_path)
    copied = broker_mod.copy_regular_files(ws / "skills", tmp_path / "out", ws, (".md",))
    assert copied == ["grasp.md"]
    assert broker_mod.copy_regular_files(ws / "linked", tmp_path / "out2", ws, (".md",)) == []
    assert broker_mod.read_regular_file(ws / "skills" / "leak.md", ws) is None


# ---- whole trials ---------------------------------------------------------------------------------------------------
AGENT = r'''
import json, os, subprocess, sys
from pathlib import Path

ws = Path.cwd()
report = {
    "socket_env": os.environ.get("ROBOUSE_SOCKET"),
    "socket_file": (ws / ".robouse" / "socket").exists(),
    "ready_file": (ws / ".robouse" / "ready").exists(),
    "driver_key": (ws / ".robouse" / "aspire" / "driver.key").exists(),
}
import urllib.error, urllib.request
try:  # the agent holds the broker's token, not the driver's freeze key
    urllib.request.urlopen(urllib.request.Request(
        os.environ["ROBOUSE_PRACTICE_URL"].rstrip("/") + "/freeze", data=b'{"by": "agent"}', method="POST"), timeout=30)
    report["freeze"] = 200
except urllib.error.HTTPError as e:
    report["freeze"] = e.code
run_root = (ws / "outputs" / "runs" / "LATEST").resolve()
report["campaign"] = json.loads((run_root / "campaign.json").read_text())
task_dir = run_root / "cubepick" / "reach" / "task_0"
(task_dir / "code").mkdir(parents=True)
program = task_dir / "code" / "v00_initial.py"
program.write_text(PROGRAM)
common = ["--benchmark", "cubepick", "--suite", "reach", "--task-id", "0", "--program", str(program)]
r = subprocess.run(["cap-harness", "run-batch", *common, "--seeds", "101-102", "--workers", "2",
                    "--output-root", str(task_dir / "debug" / "initial"), "--flat-run-dir",
                    "--results-jsonl", str(task_dir / "debug" / "initial" / "results.jsonl")],
                   capture_output=True, text=True)
report["batch"] = r.stdout
report["results"] = [json.loads(l) for l in (task_dir / "debug" / "initial" / "results.jsonl").read_text().splitlines()]
for k, seed in enumerate(("0", "103", "103")):  # the scored seed, then the unseen-check seed twice
    r = subprocess.run(["cap-harness", "run", *common, "--seed", seed, "--output-root", str(task_dir / "debug" / "holdout"),
                        "--flat-run-dir"], capture_output=True, text=True)
    report[f"run_{k}"] = (r.returncode, (r.stdout + r.stderr).strip()[-300:])
(task_dir / "fix_code.py").write_text(PROGRAM)
lib = ws / ".claude" / "skills" / "iterative-debugging" / "skills" / "transport.md"
lib.write_text(lib.read_text() + "\n## Reach by the reported state (verified on reach)\n")
vdir = run_root / "verification" / "cubepick__reach__task_0"  # ASPIRE's verifier reproduced the entry
vdir.mkdir(parents=True)
(vdir / "verification_report.json").write_text(json.dumps({"verdict": "verified", "trials": 2, "passes": 2}))
print("ASPIRE-REPORT " + json.dumps(report), flush=True)
'''


def _scripted_agent(monkeypatch, body: str = "", skill: str = "iterative-debugging") -> None:
    def launch(agent, model, prompt, workspace, task, env):
        script = workspace / ".robouse" / "aspire" / "stand_in_agent.py"
        script.write_text(f"PROGRAM = {REACH!r}\n" + (body or AGENT))
        assert f"{skill}/SKILL.md" in prompt and "docs/robouse.md" in prompt
        return harnesses.Launch([sys.executable, str(script)], env, notes={"model": "stand-in"})

    monkeypatch.setattr(aspire, "agent_launch", launch)
    monkeypatch.setitem(
        aspire.PROFILES,
        "cubepick",
        aspire.Profile(
            dev=(101, 102),
            unseen=(103,),
            rule="seed n is CubePick's layout n",
            scene=lambda s: s,
            family=lambda task: ("cubepick", "reach", 0),
            perception="the robot's state",
        ),
    )


def _report(trial: Path) -> dict:
    out = (trial / "agent" / "stdout.jsonl").read_text()
    line = next(ln for ln in out.splitlines() if ln.startswith("ASPIRE-REPORT "))
    return json.loads(line[len("ASPIRE-REPORT ") :])


def test_a_trial_practises_on_other_seeds_and_scores_the_frozen_program(tmp_path, monkeypatch) -> None:
    pytest.importorskip("mujoco")
    from robouse.runner import run_trial
    from robouse.tasks import load_task

    _scripted_agent(monkeypatch)
    monkeypatch.setenv("ROBOUSE_SANDBOX", "0")
    monkeypatch.setenv("ROBOUSE_ASPIRE_LIBRARY", str(tmp_path / "library"))
    monkeypatch.setenv("ROBOUSE_ASPIRE_PRACTICE_WORKERS", "2")
    job = tmp_path / "job"
    res = run_trial(load_task(CUBEPICK / "cubepick-reach-layout-0"), "aspire", "", job, timeout=900)
    assert res["exception"] is None, res
    assert res["reward"] == 1.0 and res["outcome"] == "success_reached"  # CubePick ends on its first success
    trial = job / res["trial"]
    rep = _report(trial)
    # the agent never had the scored episode, nor the files that name its socket, nor the driver's freeze key
    assert rep["socket_env"] is None and rep["socket_file"] is False and rep["ready_file"] is False
    assert rep["driver_key"] is False and rep["freeze"] == 403
    assert rep["campaign"]["dev_seeds"] == [101, 102] and rep["campaign"]["unseen_seeds"] == [103]
    assert [r["task_success"] for r in rep["results"]] == [True, True], rep["batch"]
    assert rep["run_0"][0] == 3 and "not a practice seed" in rep["run_0"][1]
    assert rep["run_1"][0] == 0 and rep["run_2"][0] == 3 and "once" in rep["run_2"][1]
    run_dirs = sorted((Path(r["run_dir"]) for r in rep["results"]), key=str)
    assert all(d.parent.name in ("0101", "0102") for d in run_dirs)
    rec = json.loads((trial / "result.json").read_text())["harness_record"]
    assert rec["stage1"] == "run" and rec["stage2"]["ran"] and rec["stage2"]["program_ok"]
    assert rec["scored_requests_before_stage2"] == 0
    assert rec["scored_episode_lock"]["refused"] == 0 and rec["scored_episode_lock"]["unlocked_after_s"] is not None
    assert rec["practice"]["seeds_run"] == [101, 102, 103] and rec["practice"]["episodes"] == 3
    assert rec["practice"]["frozen_by"] == "driver"
    assert rec["library"]["persistent"] and rec["library"]["written"] and rec["library"]["changed"] == ["transport.md"]
    assert rec["library"]["sha_after"] != rec["library"]["sha_before"]
    assert (trial / "aspire" / "program.py").read_text() == REACH
    assert (trial / "aspire" / "practice").is_dir()
    cfg = json.loads((trial / "config.json").read_text())
    assert cfg["harness_config"]["upstream"]["commit"] == library_mod.ASPIRE_COMMIT
    assert cfg["agent_timeout_s"] == 900
    lib = json.loads((tmp_path / "library" / "library.json").read_text())
    assert lib["trials"][0]["practice"]["seeds"] == [101, 102, 103]
    assert (lib["trials"][0]["harness"], lib["trials"][0]["model"]) == ("aspire", models.DEFAULT_MODELS["aspire"])
    assert (tmp_path / "library" / "tasks" / "cubepick" / "reach" / "task_0" / "fix_code.py").read_text() == REACH
    assert "verified on reach" in (tmp_path / "library" / "skills" / "transport.md").read_text()

    # the next layout of the same task: the library holds its selected program, so the trial is Stage 2 only (no agent)
    def no_agent(*a, **k):
        raise AssertionError("a task with a selected program runs no Stage 1")

    monkeypatch.setattr(aspire, "agent_launch", no_agent)
    res2 = run_trial(load_task(CUBEPICK / "cubepick-reach-layout-1"), "aspire", "", job, timeout=900)
    assert res2["exception"] is None and res2["reward"] == 1.0, res2
    rec2 = json.loads((job / res2["trial"] / "result.json").read_text())["harness_record"]
    assert rec2["stage1"] == "reused" and rec2["practice"]["episodes"] == 0
    assert rec2["program"]["reused_from"]["path"].endswith("task_0/fix_code.py")
    assert (
        rec2["program"]["reused_from"]["harness"] == "aspire"
        and rec2["program"]["reused_from"]["trial"] == res["trial"]
    )


CHEAT_AGENT = r'''
import json, os, socket
from pathlib import Path

def send(req):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(os.environ["FOUND_SOCKET"])
    s.sendall((json.dumps(req) + "\n").encode())
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
    s.close()
    return json.loads(buf)

# during Stage 1: look at the scored scene, fake Stage 2's marker, guess the unlock token, pass for the runner
report = {
    "socket_env": os.environ.get("ROBOUSE_SOCKET"),
    "ready_file": (Path.cwd() / ".robouse" / "ready").exists(),
    "observe": send({"op": "observe"}),
    "marker": send({"op": "info", "aspire": "stage2"}),
    "unlock": send({"op": "unlock", "unlock": "0" * 32}),
    "as_runner": send({"op": "act", "action": [0.1, 0.0], "runner": True}),
    "runner_give_up": send({"op": "give_up", "text": "[runner] agent exited", "runner": True}),
}
# and a process that outlives the agent (its own session) and keeps acting through Stage 2
SURVIVOR = """
import json, socket, sys, time
replies, deadline = [], time.time() + 25
while time.time() < deadline:
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(sys.argv[2])
        s.sendall(b'{"op": "act", "action": [0.1, 0.0]}' + b"\\n")
        buf = b""
        while not buf.endswith(b"\\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        s.close()
        replies.append(json.loads(buf))
    except (OSError, ValueError):
        break  # the episode is over
    time.sleep(0.3)
open(sys.argv[1], "w").write(json.dumps(replies))
"""
import subprocess, sys
subprocess.Popen([sys.executable, "-c", SURVIVOR, os.environ["SURVIVOR_OUT"], os.environ["FOUND_SOCKET"]],
                 start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
task_dir = (Path.cwd() / "outputs" / "runs" / "LATEST").resolve() / "cubepick" / "reach" / "task_0"
task_dir.mkdir(parents=True)
(task_dir / "fix_code.py").write_text(PROGRAM)  # a program that would solve the scored episode
lib = Path.cwd() / ".claude" / "skills" / "iterative-debugging" / "skills" / "transport.md"
lib.write_text(lib.read_text() + "\n## Learnt from the scored scene\n")
print("ASPIRE-REPORT " + json.dumps(report), flush=True)
'''


def test_a_trial_whose_agent_reaches_the_scored_episode_during_practice_is_not_scored(tmp_path, monkeypatch) -> None:
    pytest.importorskip("mujoco")
    from robouse.runner import run_trial
    from robouse.tasks import load_task

    _scripted_agent(monkeypatch, CHEAT_AGENT)
    real_launch = aspire.agent_launch

    def found_the_socket(agent, model, prompt, workspace, task, env):  # as if the agent had searched /tmp for it
        launch = real_launch(agent, model, prompt, workspace, task, env)
        launch.env["FOUND_SOCKET"] = env["ROBOUSE_SOCKET"]
        return launch

    monkeypatch.setattr(aspire, "agent_launch", found_the_socket)
    monkeypatch.setenv("ROBOUSE_SANDBOX", "0")
    monkeypatch.setenv("ROBOUSE_ASPIRE_LIBRARY", str(tmp_path / "library"))
    monkeypatch.setenv("SURVIVOR_OUT", str(tmp_path / "survivor.json"))
    res = run_trial(load_task(CUBEPICK / "cubepick-reach-layout-4"), "aspire", "", tmp_path / "job", timeout=900)
    assert res["reward"] == 0.0 and res["exception"].startswith("IntegrityError: the scored episode refused"), res
    trial = tmp_path / "job" / res["trial"]
    rep = _report(trial)
    assert rep["socket_env"] is None and rep["ready_file"] is False
    keys = ("observe", "marker", "unlock", "as_runner", "runner_give_up")
    assert all(not rep[k]["ok"] and "locked" in rep[k]["error"] for k in keys)  # a `runner` mark authorizes nothing
    result = json.loads((trial / "result.json").read_text())
    assert result["status"] == "error" and result["verifier_result"]["rewards"]["reward"] == 0.0
    assert not (trial / "verifier" / "reward.txt").exists()
    rec = result["harness_record"]
    assert rec["stage2"]["ran"]  # Stage 2 ran, and is not scored
    assert result["episode"]["lock"]["refused"] >= 5 and rec["scored_requests_before_stage2"] >= 5
    # the process that outlived the agent got nothing from the scored episode, before the unlock or after it
    deadline = time.time() + 40
    while not (tmp_path / "survivor.json").exists() and time.time() < deadline:
        time.sleep(0.5)
    replies = json.loads((tmp_path / "survivor.json").read_text())
    assert replies and all(not r["ok"] for r in replies)
    assert result["episode"]["steps_used"] == rec["stage2"]["steps_used"]  # every step was Stage 2's
    # and a trial that is not a result writes nothing into the persistent library
    assert rec["library"]["written"] is False and "not a verified result" in rec["library"]["why"]
    assert json.loads((tmp_path / "library" / "library.json").read_text())["trials"] == []
    assert "Learnt from the scored scene" not in (tmp_path / "library" / "skills" / "transport.md").read_text()
    assert not (tmp_path / "library" / "tasks").exists()


def test_a_trial_scored_on_a_practised_scene_is_refused(tmp_path, monkeypatch) -> None:
    pytest.importorskip("mujoco")
    from robouse.runner import run_trial
    from robouse.tasks import load_task

    _scripted_agent(monkeypatch)
    monkeypatch.setenv("ROBOUSE_SANDBOX", "0")
    lib = library_mod.Library(tmp_path / "library")
    lib.prepare()
    m = lib.manifest()
    m["trials"].append(
        {"trial": "earlier", "practice": {"scene_ids": [library_mod.scene_id(("cubepick", "reach", 0), 0)]}}
    )
    (tmp_path / "library" / "library.json").write_text(json.dumps(m))
    monkeypatch.setenv("ROBOUSE_ASPIRE_LIBRARY", str(tmp_path / "library"))
    res = run_trial(load_task(CUBEPICK / "cubepick-reach-layout-0"), "aspire", "", tmp_path / "job", timeout=900)
    assert res["exception"] and "practised on the scene this trial is scored on" in res["exception"]


EVOSEARCH_AGENT = r'''
import json, subprocess
from pathlib import Path

ws = Path.cwd()
baseline = ws / "outputs" / "runs" / "0000-library" / "cubepick" / "reach" / "task_0" / "fix_code.py"
task_dir = ws / "outputs" / "evosearch" / "cubepick" / "reach" / "task_0"
cand = task_dir / "run" / "iter_00" / "candidate_A" / "code.py"
cand.parent.mkdir(parents=True)
cand.write_text(baseline.read_text())  # ASPIRE seeds candidate_A with the fix loop's fix_code.py
r = subprocess.run(["cap-harness", "run", "--benchmark", "cubepick", "--suite", "reach", "--task-id", "0", "--seed", "101",
                    "--program", str(cand), "--output-root", str(cand.parent / "eval")], capture_output=True, text=True)
(task_dir / "evosearch_best_code.py").write_text(cand.read_text())
print("ASPIRE-REPORT " + json.dumps({"baseline": baseline.is_file(), "run": r.stdout[-300:]}), flush=True)
'''


def test_an_evosearch_trial_starts_from_the_fix_loop_s_program(tmp_path, monkeypatch) -> None:
    pytest.importorskip("mujoco")
    from robouse.runner import run_trial
    from robouse.tasks import load_task

    _scripted_agent(monkeypatch, EVOSEARCH_AGENT, skill="evosearch")
    monkeypatch.setenv("ROBOUSE_SANDBOX", "0")
    monkeypatch.setenv("ROBOUSE_ASPIRE_WORKFLOW", "evosearch")
    lib = library_mod.Library(tmp_path / "library")
    lib.prepare()
    task_dir = tmp_path / "library" / "tasks" / "cubepick" / "reach" / "task_0"
    task_dir.mkdir(parents=True)
    (task_dir / "fix_code.py").write_text(REACH)
    m = lib.manifest()  # the fix loop that selected it: the same harness and model as this trial
    fix_loop = {"trial": "fix-loop", "family": ["cubepick", "reach", 0], "harness": "aspire"}
    fix_loop["model"] = models.DEFAULT_MODELS["aspire"]  # what an empty --model runs
    m["trials"].append({**fix_loop, "task_results": {"selected": ["fix_code.py"]}})
    (tmp_path / "library" / "library.json").write_text(json.dumps(m))
    monkeypatch.setenv("ROBOUSE_ASPIRE_LIBRARY", str(tmp_path / "library"))
    res = run_trial(load_task(CUBEPICK / "cubepick-reach-layout-3"), "aspire", "", tmp_path / "job", timeout=900)
    assert res["exception"] is None and res["reward"] == 1.0, res
    trial = tmp_path / "job" / res["trial"]
    rep = _report(trial)
    assert rep["baseline"] and "task_success=True" in rep["run"]
    rec = json.loads((trial / "result.json").read_text())["harness_record"]
    assert rec["workflow"] == "evosearch" and rec["stage1"] == "run"
    assert rec["program"]["path"].endswith("outputs/evosearch/cubepick/reach/task_0/evosearch_best_code.py")
    cfg = json.loads((trial / "config.json").read_text())["harness_config"]
    assert "evosearch_best_code.py" in cfg["prompt"] and "candidate_A" in cfg["prompt"]
    assert (task_dir / "evosearch_best_code.py").read_text() == REACH  # the task's evosearch program, for reuse


@pytest.mark.skipif(sys.platform != "darwin", reason="the macOS Seatbelt sandbox (bubblewrap is checked on Linux runs)")
def test_a_sandboxed_trial_reaches_its_practice_broker(tmp_path, monkeypatch) -> None:
    pytest.importorskip("mujoco")
    from robouse.runner import run_trial
    from robouse.tasks import load_task

    _scripted_agent(monkeypatch)
    monkeypatch.delenv("ROBOUSE_SANDBOX", raising=False)
    monkeypatch.delenv("ROBOUSE_ASPIRE_LIBRARY", raising=False)
    res = run_trial(load_task(CUBEPICK / "cubepick-reach-layout-2"), "aspire", "", tmp_path / "job", timeout=900)
    assert res["exception"] is None and res["reward"] == 1.0, res
    trial = tmp_path / "job" / res["trial"]
    assert json.loads((trial / "config.json").read_text())["sandbox"] == "macos-seatbelt"
    rep = _report(trial)
    assert [r["task_success"] for r in rep["results"]] == [True, True], rep["batch"]
    rec = json.loads((trial / "result.json").read_text())["harness_record"]
    assert rec["library"]["persistent"] is False and (trial / "aspire" / "library-after" / "transport.md").is_file()


# ---- the driver: Stage 2 against fakes -------------------------------------------------------------------------------
WORKSPACE_SRC = ROOT / "src" / "robouse" / "harnesses" / "aspire" / "workspace"
PLANT = 'open({marker!r}, "a").write("{name} imported from the workspace\\n")\n'


def _driver_workspace(tmp_path: Path, agent_cmd: list | None, practice_url: str) -> Path:
    ws = tmp_path / "ws"
    (ws / ".robouse" / "bin").mkdir(parents=True)
    (ws / ".robouse" / "aspire").mkdir()
    shutil.copy(WORKSPACE_SRC / "programs.py", ws / ".robouse" / "bin" / "aspire_programs.py")
    shutil.copy(WORKSPACE_SRC / "driver.py", ws / ".robouse" / "aspire" / "driver.py")
    cfg = {"agent": "claude-code", "agent_cmd": agent_cmd, "practice_deadline": time.time() + 600}
    cfg.update(practice_url=practice_url, program_hint="fix_code.py")
    (ws / ".robouse" / "aspire" / "driver.json").write_text(json.dumps(cfg))
    (ws / ".robouse" / "aspire" / "driver.key").write_text("freeze-key")
    for name in ("socket", "ready"):  # what the runner wrote before: both name the scored socket
        (ws / ".robouse" / name).write_text("/tmp/robouse-0000000000.sock")
    return ws


class _FakeEpisode(threading.Thread):
    """A scored episode's socket: records every request; answers an image to `observe` with `inline`."""

    def __init__(self, path: str):
        super().__init__(daemon=True)
        import base64
        import io

        import numpy as np
        from PIL import Image

        buf = io.BytesIO()
        Image.fromarray(np.full((4, 6, 3), 90, dtype=np.uint8)).save(buf, format="PNG")
        self.png = base64.b64encode(buf.getvalue()).decode()
        self.path, self.requests = path, []
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(path)
        self.srv.listen(8)

    def run(self) -> None:
        while True:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            with conn:
                buf = b""
                while not buf.endswith(b"\n"):
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                req = json.loads(buf)
                self.requests.append(req)
                if req.get("op") == "observe" and req.get("inline"):
                    res: dict = {"images": {"agentview": self.png}}
                elif req.get("op") == "status":
                    res = {"finished": False}
                else:
                    res = {}
                conn.sendall((json.dumps({"ok": True, "result": res}) + "\n").encode())


def _fake_broker(program: str) -> tuple[str, list, Any]:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    bodies: list = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a) -> None:
            pass

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            bodies.append({"path": self.path, **body})
            raw = json.dumps({"program": program, "program_path": "fix_code.py"}).encode()  # the key is checked below
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}/tok", bodies, srv


def test_the_driver_imports_nothing_from_the_workspace_and_sends_its_token_with_every_request(tmp_path) -> None:
    marker = str(tmp_path / "planted.txt")
    # the agent plants modules where an import would find them: the driver's own folder, the program contract's
    # folder and the workspace itself (the working folder), after the driver started
    plant = "import os, pathlib\nws = pathlib.Path.cwd()\n"
    for folder in ("", ".robouse/bin", ".robouse/aspire"):
        for name in ("PIL", "numpy", "base64", "json"):
            target = f"ws / {folder!r} / {name!r} / '__init__.py'" if folder else f"ws / {name!r} / '__init__.py'"
            plant += f"t = {target}\nt.parent.mkdir(parents=True, exist_ok=True)\nt.write_text({PLANT.format(marker=marker, name=name)!r})\n"
    program = (
        "img = robo.image('agentview')\nresult = {'mean': float(img.mean()), 'shape': [int(n) for n in img.shape]}\n"
    )
    url, bodies, srv = _fake_broker(program)
    ws = _driver_workspace(tmp_path, [sys.executable, "-c", plant], url)
    sock = f"/tmp/robouse-{os.getpid():x}{int(time.time() * 1000) % 100000:x}.sock"
    episode = _FakeEpisode(sock)
    episode.start()
    try:
        env = {"PATH": os.environ["PATH"], "ROBOUSE_SOCKET": sock, "PYTHONPATH": str(ws / ".robouse" / "bin")}
        r = subprocess.run(
            [sys.executable, "-I", str(ws / ".robouse" / "aspire" / "driver.py")],
            input="T" * 32 + "\n",
            capture_output=True,
            text=True,
            cwd=ws,
            env=env,
            timeout=120,
        )
    finally:
        episode.srv.close()
        srv.shutdown()
        os.unlink(sock)
    assert r.returncode == 0, r.stderr
    assert not Path(marker).exists(), Path(marker).read_text()  # nothing planted was imported
    stage2 = json.loads((ws / ".robouse" / "aspire" / "stage2.json").read_text())["stage2"]
    assert stage2["program_ok"] and stage2["result"] == {"mean": 90.0, "shape": [4, 6, 3]}, stage2
    # every request to the scored episode carried the token; the first unlocked it
    assert episode.requests and all(q.get("unlock") == "T" * 32 for q in episode.requests)
    assert episode.requests[0]["op"] == "unlock" and episode.requests[-1]["op"] == "done"
    # the freeze carried the driver's key; the key file and the files naming the socket were gone before the agent ran
    assert bodies == [{"path": "/tok/freeze", "by": "driver", "key": "freeze-key"}]
    assert not any((ws / ".robouse" / n).exists() for n in ("socket", "ready", "aspire/driver.key"))


def test_stopping_the_driver_stops_the_agent(tmp_path) -> None:
    # the agent runs in a session of its own (so its whole group can be stopped at the deadline): a SIGTERM or SIGINT
    # to the driver (the runner's timeout, Ctrl-C) must take it down too
    pids = tmp_path / "pids.txt"
    agent = (
        "import os, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        f"open({str(pids)!r}, 'w').write(f'{{os.getpid()}} {{child.pid}}')\n"
        "time.sleep(120)\n"
    )
    for sig in (signal.SIGTERM, signal.SIGINT):
        pids.unlink(missing_ok=True)
        ws = _driver_workspace(tmp_path / sig.name, [sys.executable, "-c", agent], "http://127.0.0.1:9/none")
        d = subprocess.Popen(
            [sys.executable, "-I", str(ws / ".robouse" / "aspire" / "driver.py")],
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=ws,
            env={"PATH": os.environ["PATH"]},
        )
        assert d.stdin is not None
        d.stdin.write(b"\n")
        d.stdin.close()
        deadline = time.time() + 60
        while not (pids.exists() and len(pids.read_text().split()) == 2) and time.time() < deadline:
            time.sleep(0.1)
        agent_pid, child_pid = map(int, pids.read_text().split())
        d.send_signal(sig)
        d.wait(timeout=30)
        deadline = time.time() + 20
        alive = [agent_pid, child_pid]
        while alive and time.time() < deadline:
            alive = [p for p in alive if _alive(p)]
            time.sleep(0.2)
        assert not alive, f"{sig.name}: still running {alive}"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # a zombie waiting for its new parent counts as gone
        out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    except OSError:
        return True
    return bool(out) and not out.startswith("Z")


# ---- the agent's command --------------------------------------------------------------------------------------------
def test_claude_code_gets_aspire_s_prompt_and_the_subagent_tool(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    launch = aspire.agent_launch("claude-code", "claude-sonnet-5", "ASPIRE PROMPT", tmp_path, None, {})
    cmd = launch.cmd
    assert cmd[cmd.index("-p") + 1] == "ASPIRE PROMPT"  # no Robo Use robo prefix: ASPIRE's own coordinator prompt
    assert cmd[cmd.index("--tools") + 1] == "Bash,Read,Write,Edit,Glob,Grep,Agent,Skill"
    assert launch.env["CLAUDE_CONFIG_DIR"].startswith(str(tmp_path))
    # the coordinator waits for its background worker: print mode must not stop it 10 minutes after the last turn
    assert launch.env["CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"] == "0"


def test_codex_gets_aspire_s_prompt(tmp_path, monkeypatch) -> None:
    from robouse.harnesses import credentials

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(credentials, "clean_codex_home", lambda *a, **k: str(tmp_path / "codex-home"))
    launch = aspire.agent_launch("codex", "gpt-6-astra", "ASPIRE PROMPT", tmp_path, None, {})
    assert launch.cmd[0] == "codex" and launch.cmd[-1] == "ASPIRE PROMPT"
