"""Model ids, providers and image input: naming, legacy aliases, the image-input record, the gateway's image rule, its
handling of Codex's Responses requests and its spend accounting. The end-to-end checks (a real gateway between a scripted agent and a stub
provider) are in test_gateway_trials.py."""

from __future__ import annotations

import asyncio
import json

import pytest

from robouse.harnesses import models

pytest.importorskip("benchflow")


def test_legacy_harness_names_are_aliases_with_a_baseten_model() -> None:
    assert models.legacy("codex-glm", "") == ("codex", "baseten/zai-org/GLM-5.3")
    assert models.legacy("claude-code-glm", "moonshotai/Kimi-K3") == ("claude-code", "baseten/moonshotai/Kimi-K3")
    assert models.legacy("mini-swe-agent-glm", "baseten/zai-org/GLM-5.3") == (
        "mini-swe-agent",
        "baseten/zai-org/GLM-5.3",
    )
    assert models.legacy("codex", "gpt-6-astra") == ("codex", "gpt-6-astra")
    from robouse.cli.run import _unknown_harness

    assert _unknown_harness("codex-glm") == 0 and _unknown_harness("mini-swe-agent") == 0  # hidden aliases still run


def test_old_and_new_trials_of_a_pair_have_one_canonical_pair() -> None:
    glm = ("codex", "baseten/zai-org/GLM-5.3")
    assert models.canonical("codex-glm", "zai-org/GLM-5.3") == glm  # published folders
    assert models.canonical("codex-glm", "") == glm
    assert models.canonical("codex", "baseten/zai-org/GLM-5.3") == glm  # new folders
    assert models.canonical("mini-swe-agent-glm", "moonshotai/Kimi-K3") == (
        "mini-swe-agent",
        "baseten/moonshotai/Kimi-K3",
    )
    assert models.canonical("codex", "openai/gpt-6-astra") == (
        "codex",
        "gpt-6-astra",
    )  # first party: bare, as published
    assert models.canonical("claude-code", "claude-opus-5-5") == ("claude-code", "claude-opus-5-5")
    assert models.canonical("oracle", "") == ("oracle", "")


def test_model_ids_resolve_to_a_provider_in_benchflow_style() -> None:
    ref = models.resolve("codex", "baseten/zai-org/GLM-5.3")
    assert (ref.provider, ref.bare, ref.id) == ("baseten", "zai-org/GLM-5.3", "baseten/zai-org/GLM-5.3")
    assert models.resolve("claude-code", "claude-opus-5-5").id == "anthropic/claude-opus-5-5"
    assert models.resolve("codex", "gpt-6-astra").id == "openai/gpt-6-astra"
    assert models.resolve("codex", "openrouter/z-ai/glm-5.3").provider == "openrouter"
    with pytest.raises(ValueError, match="provider prefix"):
        models.resolve("mini-swe-agent", "zai-org/GLM-5.3")


def test_image_capability_comes_from_registry_metadata() -> None:
    assert models.accepts_images(models.resolve("codex", "baseten/zai-org/GLM-5.3")) is True
    assert models.max_images(models.resolve("codex", "baseten/zai-org/GLM-5.3")) == 8
    # GLM-5.3-Flash took up to 64 images per request in a probe but miscounted them beyond 16: capped at 8 like GLM-5.3,
    # so a long CLI session never sends it more than 8 per request
    from robouse.harnesses.gateway import image_cap

    flash = models.resolve("claude-code", "baseten/zai-org/GLM-5.3-Flash")
    assert models.accepts_images(flash) is True and models.max_images(flash) == 8
    assert image_cap(flash, True) == 8 and image_cap(flash, False) == 0
    assert models.accepts_images(models.resolve("codex", "zai/glm-5.1")) is False  # BenchFlow lists it as text only
    assert models.accepts_images(models.resolve("codex", "openrouter/some/unknown")) is None
    assert models.accepts_images(models.resolve("claude-code", "claude-opus-5-5")) is True


def test_every_model_gets_every_task_and_the_trial_records_its_image_input(monkeypatch) -> None:
    """No task is closed to a model: the plan only says whether the model gets image input, and why."""
    from robouse.runner.trial import image_input_plan

    p = image_input_plan("codex", "zai/glm-5.1")  # text-only in the registry
    assert (p["image_input"], p["accepts_images"]) == (False, False) and "text-only" in p["image_input_reason"]
    assert image_input_plan("codex", "openrouter/some/unknown")["image_input"] is False  # not described: none
    p = image_input_plan("mini-swe-agent-glm", "")  # the harness never passes images, whatever the model takes
    assert (p["harness"], p["model"], p["image_input"]) == ("mini-swe-agent", "baseten/zai-org/GLM-5.3", False)
    assert "passes no images" in p["image_input_reason"]
    p = image_input_plan("codex-glm", "")  # GLM-5.3 on Baseten reads images
    assert (p["harness"], p["model"], p["image_input"]) == ("codex", "baseten/zai-org/GLM-5.3", True)
    assert image_input_plan("claude-code", "claude-opus-5-5")["image_input"] is True
    assert image_input_plan("oracle", "")["image_input"] is None
    monkeypatch.setenv("ROBOUSE_AGENT_IMAGES", "0")  # an ablation: the gateway removes every image
    assert image_input_plan("codex", "baseten/zai-org/GLM-5.3")["image_input"] is False
    with pytest.raises(ValueError, match="model gateway"):  # a harness on its own vendor has no gateway to do that
        image_input_plan("codex", "gpt-6-astra")


def test_old_trials_record_what_their_model_could_see() -> None:
    assert models.recorded_image_input("codex-glm", {}) is False  # images were turned off for Baseten's endpoint
    assert models.recorded_image_input("mini-swe-agent-glm", {}) is False
    assert models.recorded_image_input("claude-code-glm", {}) is True
    assert models.recorded_image_input("codex", {}) is True
    assert models.recorded_image_input("oracle", {}) is None
    assert models.recorded_image_input("codex", {"image_input": False}) is False  # as recorded, when it is
    assert models.recorded_image_input("codex", {}, {"image_input": False}) is False


def test_gateway_hook_strips_every_image_for_a_text_only_model_in_every_protocol() -> None:
    pytest.importorskip("litellm")
    from robouse.harnesses.providers import gateway_hook as H

    png = "data:image/png;base64,iVBORw0KGgo="
    bodies = {
        "chat": {
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "q"}, {"type": "image_url", "image_url": {"url": png}}],
                }
            ]
        },
        "messages": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "1",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="},
                                }
                            ],
                        }
                    ],
                }
            ]
        },
        "responses": {
            "input": [
                {"type": "function_call_output", "call_id": "1", "output": [{"type": "input_image", "image_url": png}]}
            ]
        },
    }
    for name, body in bodies.items():
        body["alias"] = body.get("messages") or body.get("input")  # the same list twice, as LiteLLM passes it
        assert H.apply_cap(body, 0) == (1, 1), name
        assert H._image_refs(body, []) == [] and "data:image/" not in json.dumps(body), name
    capped = {
        "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": png}}]} for _ in range(9)]
    }
    assert H.apply_cap(capped, 8) == (9, 5) and len(H._image_refs(capped, [])) == 4  # batches of 5, as the old proxy


def test_gateway_hook_passes_a_codex_request_through_except_tool_result_images() -> None:
    """Codex's Responses request reaches the provider as sent: reasoning effort, earlier reasoning items and every tool
    (namespace groups and web_search included) stay; only an image inside a tool result moves to a user message."""
    pytest.importorskip("litellm")
    from robouse.harnesses.providers import gateway_hook as H

    tools = [
        {"type": "function", "name": "exec_command", "parameters": {}},
        {"type": "namespace", "name": "multi_agent_v1", "tools": [{"type": "function", "name": "spawn_agent"}]},
        {"type": "web_search"},
    ]
    reasoning_item = {"type": "reasoning", "id": "rs_1", "summary": [{"type": "summary_text", "text": "plan"}]}
    data = {
        "model": "m",
        "reasoning": {"effort": "medium", "summary": "auto"},
        "include": ["reasoning.encrypted_content"],
        "store": False,
        "tools": json.loads(json.dumps(tools)),
        "input": [
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "go"}]},
            json.loads(json.dumps(reasoning_item)),
            {"type": "function_call", "call_id": "c1", "name": "exec_command", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "c1", "output": "done"},
        ],
    }
    before = json.loads(json.dumps(data))
    out = asyncio.run(H.RobouseGateway().async_pre_call_hook(None, None, data, "aresponses"))
    assert out == before  # nothing to move: the request is unchanged
    assert out["reasoning"] == {"effort": "medium", "summary": "auto"} and out["input"][1] == reasoning_item
    assert out["tools"] == tools


def test_native_route_moves_tool_result_images_into_a_user_message() -> None:
    """Baseten's Responses endpoint rejects an image inside function_call_output; the native Codex route moves it into a
    user message right after the tool result, which that endpoint takes."""
    pytest.importorskip("litellm")
    from robouse.harnesses.providers import gateway_hook as H

    png = "data:image/png;base64,iVBORw0KGgo="
    body = {
        "input": [
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "look"}]},
            {"type": "function_call", "call_id": "c1", "name": "view_image", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "c1", "output": [{"type": "input_image", "image_url": png}]},
            {"type": "function_call", "call_id": "c2", "name": "shell", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "c2", "output": "ok"},
        ]
    }
    alias = body["input"]  # LiteLLM can hold the same list twice
    assert H.move_tool_images(body) == 1 and body["input"] is alias
    kinds = [(i.get("type"), i.get("role")) for i in body["input"]]
    assert kinds == [
        ("message", "user"),
        ("function_call", None),
        ("function_call_output", None),
        ("message", "user"),
        ("function_call", None),
        ("function_call_output", None),
    ]
    tool_out = body["input"][2]["output"]
    assert all(p["type"] != "input_image" for p in tool_out) and H.NOTE_MOVED in json.dumps(tool_out)
    moved = body["input"][3]["content"]
    assert moved[-1] == {"type": "input_image", "image_url": png} and "c1" in moved[0]["text"]
    assert body["input"][5]["output"] == "ok"  # text results untouched
    assert H.move_tool_images({"messages": []}) == 0  # not a Responses body


def test_gateway_spend_cap_counts_usage_and_refuses_requests_past_the_cap(tmp_path, monkeypatch) -> None:
    pytest.importorskip("litellm")
    from fastapi import HTTPException

    from robouse.harnesses.providers import gateway_hook as H

    price = {"input": 1.40, "output": 4.40}
    usage = {
        "prompt_tokens": 1_000_000,
        "completion_tokens": 100_000,
        "prompt_tokens_details": {"cached_tokens": 500_000},
    }
    assert H.usage_cost(usage, price) == pytest.approx(1.40 + 0.44)  # cached input at the input price by default
    assert H.usage_cost(usage, {**price, "cached_input": 0.14}) == pytest.approx(0.70 + 0.07 + 0.44)
    stop = tmp_path / "budget_stop.json"
    monkeypatch.setenv("ROBOUSE_GATEWAY_SPEND_CAP", "3")
    monkeypatch.setenv("ROBOUSE_GATEWAY_PRICE", json.dumps(price))
    monkeypatch.setenv("ROBOUSE_GATEWAY_STOP_FILE", str(stop))
    monkeypatch.setenv("ROBOUSE_GATEWAY_LOG", str(tmp_path / "requests.jsonl"))
    hook = H.RobouseGateway()

    class Resp:
        def __init__(self, u):
            self.usage = u

    for _ in range(2):  # $1.84 each: under the cap after one, over it after two
        asyncio.run(hook.async_pre_call_hook(None, None, {"model": "m", "messages": []}, "acompletion"))
        asyncio.run(hook.async_log_success_event({}, Resp(usage), 0, 0))
    rec = json.loads(stop.read_text())
    assert rec["cap_usd"] == 3 and rec["spent_usd"] == pytest.approx(3.68)
    with pytest.raises(HTTPException) as e:
        asyncio.run(hook.async_pre_call_hook(None, None, {"model": "m", "messages": []}, "acompletion"))
    assert e.value.status_code == 402 and "spend cap" in str(e.value.detail)
    from robouse.harnesses.gateway import summarize

    s = summarize(tmp_path / "requests.jsonl")
    assert (s["requests"], s["refused_over_cap"], s["spent_usd"]) == (2, 1, pytest.approx(3.68))
