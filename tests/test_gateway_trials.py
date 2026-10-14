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


RESPONSE = {  # a minimal Responses API reply
    "id": "resp_stub",
    "object": "response",
    "created_at": 0,
    "status": "completed",
    "model": "stub/text-model",
    "output": [
        {
            "type": "message",
            "id": "msg_stub",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "ok", "annotations": []}],
        }
    ],
    "parallel_tool_calls": True,
    "tool_choice": "auto",
    "tools": [],
    "usage": {"input_tokens": 1000, "output_tokens": 10, "total_tokens": 1010},
}


class Stub(BaseHTTPRequestHandler):
    """An OpenAI-compatible chat completions and Responses endpoint that records what reaches it."""

    bodies: list = []
    paths: list = []
    usage = {"prompt_tokens": 1000, "completion_tokens": 10, "total_tokens": 1010}

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        Stub.bodies.append(body.decode())
        Stub.paths.append(self.path)
        if self.path.endswith("/responses"):
            return self._reply(RESPONSE)
        self._reply(
            {
                "id": "stub",
                "object": "chat.completion",
                "created": 0,
                "model": "stub/text-model",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": Stub.usage,
            }
        )

    def _reply(self, obj: dict) -> None:
        out = json.dumps(obj).encode()
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
    Stub.bodies, Stub.paths = [], []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    entry = {
        "name": "stubprov",
        "base_url": url,
        "api_protocol": "openai-completions",
        "auth_type": "api_key",
        "auth_env": "STUBPROV_API_KEY",
        "endpoints": {"openai-completions": url, "openai-responses": url},
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


def test_codex_requests_reach_the_provider_with_their_reasoning(stub_provider, tmp_path) -> None:
    """Regression (2026-10-01): the Responses-to-chat bridge dropped Codex's reasoning effort and every earlier
    reasoning item, and Codex on GLM-5.3 reasoned about a quarter as much. Codex now uses the provider's own Responses
    endpoint: the request arrives as Codex sent it, except that an image in a tool result moves to a user message."""
    import base64
    import urllib.request

    ws = tmp_path / "ws"
    (ws / ".robouse").mkdir(parents=True)
    env = {
        "_ROBOUSE_TRIAL_DIR": str(tmp_path / "trial"),
        "_ROBOUSE_IMAGE_INPUT": "1",
        "_ROBOUSE_SPEND_CAP_USD": "0",
        "PATH": "/usr/bin:/bin",
    }
    launch = harnesses.build("codex", MODEL, "solve it", ws, None, env)
    try:
        model = launch.cmd[launch.cmd.index("-m") + 1]
        assert not any("bridge" in str(a) for a in launch.cmd)  # the plain alias: the provider's Responses endpoint
        url = next(v for k, v in launch.env.items() if k == "ROBOUSE_GATEWAY_URL")
        png = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
        reasoning_item = {"type": "reasoning", "id": "rs_1", "summary": [{"type": "summary_text", "text": "the plan"}]}
        tools = [
            {"type": "function", "name": "exec_command", "parameters": {"type": "object", "properties": {}}},
            {
                "type": "namespace",
                "name": "multi_agent_v1",
                "description": "agents",
                "tools": [
                    {"type": "function", "name": "spawn_agent", "parameters": {"type": "object", "properties": {}}}
                ],
            },
            {"type": "web_search"},
        ]
        body = {
            "model": model,
            "stream": False,
            "store": False,
            "reasoning": {"effort": "medium", "summary": "auto"},
            "include": ["reasoning.encrypted_content"],
            "tools": tools,
            "input": [
                {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "look"}]},
                reasoning_item,
                {"type": "function_call", "call_id": "c1", "name": "view_image", "arguments": "{}"},
                {
                    "type": "function_call_output",
                    "call_id": "c1",
                    "output": [{"type": "input_image", "image_url": png}],
                },
            ],
        }
        req = urllib.request.Request(
            url + "/v1/responses",
            json.dumps(body).encode(),
            {"Content-Type": "application/json", "Authorization": "Bearer " + launch.env["ROBOUSE_GATEWAY_KEY"]},
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            assert r.status == 200
    finally:
        launch.stop()
    assert Stub.paths[-1].endswith("/responses")  # Responses, not chat completions
    sent = json.loads(Stub.bodies[-1])
    assert sent["reasoning"] == {"effort": "medium", "summary": "auto"}
    assert [i for i in sent["input"] if i.get("type") == "reasoning"] == [reasoning_item]
    assert sent["include"] == ["reasoning.encrypted_content"] and sent["store"] is False
    assert [t.get("type") for t in sent["tools"]] == ["function", "namespace", "web_search"]
    out = next(i for i in sent["input"] if i.get("type") == "function_call_output")
    assert "input_image" not in json.dumps(out["output"])  # Baseten rejects an image in a tool result ...
    user = sent["input"][sent["input"].index(out) + 1]
    assert user["role"] == "user" and user["content"][-1]["image_url"] == png  # ... and takes it in a user message


def test_a_relative_job_folder(stub_provider, tmp_path, monkeypatch) -> None:
    """`--out runs/x` (a relative job folder): the gateway runs in its own folder, so it must get absolute paths (it
    could not find its config.yaml and the trial failed before the agent started)."""
    monkeypatch.setenv("N_REQUESTS", "1")
    monkeypatch.chdir(tmp_path)
    res = run_trial(load_task(VISION_TASK), "stubagent", MODEL, Path("runs") / "rel", timeout=120)
    assert res["exception"] is None, res
    _, result = _trial(tmp_path / "runs" / "rel", res)
    assert result["proxy_stats"]["upstream_calls"] == 1


class ChatOnly(BaseHTTPRequestHandler):
    """A provider that serves only chat completions, as the Z.ai Coding Plan does for BenchFlow's `glm` entry: any other
    path (such as /responses) answers 404. It streams as GLM-5.3 does, reasoning_content first, then a call to the Bash
    tool, or a short text once a tool result is in the conversation."""

    bodies: list = []
    paths: list = []

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        ChatOnly.bodies.append(body)
        ChatOnly.paths.append(self.path)
        if not self.path.endswith("/chat/completions"):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        call = {"index": 0, "id": "call_1", "type": "function", "function": {"name": "Bash", "arguments": ""}}
        args = {"index": 0, "function": {"arguments": json.dumps({"command": "robo done"})}}
        if any(m.get("role") == "tool" for m in body.get("messages", [])):
            deltas, finish = [{"content": "Done."}], "stop"
        else:
            deltas, finish = [{"tool_calls": [call]}, {"tool_calls": [args]}], "tool_calls"
        deltas.insert(0, {"role": "assistant", "reasoning_content": "The episode can end now."})
        usage = {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}
        base = {"id": "chatcmpl-stub", "object": "chat.completion.chunk", "created": 0, "model": "glm-5.3"}
        chunks = [{**base, "choices": [{"index": 0, "delta": d, "finish_reason": None}]} for d in deltas]
        chunks.append({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}], "usage": usage})
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for c in chunks:
                self.wfile.write(f"data: {json.dumps(c)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            return
        message: dict = {"role": "assistant", "content": None, "reasoning_content": deltas[0]["reasoning_content"]}
        if finish == "stop":
            message["content"] = "Done."
        else:
            message["tool_calls"] = [{**call, "function": {"name": "Bash", "arguments": args["function"]["arguments"]}}]
        reply = {**base, "object": "chat.completion", "usage": usage}
        reply["choices"] = [{"index": 0, "message": message, "finish_reason": finish}]
        out = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a) -> None:
        pass


@pytest.fixture
def chat_only_glm(monkeypatch):
    """BenchFlow's real `glm` provider, its GLM_BASE_URL pointed at a local ChatOnly stub (no request leaves this
    machine)."""
    ChatOnly.bodies, ChatOnly.paths = [], []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), ChatOnly)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("GLM_API_KEY", "stub-glm-key")
    monkeypatch.setenv("GLM_BASE_URL", f"http://127.0.0.1:{srv.server_address[1]}/api/coding/paas/v4")
    yield
    srv.shutdown()


def _events(resp) -> list[dict]:
    """The JSON events of a server-sent event stream."""
    out = []
    for line in resp.read().decode().splitlines():
        data = line[5:].strip() if line.startswith("data:") else ""
        if data and data != "[DONE]":
            out.append(json.loads(data))
    return out


@pytest.mark.parametrize("harness", ["claude-code", "dimcode"])
def test_messages_harnesses_reach_a_chat_only_provider_translated(harness, chat_only_glm, tmp_path) -> None:
    """Claude Code and dimcode speak Anthropic Messages; glm/glm-5.3 (the Z.ai Coding Plan) serves only chat
    completions. Through the real gateway (LiteLLM), a streamed Messages request with extended thinking and a tool, then
    the tool's result, reaches the provider as chat completions (never /responses, where the plan answers 404), the
    tool as a function and the result as a tool message; the provider's streamed tool call comes back as a tool_use
    block; and the trial's proxy_stats count the requests whose thinking the gateway removed."""
    import urllib.request

    env = {
        "_ROBOUSE_TRIAL_DIR": str(tmp_path / "trial"),
        "_ROBOUSE_IMAGE_INPUT": "0",
        "_ROBOUSE_SPEND_CAP_USD": "0",
        "PATH": "/usr/bin:/bin",
    }
    ref = models.resolve(harness, "glm/glm-5.3")
    gw = harnesses._gateway(ref, env, harnesses.GATEWAY_PROTOCOLS[harness])
    tools = [
        {
            "name": "Bash",
            "description": "Run a shell command",
            "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
        }
    ]

    def ask(messages: list) -> list[dict]:
        body = {
            "model": gw.model,
            "max_tokens": 2048,
            "stream": True,
            "thinking": {"type": "enabled", "budget_tokens": 1024},
            "tools": tools,
            "messages": messages,
        }
        headers = {"Content-Type": "application/json", "x-api-key": gw.key, "anthropic-version": "2023-06-01"}
        req = urllib.request.Request(gw.url + "/v1/messages", json.dumps(body).encode(), headers)
        with urllib.request.urlopen(req, timeout=60) as r:
            return _events(r)

    try:
        first = [{"role": "user", "content": "End the episode."}]
        events = ask(first)
        tool = next(
            e["content_block"]
            for e in events
            if e.get("type") == "content_block_start" and e["content_block"]["type"] == "tool_use"
        )
        args = "".join(
            e["delta"]["partial_json"]
            for e in events
            if e.get("type") == "content_block_delta" and e["delta"].get("type") == "input_json_delta"
        )
        assert tool["name"] == "Bash" and json.loads(args) == {"command": "robo done"}
        assert next(e for e in events if e.get("type") == "message_delta")["delta"]["stop_reason"] == "tool_use"
        use = {"type": "tool_use", "id": tool["id"], "name": "Bash", "input": {"command": "robo done"}}
        result = {"type": "tool_result", "tool_use_id": tool["id"], "content": "episode over"}
        events = ask([*first, {"role": "assistant", "content": [use]}, {"role": "user", "content": [result]}])
        text = "".join(e["delta"].get("text", "") for e in events if e.get("type") == "content_block_delta")
        assert "Done." in text
    finally:
        gw.stop()
    assert ChatOnly.paths == ["/api/coding/paas/v4/chat/completions"] * 2  # never /responses
    sent_first, sent_second = ChatOnly.bodies
    assert sent_first["model"] == "glm-5.3" and "thinking" not in sent_first
    assert [t["function"]["name"] for t in sent_first["tools"]] == ["Bash"]
    call = next(m for m in sent_second["messages"] if m.get("tool_calls"))["tool_calls"][0]
    reply = next(m for m in sent_second["messages"] if m["role"] == "tool")
    assert call["function"]["name"] == "Bash" and json.loads(call["function"]["arguments"]) == {"command": "robo done"}
    assert reply["tool_call_id"] == call["id"] and "episode over" in json.dumps(reply["content"])
    assert gw.stats["drops_thinking"] is True and gw.stats["thinking_dropped"] == 2
    assert gw.stats["upstream_calls"] == 2 and gw.stats["failures"] == 0
