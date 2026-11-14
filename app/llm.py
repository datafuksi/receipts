"""Client for the OpenAI-compatible AI router.

Rules: temperature 0, JSON output validated against a schema, one retry on a
parse failure, then an explicit failure. A refusal or an outage is surfaced as
an error state; prompts are never reworded to get around a refusal.
"""
import re
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .config import Settings, get_settings

T = TypeVar("T", bound=BaseModel)

HTTP_STATUS = {
    "not_configured": 503,
    "router_unavailable": 502,
    "refused": 422,
    "analysis_failed": 502,
}


class LLMError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def _strip_fences(text: str) -> str:
    m = _FENCE.match(text)
    return m.group(1) if m else text.strip()


async def _post_chat(payload: dict, s: Settings) -> dict:
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(
                f"{s.router_base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {s.router_api_key}"},
            )
    except httpx.HTTPError:
        raise LLMError("router_unavailable", "The AI service could not be reached. Try again shortly.")
    if r.status_code >= 400:
        raise LLMError("router_unavailable", f"The AI service returned HTTP {r.status_code}.")
    try:
        return r.json()
    except ValueError:
        raise LLMError("router_unavailable", "The AI service returned an unreadable response.")


async def chat_json(system: str, user: str, schema: type[T], max_tokens: int = 2000) -> T:
    s = get_settings()
    if not s.router_api_key or not s.router_model:
        raise LLMError("not_configured", "The AI service is not configured on this server.")
    payload = {
        "model": s.router_model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    for _attempt in range(2):  # first try + exactly one retry on parse failure
        data = await _post_chat(payload, s)
        try:
            choice = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError):
            continue
        if message.get("refusal") or choice.get("finish_reason") == "content_filter":
            raise LLMError("refused", "The AI service declined to process this text.")
        try:
            return schema.model_validate_json(_strip_fences(message.get("content") or ""))
        except ValidationError:
            continue
    raise LLMError("analysis_failed", "Analysis failed: the AI service did not return a valid result.")
