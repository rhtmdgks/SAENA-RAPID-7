"""``OutcomeLayer`` — the CLOSED set of B-layer outcome signal layers.

Source specification references (READ-ONLY basis for this module):
- docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md §3.5:159 — the
  outcome-layer vocabulary: discovery / citation / absorption / prominence /
  referral. This is the authoritative enumeration; wave5-plan.md H4 records it
  as the working assumption ``[discovery, citation, absorption, prominence,
  referral]`` with ``conversion`` explicitly EXCLUDED.
- Algorithm §4:212 / k3s §12:553 — conversion/attribution is FORBIDDEN as a
  7-day B-layer success metric, so ``conversion`` is deliberately NOT a member
  of this enum. ``tests/unit/domain_measurement_bgate/test_outcome_layer.py``
  pins ``"conversion"`` as un-constructable, an executable assertion (not a
  comment).

Closed-enum discipline (ADR-0012 narrow-AND-widen = major): this set is a
closed vocabulary. Adding or removing a member is a MAJOR change, never a
silent edit.

NOTE on ``absorption``: this member is a DATA enum value only — it lets an
outcome signal be *labelled* as an absorption-layer observation. It is NOT the
Wave-5 non-scope "absorption-analysis P1 model", which stays flag-off
(wave5-plan.md Non-scope: "``absorption`` as an ``outcome_layer`` enum value is
data-model support, NOT P1 model activation").
"""

from __future__ import annotations

from enum import Enum


class OutcomeLayer(str, Enum):
    """A single independently-observed B-layer signal layer (closed set).

    Inherits ``str`` so a member compares equal to its wire value and is
    JSON/enum-serialisable, matching the ``str``-enum precedent used elsewhere
    in ``saena_domain`` (e.g. privacy/status). The set is CLOSED: only the five
    members below are valid outcome layers. ``conversion`` is intentionally
    absent (see module docstring) — constructing ``OutcomeLayer("conversion")``
    raises ``ValueError``.
    """

    DISCOVERY = "discovery"
    CITATION = "citation"
    ABSORPTION = "absorption"
    PROMINENCE = "prominence"
    REFERRAL = "referral"


__all__ = ["OutcomeLayer"]
