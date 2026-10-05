from __future__ import annotations

import pytest
from pydantic import SecretStr

from app.core.errors import FeatureDisabled, UpstreamError
from app.modules.ai.gateway import is_local, strip_think
from tests.ai.fake import FakeLLM


async def test_chat_headers_no_think_and_think_stripping() -> None:
    llm = FakeLLM(lambda m: "Привет")
    gw = llm.gateway(
        ai_api_key=SecretStr("k-1"), ai_auth_scheme="Api-Key", ai_project_header="OpenAI-Project", ai_project_id="b1g"
    )
    res = await gw.chat([{"role": "user", "content": "hi"}])
    assert res.text == "Привет" and res.prompt_tokens == 100
    req = llm.requests[0]
    assert req.url.path == "/v1/chat/completions"
    assert req.headers["authorization"] == "Api-Key k-1"
    assert req.headers["openai-project"] == "b1g"
    assert llm.bodies[0]["messages"][-1]["content"].endswith("/no_think")
    res = await gw.chat([{"role": "user", "content": "hi"}], model="llama3")
    assert not llm.bodies[1]["messages"][-1]["content"].endswith("/no_think")


async def test_stream_filters_reasoning() -> None:
    gw = FakeLLM(lambda m: "Ответ из базы знаний [1].").gateway()
    parts = [d async for d in gw.stream([{"role": "user", "content": "q"}])]
    assert "".join(parts) == "Ответ из базы знаний [1]."


async def test_embeddings_batches() -> None:
    llm = FakeLLM()
    vecs = await llm.gateway().embed([f"text {i}" for i in range(40)])
    assert len(vecs) == 40 and len(llm.requests) == 2


async def test_errors_and_guards() -> None:
    with pytest.raises(UpstreamError):
        await FakeLLM(status=500).gateway().chat([{"role": "user", "content": "x"}])
    with pytest.raises(FeatureDisabled):
        await FakeLLM().gateway(ai_enabled=False).chat([{"role": "user", "content": "x"}])
    with pytest.raises(FeatureDisabled):
        await (
            FakeLLM()
            .gateway(ai_base_url="https://llm.api.cloud.yandex.net/v1", ai_allow_cloud=False)
            .chat([{"role": "user", "content": "x"}])
        )
    with pytest.raises(FeatureDisabled):
        await FakeLLM().gateway(ai_embedding_model=None).embed(["x"])
    ok, err = await FakeLLM(status=500).gateway().ping()
    assert not ok and "500" in err


def test_helpers() -> None:
    assert is_local("http://ollama:11434/v1") and is_local("http://10.0.0.5/v1") and is_local("http://localhost:8000")
    assert not is_local("https://llm.api.cloud.yandex.net/v1")
    assert strip_think("<think>a\nb</think>\nОтвет") == "Ответ"
    assert strip_think("Ответ<think>unfinished") == "Ответ"
