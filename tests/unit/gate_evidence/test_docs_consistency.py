"""Documentation-consistency guard for the Wave 5 closure docs. Fails when a
canonical count diverges, a stale total reappears, a required-scenario count is
confused with a total pytest-pass count, or a superseded "CI verification
pending" claim survives in a doc that otherwise presents PASS state.

Canonical numbers (single source of truth for the prose):
  - E2E required-scenario manifest: 28   (NOT the gate pass total)
  - failure required-scenario manifest: 31 (16 primary / 15 recovery)
  - measurement-e2e gate pass total: 42   (28 scenarios + 14 guard/meta tests)
  - measurement-failure-modes gate pass total: 44 (31 + 13 guard/meta tests)
  - unit lane total: 5358
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DOCS = (
    _REPO_ROOT / "docs" / "architecture" / "wave5-pr-body.md",
    _REPO_ROOT / "docs" / "architecture" / "wave5-exit-report.md",
)

#: Substrings that must NOT appear — stale totals or superseded "pending" claims.
_FORBIDDEN = (
    "5297",  # stale unit total (now 5358)
    "39 pass",  # stale e2e gate total (now 42)
    "41 pass",  # stale failure gate total (now 44)
    "36 pass",  # older stale e2e total
    "35 pass",  # older stale failure total
    "CI verification pending",
    "has not yet run green",
    "not yet been exercised on a green",
    "In progress; CI verification",
)

#: Canonical tokens that must be present in at least one doc.
_REQUIRED = (
    "5358",
    "42 pass",
    "44 pass",
    "28 E2E scenarios",
    "31 failure nodes",
    "16 primary",
    "15 recovery",
)


@pytest.mark.parametrize("doc", _DOCS, ids=lambda p: p.name)
def test_no_stale_or_pending_strings(doc: Path) -> None:
    assert doc.is_file(), f"missing doc {doc}"
    text = doc.read_text()
    hits = [s for s in _FORBIDDEN if s in text]
    assert not hits, f"{doc.name} still contains stale/pending string(s): {hits}"


def test_canonical_tokens_present() -> None:
    corpus = "\n".join(d.read_text() for d in _DOCS if d.is_file())
    missing = [t for t in _REQUIRED if t not in corpus]
    assert not missing, f"canonical token(s) absent from the closure docs: {missing}"


def test_manifest_and_pass_totals_not_conflated() -> None:
    # The required-scenario counts (28/31) and the gate pass totals (42/44) are
    # different concepts. Guard against the specific stale conflations where a
    # gate total was written as the manifest count or vice-versa.
    corpus = "\n".join(d.read_text() for d in _DOCS if d.is_file())
    for bad in ("28 pass", "31 pass", "measurement-e2e` 28", "measurement-failure-modes` 31"):
        assert bad not in corpus, f"manifest/pass-total conflation found: {bad!r}"
