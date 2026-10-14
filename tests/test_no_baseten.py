"""No default reaches Baseten, and no Baseten key is ever loaded implicitly. The defaults are GLM-5.3 on the Z.ai Coding
Plan (`glm/glm-5.3`, BenchFlow's glm provider: GLM_API_KEY and GLM_BASE_URL), or an explicit model where the model
must read images (show-harness, the VLM grader). Baseten stays only as history: the earlier trial folders still map
to their baseten/ pairs (test_models.py, test_runs_site.py). Nothing here sends a request."""

from __future__ import annotations

import builtins
import json
import os
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
    # the one mention left is the history entry's auth_env (models.PENDING_PROVIDERS), which only an explicit baseten/
    # id reaches; the runner's agent-environment filter strips the prefix BASETEN
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


def test_the_key_file_is_never_read(tmp_path, monkeypatch, capsys, no_provider_env) -> None:
    """A maintainer's ~/.config/bf-agents/baseten.env is there, and BASETEN_API_KEY is in the environment: doctor, the
    grader, the model plan and the run command's checks open no Baseten file and use neither."""
    agents = tmp_path / "bf-agents"
    agents.mkdir()
    (agents / "baseten.env").write_text("BASETEN_API_KEY=from-a-key-file\n")
    monkeypatch.setattr(_maintainer, "AGENTS_DIR", agents)
    from robouse.analysis import grader
    from robouse.core import gl

    monkeypatch.setattr(gl, "auto_select", lambda: None)
    monkeypatch.setattr(gl, "probe", lambda p=None, python=None: None)
    seen = _watch_reads(monkeypatch, agents)
    assert main(["doctor"]) == 0
    with pytest.raises(RuntimeError, match="ROBOUSE_GRADER_URL and ROBOUSE_GRADER_API_KEY"):
        grader.endpoint()
    for h in ("claude-code", "codex", "mini-swe-agent", "dimcode"):
        try:
            image_input_plan(h, "")
        except RuntimeError:  # glm/ without BenchFlow installed: the message says what to install
            pass
    assert main(["run", "--task", str(ARC), "--harness", "mini-swe-agent", "--out", str(tmp_path / "job")]) == 2
    out = capsys.readouterr()
    assert "from-a-key-file" not in out.out + out.err and "BASETEN" not in out.out + out.err
    assert seen == [] and not (tmp_path / "job").exists()


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


def test_messages_clients_reach_glm_over_chat_completions(monkeypatch) -> None:
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
    out = asyncio.run(
        H.RobouseGateway().async_pre_call_hook(None, None, json.loads(json.dumps(body)), "anthropic_messages")
    )
    assert "thinking" not in out and out["max_tokens"] == 10
    chat = {"model": "m", "messages": [], "reasoning_effort": "medium"}  # other call types pass as sent
    assert asyncio.run(H.RobouseGateway().async_pre_call_hook(None, None, dict(chat), "acompletion")) == chat
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
    assert "glm does not" in run("--harness", "codex", "--model", "glm/glm-5.3")
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
    }
    for k, v in secret.items():
        monkeypatch.setenv(k, v)
    run_trial(load_task(ARC), "envdump", "", tmp_path / "job")
    assert seen["env"] and not set(secret) & set(seen["env"])
    assert not any(v in json.dumps(seen["env"]) for v in secret.values())
    # the runner's own environment keeps it: the gateway runs there
    assert os.environ["GLM_CODING_API_KEY"] == "glm-key-0002"
