"""A scripted stand-in model for checking the `aspire` harness end to end without model credentials.

It serves OpenAI chat completions (what the trial's model gateway sends a `glm/...` model, so Claude Code reaches it
through the real gateway, translated from Anthropic Messages) and answers with scripted tool calls that walk Claude
Code through ASPIRE's iterative-debugging workflow on a CaP-X task, using the workspace's own tools and ASPIRE's own
scripts: the coordinator reads the skill, checks progress (gen_progress.py), stages a worker from ASPIRE's template
(dispatch.py worker) and dispatches it with the Agent tool; the worker takes a scene snapshot, writes v00, sweeps the
development seeds with `cap-harness run-batch`, fixes the failure mode in v01, selects fix_code.py, runs the unseen-check
seeds once, writes findings.md and a skill_report.json (checked by campaign.py); the coordinator stages a verifier
(dispatch.py verify, which lints the proposal) and dispatches it; the verifier re-solves the task from the proposal on
the first development seeds and writes verification_report.json; the coordinator promotes the verified entry into the
library. The run shows that the plumbing works (practice, selection, Stage 2, the library), not what any model would
do.

The programs are not in this script, which sits in a checkout that a trial's agent may be able to read: give them in a
JSON file kept elsewhere (--programs FILE: per suite, "v00" with one flaw, "v01" without it, and optionally "flaw":
[mode, what went wrong] and "entry": [library file, entry title]). Without one, every suite runs probe programs that
read the robot's state and solve nothing, and on the libero-pro suites a probe of the camera images.

    python3 tools/aspire/standin_model.py --port 18940 --log /tmp/standin.jsonl --programs ~/standin-programs.json
    GLM_API_KEY=standin GLM_BASE_URL=http://127.0.0.1:18940/v1 ROBOUSE_SPEND_CAP_USD=0 \\
      robouse run --task tasks/capx/capx-cube-stack-s1 --harness aspire --model glm/glm-5.3 --out runs/standin

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---- the programs: probes by default (they solve nothing); a task's real v00 and v01 come from --programs ------------
STATE_PROBE = """state = robo.observe()["state"]
info = robo.info()
result = {"fields": sorted(state)[:20], "skills": len(info.get("skills") or ()), "version": VERSION}
"""
PROGRAMS: dict[str, dict[str, str]] = {}
# LIBERO-PRO (libero-pro suite, vision tasks): a probe, not a solution. It reads both cameras as arrays (robo.image)
# and their calibration (robo.info), then makes one small move with the task's move_to and grip skills.
VISION_PROBE = """hand = robo.observe()["state"]["hand_pos"]
info = robo.info()
front = robo.image("agentview")
wrist = robo.image("robot0_eye_in_hand")
robo.move_to(float(hand[0]), float(hand[1]), float(hand[2]) + LIFT)
robo.grip(-1.0)
result = {"front": [int(n) for n in front.shape], "wrist": [int(n) for n in wrist.shape],
          "calibrated_cameras": len(info.get("cameras") or ()), "front_mean": float(front.mean())}
"""
for libero_suite in (
    "libero_goal_swap",
    "libero_goal_task",
    "libero_object_swap",
    "libero_object_task",
    "libero_spatial_swap",
    "libero_spatial_task",
    "libero_10_swap",
    "libero_10_task",
):
    PROGRAMS[libero_suite] = {"v00": VISION_PROBE.replace("LIFT", "0.02"), "v01": VISION_PROBE.replace("LIFT", "0.05")}

FLAW: dict[str, tuple[str, str]] = {}
ENTRY: dict[str, tuple[str, str]] = {}
for libero_suite in list(PROGRAMS):
    FLAW[libero_suite] = ("perception", "the probe found the cameras but not the objects")
    ENTRY[libero_suite] = ("localize.md", "Camera images and calibration through robo")


def load_programs(path: str) -> None:
    """Per suite: {"v00": ..., "v01": ..., "flaw": [mode, why], "entry": [file, title]} from a JSON file."""
    with open(path) as f:
        data = json.load(f)
    for suite, d in data.items():
        PROGRAMS[suite] = {"v00": d["v00"], "v01": d["v01"]}
        if d.get("flaw"):
            FLAW[suite] = (str(d["flaw"][0]), str(d["flaw"][1]))
        if d.get("entry"):
            ENTRY[suite] = (str(d["entry"][0]), str(d["entry"][1]))


def programs_for(suite: str) -> dict[str, str]:
    return PROGRAMS.get(suite) or {
        "v00": STATE_PROBE.replace("VERSION", "0"),
        "v01": STATE_PROBE.replace("VERSION", "1"),
    }


def flaw_for(suite: str) -> tuple[str, str]:
    return FLAW.get(suite) or ("probe", "the probe read the state and did not try the task")


def entry_for(suite: str) -> tuple[str, str]:
    return ENTRY.get(suite) or ("transport.md", "Read the robot's state before moving (stand-in probe)")


# the numbers ASPIRE's scoring one-liner prints, read back by the next step
SCORE = (
    "python3 -c \"import json,sys; rows=[json.loads(l) for l in open(sys.argv[1])]; "
    "print('passed', sum(1 for r in rows if r.get('task_success')), 'of', len(rows))\" {path}"
)


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
    return ""


def campaign(prompt: str) -> dict:
    """The names, seeds and paths the coordinator's prompt (or a staged worker or verifier prompt) gives."""

    def grab(pattern: str, default: str = "") -> str:
        m = re.search(pattern, prompt)
        return m.group(1).strip() if m else default

    c = {
        "benchmark": grab(r"BENCHMARK[=:]\s*`?([\w-]+)"),
        "suite": grab(r"SUITE[=:]\s*`?([\w-]+)"),
        "task_id": grab(r"TASK_ID[=:]\s*`?(\d+)", "0"),
        "run_root": grab(r"RUN_ROOT[=:]\s*`?(\S+?)`?(?:,|\s)"),
        "dev": grab(r"development seeds ([\d,\-]+)").strip(","),
        "unseen": grab(r"unseen-check seeds ([\d,\-]+)").strip(","),
    }
    c["task_dir"] = f"{c['run_root']}/{c['benchmark']}/{c['suite']}/task_{c['task_id']}"
    c["common"] = f"--benchmark {c['benchmark']} --suite {c['suite']} --task-id {c['task_id']}"
    return c


def first_seeds(spec: str, n: int) -> str:
    seeds: list[int] = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        seeds += list(range(int(a), int(b) + 1)) if b else [int(a)]
    return " ".join(str(s) for s in seeds[:n])


def bash(command: str, description: str, timeout_ms: int = 600000) -> dict:
    return {"name": "Bash", "input": {"command": command, "description": description, "timeout": timeout_ms}}


def heredoc(path: str, text: str) -> str:
    return f"mkdir -p \"$(dirname {path})\" && cat > {path} <<'STANDIN_EOF'\n{text}STANDIN_EOF\n"


# ---- the three roles ------------------------------------------------------------------------------------------------
def coordinator_plan(c: dict) -> list[tuple[str, str, dict | str]]:
    """The coordinator's steps as (kind, key, action): tool steps are matched to the conversation by their
    description; a wait step ends the turn until a notification naming the subagent arrives, as ASPIRE's coordinator
    goes idle after a dispatch (Claude Code runs the Agent tool's subagents in the background and re-invokes the
    coordinator when one finishes)."""
    scripts = ".claude/skills/iterative-debugging/scripts"
    rr = c["run_root"]
    vdir = f"{rr}/verification/{c['benchmark']}__{c['suite']}__task_{c['task_id']}"
    worker_desc = f"Fix loop: {c['suite']}/task_{c['task_id']}"
    verifier_desc = f"Verify skills: {c['suite']}/task_{c['task_id']}"
    skill, title = entry_for(c["suite"])
    lib = f".claude/skills/iterative-debugging/skills/{skill}"
    entry = (
        f"\n## {title}\n\n**Trigger.** CaP-X's privileged API on a {c['suite']} task: "
        f"{flaw_for(c['suite'])[1]}.\n\n```python\n{programs_for(c['suite'])['v01']}```\n\n"
        f"**Evidence.** {c['benchmark']}/{c['suite']}/task_{c['task_id']}: verified by an independent verifier "
        "(verification_report.json) on the first development seeds.\n"
    )
    read = bash(
        "sed -n 1,20p .claude/skills/iterative-debugging/SKILL.md; sed -n 1,30p docs/robouse.md",
        "Read the iterative-debugging skill and Robo Use's mapping",
    )
    stage_worker = bash(
        f"python3 {scripts}/gen_progress.py --run-root {rr} && sed -n 1,25p {rr}/progress.md && "
        f"python3 {scripts}/dispatch.py worker {c['common']} --gpu none --run-root {rr}",
        "Check progress and stage the Stage 1 worker from ASPIRE's template",
    )
    dispatch_worker = {
        "name": "Agent",
        "input": {
            "description": worker_desc,
            "subagent_type": "general-purpose",
            "prompt": (
                f"ROLE: worker. Read {rr}/prompts/worker_{c['suite']}_{c['task_id']}.txt and follow it exactly "
                f"(docs/robouse.md maps it onto this Robo Use trial). BENCHMARK={c['benchmark']} "
                f"SUITE={c['suite']} TASK_ID={c['task_id']} RUN_ROOT={rr} , development seeds {c['dev']}, "
                f"unseen-check seeds {c['unseen']}."
            ),
        },
    }
    stage_verifier = bash(
        f"python3 {scripts}/gen_progress.py --run-root {rr} && cat {c['task_dir']}/skill_report.json && "
        f"python3 {scripts}/dispatch.py verify {c['common']} --gpu none --run-root {rr}",
        "Stage a verifier for the proposed skill (dispatch.py lints the proposal)",
    )
    dispatch_verifier = {
        "name": "Agent",
        "input": {
            "description": verifier_desc,
            "subagent_type": "general-purpose",
            "prompt": (
                f"ROLE: verifier. Read {rr}/prompts/verify_{c['suite']}_{c['task_id']}.txt and follow it exactly. "
                f"VERIFY_DIR={vdir} BENCHMARK={c['benchmark']} SUITE={c['suite']} TASK_ID={c['task_id']} "
                f"RUN_ROOT={rr} , development seeds {c['dev']}."
            ),
        },
    }
    promote = bash(
        f"python3 -c \"import json; r=json.load(open('{vdir}/verification_report.json')); "
        "print(r['verdict'], r['passes'], '/', r['trials']); assert r['verdict'] == 'verified'\" && "
        f"cat >> {lib} <<'STANDIN_EOF'\n{entry}STANDIN_EOF\n"
        f"python3 {scripts}/campaign.py --skill-library-sha",
        "Promote the verified proposal into the library",
    )
    final = (
        f"Campaign finished for {c['benchmark']}/{c['suite']}/task_{c['task_id']}: Stage 1 done "
        "(fix_code.py selected), one proposal verified and promoted. Stage 2 is Robo Use's."
    )
    return [
        ("tool", "", read),
        ("tool", "", stage_worker),
        ("tool", "", dispatch_worker),
        ("wait", worker_desc, "Dispatched the Stage 1 worker; idle until it returns."),
        ("tool", "", stage_verifier),
        ("tool", "", dispatch_verifier),
        ("wait", verifier_desc, "Dispatched the verifier; idle until it returns."),
        ("tool", "", promote),
        ("final", "", final),
    ]


def coordinator(msgs: list[dict], c: dict) -> dict | str:
    done_calls = [
        json.loads((tc.get("function") or {}).get("arguments") or "{}")
        for m in msgs
        if m.get("role") == "assistant"
        for tc in m.get("tool_calls") or []
    ]
    descriptions = [d.get("description", "") for d in done_calls]
    notes = [_text(m.get("content")) for m in msgs[1:] if m.get("role") == "user"]
    for kind, key, action in coordinator_plan(c):
        if kind == "tool":
            assert isinstance(action, dict)
            if action["input"]["description"] in descriptions:
                continue
            return action
        if kind == "wait":
            if any(key in n for n in notes):
                continue
            return action  # end the turn: the notification starts the next one
        return action
    return "done"


def worker(step: int, c: dict) -> dict | str:
    td, common, suite = c["task_dir"], c["common"], c["suite"]
    dev, unseen = c["dev"].replace(",", " "), c["unseen"].replace(",", " ")
    dev0 = first_seeds(c["dev"], 1)
    sweep = "--flat-run-dir --workers 4"
    v00, v01 = programs_for(suite)["v00"], programs_for(suite)["v01"]
    mode, why = flaw_for(suite)
    if step == 0:
        return bash(
            f"mkdir -p {td}/code {td}/debug/explore {td}/debug/initial {td}/debug/attempts {td}/debug/holdout "
            f"{td}/debug/logs {td}/debug/blocked && cap-harness run {common} --seed {dev0} --program "
            f"docs/scene_snapshot.py --output-root {td}/debug/explore --flat-run-dir --no-videos && "
            f"cat {td}/debug/explore/*/*/source/program-result.json | head -c 1200",
            "Stage 0: one scene snapshot on the first development seed",
        )
    if step == 1:
        analysis = (
            f"# Initial Task Analysis\n\n- Actual task language: docs/task.md\n- Interaction type: pick/place\n"
            f"- Uncertainties to verify from later seeds: {mode}\n"
        )
        return bash(
            heredoc(f"{td}/task_analysis.md", analysis)
            + heredoc(f"{td}/code/v00_initial.py", v00)
            + f"echo 'v00 — initial program from scene analysis' > {td}/code/CHANGELOG.md",
            "Write the task analysis and v00",
        )
    if step == 2:
        return bash(
            f"cap-harness run-batch {common} --seeds {dev} --program {td}/code/v00_initial.py --output-root "
            f"{td}/debug/initial {sweep} --log-dir {td}/debug/logs/v00 --results-jsonl {td}/debug/initial/results.jsonl"
            f"; {SCORE.format(path=td + '/debug/initial/results.jsonl')}",
            "Run v00 on every development seed",
        )
    if step == 3:
        return bash(
            heredoc(f"{td}/code/v01_{mode.replace(' ', '_')}.py", v01)
            + f"echo 'modes: {mode} (all seeds) | v01 — {mode}: {why}' >> {td}/code/CHANGELOG.md",
            "Fix the largest failure mode as v01",
        )
    if step == 4:
        prog = f"{td}/code/v01_{mode.replace(' ', '_')}.py"
        return bash(
            f"cap-harness run-batch {common} --seeds {dev} --program {prog} --output-root {td}/debug/attempts/v01 "
            f"{sweep} --log-dir {td}/debug/logs/v01 --results-jsonl {td}/debug/attempts/v01/results.jsonl; "
            f"{SCORE.format(path=td + '/debug/attempts/v01/results.jsonl')}",
            "Run v01 on every development seed",
        )
    if step == 5:
        prog = f"{td}/code/v01_{mode.replace(' ', '_')}.py"
        return bash(
            f"cp {prog} {td}/fix_code.py && echo 'SELECTED: v01' >> {td}/code/CHANGELOG.md && "
            f"cap-harness run-batch {common} --seeds {unseen} --program {td}/fix_code.py --output-root "
            f"{td}/debug/holdout {sweep} --log-dir {td}/debug/logs/holdout --results-jsonl "
            f"{td}/debug/holdout/results.jsonl; {SCORE.format(path=td + '/debug/holdout/results.jsonl')}",
            "Select v01 and measure it once on the unseen-check seeds",
        )
    if step == 6:
        skill, title = entry_for(suite)
        findings = (
            f"# Findings: {c['benchmark']}/{suite}/task_{c['task_id']}\n\n## Root causes observed\n- {mode}: {why}\n\n"
            f"## What fixed them\n- v01\n\n## Development vs unseen\nsee debug/attempts/v01 and debug/holdout\n\n"
            f"## Generalizable patterns\n- target skill file: {skill}; trigger: {why}\n\n## Skill report\nnone consulted\n\n"
            "## Blocked modes\nnone\n\n## Non-privileged API audit\nPASS (the task's own API only; no observed "
            "coordinate in the program)\n"
        )
        report = {
            "schema_version": 1,
            "benchmark": c["benchmark"],
            "suite": suite,
            "task_id": int(c["task_id"]),
            "consulted": [
                {
                    "skill": "transport.md",
                    "section": "Placement Approach",
                    "verdict": "not-applicable",
                    "evidence": "written for cap-harness perception tools that this task does not have",
                }
            ],
            "proposed_edits": [],
            "proposed_new": [
                {
                    "skill": skill,
                    "title": title,
                    "trigger": why,
                    "evidence": "v00 failed every development seed on this mode; v01 fixed it",
                }
            ],
        }
        # the report as JSON inside a Python string literal (repr escapes it), with the library hash and the selected
        # program's code filled in when it runs
        report_py = (
            "import json, subprocess, sys\n"
            f"report = json.loads({json.dumps(report)!r})\n"
            "report['skill_library_sha'] = subprocess.run([sys.executable, "
            "'.claude/skills/iterative-debugging/scripts/campaign.py', '--skill-library-sha'], capture_output=True, "
            "text=True).stdout.strip()\n"
            f"report['proposed_new'][0]['code'] = open({td + '/fix_code.py'!r}).read()\n"
            f"json.dump(report, open({td + '/skill_report.json'!r}, 'w'), indent=2)\n"
        )
        return bash(
            heredoc(f"{td}/findings.md", findings)
            + f"python3 - <<'STANDIN_EOF'\n{report_py}STANDIN_EOF\n"
            + f"python3 .claude/skills/iterative-debugging/scripts/campaign.py --validate-skill-report "
            f"{td}/skill_report.json",
            "Write findings.md and skill_report.json, and check the report",
        )
    return (
        f"BENCHMARK: {c['benchmark']}\nSUITE: {suite}\nTASK_ID: {c['task_id']}\nGPU: none\n\nStage 1 Results:\n"
        "  fix_code.py written: yes\n  findings.md written: yes\n  skill_report.json written: yes\n"
        "  Non-privileged API audit: PASS\n"
    )


def verifier(step: int, c: dict) -> dict | str:
    vdir = re.search(r"VERIFY_DIR=(\S+)", c["raw"]).group(1)  # type: ignore[union-attr]
    seeds = first_seeds(c["dev"], 5)
    if step == 0:
        return bash(f"mkdir -p {vdir}/code {vdir}/logs && sed -n 1,40p {vdir}/proposed_skills.md", "Read the proposals")
    if step == 1:
        # the proposal's snippet, applied literally
        code = (
            "import re\n"
            f"text = open('{vdir}/proposed_skills.md').read()\n"
            "snippet = re.search(r'```python\\n(.*?)```', text, re.S).group(1)\n"
            f"open('{vdir}/code/v01_from_skills.py', 'w').write(snippet)\n"
        )
        return bash(
            f"python3 - <<'STANDIN_EOF'\n{code}STANDIN_EOF\ncap-harness run-batch {c['common']} --seeds {seeds} "
            f"--program {vdir}/code/v01_from_skills.py --output-root {vdir}/debug/v01 --flat-run-dir --workers 4 "
            f"--log-dir {vdir}/logs --results-jsonl {vdir}/debug/v01/results.jsonl; "
            f"{SCORE.format(path=vdir + '/debug/v01/results.jsonl')}",
            "Write v01 from the proposal and run it on the first development seeds",
        )
    if step == 2:
        code = (
            "import json\n"
            f"rows = [json.loads(l) for l in open('{vdir}/debug/v01/results.jsonl')]\n"
            "passes = sum(1 for r in rows if r.get('task_success'))\n"
            "verdict = 'verified' if passes >= 4 else 'refuted'\n"
            f"json.dump({{'schema_version': 1, 'benchmark': '{c['benchmark']}', 'suite': '{c['suite']}', 'task_id': "
            f"{c['task_id']}, 'seeds': [r['seed'] for r in rows], 'attempts_used': 1, 'trials': len(rows), "
            "'passes': passes, 'verdict': verdict, 'skills_applied': ['proposed'], 'proposals': [], 'gaps': [], "
            f"'notes': 'stand-in verifier'}}, open('{vdir}/verification_report.json', 'w'), indent=2)\n"
            "print(verdict, passes, len(rows))\n"
        )
        return bash(f"python3 - <<'STANDIN_EOF'\n{code}STANDIN_EOF\n", "Write the verification report")
    return "VERIFIER\nVerdict: see verification_report.json\nReading rules: RESPECTED"


# ---- the server -----------------------------------------------------------------------------------------------------
def decide(body: dict) -> tuple[str, dict | str]:
    """(role, the next tool call or the final text) for one chat completions request."""
    msgs = body.get("messages") or []
    if not body.get("tools"):
        return "side", "ok"
    users = [m for m in msgs if m.get("role") == "user"]
    first = _text(users[0].get("content")) if users else ""
    step = sum(1 for m in msgs if m.get("role") == "assistant")
    c = campaign(first)
    c["raw"] = first
    if "You are the coordinator of an ASPIRE campaign" in first:
        return "coordinator", coordinator(msgs, c)
    if "ROLE: worker" in first:
        return "worker", worker(step, c)
    if "ROLE: verifier" in first:
        return "verifier", verifier(step, c)
    return "unknown", "ok"


def _last_user(body: dict) -> str:
    users = [m for m in body.get("messages") or [] if m.get("role") == "user"]
    return _text(users[-1].get("content")) if len(users) > 1 else ""


def tool_names(body: dict) -> list[str]:
    return [str((t.get("function") or {}).get("name") or t.get("name")) for t in body.get("tools") or []]


class Handler(BaseHTTPRequestHandler):
    log_path = ""
    lock = threading.Lock()

    def log_message(self, format, *args) -> None:
        pass

    def do_GET(self) -> None:
        self._json({"object": "list", "data": [{"id": "glm-5.3", "object": "model"}]})

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        role, action = decide(body)
        with self.lock, open(self.log_path, "a") as f:
            f.write(
                json.dumps(
                    {
                        "t": time.time(),
                        "role": role,
                        "messages": len(body.get("messages") or []),
                        "tools": tool_names(body),
                        "last_user": _last_user(body)[:400],
                        "action": action if isinstance(action, str) else {"tool": action["name"]},
                    }
                )
                + "\n"
            )
        message: dict = {"role": "assistant", "content": None}
        finish = "tool_calls"
        if isinstance(action, str):
            message["content"], finish = action, "stop"
        else:
            call_id = "call_" + uuid.uuid4().hex[:20]
            message["tool_calls"] = [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": action["name"], "arguments": json.dumps(action["input"])},
                }
            ]
        usage = {"prompt_tokens": 1000, "completion_tokens": 50, "total_tokens": 1050}
        created, rid = int(time.time()), "chatcmpl-" + uuid.uuid4().hex[:24]
        if not body.get("stream"):
            return self._json(
                {
                    "id": rid,
                    "object": "chat.completion",
                    "created": created,
                    "model": body.get("model", "glm-5.3"),
                    "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                    "usage": usage,
                }
            )
        delta: dict = {"role": "assistant"}
        if message.get("content"):
            delta["content"] = message["content"]
        if message.get("tool_calls"):
            tc = message["tool_calls"][0]
            delta["tool_calls"] = [{"index": 0, "id": tc["id"], "type": "function", "function": tc["function"]}]
        chunks = [
            {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": finish}], "usage": usage},
        ]
        raw = (
            b"".join(
                b"data: "
                + json.dumps(
                    {"id": rid, "object": "chat.completion.chunk", "created": created, "model": body.get("model"), **ch}
                ).encode()
                + b"\n\n"
                for ch in chunks
            )
            + b"data: [DONE]\n\n"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _json(self, data: dict) -> None:
        raw = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=18940)
    ap.add_argument("--log", default="standin-requests.jsonl", help="one line per request: role, tools offered, action")
    ap.add_argument("--programs", help="a JSON file with each suite's v00 and v01, kept outside any checkout")
    a = ap.parse_args()
    if a.programs:
        load_programs(a.programs)
    Handler.log_path = a.log
    print(f"stand-in model on http://127.0.0.1:{a.port}/v1", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
