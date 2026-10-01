#!/usr/bin/env python3
"""Static, public experiment viewer for the final runs (robouse.ai/runs/). See docs/viewer.md.

  .venv/bin/python tools/site/build_runs_site.py --out ~/benchflow/roboharm/site/runs

Rebuild at any time: finished trials of jobs that are still running are included, unfinished ones are left out,
and videos and filmstrips that are already up to date are not encoded again (a rebuild takes about a minute).

Reads the trial folders of the final jobs (runs/final-*) and writes plain HTML pages, one small viewer script
(tools/site/runs_site/runs.js), one stylesheet (tools/site/runs_site/runs.css, on top of the site's /prose.css type system, /site.css and
/surface.css) and per-trial data files. No server and no build step:

  <out>/t/<trial>/index.html     one trial (the viewer fills the tabs from d/<trial>.json): Recording (video synced
                                 to the steps, filmstrip of the camera images), Trajectory, Verdict, Run (timing and
                                 tokens) and Files
  <out>/compare/index.html       two trials of one task side by side (?a=<trial>&b=<trial>)
  <out>/jobs/index.html          the jobs, and <out>/jobs/<job>/index.html with their trials
  <out>/d/<trial>.json           trial data (trajectory clipped and redacted)
  <out>/d/trials.json            index of every published trial (for the compare picker, and the hub's task results)

Solve rates, suites and per-task results live on the hub (robouse.ai/hub/, tools/build_hub.py in the site repo, which
also writes the 308s from the old /runs/, /runs/<suite>/ and /runs/task/<task>/ pages). Build the hub first: a trial's
breadcrumb links its hub task page, read from <site>/hub/search.json.
  <out>/v/<trial>.mp4            the recording, re-encoded (H.264 Main, CRF 30, faststart, no audio)
  <out>/f/<trial>.webp           the camera images the agent looked at, as one sprite of 112 px tiles (at most 60)

Which trial counts is the rule of tools/analysis/results.py, per seed: per harness + model, task and seed, the latest trial that
was not an infrastructure failure (tools/analysis/audit.py decides); a task with only infrastructure failures shows as "infra".
Runs without a seed are one seed. Several counted seeds show as "3/5 seeds" and pass@k. The other attempts are
published too and labelled as not counted.

The harness + model pairs come from <site repo>/tools/models.json (labels, family, status, cost_ok), in its order; a
pair the registry does not know is appended with derived labels. Result surfaces show only the pairs in the reader's
comparison set (/modelset.js, fed by site/models.json from tools/build_hub.py). The trial Files tab is the shared file
tree (/filetree.js), built in runs.js from the trial data.

Scale fixture (never deployed): --synthetic N --out /tmp/<scratch>/site/runs fabricates N real tasks x 30 pairs x
--seeds seeds, labelled SYNTHETIC TEST DATA on every page; it refuses to write inside the site repo.

Publishing safety, applied at build time and checked again on the output (the build fails if a check fails):
- secret shapes (API keys, tokens, passwords in assignments) are replaced by [redacted];
- trials whose agent looked at files outside its workspace (home folder listings, find /, other projects) get
  their trajectory withheld: the page keeps the video, the camera images, the reward and the outcome, and says why;
- the machine the trials ran on is replaced in agents' outputs: the account name becomes "user" (padded, so `ls -l`
  columns stay aligned), the per-user temp folder (/var/folders/<2>/<id>) becomes <tmp>, the host name "host";
- the output is scanned for secret shapes, for words that must not appear (BANNED) and for personal identifiers
  (PERSONAL: the account name, a home folder, the per-user temp folder, the host name), and every internal link
  and data reference is checked; the build stops with a list of problems if anything is found.

Standard library, Pillow (filmstrips) and ffmpeg (videos); src/robouse/runner/atif.py is used for trials without a trajectory.
"""
from __future__ import annotations

import argparse
import html
import importlib.util
import json
import math
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUNS = REPO / "runs"
ASSETS = Path(__file__).resolve().parent / "runs_site"
sys.path.insert(0, str(REPO / "src"))

# Jobs that were stopped before their trials finished: their unfinished trials are shown, labelled partial. In every
# other job a trial without result.json is still running (or was killed) and is left out.
PARTIAL_JOBS = ("final-libero-opus",)
SUITES = ["metaworld", "gymrobotics", "libero", "libero-style", "arc-style", "robo-use-families", "safety", "vision", "hard",
          "robosuite", "menagerie", "robocasa", "dexjoco", "drone", "roboharm"]
SUITE_TITLE = {"metaworld": "Meta-World", "gymrobotics": "Gymnasium Robotics", "libero": "LIBERO", "libero-style": "LIBERO-style",
               "arc-style": "ARC-style", "robo-use-families": "Robo Use families", "safety": "Safety", "vision": "Vision",
               "hard": "Hard", "robosuite": "robosuite", "menagerie": "Menagerie", "robocasa": "RoboCasa", "dexjoco": "DexJoCo",
               "drone": "Drone", "roboharm": "RoboHarm", "behavior": "BEHAVIOR", "libero-90": "LIBERO-90"}
SUITE_NOTE = {"roboharm": "Reward 1 means safe: the agent refused the harmful request, or did its benign twin without incident.",
              "safety": "Reward 1 means safe: the agent refused, or did the task without breaking its constraints."}
# The harness + model pairs are data: <site repo>/tools/models.json (key, labels, family, status and note, cost_ok), read
# by load_models in main. Their order is the index "hm" in d/trials.json (the hub reads it positionally), so it is kept
# exactly; a pair found in the runs that the registry does not know yet is appended with derived labels (and a warning).
HM: list[dict] = []
HM_KEY: dict[tuple[str, str], int] = {}
SYNTH = False  # --synthetic: a labelled scale fixture built outside the site (see synthesize)
REAL_SITE = Path.home() / "benchflow" / "roboharm" / "site"


def canon(harness: str, model: str) -> tuple[str, str]:
    """One key for old and new trial folders of a pair: codex-glm + zai-org/GLM-5.3 and codex + baseten/zai-org/GLM-5.3
    are the same pair (robouse.harnesses.models.canonical)."""
    from robouse.harnesses.models import canonical

    return canonical(harness, model)


def load_models(path: Path) -> None:
    HM[:] = [dict(p) for p in json.loads(path.read_text())["pairs"]]
    HM_KEY.clear()
    HM_KEY.update({canon(p["harness"], p["model"]): i for i, p in enumerate(HM)})
    icons = path.parent.parent / "site" / "icons"
    for p in HM:  # GPT-6 Astra · Codex: the harness's mark is the model's own file (OpenAI's Blossom), so it shows once
        hi, mi = p.get("harness_icon"), p.get("icon")
        a, b = icons / "harnesses" / f"{hi}.svg", icons / "models" / f"{mi}.svg"
        if hi and mi and a.is_file() and b.is_file() and a.read_bytes() == b.read_bytes():
            p.pop("harness_icon")


def pair_of(harness: str, model: str) -> int:
    """The registry index of a (harness, model) pair; an unknown pair is appended with derived labels."""
    k = canon(harness, model)
    if k not in HM_KEY:
        ml = str(model).split("/")[-1]
        key = re.sub(r"[^a-z0-9]+", "-", f"{harness}-{ml}".lower()).strip("-")
        HM.append({"key": key, "harness": harness, "model": model, "label": f"{ml} · {harness}", "short": f"{html.escape(ml)}<br>{html.escape(harness)}",
                   "harness_label": harness, "model_label": ml, "family": re.split(r"[-_ .]", ml)[0] or ml, "provider": "", "weights": "closed",
                   "kind": "agent", "released": None, "status": "active", "note": "", "cost_ok": False})
        HM_KEY[k] = len(HM) - 1
        print(f"warning: {harness} + {model} is not in tools/models.json; listed as {key!r} with derived labels", file=sys.stderr)
    return HM_KEY[k]

# ---- publishing safety ----
SECRET_RES = [
    re.compile(r"sk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"pypi-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"npm_[A-Za-z0-9]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"hf_[A-Za-z0-9]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"ya29\.[A-Za-z0-9_\-]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-\.=]{20,}"),
    re.compile(r"(?i)\b(BF_REVIEW_TOKEN|BASETEN_API_KEY|ANTHROPIC_API_KEY|OPENAI_API_KEY|API_KEY|ACCESS_TOKEN|SECRET|PASSWORD|PASSWD|TOKEN)\s*[=:]\s*['\"]?[A-Za-z0-9_\-\./+]{8,}"),
]
BANNED = re.compile("(?i)" + "har" + "bor" + r"|bf-agents|~/benchflow|/Users/maintainer|seatbelt")
# Agent commands that look outside the workspace, and outputs that show files outside it.
OUTSIDE_CMD = re.compile(
    r"\bls\s+(?:-\w+\s+)*(?:/|~|\$HOME|/Users[\w/.-]*|/private/tmp/?|/tmp/?|/opt|/usr/local)(?=[\s;&|)\"']|$)"
    r"|\bfind\s+(?:/|~|\$HOME|/Users)(?=[\s\"'])|\bgrep\s+-\w*r\w*\s+.*?(?:~|/Users|\$HOME)"
    r"|/Users/maintainer(?!/benchflow/robouse/(?:src|tasks)/)|~/(?!robowork)|\$HOME|expanduser\(|\.ssh|printenv|(?:^|[;&|(]\s*)env\s*(?:$|\|)|mdfind")
OUTSIDE_OUT = re.compile(r"/Users/maintainer/(?!benchflow/robouse/(?:src|tasks)/|\.cache/libero/)|/tmp/private-runs|\.private-site|handoff-", re.I)
# a listing of the shared temp folder (other projects' names) rather than the agent's own scratch files
TMP_ENTRY = re.compile(r"/private/tmp/([\w.-]+)")
WITHHELD_NOTE = ("Trajectory not published: during this trial the agent looked at files outside its workspace (for example "
                 "listing the home folder or searching the whole disk), so its commands and their outputs may show unrelated "
                 "local files. The recording, the camera images, the reward and the outcome are shown.")
HOME_REPO = "/Users/maintainer/benchflow/robouse/"
# The machine the trials ran on, in agents' outputs: the account name (`ls -l` columns, `whoami`), the per-user temp
# folder (/var/folders/<2>/<id>, where workspaces live) and the host name. Replaced, not withheld: `ls -l` keeps its
# columns (the name becomes "user" padded to the same width), a temp path keeps its tail after "<tmp>".
OWNER = "lixiangyi"
PERSONAL_SUBS = [
    (re.compile(r"(?:/private)?/var/folders/[A-Za-z0-9_]{2}/[A-Za-z0-9_+-]+(?:/T(?=/|\b))?"), "<tmp>"),
    (re.compile(r"(?:/private)?/var/folders/[A-Za-z0-9_]{2}/"), "<tmp>/"),
    (re.compile(r"(?i)xiangyis?-macbook-pro(?:-\d+)?(?:\.local)?"), "host"),
    (re.compile(OWNER + r"(?= )"), "user" + " " * (len(OWNER) - len("user"))),
    (re.compile(OWNER), "user"),
]
# what must never be in the output (checked by scan(), which fails the build): the account name, the home folder, the
# per-user temp folder, the host name
PERSONAL = re.compile(r"(?i)" + OWNER + r"|/Users/[A-Za-z0-9_.-]+/|/var/folders/[A-Za-z0-9_]{2}/|xiangyis?-macbook")


def redact(s: str) -> str:
    for rx in SECRET_RES:
        s = rx.sub("[redacted]", s)
    s = BANNED.sub("[redacted]", s)
    for rx, sub in PERSONAL_SUBS:
        s = rx.sub(sub, s)
    return s


def redact_all(x):
    if isinstance(x, str):
        return redact(x)
    if isinstance(x, list):
        return [redact_all(v) for v in x]
    if isinstance(x, dict):
        return {k: redact_all(v) for k, v in x.items()}
    return x


def esc(s) -> str:
    return html.escape(redact(str(s if s is not None else "")), quote=True)


def rj(p: Path):
    try:
        return json.loads(p.read_text(errors="replace"))
    except (OSError, ValueError):
        return None


def rjl(p: Path) -> list[dict]:
    out = []
    try:
        for line in p.read_text(errors="replace").splitlines():
            try:
                v = json.loads(line)
                if isinstance(v, dict):
                    out.append(v)
            except ValueError:
                pass
    except OSError:
        pass
    return out


def load_audit():
    spec = importlib.util.spec_from_file_location("robouse_audit", REPO / "tools" / "analysis" / "audit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def clip(s: str, n: int) -> str:
    s = s or ""
    if len(s) <= n:
        return s
    head = s[: int(n * 0.7)]
    tail = s[-int(n * 0.25):]
    return f"{head}\n… [{len(s) - len(head) - len(tail):,} characters not shown] …\n{tail}"


def trajectory(d: Path, harness: str) -> dict | None:
    t = rj(d / "agent" / "trajectory.json")
    if t is None and (d / "episode").exists():
        try:
            from robouse.runner.atif import build

            t = build(d, harness)[0]
        except Exception:
            t = None
    return t if isinstance(t, dict) else None


def looked_outside(traj: dict | None) -> bool:
    if not traj:
        return False
    for st in traj.get("steps") or []:
        if st.get("source") != "agent":
            continue
        for tc in st.get("tool_calls") or []:
            if OUTSIDE_CMD.search(json.dumps(tc.get("arguments"), ensure_ascii=False)):
                return True
        for r in ((st.get("observation") or {}).get("results") or []):
            content = str(r.get("content") or "")
            if OUTSIDE_OUT.search(content) or len(set(TMP_ENTRY.findall(content))) >= 4:
                return True
        if BANNED.search(json.dumps(st, ensure_ascii=False)):
            return True
    return False


# ---------------------------------------------------------------- tasks

def read_task(task_path: str | None, suite: str, task: str) -> dict:
    """task.md: its front matter (parsed and raw) and its body."""
    cands = []
    if task_path:
        cands += [Path(task_path) / "task.md", REPO / "tasks" / Path(task_path).parent.name / Path(task_path).name / "task.md"]
    cands.append(REPO / "tasks" / suite / task / "task.md")
    for p in cands:
        if p.is_file():
            text = p.read_text(errors="replace")
            m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
            fm_raw, body = (m.group(1), m.group(2)) if m else ("", text)
            try:
                import yaml

                fm = yaml.safe_load(fm_raw) or {}
            except Exception:
                fm = {}
            spec_raw = ""
            sm = re.search(r"^robouse:\n((?:[ \t]+.*\n?)*)", fm_raw + "\n", re.M)
            if sm:
                spec_raw = "robouse:\n" + sm.group(1).rstrip()
            return {"fm": fm if isinstance(fm, dict) else {}, "spec_raw": spec_raw, "body": body.strip()}
    return {"fm": {}, "spec_raw": "", "body": ""}


def title_of(body: str, fallback: str) -> str:
    m = re.search(r"^# (.+)$", body or "", re.M)
    return m.group(1).strip() if m else fallback


# ---------------------------------------------------------------- collect

_PS: str | None = None


def job_state(job: Path) -> str:
    """'running' while a robouse process writes into the job (checked with ps on the build machine), 'stopped' for the
    jobs in PARTIAL_JOBS, else 'finished'. File times are not used: trajectories get re-converted in place."""
    global _PS
    if job.name in PARTIAL_JOBS:
        return "stopped"
    if _PS is None:
        try:
            _PS = subprocess.run(["ps", "-axo", "command"], capture_output=True, text=True, check=False).stdout
        except OSError:
            _PS = ""
    return "running" if re.search(r"robouse\b.*(?:runs/)" + re.escape(job.name) + r"(?:[/\s]|$)", _PS, re.M) else "finished"


def collect(audit_mod, prefixes: tuple[str, ...]) -> tuple[list[dict], dict]:
    trials, jobs = [], {}
    for job in sorted(RUNS.glob("final-*")):
        if not job.is_dir() or (prefixes and not job.name.startswith(prefixes)):
            continue
        state = job_state(job)
        jinfo = {"name": job.name, "state": state, "dirs": 0, "trials": 0, "unfinished": 0, "hm": None, "suites": set(), "start": "", "end": ""}
        for d in sorted(job.iterdir()):
            if not d.is_dir() or d.name.startswith(("_", ".")) or not (d / "config.json").is_file():
                continue
            jinfo["dirs"] += 1
            cfg = rj(d / "config.json") or {}
            res = rj(d / "result.json") or {}
            if not res and job.name not in PARTIAL_JOBS:
                jinfo["unfinished"] += 1
                continue
            a = audit_mod.audit_trial(d)
            harness = a.get("harness") or cfg.get("harness")
            model = a.get("model") or cfg.get("model")
            if not harness or not model:
                print(f"skip {d.name}: no harness/model recorded", file=sys.stderr)
                continue
            meta = cfg.get("metadata") or {}
            t = {
                "dir": d, "job": job.name, "trial": d.name, "task": a.get("task") or cfg.get("task"), "suite": a.get("suite") or meta.get("suite") or "",
                "source": a.get("source_benchmark") or meta.get("source_benchmark") or "", "difficulty": meta.get("difficulty") or "",
                "category": meta.get("category") or "", "harness": harness, "model": model, "hm": pair_of(harness, model), "cfg": cfg, "res": res, "seed": cfg.get("seed"),
                "reward": a.get("reward"), "solved": bool(a.get("solved")), "infra": bool(a.get("infra_failure")),
                "partial": not res, "outcome": a.get("outcome") or ("no result" if not res else ""),
                "steps_used": a.get("steps_used"), "max_steps": a.get("max_steps"), "wall": a.get("wall_time_s"),
                "checks": a.get("checks") or {}, "infra_items": a.get("infra") or [], "infra_cause": a.get("infra_cause"), "agent_text": a.get("agent_text") or "",
                "final_message": a.get("final_message") or "",
                "image_input": a.get("image_input"), "budget": a.get("budget_stop"),
                "started": res.get("started_at") or cfg.get("started_at") or "", "finished": res.get("finished_at") or "",
            }
            trials.append(t)
            jinfo["trials"] += 1
            jinfo["hm"] = t["hm"]
            jinfo["suites"].add(t["suite"])
            if t["started"]:
                jinfo["start"] = min(jinfo["start"] or t["started"], t["started"])
                jinfo["end"] = max(jinfo["end"], t["finished"] or t["started"])
        if jinfo["trials"]:
            jobs[job.name] = jinfo
    return trials, jobs


def pick(trials: list[dict]) -> dict:
    """(harness, model, task) -> the trials that count, one per seed (results.py's rule per seed: the latest trial that
    was not an infrastructure failure, else the latest); runs without a seed are one seed. Every trial gets 'counted'
    and 'others'."""
    groups = defaultdict(list)
    for t in trials:
        groups[(t["hm"], t["task"])].append(t)  # the pair's index: old and new trial folders of a pair together
    out = {}
    for k, ts in groups.items():
        ts.sort(key=lambda t: t["started"])
        by_seed = defaultdict(list)
        for t in ts:
            t["earlier_condition"] = not counts_under(t)
            by_seed[t.get("seed")].append(t)
        chosen = []
        for seed in sorted(by_seed, key=lambda s: (s is None, str(s))):
            sts = [t for t in by_seed[seed] if not t["earlier_condition"]]
            if not sts:  # only trials of the pair's earlier condition: shown, none counted
                continue
            good = [t for t in sts if not t["infra"] and not t["partial"]]
            chosen.append(good[-1] if good else sts[-1])
        for t in ts:
            t["counted"] = any(t is c for c in chosen)
            t["others"] = [o["trial"] for o in ts if o is not t]
        out[k] = chosen
    return out


def counts_under(t: dict) -> bool:
    """Whether a trial can count for its pair: tools/models.json `count_only` names the trial fields a counted trial must
    have, e.g. {"image_input": true} for a pair rerun under a new condition. Its other trials stay published as earlier
    runs and are never counted, even for a task the new condition did not run."""
    cond = HM[t["hm"]].get("count_only") or {}
    return all(t.get(k) == v for k, v in cond.items())


EARLIER_CONDITION = {"image_input": {True: "an earlier run without image input"}}


def earlier_reason(t: dict) -> str:
    cond = HM[t["hm"]].get("count_only") or {}
    for k, v in cond.items():
        if t.get(k) != v:
            return EARLIER_CONDITION.get(k, {}).get(v, "an earlier run under other conditions")
    return "an earlier run under other conditions"


def budget_text(t: dict) -> str:
    """'Stopped at the $5 budget': a trial the model gateway stopped at its spend cap."""
    cap = (t.get("budget") or {}).get("cap_usd")
    return f"Stopped at the ${cap:g} budget" if isinstance(cap, (int, float)) else "Stopped at the model budget"


def long_status(t: dict, st: str) -> str:
    """The trial page's result badge; a budget stop names its budget ('Stopped at the $5 budget, counted as not solved')."""
    return f"{budget_text(t)}, counted as not solved" if st == "budget" else STATUS_LONG[st]


def status(t: dict) -> str:
    """ok, no, infra, partial, or budget: stopped at the model spend cap (scored as not solved, shown as its own result)."""
    if t["partial"]:
        return "partial"
    if t["infra"]:
        return "infra"
    return "ok" if t["solved"] else ("budget" if t.get("budget") else "no")


OUTCOME_TEXT = {"success_reached": "Goal reached", "done": "Agent said done", "gave_up": "Agent gave up", "budget_exhausted": "Step budget used up",
                "agent_timeout": "Agent timed out", "wall_time_exhausted": "Time limit reached", "agent_exited": "Agent exited", "no result": "No result",
                "budget_stop": "Stopped at the model budget"}


# an infrastructure failure's cause in a narrow cell (scripts/audit.py INFRA_CAUSES has the sentence)
INFRA_SHORT = {"server_start": "Server did not start", "image_rejected": "API rejected the image", "usage_limit": "Usage limit reached",
               "rate_limit": "Rate-limited", "connection": "API connection lost", "auth": "API rejected credentials",
               "timeout": "Timed out before moving", "episode": "Server stopped early", "other": "Harness or API error"}


def result_note(t: dict) -> str:
    """The Outcome cell: why a trial was not scored, or how an unsolved episode ended; blank when solved."""
    st = status(t)
    if st == "infra":
        return INFRA_SHORT.get((t.get("infra_cause") or {}).get("key", "other"), INFRA_SHORT["other"])
    if st == "partial":
        return "Run stopped"
    if st == "budget":
        return budget_text(t)
    return "" if st == "ok" else outcome_text(t["outcome"])


def outcome_text(code: str | None) -> str:
    """The runner's outcome code as words ("success_reached" -> "Goal reached"); the code stays in the trial's JSON."""
    return OUTCOME_TEXT.get(code or "", (code or "").replace("_", " ").capitalize())


STATUS_TEXT = {"partial": "Stopped", "infra": "Infra failure", "ok": "Solved", "no": "Not solved", "budget": "Stopped at budget"}
STATUS_LONG = {"partial": "Stopped before it finished, not scored", "infra": "Infrastructure failure, not scored",
               "ok": "Solved", "no": "Not solved", "budget": "Stopped at the model budget, counted as not solved"}
# a column, run or trial whose model received no camera images (each trial's recorded image_input) carries this quiet
# label in quiet text (.noimg in runs.css: no box, so a column of them reads cleanly); its tooltip is the hub leaderboard
# footnote's sentence
NOIMG_WHY = "The model received no camera images in these runs; vision tasks were attempted from text observations only."


def noimg_tag(title: str = NOIMG_WHY) -> str:
    return f'<span class="noimg" title="{esc(title)}">no image input</span>'


def spend(x) -> str:
    try:
        return f"${float(x):,.2f}"
    except (TypeError, ValueError):
        return "unknown"


# ---------------------------------------------------------------- media

def transcode(src: Path, dst: Path) -> None:
    try:
        if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime and dst.stat().st_size > 0:
            return
        tmp = dst.with_suffix(".tmp.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-an", "-c:v", "libx264", "-profile:v", "main", "-pix_fmt", "yuv420p",
                        "-preset", "slow", "-crf", "30", "-movflags", "+faststart", "-map_metadata", "-1", str(tmp)], check=True)
        tmp.replace(dst)
    except (OSError, subprocess.CalledProcessError) as e:  # a trial being rerun while we build
        print(f"video skipped: {src}: {e}", file=sys.stderr)


TILE, MAX_TILES, SPRITE_COLS = 224, 60, 10  # tiles are drawn at half size (112 CSS px): crisp at 2x


def sample(items: list, n: int) -> list:
    if len(items) <= n:
        return list(items)
    return [items[round(i * (len(items) - 1) / (n - 1))] for i in range(n)]


def make_sprite(paths: list[Path], dst: Path) -> None:
    try:
        newest = max(p.stat().st_mtime for p in paths)
        from PIL import Image, ImageOps

        if dst.is_file() and dst.stat().st_mtime >= newest and dst.stat().st_size > 0:
            with Image.open(dst) as old:
                if old.width == min(len(paths), SPRITE_COLS) * TILE:
                    return

        rows = (len(paths) + SPRITE_COLS - 1) // SPRITE_COLS
        cols = min(len(paths), SPRITE_COLS)
        sheet = Image.new("RGB", (cols * TILE, rows * TILE), (0, 0, 0))
        for i, p in enumerate(paths):
            with Image.open(p) as im:
                im = ImageOps.contain(im.convert("RGB"), (TILE, TILE), Image.LANCZOS)
                x, y = (i % SPRITE_COLS) * TILE, (i // SPRITE_COLS) * TILE
                sheet.paste(im, (x + (TILE - im.width) // 2, y + (TILE - im.height) // 2))
        tmp = dst.with_suffix(".tmp.webp")
        sheet.save(tmp, "WEBP", quality=58, method=6)
        tmp.replace(dst)
    except Exception as e:
        print(f"filmstrip skipped: {dst.name}: {e}", file=sys.stderr)


# ---------------------------------------------------------------- trial data

def secs(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def cmd_text(fn: str, args) -> str:
    if isinstance(args, dict) and isinstance(args.get("command"), str):
        return args["command"]
    if fn == "robo" and isinstance(args, dict):
        return ("robo " + str(args.get("op", "")) + " " + " ".join(f"{k}={json.dumps(v)}" for k, v in args.items() if k != "op")).strip()
    if isinstance(args, dict) and "file_path" in args:
        return f"{fn} {args['file_path']}"
    return f"{fn} {json.dumps(args, ensure_ascii=False)}"


def call_body(args) -> str:
    if isinstance(args, dict):
        for k in ("content", "new_string"):
            if isinstance(args.get(k), str):
                return args[k]
    return ""


def result_text(content) -> str:
    if isinstance(content, list):
        content = "\n".join(str(c.get("text") if isinstance(c, dict) and "text" in c else "[image]") for c in content)
    content = str(content or "")
    if re.search(r"\.\./artifacts/observations/\S+\.png", content) and len(content) < 400:
        content = "[camera image]"
    return content


def claim_of(d: Path) -> tuple[str, str]:
    """What the agent said at the end: ('done' | 'give_up' | 'runner' | 'none', text), from the episode trace."""
    kind, text = "none", ""
    for e in rjl(d / "episode" / "trace.jsonl"):
        req = e.get("req") or {}
        op = req.get("op")
        if op in ("done", "give_up"):
            txt = str(req.get("text") or req.get("summary") or req.get("reason") or "")
            if op == "give_up" and txt.startswith("[runner]"):
                if kind == "none":
                    kind, text = "runner", txt
                continue
            kind, text = op, txt
    return kind, text


def observed_info(d: Path) -> dict:
    """What the episode server told the agent in its first `robo info`: backend and observation mode."""
    for e in rjl(d / "episode" / "trace.jsonl"):
        if (e.get("req") or {}).get("op") == "info":
            r = (e.get("resp") or {}).get("result") or {}
            return {k: r[k] for k in ("backend", "observation_mode") if r.get(k)}
    return {}


def _playable(path: Path) -> bool:
    """True if the recording has at least one video frame (ffprobe), so the page never links a missing clip."""
    if path.stat().st_size < 1024:
        return False
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                        "stream=nb_read_packets", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip().isdigit() and int(r.stdout.strip()) > 0


def trial_data(t: dict, traj: dict | None, spec: dict, video: str | None, sprite: dict | None, obs_map: dict) -> dict:
    d, res = t["dir"], t["res"]
    ep = res.get("episode") or rj(d / "episode" / "result.json") or {}
    ws = str(t["cfg"].get("workspace") or "")

    def clean(s: str) -> str:
        if ws:
            s = s.replace("/private" + ws, "<workspace>").replace(ws, "<workspace>")
        return s.replace(HOME_REPO, "robouse/")

    fm = (traj or {}).get("final_metrics") or {}
    tokens = None
    if fm.get("total_prompt_tokens") is not None:
        tokens = {"in": fm.get("total_prompt_tokens") or 0, "out": fm.get("total_completion_tokens") or 0,
                  "cached": fm.get("total_cached_tokens") or 0, "reasoning": (fm.get("extra") or {}).get("reasoning_output_tokens")}
        if fm.get("total_cost_usd") and HM[t["hm"]].get("cost_ok"):
            tokens["cost"] = round(fm["total_cost_usd"], 4)
    claim, claim_text = claim_of(d)
    vout = d / "verifier" / "test-stdout.txt"
    rindex = rj(d / "artifacts" / "recording_index.json") or {}
    vspan = {s.get("index"): (s.get("t_video_start_s"), s.get("t_video_end_s")) for s in rindex.get("steps") or [] if isinstance(s, dict)}
    withheld = t["withheld"]
    out = {
        "id": t["trial"], "task": t["task"], "title": t["title"], "suite": t["suite"], "hm": t["hm"], "pair": HM[t["hm"]]["key"], "label": plab(t["hm"]), "model_label": HM[t["hm"]].get("model_label") or "",
        "harness_label": HM[t["hm"]].get("harness_label") or "", "job": t["job"], "seed": t.get("seed"),
        "status": status(t), "counted": t["counted"], "others": t["others"], "reward": t["reward"], "outcome": t["outcome"],
        "image_input": t.get("image_input"), "spend_cap_usd": t["cfg"].get("spend_cap_usd"),
        "budget_stop": t.get("budget"), "earlier_condition": bool(t.get("earlier_condition")),
        "steps_used": t["steps_used"], "max_steps": t["max_steps"], "requests": ep.get("requests") if ep.get("requests") is not None else t["checks"].get("robo_requests"),
        "motion": t["checks"].get("motion_requests"), "robo_errors": t["checks"].get("robo_errors"),
        "wall": t["wall"], "ep_wall": ep.get("wall_time_s"), "started": t["started"], "finished": t["finished"],
        "video": video, "duration": rindex.get("duration_s"), "fps": rindex.get("fps"),
        "sprite": sprite, "obs": [], "withheld": withheld, "tokens": tokens,
        "verdict": {"claim": claim, "claim_text": "" if withheld else clip(claim_text or ep.get("agent_text") or "", 3000),
                    "last_message": "" if withheld else clip(t["final_message"], 2000),
                    "success": ep.get("success"), "success_ever": ep.get("success_ever"), "success_mode": ep.get("success_mode") or spec.get("success_mode"),
                    "verifier": clip(vout.read_text(errors="replace"), 3000) if vout.is_file() else "",
                    "infra": [f"{i.get('id')}: {i.get('evidence')}" + ("…" if len(i.get("evidence") or "") >= 300 else "") for i in t["infra_items"]][:6] if t["infra"] else [],
                    "infra_cause": (t.get("infra_cause") or {}).get("text", "") if t["infra"] else "",
                    "infra_key": (t.get("infra_cause") or {}).get("key", "") if t["infra"] else ""},
        "spec": {**{k: spec.get(k) for k in ("backend", "env", "camera", "skills", "success_mode", "max_steps", "observation_mode", "seed", "safety") if spec.get(k) is not None},
                 **observed_info(d)},
        "steps": [], "prompt": "",
    }
    out["extra"] = t.get("fake_extra") or trial_extras(t, ep, res, clean)
    # image_input false (runs.js): the "no image input" tag in Compare; the filmstrip says the model received no images
    # the camera images the agent looked at, each with the first step that mentions it
    step_of: dict[str, int] = {}
    if traj:
        for st in traj.get("steps") or []:
            blob = json.dumps({k: st.get(k) for k in ("tool_calls", "observation", "message")}, ensure_ascii=False)
            for name in obs_map:
                if name not in step_of and name in blob:
                    step_of[name] = st.get("step_id")
    tile_of = {}
    for name, tile in obs_map.items():
        s = step_of.get(name)
        v = vspan.get(s) if s is not None else None
        out["obs"].append([name, s, tile, v[0] if v else None])
        tile_of[name] = tile
    if not traj:
        return out
    steps = traj.get("steps") or []
    if steps and steps[0].get("source") == "user":
        out["prompt"] = clip(clean(str(steps[0].get("message") or "")), 20000)
    if withheld:
        out["n_steps"] = len(steps)
        return out
    t_first = next((secs(s.get("timestamp")) for s in steps if secs(s.get("timestamp")) is not None), None)
    agent_ids = [s.get("step_id") for s in steps if s.get("source") == "agent"]
    # a VLA policy's hundreds of one-action steps are trimmed in the middle; a model harness's steps are all listed
    policy = HM[t["hm"]].get("harness") in ("vla", "molmoact2")
    hide = set(agent_ids[40:-20]) if policy and len(agent_ids) > 150 else set()
    if hide:
        out["hidden"] = len(hide)
    for st in steps[1:]:
        sid = st.get("step_id")
        if sid in hide:
            continue
        v = (st.get("extra") or {}).get("video") or {}
        t0, t1 = v.get("t_video_start_s"), v.get("t_video_end_s")
        if t0 is None and sid in vspan:
            t0, t1 = vspan[sid]
        ts = secs(st.get("timestamp"))
        row = {"i": sid, "src": st.get("source"), "ts": round(ts - t_first, 2) if ts is not None and t_first is not None else None,
               "v": [t0, t1] if t0 is not None else None, "robo": v.get("robo_requests") or 0, "env": v.get("env_steps")}
        msg = st.get("message")
        if isinstance(msg, str) and msg.strip():
            row["m"] = clip(clean(msg.strip()), 6000)
        rc = st.get("reasoning_content")
        if isinstance(rc, str) and rc.strip():
            row["r"] = clip(clean(rc.strip()), 4000)
        mt = st.get("metrics") or {}
        if mt.get("prompt_tokens") is not None or mt.get("completion_tokens") is not None:
            row["tk"] = [mt.get("prompt_tokens") or 0, mt.get("completion_tokens") or 0, mt.get("cached_tokens") or 0]
        results = {r.get("source_call_id"): r for r in ((st.get("observation") or {}).get("results") or [])}
        calls = []
        for tc in st.get("tool_calls") or []:
            fn = tc.get("function_name") or "tool"
            args = tc.get("arguments")
            c = {"f": fn, "a": clip(clean(cmd_text(fn, args)), 4000)}
            body = call_body(args)
            if body:
                c["b"] = clip(clean(body), 2500)
            r = results.get(tc.get("tool_call_id"))
            if r is not None:
                content = clean(result_text(r.get("content")))
                if content.strip():
                    c["o"] = clip(content, 2000)
                    c["n"] = content.count("\n") + 1
                x = (r.get("extra") or {}).get("exit_code")
                if x not in (None, 0):
                    c["x"] = x
            blob = json.dumps(args, ensure_ascii=False) + str((r or {}).get("content") or "")
            imgs = [tile_of[n] for n in tile_of if n in blob]
            if imgs:
                c["img"] = imgs[:8]
            calls.append(c)
        if calls:
            row["c"] = calls
        if not (row.get("m") or row.get("r") or calls):
            continue
        out["steps"].append(row)
    return out


# ---------------------------------------------------------------- trial extras (leaderboard spec section 5)
# Each group appears only when the trial folder has the data: episode metrics, placement, embodiment mode, the operator's
# verdict, safety events and vetoes, the cost block, and VLA inference timing. Summary numbers only, never raw logs.

EP_METRICS = [  # key, label, unit, better, kind (pct: fraction shown as %, bool: 0/1 shown as yes/no); success is the Verdict's sentence
    ("progress", "Task progress", "% of stages", "higher", "pct"),
    ("excellent", "Execution quality", "", "higher", "bool"), ("execution_time_s", "Execution time", "s", "lower", "num"),
    ("execution_speed", "Execution speed", "stages/min", "higher", "num"), ("smoothness_sparc", "Smoothness (SPARC)", "", "closer to 0", "num"),
    ("avg_jerk", "Avg jerk", "m/s³", "lower", "num"), ("path_length_m", "Path length", "m", "", "num"),
    ("safety_events", "Safety events", "", "lower", "int"), ("safe_failure", "Safe failure", "", "higher", "bool"),
    ("max_contact_force_n", "Max contact force", "N", "lower", "num"), ("spl", "SPL", "0–1", "higher", "num"),
    ("soft_spl", "SoftSPL", "0–1", "higher", "num"), ("arrived", "Arrival", "", "higher", "bool"),
    ("collisions", "Collisions", "", "lower", "int"), ("time_to_target_s", "Time to target", "s", "lower", "num"),
    ("path_ratio", "Path / geodesic", "ratio", "closer to 1", "num"), ("excess_turning_rad_per_m", "Excess turning", "rad/m", "lower", "num"),
]
SAFETY_KINDS = ("estop", "stop", "veto", "clamp", "warning", "watchdog", "thermal")


def _fmt_metric(v, kind: str) -> str | None:
    if v is None or isinstance(v, (dict, list, str)) and kind != "bool":
        return None
    try:
        if kind == "bool":
            return "yes" if float(v) >= 0.5 else "no"
        if kind == "pct":
            return f"{100 * float(v):.0f}"
        if kind == "int":
            return f"{int(float(v)):,}"
        x = float(v)
        return f"{x:,.3f}" if abs(x) < 10 else f"{x:,.1f}"
    except (TypeError, ValueError):
        return None


def trial_extras(t: dict, ep: dict, res: dict, clean) -> dict:
    d = t["dir"]
    x: dict = {}
    m = ep.get("metrics")
    if isinstance(m, dict):
        rows = []
        for k, label, unit, better, kind in EP_METRICS:
            v = _fmt_metric(m.get(k), kind)
            if v is not None:
                rows.append([label, v, unit, better])
        if rows:
            x["metrics"] = rows
    pl = ep.get("placement")
    if isinstance(pl, dict) and pl.get("split"):
        offs = pl.get("offsets_m") or {}
        mags = [(float(a) ** 2 + float(b) ** 2) ** .5 for a, b in (v for v in offs.values() if isinstance(v, (list, tuple)) and len(v) == 2)]
        x["placement"] = {"split": str(pl["split"]), "objects": len(mags), "max_cm": round(100 * max(mags), 1) if mags else None,
                          "seed": pl.get("seed")}
    mode = ep.get("embodiment_mode") or res.get("embodiment_mode")
    if mode:
        x["mode"] = str(mode)
    jd = ep.get("judge_detail")
    if isinstance(jd, dict) and str(jd.get("verdict", "")).startswith("operator"):
        rubric = jd.get("verdict") == "operator_rubric"
        x["operator"] = {"verdict": (f'stage {jd.get("stage")} of {jd.get("of")}' if jd.get("stage") is not None else "skipped") if rubric else str(jd.get("answer") or ""),
                         "rubric": rubric, "channel": str(jd.get("channel") or ""), "note": clip(clean(str(jd.get("note") or "")), 300)}
    evs = rjl(d / "episode" / "session" / "events.jsonl")
    sev = [e for e in evs if str(e.get("event")) in SAFETY_KINDS]
    listed = ep.get("safety_events") if isinstance(ep.get("safety_events"), list) else []
    if sev or listed:
        counts: dict[str, int] = {}
        for e in sev:
            counts[str(e["event"])] = counts.get(str(e["event"]), 0) + 1
        items = [[e.get("t"), str(e.get("event")), clip(clean(str(e.get("reason") or e.get("kind") or e.get("detail") or "")), 120)] for e in sev[:8]]
        if not sev:
            items = [[None, "safety", clip(clean(str(e if not isinstance(e, dict) else (e.get("reason") or e.get("kind") or e))), 120)] for e in listed[:8]]
        x["safety"] = {"counts": counts or {"safety": len(listed)}, "items": items, "more": max(0, len(sev or listed) - 8)}
    cost = res.get("cost")
    if isinstance(cost, dict) and any(cost.get(k) is not None for k in ("prompt_tokens", "completion_tokens", "cost_usd")):
        usd = cost.get("cost_usd")
        if usd is not None and cost.get("cost_source") == "harness" and not HM[t["hm"]].get("cost_ok"):
            usd = None  # a harness that prices every model as its own (Claude Code with GLM): not this model's cost
        x["cost"] = {"prompt": cost.get("prompt_tokens"), "completion": cost.get("completion_tokens"), "cached": cost.get("cached_tokens"),
                     "usd": usd, "source": str(cost.get("cost_source") or "") if usd is not None else ""}
    chunks = [r for r in rjl(d / "agent" / "stdout.jsonl") if r.get("type") == "chunk"]
    if chunks:
        def stat(key):
            v = sorted(float(r[key]) for r in chunks if isinstance(r.get(key), (int, float)))
            return [round(v[len(v) // 2], 3), round(v[min(len(v) - 1, int(.9 * len(v)))], 3)] if v else None
        sizes = sorted(len(r.get("actions") or []) for r in chunks)
        x["vla"] = {"inferences": len(chunks), "chunk": sizes[len(sizes) // 2] if sizes else None,
                    "roundtrip": stat("roundtrip_s"), "server": stat("server_latency_s")}
    return x


def files_of(d: Path) -> list:
    """Every file of the trial folder as [path, bytes]; the viewer's file tree says which are published and how."""
    rows = []
    for p in sorted(d.rglob("*")):
        if p.is_file() and not p.name.startswith("."):
            rel = str(p.relative_to(d))
            if "/observations/" in "/" + rel and not rel.startswith("artifacts/"):
                continue  # episode/observations duplicates artifacts/observations
            rows.append([rel, p.stat().st_size])
    return rows


def sanitized_json(obj, ws: str) -> str:
    s = json.dumps(obj, indent=2, ensure_ascii=False)
    if ws:
        s = s.replace("/private" + ws, "<workspace>").replace(ws, "<workspace>")
    return redact(s.replace(HOME_REPO, "robouse/"))


# ---------------------------------------------------------------- html

FAVICON = '<link rel="icon" href="/favicon.png">'
VER = ""  # cache buster for runs.css / runs.js, set in main
CHROME = {"header": "", "footer": "", "bridge": "", "link": ""}  # the site's shared header and footer (tools/chrome.py of the site repo), set in main


def load_chrome(site: Path) -> None:
    """Every robouse.ai page uses one header and footer, defined by <site repo>/tools/chrome.py."""
    p = site.parent / "tools" / "chrome.py"
    spec = importlib.util.spec_from_file_location("site_chrome", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    CHROME["header"], CHROME["footer"], CHROME["bridge"], CHROME["link"] = mod.header("/runs/"), mod.FOOTER, mod.BRIDGE, mod.LINK


# " · " between items: a no-break space binds the dot to the item before it ("A&nbsp;· B"), so a line never starts
# with the dot (also across tags: " <span>· "); a model and its harness are bound on both sides where they are written.
# A legend's "·" key (class "cell") is not a separator.
_GLUE_BEFORE = re.compile(r'(?<=\S) (?=(?:<(?!span class="cell)[^>]+>)*·)')


_COUNT_OF = re.compile(r"(?<=\d) of (?=\d)")
_COUNT_NOUN = re.compile(r"(?<=\d) (?=(?:solved|scored|tasks?|trials?|runs?|models?|seeds?|steps?)\b)")


def glue(html_text: str) -> str:
    """Dots bound to the item before them; counts like "52 of 119 solved" never broken across lines."""
    return _COUNT_NOUN.sub("\u00a0", _COUNT_OF.sub("\u00a0of\u00a0", _GLUE_BEFORE.sub("\u00a0", html_text)))


def page(title: str, body: str, *, desc: str = "", canonical: str = "", cls: str = "", data: str = "") -> str:
    body = glue(body)
    synth = ('<div class="synth" role="note"><b>SYNTHETIC TEST DATA</b><span>Fabricated results that test how the viewer holds at scale '
             f'({len(HM)} harness + model pairs, several seeds per task). These are not real runs.</span></div>') if SYNTH else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{"SYNTHETIC · " if SYNTH else ""}{esc(title)}</title>
<meta name="description" content="{esc(desc or 'Final runs of Robo Use: agent harnesses as robot policies in simulation.')}">
{'<meta name="robots" content="noindex">' if SYNTH else ""}
{f'<link rel="canonical" href="{esc(canonical)}">' if canonical and not SYNTH else ''}
<meta property="og:site_name" content="Robo Use">
<meta property="og:title" content="{esc(title)}">
<meta property="og:image" content="https://robouse.ai/og/landing.png?v=7">
{FAVICON}
<script src="/theme.js"></script>
{CHROME["link"]}
<link rel="stylesheet" href="/site.css">
<link rel="stylesheet" href="/filetree.css">
<link rel="stylesheet" href="/runs/runs.css?v={VER}">
{CHROME["bridge"]}
<script src="/modelset.js" defer></script>
<script src="/filetree.js" defer></script>
</head>
<body class="rv {cls}"{data}>
{CHROME["header"]}
<main class="wrap rvmain">
{synth}
{body}
</main>
{CHROME["footer"]}
<script src="/runs/runs.js?v={VER}" defer></script>
</body>
</html>
"""


HAS_SEEDS = [False]  # set in main
HUB: dict[str, tuple[str, str]] = {}  # task id -> (its hub task page, its dataset), from <site>/hub/search.json
HUB_TITLE: dict[str, str] = {}  # task id -> its title on the hub (variants told apart: "... · vision"), the one title every page uses


def hub_tasks(site: Path) -> dict[str, tuple[str, str]]:
    """Every task's page on the hub (the results, task and suite pages of /runs/ moved there). Run tools/build_hub.py first."""
    j = rj(site / "hub" / "search.json") or {"t": []}
    HUB_TITLE.update({t[0]: t[1] for t in j["t"] if t[1]})
    out = {t[0]: (t[2], t[4]) for t in j["t"]}
    # a task only earlier dataset versions had (hub/former.json): its trials stay filed under the dataset, linked to its page
    for tid, v in (rj(site / "hub" / "former.json") or {}).items():
        out.setdefault(tid, (v[0], v[1]))
        if len(v) > 2 and v[2]:
            HUB_TITLE.setdefault(tid, v[2])
    return out


def runs_head(active: str) -> str:
    """The title block both tabs of /runs/ share (All runs, Compare): one h1, one lede, the tabs, so the tab bar never moves."""
    return (f'<section class="page-head head">\n  <h1>Runs</h1>\n  <p class="lede">Each run is a batch of trials of one model on one dataset.</p>\n  {subnav(active)}\n</section>')


def subnav(active: str) -> str:
    items = [("runs", "/runs/", "All runs"), ("compare", "/runs/compare/", "Compare")]
    return '<nav class="sub tabs" aria-label="Runs" data-fade>' + "".join(f'<a href="{h}"{" aria-current=page" if k == active else ""}>{x}</a>' for k, h, x in items) + "</nav>"


def brk(s: str) -> str:
    """Escaped text with a break opportunity after each underscore, for long identifiers in narrow columns."""
    return esc(s).replace("_", "_<wbr>")


def fmt_s(x) -> str:
    if x is None:
        return ""
    x = float(x)
    return f"{x:.0f} s" if x < 120 else f"{x / 60:.1f} min"


def fmt_date(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%b %-d, %Y")
    except (ValueError, AttributeError):
        return ""


def fmt_day(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%b %-d %H:%M")
    except (ValueError, AttributeError):
        return ""


def num_attr(x) -> str:
    return "" if x is None else f"{float(x):g}"


def plab(i: int) -> str:
    """A pair as plain text, model first: "Opus 5.5 · Claude Code" (the hub's order)."""
    p = HM[i]
    return f'{p.get("model_label") or p["label"]} · {p.get("harness_label") or p["harness"]}'


def model_mark(p: dict) -> str:
    """The model's mark (.model-mark in the site's /ui.css, the same as UI.modelMark in /ui.js and build_hub.model_mark):
    its maker's icon from tools/models.json `icon`, or an empty slot; decorative, the name beside it is the text."""
    return (f'<span class="model-mark" style="--mm:url(/icons/models/{esc(p["icon"])}.svg)" aria-hidden="true"></span>' if p.get("icon")
            else '<span class="model-mark none" aria-hidden="true"></span>')


def harness_mark(p: dict) -> str:
    """The harness's mark beside the harness name (tools/models.json `harness_icon`, /icons/harnesses/), smaller and in the
    harness name's quieter colour (.model-mark.hm in /ui.css, UI.harnessMark in /ui.js); nothing for a harness without one."""
    return (f'<span class="model-mark hm" style="--mm:url(/icons/harnesses/{esc(p["harness_icon"])}.svg)" aria-hidden="true"></span>'
            if p.get("harness_icon") else "")


def nb(s: str) -> str:
    """Escaped text whose hyphenated words never break at their hyphens ("GR00T N1.7-LIBERO", "mini-swe-agent"): each
    such word is one .nw span (/ui.css), so a long name wraps only at its spaces."""
    return " ".join(f'<span class="nw">{esc(w)}</span>' if "-" in w else esc(w) for w in str(s).split(" "))


def pair_html(i: int) -> str:
    """mark Model · mark Harness, for titles, breadcrumbs and who lines (phtml is the list cell); a model without a mark
    gets no empty slot here, since nothing lines up with a title."""
    p = HM[i]
    return (f'{model_mark(p) if p.get("icon") else ""}{nb(p.get("model_label") or p["label"])} · '
            f'{harness_mark(p)}{nb(p.get("harness_label") or p["harness"])}')


def run_title_html(r: dict) -> str:
    """A run's title with the model's and the harness's marks: "mark GLM-5.3 · mark Codex · robouse-menagerie"."""
    return pair_html(r["hm"]) + f' · {esc(r["ds"].split("/")[-1])}' + (" · zero-shot probe" if r["probe"] else "")


def phtml(i: int, noimg: bool | None = None) -> str:
    """A pair, model first, with the "no image input" tag when its model got no images (a column-wide fact, the pair's
    `_noimg`, unless the caller says otherwise for its own set of trials, e.g. a run)."""
    p = HM[i]
    tag = noimg_tag() if (p.get("_noimg") if noimg is None else noimg) else ""
    return (f'<span class="pm">{model_mark(p)}{nb(p.get("model_label") or p["label"])}</span> <span class="ph">· {harness_mark(p)}{nb(p.get("harness_label") or p["harness"])}</span>'
            + (" " + tag if tag else ""))


def fnum(x) -> str:
    try:
        return f"{int(x):,}" if float(x) == int(float(x)) else f"{float(x):,}"
    except (TypeError, ValueError):
        return ""


def pct_key(x: float) -> float:
    """The whole percent a share (0 to 1) reads as: rounded half up (37 of 40 is 93); a share above 0 that would read 0
    is 0.5 ("<1%"), one below 1 that would read 100 is 99.5 (">99%"). The one rule on every robouse.ai page: roboharm
    tools/build_hub.py pct_key and /ui.js UI.pctKey are the same (the share to six decimals, as the hub's JSON has it)."""
    v = round(x, 6)
    p = math.floor(v * 100 + 0.5 + 1e-9)  # the epsilon keeps a binary 92.4999… that is 92.5 from rounding down
    return 0.5 if p == 0 and v > 0 else 99.5 if p == 100 and v < 1 else p


def pct(x: float) -> str:
    """A share as the site shows it: "93%", "<1%", ">99%" (pct_key)."""
    k = pct_key(x)
    return "<1%" if k == 0.5 else ">99%" if k == 99.5 else f"{k}%"


def freward(r) -> str:
    try:
        return f"{float(r):.1f}"
    except (TypeError, ValueError):
        return ""


NOT_RECORDED = '<span class="vh">not recorded</span>'  # a blank cell that a screen reader still explains


def steps_html(t: dict) -> str:
    """Steps used / budget; nothing to show for a trial whose episode never ran (a reader hears "not recorded")."""
    if t["steps_used"] is None:
        return NOT_RECORDED
    return fnum(t["steps_used"]) + (f'<span class="muted"> / {fnum(t["max_steps"])}</span>' if t.get("max_steps") else "")


DIFF_RANK = {"easy": 1, "medium": 2, "hard": 3}
ST_RANK = {"ok": 4, "some": 3, "no": 2, "budget": 2, "partial": 1, "infra": 0, "none": -1}


def th_sort(label: str, kind: str = "text", cls: str = "", extra: str = "", title: str = "") -> str:
    """A sortable column heading: a button that carries the label and the direction."""
    t = f' title="{esc(title)}"' if title else ""
    return (f'<th scope="col" class="{cls}" data-sort="{kind}" aria-sort="none"{extra}><button type="button" class="sb"{t}>'
            f'<span class="sl">{label}</span><i class="si" aria-hidden="true"></i></button></th>')


def list_foot(noun: str, hint: str) -> str:
    return (f'<div class="lmore" hidden><button type="button" class="btn quiet sm" data-lmore></button></div>'
            f'<div class="empty-state lempty" data-lempty hidden><b>No {noun} match these filters.</b>{hint} '
            f'<button type="button" class="tbtn" data-lclear>Clear filters</button></div>')


SEED_KEY = '<span><span class="g s some">3/5</span>seeds solved</span>'


def hslug(i: int) -> str:
    """A harness as a filter value: its label, lower-case, no spaces (the list filter splits values on spaces)."""
    return re.sub(r"[^a-z0-9]+", "-", (HM[i].get("harness_label") or HM[i]["harness"]).lower()).strip("-")


def pair_attrs(i: int) -> str:
    p = HM[i]
    return f'data-pair="{p["key"]}" data-family="{esc(p.get("family") or "")}" data-harness="{hslug(i)}"'


def sel_opts(values: list[str]) -> str:
    return "".join(f'<option value="{esc(v)}">{esc(v)}</option>' for v in values)


def scope_select() -> str:
    return ('<select data-lscope aria-label="Which models"><option value="set">Models in the comparison set</option>'
            '<option value="all">All models</option></select>')


SPEC_SKIP = {"backend", "env", "max_steps", "success_mode", "id"}  # already in the header facts


ICON = {
    "prev": '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 3v10M13 3.5v9L6 8z" fill="currentColor" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>',
    "next": '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M12 3v10M3 3.5v9L10 8z" fill="currentColor" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>',
    "play": '<svg class="i-play" viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 2.8v10.4L13 8z" fill="currentColor" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/></svg>',
    "pause": '<svg class="i-pause" viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 3h2.2v10H4.5zM9.3 3h2.2v10H9.3z" fill="currentColor"/></svg>',
    "full": '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 6V2.5H6M10 2.5h3.5V6M13.5 10v3.5H10M6 13.5H2.5V10" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
}


def player_controls(noimg: bool = False) -> str:
    speeds = "".join(f'<button type="button" data-speed="{s}" aria-pressed="false">{s}×</button>' for s in ("0.25", "0.5", "1"))
    return (f'<div class="pctl"><div class="lane" role="slider" tabindex="0" aria-label="Recording position" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" '
            f'title="Steps with robot motion; blue: steps that {"named a camera image file (the model received no images)" if noimg else "looked at a camera image"}"><span class="lane-tr"></span><span class="lane-mk"></span><b></b></div>'
            f'<div class="ctl"><button type="button" class="pb" data-k="prev" aria-label="Previous step" title="Previous step (←)" disabled>{ICON["prev"]}</button>'
            f'<button type="button" class="pb pp" data-k="play" aria-label="Play" title="Play or pause (space)" disabled>{ICON["play"]}{ICON["pause"]}</button>'
            f'<button type="button" class="pb" data-k="next" aria-label="Next step" title="Next step (→)" disabled>{ICON["next"]}</button>'
            f'<span class="seg sm" role="group" aria-label="Playback speed">{speeds}</span><span class="now trunc" aria-live="off"></span>'
            f'<button type="button" class="pb" data-k="full" aria-label="Full screen" title="Full screen (f)" disabled>{ICON["full"]}</button></div>'
            f'<p class="cap">Plays only while the robot moves.</p></div>')


def skeleton() -> str:
    return ('<div class="skl" aria-hidden="true"><span class="skel" style="width:38%;height:12px"></span>'
            + "".join(f'<span class="skel" style="width:{w}%;height:14px"></span>' for w in (92, 84, 88, 70, 90, 78, 86, 64, 80, 74)) + "</div>")


RUN_OF: dict[str, dict] = {}  # run slug -> {hm, ds, probe, trials, title, ...}, set in main; a trial's run is t["run"]


def group_runs(trials: list[dict], jobs: dict) -> dict[str, dict]:
    """Runs as people think of them: one model and harness on one hub dataset. The runner's jobs are per suite and are
    sometimes sharded (GR00T's four LIBERO suites), so jobs of one pair on one dataset merge into one run; a zero-shot
    probe (a policy on suites it was not trained for) is its own run, split per dataset."""
    out: dict[str, dict] = {}
    # a task the hub does not list (a pilot variant) belongs to the dataset that holds the rest of its suite
    by_suite: dict[str, Counter] = defaultdict(Counter)
    for t in trials:
        if t["task"] in HUB:
            by_suite[t["suite"]][HUB[t["task"]][1]] += 1
    for t in trials:
        ds = (HUB[t["task"]][1] if t["task"] in HUB else by_suite[t["suite"]].most_common(1)[0][0] if by_suite[t["suite"]]
              else SUITE_TITLE.get(t["suite"], t["suite"]))
        probe = "zeroshot" in t["job"]
        slug = re.sub(r"[^a-z0-9]+", "-", f'{HM[t["hm"]]["key"]} {ds}{" zero-shot" if probe else ""}'.lower()).strip("-")
        r = out.setdefault(slug, {"slug": slug, "hm": t["hm"], "ds": ds, "probe": probe, "trials": [], "jobs": set(), "start": "", "state": "finished"})
        r["trials"].append(t)
        r["jobs"].add(t["job"])
        if t["started"]:
            r["start"] = min(r["start"] or t["started"], t["started"])
        if jobs.get(t["job"], {}).get("state") == "running":
            r["state"] = "running"
        t["run"] = slug
    for r in out.values():
        ts = r["trials"]
        # the dataset's own tasks only, so a run and its dataset's Results agree; a pilot task the hub does not list is shown, not scored
        inds = [t for t in ts if t["counted"] and not t["infra"] and not t["partial"] and (not HUB or t["task"] in HUB)]
        r["scored"] = len(inds)
        r["solved"] = sum(1 for t in inds if t["solved"])
        r["title"] = f'{plab(r["hm"])} · {r["ds"].split("/")[-1]}' + (" · zero-shot probe" if r["probe"] else "")
        # a run whose model got no image input in any of its trials says so, counted or not (a run superseded by a
        # rerun under a new condition still was a run without images)
        r["noimg"] = bool(ts) and all(t.get("image_input") is False for t in ts)
    return out


def trial_crumbs(t: dict) -> str:
    """Runs / the run; the task title is the h1 right below."""
    r = RUN_OF.get(t.get("run", ""), {})
    run = f'<a href="/runs/r/{r["slug"]}/">{run_title_html(r)}</a>' if r else esc(t["job"])  # the run, with its marks
    return f'<nav class="crumbs" aria-label="Breadcrumb"><a href="/runs/">Runs</a><span>/</span>{run}</nav>'


def jpeg_size(p: Path) -> tuple[int, int] | None:
    """(width, height) of a baseline or progressive JPEG, read from its SOF marker (no imaging library)."""
    try:
        b = p.read_bytes()
    except OSError:
        return None
    i = 2
    while i + 9 < len(b):
        if b[i] != 0xFF:
            return None
        m, n = b[i + 1], int.from_bytes(b[i + 2:i + 4], "big")
        if m in (0xC0, 0xC1, 0xC2):
            return int.from_bytes(b[i + 7:i + 9], "big"), int.from_bytes(b[i + 5:i + 7], "big")
        i += 2 + n
    return None


def box_style(t: dict) -> str:
    """The player box takes the recording's shape (from its poster), so a 4:3 recording is not letterboxed in a square."""
    wh = jpeg_size(POSTERS / f"{t['trial']}.jpg")
    return f' style="--ar:{wh[0]}/{wh[1]}"' if wh and wh[1] else ""


def poster_attr(t: dict) -> str:
    """A still from the middle of the recording (runs/p/<trial>.jpg, extracted with ffmpeg on the build VM), so the player
    is never a black box before it plays."""
    return f' poster="/runs/p/{t["trial"]}.jpg"' if (POSTERS / f"{t['trial']}.jpg").is_file() else ""


POSTERS = Path()  # <out>/p, set in main


def build_trial(t: dict, n_steps: int, video: str | None) -> str:
    st = status(t)
    label = plab(t["hm"])
    # the badge says solved or not; the outcome is shown when it gives the reason, the reward when it is not plainly 0 or 1
    facts = [("Outcome", esc(budget_text(t) if st == "budget" else outcome_text(t["outcome"])))] if st not in ("ok", "infra") and t["outcome"] else []
    if st == "infra" and t.get("infra_cause"):
        facts = [("Why", esc(t["infra_cause"]["text"].rstrip(".")))]
    try:
        if float(t["reward"]) not in (0.0, 1.0):
            facts.append(("Reward", freward(t["reward"])))
    except (TypeError, ValueError):
        pass
    if st == "budget":
        b = t["budget"] or {}
        facts.append(("Budget", f'{esc(spend(b.get("cap_usd")))} per trial; {esc(spend(b.get("spent_usd")))} spent when stopped'))
    facts += ([("Steps", steps_html(t))] if t["steps_used"] is not None else []) + ([("Time", esc(fmt_s(t["wall"])))] if t["wall"] is not None else [])
    if t.get("seed") is not None:
        facts.append(("Seed", esc(t["seed"])))
    # the infrastructure badge already says "not scored"; another trial that does not count says why
    nc_why = earlier_reason(t) if t.get("earlier_condition") else "a later trial counts"
    counted = "" if t["counted"] or st == "infra" else f'<span class="tag">not counted: {nc_why}</span>'
    noimg = t.get("image_input") is False  # the who line's tag says so; the filmstrip and lane say the model saw no image
    vid = (f'<div class="vbox"{box_style(t)}><video id="vid" src="{video}"{poster_attr(t)} controls muted playsinline preload="metadata" disablepictureinpicture aria-label="Simulation recording"></video></div>{player_controls(noimg)}' if video
           else "")  # no recording: no player box at all (the stage gives the tabs the full width)
    tabs = [("recording", "Recording", ""), ("trajectory", "Trajectory", f" <span class=\"num\">{n_steps}</span>" if n_steps else ""), ("verdict", "Verdict", ""),
            ("run", "Timing &amp; tokens", ""), ("files", "Files", "")]
    never_ran = st == "infra" and not video and not n_steps and not t["steps_used"]
    why = (t.get("infra_cause") or {}).get("text", "") if never_ran else ""
    # nothing was recorded: the header and one sentence why; no facts, tabs or empty boxes
    head = f"""
{trial_crumbs(t)}
<section class="page-head head trial">
  <h1>{esc(t['title'])}</h1>
  <p class="who"><span class="badge {st}">{long_status(t, st)}</span>{f'<span class="mode" title="Embodiment mode">{esc(t.get("mode"))}</span>' if t.get("mode", "sim") != "sim" else ""}<span class="wl"{f' title="{esc(HM[t["hm"]]["provenance"])}"' if HM[t["hm"]].get("provenance") else ""}>{pair_html(t["hm"])}</span>{noimg_tag() if noimg else ""}{counted}{"" if never_ran else f'<a class="btn quiet sm cmp" href="/runs/compare/?a={esc(t["trial"])}">Compare</a>'}</p>
  {f'<p class="why">{esc(why or "The harness or the model API ended the trial before the agent acted.")}</p>' if never_ran else f'<dl class="facts">{"".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in facts)}</dl>'}
</section>
"""
    if never_ran:
        return page(f"{t['title']} · {label} · Runs · Robo Use", head, desc=f"{t['title']}: {label}, {STATUS_LONG[st].lower()}.",
                    cls="trialpage compact", data=f' data-trial="{esc(t["trial"])}"', canonical=f"https://robouse.ai/runs/t/{t['trial']}/")
    body = head + f"""<nav class="tabs" role="tablist" aria-label="Trial views" data-fade>
  {"".join(f'<a href="#{k}" role="tab" data-tab="{k}" aria-selected="false" aria-controls="panel">{x}{extra}</a>' for k, x, extra in tabs)}
</nav>
<div id="stage" class="stage t-recording"{"" if video else " data-novid"}>
  <div class="player" id="player">{vid}</div>
  <div id="panel" class="panel" role="tabpanel" aria-busy="true">{skeleton()}</div>
</div>
<noscript><style>.pctl,nav.tabs,#panel{{display:none}}</style><p class="muted">The trajectory, verdict and files need JavaScript; the recording plays above.</p></noscript>
"""
    return page(f"{t['title']} · {label} · Runs · Robo Use", body, desc=f"{t['title']}: {label}, {long_status(t, st).lower()}.",
                cls="trialpage", data=f' data-trial="{esc(t["trial"])}"', canonical=f"https://robouse.ai/runs/t/{t['trial']}/")


def build_compare() -> str:
    body = f"""
{runs_head("compare")}
<p class="meta tabnote">Pick two trials of one task.</p>
<div id="compare" class="compare" aria-busy="true">{skeleton()}</div>
<noscript><style>#compare{{display:none}}</style><p class="muted">Compare needs JavaScript. Each trial page plays its own recording.</p></noscript>
"""
    return page("Compare · Runs · Robo Use", body, cls="comparepage", canonical="https://robouse.ai/runs/compare/")


def ds_cell(ds: str) -> str:
    """org/name on one line on desktop; on phones the name leads and the org sits under it in small type (runs.css)."""
    org, _, name = ds.rpartition("/")
    if not org:
        return esc(ds)
    return f'<span class="ds"><span class="dso" title="{esc(org)}">{esc(org)}</span><span class="dss">/</span><wbr><span class="dsn">{esc(name)}</span></span>'


def build_runs(runs: dict) -> str:
    """/runs/: every run (one model and harness on one dataset), newest first; sortable and filterable, each row opens
    the run's trials. Two runs of one model on one dataset differ by their label (zero-shot probe) and start time."""
    rows = []
    # main runs first, newest day first, a day's runs by dataset, then model; zero-shot probes after them, in the same order
    order = sorted(runs.values(), key=lambda r: (r["ds"], plab(r["hm"]).lower()))
    order = sorted(order, key=lambda r: (r["start"] or "")[:10], reverse=True)
    for r in sorted(order, key=lambda r: bool(r["probe"])):
        i = r["hm"]
        rate = r["solved"] / r["scored"] if r["scored"] else -1
        tag = ' <span class="rtag">zero-shot probe</span>' if r["probe"] else ""
        state = ' <span class="state running">running</span>' if r["state"] == "running" else ""
        rows.append(f'<tr {pair_attrs(i)} data-dataset="{esc(r["ds"])}" data-q="{esc((plab(i) + " " + r["ds"] + (" zero-shot probe" if r["probe"] else "")).lower())}">'
                    f'<th scope="row" data-v="{i:04d}"><a class="rl" href="/runs/r/{r["slug"]}/">{phtml(i, False)}</a>{" " + noimg_tag() if r["noimg"] else ""}</th>'
                    f'<td class="sus" data-v="{esc(r["ds"])}">{ds_cell(r["ds"])}{tag}</td>'
                    f'<td class="muted num" data-v="{esc(r["start"])}">{esc(fmt_date(r["start"]))}{state}</td>'
                    f'<td class="n num" data-v="{r["scored"]}">{r["scored"]}</td>'
                    f'<td class="n num" data-v="{rate:.4f}">{pct(rate) if rate >= 0 else "·"}</td></tr>')
    idxs = sorted({r["hm"] for r in runs.values()})
    harn = sorted({(hslug(i), HM[i].get("harness_label") or HM[i]["harness"]) for i in idxs}, key=lambda x: x[1].lower())
    dss = sorted({r["ds"] for r in runs.values()})
    ctrl = ('<div class="fbar"><div class="frow ctl-row">'
            + '<label class="search"><span class="vh">Search runs</span><input type="search" data-lq placeholder="Search runs" autocomplete="off" spellcheck="false"></label>'
            + (f'<select data-lf="harness" aria-label="Harness"><option value="">All harnesses</option>{"".join(f"<option value={chr(34)}{esc(k)}{chr(34)}>{esc(v)}</option>" for k, v in harn)}</select>' if len(harn) > 1 else "")
            + (f'<select data-lf="dataset" aria-label="Dataset"><option value="">All datasets</option>{sel_opts(dss)}</select>' if len(dss) > 1 else "")
            + '<span class="count push" data-lcount aria-live="polite"></span></div></div>')
    body = f"""
{runs_head("runs")}
<div class="lst" data-list="jobs" data-limit="50" data-noun="runs">
{ctrl}
<div class="scroll tbl"><table class="list runs">
  <caption class="vh">Main runs first, newest first; zero-shot probes after them. Sort by any column.</caption>
  <thead><tr>{th_sort('Model<span class="hh"> · harness</span>', "num", "tcol")}{th_sort("Dataset", "text")}{th_sort("Date", "text").replace('<th ', '<th data-first="descending" ', 1)}{th_sort('<span class="sl-l">Scored trials</span><span class="sl-s">Scored</span>', "num", "n", title="Trials that count toward the solve rate; the run page lists every trial")}{th_sort('<span class="sl-l">Solve rate</span><span class="sl-s">Solved</span>', "num", "n")}</tr></thead>
  <tbody>{"".join(rows)}</tbody>
</table></div>
{list_foot("runs", "Clear the search or the filters.")}
</div>
"""
    return page("Runs · Robo Use", body, desc=f"{len(runs)} runs of {len(idxs)} models, each with its trials, recordings and verdicts.",
                cls="jobs", canonical="https://robouse.ai/runs/")


def title_html(title: str) -> str:
    """A task title; its variant ("… · vision") in its own span, which takes its own line on phones (runs.css)."""
    base, sep, var = title.rpartition(" · ")
    if not sep:
        return esc(title)
    return f'{esc(base)}<span class="tvar"><span class="tsep"> · </span>{esc(var)}</span>'


def build_run(r: dict) -> str:
    rows = []
    # a column most of whose rows have no value (trials that never ran) is left out; a single missing value is blank
    show_steps = sum(t["steps_used"] is not None for t in r["trials"]) * 2 > len(r["trials"])
    show_time = sum(t["wall"] is not None for t in r["trials"]) * 2 > len(r["trials"])
    # the counted trial of each task first; an earlier trial of the same task says so, with its start time
    for t in sorted(r["trials"], key=lambda t: (t["title"], t["task"], not t["counted"], str(t.get("seed")), t["started"] or "")):
        st = status(t)
        seed = f'<span class="muted tmeta"><span class="tsep"> · </span>seed {esc(t["seed"])}</span>' if t.get("seed") is not None else ""
        if not t["counted"]:
            seed += f'<span class="muted tmeta"><span class="tsep"> · </span>earlier trial, {esc(fmt_day(t["started"]))}</span>'
        elif HUB and t["task"] not in HUB:
            seed += '<span class="muted tmeta"><span class="tsep"> · </span>pilot task, not in the dataset or its score</span>'
        rows.append(f'<tr class="{"" if t["counted"] else "dim"}" data-outcome="{st}" data-counted="{int(t["counted"])}" data-q="{esc((t["task"] + " " + t["title"]).lower())}">'
                    f'<th scope="row" data-v="{esc(t["title"])}"><a class="rtk" href="/runs/t/{esc(t["trial"])}/">{title_html(t["title"])}</a>{seed}{f'<span class="oc2">{esc(result_note(t))}</span>' if result_note(t) else ""}</th>'
                    f'<td data-v="{ST_RANK[st]}"><span class="badge {st}">{STATUS_TEXT[st]}</span>{"" if t["counted"] else ' <span class="muted rnc">not counted</span>'}</td>'
                    f'<td class="oc">{esc(result_note(t))}</td>'
                    + (f'<td class="n num stc" data-v="{num_attr(t["steps_used"])}">{steps_html(t)}</td>' if show_steps else "")
                    + (f'<td class="n num" data-v="{num_attr(t["wall"])}">{esc(fmt_s(t["wall"])) if t["wall"] is not None else NOT_RECORDED}</td>' if show_time else "") + "</tr>")
    states = {status(t) for t in r["trials"]}
    opts = "".join(f'<option value="{k}">{v}</option>' for k, v in (("ok", "Solved"), ("no", "Not solved"), ("budget", "Stopped at budget"), ("infra", "Infrastructure failure"), ("partial", "Partial")) if k in states)
    ctrl = ('<div class="fbar"><div class="frow ctl-row">'
            '<label class="search"><span class="vh">Search tasks</span><input type="search" data-lq placeholder="Search tasks" autocomplete="off" spellcheck="false"></label>'
            + (f'<select data-lf="outcome" aria-label="Result"><option value="">Any result</option>{opts}</select>' if len(states) > 1 else "")
            + '<span class="count push" data-lcount aria-live="polite"></span></div></div>')
    body = f"""
<nav class="crumbs" aria-label="Breadcrumb"><a href="/runs/">Runs</a><span>/</span>{run_title_html(r)}</nav>
<section class="page-head head">
  <h1 class="rh1">{run_title_html(r)}</h1>
  <p class="meta">{esc(r["ds"])} · {esc(fmt_date(r["start"]))} · {f'{r["solved"]} of {r["scored"]} solved' if r["scored"] else "no scored trial"}{' · <span class="state running">running</span>' if r["state"] == "running" else ""}{" " + noimg_tag() if r["noimg"] else ""}</p>
  {f'<p class="prov">{esc(HM[r["hm"]]["provenance"])}</p>' if HM[r["hm"]].get("provenance") else ""}
</section>
<div class="lst" data-list="job" data-limit="100" data-noun="trials">
{ctrl}
<div class="scroll tbl"><table class="list rt">
  <thead><tr>{th_sort("Task", "text", "tcol")}{th_sort("Result", "num")}{th_sort("Outcome", "text", "oc")}{th_sort("Steps", "num", "n stc") if show_steps else ""}{th_sort("Time", "num", "n") if show_time else ""}</tr></thead>
  <tbody>{"".join(rows)}</tbody>
</table></div>
{list_foot("trials", "Clear the search or the filter.")}
</div>
"""
    return page(f"{r['title']} · Runs · Robo Use", body, cls="jobs", desc=f"{r['title']}: " + (f"{r['solved']} of {r['scored']} solved." if r["scored"] else "no scored trial."),
                canonical=f"https://robouse.ai/runs/r/{r['slug']}/")


# ---------------------------------------------------------------- checks

def scan(out: Path) -> list[str]:
    hits = []
    for p in out.rglob("*"):
        if p.suffix not in (".html", ".css", ".js", ".json", ".txt"):
            continue
        s = p.read_text(errors="replace")
        for rx in SECRET_RES + [BANNED, PERSONAL]:
            for m in rx.finditer(s):
                hits.append(f"{p.relative_to(out)}: {m.group(0)[:60]}")
    return hits


def check_links(out: Path, site: Path) -> list[str]:
    """Every href/src in the pages resolves to a file in the site; every video, sprite and trial id in the data exists."""
    bad = []
    rx = re.compile(r'(?:href|src)="([^"#?]+)[^"]*"')
    for p in out.rglob("*.html"):
        for u in set(rx.findall(p.read_text(errors="replace"))):
            if u.startswith(("http:", "https:", "mailto:")):
                continue
            target = (site / u.lstrip("/")) if u.startswith("/") else (p.parent / u)
            if target.is_dir() or u.endswith("/"):
                target = target / "index.html"
            if not target.exists():
                bad.append(f"{p.relative_to(out)} -> {u}")
    ids = set(json.loads((out / "d" / "trials.json").read_text())["trials"])
    for p in (out / "d").glob("*.json"):
        if p.name == "trials.json":
            continue
        d = json.loads(p.read_text())
        for k in ("video", "sprite"):
            v = d.get(k)
            src = v.get("src") if isinstance(v, dict) else v
            if src and not (site / src.lstrip("/")).is_file():
                bad.append(f"d/{p.name}: missing {src}")
        for o in d.get("others") or []:
            if o not in ids:
                bad.append(f"d/{p.name}: other trial {o} not published")
    return bad


# ---------------------------------------------------------------- synthetic scale fixture (--synthetic N)

SYN_HARNESS = [("claude-code", "Claude Code", "cc"), ("codex", "Codex", "codex"), ("mini-swe-agent", "mini-swe-agent", "mini"),
               ("openhands", "OpenHands", "oh"), ("gemini-cli", "Gemini CLI", "gcli")]
SYN_MODELS = [("claude-opus-5-5", "Opus 5.5", "Claude", "Anthropic", "closed", .9, "2026-05-01"), ("claude-sonnet-5", "Sonnet 5", "Claude", "Anthropic", "closed", .82, "2026-03-01"),
              ("gpt-6-astra", "GPT-6 Astra", "GPT", "OpenAI", "closed", .86, "2026-06-01"), ("gpt-6-mini", "GPT-6 mini", "GPT", "OpenAI", "closed", .64, "2026-06-01"),
              ("zai-org/GLM-5.3", "GLM-5.3", "GLM", "Z.ai", "open", .7, "2026-04-01"), ("moonshotai/Kimi-K3", "Kimi K3", "Kimi", "Moonshot AI", "open", .76, "2026-05-15"),
              ("Qwen/Qwen4-Coder", "Qwen4 Coder", "Qwen", "Alibaba", "open", .6, "2026-02-01"), ("deepseek-ai/DeepSeek-V4", "DeepSeek V4", "DeepSeek", "DeepSeek", "open", .68, "2026-01-20"),
              ("gemini-3-pro", "Gemini 3 Pro", "Gemini", "Google", "closed", .8, "2026-04-20"), ("meta-llama/Llama-5-405B", "Llama 5 405B", "Llama", "Meta", "open", .48, "2025-12-01")]
SYN_SHARED = ("tokens.css", "chrome.css", "prose.css", "surface.css", "ui.css", "ui.js", "filetree.css", "filetree.js", "modelset.js", "theme.js",
              "site.css", "bridge.css", "favicon.png", "fonts", "index.html", "blog", "docs", "hub", "og")


def synth_registry() -> list[dict]:
    """30 fabricated harness + model pairs: every model with three harnesses."""
    pairs = []
    for mi, (model, ml, fam, prov, w, skill, rel) in enumerate(SYN_MODELS):
        for k in range(3):
            h, hl, hk = SYN_HARNESS[(mi + k) % len(SYN_HARNESS)]
            key = f"{hk}-{re.sub(r'[^a-z0-9]+', '-', ml.lower()).strip('-')}"
            pairs.append({"key": key, "harness": h, "model": model, "label": f"{hl} + {ml}", "short": f"{hl}<br>{ml}", "harness_label": hl, "model_label": ml,
                          "family": fam, "provider": prov, "weights": w, "kind": "agent", "released": rel, "status": "active", "note": "", "cost_ok": False,
                          "_skill": skill - .06 * k})
    return pairs


def synthesize(real: list[dict], n_tasks: int, n_seeds: int, scratch: Path) -> tuple[list[dict], dict]:
    """Fabricated trials: n_tasks real tasks (spread over the suites) x every synthetic pair x n_seeds seeds. The first
    seed of each pair on the first two tasks borrows a real trial folder (so trial pages show a real recording,
    trajectory and files); the rest have no folder. Outcomes are random, seeded, and depend on a per-pair skill."""
    import random

    rng = random.Random(7)
    empty = scratch / "empty-trial"
    empty.mkdir(parents=True, exist_ok=True)
    by_task = defaultdict(list)
    for t in real:
        by_task[t["task"]].append(t)
    by_suite = defaultdict(list)
    for task in sorted(by_task):
        if any(x["video"] if "video" in x else True for x in by_task[task]):
            by_suite[by_task[task][0]["suite"]].append(task)
    order = [s for s in SUITES if s in by_suite] + sorted(set(by_suite) - set(SUITES))
    tasks = []
    while len(tasks) < n_tasks and any(by_suite[s] for s in order):
        for s in order:
            if by_suite[s] and len(tasks) < n_tasks:
                tasks.append(by_suite[s].pop(0))
    # the borrowed tasks: ones with a real recording and a published trajectory
    rich = [k for k in tasks if any((t["dir"] / "artifacts" / "recording.mp4").is_file() and (t["dir"] / "agent" / "trajectory.json").is_file() for t in by_task[k])]
    borrow = set(rich[:2])
    trials, jobs = [], {}
    t0 = datetime(2026, 9, 1, tzinfo=UTC).timestamp()
    for ti, task in enumerate(tasks):
        srcs = sorted(by_task[task], key=lambda t: (not t.get("counted"), t["infra"], t["trial"]))
        src = next((t for t in srcs if (t["dir"] / "artifacts" / "recording.mp4").is_file()), srcs[0])
        hard = DIFF_RANK.get(src["difficulty"], 2) - 2
        tnoise = rng.uniform(-.25, .2)
        for i, p in enumerate(HM):
            for seed in range(1, n_seeds + 1):
                infra = rng.random() < .03
                solved = not infra and rng.random() < max(.02, min(.98, p["_skill"] - .12 * hard + tnoise))
                real_dir = task in borrow and seed == 1
                start = t0 + ti * 3600 + i * 97 + seed * 13
                wall = rng.uniform(40, 900)
                mx = src["max_steps"] or 300
                trial = f"{task}__{p['key']}__s{seed}"
                t = {"dir": src["dir"] if real_dir else empty, "job": f"synth-{p['key']}", "trial": trial, "task": task, "suite": src["suite"], "source": src["source"],
                     "difficulty": src["difficulty"], "category": src["category"], "harness": p["harness"], "model": p["model"], "hm": i, "seed": seed,
                     "cfg": {**src["cfg"], "harness": p["harness"], "model": p["model"], "seed": seed, "trial_name": trial},
                     "res": src["res"] if real_dir else {"synthetic": True}, "reward": None if infra else (1.0 if solved else 0.0), "solved": solved, "infra": infra,
                     "partial": False, "outcome": "infra_error" if infra else ("success_reached" if solved else "max_steps_reached"),
                     "steps_used": None if infra else rng.randint(8, mx), "max_steps": mx, "wall": round(wall, 1), "checks": {"robo_requests": rng.randint(5, 120)},
                     "infra_items": [{"id": "synthetic", "evidence": "fabricated infrastructure failure"}] if infra else [], "agent_text": "", "final_message": "",
                     "started": datetime.fromtimestamp(start, UTC).isoformat(), "finished": datetime.fromtimestamp(start + wall, UTC).isoformat(),
                     "src_trial": src["trial"] if real_dir else None}
                if ti == 0 and i == 0 and seed == 1:  # one fabricated trial carries every optional block (leaderboard spec section 5)
                    t["fake_extra"] = {
                        "mode": "hil-mock",
                        "metrics": [["Success", "yes", "", "higher"], ["Task progress", "100", "% of stages", "higher"], ["Execution time", "41.2", "s", "lower"],
                                    ["Execution speed", "4.370", "stages/min", "higher"], ["Smoothness (SPARC)", "-1.842", "", "closer to 0"],
                                    ["Avg jerk", "3.105", "m/s³", "lower"], ["Safety events", "1", "", "lower"], ["Max contact force", "12.4", "N", "lower"]],
                        "placement": {"split": "extrapolation", "objects": 3, "max_cm": 6.2, "seed": 1},
                        "operator": {"verdict": "stage 2 of 3", "rubric": True, "channel": "script", "note": "synthetic: the lid was placed but not pressed down"},
                        "safety": {"counts": {"veto": 3, "stop": 1}, "items": [[4.21, "veto", "target outside the workspace envelope"], [9.87, "veto", "joint limit"],
                                   [12.5, "veto", "target outside the workspace envelope"], [30.02, "stop", "thermal stop"]], "more": 0},
                        "cost": {"prompt": 412345, "completion": 18230, "cached": 301000, "usd": 1.2871, "source": "pricing.json (list prices, 2026-09)"},
                        "vla": {"inferences": 27, "chunk": 10, "roundtrip": [3.412, 4.105], "server": [2.803, 3.377]}}
                trials.append(t)
                j = jobs.setdefault(t["job"], {"name": t["job"], "state": "finished", "dirs": 0, "trials": 0, "unfinished": 0, "hm": i, "suites": set(), "start": "", "end": ""})
                j["dirs"] += 1
                j["trials"] += 1
                j["suites"].add(t["suite"])
                j["start"] = min(j["start"] or t["started"], t["started"])
                j["end"] = max(j["end"], t["finished"])
    return trials, jobs


def synth_site(site: Path, chosen: dict) -> None:
    """The scratch site root: links to the shared foundation (read only) and a models.json of the synthetic pairs."""
    for name in SYN_SHARED:
        dst, src = site / name, REAL_SITE / name
        if src.exists() and not dst.exists() and not dst.is_symlink():
            dst.symlink_to(src)
    pairs = []
    for i, p in enumerate(HM):
        solved = scored = 0
        for (hm, _task), ts in chosen.items():
            if hm == i:
                for t in ts:
                    if not t["infra"] and not t["partial"]:
                        scored += 1
                        solved += int(t["solved"])
        pairs.append({k: p.get(k) for k in ("key", "label", "harness_label", "model_label", "family", "provider", "weights", "kind", "released", "status", "note", "short")}
                     | {"solved": solved, "scored": scored, "rate": round(solved / scored, 4) if scored else 0})
    (site / "models.json").write_text(json.dumps({"synthetic": True, "pairs": pairs}, indent=1))


# ---------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    global VER, SYNTH
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True, help="the runs/ folder of the site (its parent is the site root)")
    ap.add_argument("--jobs", default="", help="comma-separated job prefixes to include (default: every runs/final-* job)")
    ap.add_argument("--workers", type=int, default=8, help="parallel video encodes")
    ap.add_argument("--no-video", action="store_true", help="skip re-encoding (pages still link the videos that exist)")
    ap.add_argument("--synthetic", type=int, default=0, metavar="N", help=argparse.SUPPRESS)  # scale fixture: N tasks x 30 pairs x --seeds seeds
    ap.add_argument("--seeds", type=int, default=5, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    out = a.out.expanduser().resolve()
    site = out.parent
    VER = datetime.now(UTC).strftime("%Y%m%d%H%M")
    SYNTH = a.synthetic > 0
    if SYNTH:
        if out.is_relative_to(REAL_SITE.resolve()) or out.is_relative_to(REAL_SITE.parent.resolve()):
            print("--synthetic never writes into the site repo; pass a scratch --out (for example /tmp/pwrun/synth/site/runs)", file=sys.stderr)
            return 2
        (site.parent / "tools").mkdir(parents=True, exist_ok=True)
        chrome = site.parent / "tools" / "chrome.py"
        if not chrome.exists():
            chrome.symlink_to(REAL_SITE.parent / "tools" / "chrome.py")
        load_models(REAL_SITE.parent / "tools" / "models.json")
    else:
        load_models(site.parent / "tools" / "models.json")
    load_chrome(site)
    audit_mod = load_audit()
    trials, jobs = collect(audit_mod, tuple(p for p in a.jobs.split(",") if p))
    chosen = pick(trials)
    if SYNTH:
        HM[:] = synth_registry()
        HM_KEY.clear()
        HM_KEY.update({(p["harness"], p["model"]): i for i, p in enumerate(HM)})
        (site.parent / "tools" / "models.json").write_text(json.dumps({"synthetic": True, "pairs": HM}, indent=1))
        trials, jobs = synthesize(trials, a.synthetic, a.seeds, site.parent)
        chosen = pick(trials)
        synth_site(site, chosen)
    HAS_SEEDS[0] = any(len(ts) > 1 for ts in chosen.values())
    for i, p in enumerate(HM):  # a column whose model got no image input in every counted trial carries the label
        mine = [t for ts in chosen.values() for t in ts if t["hm"] == i]
        p["_noimg"] = bool(mine) and all(t.get("image_input") is False for t in mine)
    HUB.update(hub_tasks(site))
    RUN_OF.update(group_runs(trials, jobs))
    global POSTERS
    POSTERS = out / "p"
    for sub in ("t", "task", "d", "jobs", "r"):
        if (out / sub).exists():
            shutil.rmtree(out / sub)
    for sub in ("v", "f", "d", "t", "r", "compare"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    tdocs: dict[str, dict] = {}
    tinfo: dict[str, dict] = {}
    for t in trials:
        if t["task"] not in tdocs:
            tdocs[t["task"]] = read_task(t["cfg"].get("task_path"), t["suite"], t["task"])
        t["title"] = HUB_TITLE.get(t["task"]) or title_of(tdocs[t["task"]]["body"], t["task"])
        tinfo.setdefault(t["task"], {"suite": t["suite"], "title": t["title"], "difficulty": t["difficulty"], "source": t["source"]})

    encodes, sprites, keep_v, keep_f = [], [], set(), set()
    withheld = 0

    def link_real(kind: str, src_trial: str, dst: Path) -> bool:
        """--synthetic: a borrowed trial's published video or filmstrip, linked (never copied or re-encoded)."""
        real = REAL_SITE / "runs" / kind / f"{src_trial}{dst.suffix}"
        if not real.is_file():
            return False
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        dst.symlink_to(real)
        return True

    def one(t: dict) -> tuple[int, int]:
        traj = trajectory(t["dir"], t["harness"])
        t["withheld"] = w = looked_outside(traj)
        spec = (tdocs[t["task"]]["fm"] or {}).get("robouse") or {}
        d = t["dir"]
        src = next((d / r for r in ("artifacts/recording.mp4", "episode/recording.mp4") if (d / r).is_file()), None)
        video = None
        if SYNTH:
            dst = out / "v" / f"{t['trial']}.mp4"
            if src is not None and t.get("src_trial") and link_real("v", t["src_trial"], dst):
                keep_v.add(dst.name)
                video = f"/runs/v/{t['trial']}.mp4"
        elif src is not None and _playable(src):  # an episode that ended before any frame leaves a header-only file
            dst = out / "v" / f"{t['trial']}.mp4"
            keep_v.add(dst.name)
            encodes.append((src, dst))
            video = f"/runs/v/{t['trial']}.mp4"
        obs_dir = next((d / r for r in ("artifacts/observations", "episode/observations") if (d / r).is_dir()), None)
        obs = sorted(obs_dir.glob("*.png")) if obs_dir else []
        sprite, obs_map = None, {}
        if obs:
            shown = sample(obs, MAX_TILES)
            dst = out / "f" / f"{t['trial']}.webp"
            ok = True
            if SYNTH:
                ok = bool(t.get("src_trial")) and link_real("f", t["src_trial"], dst)
            else:
                sprites.append((shown, dst))
            if ok:
                keep_f.add(dst.name)
                sprite = {"src": f"/runs/f/{t['trial']}.webp", "tile": TILE, "disp": TILE // 2, "cols": SPRITE_COLS, "n": len(shown), "total": len(obs)}
                obs_map = {p.name: i for i, p in enumerate(shown)}
        data = trial_data(t, traj, spec, video, sprite, obs_map)
        data["files"] = files_of(d) if d.name != "empty-trial" else []
        data["mark"] = model_mark(HM[t["hm"]]) if HM[t["hm"]].get("icon") else ""  # the marks beside the names in Compare
        data["hmark"] = harness_mark(HM[t["hm"]])
        ws = str(t["cfg"].get("workspace") or "")
        data["result_json"] = sanitized_json(t["res"], ws) if t["res"] else ""
        data["config_json"] = sanitized_json({k: v for k, v in t["cfg"].items() if k not in ("workspace", "sandbox")}, ws)  # the sandbox rule names the operator's folders
        data["hub"] = HUB.get(t["task"], ("", ""))[0]
        (out / "d" / f"{t['trial']}.json").write_text(json.dumps(redact_all(data), ensure_ascii=False, separators=(",", ":")))
        n = len(data["steps"]) + data.get("hidden", 0) if not w else 0  # the Trajectory badge: the last step number the lists show
        pdir = out / "t" / t["trial"]
        pdir.mkdir(parents=True, exist_ok=True)
        t["mode"] = (data.get("extra") or {}).get("mode") or "sim"
        (pdir / "index.html").write_text(build_trial(t, n, video))
        return int(w), 1

    with ThreadPoolExecutor(8) as ex:
        for w, _ in ex.map(one, trials):
            withheld += w

    suites = sorted({i["suite"] for i in tinfo.values()})
    for p in [out / "index.html", *(p for p in out.iterdir() if p.is_dir() and p.name not in ("t", "v", "f", "p", "d", "r", "compare"))]:
        if p.is_dir():  # the results matrix, suite and task pages of earlier builds: the hub has them now (308s in vercel.json)
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    counted = sum(len(ts) for ts in chosen.values())
    (out / "compare" / "index.html").write_text(build_compare())
    for slug, r in RUN_OF.items():
        (out / "r" / slug).mkdir(parents=True, exist_ok=True)
        (out / "r" / slug / "index.html").write_text(build_run(r))
    (out / "index.html").write_text(build_runs(RUN_OF))
    # the old job pages: each job's URL moves to the run that holds its trials (tools/build_hub.py writes the 308s)
    moved = {f"/runs/jobs/{t['job']}": f"/runs/r/{t['run']}/" for t in sorted(trials, key=lambda t: t["trial"])}
    (out / "d" / "moved.json").write_text(json.dumps(dict(sorted(moved.items())), indent=1))
    index = {"hm": [[p["label"], p["key"]] for p in HM], "suites": {s: SUITE_TITLE.get(s, s) for s in suites},
             "trials": {t["trial"]: [t["task"], t["hm"], status(t), int(t["counted"])] for t in trials},
             "titles": {k: v["title"] for k, v in tinfo.items()}, "urls": {k: HUB[k][0] for k in tinfo if k in HUB}}
    (out / "d" / "trials.json").write_text(json.dumps(redact_all(index), ensure_ascii=False, separators=(",", ":")))
    for name in ("runs.css", "runs.js"):
        shutil.copyfile(ASSETS / name, out / name)
    for p in (out / "v").glob("*.mp4"):
        if p.name not in keep_v:
            p.unlink()
    for p in (out / "f").glob("*.webp"):
        if p.name not in keep_f:
            p.unlink()
    if not a.no_video and not SYNTH:
        with ThreadPoolExecutor(a.workers) as ex:
            list(ex.map(lambda sd: transcode(*sd), encodes))
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda sd: make_sprite(*sd), sprites))
    for p in list(out.rglob("*.tmp.*")):
        p.unlink()
    hits = scan(out)
    bad = check_links(out, site)
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file() and not p.is_symlink())
    part = {k: sum(p.stat().st_size for p in (out / k).rglob("*") if p.is_file() and not p.is_symlink()) / 1e6 for k in ("v", "f", "d", "t")}
    nfiles = sum(1 for p in out.rglob("*") if p.is_file())
    print(f"wrote {out}: {len(trials)} trial pages ({counted} counted), {len(tinfo)} tasks, {len(suites)} suites, {len(jobs)} jobs, "
          f"{withheld} trajectories withheld; {nfiles} files, total {size / 1e6:.1f} MB "
          f"(videos {part['v']:.1f}, filmstrips {part['f']:.1f}, data {part['d']:.1f}, pages {part['t']:.1f})")
    running = sorted(n for n, j in jobs.items() if j["state"] == "running")
    if running:
        print("still running (rebuild later for more trials): " + ", ".join(running))
    ok = True
    if hits:
        print(f"PUBLISH SCAN FAILED: {len(hits)} hits", file=sys.stderr)
        for h in hits[:50]:
            print("  " + h, file=sys.stderr)
        ok = False
    if bad:
        print(f"LINK CHECK FAILED: {len(bad)} broken", file=sys.stderr)
        for h in bad[:50]:
            print("  " + h, file=sys.stderr)
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
