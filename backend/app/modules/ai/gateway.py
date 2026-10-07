"""Gateway to any OpenAI-compatible API (Ollama, vLLM, Yandex AI Studio…).

One place for timeouts, auth headers, the data-residency guard, streaming and token accounting, so modules
never talk to a model directly. Tests inject an ``httpx`` transport.
"""

from __future__ import annotations

import ipaddress
import json
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog

from app.core.config import Settings, get_settings
from app.core.errors import FeatureDisabled, UpstreamError

log = structlog.get_logger("ai")
THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
LOCAL_HOSTS = {"localhost", "ollama", "vllm", "host.docker.internal"}


@dataclass
class ChatResult:
    text: str
    model: str
    latency_ms: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


def is_local(url: str) -> bool:
    host = urlparse(url).hostname or ""
    if host in LOCAL_HOSTS or host.endswith(".local") or host.endswith(".svc") or "." not in host:
        return True
    try:
        return ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def strip_think(text: str) -> str:
    """Removes the reasoning block of Qwen3/DeepSeek-style models (also an unterminated one, or one whose
    opening tag the provider already dropped)."""
    text = THINK_RE.sub("", text)
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    if "<think>" in text:
        text = text.split("<think>", 1)[0]
    return text.strip()


class AiGateway:
    def __init__(self, settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.s = settings or get_settings()
        self.transport = transport

    # ------------------------------------------------------------------ config
    @property
    def enabled(self) -> bool:
        return self.s.ai_enabled

    @property
    def cloud(self) -> bool:
        return not is_local(self.s.ai_base_url)

    def check(self) -> None:
        if not self.s.ai_enabled:
            raise FeatureDisabled("ИИ-ассистент выключен (AI_ENABLED=false). См. docs/ai-setup.md")
        if self.cloud and not self.s.ai_allow_cloud:
            raise FeatureDisabled("Облачный провайдер ИИ запрещён настройкой AI_ALLOW_CLOUD=false")

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.s.ai_api_key:
            h["Authorization"] = f"{self.s.ai_auth_scheme} {self.s.ai_api_key.get_secret_value()}"
        if self.s.ai_project_header and self.s.ai_project_id:
            h[self.s.ai_project_header] = self.s.ai_project_id
        return h

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.s.ai_base_url.rstrip("/") + "/",
            headers=self._headers(),
            timeout=httpx.Timeout(self.s.ai_timeout_s, connect=10),
            transport=self.transport,
        )

    def _body(self, messages: list[dict[str, str]], model: str | None, stream: bool, **kw: Any) -> dict[str, Any]:
        model = model or self.s.ai_chat_model
        msgs = [dict(m) for m in messages]
        if self.s.ai_no_think and kw.pop("no_think", True) and "qwen3" in model.lower() and msgs:
            msgs[-1]["content"] = msgs[-1]["content"] + "\n/no_think"
        kw.pop("no_think", None)
        return {
            "model": model,
            "messages": msgs,
            "temperature": kw.pop("temperature", self.s.ai_temperature),
            "max_tokens": kw.pop("max_tokens", self.s.ai_max_tokens),
            "stream": stream,
            **self.s.ai_extra_body,
            **kw,
        }

    # ------------------------------------------------------------------ calls
    async def chat(self, messages: list[dict[str, str]], model: str | None = None, **kw: Any) -> ChatResult:
        self.check()
        body = self._body(messages, model, False, **kw)
        started = time.perf_counter()
        try:
            async with self._client() as c:
                r = await c.post("chat/completions", json=body)
        except httpx.HTTPError as exc:
            raise UpstreamError(f"Модель недоступна: {exc.__class__.__name__}") from exc
        if r.status_code >= 400:
            raise UpstreamError(f"Модель вернула ошибку {r.status_code}", details={"body": r.text[:500]})
        data = r.json()
        usage = data.get("usage") or {}
        choice = data["choices"][0]
        text = strip_think(choice["message"].get("content") or "")
        if not text and choice.get("finish_reason") == "length":
            raise UpstreamError(
                f"Модель израсходовала лимит {body['max_tokens']} токенов на рассуждения и не успела ответить. "
                "Увеличьте AI_MAX_TOKENS или отключите рассуждения через AI_EXTRA_BODY (docs/ai-setup.md)"
            )
        return ChatResult(
            text=text,
            model=data.get("model") or body["model"],
            latency_ms=(time.perf_counter() - started) * 1000,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            raw=data,
        )

    async def stream(self, messages: list[dict[str, str]], model: str | None = None, **kw: Any) -> AsyncIterator[str]:
        """Yields text deltas (reasoning blocks filtered out)."""
        self.check()
        body = self._body(messages, model, True, **kw)
        in_think = False
        try:
            async with self._client() as c, c.stream("POST", "chat/completions", json=body) as r:
                if r.status_code >= 400:
                    await r.aread()
                    raise UpstreamError(f"Модель вернула ошибку {r.status_code}", details={"body": r.text[:500]})
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        delta = json.loads(payload)["choices"][0].get("delta", {}).get("content") or ""
                    except (ValueError, KeyError, IndexError):
                        continue
                    while delta:
                        if in_think:
                            end = delta.find("</think>")
                            if end < 0:
                                delta = ""
                            else:
                                in_think, delta = False, delta[end + 8 :].lstrip()
                        else:
                            start = delta.find("<think>")
                            if start < 0:
                                yield delta
                                delta = ""
                            else:
                                if start:
                                    yield delta[:start]
                                in_think, delta = True, delta[start + 7 :]
        except httpx.HTTPError as exc:
            raise UpstreamError(f"Модель недоступна: {exc.__class__.__name__}") from exc

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.check()
        if not self.s.ai_embedding_model:
            raise FeatureDisabled("Модель эмбеддингов не настроена (AI_EMBEDDING_MODEL)")
        out: list[list[float]] = []
        try:
            async with self._client() as c:
                for i in range(0, len(texts), 32):
                    r = await c.post(
                        "embeddings", json={"model": self.s.ai_embedding_model, "input": texts[i : i + 32]}
                    )
                    if r.status_code >= 400:
                        raise UpstreamError(f"Эмбеддинги: ошибка {r.status_code}", details={"body": r.text[:500]})
                    data = sorted(r.json()["data"], key=lambda d: d.get("index", 0))
                    out.extend(d["embedding"] for d in data)
        except httpx.HTTPError as exc:
            raise UpstreamError(f"Модель эмбеддингов недоступна: {exc.__class__.__name__}") from exc
        return out

    async def ping(self) -> tuple[bool, str]:
        try:
            await self.chat([{"role": "user", "content": "ping"}], max_tokens=5)
            return True, ""
        except Exception as exc:
            return False, getattr(exc, "message", None) or str(exc)


_override: AiGateway | None = None


def get_gateway() -> AiGateway:
    return _override or AiGateway()


def set_gateway(gw: AiGateway | None) -> None:
    """Test hook: replaces the gateway used by the services."""
    global _override
    _override = gw
