"""
LLM 客户端 - OpenAI 兼容协议
DeepSeek: https://api.deepseek.com/v1/chat/completions
         model: deepseek-chat
支持: DeepSeek / OpenAI / Ollama (OpenAI 兼容) / 任何兼容协议
"""
from __future__ import annotations
import json
import logging
from typing import Any
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.settings import settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    pass


class LLMClient:
    """OpenAI 兼容 Chat Completion 客户端"""

    def __init__(self,
                 api_key: str | None = None,
                 base_url: str | None = None,
                 model: str | None = None,
                 timeout_s: int | None = None):
        self.api_key = api_key or settings.llm_api_key
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.model = model or settings.llm_model
        self.timeout_s = timeout_s or settings.llm_timeout_s

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, LLMError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def complete(self,
                 messages: list[dict[str, str]],
                 *,
                 temperature: float = 0.3,
                 max_tokens: int = 2000,
                 response_format_json: bool = True,
                 ) -> str:
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        # DeepSeek 支持 response_format: {"type": "json_object"}
        if response_format_json and self.model.startswith("deepseek"):
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=self.timeout_s) as client:
            resp = client.post(url, json=payload, headers=headers)

        if resp.status_code != 200:
            raise LLMError(f"LLM HTTP {resp.status_code}: {resp.text[:500]}")

        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"unexpected LLM response: {data}") from e
