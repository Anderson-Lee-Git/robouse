"""Whole trials through a real model gateway (a LiteLLM proxy) to a stub provider on this machine, driven by a scripted
agent that behaves like a model harness. Two regressions:

- No image input: a text-only model on a vision task. The task runs (every task is open to every model), the agent's
  camera images stay files in its workspace, the hidden object state stays hidden, and no image part reaches the
  provider whatever the agent sends; the trial records image_input: false.
- Spend cap: the gateway refuses requests once the model's cost reaches the cap and the runner stops the agent; the
  trial is recorded as a budget stop, not an infrastructure failure and not an ordinary unsolved attempt.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("mujoco")
pytest.importorskip("benchflow")
pytest.importorskip("litellm")

from robouse import harnesses
from robouse.harnesses import models
from robouse.runner import run_trial
from robouse.runner import trial as trial_mod
from robouse.tasks import load_task

ROOT = Path(__file__).resolve().parents[1]
VISION_TASK = ROOT / "tasks" / "vision" / "arc-gravity-vision"
MODEL = "stubprov/stub/text-model"

AGENT = r'''
import base64, glob, json, os, subprocess, sys, time, urllib.error, urllib.request

def ask(content):
    body = {"model": os.environ["GW_MODEL"], "messages": [{"role": "user", "content": content}]}
    req = urllib.request.Request(os.environ["GW_URL"] + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Authorization": "Bearer " + os.environ["GW_KEY"]})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code

obs = json.loads(subprocess.check_output(["robo", "observe", "--image", "--json"]))["result"]
report = {"observe": obs, "pngs": sorted(glob.glob("**/*.png", recursive=True)), "codes": []}
path = obs.get("image_path")
if isinstance(path, list):
    path = path[0]
png = base64.b64encode(open(path, "rb").read()).decode() if path else ""
image = [{"type": "text", "text": "what is in the picture?"},
         {"type": "image_url", "image_url": {"url": "data:image/png;base64," + png}}]
for i in range(int(os.environ["N_REQUESTS"])):
    report["codes"].append(ask(image if i % 2 == 0 else "and now?"))
    json.dump(report, open(os.environ["REPORT"], "w"))
    if report["codes"][-1] != 200:
        time.sleep(float(os.environ.get("HOLD_S", "0")))  # the runner should stop us here
subprocess.run(["robo", "done", "scripted agent"], check=False)
'''


class Stub(BaseHTTPRequestHandler):
    """An OpenAI-compatible chat completions endpoint that records what reaches it."""

    bodies: list = []
    usage = {"prompt_tokens": 1000, "completion_tokens": 10, "total_tokens": 1010}

    def do_POST(self) -> None:  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        Stub.bodies.append(body.decode())
        out = json.dumps({
            "id": "stub", "object": "chat.completion", "created": 0, "model": "stub/text-model",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": Stub.usage,
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a) -> None:
        pass


@pytest.fixture
def stub_provider(tmp_path, monkeypatch):
    """A provider `stubprov` in the registry, serving one text-only model from a local stub; its price in a pricing
    file; a scripted harness `stubagent` that reaches it through the trial's gateway."""
    Stub.bodies = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    entry = {
        "name": "stubprov", "base_url": url, "api_protocol": "openai-completions", "auth_type": "api_key",
        "auth_env": "STUBPROV_API_KEY", "endpoints": {"openai-completions": url},
        "models": [{"id": "stub/text-model", "name": "Stub", "input": ["text"]}],
    }
    monkeypatch.setitem(models.PENDING_PROVIDERS, "stubprov", entry)
    reg = models.provider_registry()
    monkeypatch.setitem(reg, "stubprov", type(next(iter(reg.values())))(**entry))
    monkeypatch.setenv("STUBPROV_API_KEY", "stub-provider-key")
    pricing = tmp_path / "pricing.json"
    pricing.write_text(json.dumps({"stub/text-model": {"input": 1.0, "output": 1.0}}))
    monkeypatch.setenv("ROBOUSE_PRICING", str(pricing))
    monkeypatch.setenv("ROBOUSE_SANDBOX", "0")  # the stub agent needs no sandbox; the sandbox has its own tests
    monkeypatch.setattr(trial_mod, "LLM_HARNESSES", (*trial_mod.LLM_HARNESSES, "stubagent"))
    report = tmp_path / "report.json"

    def stubagent(model, prompt, workspace, task, env):
        ref = models.resolve("stubagent", model)
        gw = harnesses._gateway(ref, env, "openai-completions")
        script = workspace / ".robouse" / "agent.py"
        script.write_text(AGENT)
        env.update({"GW_URL": gw.url, "GW_KEY": gw.key, "GW_MODEL": gw.model, "REPORT": str(report)})
        return harnesses._gateway_launch(gw, ref, [sys.executable, str(script)], env)

    monkeypatch.setitem(harnesses.HARNESSES, "stubagent", stubagent)
    yield report
    srv.shutdown()


def _trial(job: Path, res: dict) -> tuple[dict, dict]:
    d = job / res["trial"]
    return json.loads((d / "config.json").read_text()), json.loads((d / "result.json").read_text())


def test_a_text_only_model_runs_a_vision_task_and_no_image_reaches_it(stub_provider, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("N_REQUESTS", "3")
    task = load_task(VISION_TASK)
    job = tmp_path / "job"
    res = run_trial(task, "stubagent", MODEL, job, timeout=120)
    assert res["exception"] is None, res
    cfg, result = _trial(job, res)
    report = json.loads(stub_provider.read_text())
    # the task ran as a vision task: images are files the agent can open, the hidden state stays hidden
    assert report["observe"].get("image_path") and report["pngs"]
    assert set(report["observe"]["state"]) <= set(task.spec["visible_fields"])
    assert report["codes"] == [200, 200, 200]
    # ... and the model got no image input: nothing image-like reached the provider
    assert len(Stub.bodies) == 3
    for body in Stub.bodies:
        assert "image_url" not in body and "data:image" not in body and "base64" not in body
    assert "[image removed: no image input in this run]" in Stub.bodies[0]
    assert (cfg["image_input"], result["image_input"]) == (False, False)
    assert "text-only" in cfg["image_input_reason"] and cfg["accepts_images"] is False
    assert (cfg["harness"], cfg["model"]) == ("stubagent", MODEL)
    stats = result["proxy_stats"]
    assert stats["upstream_image_parts"] == 0 and stats["upstream_data_uris"] == 0 and stats["images_removed"] == 2
    assert result["budget_stop"] is None and result["episode"]["outcome"] != "budget_stop"
    assert "stub-provider-key" not in json.dumps(cfg) + json.dumps(result)  # the provider key stays in the gateway
    assert "stub-provider-key" not in (job / res["trial"] / "gateway" / "config.yaml").read_text()


def test_the_spend_cap_stops_the_trial_as_a_budget_stop(stub_provider, tmp_path, monkeypatch) -> None:
    Stub.usage = {"prompt_tokens": 3_000_000, "completion_tokens": 0, "total_tokens": 3_000_000}  # $3 per response
    monkeypatch.setenv("N_REQUESTS", "50")
    monkeypatch.setenv("HOLD_S", "120")
    monkeypatch.setenv("ROBOUSE_SPEND_CAP_USD", "5")
    task = load_task(VISION_TASK)
    job = tmp_path / "job"
    try:
        res = run_trial(task, "stubagent", MODEL, job, timeout=300)
    finally:
        Stub.usage = {"prompt_tokens": 1000, "completion_tokens": 10, "total_tokens": 1010}
    assert res["exception"] is None, res
    cfg, result = _trial(job, res)
    report = json.loads(stub_provider.read_text())
    # $3, then $6: past the cap. The cost is counted as each response is logged, so at most one more request can
    # slip through before the gateway refuses; nothing after that reaches the provider
    assert 2 <= len(Stub.bodies) <= 3
    assert report["codes"][:2] == [200, 200] and report["codes"][-1] == 402
    assert result["wall_time_s"] < 100  # stopped at the cap, not at the 120 s the agent would have waited
    assert result["budget_stop"]["cap_usd"] == 5 and 6.0 <= result["budget_stop"]["spent_usd"] <= 9.0
    assert result["episode"]["outcome"] == "budget_stop" and res["outcome"] == "budget_stop"
    assert result["exception_info"] is None and result["verifier_result"]["rewards"]["reward"] == 0.0
    assert cfg["spend_cap_usd"] == 5
    assert result["proxy_stats"]["refused_over_cap"] >= 1

    sys.path.insert(0, str(ROOT / "tools" / "analysis"))
    import audit

    rec = audit.audit_trial(job / res["trial"])
    assert rec["outcome"] == "budget_stop" and rec["infra_failure"] is False and rec["budget_stop"]
