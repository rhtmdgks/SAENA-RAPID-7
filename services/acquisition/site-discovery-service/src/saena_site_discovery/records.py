"""`ContentRecordProjection` — read-only site-inventory record for one route.

`ContentRecord` itself is a P1 (Wave 3-4) contract
(`docs/architecture/contract-catalog.md` row 37: owner site-discovery,
"게시 전 draft=customer-proprietary — 등급 전환 규칙 OPEN") that has NO
`packages/contracts` JSON Schema yet — this module deliberately does not
invent that schema (out of this unit's exclusive write paths and out of its
mission scope, which names this a "ContentRecord-**like**... structured
projection"). `ContentRecordProjection` below is this service's own
domain-internal value object covering exactly the discovery-relevant facts
the mission names (route, render mode, robots, canonical, sitemap,
structured-data presence) — a later patch unit against `packages/contracts`
owns reconciling it with the eventual formal `ContentRecord` contract.

Every instance is frozen/immutable (deliverable 2: "observation artifact
(immutable, frozen)") and carries `evidence_ref` — an OPAQUE reference to
the raw captured page content, never the raw HTML/DOM itself (mirrors
`saena_artifact_registry.blobstore.BlobRef`'s "opaque reference only, never
inline content" discipline, and contract-catalog's `PlatformObservation`
row "raw는 object ref만" rule, applied here too for the same reason: crawled
web content can carry third-party PII or ToS-sensitive material this
service must never persist inline).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from saena_site_discovery.errors import SiteDiscoveryError

_ROUTE_PATH_MAX_LENGTH = 2048
_EVIDENCE_REF_MAX_LENGTH = 512
# ADR-0024(f) common uri-field pattern (scheme + `://` + no `?`/`#`) reused
# for evidence_ref's shape check — same discipline
# `saena_artifact_registry.uri_validation` applies to manifest uri fields,
# applied here to keep raw-content references off any query-string-shaped
# (e.g. presigned-token) path.
_EVIDENCE_REF_PATTERN = re.compile(r"^[a-z0-9+.-]+://[^?#]+$")


class RecordValidationError(SiteDiscoveryError):
    """A `ContentRecordProjection` field failed validation at construction
    time."""

    error_code = "saena.validation.content_record_invalid"


class RenderMode(StrEnum):
    """How a route's primary content is rendered — discovery-relevant fact
    this service's crawl adapter observes per route."""

    STATIC = "static"
    SERVER_SIDE = "server_side"
    CLIENT_SIDE = "client_side"
    HYBRID = "hybrid"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ContentRecordProjection:
    """Read-only, immutable per-route site-inventory projection.

    `robots_allowed=False` records mean the route was NEVER fetched (see
    `inventory.run_site_discovery`'s robots-boundary hook) — every field
    other than `route_path`/`robots_allowed`/`observed_at` is left at its
    "unknown/never observed" default in that case (`render_mode=UNKNOWN`,
    `canonical_url=None`, `sitemap_listed=False`,
    `structured_data_present=False`, `evidence_ref=""`), never a
    fabricated or stale value.
    """

    route_path: str
    render_mode: RenderMode
    robots_allowed: bool
    canonical_url: str | None
    sitemap_listed: bool
    structured_data_present: bool
    evidence_ref: str
    observed_at: str

    def __post_init__(self) -> None:
        if not self.route_path:
            raise RecordValidationError(
                "route_path must be a non-empty string", context={"field": "route_path"}
            )
        if len(self.route_path) > _ROUTE_PATH_MAX_LENGTH:
            raise RecordValidationError(
                f"route_path exceeds {_ROUTE_PATH_MAX_LENGTH} chars",
                context={"field": "route_path", "length": len(self.route_path)},
            )
        if not self.observed_at:
            raise RecordValidationError(
                "observed_at must be a non-empty string", context={"field": "observed_at"}
            )
        # A robots-disallowed route was never fetched — evidence_ref MUST be
        # empty (no fetch happened, so there is nothing to reference); a
        # fetched route MUST carry a non-empty, opaque evidence_ref (never
        # raw content).
        if not self.robots_allowed:
            if self.evidence_ref:
                raise RecordValidationError(
                    "a robots-disallowed record must never carry an evidence_ref "
                    "(the route was never fetched)",
                    context={"field": "evidence_ref", "route_path": self.route_path},
                )
            return
        if not self.evidence_ref:
            raise RecordValidationError(
                "a fetched (robots_allowed=True) record must carry a non-empty evidence_ref",
                context={"field": "evidence_ref", "route_path": self.route_path},
            )
        if len(self.evidence_ref) > _EVIDENCE_REF_MAX_LENGTH:
            raise RecordValidationError(
                f"evidence_ref exceeds {_EVIDENCE_REF_MAX_LENGTH} chars",
                context={"field": "evidence_ref", "length": len(self.evidence_ref)},
            )
        if not _EVIDENCE_REF_PATTERN.match(self.evidence_ref):
            raise RecordValidationError(
                f"evidence_ref {self.evidence_ref!r} is not a well-formed opaque "
                "reference (scheme required, '?'/'#' forbidden)",
                context={"field": "evidence_ref"},
            )


__all__ = ["ContentRecordProjection", "RecordValidationError", "RenderMode"]
