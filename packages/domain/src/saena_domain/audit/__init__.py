"""saena_domain.audit — audit-ledger hash-chain domain logic (w2-04).

Pure logic for the `AuditEvent` contract (contract-catalog.md P0 row 12:
Owner=audit-ledger, Idempotency key='event hash (chain)', Sensitivity
'internal+actor PII 최소화', Retention 'contractual, immutable role; payload
PII/secret 금지') plus ADR-0015's audit error-recording scope (`error_code` +
`trace_id` only — never stack traces or raw content).

Persistence ports (real storage adapters) arrive in w2-07; this module keeps
the chain/guard/hash logic separable from any I/O so those ports can wrap
`InMemoryAuditChain`'s pure operations without re-deriving the hashing or
guard rules.
"""

from __future__ import annotations

from saena_domain.audit.canonical import canonical_json, sha256_hex
from saena_domain.audit.chain import (
    AuditEntry,
    InMemoryAuditChain,
    append_entry,
    verify_chain,
)
from saena_domain.audit.guard import (
    ForbiddenAuditDataError,
    guard_actor_fields,
    guard_error_detail,
    guard_payload,
)
from saena_domain.audit.hashing import GENESIS, compute_entry_hash
from saena_domain.audit.lineage import make_lineage_ref

__all__ = [
    "GENESIS",
    "AuditEntry",
    "ForbiddenAuditDataError",
    "InMemoryAuditChain",
    "append_entry",
    "canonical_json",
    "compute_entry_hash",
    "guard_actor_fields",
    "guard_error_detail",
    "guard_payload",
    "make_lineage_ref",
    "sha256_hex",
    "verify_chain",
]
