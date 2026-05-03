from __future__ import annotations

import json
import time
from typing import Type

import httpx
from pydantic import BaseModel, ValidationError


class JSONParseError(Exception):
    pass


def _extract_json(text: str) -> str:
    t = (text or "").strip()
    if not t:
        raise JSONParseError("empty")
    # If model wrapped JSON in text, try to isolate first { ... } block.
    if t[0] != "{":
        start = t.find("{")
        end = t.rfind("}")
        if start >= 0 and end > start:
            t = t[start : end + 1]
    return t


async def call_and_parse_json(
    *,
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    payload: dict,
    out_model: Type[BaseModel],
    timeout_s: float = 20.0,
    retry_once: bool = True,
) -> BaseModel:
    """Call provider endpoint and parse JSON into pydantic model. Retries once on invalid JSON."""

    last_err: Exception | None = None
    for attempt in range(2 if retry_once else 1):
        try:
            t0 = time.time()
            resp = await client.post(url, headers=headers, json=payload, timeout=timeout_s)
            _ = time.time() - t0
            resp.raise_for_status()
            data = resp.json()
            # Provider adapters can pass raw content or already-extracted JSON.
            if isinstance(data, dict) and "output_text" in data:
                raw = data["output_text"]
            else:
                raw = data
            if isinstance(raw, dict):
                return out_model.model_validate(raw)
            if isinstance(raw, str):
                js = json.loads(_extract_json(raw))
                return out_model.model_validate(js)
            raise JSONParseError("unexpected_response_shape")
        except (httpx.HTTPError, json.JSONDecodeError, JSONParseError, ValidationError) as e:
            last_err = e
            if attempt == 0 and retry_once:
                continue
            break
    raise JSONParseError(str(last_err) if last_err else "parse_failed")

