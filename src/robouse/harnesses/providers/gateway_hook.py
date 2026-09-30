"""LiteLLM proxy hook for Robo Use's model gateway. Copied next to the proxy's config.yaml and loaded by LiteLLM, so it
imports nothing from robouse.

Before each request (any protocol: chat completions, Responses, Anthropic Messages) it applies the model's image
capability, read from ROBOUSE_GATEWAY_MAX_IMAGES:
  0   text-only model: every image part is replaced by a text note
  N   at most N images per request: the oldest are replaced, in batches of 5 so the prompt prefix (and the provider's
      prompt cache) stays the same for several turns (the rule of the earlier Baseten proxy)
  -1  no limit
Right before the upstream call it counts the image parts that actually leave the gateway, and appends one line per
request to $ROBOUSE_GATEWAY_LOG (JSON: call type, images in, removed, sent upstream). No request content is logged.
"""

from __future__ import annotations

import json
import os
import time

from litellm.integrations.custom_logger import CustomLogger

IMAGE_TYPES = {"image": "text", "image_url": "text", "input_image": "input_text"}
NOTE_TEXT_ONLY = "[image removed: this model does not take image input]"
NOTE_CAPPED = "[older image removed: the model endpoint takes at most {n} images per request]"
BATCH = 5


def _image_refs(node, out: list, seen: set | None = None) -> list:
    """(container, index) of every image part, in document order (= conversation order). A request body can hold the
    same list object twice (LiteLLM keeps a reference to the original body); each part is counted once."""
    seen = set() if seen is None else seen
    if isinstance(node, list):
        if id(node) in seen:
            return out
        seen.add(id(node))
        for i, v in enumerate(node):
            if isinstance(v, dict) and v.get("type") in IMAGE_TYPES:
                out.append((node, i))
            else:
                _image_refs(v, out, seen)
    elif isinstance(node, dict):
        if id(node) in seen:
            return out
        seen.add(id(node))
        for v in node.values():
            _image_refs(v, out, seen)
    return out


def _data_uris(node) -> int:
    """Base64 images anywhere in the payload, whatever part type carries them (a second, type-blind count)."""
    s = json.dumps(node, default=str)
    return s.count("data:image/") + s.count('"media_type": "image/')


def removed_count(n: int, cap: int) -> int:
    if cap < 0 or n == 0:
        return 0
    if cap == 0:
        return n
    if n <= cap:
        return 0
    return min(n, BATCH * ((n - (cap - BATCH + 1)) // BATCH)) if cap >= BATCH else n - cap


def apply_cap(body: dict, cap: int) -> tuple[int, int]:
    refs = _image_refs(body, [])
    k = removed_count(len(refs), cap)
    note = NOTE_TEXT_ONLY if cap == 0 else NOTE_CAPPED.format(n=cap)
    for lst, i in refs[:k]:
        lst[i] = {"type": IMAGE_TYPES[lst[i]["type"]], "text": note}
    return len(refs), k


def _log(rec: dict) -> None:
    path = os.environ.get("ROBOUSE_GATEWAY_LOG")
    if path:
        with open(path, "a") as f:
            f.write(json.dumps({"t": round(time.time(), 3), **rec}) + "\n")


class RobouseGateway(CustomLogger):
    def __init__(self) -> None:
        super().__init__()
        self.cap = int(os.environ.get("ROBOUSE_GATEWAY_MAX_IMAGES", "-1"))

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        n, k = apply_cap(data, self.cap)
        bearer = os.environ.get("ROBOUSE_GATEWAY_BEARER_ENV")
        if bearer and os.environ.get(bearer):  # providers whose Anthropic endpoint wants a Bearer token, not x-api-key
            data["extra_headers"] = {**(data.get("extra_headers") or {}), "Authorization": f"Bearer {os.environ[bearer]}"}
        _log({"event": "request", "call_type": str(call_type), "images_in": n, "images_removed": k})
        return data

    def log_pre_api_call(self, model, messages, kwargs):
        payload = {"messages": messages, "input": (kwargs.get("optional_params") or {}).get("input")}
        extra = (kwargs.get("additional_args") or {}).get("complete_input_dict")
        _log(
            {
                "event": "upstream",
                "model": str(model),
                # the same request as LiteLLM's messages and as the raw provider body: the larger count of the two
                "image_parts": max(len(_image_refs(payload, [])), len(_image_refs(extra, [])) if extra else 0),
                "data_uris": max(_data_uris(payload), _data_uris(extra) if extra else 0),
            }
        )

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        usage = getattr(response_obj, "usage", None)
        _log({"event": "success", "usage": usage.model_dump() if hasattr(usage, "model_dump") else str(usage)})

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        _log({"event": "failure", "error": str(kwargs.get("exception", ""))[:400]})


proxy_handler_instance = RobouseGateway()
