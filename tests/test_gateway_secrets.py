"""The model gateway's per-trial master key never reaches a file. gateway/config.yaml names the variable that holds it
(os.environ/LITELLM_MASTER_KEY) and the key lives only in the proxy's environment, as the provider key does. A finished
gateway trial is scanned for it, file by file. And the runs viewer (tools/site/build_runs_site.py) redacts a key of that
shape, and its publish scan fails the build if one ever reached the published output."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import secrets
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ARC = ROOT / "tasks" / "arc-style" / "arc-gravity"
KEY_SHAPE = re.compile(rb"sk-robouse-[0-9a-f]{8,}")
WRONG = "sk-robouse-" + "0" * 32
# the stand-in for Claude Code asks the gateway for its models, with the key it was given and with a wrong one, and
# reports both HTTP statuses as its `robo done` message
ASK = """import os, sys, urllib.error, urllib.request
req = urllib.request.Request(
    os.environ["ANTHROPIC_BASE_URL"] + "/v1/models", headers={"Authorization": "Bearer " + sys.argv[1]}
)
try:
    print(urllib.request.urlopen(req, timeout=30).status)
except urllib.error.HTTPError as e:
    print(e.code)
"""


def test_a_finished_gateway_trial_holds_no_key(tmp_path, monkeypatch) -> None:
    for module in ("mujoco", "litellm", "benchflow"):
        pytest.importorskip(module)
    if not (shutil.which("litellm", path=str(Path(sys.executable).parent)) or shutil.which("litellm")):
        pytest.skip("the litellm proxy command is not installed")
    from robouse.harnesses import gateway
    from robouse.runner import run_trial
    from robouse.tasks import load_task

    keys: list[str] = []
    real = gateway.start

    def start(*args, **kwargs):
        gw = real(*args, **kwargs)
        keys.append(gw.key)
        return gw

    monkeypatch.setattr(gateway, "start", start)
    (tmp_path / "ask.py").write_text(ASK)
    stubs = tmp_path / "bin"
    stubs.mkdir()
    ask = f"{sys.executable} {tmp_path / 'ask.py'}"
    (stubs / "claude").write_text(
        f'#!/bin/sh\nrobo done "right=$({ask} "$ANTHROPIC_AUTH_TOKEN") wrong=$({ask} {WRONG})"\n'
    )
    (stubs / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", f"{stubs}:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("ROBOUSE_SANDBOX", "0")  # the stand-in and its helper live in tmp_path
    monkeypatch.setenv("ROBOUSE_CACHE_DIR", str(tmp_path / "cache"))
    # nothing goes upstream: /v1/models is the gateway's own (and the provider URL is a closed local port)
    monkeypatch.setenv("GLM_API_KEY", "not-a-real-key")
    monkeypatch.setenv("GLM_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("ROBOUSE_SPEND_CAP_USD", "0")  # glm-5.3 has no per-token price

    job = tmp_path / "job"
    res = run_trial(load_task(ARC), "claude-code", "glm/glm-5.3", job)
    assert len(keys) == 1, "the trial did not start the gateway"
    key = keys[0].encode()
    files = [p for p in sorted(job.rglob("*")) if p.is_file()]
    assert any(p.parent.name == "gateway" for p in files)  # config.yaml, proxy.log, ...
    hits = [
        str(p.relative_to(job))
        for p in files
        if key in (data := p.read_bytes()) or key.removeprefix(b"sk-robouse-") in data or KEY_SHAPE.search(data)
    ]
    assert not hits, f"the gateway's master key is in {hits}"

    trial = job / res["trial"]
    assert "master_key: os.environ/LITELLM_MASTER_KEY" in (trial / "gateway" / "config.yaml").read_text()
    # the key that reached the proxy through its environment is the one it accepts, and the only one (LiteLLM refuses
    # a wrong key with 400, 401 or 403, depending on its version)
    episode = json.loads((trial / "result.json").read_text()).get("episode") or {}
    statuses = dict(part.split("=") for part in str(episode.get("agent_text", "")).split())
    assert statuses.get("right") == "200" and statuses.get("wrong") in ("400", "401", "403"), episode


@pytest.mark.maintainer
@pytest.mark.skipif(sys.version_info < (3, 12), reason="tools/site/build_runs_site.py needs Python 3.12")
def test_the_runs_viewer_never_publishes_a_gateway_key(tmp_path) -> None:
    spec = importlib.util.spec_from_file_location("build_runs_site", ROOT / "tools" / "site" / "build_runs_site.py")
    site = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(site)
    key = "sk-robouse-" + secrets.token_hex(16)
    text = f"general_settings:\n  master_key: {key}\n"
    assert key not in site.redact(text) and "[redacted]" in site.redact(text)  # what the build writes is redacted
    out = tmp_path / "out"
    (out / "d").mkdir(parents=True)
    (out / "d" / "trial.json").write_text(json.dumps({"gateway/config.yaml": text}))
    hits = site.scan(out)  # and if a key got past that, the publish scan finds it, which fails the build
    assert hits and all(h.startswith("d/trial.json: ") for h in hits) and any(key[:24] in h for h in hits), hits
