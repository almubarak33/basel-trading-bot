"""Small in-process async TTL cache with per-key request coalescing."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any


class AsyncTTLCache:
    def __init__(self):
        self._values: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def get(self, key: str, ttl: float,
                  loader: Callable[[], Awaitable[Any]]) -> Any:
        now = time.monotonic()
        cached = self._values.get(key)
        if cached and cached[0] > now:
            return cached[1]

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            cached = self._values.get(key)
            if cached and cached[0] > now:
                return cached[1]
            value = await loader()
            self._values[key] = (now + max(ttl, 0), value)
            return value

    def clear(self) -> None:
        self._values.clear()
        self._locks.clear()
