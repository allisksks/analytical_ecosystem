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
