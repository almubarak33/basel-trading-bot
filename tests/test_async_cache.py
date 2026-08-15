import asyncio

import pytest

from app.async_cache import AsyncTTLCache


@pytest.mark.asyncio
async def test_concurrent_requests_share_one_loader_call():
    cache = AsyncTTLCache()
    calls = 0

    async def loader():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return {"value": 7}

    results = await asyncio.gather(*(cache.get("stock", 30, loader) for _ in range(8)))

    assert calls == 1
    assert results == [{"value": 7}] * 8


@pytest.mark.asyncio
async def test_clear_forces_a_fresh_load():
    cache = AsyncTTLCache()
    calls = 0

    async def loader():
        nonlocal calls
        calls += 1
        return calls

    assert await cache.get("stock", 30, loader) == 1
    cache.clear()
    assert await cache.get("stock", 30, loader) == 2
