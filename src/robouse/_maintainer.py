"""Maintainer-only fallbacks, isolated here. None of them is needed to use robouse; each applies only when its folder
exists on the machine.

- Credential pools under ~/.config/bf-agents: `oauth.env` (Claude Code OAuth tokens, rotated) and `codex-auth/*.json`
  (a pool of Codex accounts). No model provider's key is read from a file: the model gateway takes it from the
  environment only.
- Remote worker endpoint files inside a development checkout: <repo>/runs/_<name>/remote.json.
- Folders agents must never read in the local runner's sandbox: the maintainers' workspace (~/benchflow), the
  credential pools, and the maintainers' provider key files (~/.config/benchflow, e.g. the Z.ai Coding Plan's key,
  which the runner keeps out of agent environments as well).
"""

from __future__ import annotations

from pathlib import Path

AGENTS_DIR = Path.home() / ".config" / "bf-agents"
OAUTH_ENV = AGENTS_DIR / "oauth.env"
CODEX_POOL = AGENTS_DIR / "codex-auth"
WORKSPACE = Path.home() / "benchflow"
PROVIDER_KEYS = Path.home() / ".config" / "benchflow"  # env files the maintainers source before a run
CHECKOUT = Path(__file__).resolve().parents[2]


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines of a shell-style env file (comments, `export` and quotes allowed); {} when it is missing."""
    out: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip().removeprefix("export ").strip()] = v.strip().strip('"').strip("'")
    return out


def claude_tokens() -> list[str]:
    """Claude Code OAuth tokens from the pool (BF_REVIEW_TOKEN_* entries), in a stable order."""
    return [v for k, v in sorted(read_env_file(OAUTH_ENV).items()) if k.startswith("BF_REVIEW_TOKEN") and v]


def codex_accounts() -> list[Path]:
    return sorted(CODEX_POOL.glob("*.json")) if CODEX_POOL.is_dir() else []


def remote_endpoint_files(name: str) -> list[Path]:
    return [CHECKOUT / "runs" / f"_{name}" / "remote.json"]


def private_dirs() -> list[Path]:
    return [WORKSPACE, AGENTS_DIR, PROVIDER_KEYS]
