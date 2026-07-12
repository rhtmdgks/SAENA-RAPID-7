"""SignalClient port — FakeSignalClient records sends; Protocol shape check.

Uses plain `asyncio.run` (no `pytest-asyncio`/`anyio` plugin dependency —
this patch unit adds no new deps) to drive the small async `send_approval`
coroutines from ordinary sync test functions.
"""

from __future__ import annotations

import asyncio

from orchestrator_factories import make_signal
from saena_orchestrator.signal_client import APPROVE_SIGNAL_NAME, FakeSignalClient, SignalClient


def test_fake_signal_client_records_sent_signal() -> None:
    client = FakeSignalClient()
    signal = make_signal()
    asyncio.run(client.send_approval("wf-1", signal))
    assert client.sent == [("wf-1", signal)]


def test_fake_signal_client_records_multiple_sends_in_order() -> None:
    client = FakeSignalClient()
    signal_a = make_signal()
    signal_b = make_signal(proposer_actor_id="actor-proposer-0002")

    async def _send_both() -> None:
        await client.send_approval("wf-1", signal_a)
        await client.send_approval("wf-2", signal_b)

    asyncio.run(_send_both())
    assert [wf_id for wf_id, _ in client.sent] == ["wf-1", "wf-2"]


def test_fake_signal_client_satisfies_signal_client_protocol() -> None:
    client = FakeSignalClient()
    assert isinstance(client, SignalClient)


def test_approve_signal_name_constant() -> None:
    assert APPROVE_SIGNAL_NAME == "approve"
