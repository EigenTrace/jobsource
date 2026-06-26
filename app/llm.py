"""DeepSeek client (OpenAI-compatible).

Exposes a single `llm` singleton. When no API key is configured, `llm.available`
is False and `complete_json` returns None, so every caller can fall back to
heuristics. All LLM calls request strict JSON and parse defensively.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from .config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self) -> None:
        self._client = None
        if settings.has_deepseek:
            try:
                from openai import OpenAI

                self._client = OpenAI(
                    api_key=settings.deepseek_api_key,
                    base_url=settings.deepseek_base_url,
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Failed to init DeepSeek client: %s", exc)
                self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> Optional[dict[str, Any]]:
        """Return a parsed JSON object, or None if unavailable / unparseable."""
        if not self._client:
            return None
        try:
            resp = self._client.chat.completions.create(
                model=settings.deepseek_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = resp.choices[0].message.content or ""
            return _safe_json(content)
        except Exception as exc:  # pragma: no cover - network/runtime
            logger.warning("DeepSeek call failed, falling back to heuristics: %s", exc)
            return None


def _safe_json(text: str) -> Optional[dict[str, Any]]:
    text = text.strip()
    # Strip ```json fences if the model added them.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {"value": obj}
    except json.JSONDecodeError:
        # Last resort: grab the outermost {...} block.
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


llm = LLMClient()
