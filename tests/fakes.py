"""A dependency-free backend for testing the episode server: a point hand that moves toward a goal."""

from __future__ import annotations

import numpy as np

from robouse.backends.base import ActionSpec, Backend, StepInfo


class FakeBackend(Backend):
    name = "fake"
    camera = "front"

    def __init__(self, spec: dict):
        super().__init__(spec)
        self.action_spec = ActionSpec(["dx", "dy", "dz", "grip"], [-1.0] * 4, [1.0] * 4, "move the hand 1 cm per unit")
        self.max_steps = int(spec.get("max_steps", 50))
        self.goal = np.asarray(spec.get("goal", [0.05, 0.0, 0.0]), dtype=float)
        self.halted: str | None = None
        self.last_judge = None

    def reset(self, seed: int) -> None:
        self.pos = np.zeros(3)
        self._grip = -1.0
        self.seed = seed

    def step(self, action) -> StepInfo:
        a = self.action_spec.clip(action)
        self.pos = self.pos + 0.01 * np.asarray(a[:3], dtype=float)
        self._grip = float(a[3])
        return StepInfo(success=self.success())

    def observe(self) -> dict:
        return {
            "hand_pos": [round(float(x), 4) for x in self.pos],
            "gripper_open": self._grip < 0,
            "goal": list(self.goal),
        }

    def render(self) -> np.ndarray:
        img = np.zeros((32, 48, 3), dtype=np.uint8)
        img[..., 0] = min(255, int(self.pos[0] * 1000))
        return img

    def success(self) -> bool:
        return bool(np.linalg.norm(self.pos - self.goal) < 0.011)

    def hand_pos(self) -> np.ndarray:
        return self.pos.copy()

    def skills(self) -> list[str]:
        return ["move_to", "grip", "wiggle"]

    def start_skill(self, name: str, args: list[str]):
        if name != "wiggle":
            raise ValueError(f"unknown skill {name!r}")
        n = int(args[0]) if args else 2

        def gen():
            for i in range(n):
                yield [1.0 if i % 2 == 0 else -1.0, 0.0, 0.0, self._grip]
            return {"wiggled": n}

        return gen()

    def privileged_state(self) -> dict:
        return {"secret": 42}


def glm_registry() -> dict:
    """A provider registry stand-in with BenchFlow's `glm` entry, as BenchFlow 0.7.9.dev2354 has it (GLM-5.3 on the
    Z.ai Coding Plan: key in GLM_API_KEY, endpoint in GLM_BASE_URL, chat completions only, no model metadata for
    glm-5.3), so a test runs without the llm extra."""
    from types import SimpleNamespace

    url = "{base_url}"
    glm = SimpleNamespace(
        name="glm",
        base_url=url,
        api_protocol="openai-completions",
        auth_type="api_key",
        auth_env="GLM_API_KEY",
        url_params={"base_url": "GLM_BASE_URL"},
        url_param_defaults={},
        models=[],
        model_prefixes=["glm"],
        endpoints={},
        all_endpoints={"openai-completions": url},
    )
    return {"glm": glm}
