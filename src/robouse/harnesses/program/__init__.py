"""The `program` and `program-codex` harnesses: code as policy, scored on one explicit submission.

The agent (Claude Code or Codex) never drives the scored episode. It writes `solution/solve.py`, defining
`solve(robo)`, and develops it with `robo-dev` in its workspace (workspace/robo_dev.py):

- `robo-dev run` runs the current program on a practice episode: the task's own episode server on the trial's own
  seed, so a fresh reset of the very scene that is scored. A development run reports what the program printed, its
  tool calls, the robot's state and camera keyframes, and nothing the episode server judges: no success, no outcome,
  no safety events, no result.json. (A task that ends at its first success still ends early in a development run,
  without saying why; the scenario tasks this harness was built for judge only after the program.)
- `robo-dev submit` hands the program to the trial's broker, which keeps a copy outside the sandbox. Only the last
  submission counts; the workspace file is never read for scoring.

When the agent exits, the driver (ASPIRE's, workspace/driver.py, with this harness's names) freezes the broker, gets
the last submission back from it, unlocks the scored episode and runs `solve(robo)` once on it from its fresh reset,
with no model in the loop, then sends `robo done`. No submission: it gives up, a scored 0 (an agent that failed before
submitting leaves the episode to the runner, an infrastructure failure).

The program contract is ASPIRE's (aspire/workspace/programs.py: `math` and `numpy` imports only, no classes, `with`,
`global`, `nonlocal`, `del` or underscore names, a short list of builtins), so a program cannot reach files, processes
or the network. The scored run and development runs execute under the same contract and the same `robo` object.

Unlike `aspire`, practice here is on the scored scene itself: the task's scene is fixed (the scenario backends replay a
recorded scene), and the benchmark condition is "develop on the environment, submit once", as code-as-policy is
evaluated in omni-safety. What keeps the score honest is the hidden verdict, the explicit submission, and the fresh
reset, not a held-out scene.
"""

from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

from ... import config
from ..aspire import WORKSPACE_FILES as ASPIRE_FILES
from ..aspire import _requests_before_stage2, _shim
from ..aspire.broker import PracticeBroker, WorkspaceReader, _reply

HERE = Path(__file__).resolve().parent
AGENTS = {"program": "claude-code", "program-codex": "codex"}
CLAUDE_MAX_TURNS = 1000
BASH_MAX_TIMEOUT_MS = 3600 * 1000
MIN_TIMEOUT_S = 2 * 3600  # writing and testing a program: two hours unless --timeout says otherwise
MAX_SOURCE_BYTES = 256 * 1024
GIVE_UP_CHARS = 4000  # a `robo-dev give-up` reason, as long as a text-mode plan
CALL = "\n\nresult = solve(robo)\n"  # what the driver appends to the submitted source

# ASPIRE's driver, with this harness's folder and words; each replacement must apply (a changed driver fails the build)
DRIVER_EDITS = (
    ('print(f"[aspire] {msg}"', 'print(f"[program] {msg}"'),
    ('text = f"aspire: frozen program {sha[:12]} "', 'text = f"program: submitted program {sha[:12]} "'),
    ("else f\"no program was selected ({cfg.get('program_hint')} is missing)\"", 'else "nothing was submitted"'),
    ('send({"op": "give_up", "text": f"aspire: {why}"})', 'send({"op": "give_up", "text": f"program: {why}"})'),
    (  # `robo-dev give-up`: the agent's reason ends the scored episode, as `robo give-up` does in a live trial
        '    why = (\n        "practice time ran out before a program was selected"\n        if stopped',
        '    why = (\n        f"the agent gave up: {frozen[\'gave_up\']}"\n        if frozen.get("gave_up")\n'
        '        else "practice time ran out before a program was selected"\n        if stopped',
    ),
)


def driver_source() -> str:
    src = (ASPIRE_FILES / "driver.py").read_text()
    for old, new in DRIVER_EDITS:
        if old not in src:
            raise RuntimeError(f"the aspire driver changed: {old!r} is not in it")
        src = src.replace(old, new)
    return src


def _programs():
    from ..aspire.workspace import programs

    return programs


class ProgramBroker(PracticeBroker):
    """The practice broker for development runs on the scored scene: the trial's seed is the only practice seed, and
    nothing the episode server judges goes back to the agent. Adds `POST /submit {source}` and `POST /give_up {reason}`
(the agent declines: nothing runs on the scored episode, which ends with the reason); the later of the two counts."""

    def __init__(self, *a: Any, **kw: Any):
        super().__init__(*a, **kw)
        self.submissions: list[dict] = []
        self.submitted: str | None = None
        self.gave_up: str | None = None  # the reason of a `robo-dev give-up` made after the last submission
        self.sub_lock = threading.Lock()
        self.t0 = time.time()
        self.deadline: float | None = None  # when the driver stops development (set by build)

    def refusal(self, seed: Any) -> str | None:
        if self.frozen is not None:
            return "development is over: the trial is frozen and the submitted program is being scored"
        if len(self.order) >= self.max_episodes:
            return f"the development budget is used: {self.max_episodes} runs in this trial"
        return None

    def start_episode(self, seed: Any, label: str = "") -> tuple[int, dict]:
        status, out = super().start_episode(self.dev[0], label)  # the agent never picks the seed
        if status == 200:
            out = {"id": out["id"], "info": out.get("info") or {}}
        return status, out

    def request(self, eid: str, req: Any) -> tuple[int, dict]:
        """As practice forwards it, without the episode's ending reason (a task that ends on success says so)."""
        status, reply = super().request(eid, req)
        if isinstance(reply, dict) and str(reply.get("error", "")).startswith("episode finished"):
            reply["error"] = "episode finished"  # the server names the outcome
        res = reply.get("result") if isinstance(reply, dict) else None
        if isinstance(res, dict):
            if isinstance(res.get("episode"), str) and res["episode"].startswith("finished"):
                res["episode"] = "finished"
            res.pop("outcome", None)  # the status op's
        return status, reply

    def finish(self, eid: str, op: str, text: str) -> tuple[int, dict]:
        status, out = super().finish(eid, "give_up", "development run")  # never judged as an attempt
        if status != 200:
            return status, out
        v = out.get("verdict") or {}
        return 200, {"ended": True, "steps_used": v.get("steps_used")}

    def files(self, ep: Any) -> list[str]:
        return []  # result.json, the physics probe and the trace hold the episode server's judgment

    def file(self, eid: str, rel: str) -> tuple[int, bytes | dict]:
        return 404, {"error": "development runs return their pictures through robo.image(), not files"}

    def submit(self, source: Any) -> tuple[int, dict]:
        if not isinstance(source, str) or not source.strip():
            return 400, {"error": "submit the program's source (solution/solve.py)"}
        if len(source.encode()) > MAX_SOURCE_BYTES:
            return 413, {"error": f"the program is larger than {MAX_SOURCE_BYTES // 1024} KiB"}
        programs = _programs()
        try:
            tree = programs.validate(source + CALL)
        except programs.ProgramRejected as e:
            return 400, {"error": str(e)}
        if not any(getattr(n, "name", None) == "solve" and len(n.args.args) == 1 for n in tree.body):
            return 400, {"error": "the program must define solve(robo) at the top level"}
        with self.sub_lock:
            if self.frozen is not None:
                return 409, {"error": "development is over: the trial is frozen"}
            n = len(self.submissions) + 1
            sha = hashlib.sha256(source.encode()).hexdigest()
            d = self.record_dir / "submissions"
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{n:03d}.py").write_text(source)
            self.submissions.append({"n": n, "sha256": sha, "at_s": round(time.time() - self.t0, 1)})
            self.submitted = source
            self.gave_up = None
        return 200, {"submission": n, "sha256": sha}

    def give_up(self, reason: Any) -> tuple[int, dict]:
        if not isinstance(reason, str) or not reason.strip():
            return 400, {"error": "give a reason"}
        with self.sub_lock:
            if self.frozen is not None:
                return 409, {"error": "development is over: the trial is frozen"}
            self.gave_up = reason.strip()[:GIVE_UP_CHARS]
            self.submitted = None
            self.submissions.append({"gave_up": self.gave_up, "at_s": round(time.time() - self.t0, 1)})
        return 200, {"gave_up": True}

    def status(self) -> dict:
        last = self.submissions[-1] if self.submissions else None
        return {
            "runs": len(self.order),
            "max_runs": self.max_episodes,
            "submissions": len(self.submissions),
            "last_submission": last,
            **({"gave_up": self.gave_up} if self.gave_up else {}),
            "frozen": self.frozen is not None,
            **({"minutes_left": max(0, round((self.deadline - time.time()) / 60))} if self.deadline else {}),
        }

    def _handle(self, h: BaseHTTPRequestHandler, method: str) -> None:
        import secrets

        parts = [p for p in h.path.split("?")[0].split("/") if p]
        ours = len(parts) == 2 and secrets.compare_digest(parts[0], self.token) and parts[1] in ("status", "submit", "give_up")
        if not ours:
            return super()._handle(h, method)
        if parts[1] == "status" and method == "GET":
            return _reply(h, 200, self.status())
        if parts[1] == "submit" and method == "POST":
            n = int(h.headers.get("Content-Length") or 0)
            if n > 2 * MAX_SOURCE_BYTES:
                return _reply(h, 413, {"error": "request too large"})
            try:
                body = json.loads(h.rfile.read(n).decode() or "{}")
            except ValueError:
                return _reply(h, 400, {"error": "the body is not JSON"})
            return _reply(h, *self.submit(body.get("source")))
        if parts[1] == "give_up" and method == "POST":
            n = int(h.headers.get("Content-Length") or 0)
            if n > 64 * 1024:
                return _reply(h, 413, {"error": "request too large"})
            try:
                body = json.loads(h.rfile.read(n).decode() or "{}")
            except ValueError:
                return _reply(h, 400, {"error": "the body is not JSON"})
            return _reply(h, *self.give_up(body.get("reason")))
        return _reply(h, 404, {"error": f"unknown request {method} /{parts[1]}"})


PROGRAM_FRAMING_EDITS = (
    ("Runs take simulated time and real time", "Runs take robot time and real time"),
    ("Every simulated step counts", "Every step counts"),
)


def frame_program_doc(text: str, robot_framing: str = "simulated") -> str:
    if robot_framing == "simulated":
        return text
    if robot_framing != "real":
        raise ValueError(f"unknown robot framing: {robot_framing!r}")
    for old, new in PROGRAM_FRAMING_EDITS:
        if old not in text:
            raise ValueError(f"expected PROGRAM.md phrase {old!r} for real robot framing")
        text = text.replace(old, new, 1)
    return text


def prepare_workspace(ws: Path, values: dict, robot_framing: str = "simulated") -> None:
    py = sys.executable
    bin_dir = ws / ".robouse" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "aspire_programs.py").write_text((ASPIRE_FILES / "programs.py").read_text())
    (bin_dir / "robo-dev").write_text(_shim(HERE / "workspace" / "robo_dev.py", py))
    (bin_dir / "robo-dev").chmod(0o755)
    own = ws / ".robouse" / "program"
    own.mkdir(parents=True, exist_ok=True)
    (own / "driver.py").write_text(f"#!{py}\n" + driver_source())
    text = frame_program_doc((HERE / "workspace" / "PROGRAM.md").read_text(), robot_framing)
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", str(v))
    (ws / "PROGRAM.md").write_text(text)
    sol = ws / "solution"
    sol.mkdir(exist_ok=True)
    if not (sol / "solve.py").exists():
        (sol / "solve.py").write_text((HERE / "workspace" / "solve_template.py").read_text())


def agent_launch(agent: str, model: str, prompt: str, workspace: Path, task: Any, env: dict) -> Any:
    """Claude Code or Codex, as the claude-code and codex harnesses start them, with this harness's prompt instead of
    Robo Use's robot-control prefix."""
    from .. import CLAUDE_TOOLS, _claude_code, _codex

    if agent == "claude-code":
        launch = _claude_code(
            model, prompt, workspace, task, env, prefix="", tools=CLAUDE_TOOLS, max_turns=CLAUDE_MAX_TURNS
        )
        # a development run can outlast Claude Code's default two minutes for one shell command
        launch.env.update(BASH_DEFAULT_TIMEOUT_MS="600000", BASH_MAX_TIMEOUT_MS=str(BASH_MAX_TIMEOUT_MS))
        return launch
    return _codex(model, prompt, workspace, task, env, prefix="")


def build(harness: str, model: str, prompt: str, workspace: Path, task: Any, env: dict) -> Any:
    from .. import ROBOT_FRAMING_ENV, Launch, _flag

    agent = AGENTS[harness]
    facts = json.loads(env.get("_ROBOUSE_TRIAL") or "{}")  # read before the agent's builder removes private variables
    tdir = Path(env["_ROBOUSE_TRIAL_DIR"])
    seed = int(facts["seed"]) if facts.get("seed") is not None else int(task.spec.get("seed", 0))
    max_runs = int(config.env("ROBOUSE_PROGRAM_DEV_RUNS") or 40)
    workers = int(config.env("ROBOUSE_PROGRAM_DEV_WORKERS") or 2)
    timeout_s = float(facts.get("timeout_s") or MIN_TIMEOUT_S)
    reserve = min(1800.0, max(300.0, 0.15 * timeout_s))
    ws = Path(workspace).resolve()
    reader = WorkspaceReader(ws)
    own_dir = ws / ".robouse" / "program"
    max_steps = int(task.spec.get("max_steps") or 0)
    prepare_workspace(ws, {"max_runs": max_runs, "max_steps": max_steps}, env.get(ROBOT_FRAMING_ENV, "simulated"))
    rec = tdir / "program"

    broker: ProgramBroker

    def snapshot() -> dict:
        """At freeze, outside the sandbox: the last submission (never the workspace file)."""
        src = broker.submitted
        out: dict[str, Any] = {"submissions": len(broker.submissions)}
        (rec / "solution").mkdir(parents=True, exist_ok=True)
        ws_copy = reader.read_text(ws / "solution" / "solve.py")  # for the record only
        if ws_copy is not None:
            (rec / "solution" / "workspace-solve.py").write_text(ws_copy)
        if broker.gave_up:
            out["gave_up"] = broker.gave_up
            return out
        if src is None:
            return out
        (rec / "solution" / "submitted-solve.py").write_text(src)
        last = broker.submissions[-1]
        out.update(program=src + CALL, program_path=f"submission {last['n']} ({last['sha256'][:12]})")
        return out

    broker = ProgramBroker(
        task.path,
        rec,
        [seed],
        [],
        lambda s: s,
        set(),
        max_runs,
        workers,
        float(task.agent_timeout_s),
        split=facts.get("split"),
        snapshot=snapshot,
    )
    practice_s = max(60.0, timeout_s - reserve)
    broker.deadline = time.time() + practice_s
    url = broker.start()
    env["ROBOUSE_PRACTICE_URL"] = url  # also lets the macOS sandbox allow this local port
    key_file = own_dir / "driver.key"  # the freeze key: the driver reads and deletes it before the agent starts
    key_file.write_text(broker.freeze_key)
    key_file.chmod(0o600)
    preamble = (
        (HERE / "prompt.md").read_text().replace("{{max_runs}}", str(max_runs)).replace("{{minutes}}", str(int(practice_s // 60)))
    )
    from .. import ROBOT_FRAMING_ENV, frame_prompt

    try:
        preamble = frame_prompt(preamble, env.pop(ROBOT_FRAMING_ENV, "simulated"), program=True)
        text = preamble + prompt
        inner = agent_launch(agent, model, text, ws, task, env)
    except BaseException:
        broker.stop()
        raise
    (own_dir / "driver.json").write_text(
        json.dumps(
            {
                "agent": agent,
                "agent_cmd": inner.cmd,
                "practice_deadline": broker.deadline,
                "practice_url": url,
                "program_hint": "solution/solve.py, submitted with robo-dev submit",
            },
            indent=2,
        )
    )
    cfg = {
        "agent": agent,
        "scored_seed": seed,
        "dev_runs": max_runs,
        "dev_workers": workers,
        "practice_deadline_s": round(practice_s),
        "effort": _flag(inner.cmd, "--effort"),
        "prompt": text,
    }
    state: dict[str, Any] = {}

    def stop() -> None:
        try:
            if inner.stop is not None:
                inner.stop()
        finally:
            broker.stop()
            try:
                state.update(_record(tdir, ws, reader, broker, cfg))
            except Exception as e:  # noqa: BLE001 - the trial's result stands; the record says what failed
                state.update(cfg, record_error=f"{type(e).__name__}: {e}")
            finally:
                reader.close()

    return Launch(
        # -I: the driver imports nothing from its own folder, the workspace or PYTHON* variables (the agent's)
        [sys.executable, "-I", str(own_dir / "driver.py")],
        env,
        helper=inner.helper,
        stop=stop,
        stop_file=inner.stop_file,
        notes=dict(inner.notes),
        config=cfg,
        record=lambda trial_ok: state,
    )


def _record(tdir: Path, ws: Path, reader: WorkspaceReader, broker: ProgramBroker, cfg: dict) -> dict:
    rec = tdir / "program"
    rec.mkdir(parents=True, exist_ok=True)
    practice = broker.record()
    frozen = broker.frozen or {}
    stage2_text = reader.read_text(ws / ".robouse" / "program" / "stage2.json")
    try:
        driver = json.loads(stage2_text) if stage2_text else {}
    except ValueError:
        driver = {}
    try:  # the episode server's own count, in its signed verdict: requests it refused while locked
        lock = json.loads((tdir / "episode" / "result.json").read_text()).get("lock") or {}
    except (OSError, ValueError):
        lock = {}
    before = lock.get("refused") if lock else _requests_before_stage2(tdir / "episode" / "trace.jsonl")
    (rec / "practice.json").write_text(json.dumps({**practice, "submissions": broker.submissions}, indent=2))
    return {
        "agent": cfg["agent"],
        "dev_runs": {k: v for k, v in practice.items() if k in ("episodes", "max_episodes", "workers", "frozen_by")},
        "submissions": broker.submissions,
        "program": {
            "submitted": bool(frozen.get("program")),
            "gave_up": frozen.get("gave_up"),
            "path": frozen.get("program_path"),
            "sha256": (driver.get("stage2") or {}).get("program_sha256"),
        },
        "stage2": driver.get("stage2") or {"ran": False, "error": "the driver left no report"},
        "agent_exit": driver.get("agent_exit"),
        "agent_stopped_at_deadline": driver.get("agent_stopped_at_deadline"),
        "scored_requests_before_stage2": before,
        "scored_episode_lock": lock or None,
    }


def default_timeout(harness: str) -> float:
    return MIN_TIMEOUT_S if harness in AGENTS else 0.0


__all__ = ["AGENTS", "ProgramBroker", "build", "default_timeout"]
