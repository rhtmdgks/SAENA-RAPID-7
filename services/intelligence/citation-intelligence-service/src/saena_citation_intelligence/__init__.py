"""saena_citation_intelligence — citation-intelligence-service (W4, w4-05).

Deterministic, offline citation-selection intelligence: URL normalization
(`normalization.normalize_url`), rule-based + calibrated-prior source
ownership classification (`ownership.classify_ownership`), an immutable
tenant-scoped `records.CitationRecord`, and `service.normalize_citation` —
the single entry point that ties normalization + ownership + the
`citation.normalized.v1` event envelope together (built via
`saena_domain.events.EnvelopeFactory`, no hand-built envelope dict).

W4 MINIMAL scope — explicitly OUT of this package (deliberately not
implemented here, per this unit's own task instruction and CLAUDE.md Wave-4
hard constraints): NO answer-absorption analysis (P1
`absorption-analysis-service`'s job), NO contribution/prominence scoring
beyond the ownership classification itself, NO outcome/DiD/causal/lift
computation (Wave 5), NO ML model training or runtime ML inference (the
"calibrated prior" is a fixed, documented weight table — see
`ownership.py`), NO network/DNS access (URL normalization is pure string
logic; ownership classification consumes caller-sourced domain sets, it
never resolves/looks anything up itself).

Public API:
    normalize_url
    OwnershipClass / OwnershipDecision / classify_ownership
    CitationRecord / compute_content_hash
    CitationNormalizationResult / normalize_citation / ALLOWED_ENGINE_IDS
    CitationIntelligenceError and every specific error subclass
"""

from __future__ import annotations

from saena_citation_intelligence.errors import (
    CitationIntelligenceError,
    CrossTenantCitationError,
    EngineNotPermittedError,
    OwnershipClassificationError,
    UrlNormalizationError,
)
from saena_citation_intelligence.normalization import normalize_url
from saena_citation_intelligence.ownership import (
    OwnershipClass,
    OwnershipDecision,
    classify_ownership,
)
from saena_citation_intelligence.records import CitationRecord, compute_content_hash
from saena_citation_intelligence.service import (
    ALLOWED_ENGINE_IDS,
    CitationNormalizationResult,
    normalize_citation,
)

__all__ = [
    "ALLOWED_ENGINE_IDS",
    "CitationIntelligenceError",
    "CitationNormalizationResult",
    "CitationRecord",
    "CrossTenantCitationError",
    "EngineNotPermittedError",
    "OwnershipClass",
    "OwnershipClassificationError",
    "OwnershipDecision",
    "UrlNormalizationError",
    "classify_ownership",
    "compute_content_hash",
    "normalize_citation",
    "normalize_url",
]
