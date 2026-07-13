"""W2A approval end-to-end suite — the named W2A exit narratives:

1. Approval E2E: propose -> Policy Gate 검증 -> 승인 -> audit chain
   (`test_happy_path.py`).
2. Policy-gate fail-closed 데모: gate 다운 -> 승인 불가 (`test_happy_path.py`
   also contains the explicit fail-closed demo, run alongside the happy
   path so both are visible in one narrative module — mirrors how
   implementation-waves.md W2A Exit lists them as one bullet).

Builds on `tests/integration/approval_flow`'s shared harness/factories
(`conftest.py` inserts that directory onto `sys.path` too) rather than
duplicating the wiring — this package's OWN job is the end-to-end narrative
assertions, not re-deriving component wiring.
"""

from __future__ import annotations
