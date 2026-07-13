"""actor_id canonicalization for equality/dedup purposes.

identifiers.schema.json's `actor_id` $def is explicitly format-OPEN
("format OPEN — issuer runtime convention; W1 opaque", minLength/maxLength
only — no case or whitespace normalization is schema-enforced). Left as raw
string `==`, "Actor-1", "actor-1", and "actor-1 " would count as three
distinct approvers, which would defeat both H-7 two-person quorum (an
attacker could satisfy "2 distinct approvers" with two case-variants of the
same identity) and the proposer-never-equals-approver self-approval ban
(critic MUST-FIX 2). This module centralizes the one normalization rule used
everywhere an actor_id is compared or used as a dedup/replay key.
"""

from __future__ import annotations

import unicodedata


def canonical_actor_id(actor_id: str) -> str:
    """Canonical form of an actor_id for equality/dedup/replay-key purposes.

    NFKC-normalizes (folds compatibility-equivalent Unicode forms), strips
    leading/trailing whitespace, then casefolds (stronger than .lower() for
    non-ASCII equality). Used for: H-7 distinct-approver dedup, proposer !=
    approver checks, and DecisionRecord.decision_key derivation — NOT for
    display or storage, which should retain the original actor_id as
    presented (this function is comparison-only).
    """
    return unicodedata.normalize("NFKC", actor_id).strip().casefold()
