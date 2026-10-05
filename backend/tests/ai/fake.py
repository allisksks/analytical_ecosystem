"""A fake OpenAI-compatible server for tests (chat, streaming, embeddings)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

import httpx

from app.core.config import Settings
from app.modules.ai.gateway import AiGateway

Reply = Callable[[list[dict[str, str]]], str]


def vector(text: str, dims: int = 16) -> list[float]:
    """Deterministic bag-of-stems embedding: texts sharing words get close vectors."""
    v = [0.0] * dims
    for w in text.lower().split():
        h = int(hashlib.md5(w[:5].encode()).hexdigest(), 16)
        v[h % dims] += 1.0
    return v


class FakeLLM:
    def __init__(self, reply: Reply | None = None, status: int = 200) -> None:
        self.reply: Reply = reply or (lambda msgs: "Ответ [1].")
        self.status = status
        self.requests: list[httpx.Request] = []
        self.bodies: list[dict[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        self.bodies.append(body)
        if self.status >= 400:
            return httpx.Response(self.status, text="boom")
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(
                200, json={"data": [{"index": i, "embedding": vector(t)} for i, t in enumerate(body["input"])]}
            )
        text = self.reply(body["messages"])
        if body.get("stream"):
            chunks = ["<think>hidden", " reasoning</think>", *[text[i : i + 7] for i in range(0, len(text), 7)]]
            sse = "".join(f"data: {json.dumps({'choices': [{'delta': {'content': c}}]})}\n\n" for c in chunks)
            return httpx.Response(200, text=sse + "data: [DONE]\n\n", headers={"content-type": "text/event-stream"})
        return httpx.Response(
            200,
            json={
                "model": body["model"],
                "choices": [{"message": {"content": f"<think>let me think</think>{text}"}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            },
        )

    def gateway(self, **overrides: Any) -> AiGateway:
        cfg = {
            "ai_enabled": True,
            "ai_base_url": "http://ollama:11434/v1",
            "ai_chat_model": "qwen3:8b",
            "ai_embedding_model": "fake-embed",
            **overrides,
        }
        return AiGateway(Settings(**cfg), transport=httpx.MockTransport(self.handler))
