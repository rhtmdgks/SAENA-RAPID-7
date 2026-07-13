"""BrowserPool lifecycle (w4-08): bounded acquire/release/recycle, read-only
Protocol, fixture-session determinism, fail-closed exhaustion."""

from __future__ import annotations

import pytest
from saena_chatgpt_observer.errors import (
    BrowserPoolClosedError,
    BrowserPoolExhaustedError,
    BrowserSessionRenderError,
)
from saena_chatgpt_observer.pool import (
    BrowserPool,
    BrowserSessionPort,
    FixtureBrowserSession,
    FixtureBrowserSessionFactory,
)


def _pool(**kw) -> BrowserPool:
    factory = FixtureBrowserSessionFactory(shared_responses={"q": b"<html>ok</html>"})
    return BrowserPool(factory, **kw)


def test_read_only_protocol_has_no_write_method() -> None:
    # The session Protocol exposes only render (read), health, close — no
    # navigate/click/type/login/write surface at all (read-only invariant).
    surface = set(dir(BrowserSessionPort))
    for banned in ("navigate", "click", "type", "fill", "login", "submit", "write", "post"):
        assert banned not in surface


def test_max_size_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_size must be >= 1"):
        _pool(max_size=0)


def test_acquire_creates_up_to_max_size_then_blocks_and_times_out() -> None:
    pool = _pool(max_size=2, acquire_timeout_seconds=0.0)
    s1 = pool.acquire()
    s2 = pool.acquire()
    assert pool.stats().in_use == 2
    assert pool.stats().total == 2
    # third acquire with no free session + zero timeout → fail-closed, bounded
    with pytest.raises(BrowserPoolExhaustedError):
        pool.acquire()
    pool.release(s1)
    pool.release(s2)


def test_released_session_is_reused_not_recreated() -> None:
    factory = FixtureBrowserSessionFactory(shared_responses={"q": b"x"})
    pool = BrowserPool(factory, max_size=1, max_uses_per_session=10)
    a = pool.acquire()
    pool.release(a)
    b = pool.acquire()
    assert a is b  # same instance reused
    assert len(factory.sessions_built) == 1
    pool.release(b)


def test_unhealthy_session_is_recycled_on_release() -> None:
    pool = _pool(max_size=1, max_uses_per_session=10)
    s = pool.acquire()
    assert isinstance(s, FixtureBrowserSession)
    s.poison()
    pool.release(s)
    assert pool.stats().recycled_count == 1
    assert pool.stats().total == 0  # capacity slot freed for a fresh session


def test_session_recycled_after_max_uses() -> None:
    pool = _pool(max_size=1, max_uses_per_session=2)
    for _ in range(2):
        s = pool.acquire()
        pool.release(s)
    assert pool.stats().recycled_count == 1


def test_release_of_unknown_session_is_a_noop() -> None:
    pool = _pool(max_size=1)
    stranger = FixtureBrowserSession(session_id="stranger")
    pool.release(stranger)  # must not raise, must not change occupancy
    assert pool.stats() == pool.stats()
    assert pool.stats().in_use == 0


def test_close_is_idempotent_and_blocks_further_acquire() -> None:
    pool = _pool(max_size=1)
    pool.close()
    pool.close()  # idempotent
    with pytest.raises(BrowserPoolClosedError):
        pool.acquire()


def test_leased_session_context_releases_on_exit_including_error() -> None:
    pool = _pool(max_size=1)
    with pool.leased_session() as session:
        assert pool.stats().in_use == 1
        assert session.render_search_result(query_text="q") == b"<html>ok</html>"
    assert pool.stats().in_use == 0  # released on normal exit

    with pytest.raises(RuntimeError), pool.leased_session():
        raise RuntimeError("boom")
    assert pool.stats().in_use == 0  # released on exceptional exit too


def test_fixture_session_render_without_registered_query_raises() -> None:
    pool = BrowserPool(FixtureBrowserSessionFactory(), max_size=1)
    with pool.leased_session() as session, pytest.raises(BrowserSessionRenderError):
        session.render_search_result(query_text="never-registered")
