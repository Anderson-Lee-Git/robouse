"""The `gemini-cli` harness: Google's Gemini CLI (npm `@google/gemini-cli`, Apache-2.0), headless through
`gemini --prompt PROMPT --output-format stream-json`, with every tool call approved (`--approval-mode yolo`).

Model: a Gemini API model on its own vendor, a bare id (default gemini-4-argon) or `gemini/<id>`, reached directly with
the key in GEMINI_API_KEY (a Gemini API key from Google AI Studio): no model gateway and no spend cap, as for Claude
Code and Codex on their own vendors. Gemini CLI speaks only the Gemini API's generateContent protocol, and Robo Use does
not route it through the model gateway, so a model of another provider is refused before the trial starts
(`refusal`).

Isolation: everything Gemini CLI reads or writes is per trial, inside the workspace's `.robouse/gemini-home/`
(GEMINI_CLI_HOME and HOME: its .gemini folder with settings, sessions, shell history, memory, extensions, skills and
logins), so the user's ~/.gemini (which the sandbox denies anyway), ~/.env and extensions never load, and nothing one
trial writes reaches another. The machine's system settings and system defaults are not read either: their paths
(GEMINI_CLI_SYSTEM_SETTINGS_PATH, GEMINI_CLI_SYSTEM_DEFAULTS_PATH) point at files that do not exist. (They cannot hold
the trial's settings: Gemini CLI loads a system settings file only from a folder root owns.) The trial's user
settings (`SETTINGS`):
  - the built-in tools are limited to the shell, file and search tools (`TOOLS`): no web search or fetch, no
    subagents, skills, memory, planning, topic or question tools (and the system prompt's topic updates are off, since
    their tool is not offered);
  - no MCP servers, extensions, hooks, checkpointing, telemetry, usage statistics or update checks;
  - no loop detection: it stops the session when the same tool call repeats five times in a row, and a robot is often
    driven by repeating one command (each one moves it further);
  - API key authentication, and a shell-tool environment without variables whose names mark a credential
    (security.environmentVariableRedaction), so the agent's commands do not see GEMINI_API_KEY;
  - no .env file is loaded from the workspace or the folders above it (advanced.ignoreLocalEnv).
The workspace is trusted for the session (GEMINI_CLI_TRUST_WORKSPACE), which headless runs need. Gemini CLI runs as one
process (GEMINI_CLI_NO_RELAUNCH: it would otherwise restart itself to raise Node's memory limit). GOOGLE_GEMINI_BASE_URL,
Gemini CLI's own setting for another endpoint (a proxy, or tests/model_standin.py), is passed on when it is set.

The trajectory is Gemini CLI's stream-json output (agent/stdout.jsonl), converted by runner/atif.py.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

# the built-in tools Gemini CLI offers its model (tools.core), the counterparts of Claude Code's CLAUDE_TOOLS
TOOLS = ["run_shell_command", "read_file", "write_file", "replace", "glob", "grep_search", "list_directory"]
SETTINGS = {
    "security": {
        "auth": {"selectedType": "gemini-api-key"},
        "environmentVariableRedaction": {"enabled": True},
    },
    "tools": {"core": TOOLS, "sandbox": False},
    "mcpServers": {},
    "experimental": {"enableAgents": False},
    "skills": {"enabled": False},
    "hooksConfig": {"enabled": False},
    "model": {"disableLoopDetection": True},
    "general": {
        "enableAutoUpdate": False,
        "enableAutoUpdateNotification": False,
        "checkpointing": {"enabled": False},
        "topicUpdateNarration": False,
    },
    "privacy": {"usageStatisticsEnabled": False},
    "telemetry": {"enabled": False},
    "advanced": {"ignoreLocalEnv": True},
}


def refusal(ref) -> str | None:
    """Why gemini-cli cannot run this model (one of another provider), or None."""
    if ref.provider == "gemini":
        return None
    return (
        f"gemini-cli runs only Gemini API models (a bare id such as gemini-4-argon, or gemini/<id>): it speaks the "
        f"Gemini API's own protocol, and Robo Use does not route it through the model gateway. Run {ref.id} on "
        "claude-code, mini-swe-agent or dimcode"
    )


def build(model, prompt, workspace: Path, task, env: dict):
    from . import PROMPT_PREFIX, Launch, credentials, models

    ref = models.resolve("gemini-cli", model or models.DEFAULT_MODELS["gemini-cli"])
    if why := refusal(ref):
        raise ValueError(why)
    exe = shutil.which("gemini")
    if not exe:
        raise RuntimeError("gemini-cli is not installed: no `gemini` on PATH (npm install -g @google/gemini-cli)")
    env.update(credentials.gemini_auth())
    home = credentials.clean_gemini_home(workspace)
    (home / ".gemini" / "settings.json").write_text(json.dumps(SETTINGS, indent=2))
    env.update(
        {
            "GEMINI_CLI_HOME": str(home),
            "HOME": str(home),
            "GEMINI_CLI_SYSTEM_SETTINGS_PATH": str(home / "no-system-settings.json"),
            "GEMINI_CLI_SYSTEM_DEFAULTS_PATH": str(home / "no-system-defaults.json"),
            "GEMINI_CLI_TRUST_WORKSPACE": "true",
            "GEMINI_CLI_NO_RELAUNCH": "true",
        }
    )
    if base := os.environ.get("GOOGLE_GEMINI_BASE_URL"):
        env["GOOGLE_GEMINI_BASE_URL"] = base
    cmd = [
        exe,
        "--prompt",
        PROMPT_PREFIX + prompt,
        "--model",
        ref.bare,
        "--output-format",
        "stream-json",
        "--approval-mode",
        "yolo",
    ]
    return Launch(cmd, env, notes={"model": ref.bare})
