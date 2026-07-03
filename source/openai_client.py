from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class OpenAICompatClient:
    base_url: str
    timeout: int | tuple[int, int] = (5, 300)

    def chat(self, messages: list[dict[str, Any]], temperature: float, **kwargs) -> str:
        """
        支持通过 kwargs 透传高级参数 (如 top_p, max_tokens, response_format 等)
        """
        if not self.base_url:
            raise RuntimeError("IMAGE2PPT_VISION_BASE_URL is required")
        headers = {"Content-Type": "application/json"}
        
        # 基础 payload
        payload = {
            "messages": messages,
            "temperature": temperature,
        }
        
        # 动态将外部传入的高级参数混入 payload 中
        if kwargs:
            payload.update(kwargs)
            
        resp = requests.post(self.base_url, headers=headers, json=payload, timeout=self.timeout)
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