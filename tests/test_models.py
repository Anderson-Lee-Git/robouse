"""Model ids, providers and image capability: naming, legacy aliases, eligibility, the episode server's image switch and
the gateway's image rule. The central regression: a model that gets no images never receives an image path, file or
image part on a vision task."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from robouse.harnesses import models
from robouse.tasks import Task

pytest.importorskip("benchflow")


def _task(obs_mode: str = "state") -> Task:
    return Task(Path("/nonexistent"), {"robouse": {"id": f"t-{obs_mode}", "backend": "fake", "obs_mode": obs_mode}}, "")


def test_legacy_harness_names_are_aliases_with_a_baseten_model() -> None:
    assert models.legacy("codex-glm", "") == ("codex", "baseten/zai-org/GLM-5.3")
    assert models.legacy("claude-code-glm", "moonshotai/Kimi-K3") == ("claude-code", "baseten/moonshotai/Kimi-K3")
    assert models.legacy("mini-swe-agent-glm", "baseten/zai-org/GLM-5.3") == (
        "mini-swe-agent",
        "baseten/zai-org/GLM-5.3",
    )
    assert models.legacy("codex", "gpt-6-astra") == ("codex", "gpt-6-astra")


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
    assert models.accepts_images(models.resolve("codex", "zai/glm-5.1")) is False  # BenchFlow lists it as text only
    assert models.accepts_images(models.resolve("codex", "openrouter/some/unknown")) is None
    assert models.accepts_images(models.resolve("claude-code", "claude-opus-5-5")) is True


def test_vision_tasks_are_ineligible_for_a_model_that_gets_no_images(monkeypatch) -> None:
    from robouse.runner.trial import Ineligible, image_plan

    with pytest.raises(Ineligible, match="vision task"):
        image_plan(_task("vision"), "codex", "zai/glm-5.1")  # text-only
    with pytest.raises(Ineligible):
        image_plan(_task("vision"), "codex", "openrouter/some/unknown")  # capability unknown: treated as text-only
    assert image_plan(_task("state"), "codex", "zai/glm-5.1")["images"] is False
    assert image_plan(_task("vision"), "codex-glm", "")["images"] is True  # GLM-5.3 on Baseten reads images
    assert image_plan(_task("vision"), "oracle", "")["images"] is True
    monkeypatch.setenv("ROBOUSE_AGENT_IMAGES", "0")  # the published GLM-5.3 · Codex condition
    assert image_plan(_task("state"), "codex-glm", "")["images"] is False
    with pytest.raises(Ineligible):
        image_plan(_task("vision"), "codex-glm", "")
    monkeypatch.setenv("ROBOUSE_RUN_INELIGIBLE", "1")
    assert image_plan(_task("vision"), "codex-glm", "")["images"] is False


def test_a_model_without_images_never_gets_an_image_path_on_a_vision_task(tmp_path, monkeypatch) -> None:
    """Server side: whatever the agent asks for, no image is rendered for it and no path or file reaches it."""
    pytest.importorskip("imageio")
    from fakes import FakeBackend

    from robouse.core import session as S

    monkeypatch.setattr(S, "make_backend", FakeBackend)
    monkeypatch.setattr(FakeBackend, "workspace_images", lambda self: {"example_1.png": __import__("numpy").zeros((4, 4, 3))}, raising=False)
    ws = tmp_path / "ws"
    spec = {"id": "t", "backend": "fake", "obs_mode": "vision", "visible_fields": ["hand_pos"], "agent_images": False}
    ep = S.Episode(spec, tmp_path / "run", ws)
    assert ep.handle({"op": "info"})["result"]["images"] is False
    for req in ({"op": "observe"}, {"op": "observe", "image": True}, {"op": "observe", "image": True, "camera": "front"}):
        r = ep.handle(req)["result"]
        assert "image_path" not in r and "not available" in r["images"]
        assert ".png" not in json.dumps(r)
    ep.close()
    assert not list(ws.rglob("*.png"))  # nothing an agent could open, list or have auto-attached
    assert "image_path" not in (tmp_path / "run" / "trace.jsonl").read_text()
    # the same task with images on still gets them
    ep2 = S.Episode({**spec, "agent_images": True}, tmp_path / "run2", tmp_path / "ws2")
    assert "image_path" in ep2.handle({"op": "observe"})["result"]
    ep2.close()


def test_gateway_hook_strips_every_image_for_a_text_only_model_in_every_protocol() -> None:
    pytest.importorskip("litellm")
    from robouse.harnesses.providers import gateway_hook as H

    png = "data:image/png;base64,iVBORw0KGgo="
    bodies = {
        "chat": {"messages": [{"role": "user", "content": [{"type": "text", "text": "q"}, {"type": "image_url", "image_url": {"url": png}}]}]},
        "messages": {"messages": [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "1", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}}]}]}]},
        "responses": {"input": [{"type": "function_call_output", "call_id": "1", "output": [{"type": "input_image", "image_url": png}]}]},
    }
    for name, body in bodies.items():
        body["alias"] = body.get("messages") or body.get("input")  # the same list twice, as LiteLLM passes it
        assert H.apply_cap(body, 0) == (1, 1), name
        assert H._image_refs(body, []) == [] and "data:image/" not in json.dumps(body), name
    capped = {"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": png}}]} for _ in range(9)]}
    assert H.apply_cap(capped, 8) == (9, 5) and len(H._image_refs(capped, [])) == 4  # batches of 5, as the old proxy
