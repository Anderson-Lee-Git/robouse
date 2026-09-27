"""Harness launchers. Each returns the command, environment and any helper process for one trial.

The agent process gets: cwd = an isolated workspace (instruction.md, observations/), PATH with a
standard-library `robo` shim first, and ROBOUSE_SOCKET. Credentials are read from the owner's env files
into this process only and passed to the harness child (never printed or written to the trial dir).

Harnesses
  oracle                 the task's reference solution (solution/solve.sh)
  noop                   calls `robo done` immediately (negative control)
  claude-code            Claude Code CLI; model e.g. claude-opus-5-5 (OAuth token pool)
  codex                  Codex CLI; model e.g. gpt-6-astra (the owner's Codex login)
  claude-code-glm        Claude Code CLI against GLM-5.3 on Baseten via a local image-capping proxy
  codex-glm              Codex CLI with a custom OpenAI-compatible provider (Baseten GLM-5.3)
  mini-swe-agent-glm     mini-swe-agent (litellm) with GLM-5.3 on Baseten
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

HOME = Path.home()
OAUTH_ENV = HOME / ".config/bf-agents/oauth.env"
BASETEN_ENV = HOME / ".config/bf-agents/baseten.env"
GLM_MODEL = "zai-org/GLM-5.3"
BASETEN_OPENAI = "https://inference.baseten.co/v1"

PROMPT_PREFIX = (
    "You are controlling a simulated robot. Read the task below, then solve it by running the `robo` command "
    "in your shell (start with `robo info` and `robo observe`). Keep going until the task is done, then call "
    "`robo done` once. Do not stop to ask questions; there is no human to answer.\n\n"
)


@dataclass
class Launch:
    cmd: list[str]
    env: dict[str, str]
    helper: object | None = None  # e.g. a proxy server to stop afterwards
    notes: dict = field(default_factory=dict)


def _read_env(path: Path) -> dict[str, str]:
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip().removeprefix("export ").strip()] = v.strip().strip('"').strip("'")
    return out


_token_rr = {"i": 0}
CACHE = HOME / ".cache" / "robouse"


def _clean_claude_home() -> str:
    """Empty Claude Code config dir: no user settings, CLAUDE.md, MCP servers or plugins leak into trials."""
    d = CACHE / "claude-home"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def _clean_codex_home(extra_config: str = "") -> str:
    """Codex home with only the owner's login (auth.json) and a minimal config: no personal MCP servers or skills."""
    d = CACHE / ("codex-home-glm" if extra_config else "codex-home")
    d.mkdir(parents=True, exist_ok=True)
    auth = HOME / ".codex" / "auth.json"
    link = d / "auth.json"
    if auth.exists() and not link.exists():
        link.symlink_to(auth)
    (d / "config.toml").write_text('model_reasoning_effort = "medium"\n' + extra_config)
    return str(d)


def _claude_oauth() -> str:
    env = _read_env(OAUTH_ENV)
    toks = [v for k, v in sorted(env.items()) if k.startswith("BF_REVIEW_TOKEN") and v]
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        toks.insert(0, os.environ["CLAUDE_CODE_OAUTH_TOKEN"])
    if not toks:
        raise RuntimeError("no Claude OAuth token found")
    t = toks[_token_rr["i"] % len(toks)]
    _token_rr["i"] += 1
    return t


def _baseten_key() -> str:
    k = _read_env(BASETEN_ENV).get("BASETEN_API_KEY") or os.environ.get("BASETEN_API_KEY")
    if not k:
        raise RuntimeError("no BASETEN_API_KEY")
    return k


def build(harness: str, model: str, prompt: str, workspace: Path, task_dir: Path, base_env: dict) -> Launch:
    env = dict(base_env)
    if harness == "oracle":
        return Launch(["bash", str(task_dir / "solution" / "solve.sh")], env, notes={"model": "scripted"})
    if harness == "noop":
        return Launch(["robo", "done", "noop control"], env, notes={"model": "none"})

    if harness == "claude-code":
        env["CLAUDE_CODE_OAUTH_TOKEN"] = _claude_oauth()
        env["CLAUDE_CONFIG_DIR"] = _clean_claude_home()
        m = model or "claude-opus-5-5"
        return Launch(["claude", "-p", PROMPT_PREFIX + prompt, "--model", m, "--output-format", "stream-json", "--verbose",
                       "--dangerously-skip-permissions", "--max-turns", "400", "--disallowedTools", "WebFetch,WebSearch,Task"],
                      env, notes={"model": m})

    if harness == "claude-code-glm":
        from .providers import baseten_proxy

        port, stats = baseten_proxy.start(_baseten_key())
        env.update({"ANTHROPIC_BASE_URL": f"http://127.0.0.1:{port}", "ANTHROPIC_AUTH_TOKEN": "proxy-held",
                    "ANTHROPIC_API_KEY": "", "ANTHROPIC_MODEL": GLM_MODEL, "ANTHROPIC_DEFAULT_OPUS_MODEL": GLM_MODEL,
                    "ANTHROPIC_DEFAULT_SONNET_MODEL": GLM_MODEL, "ANTHROPIC_DEFAULT_HAIKU_MODEL": GLM_MODEL,
                    "ANTHROPIC_SMALL_FAST_MODEL": GLM_MODEL, "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
        env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
        env["CLAUDE_CONFIG_DIR"] = _clean_claude_home()
        return Launch(["claude", "-p", PROMPT_PREFIX + prompt, "--model", GLM_MODEL, "--output-format", "stream-json",
                       "--verbose", "--dangerously-skip-permissions", "--max-turns", "400",
                       "--disallowedTools", "WebFetch,WebSearch,Task"], env, helper=stats, notes={"model": GLM_MODEL, "provider": "baseten"})

    if harness == "codex":
        m = model or "gpt-6-astra"
        env["CODEX_HOME"] = _clean_codex_home()
        return Launch(["codex", "exec", "--json", "--skip-git-repo-check", "--dangerously-bypass-approvals-and-sandbox",
                       "-m", m, "-C", str(workspace), PROMPT_PREFIX + prompt], env, notes={"model": m})

    if harness == "codex-glm":
        env["BASETEN_API_KEY"] = _baseten_key()
        env["CODEX_HOME"] = _clean_codex_home("# GLM via Baseten; provider set on the command line\n")
        cfg = ['-c', 'model_providers.baseten.name="Baseten"', '-c', f'model_providers.baseten.base_url="{BASETEN_OPENAI}"',
               '-c', 'model_providers.baseten.env_key="BASETEN_API_KEY"', '-c', 'model_providers.baseten.wire_api="chat"',
               '-c', 'model_provider="baseten"']
        return Launch(["codex", "exec", "--json", "--skip-git-repo-check", "--dangerously-bypass-approvals-and-sandbox",
                       *cfg, "-m", GLM_MODEL, "-C", str(workspace), PROMPT_PREFIX + prompt], env,
                      notes={"model": GLM_MODEL, "provider": "baseten"})

    if harness == "mini-swe-agent-glm":
        env.update({"OPENAI_API_KEY": _baseten_key(), "OPENAI_API_BASE": BASETEN_OPENAI, "MSWEA_CONFIGURED": "true",
                    "MSWEA_COST_TRACKING": "ignore_errors"})
        exe = shutil.which("mini") or str(HOME / ".local/bin/mini")
        (workspace / ".robouse" / "task.txt").write_text(PROMPT_PREFIX + prompt)
        return Launch([exe, "-y", "--exit-immediately", "-l", "0", "-m", f"openai/{GLM_MODEL}", "-t", PROMPT_PREFIX + prompt, "-o",
                       str(workspace / ".robouse" / "mini_traj.json")], env, notes={"model": GLM_MODEL, "provider": "baseten"})

    raise KeyError(f"unknown harness {harness!r}")
