from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class OpenAICompatClient:
    base_url: str
    api_key: str | None
    timeout: int = 300

    def chat(self, model: str, messages: list[dict[str, Any]], temperature: float) -> str:
        if not self.base_url:
            raise RuntimeError("IMAGE2PPT_VISION_BASE_URL is required")
        url = self.base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            # "max_tokens": 8192,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        if resp.status_code >= 400:
            raise RuntimeError(f"OpenAI-compatible API error: {resp.status_code} {resp.text[:200]}")
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"OpenAI-compatible API missing choices: {json.dumps(data)[:200]}")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            parts = [item.get("text", "") for item in content if item.get("type") == "text"]
            content = "".join(parts).strip()
        if not content:
            raise RuntimeError(f"OpenAI-compatible API empty content: {json.dumps(data)[:200]}")
        return str(content)
