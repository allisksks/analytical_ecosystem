from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.modules.connectors.plugins.gsheets import GoogleSheetsConnector


def _sa() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return json.dumps({"client_email": "bot@x.iam.gserviceaccount.com", "private_key": pem.decode()})


def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url.startswith("https://oauth2.googleapis.com/token"):
        assert b"jwt-bearer" in request.content
        return httpx.Response(200, json={"access_token": "tok"})
    assert request.headers["Authorization"] == "Bearer tok"
    if url.endswith("fields=sheets.properties.title"):
        return httpx.Response(200, json={"sheets": [{"properties": {"title": "Plan 2026"}}]})
    if "/values/" in url:
        return httpx.Response(200, json={"values": [["month", "budget"], ["2026-01", "100"], ["2026-02"]]})
    return httpx.Response(404)


async def test_sync_writes_parquet_and_queries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(GoogleSheetsConnector, "transport", httpx.MockTransport(_handler))
    c = GoogleSheetsConnector({"spreadsheet_id": "abc", "_storage_dir": str(tmp_path)}, {"service_account_json": _sa()})
    assert (await c.test()).ok
    assert await c.sync() == {"plan_2026": 2}
    catalog = await c.list_catalog()
    assert catalog[0].name == "plan_2026"
    res = await c.execute("SELECT month, budget FROM plan_2026 ORDER BY month", None, 10, 5, "g1")
    assert res.rows == [["2026-01", "100"], ["2026-02", None]]
