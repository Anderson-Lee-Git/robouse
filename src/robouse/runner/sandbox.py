"""The macOS Seatbelt profile the local runner puts around agent processes."""
from __future__ import annotations

import os
from pathlib import Path

from .. import config


def sandbox_profile(workspace: str | Path | None = None, local_ports: tuple[int, ...] = ()) -> str:
    """macOS Seatbelt profile for agent processes. Everything is allowed except:

    - reading or writing private settings, the real-robot operator channel, the maintainers' folders and the paths
      in ROBOUSE_SANDBOX_DENY (`config.sandbox_denied_paths`);
    - reading any robo-use source or install (a `robouse` package directory anywhere, e.g. another venv under /tmp);
    - reading other trials' workspaces (only this trial's workspace is allowed);
    - TCP connections to this machine, except `local_ports` (a harness's own local proxy). This keeps agents away
      from local viewers and servers (e.g. a runs viewer on localhost) while the episode Unix socket and the
      network (model APIs) stay reachable.
    Set ROBOUSE_SANDBOX=0 to disable."""
    denied = [os.path.realpath(os.path.expanduser(d)) for d in config.sandbox_denied_paths()]  # Seatbelt matches resolved paths (/tmp -> /private/tmp)
    rules = "".join(f'(deny file-read* file-write* (subpath "{d}"))' for d in dict.fromkeys(denied))
    rules += '(deny file-read* (regex #"/site-packages/robouse(/|$)") (regex #"/src/robouse(/|$)"))'
    rules += '(deny file-read* file-write* (regex #"/robouse-ws-[^/]*(/|$)"))'
    if workspace:
        rules += f'(allow file-read* file-write* (subpath "{os.path.realpath(workspace)}"))'
    rules += '(deny network-outbound (remote ip "localhost:*"))'
    rules += "".join(f'(allow network-outbound (remote ip "localhost:{p}"))' for p in local_ports)
    return "(version 1)(allow default)" + rules
