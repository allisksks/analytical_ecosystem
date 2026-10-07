from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from app.main import create_app


async def test_healthz_and_readyz() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/healthz")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert r.headers["x-request-id"]

        r = await client.get("/readyz")
        assert r.status_code == 200

        r = await client.get("/api/v1/openapi.json")
        assert r.status_code == 200
        assert r.json()["openapi"].startswith("3.1")


def test_cors_origins_from_plain_env(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Docker Compose passes CORS_ORIGINS as a plain URL — the API must start with it."""
    from app.core.config import Settings

    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:8080")
    assert Settings().cors_origins == ["http://localhost:8080"]
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example")
    assert Settings().cors_origins == ["https://a.example", "https://b.example"]
    monkeypatch.setenv("CORS_ORIGINS", '["https://c.example"]')
    assert Settings().cors_origins == ["https://c.example"]


def test_ai_extra_body_from_env(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.core.config import Settings

    monkeypatch.setenv("AI_EXTRA_BODY", "")
    assert Settings().ai_extra_body == {}
    monkeypatch.setenv("AI_EXTRA_BODY", '{"reasoning_effort": "low"}')
    assert Settings().ai_extra_body == {"reasoning_effort": "low"}
