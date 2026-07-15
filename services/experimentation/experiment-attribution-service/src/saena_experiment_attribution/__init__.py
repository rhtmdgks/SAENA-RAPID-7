"""SAENA experiment-attribution-service (W5).

This package is the measurement module of the optimization-worker deployment
unit (ADR-0002 rev.3; see `docs/architecture/wave5-plan.md` "Topology
decision"). w5-10 ships ONLY the `persistence` sub-package (Postgres adapters
+ migrations for the measurement stores); the service boundary/pipeline/
workflow sub-packages land in sibling W5 units (w5-12/13/14). This top-level
`__init__` is intentionally minimal — a namespace anchor, no re-exports — so
those later units can add their own sub-packages without any coordination
edit here.
"""

from __future__ import annotations

__all__: list[str] = []
