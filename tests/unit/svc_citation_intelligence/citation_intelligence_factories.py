"""Shared test-data builders for `tests/unit/svc_citation_intelligence`
(w4-05). Mirrors `tests/unit/svc_observer_discovery/observer_discovery_factories.py`'s
naming convention (uniquely-named module, never `factories.py` bare, to
avoid cross-directory import collisions under pytest's default `prepend`
import mode).
"""

from __future__ import annotations

TENANT_ID = "acme-co"
RUN_ID = "run-0001"
CITATION_ID = "cite-0001"

TENANT_OWNED_DOMAINS = frozenset({"acme.com"})
COMPETITOR_DOMAINS = frozenset({"rival.com"})


def fixed_clock() -> str:
    """Deterministic `clock` callable for `normalize_citation` tests — never
    real wall-clock time."""
    return "2026-07-13T00:00:00Z"
