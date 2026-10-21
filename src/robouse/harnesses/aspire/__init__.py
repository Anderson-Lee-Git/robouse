"""The `aspire` and `aspire-codex` harnesses: NVIDIA's ASPIRE workflow, run by Claude Code or Codex, in a Robo Use trial.

ASPIRE ("Agentic /Skills Discovery for Robotics", NVlabs/ASPIRE, Apache-2.0; arXiv 2607.00272) is a workflow for
coding agents that write robot programs: explore the scene, write a program, run it on development seeds, debug it by
failure mode, select one program, check it once on unseen seeds and evaluate it frozen on held-out seeds; patterns
that a verifier could reproduce a fix from are promoted into a skill library that later tasks read. Its workflow
ships as agent skills (`iterative-debugging`, `evosearch`) over its own program runner, cap-harness.

Here the agent runs ASPIRE's skill files unchanged (vendored in `upstream/` at the pinned commit, `library.py`), as
the coordinator of a one-task campaign, in a workspace that maps ASPIRE onto Robo Use (`workspace/robouse.md`):

- practice: `cap-harness` in the workspace (workspace/cap_harness.py) runs programs on practice episodes, the
  task's own episode server on other seeds of the task, through the trial's practice broker (broker.py), which
  refuses the scored scene, seeds outside ASPIRE's development and unseen-check bands, and runs past the budget;
- Stage 2: when the agent exits, the driver (workspace/driver.py) has the broker freeze the trial and runs the selected
  program once on the scored episode, then ends it with `robo done`. The episode server and its judge are unchanged.
- the skill library: a copy per trial, or with ROBOUSE_ASPIRE_LIBRARY a folder that persists across a suite's trials;
  a task whose selected program the folder already holds is evaluated without a new Stage 1, as ASPIRE evaluates one
  frozen program on every held-out seed.

Tasks run on a backend with a practice profile (PROFILES): one whose seeds give distinct scenes by a known rule, so
the broker can tell the scored scene apart. Anything else is refused before the trial starts.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ... import config
from .broker import PracticeBroker, WorkspaceReader, fmt
from .library import ASPIRE_COMMIT, ASPIRE_REPO, UPSTREAM, Library, file_hashes, scene_id, skill_library_sha

HERE = Path(__file__).resolve().parent
WORKSPACE_FILES = HERE / "workspace"
WORKFLOWS = ("iterative-debugging", "evosearch")
AGENTS = {"aspire": "claude-code", "aspire-codex": "codex"}
# the tools Claude Code offers its model: Robo Use's usual six, the Agent tool for ASPIRE's worker and verifier
# subagents, and Skill for the ASPIRE skills in the workspace's .claude/skills
CLAUDE_TOOLS = "Bash,Read,Write,Edit,Glob,Grep,Agent,Skill"
CLAUDE_MAX_TURNS = 2000
BASH_MAX_TIMEOUT_MS = 2 * 3600 * 1000
MIN_TIMEOUT_S = 4 * 3600  # an ASPIRE campaign for one task: at least four hours unless --timeout says otherwise
LIBERO_INIT_STATES = 50  # LIBERO ships 50 initial states per task; CaP-X's seed n restores state (n - 1) % 50


@dataclass(frozen=True)
class Profile:
    """How ASPIRE's seed protocol maps onto one task backend: its development and unseen-check bands (ASPIRE's own
    for the benchmark the backend comes from), the backend's seed rule (seed -> scene), and the campaign names
    (BENCHMARK, SUITE, TASK_ID) of a task."""

    dev: tuple[int, ...]
    unseen: tuple[int, ...]
    rule: str
    scene: Callable[[int], Any]
    family: Callable[[Any], tuple[str, str, int]]
    perception: str


def _capx_family(task: Any) -> tuple[str, str, int]:
    return ("capx", str(task.spec.get("env")), 0)


def _capx_libero_family(task: Any) -> tuple[str, str, int]:
    _, suite, idx = str(task.spec.get("env")).split(":")
    return ("capx-libero", suite, int(idx))


PROFILES: dict[str, Profile] = {
    # CaP-X's robosuite tasks: the seed seeds robosuite's placement sampler, so every seed is its own layout; ASPIRE's
    # Robosuite bands (development 101-125, unseen-check 126-130)
    "capx": Profile(
        dev=tuple(range(101, 126)),
        unseen=tuple(range(126, 131)),
        rule="seed n is robosuite's object layout n",
        scene=lambda s: s,
        family=_capx_family,
        perception="CaP-X's privileged API: object poses from the simulator",
    ),
    # CaP-X's LIBERO-PRO tasks restore one of LIBERO's 50 saved initial states, (n - 1) % 50: ASPIRE's LIBERO bands
    # (51-65 and 66-80) would replay states 0-29, so the bands here are other saved states
    "capx_libero": Profile(
        dev=tuple(range(36, 51)),
        unseen=tuple(range(21, 36)),
        rule=f"seed n restores LIBERO's saved initial state (n - 1) % {LIBERO_INIT_STATES}",
        scene=lambda s: (s - 1) % LIBERO_INIT_STATES,
        family=_capx_libero_family,
        perception="CaP-X's privileged LIBERO API: object poses from the simulator",
    ),
}


def saved_state_bands(n: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Development and unseen-check seeds among n saved start states (seed k restores state (k - 1) % n): the last
    15 states, and the 15 before them, as many as there are, never state 0 (the tasks' own seed 1)."""
    size = min(15, (n - 1) // 2)
    if size < 1:
        raise ValueError(f"{n} saved start states leave no practice scene besides the scored one")
    return tuple(range(n - size + 1, n + 1)), tuple(range(n - 2 * size + 1, n - size + 1))


def _libero_profile(task: Any) -> Profile:
    """LIBERO tasks that name their start states, as the libero-pro suite's do (LIBERO-PRO's init files):
    `init_mode: seeded` draws a new layout per seed (ASPIRE's `--init-mode seeded`), so ASPIRE's own LIBERO bands
    apply; `saved` restores state (n - 1) mod N (ASPIRE's `--init-mode saved`), so the bands are saved states other
    than the scored one. A task with one fixed start state gives every seed the same scene: refused.

    This reads the task's `init_mode` and `init_states` only. The libero backend starts an episode from them only with
    the libero-pro suite's backend change (its saved and seeded start modes); on a backend without it every seed of a
    LIBERO task starts from the same state, so such a task must not reach this profile."""
    spec = task.spec
    family = (str(task.metadata.get("suite") or "libero"), str(spec.get("suite")), int(spec.get("task_index", 0)))
    perception = (
        "the robot's own state and the task's camera images (robo.image) with their calibration (robo.info()), "
        "no object poses"
        if spec.get("obs_mode") == "vision"
        else "the robot's and the objects' state (robo.observe)"
    )
    if spec.get("init_mode") == "seeded":
        return Profile(
            dev=tuple(range(51, 66)),
            unseen=tuple(range(66, 81)),
            rule="seed n is LIBERO's placement sampler seeded with n",
            scene=lambda seed: seed,
            family=lambda t: family,
            perception=perception,
        )
    if not spec.get("init_states"):
        raise ValueError(
            f"{task.id} starts every episode from one fixed state, so no seed shows another scene to practise on"
        )
    n = int(spec["init_states"].get("count") or LIBERO_INIT_STATES)
    dev, unseen = saved_state_bands(n)
    return Profile(
        dev=dev,
        unseen=unseen,
        rule=f"seed n restores the task's saved start state (n - 1) % {n}",
        scene=lambda seed: (seed - 1) % n,
        family=lambda t: family,
        perception=perception,
    )


# backends whose profile depends on the task (its own seed rule)
PROFILE_FACTORIES: dict[str, Callable[[Any], Profile]] = {"libero": _libero_profile}


def profile_for(task: Any) -> Profile:
    backend = str(task.spec.get("backend"))
    if backend in PROFILE_FACTORIES:
        return PROFILE_FACTORIES[backend](task)
    if backend not in PROFILES:
        known = ", ".join(sorted([*PROFILES, *PROFILE_FACTORIES]))
        raise ValueError(
            f"the aspire harnesses run code-as-policy tasks whose seeds give distinct scenes ({known} backends); "
            f"{task.id} runs on {backend!r}"
        )
    return PROFILES[backend]


def parse_seeds(spec: str) -> list[int]:
    """101-125, or 101,103,110-112."""
    out: list[int] = []
    for part in spec.split(","):
        a, _, b = part.strip().partition("-")
        if not a.isdigit() or (b and not b.isdigit()):
            raise ValueError(f"seeds look like 101-125 or 101,103 (positive integers), not {spec!r}")
        out += list(range(int(a), int(b) + 1)) if b else [int(a)]
    return sorted(set(out))


def bands(profile: Profile, protected: set) -> tuple[list[int], list[int], list[int]]:
    """(development, unseen-check, dropped) seeds: the profile's, or ROBOUSE_ASPIRE_DEV_SEEDS and
    ROBOUSE_ASPIRE_UNSEEN_SEEDS; seeds showing a protected scene are dropped."""
    dev = (
        parse_seeds(config.env("ROBOUSE_ASPIRE_DEV_SEEDS"))
        if config.env("ROBOUSE_ASPIRE_DEV_SEEDS")
        else list(profile.dev)
    )
    unseen = (
        parse_seeds(config.env("ROBOUSE_ASPIRE_UNSEEN_SEEDS"))
        if config.env("ROBOUSE_ASPIRE_UNSEEN_SEEDS")
        else list(profile.unseen)
    )
    if set(dev) & set(unseen):
        raise ValueError("development and unseen-check seeds overlap")
    if min([*dev, *unseen], default=2) < 2:
        raise ValueError("practice seeds start at 2: ASPIRE's held-out band is 1..N below them")
    dropped = sorted(s for s in [*dev, *unseen] if profile.scene(s) in protected)
    dev = [s for s in dev if s not in dropped]
    unseen = [s for s in unseen if s not in dropped]
    if not dev or not unseen:
        raise ValueError("no development or no unseen-check seed is left once the scored scene is excluded")
    return dev, unseen, dropped


def workflow() -> str:
    w = config.env("ROBOUSE_ASPIRE_WORKFLOW", "iterative-debugging")
    if w not in WORKFLOWS:
        raise ValueError(f"ROBOUSE_ASPIRE_WORKFLOW is {w!r}; one of {', '.join(WORKFLOWS)}")
    return w


# ---- the coordinator's prompt ---------------------------------------------------------------------------------------
# prompts/<workflow>.md: ASPIRE's Quick Start prompt for one task, as a coordinator with no human to answer; filled with
# the campaign's names, seeds and the path of the program Stage 2 runs
PROMPTS_DIR = HERE / "prompts"


# ---- workspace ------------------------------------------------------------------------------------------------------
def _fill(text: str, values: dict) -> str:
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def _task_api(task: Any) -> tuple[list[str], str]:
    """The task's API functions (from its metadata) and the API documentation section of its text."""
    meta = task.metadata or {}
    names: list[str] = []
    for v in meta.values():
        if isinstance(v, dict) and isinstance(v.get("api"), list):
            names = [str(n) for n in v["api"]]
    m = re.search(r"^## API.*?(?=^## |\Z)", task.body, flags=re.M | re.S)
    return names, (m.group(0).strip() if m else "")


def _shim(src: Path, python: str) -> str:
    """A standalone script for the workspace, run by `python` (the runner's interpreter: readable in the sandbox,
    with numpy, without access to the robouse package)."""
    return f"#!{python}\n" + src.read_text()


def prepare_workspace(ws: Path, values: dict, task: Any, library: Library, profile: Profile) -> dict:
    """Lay out ASPIRE's repository as the agent expects it, with Robo Use's mapping. Returns the library's starting
    hashes."""
    up = UPSTREAM
    skills_root = ws / ".claude" / "skills"
    shutil.copytree(up / "claude" / "skills", skills_root, ignore=shutil.ignore_patterns("skills"), dirs_exist_ok=True)
    shutil.copytree(up / "claude" / "skills" / "evosearch" / "skills", skills_root / "evosearch" / "skills")
    shutil.copytree(up / "codex" / "skills", ws / ".codex" / "skills")
    for name in ("LICENSE", "NOTICE"):
        shutil.copyfile(up / name, ws / name)
    start = library.copy_skills_to(skills_root / "iterative-debugging" / "skills")
    docs = ws / "docs"
    docs.mkdir()
    (docs / "robouse.md").write_text(_fill((WORKSPACE_FILES / "robouse.md").read_text(), values))
    shutil.copyfile(WORKSPACE_FILES / "run-artifacts.md", docs / "run-artifacts.md")
    shutil.copyfile(WORKSPACE_FILES / "scene_snapshot.py", docs / "scene_snapshot.py")
    (docs / "task.md").write_text(f"# {task.id}\n\n{task.instruction.strip()}\n")
    names, api_doc = _task_api(task)
    rows = "\n".join(f"| `{n}(...)` | the task's `{n}` (documented below) |" for n in names)
    functions = (
        "| Function | |\n|---|---|\n" + rows if rows else "The functions are the `skills` that `robo.info()` lists."
    )
    api = {"functions": functions, "max_steps": values["max_steps"], "api_doc": api_doc or "As the task text says."}
    (docs / "api-reference.md").write_text(_fill((WORKSPACE_FILES / "api-reference.md").read_text(), api))
    for name in ("libero-pro.md", "robosuite.md"):  # ASPIRE's benchmark pages, which the profile replaces
        (docs / name).write_text(_fill((WORKSPACE_FILES / "pointer.md").read_text(), {"name": name}))
    py = sys.executable
    bin_dir = ws / ".robouse" / "bin"
    (bin_dir / "aspire_programs.py").write_text((WORKSPACE_FILES / "programs.py").read_text())
    (bin_dir / "cap-harness").write_text(_shim(WORKSPACE_FILES / "cap_harness.py", py))
    (bin_dir / "cap-harness").chmod(0o755)
    own = ws / ".robouse" / "aspire"
    own.mkdir(parents=True, exist_ok=True)
    (own / "driver.py").write_text(_shim(WORKSPACE_FILES / "driver.py", py))
    # ASPIRE's lint imports cap_harness.runtime._ProgramValidator from <repo>/src: Robo Use's contract, by that name
    compat = ws / "src" / "cap_harness"
    compat.mkdir(parents=True)
    (compat / "__init__.py").write_text('"""Robo Use\'s stand-in for cap_harness: the program contract only."""\n')
    (compat / "runtime.py").write_text(
        '"""The aspire program contract (.robouse/bin/aspire_programs.py) under cap-harness\'s name, for ASPIRE\'s\n'
        'lint_skills.py."""\n\nimport sys\nfrom pathlib import Path\n\n'
        'sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".robouse" / "bin"))\n'
        "from aspire_programs import ProgramValidator as _ProgramValidator  # noqa: E402\n\n"
        '__all__ = ["_ProgramValidator"]\n'
    )
    return start


def init_campaign(
    ws: Path, family: tuple[str, str, int], task: Any, dev: list[int], unseen: list[int]
) -> tuple[Path, int]:
    """Initialize the campaign root with ASPIRE's own init_run.py, as a coordinator does at kickoff."""
    b, s, i = family
    tasks = ws / ".robouse" / "aspire" / "tasks.json"
    tasks.write_text(json.dumps([{"benchmark": b, "suite": s, "task_id": i, "task_name": task.id}], indent=2))
    heldout = min([*dev, *unseen]) - 1
    script = ws / ".claude" / "skills" / "iterative-debugging" / "scripts" / "init_run.py"
    cmd = [
        sys.executable,
        "-I",
        str(script),
        "--tasks",
        str(tasks),
        "--name",
        "robouse",
        "--heldout-count",
        str(heldout),
    ]
    cmd += ["--dev-seeds", *map(str, dev), "--unseen-seeds", *map(str, unseen)]
    r = subprocess.run(cmd, cwd=ws, capture_output=True, text=True, check=False)
    m = re.search(r"^RUN_ROOT=(.+)$", r.stdout, flags=re.M)
    if r.returncode != 0 or not m:
        raise RuntimeError(f"ASPIRE's init_run.py failed: {(r.stderr or r.stdout).strip()[-500:]}")
    return Path(m.group(1)), heldout


# ---- the harness ----------------------------------------------------------------------------------------------------
def build(harness: str, model: str, prompt: str, workspace: Path, task: Any, env: dict) -> Any:
    from .. import Launch

    agent = AGENTS[harness]
    facts = json.loads(env.get("_ROBOUSE_TRIAL") or "{}")  # read before the agent's builder removes private variables
    tdir = Path(env["_ROBOUSE_TRIAL_DIR"])
    profile = profile_for(task)
    family = profile.family(task)
    wf = workflow()
    scored_seed = int(facts["seed"]) if facts.get("seed") is not None else int(task.spec.get("seed", 0))
    scored_scene = profile.scene(scored_seed)
    lib = Library(Path(config.env("ROBOUSE_ASPIRE_LIBRARY")) if config.env("ROBOUSE_ASPIRE_LIBRARY") else None)
    lib.prepare()
    if scene_id(family, scored_scene) in lib.practised():
        raise ValueError(
            f"the skill library at {lib.path} has practised on the scene this trial is scored on ({'/'.join(map(str, family))}, "
            f"seed {scored_seed}): its score would not be a held-out result. Use another library, or practice bands "
            "that avoid the scored seeds"
        )
    dev, unseen, dropped = bands(profile, {scored_scene})
    max_episodes = int(config.env("ROBOUSE_ASPIRE_PRACTICE_EPISODES") or (650 if wf == "evosearch" else 300))
    workers = int(config.env("ROBOUSE_ASPIRE_PRACTICE_WORKERS") or 4)
    timeout_s = float(facts.get("timeout_s") or MIN_TIMEOUT_S)
    reserve = min(1800.0, max(300.0, 0.15 * timeout_s))
    b, s, i = family
    selected_name = "fix_code.py" if wf == "iterative-debugging" else "evosearch_best_code.py"
    reuse, reuse_from, reuse_refused = library_program(lib, family, selected_name, harness, model)
    ws = Path(workspace).resolve()  # ASPIRE's scripts resolve their paths (macOS's /var is /private/var)
    # the workspace folder, opened now, before the agent exists: what the trial copies out of it at the freeze is read
    # through this handle without following links (the agent owns everything inside)
    reader = WorkspaceReader(ws)
    fix_loop, _, _ = library_program(lib, family, "fix_code.py", harness, model)
    if wf == "evosearch" and fix_loop is not None:
        # the fix loop's results for this task (the same harness and model's), where ASPIRE's evosearch looks for its
        # baseline (candidate_A)
        lib.copy_task_results_to(family, ws / "outputs" / "runs" / "0000-library" / b / s / f"task_{i}")
    own_dir = ws / ".robouse" / "aspire"
    values: dict[str, Any] = {
        "aspire_repo": ASPIRE_REPO,
        "aspire_commit": ASPIRE_COMMIT[:12],
        "benchmark": b,
        "suite": s,
        "task_id": i,
        "task": task.id,
        "dev": fmt(dev),
        "unseen": fmt(unseen) if unseen else "none",
        "max_steps": int(task.spec.get("max_steps") or 0),
        "seed_rule": profile.rule,
        "perception": profile.perception,
        "max_episodes": max_episodes,
        "workers": workers,
        "success_rule": _success_rule(task),
        "library_sentence": (
            f"It persists across this suite's trials (ROBOUSE_ASPIRE_LIBRARY): what you promote here reaches later "
            f"tasks, and it already holds what earlier trials promoted (library hash {skill_library_sha(lib.skills)})."
            if lib.persistent
            else "This trial has its own copy of ASPIRE's library: what you promote is recorded with the trial."
        ),
    }
    own_dir.mkdir(parents=True, exist_ok=True)
    run_root, heldout = (Path(), 0)
    start = {}
    if reuse is None:
        start = prepare_workspace(ws, {**values, "run_root": "{{run_root}}"}, task, lib, profile)
        run_root, heldout = init_campaign(ws, family, task, dev, unseen)
    else:
        own_dir.mkdir(parents=True, exist_ok=True)
        (own_dir / "driver.py").write_text(_shim(WORKSPACE_FILES / "driver.py", sys.executable))
        (ws / ".robouse" / "bin" / "aspire_programs.py").write_text((WORKSPACE_FILES / "programs.py").read_text())
    task_dir = run_root / b / s / f"task_{i}"
    evo_task_dir = ws / "outputs" / "evosearch" / b / s / f"task_{i}"
    # where the coordinator leaves the selected program; a Stage 2 only trial takes the library's
    program = (
        reuse if reuse is not None else (task_dir if wf == "iterative-debugging" else evo_task_dir) / selected_name
    )
    program_hint = str(program) if reuse is not None else str(program.relative_to(ws))
    values.update(run_root=run_root, task_dir=task_dir, heldout_count=heldout, program=program)
    if reuse is None:
        doc = ws / "docs" / "robouse.md"
        doc.write_text(_fill(doc.read_text(), values))
    lib_after = tdir / "aspire" / "library-after"

    def snapshot() -> dict:
        """At freeze, outside the sandbox: the library, the campaign's text record and the selected program."""
        out: dict[str, Any] = {}
        rec = tdir / "aspire"
        if reuse is not None:
            kept = reuse.read_text()
            (rec / "program.py").parent.mkdir(parents=True, exist_ok=True)
            (rec / "program.py").write_text(kept)
            return {"program": kept, "program_path": str(reuse), "reused": True}
        reader.copy(ws / ".claude" / "skills" / "iterative-debugging" / "skills", lib_after, (".md",))
        out["library_sha"] = skill_library_sha(lib_after)
        reader.copy(ws / "outputs", rec / "outputs", (".md", ".json", ".py", ".txt", ".jsonl"))
        found = reader.read_text(program)
        if found is None and wf == "iterative-debugging":  # a coordinator that re-initialized the campaign root
            latest = reader.readlink(ws / "outputs" / "runs" / "LATEST")  # by name: the link is not followed
            if latest:
                found = reader.read_text(
                    ws / "outputs" / "runs" / Path(latest).name / b / s / f"task_{i}" / selected_name
                )
        if found is not None:
            (rec / "program.py").write_text(found)
        out.update(program=found, program_path=program_hint)
        return out

    broker = PracticeBroker(
        task.path,
        tdir / "aspire",
        dev,
        unseen if reuse is None else [],
        profile.scene,
        {scored_scene},
        max_episodes if reuse is None else 0,
        workers,
        float(task.agent_timeout_s),
        split=facts.get("split"),
        snapshot=snapshot,
    )
    url = broker.start()
    env["ROBOUSE_PRACTICE_URL"] = url  # also lets the macOS sandbox allow this local port
    key_file = own_dir / "driver.key"  # the freeze key: the driver reads and deletes it before the agent starts
    key_file.write_text(broker.freeze_key)
    key_file.chmod(0o600)
    inner = None
    agent_cmd = None
    text = ""
    if reuse is None:
        text = _fill(
            (PROMPTS_DIR / f"{wf}.md").read_text(),
            dict(
                repo=ASPIRE_REPO,
                commit=ASPIRE_COMMIT[:12],
                skill_file=(".claude" if agent == "claude-code" else ".codex") + f"/skills/{wf}/SKILL.md",
                benchmark=b,
                suite=s,
                task_id=i,
                task=task.id,
                run_root=run_root,
                dev=fmt(dev),
                unseen=fmt(unseen) if unseen else "none",
                heldout=heldout,
                max_steps=values["max_steps"],
                workers=workers,
                max_episodes=max_episodes,
                program=program_hint,
                evo_task_dir=evo_task_dir.relative_to(ws),
                baseline=_baseline(family, fix_loop is not None),
            ),
        )
        try:
            inner = agent_launch(agent, model, text, ws, task, env)
        except BaseException:
            broker.stop()
            raise
        agent_cmd = inner.cmd
    trial_json = {
        "benchmark": b,
        "suite": s,
        "task_id": i,
        "task": task.id,
        "max_steps": values["max_steps"],
        "camera": task.spec.get("camera") or (task.spec.get("cameras") or ["camera"])[0],
        "dev_seeds": dev,
        "unseen_seeds": unseen,
        "practice_url": url,
        "program_timeout_s": float(task.agent_timeout_s),
    }
    (own_dir / "trial.json").write_text(json.dumps(trial_json, indent=2))
    started = time.time()
    (own_dir / "driver.json").write_text(
        json.dumps(
            {
                "agent": agent,
                "agent_cmd": agent_cmd,
                "practice_deadline": started + max(60.0, timeout_s - reserve),
                "practice_url": url,
                "program_hint": program_hint,
            },
            indent=2,
        )
    )
    cfg = {
        "upstream": {"repo": ASPIRE_REPO, "commit": ASPIRE_COMMIT},
        "agent": agent,
        "workflow": wf,
        "family": {"benchmark": b, "suite": s, "task_id": i},
        "stage1": "reused" if reuse is not None else "run",
        "reused_program": reuse_from,
        "reuse_refused": reuse_refused,
        "scored_seed": scored_seed,
        "dev_seeds": dev,
        "unseen_seeds": unseen,
        "dropped_seeds": dropped,
        "max_episodes": max_episodes,
        "workers": workers,
        "practice_deadline_s": round(max(60.0, timeout_s - reserve)),
        "library": str(lib.path) if lib.persistent else None,
        "library_sha_before": skill_library_sha(lib.skills),
        "prompt": text if reuse is None else None,
    }
    state: dict[str, Any] = {}
    pending: dict[str, Any] = {}

    def stop() -> None:
        try:
            if inner is not None and inner.stop is not None:
                inner.stop()
        finally:
            broker.stop()
            try:
                out, pending_write = finish(
                    tdir,
                    ws,
                    reader,
                    cfg,
                    broker,
                    lib,
                    start,
                    family,
                    task,
                    harness,
                    model,
                    scored_seed,
                    lib_after,
                    reuse,
                )
                state.update(out)
                pending.update(pending_write)
            except Exception as e:  # noqa: BLE001 - the trial's result stands; the record says what failed
                state.update(cfg, record_error=f"{type(e).__name__}: {e}")
            finally:
                reader.close()

    def record(trial_ok: bool) -> dict:
        """After the runner judged the verdict: the library is written back only from a verified result."""
        if pending:
            try:
                state.setdefault("library", {}).update(write_library(lib, family, trial_ok, **pending))
            except Exception as e:  # noqa: BLE001 - the trial's result stands; the record says what failed
                state.setdefault("library", {})["error"] = f"{type(e).__name__}: {e}"
            pending.clear()
        return state

    notes = dict(inner.notes) if inner is not None else {"model": model or "none"}
    return Launch(
        # -I: the driver imports nothing from its own folder, the workspace or PYTHON* variables (the agent's)
        [sys.executable, "-I", str(own_dir / "driver.py")],
        env,
        helper=inner.helper if inner is not None else None,
        stop=stop,
        stop_file=inner.stop_file if inner is not None else None,
        notes=notes,
        deny=[lib.path] if lib.path is not None else [],
        config=cfg,
        record=record,
    )


def agent_launch(agent: str, model: str, prompt: str, workspace: Path, task: Any, env: dict) -> Any:
    """Claude Code or Codex, as the claude-code and codex harnesses start them (credentials, model gateway, a clean
    config home), with ASPIRE's prompt instead of Robo Use's and, for Claude Code, the tools ASPIRE's coordinator needs."""
    from .. import _claude_code, _codex

    if agent == "claude-code":
        launch = _claude_code(
            model, prompt, workspace, task, env, prefix="", tools=CLAUDE_TOOLS, max_turns=CLAUDE_MAX_TURNS
        )
        # a sweep of practice episodes on the CPU outlasts Claude Code's 10-minute ceiling for one shell command, which
        # ASPIRE's guides plan around on GPUs: allow two hours, and ten minutes when the model names no limit
        launch.env.update(BASH_DEFAULT_TIMEOUT_MS="600000", BASH_MAX_TIMEOUT_MS=str(BASH_MAX_TIMEOUT_MS))
        # ASPIRE's coordinator dispatches its worker and verifier as background subagents and ends its turn to wait
        # for them. In print mode Claude Code stops background work 10 minutes after the last turn unless this is 0;
        # the driver's practice deadline is the limit instead
        launch.env["CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"] = "0"
        return launch
    return _codex(model, prompt, workspace, task, env, prefix="")


def _success_rule(task: Any) -> str:
    m = re.search(r"\*\*Success:\*\*\s*(.+?)(?:\n\n|\Z)", task.body, flags=re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip().rstrip(".") if m else "the task's own success check"


def library_program(
    lib: Library, family: tuple[str, str, int], name: str, harness: str, model: str
) -> tuple[Path | None, dict | None, str | None]:
    """The library's program `name` for this task, when this trial may use it: (its path, which trial, harness and
    model selected it, why not). ROBOUSE_ASPIRE_REUSE: 1 (default) uses a program the same harness and model selected,
    any also one another harness or model selected, 0 none."""
    mode = (config.env("ROBOUSE_ASPIRE_REUSE") or "1").strip().lower()
    if mode in ("0", "false", "no", "off"):
        return None, None, None
    held = lib.selected_program(family, name)
    if held is None:
        return None, None, None
    source = lib.program_source(family, name) or {}
    if mode == "any" or (source.get("harness") == harness and source.get("model") == model):
        return held, {**source, "path": str(held)}, None
    why = (
        f"the library's {name} for this task was selected by {source.get('harness') or 'an unrecorded harness'} with "
        f"{source.get('model') or 'an unrecorded model'}, not {harness} with {model or 'its default model'}: Stage 1 "
        "runs (ROBOUSE_ASPIRE_REUSE=any uses it anyway)"
    )
    return None, None, why


def _baseline(family: tuple[str, str, int], available: bool) -> str:
    if available:
        b, s, i = family
        return (
            f"the fix loop's fix_code.py for this task is in outputs/runs/0000-library/{b}/{s}/task_{i}/ (its held-out "
            "rate is not known here); seed it as candidate_A"
        )
    return "none: no fix loop has run for this task; candidate_A is your own first program"


def finish(
    tdir: Path,
    ws: Path,
    reader: WorkspaceReader,
    cfg: dict,
    broker: PracticeBroker,
    lib: Library,
    start: dict,
    family: tuple[str, str, int],
    task: Any,
    harness: str,
    model: str,
    scored_seed: int,
    lib_after: Path,
    reuse: Path | None,
) -> tuple[dict, dict]:
    """After the trial, outside the sandbox: the practice record, Stage 2's report and whether anything reached the
    scored episode before Stage 2; and what write_library needs once the runner has judged the verdict."""
    rec = tdir / "aspire"
    rec.mkdir(parents=True, exist_ok=True)
    practice = broker.record()
    frozen = broker.frozen or {}
    stage2_text = reader.read_text(ws / ".robouse" / "aspire" / "stage2.json")
    try:
        driver = json.loads(stage2_text) if stage2_text else {}
    except ValueError:
        driver = {}
    try:  # the episode server's own count, in its signed verdict: requests it refused while locked
        lock = json.loads((tdir / "episode" / "result.json").read_text()).get("lock") or {}
    except (OSError, ValueError):
        lock = {}
    before = lock.get("refused") if lock else _requests_before_stage2(tdir / "episode" / "trace.jsonl")
    out: dict[str, Any] = {
        **{k: cfg[k] for k in ("upstream", "agent", "workflow", "family", "stage1")},
        "practice": {k: v for k, v in practice.items() if k != "runs"},
        "program": {
            "path": frozen.get("program_path"),
            "selected": bool(frozen.get("program")),
            "reused_from": cfg.get("reused_program"),
            "reuse_refused": cfg.get("reuse_refused"),
            "sha256": (driver.get("stage2") or {}).get("program_sha256"),
        },
        "stage2": driver.get("stage2") or {"ran": False, "error": "the driver left no report"},
        "agent_exit": driver.get("agent_exit"),
        "agent_stopped_at_deadline": driver.get("agent_stopped_at_deadline"),
        "scored_requests_before_stage2": before,
        "scored_episode_lock": lock or None,
    }
    (rec / "practice.json").write_text(json.dumps(practice, indent=2))
    library: dict[str, Any] = {
        "path": str(lib.path) if lib.persistent else None,
        "persistent": lib.persistent,
        "sha_before": cfg["library_sha_before"],
        "sha_after": frozen.get("library_sha", cfg["library_sha_before"]),
    }
    pending: dict[str, Any] = {}
    if lib.persistent and reuse is None and lib_after.is_dir():
        entry = {
            "trial": tdir.name,
            "task": task.id,
            "backend": task.spec.get("backend"),
            "env": task.spec.get("env"),
            "family": list(family),
            "harness": harness,
            "model": model,
            "workflow": cfg["workflow"],
            "scored_seed": scored_seed,
            "library_sha_before": cfg["library_sha_before"],
            "practice": {
                "seeds": practice["seeds_run"],
                "scene_ids": [scene_id(family, json.loads(sc)) for sc in practice["scenes_run"]],
                "episodes": practice["episodes"],
            },
            "program_selected": out["program"]["selected"],
        }
        results = None
        if (rec / "outputs").is_dir():
            b, s, i = family
            sub = ("evosearch", b, s, f"task_{i}") if cfg["workflow"] == "evosearch" else None
            cand = (
                [rec / "outputs" / Path(*sub)]
                if sub
                else sorted((rec / "outputs" / "runs").glob(f"*/{b}/{s}/task_{i}"))
            )
            results = next((c for c in reversed(cand) if c.is_dir() and "0000-library" not in str(c)), None)
        verified, why = aspire_verified(rec, family)
        pending = {
            "entry": entry,
            "start": start,
            "after": lib_after,
            "results": results,
            "skills_withheld": None if verified else why,
            "record": rec / "record.json",
        }
        library["pending"] = "written back once the runner has judged the trial's verdict"
    elif lib.persistent and reuse is not None:
        library["note"] = "Stage 2 only: the library was read, not changed"
    out["library"] = library
    if lib_after.is_dir():
        library["files_after"] = len(file_hashes(lib_after))
    (rec / "record.json").write_text(json.dumps(out, indent=2))
    return out, pending


def aspire_verified(rec: Path, family: tuple[str, str, int]) -> tuple[bool, str]:
    """Whether the trial's own ASPIRE verifier reported "verified" for this task (verification_report.json in the
    campaign's record), as ASPIRE promotes only verified library entries: (yes, the report) or (no, why)."""
    b, s, i = family
    reports = sorted((rec / "outputs" / "runs").glob(f"*/verification/{b}__{s}__task_{i}/verification_report.json"))
    for r in reversed(reports):
        try:
            verdict = json.loads(r.read_text()).get("verdict")
        except (OSError, ValueError, AttributeError):
            continue
        if verdict == "verified":
            return True, str(r.relative_to(rec))
    return (
        False,
        "the trial's ASPIRE verifier did not report verified for this task (no verification_report.json says so)",
    )


def write_library(
    lib: Library,
    family: tuple[str, str, int],
    trial_ok: bool,
    entry: dict,
    start: dict,
    after: Path,
    results: Path | None,
    skills_withheld: str | None,
    record: Path,
) -> dict:
    """The persistent library's write-back, after the runner judged the verdict: nothing from a trial that is not a
    verified result (signed, no integrity failure); the skill files only when ASPIRE's verifier verified the task."""
    if not trial_ok:
        out: dict[str, Any] = {
            "pending": None,
            "written": False,
            "why": "the trial's verdict is not a verified result (unsigned, or an integrity failure): nothing written",
        }
    else:
        out = {
            "pending": None,
            "written": True,
            **lib.write_back(entry, start, after, results, family, skills_withheld),
        }
    try:  # the trial folder's record.json, as result.json's harness_record
        rec = json.loads(record.read_text())
        rec.setdefault("library", {}).update(out)
        record.write_text(json.dumps(rec, indent=2))
    except (OSError, ValueError):
        pass
    return out


def _requests_before_stage2(trace: Path) -> int | None:
    """Requests the scored episode got before Stage 2's marked first request, from its trace: the fallback when the
    episode ran unlocked. The runner judges a locked episode by the server's own count of refused requests."""
    try:
        lines = trace.read_text().splitlines()
    except OSError:
        return None
    n = 0
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        req = e.get("req") or {}
        if req.get("aspire") == "stage2":
            return n
        if not req.get("runner") and not str(req.get("text", "")).startswith("[runner]"):
            n += 1
    return None


def default_timeout(harness: str) -> float:
    """The agent time an aspire trial gets when --timeout is not given (at least MIN_TIMEOUT_S)."""
    return MIN_TIMEOUT_S if harness in AGENTS else 0.0


def harness_names() -> tuple[str, ...]:
    return tuple(AGENTS)


__all__ = ["AGENTS", "PROFILES", "Profile", "build", "default_timeout", "profile_for"]
