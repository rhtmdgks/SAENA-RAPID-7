"""Defensive-branch coverage (w4-08): closed-session render, pool wait/close
paths, envelope payload-validation failure, error taxonomy conversions."""

from __future__ import annotations

import threading
import time

import pytest
from saena_chatgpt_observer.errors import BrowserSessionRenderError, CrossTenantObservationError
from saena_chatgpt_observer.platform_observation_record import (
    ObservationCapturedEventError,
    build_observation_captured_envelope,
)
from saena_chatgpt_observer.pool import (
    BrowserPool,
    FixtureBrowserSession,
    FixtureBrowserSessionFactory,
)

from .conftest import ENGINE, RUN_ID, TENANT_A


def test_render_on_closed_session_raises() -> None:
    s = FixtureBrowserSession(session_id="s0")
    s.register_query("q", b"x")
    s.close()
    with pytest.raises(BrowserSessionRenderError, match="is closed"):
        s.render_search_result(query_text="q")


def test_close_closes_idle_sessions() -> None:
    pool = BrowserPool(FixtureBrowserSessionFactory(shared_responses={"q": b"x"}), max_size=1)
    s = pool.acquire()
    pool.release(s)  # now idle
    assert pool.stats().idle == 1
    pool.close()
    assert pool.stats().idle == 0
    assert isinstance(s, FixtureBrowserSession)
    assert not s.is_healthy()  # closed


def test_acquire_waits_then_succeeds_when_a_session_is_released() -> None:
    pool = BrowserPool(
        FixtureBrowserSessionFactory(shared_responses={"q": b"x"}),
        max_size=1,
        acquire_timeout_seconds=2.0,
    )
    held = pool.acquire()

    def _release_soon() -> None:
        time.sleep(0.05)
        pool.release(held)

    t = threading.Thread(target=_release_soon)
    t.start()
    # pool is full → this acquire enters the wait path, then wakes on release
    session = pool.acquire()
    t.join()
    assert session is not None
    pool.release(session)


def test_envelope_build_fails_closed_on_invalid_payload() -> None:
    # engine_id passes the guard (chatgpt-search) but a malformed artifact_hash
    # fails the payload schema → ObservationCapturedEventError (defensive path).
    with pytest.raises(ObservationCapturedEventError):
        build_observation_captured_envelope(
            tenant_id=TENANT_A,
            run_id=RUN_ID,
            engine_id=ENGINE,
            observation_id=f"{RUN_ID}-0000",
            artifact_hash="not-a-valid-sha",
            idempotency_key="k",
        )


def test_error_to_dict_and_to_job_error() -> None:
    err = CrossTenantObservationError("nope", context={"requested_tenant_id": TENANT_A})
    d = err.to_dict()
    assert d["message"] == "nope"
    assert d["requested_tenant_id"] == TENANT_A
    assert "error_code" in d
    je = err.to_job_error()
    assert je.error_code == err.error_code
    assert je.summary == "nope"
