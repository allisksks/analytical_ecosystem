"""Result cache: Redis/Valkey when configured, otherwise an in-process LRU (single-node dev)."""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any

import orjson
import structlog
from redis.asyncio import Redis

from app.core.config import get_settings

log = structlog.get_logger("cache")
PREFIX = "qc:"


class _Memory:
    def __init__(self, max_items: int = 512) -> None:
        self.data: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
        self.max_items = max_items

    async def get(self, key: str) -> bytes | None:
        item = self.data.get(key)
        if item is None:
            return None
        if item[0] < time.monotonic():
            self.data.pop(key, None)
            return None
        self.data.move_to_end(key)
        return item[1]

    async def set(self, key: str, value: bytes, ex: int) -> None:
        self.data[key] = (time.monotonic() + ex, value)
        self.data.move_to_end(key)
        while len(self.data) > self.max_items:
            self.data.popitem(last=False)

    async def delete_prefix(self, prefix: str) -> int:
        keys = [k for k in self.data if k.startswith(prefix)]
        for k in keys:
            self.data.pop(k, None)
        return len(keys)


class ResultCache:
    def __init__(self) -> None:
        url = get_settings().redis_url
        self._redis: Redis | None = Redis.from_url(url) if url else None
        self._memory = _Memory()

    async def get(self, key: str) -> dict[str, Any] | None:
        raw: bytes | str | None
        try:
            raw = await self._redis.get(PREFIX + key) if self._redis else await self._memory.get(key)
        except Exception as exc:  # cache is an optimisation: never fail the query because of it
            log.warning("cache get failed", error=str(exc))
            return None
        return orjson.loads(raw) if raw else None

    async def set(self, key: str, value: dict[str, Any], ttl: int) -> None:
        if ttl <= 0:
            return
        raw = orjson.dumps(value, default=str)
        try:
            if self._redis:
                await self._redis.set(PREFIX + key, raw, ex=ttl)
            else:
                await self._memory.set(key, raw, ttl)
        except Exception as exc:
            log.warning("cache set failed", error=str(exc))

    async def invalidate_source(self, source_id: str) -> int:
        """Drops cached results of a source (152-FZ: cache can be removed on request)."""
        prefix = f"{source_id}:"
        if self._redis:
            n = 0
            async for key in self._redis.scan_iter(match=f"{PREFIX}{prefix}*"):
                n += await self._redis.delete(key)
            return n
        return await self._memory.delete_prefix(prefix)


_cache: ResultCache | None = None


def get_cache() -> ResultCache:
    global _cache
    if _cache is None:
        _cache = ResultCache()
    return _cache
