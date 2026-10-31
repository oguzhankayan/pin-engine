"""Claude for pin copy and image checks. Replies are strict JSON; spend is logged per call."""
from __future__ import annotations

import base64
import json
import re
import time

from .config import DATA_DIR, settings

SPEND_LOG = DATA_DIR / "anthropic_spend.jsonl"
# USD per million tokens (Claude Sonnet 5.5 and Haiku 5.5 list prices, October 2026).
RATES = {"claude-sonnet-5-5": (2.00, 10.00), "claude-haiku-5-5": (0.10, 0.50)}


def _client():
    settings.require("anthropic_api_key")
    from anthropic import Anthropic
    return Anthropic(api_key=settings.anthropic_api_key)


def _record(usage, kind: str) -> None:
    rate_in, rate_out = RATES.get(settings.anthropic_model, (2.00, 10.00))
    tokens_in, tokens_out = getattr(usage, "input_tokens", 0) or 0, getattr(usage, "output_tokens", 0) or 0
    SPEND_LOG.parent.mkdir(parents=True, exist_ok=True)
    with SPEND_LOG.open("a") as handle:
        handle.write(json.dumps({"time": int(time.time()), "model": settings.anthropic_model, "kind": kind,
                                 "input_tokens": tokens_in, "output_tokens": tokens_out,
                                 "usd": round((tokens_in * rate_in + tokens_out * rate_out) / 1e6, 6)}) + "\n")


def parse_json(text: str):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except ValueError:
        match = re.search(r"(\{.*\}|\[.*\])", text, re.S)
        if not match:
            raise
        return json.loads(match.group(1))


def ask_json(system: str, content: list[dict] | str, kind: str, max_tokens: int = 8000):
    response = _client().messages.create(model=settings.anthropic_model, max_tokens=max_tokens, system=system,
                                         messages=[{"role": "user", "content": content}])
    _record(response.usage, kind)
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined this request.")
    text = "".join(block.text for block in response.content if block.type == "text")
    return parse_json(text)


def image_block(data: bytes, media_type: str = "image/jpeg") -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                        "data": base64.standard_b64encode(data).decode()}}


def total_spend() -> float:
    if not SPEND_LOG.exists():
        return 0.0
    return round(sum(json.loads(line).get("usd", 0) for line in SPEND_LOG.read_text().splitlines() if line.strip()), 4)
