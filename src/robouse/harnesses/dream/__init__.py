"""`dream` harness: Dream Labs' Dream-1 world-action models through DreamAPI, driving the robot as its policy.

`client.py` (copied into the trial workspace) runs Dream's own simulation loop over the `robo` socket with Dream's client
library, in a Python that has it (ROBOUSE_DREAM_PYTHON, default <cache>/dream-venv/bin/python; `pip install
dreamlabs-client`). Dream-1's public models drive Dream's bimanual YAM, so the harness runs the `yam` suite; on any other
robot it gives up at 0 steps and says why.

Credentials: DREAM_API_KEY, else the key in Dream's credentials file (~/.dreamlabs/credentials, or $DREAM_CREDENTIALS),
read as Dream's client reads it, with the service URLs (DREAM_GATEWAY_URL, DREAM_API_URL, DREAM_DATA_URL) from the same
places. They go to the client's environment only; the client never reads the file itself (the sandbox denies it to
every agent).
"""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from typing import Any

from ... import config

CLIENT = Path(__file__).with_name("client.py")
DEFAULT_MODEL = "dreamlabs/dream-1-beta"
# public on 2026-10-19 (get_models()); any checkpoint the account may run is accepted, e.g. a fine-tune dream-1-ft:...
MODELS = ("dreamlabs/dream-1-beta", "dreamlabs/dream-1-beta-flash")
NAMES = ("DREAM_GATEWAY_URL", "DREAM_API_URL", "DREAM_DATA_URL", "DREAM_API_KEY")


def credentials() -> dict[str, str]:
    """DREAM_API_KEY and whichever service URLs are set: the environment first, then Dream's credentials file (shell
    `NAME=value` lines; a later line wins). Raises RuntimeError when there is no key."""
    path = Path(os.environ.get("DREAM_CREDENTIALS") or "~/.dreamlabs/credentials").expanduser()
    found: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            name, sep, value = line.strip().removeprefix("export ").partition("=")
            if sep and name.strip() in NAMES:
                parts = shlex.split(value, comments=True)
                found[name.strip()] = parts[0] if parts else ""
    found.update({k: os.environ[k] for k in NAMES if os.environ.get(k)})
    if not found.get("DREAM_API_KEY"):
        raise RuntimeError(
            "no Dream Labs key: set DREAM_API_KEY, or write ~/.dreamlabs/credentials as the Dream Labs platform's "
            "Setup API page prints it"
        )
    return {k: v for k, v in found.items() if v}


def client_python() -> str:
    """The Python with Dream's client library: ROBOUSE_DREAM_PYTHON, else <cache>/dream-venv."""
    return config.env("ROBOUSE_DREAM_PYTHON") or str(config.cache_dir() / "dream-venv" / "bin" / "python")


def build(model: str, prompt: str, workspace: Path, task: Any, env: dict) -> Any:
    from .. import Launch, _task_language

    py = client_python()
    creds = credentials()  # before anything is written: a missing key stops the trial here
    client = workspace / ".robouse" / "dream_client.py"
    client.write_text(CLIENT.read_text())
    env.update(creds)
    # the key and the URLs come from the environment; a credentials path that does not exist keeps the client away
    # from the user's file (a file it cannot read would be an error)
    env["DREAM_CREDENTIALS"] = str(workspace / ".robouse" / "dream-credentials-unused")
    env["DREAM_LOG_DIR"] = str(workspace / ".robouse" / "dream-log")  # the client's own diagnostic log
    m = model or DEFAULT_MODEL
    actions = int(config.env("ROBOUSE_DREAM_ACTIONS") or 48)
    env["ROBOUSE_DREAM_CONFIG"] = json.dumps({"model": m, "actions": actions})
    env["ROBOUSE_TASK_LANGUAGE"] = _task_language(task)
    gateway = creds.get("DREAM_GATEWAY_URL", "https://api.dreamlabs.ai")
    return Launch([py, str(client)], env, notes={"model": m, "provider": "dreamlabs", "server": gateway})
