"""Model ids, providers and model capabilities, in BenchFlow's conventions.

A model id is provider-prefixed, as in BenchFlow: `baseten/zai-org/GLM-5.3`, `openrouter/<org>/<model>`,
`anthropic/claude-opus-5-5`, `openai/gpt-6-astra`. The provider part names an entry in BenchFlow's provider registry
(`benchflow.agents.providers.PROVIDERS`); Robo Use keeps no registry of its own. Until BenchFlow ships the `baseten`
entry, `PENDING_PROVIDERS` holds it here in BenchFlow's own `ProviderConfig` shape, and `provider_registry()` adds it.

A bare id keeps working: `claude-*` is Anthropic's, `gpt-*`/`o<n>` OpenAI's, and a bare `org/model` id given with a
legacy `-glm` harness is Baseten's (`legacy()`).

Capabilities come from the registry's model metadata (`models[].input`, BenchFlow's field: ["text"] or
["text", "image"]). `accepts_images()` answers True, False or None (unknown).
"""

from __future__ import annotations

from dataclasses import dataclass

# Legacy harness names: hidden aliases for (harness, provider). Old trial folders and URLs keep these names.
LEGACY_HARNESSES = {
    "claude-code-glm": ("claude-code", "baseten"),
    "codex-glm": ("codex", "baseten"),
    "mini-swe-agent-glm": ("mini-swe-agent", "baseten"),
}
LEGACY_DEFAULT_MODEL = "zai-org/GLM-5.3"

# First-party providers every harness knows natively (their own subscription or API key), and whose models take images.
NATIVE_VENDORS = {"claude-code": "anthropic", "codex": "openai"}
FIRST_PARTY_IMAGE_PROVIDERS = {"anthropic", "openai"}

# Proposed for BenchFlow's registry (src/benchflow/agents/providers.py). Verified on 2026-09-30 against
# inference.baseten.co: all three protocols answer, and both models below read an image on each of them
# (scratch/provider-spike/evidence/image-probe2.jsonl). maxImages: the Messages endpoint rejects a request with more
# than 8 images. Baseten's Responses endpoint rejects an image inside a tool result (function_call_output); see
# `gateway.py` for how the gateway routes Codex around it.
BASETEN_URL = "https://inference.baseten.co/v1"
PENDING_PROVIDERS: dict[str, dict] = {
    "baseten": {
        "name": "baseten",
        "base_url": BASETEN_URL,
        "api_protocol": "openai-completions",
        "auth_type": "api_key",
        "auth_env": "BASETEN_API_KEY",
        "endpoints": {
            "openai-completions": BASETEN_URL,
            "openai-responses": BASETEN_URL,
            "anthropic-messages": "https://inference.baseten.co",
        },
        "models": [
            {"id": "zai-org/GLM-5.3", "name": "GLM-5.3", "reasoning": True, "input": ["text", "image"], "maxImages": 8},
            {"id": "moonshotai/Kimi-K3", "name": "Kimi K3", "reasoning": True, "input": ["text", "image"], "maxImages": 8},
        ],
    }
}


def provider_registry() -> dict:
    """BenchFlow's provider registry plus the entries pending upstream. Needs the `benchflow` extra."""
    try:
        from benchflow.agents.providers import PROVIDERS, ProviderConfig
    except ImportError as e:  # pragma: no cover - depends on the install
        raise RuntimeError(
            "provider-routed models need BenchFlow's provider registry: pip install 'robouse[llm]'"
        ) from e
    for name, fields in PENDING_PROVIDERS.items():
        PROVIDERS.setdefault(name, ProviderConfig(**fields))
    return PROVIDERS


@dataclass(frozen=True)
class ModelRef:
    """One resolved model: `provider/bare` (the id recorded in config.json), and its registry metadata."""

    provider: str  # registry name, or "anthropic"/"openai" for first-party ids
    bare: str  # the id the provider knows, e.g. zai-org/GLM-5.3
    meta: dict

    @property
    def id(self) -> str:
        return f"{self.provider}/{self.bare}"


def split(model: str) -> tuple[str | None, str]:
    """('baseten', 'zai-org/GLM-5.3') for 'baseten/zai-org/GLM-5.3'; (None, model) when there is no known provider."""
    head, _, rest = model.partition("/")
    if rest and (head in FIRST_PARTY_IMAGE_PROVIDERS or head in PENDING_PROVIDERS or _registered(head)):
        return head, rest
    return None, model


def _registered(name: str) -> bool:
    try:
        return name in provider_registry()
    except RuntimeError:
        return False


def resolve(harness: str, model: str) -> ModelRef:
    """The provider-prefixed model for a (canonical harness, model) pair. A bare id goes to the harness's own vendor."""
    provider, bare = split(model)
    if provider is None:
        if harness in NATIVE_VENDORS:
            provider = NATIVE_VENDORS[harness]
        else:
            raise ValueError(f"model {model!r} needs a provider prefix, e.g. baseten/{model} or openrouter/{model}")
    meta: dict = {}
    if provider not in FIRST_PARTY_IMAGE_PROVIDERS:
        cfg = provider_registry()[provider]
        meta = next((m for m in cfg.models if str(m.get("id", "")).lower() == bare.lower()), {})
    return ModelRef(provider, bare, meta)


def legacy(harness: str, model: str) -> tuple[str, str]:
    """(canonical harness, provider-prefixed model) for a legacy harness name; other names pass through."""
    if harness not in LEGACY_HARNESSES:
        return harness, model
    canon, provider = LEGACY_HARNESSES[harness]
    m = model or LEGACY_DEFAULT_MODEL
    return canon, m if split(m)[0] else f"{provider}/{m}"


def accepts_images(ref: ModelRef) -> bool | None:
    """True/False from the registry's `input` metadata; first-party Anthropic and OpenAI models take images; None if
    the registry does not say."""
    if ref.provider in FIRST_PARTY_IMAGE_PROVIDERS:
        return True
    inputs = ref.meta.get("input")
    return None if inputs is None else "image" in inputs


def max_images(ref: ModelRef) -> int:
    """Images per request the endpoint takes (0: no limit declared)."""
    return int(ref.meta.get("maxImages") or 0)
