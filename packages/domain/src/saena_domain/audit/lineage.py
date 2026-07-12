"""Opaque `lineage_audit_ref` construction (ADR-0013 AggregateContext field).

ADR-0013 defines `lineage_audit_ref` as an "opaque audit-ledger hash 문자열,
audit role 전용 열람" — the field's example value in the ADR appendix is
`"sha256:8f2e1c9a7b3d5f4e6a8c2b1d9f7e3a5c4b6d8f2e1c9a7b3d5f4e6a8c2b1d9f7e"`
(ADR-0013 :148), and its rev.2 amendment note ("lineage_audit_ref의
audit-ledger 저장 포맷... W1/W2A 세부 설계") leaves the concrete construction
to this wave. security-model.md's Open decisions list "audit hash chain 외부
앵커·WORM·immutable role 정의"로 남아 있어, this module implements only the
opaque-ref *format*, not resolution/verification against an external anchor.

The wire format is documented HERE as an implementation detail rather than
re-specified by any contract: `"audit:sha256:<hex>"` — an `audit:` scheme
prefix wrapping the entry's own `sha256:<hex>` `event_hash`, so a ref is
self-describing (`audit:` marks "this opaque string resolves via the
audit-ledger role-restricted path", distinguishing it at a glance from a bare
`sha256_ref` used elsewhere, e.g. `SourceSnapshot`'s content hash). There is
deliberately no parsing API beyond `is_lineage_ref` — ADR-0013 constraints
say `lineage_audit_ref` 열람 is "audit role 전용... 일반 서비스 코드/로그에
원문 노출 금지", so this module does not offer a way to extract the wrapped
hash back out for general use.
"""

from __future__ import annotations

import re

#: Wire-format scheme prefix — see module docstring.
LINEAGE_REF_SCHEME = "audit"

_LINEAGE_REF_RE = re.compile(r"^audit:sha256:[0-9a-f]{64}$")

_SHA256_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def make_lineage_ref(entry_hash: str) -> str:
    """Build an opaque `lineage_audit_ref` from an audit entry's `event_hash`.

    `entry_hash` must already be in the contract's `sha256_ref` wire form
    (`sha256:<64-hex>`, matching `event_hash`/`prev_event_hash` in the
    audit-event schema and `hashing.compute_entry_hash`'s return value).
    Raises `ValueError` if `entry_hash` is not in that form — a lineage ref
    must always anchor to a real, well-formed chain entry hash.
    """
    if not _SHA256_REF_RE.match(entry_hash):
        raise ValueError("entry_hash must be a well-formed sha256_ref ('sha256:<64-hex>')")
    return f"{LINEAGE_REF_SCHEME}:{entry_hash}"


def is_lineage_ref(value: str) -> bool:
    """Return whether `value` is a well-formed opaque lineage ref.

    Validation only — this is the extent of the "no parsing API beyond
    validation" surface documented in the module docstring; it does not
    expose the wrapped hash.
    """
    return bool(_LINEAGE_REF_RE.match(value))
