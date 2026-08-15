"""Rate limiting is a wait, not a failure.

Six months of minute bars for 150 symbols is thousands of pages. A run launched
minutes after another shares the same rate window and used to die partway with
a 429 — and because the workflow piped the crash into `tee`, GitHub reported
the run as a success with an empty report.
"""
import httpx
import pytest

from app.backtest.data import MAX_RETRIES, RETRY_STATUS, _get_with_retry


class FakeClient:
    """Returns the queued statuses in order, then 200 forever."""

    def __init__(self, statuses, headers=None):
        self.statuses = list(statuses)
        self.headers = headers or {}
        self.calls = 0

    async def get(self, url, params=None):
        self.calls += 1
        status = self.statuses.pop(0) if self.statuses else 200
        return httpx.Response(status, json={"bars": {}}, headers=self.headers,
                              request=httpx.Request("GET", url))


@pytest.fixture
def slept():
    delays = []
    async def fake_sleep(seconds): delays.append(seconds)
    fake_sleep.delays = delays
    return fake_sleep


@pytest.mark.asyncio
async def test_a_rate_limit_is_waited_out_not_raised(slept):
    client = FakeClient([429, 429])
    response = await _get_with_retry(client, {}, sleep=slept)
    assert response.status_code == 200
    assert client.calls == 3


@pytest.mark.asyncio
async def test_the_wait_grows_between_attempts(slept):
    await _get_with_retry(FakeClient([429, 429, 429]), {}, sleep=slept)
    assert slept.delays == [2.0, 4.0, 8.0]


@pytest.mark.asyncio
async def test_the_servers_retry_after_wins_when_it_is_longer(slept):
    await _get_with_retry(FakeClient([429], headers={"retry-after": "30"}), {}, sleep=slept)
    assert slept.delays == [30.0]


@pytest.mark.asyncio
async def test_a_junk_retry_after_falls_back_to_the_backoff(slept):
    await _get_with_retry(FakeClient([429], headers={"retry-after": "soon"}), {}, sleep=slept)
    assert slept.delays == [2.0]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", sorted(RETRY_STATUS))
async def test_every_transient_status_is_retried(status, slept):
    client = FakeClient([status])
    assert (await _get_with_retry(client, {}, sleep=slept)).status_code == 200
    assert client.calls == 2


@pytest.mark.asyncio
async def test_a_client_error_that_will_not_heal_raises_at_once(slept):
    """A bad symbol or a bad key must fail loudly, not spin for minutes."""
    client = FakeClient([403])
    with pytest.raises(httpx.HTTPStatusError):
        await _get_with_retry(client, {}, sleep=slept)
    assert client.calls == 1 and slept.delays == []


@pytest.mark.asyncio
async def test_persistent_rate_limiting_eventually_raises(slept):
    client = FakeClient([429] * (MAX_RETRIES + 2))
    with pytest.raises(httpx.HTTPStatusError):
        await _get_with_retry(client, {}, sleep=slept)
    assert client.calls == MAX_RETRIES


@pytest.mark.asyncio
async def test_a_clean_response_costs_no_extra_calls(slept):
    client = FakeClient([])
    await _get_with_retry(client, {}, sleep=slept)
    assert client.calls == 1 and slept.delays == []
