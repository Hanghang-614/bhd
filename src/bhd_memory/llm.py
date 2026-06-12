from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen


class LLMNotConfigured(RuntimeError):
    pass


@dataclass(frozen=True)
class OpenAICompatibleClient:
    base_url: str
    model: str
    api_key: str | None = None
    timeout: int = 60

    @classmethod
    def from_env(cls) -> "OpenAICompatibleClient":
        base_url = os.environ.get("BHD_LLM_BASE_URL", "").rstrip("/")
        model = os.environ.get("BHD_LLM_MODEL", "")
        if not base_url or not model:
            raise LLMNotConfigured("BHD_LLM_BASE_URL and BHD_LLM_MODEL are required")
        return cls(
            base_url=base_url,
            model=model,
            api_key=os.environ.get("BHD_LLM_API_KEY") or None,
            timeout=int(os.environ.get("BHD_LLM_TIMEOUT", "60")),
        )

    def chat_json(self, messages: list[dict[str, str]], *, temperature: float = 0.0) -> Any:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        request = Request(f"{self.base_url}/chat/completions", data=data, headers=headers)
        with urlopen(request, timeout=self.timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        return parse_json_content(content)


def parse_json_content(content: str) -> Any:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*(.*?)```", content, flags=re.DOTALL)
    if match:
        return json.loads(match.group(1))
    start = min((idx for idx in [content.find("{"), content.find("[")] if idx >= 0), default=-1)
    if start >= 0:
        end = max(content.rfind("}"), content.rfind("]"))
        if end >= start:
            return json.loads(content[start : end + 1])
    raise ValueError("LLM response did not contain JSON")

