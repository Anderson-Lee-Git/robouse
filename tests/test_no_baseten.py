"""No default reaches Baseten, and no Baseten key is ever loaded implicitly. The defaults are GLM-5.3 on the Z.ai Coding
Plan (`glm/glm-5.3`, BenchFlow's glm provider: GLM_API_KEY and GLM_BASE_URL), or an explicit model where the model
must read images (show-harness, the VLM grader). Baseten stays only as history: the earlier trial folders still map
to their baseten/ pairs (test_models.py, test_runs_site.py), and a new run refuses a baseten/ model. Nothing here sends
a request."""

from __future__ import annotations

import builtins
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest

from robouse import _maintainer
from robouse.cli import main
from robouse.harnesses import credentials, models
from robouse.runner.trial import LLM_HARNESSES, image_input_plan

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "robouse"
ARC = ROOT / "tasks" / "arc-style" / "arc-gravity"
ZAI_VARS = ("GLM_API_KEY", "GLM_BASE_URL")


@pytest.fixture
def no_provider_env(monkeypatch):
    for var in (*ZAI_VARS, "ROBOUSE_SPEND_CAP_USD", "ROBOUSE_GRADER_URL", "ROBOUSE_GRADER_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("BASETEN_API_KEY", "a-baseten-key-that-must-not-be-used")


def test_no_default_model_is_a_baseten_model() -> None:
    assert not any(m.startswith("baseten/") for m in models.DEFAULT_MODELS.values())
    assert models.DEFAULT_MODELS["mini-swe-agent"] == models.DEFAULT_MODELS["dimcode"] == "glm/glm-5.3"
    pytest.importorskip("benchflow")  # resolving glm/ needs BenchFlow's registry
    for h in LLM_HARNESSES:
        if h == "show-harness":  # no default: its model must read the camera images
            with pytest.raises(ValueError, match="show-harness needs --model"):
                image_input_plan(h, "")
            continue
        model = image_input_plan(h, "")["model"]
        assert not model.startswith("baseten/") and models.resolve(h, model).provider != "baseten", (h, model)


def test_the_maintainer_script_runs_no_baseten_pair() -> None:
    text = (ROOT / "tools" / "ops" / "final_run.sh").read_text()
    pairs = next(line for line in text.splitlines() if line.startswith("PAIRS="))
    assert "baseten" not in pairs and "glm/glm-5.3" in pairs and "codex:glm" not in pairs


def test_no_source_file_names_the_baseten_key_file_or_reads_the_key() -> None:
    assert not hasattr(_maintainer, "BASETEN_ENV") and not hasattr(_maintainer, "baseten_key")
    assert not hasattr(credentials, "baseten_key") and not hasattr(credentials, "have_baseten")
    files = [p for p in SRC.rglob("*.py") if "_upstream" not in str(p)]
    assert not [str(p) for p in files if "baseten.env" in p.read_text()]
    # the one mention left is the history entry's auth_env (models.PENDING_PROVIDERS), which no new run reaches (a
    # baseten/ id is refused); the runner's agent-environment filter strips the prefix BASETEN
    assert [p.name for p in files if "BASETEN_API_KEY" in p.read_text()] == ["models.py"]


def _watch_reads(monkeypatch, agents: Path) -> list[str]:
    """Record every file opened that is named after Baseten or lies in the maintainers' credential folder."""
    seen: list[str] = []
    real_open, real_read = builtins.open, Path.read_text

    def suspect(p) -> bool:
        p = Path(os.fsdecode(p)) if isinstance(p, str | bytes | os.PathLike) else None
        return p is not None and ("baseten" in p.name.lower() or agents in p.parents)

    def opened(file, *a, **k):
        if suspect(file):
            seen.append(str(file))
        return real_open(file, *a, **k)

    def read_text(self, *a, **k):
        if suspect(self):
            seen.append(str(self))
        return real_read(self, *a, **k)

    monkeypatch.setattr(builtins, "open", opened)
    monkeypatch.setattr(Path, "read_text", read_text)
    return seen


def test_doctor_the_model_plan_and_run_use_no_baseten_key(tmp_path, monkeypatch, capsys, no_provider_env) -> None:
    """A baseten.env is in the configured credential pool folder (where 0.4.0 read ~/.config/bf-agents/baseten.env),
    and BASETEN_API_KEY is in the environment: doctor, the model plan and the run command's checks open no Baseten
    file, and the run still stops for want of the default model's own settings (with a Baseten default, the key in the
    environment would have let it start)."""
    agents = tmp_path / "bf-agents"
    agents.mkdir()
    (agents / "baseten.env").write_text("BASETEN_API_KEY=from-a-key-file\n")
    monkeypatch.setenv("ROBOUSE_CODEX_AUTH_DIR", str(agents))
    from robouse.core import gl

    monkeypatch.setattr(gl, "auto_select", lambda: None)
    monkeypatch.setattr(gl, "probe", lambda p=None, python=None: None)
    seen = _watch_reads(monkeypatch, agents)
    assert main(["doctor"]) == 0
    for h in ("claude-code", "codex", "mini-swe-agent", "dimcode"):
        try:
            image_input_plan(h, "")
        except RuntimeError:  # glm/ without BenchFlow installed: the message says what to install
            pass
    assert main(["run", "--task", str(ARC), "--harness", "mini-swe-agent", "--out", str(tmp_path / "job")]) == 2
    out = capsys.readouterr()
    assert "from-a-key-file" not in out.out + out.err and "BASETEN" not in out.out + out.err
    assert seen == [] and not (tmp_path / "job").exists()


class _Grader(BaseHTTPRequestHandler):
    """An OpenAI-compatible endpoint that records the Authorization header of every request and says yes."""

    seen: list = []

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        _Grader.seen.append(self.headers.get("Authorization", ""))
        out = json.dumps({"choices": [{"message": {"content": '{"verdict": "yes", "reason": "stub"}'}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a) -> None:
        pass


def test_the_grader_never_uses_the_baseten_key_or_key_file(tmp_path, monkeypatch, capsys, no_provider_env) -> None:
    """The VLM grader (`robouse grade`, `real.verdict: vlm`) was the one reader of BASETEN_API_KEY and of
    ~/.config/bf-agents/baseten.env: given only one of them, robouse 0.4.0 sent that key to the grader's endpoint. With
    the variable set, then with only the file, it now stops before any request; with its own key it sends that one."""
    pytest.importorskip("PIL")
    from robouse.analysis import grader

    _Grader.seen = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Grader)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    agents = tmp_path / "bf-agents"
    agents.mkdir()
    (agents / "baseten.env").write_text("BASETEN_API_KEY=from-a-key-file\n")
    monkeypatch.setenv("ROBOUSE_CODEX_AUTH_DIR", str(agents))
    monkeypatch.setattr(_maintainer, "BASETEN_ENV", agents / "baseten.env", raising=False)  # where 0.4.0 read it
    monkeypatch.setenv("ROBOUSE_GRADER_URL", f"http://127.0.0.1:{srv.server_address[1]}/v1")
    frames = [np.zeros((4, 4, 3), np.uint8)]
    reads = _watch_reads(monkeypatch, agents)
    try:
        with pytest.raises(RuntimeError, match="the VLM grader needs ROBOUSE_GRADER_API_KEY"):  # BASETEN_API_KEY set
            grader.vlm_verdict(frames, "task", None, "some-vlm")
        monkeypatch.delenv("BASETEN_API_KEY")
        with pytest.raises(RuntimeError, match="the VLM grader needs ROBOUSE_GRADER_API_KEY"):  # only the file
            grader.vlm_verdict(frames, "task", None, "some-vlm")
        assert main(["grade", "--model", "some-vlm", str(tmp_path)]) == 2
        assert _Grader.seen == [] and reads == []
        monkeypatch.setenv("ROBOUSE_GRADER_API_KEY", "grader-key")
        assert grader.vlm_verdict(frames, "task", None, "some-vlm")["verdict"] == "yes"
        assert _Grader.seen == ["Bearer grader-key"] and reads == []
    finally:
        srv.shutdown()
    assert "from-a-key-file" not in capsys.readouterr().err


def test_the_grader_needs_its_own_endpoint_key_and_model(tmp_path, monkeypatch, capsys, no_provider_env) -> None:
    from robouse.analysis import grader

    assert not hasattr(grader, "DEFAULT_MODEL") and not hasattr(grader, "DEFAULT_URL")
    with pytest.raises(SystemExit):  # --model is required
        main(["grade", str(tmp_path)])
    assert "--model" in capsys.readouterr().err
    assert main(["grade", "--model", "some-vlm", str(tmp_path)]) == 2  # before any trial is read
    assert "the VLM grader needs ROBOUSE_GRADER_URL and ROBOUSE_GRADER_API_KEY" in capsys.readouterr().err
    with pytest.raises(ValueError, match="needs a model"):
        grader.vlm_verdict([np.zeros((4, 4, 3), np.uint8)], "task")

    pytest.importorskip("PIL")
    monkeypatch.setenv("ROBOUSE_GRADER_URL", "http://127.0.0.1:9/v1/")
    monkeypatch.setenv("ROBOUSE_GRADER_API_KEY", "grader-key")
    sent: dict = {}

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": '{"verdict": "yes", "reason": "ok"}'}}]}).encode()

    def urlopen(req, timeout=None):
        sent.update(url=req.full_url, auth=req.get_header("Authorization"), body=json.loads(req.data))
        return Reply()

    monkeypatch.setattr(grader.urllib.request, "urlopen", urlopen)
    res = grader.vlm_verdict([np.zeros((4, 4, 3), np.uint8)], "task", model="some-vlm")
    assert res["verdict"] == "yes" and sent["body"]["model"] == "some-vlm"
    assert sent["url"] == "http://127.0.0.1:9/v1/chat/completions" and sent["auth"] == "Bearer grader-key"


def test_the_gateway_names_every_missing_setting_at_once() -> None:
    pytest.importorskip("benchflow")
    from robouse.harnesses.gateway import check_settings

    ref = models.resolve("mini-swe-agent", "glm/glm-5.3")
    with pytest.raises(RuntimeError) as e:
        check_settings(ref, "openai-completions", 5.0, {})
    msg = str(e.value)
    assert "model glm/glm-5.3 needs GLM_API_KEY and GLM_BASE_URL in the environment" in msg
    assert "no price for glm-5.3 in pricing.json" in msg and "ROBOUSE_SPEND_CAP_USD=0" in msg
    assert "GLM_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4" in msg and "baseten" not in msg.lower()
    env = {"GLM_API_KEY": "k", "GLM_BASE_URL": "http://127.0.0.1:9/v1"}
    with pytest.raises(RuntimeError) as e:
        check_settings(ref, "openai-completions", 5.0, env)
    assert str(e.value).startswith("no price for glm-5.3") and "needs GLM" not in str(e.value)
    check_settings(ref, "openai-completions", 0.0, env)  # all set: no error
    check_settings(ref, "anthropic-messages", 0.0, env)  # Claude Code and dimcode: translated to chat completions
    with pytest.raises(RuntimeError, match="Codex needs a provider that serves the Responses API; glm does not"):
        check_settings(ref, "openai-responses", 0.0, env)


def test_messages_clients_reach_glm_over_chat_completions(monkeypatch, tmp_path) -> None:
    """LiteLLM sends an Anthropic Messages request with thinking enabled to an OpenAI-compatible provider's Responses
    API; the Coding Plan has none (404 at .../paas/v4/responses: dimcode stopped at its first request). For such a
    provider the gateway removes `thinking`, so Claude Code and dimcode get chat completions."""
    pytest.importorskip("benchflow")
    pytest.importorskip("litellm")
    import asyncio

    from benchflow.providers.litellm_config import resolve_litellm_route

    from robouse.harnesses import gateway
    from robouse.harnesses.providers import gateway_hook as H

    env = {"GLM_API_KEY": "k", "GLM_BASE_URL": "http://127.0.0.1:9/v1", "ZAI_API_KEY": "k"}
    reg = models.provider_registry()
    glm = models.resolve("dimcode", "glm/glm-5.3")
    route = gateway._same_protocol_route(resolve_litellm_route(glm.id, env), reg["glm"], "anthropic-messages", env)
    assert route.upstream_model == "openai/glm-5.3"
    assert gateway.drops_thinking(route, reg["glm"], "anthropic-messages")
    assert not gateway.drops_thinking(route, reg["glm"], "openai-completions")  # mini-swe-agent, show-harness
    zai = models.resolve("dimcode", "zai/glm-5.1")  # a provider with its own Anthropic endpoint: unchanged
    zroute = gateway._same_protocol_route(resolve_litellm_route(zai.id, env), reg["zai"], "anthropic-messages", env)
    assert not gateway.drops_thinking(zroute, reg["zai"], "anthropic-messages")

    body = {"model": "m", "max_tokens": 10, "thinking": {"type": "enabled", "budget_tokens": 1024}, "messages": []}
    monkeypatch.setenv("ROBOUSE_GATEWAY_DROP_THINKING", "1")
    monkeypatch.setenv("ROBOUSE_GATEWAY_LOG", str(tmp_path / "requests.jsonl"))
    out = asyncio.run(
        H.RobouseGateway().async_pre_call_hook(None, None, json.loads(json.dumps(body)), "anthropic_messages")
    )
    assert "thinking" not in out and out["max_tokens"] == 10
    chat = {"model": "m", "messages": [], "reasoning_effort": "medium"}  # other call types pass as sent
    assert asyncio.run(H.RobouseGateway().async_pre_call_hook(None, None, dict(chat), "acompletion")) == chat
    # recorded: the trial's result.json gets the count (proxy_stats), so such trials can be told apart
    stats = gateway.summarize(tmp_path / "requests.jsonl")
    assert (stats["requests"], stats["thinking_dropped"]) == (2, 1)
    monkeypatch.delenv("ROBOUSE_GATEWAY_LOG")
    monkeypatch.delenv("ROBOUSE_GATEWAY_DROP_THINKING")
    out = asyncio.run(
        H.RobouseGateway().async_pre_call_hook(None, None, json.loads(json.dumps(body)), "anthropic_messages")
    )
    assert out["thinking"] == body["thinking"]


def test_run_checks_the_model_before_any_trial(tmp_path, monkeypatch, capsys, no_provider_env) -> None:
    pytest.importorskip("benchflow")
    from robouse.cli.run import _check_model

    out = tmp_path / "job"

    def run(*args: str) -> str:
        assert main(["run", "--task", str(ARC), *args, "--out", str(out)]) == 2
        return capsys.readouterr().err

    for h in ("mini-swe-agent", "dimcode"):  # the default model, with nothing set
        err = run("--harness", h)
        assert "model glm/glm-5.3 needs GLM_API_KEY and GLM_BASE_URL in the environment" in err
        assert "GLM_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4" in err
    assert "show-harness needs --model" in run("--harness", "show-harness")
    assert "kept only to read those trials" in run("--harness", "mini-swe-agent-glm")
    monkeypatch.setenv("GLM_API_KEY", "not-a-real-key")
    monkeypatch.setenv("GLM_BASE_URL", "http://127.0.0.1:9/v1")
    assert "no price for glm-5.3" in run("--harness", "mini-swe-agent")
    monkeypatch.setenv("ROBOUSE_SPEND_CAP_USD", "0")
    err = run("--harness", "codex", "--model", "glm/glm-5.3")
    assert "glm does not" in err and "Codex runs on its own model, gpt-6-astra" in err  # and what to run instead
    # a baseten/ model is history, refused for a new run although BASETEN_API_KEY is set (no_provider_env)
    for h in ("mini-swe-agent", "dimcode", "claude-code", "codex", "show-harness"):
        err = run("--harness", h, "--model", "baseten/zai-org/GLM-5.3")
        assert "baseten/zai-org/GLM-5.3 is a Baseten model of the earlier runs" in err and "glm/glm-5.3" in err
    err = run("--engine", "benchflow", "--harness", "claude-code", "--model", "baseten/moonshotai/Kimi-K3")
    assert "baseten/moonshotai/Kimi-K3 is a Baseten model of the earlier runs" in err  # on the BenchFlow engine too
    # show-harness's policy reads the camera images: a gateway model the registry does not list as reading images
    # would get none, so it is refused rather than run blind
    err = run("--harness", "show-harness", "--model", "glm/glm-5.3")
    assert "show-harness needs a model that reads images" in err and "lists no image input for glm/glm-5.3" in err
    err = run("--harness", "mini-swe-agent", "--model", "nosuch/model")
    assert "'nosuch' is not a provider in BenchFlow's registry" in err
    assert not out.exists()  # no trial folder for a run that could not start
    # all set: the checks pass (the run itself would reach Z.ai, so it is not started here)
    for h, m in (("mini-swe-agent", ""), ("dimcode", ""), ("claude-code", "glm/glm-5.3"), ("claude-code", "")):
        assert _check_model(h, m) == 0, capsys.readouterr().err


@pytest.mark.skipif(__import__("importlib").util.find_spec("mujoco") is None, reason="needs MuJoCo")
def test_no_provider_variable_reaches_the_agent(tmp_path, monkeypatch) -> None:
    from robouse import harnesses
    from robouse.harnesses import Launch
    from robouse.runner import run_trial
    from robouse.tasks import load_task

    seen: dict = {}

    def build(model, prompt, workspace, task, env) -> Launch:
        seen["env"] = dict(env)
        return Launch(["robo", "done"], env, notes={"model": "none"})

    monkeypatch.setitem(harnesses.HARNESSES, "envdump", build)
    monkeypatch.setenv("ROBOUSE_SANDBOX", "0")
    secret = {
        "GLM_API_KEY": "glm-key-0001",
        "GLM_BASE_URL": "http://127.0.0.1:9/v1",
        "GLM_CODING_API_KEY": "glm-key-0002",  # the Coding Plan key kept under another name
        "ZAI_API_KEY": "zai-key-0003",
        "BASETEN_API_KEY": "baseten-key-0004",
        "ROBOUSE_GRADER_API_KEY": "grader-key-0005",  # the VLM grader's: the episode server reads it, the agent must not
    }
    for k, v in secret.items():
        monkeypatch.setenv(k, v)
    run_trial(load_task(ARC), "envdump", "", tmp_path / "job")
    assert seen["env"] and not set(secret) & set(seen["env"])
    assert not any(v in json.dumps(seen["env"]) for v in secret.values())
    # the runner's own environment keeps them: the gateway runs there, and the episode server gets it (the grader key)
    assert os.environ["GLM_CODING_API_KEY"] == "glm-key-0002"
    assert os.environ["ROBOUSE_GRADER_API_KEY"] == "grader-key-0005"


def test_a_provider_outside_the_registry_is_named_not_a_traceback(tmp_path, capsys, no_provider_env) -> None:
    """BenchFlow's registry has no first-party Anthropic entry: a gateway harness given anthropic/... got a KeyError
    traceback from the check before a trial."""
    pytest.importorskip("benchflow")
    if "anthropic" in models.provider_registry():
        pytest.skip("this BenchFlow has an anthropic provider")
    for h in ("codex", "mini-swe-agent"):
        args = ["run", "--task", str(ARC), "--harness", h, "--model", "anthropic/claude-opus-5-5"]
        assert main([*args, "--out", str(tmp_path / "job")]) == 2
        err = capsys.readouterr().err
        assert "the model gateway cannot reach anthropic/claude-opus-5-5" in err and "Traceback" not in err
        assert "--harness claude-code with the bare id, claude-opus-5-5" in err
    assert not (tmp_path / "job").exists()


def test_the_run_check_and_the_gateway_read_one_environment(tmp_path, monkeypatch, no_provider_env) -> None:
    """The check before a trial and the gateway itself read a provider's settings from gateway.provider_environ(): a
    variable derived from another (a branch derives MiMo's Anthropic URL from MIMO_BASE_URL) must be derived there, or
    the check refuses a model the gateway would serve."""
    pytest.importorskip("benchflow")
    from robouse.harnesses import gateway
    from robouse.runner.trial import check_model

    settings = {"GLM_API_KEY": "k", "GLM_BASE_URL": "http://127.0.0.1:9/v1"}  # in neither os.environ nor the check
    monkeypatch.setenv("ROBOUSE_SPEND_CAP_USD", "0")
    monkeypatch.setattr(gateway, "provider_environ", lambda: dict(settings))
    assert check_model("mini-swe-agent", "")["model"] == "glm/glm-5.3"
    assert check_model("claude-code", "glm/glm-5.3")["model"] == "glm/glm-5.3"
    seen: dict = {}

    def stop(ref, protocol, cap, env=None):
        seen["env"] = env
        raise RuntimeError("stopped before the proxy starts")

    monkeypatch.setattr(gateway, "check_settings", stop)
    with pytest.raises(RuntimeError, match="stopped before the proxy starts"):
        gateway.start(models.resolve("mini-swe-agent", "glm/glm-5.3"), tmp_path, images=False)
    assert seen["env"] == settings


def test_no_published_docs_page_names_baseten() -> None:
    """Baseten served the September runs and stays only in their records: no page the docs builder publishes names it
    (a merge with an older docs branch would bring its Baseten examples and defaults back)."""
    import ast

    tree = ast.parse((ROOT / "tools" / "docs" / "build_docs.py").read_text())
    pages = next(
        ast.literal_eval(n.value)
        for n in tree.body
        if isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "PAGES"
    )
    assert len(pages) > 10
    hits = [
        f"{page[1]}:{i}"
        for page in pages
        for i, line in enumerate((ROOT / page[1]).read_text().splitlines(), 1)
        if "baseten" in line.lower()
    ]
    assert not hits


def test_agents_cannot_read_the_maintainers_provider_keys(tmp_path, monkeypatch) -> None:
    """The maintainers keep provider keys in env files under ~/.config/benchflow (the Z.ai Coding Plan's among them):
    the agent sandbox hides the folder (sandbox.HOME_DENIED), as it hides a configured credential pool."""
    from robouse.runner.sandbox import bwrap_args, sandbox_profile

    home = tmp_path / "home"
    keys = home / ".config" / "benchflow"
    keys.mkdir(parents=True)
    (keys / "glm-coding.env").write_text("GLM_CODING_API_KEY=not-a-real-key\n")
    monkeypatch.setenv("HOME", str(home))
    real = os.path.realpath(keys)
    assert f'(deny file-read* file-write* (subpath "{real}"))' in sandbox_profile(tmp_path / "ws")
    args = bwrap_args(tmp_path / "ws", str(tmp_path / "sock"), [])
    assert any(a == "--tmpfs" and b == real for a, b in zip(args, args[1:], strict=False))


def test_the_maintainer_script_turns_the_spend_cap_off_only_for_glm_streams(tmp_path) -> None:
    """tools/ops/final_run.sh: a glm/ stream runs without the spend cap (no per-token price), every other stream keeps
    the runner's default, and a cap given in the environment applies to all."""
    import shutil

    repo = tmp_path / "repo"
    (repo / "tools" / "ops").mkdir(parents=True)
    shutil.copy(ROOT / "tools" / "ops" / "final_run.sh", repo / "tools" / "ops" / "final_run.sh")
    for d in ("tasks/s", ".venv/bin", "runs"):
        (repo / d).mkdir(parents=True)
    exe = repo / ".venv" / "bin" / "robouse"  # records the cap each stream's run-many sees
    exe.write_text('#!/bin/sh\necho "cap=${ROBOUSE_SPEND_CAP_USD:-unset}"\n')
    exe.chmod(0o755)
    pairs = "codex:gpt-6-astra:1:astra claude-code:glm/glm-5.3:1:cc-zai mini-swe-agent:openrouter/x/y:1:or"

    def caps(**extra: str) -> dict:
        for f in (repo / "runs").glob("final-s-*/console.log"):
            f.unlink()
        env = {k: v for k, v in os.environ.items() if k != "ROBOUSE_SPEND_CAP_USD"} | {"FINAL_PAIRS": pairs, **extra}
        subprocess.run(["bash", str(repo / "tools" / "ops" / "final_run.sh"), "s"], env=env, check=True, timeout=30)
        logs = {t: repo / "runs" / f"final-s-{t}" / "console.log" for t in ("astra", "cc-zai", "or")}
        deadline = time.time() + 20
        while time.time() < deadline and not all(f.exists() and f.read_text() for f in logs.values()):
            time.sleep(0.1)
        return {t: f.read_text().strip() for t, f in logs.items()}

    assert caps() == {"astra": "cap=unset", "cc-zai": "cap=0", "or": "cap=unset"}
    assert caps(ROBOUSE_SPEND_CAP_USD="2") == {"astra": "cap=2", "cc-zai": "cap=2", "or": "cap=2"}


def _rerun_tool():
    import importlib.util

    spec = importlib.util.spec_from_file_location("rerun_infra", ROOT / "tools" / "analysis" / "rerun_infra.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _infra_failed_job(tmp_path: Path, pairs: dict) -> tuple[Path, Path]:
    job = tmp_path / "runs" / "j"
    recs = []
    for name, (h, m) in pairs.items():
        d = job / name
        d.mkdir(parents=True)
        (d / "config.json").write_text(json.dumps({"task_path": str(ARC), "harness": h, "model": m}))
        recs.append({"path": str(d), "job": "j", "trial": name, "infra_failure": True, "harness": h})
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({"trials": recs}))
    return job, audit


def test_rerun_infra_reruns_no_baseten_pair_and_moves_only_what_it_reruns(
    tmp_path, monkeypatch, capsys, no_provider_env
) -> None:
    """tools/analysis/rerun_infra.py re-runs a trial's recorded pair with run_trial directly. A pair served by Baseten
    (a -glm name, a baseten/ model, or 0.4.0's empty-model default) is not re-run, whatever key is set; a pair that
    cannot start here is not either; neither is moved out of its job. It used to move the trial first and then fail
    (a -glm name) or reach Baseten (a baseten/ model with BASETEN_API_KEY set)."""
    pytest.importorskip("benchflow")
    mod = _rerun_tool()
    pairs = {
        "a__codex-glm__1": ("codex-glm", "zai-org/GLM-5.3"),
        "b__mini-swe-agent-glm__2": ("mini-swe-agent-glm", ""),
        "c__claude-code__3": ("claude-code", "baseten/moonshotai/Kimi-K3"),
        "d__mini-swe-agent__4": ("mini-swe-agent", ""),  # recorded by 0.4.0: its default, Baseten's GLM-5.3
        "e__mini-swe-agent__5": ("mini-swe-agent", "glm/glm-5.3"),  # no GLM settings here
        "f__noop__6": ("noop", ""),
    }
    job, audit = _infra_failed_job(tmp_path, pairs)
    calls = []

    def run_trial(task, harness, model, job_dir):
        calls.append((harness, model))
        return {"trial": "f__noop__new", "reward": 0.0, "outcome": "gave_up"}

    monkeypatch.setattr(mod, "run_trial", run_trial)
    monkeypatch.setattr(sys, "argv", ["rerun_infra.py", "--audit", str(audit), "--concurrency", "1"])
    mod.main()
    out = capsys.readouterr().out
    assert calls == [("noop", "")]
    assert out.count("served by Baseten") == 4 and "cannot start here: model glm/glm-5.3 needs GLM_API_KEY" in out
    left = {p.name for p in job.iterdir() if p.is_dir() and p.name != "_infra_failed"}
    assert left == set(pairs) - {"f__noop__6"} and {p.name for p in (job / "_infra_failed").iterdir()} == {"f__noop__6"}

    # a re-run that raises before it starts puts the trial back, and the other re-runs go on
    job2, audit2 = _infra_failed_job(tmp_path / "2", {"g__noop__7": ("noop", ""), "h__oracle__8": ("oracle", "")})
    calls.clear()

    def run_trial2(task, harness, model, job_dir):
        calls.append(harness)
        if harness == "noop":
            raise ValueError("cannot start")
        return {"trial": "h__oracle__new", "reward": 1.0, "outcome": "success_reached"}

    monkeypatch.setattr(mod, "run_trial", run_trial2)
    monkeypatch.setattr(sys, "argv", ["rerun_infra.py", "--audit", str(audit2), "--concurrency", "1"])
    mod.main()
    assert sorted(calls) == ["noop", "oracle"] and (job2 / "g__noop__7" / "config.json").is_file()
    assert "not re-run, left in place: ValueError: cannot start" in capsys.readouterr().out
