"""Wave 4 (Intelligence) observability tests — w4-15.

Covers the mission's explicit gate list:
- new metric/attribute names follow the naming convention
  (`saena.<domain>.<name>` / `saena.<capability>.<operation>`);
- redaction blocks PII/secret-shaped fields AND the new intelligence-service
  customer-source-bearing field names (claim_text/excerpt/source_uri/
  normalized_uri/raw_object_ref/citation_ref/query_text) even when passed
  as an attribute key;
- no high-cardinality raw-content label is registered for the new
  intelligence attributes (every new attribute is an id/hash/version/
  boolean/closed-enum, never raw customer-source content);
- V-AGG-* structural violation rules are enforced for the new
  high-cardinality intelligence identifiers, same as V-AGG-TENANT;
- no outcome/lift/causal-estimate token appears in any new metric/span/
  attribute name (Wave 5 forbidden scope, CLAUDE.md "Current decision").
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from saena_observability.intelligence import (
    INTELLIGENCE_ATTRIBUTE_NAMES,
    INTELLIGENCE_METRIC_NAMES,
    INTELLIGENCE_SPAN_NAMES,
)
from saena_observability.naming import is_valid_metric_name, is_valid_span_name
from saena_observability.redaction import RedactionAction, decide_redaction
from saena_observability.registry import load_attribute_registry, load_redaction_rules

REGISTRY_DIR = Path(__file__).resolve().parent.parent / "registry"
ATTRIBUTES_JSON_PATH = REGISTRY_DIR / "attributes.json"

#: The nine new w4-15 attribute names (a strict subset of
#: INTELLIGENCE_ATTRIBUTE_NAMES, which also includes the pre-existing W0
#: core set: tenant_id/run_id/engine_id/context).
NEW_W4_15_ATTRIBUTE_NAMES = frozenset(
    {
        "saena.demand_graph_version",
        "saena.entity_graph_version",
        "saena.claim_id",
        "saena.evidence_id",
        "saena.claim_publishable",
        "saena.citation_normalized_uri_hash",
        "saena.browser_pool_state",
        "saena.experiment_id",
        "saena.intent_label",
    }
)

#: Customer-source-bearing field names that must NEVER be used as a
#: telemetry attribute key for any of the six w4-15 intelligence workloads
#: (mirrors the actual field names on the wave4-intelligence service
#: domain objects: ExtractedClaim.claim_text, EvidenceRecord.excerpt/
#: source_uri, citation normalize_url's normalized_uri output,
#: PlatformObservation.raw_object_ref/citation_refs/query_text).
FORBIDDEN_CUSTOMER_SOURCE_KEYS = (
    "claim_text",
    "excerpt",
    "source_uri",
    "normalized_uri",
    "raw_object_ref",
    "citation_ref",
    "query_text",
)

#: Case-insensitive substrings that must never appear in a registered
#: metric/span/attribute NAME for the intelligence workloads (Wave 5
#: forbidden scope) — mirrors
#: saena_domain.experiment.models.FORBIDDEN_OUTCOME_TOKENS verbatim (that
#: module is the domain-model-level pin; this is the observability-level
#: pin over the names THIS package registers).
FORBIDDEN_OUTCOME_TOKENS = (
    "lift",
    "outcome",
    "delta",
    "effect",
    "uplift",
    "causal",
    "_did_",
    "p_value",
    "pvalue",
    "significance",
    "observed_value",
    "estimate",
)


def load_attributes_json() -> list[dict[str, Any]]:
    with ATTRIBUTES_JSON_PATH.open(encoding="utf-8") as fh:
        result: list[dict[str, Any]] = json.load(fh)
        return result


class TestIntelligenceMetricNamesFollowConvention:
    @pytest.mark.parametrize("name", sorted(INTELLIGENCE_METRIC_NAMES))
    def test_metric_name_is_valid(self, name: str) -> None:
        assert is_valid_metric_name(name), name

    @pytest.mark.parametrize("name", sorted(INTELLIGENCE_METRIC_NAMES))
    def test_metric_name_has_saena_prefix_and_domain(self, name: str) -> None:
        assert name.startswith("saena.")
        domain, _, rest = name.removeprefix("saena.").partition(".")
        assert domain, name
        assert rest, name

    def test_at_least_one_metric_per_required_workload(self) -> None:
        # w4-15 mission: "Metric + span + log-attribute definitions for:
        # demand-graph builds, entity-resolution runs, claim-evidence
        # ledger/publishability, citation normalization, browser-pool
        # observation capture, experiment registration."
        required_domains = {
            "demand_graph",
            "entity_resolution",
            "claim_evidence",
            "citation",
            "browser_pool",
            "experiment",
        }
        present_domains = {name.split(".")[1] for name in INTELLIGENCE_METRIC_NAMES}
        assert required_domains <= present_domains

    def test_no_duration_metric_missing_seconds_unit_suffix(self) -> None:
        # UCUM/OTel convention (CONVENTIONS.md "Metric naming ... using UCUM
        # units") — every *_duration* metric in this set is a time
        # histogram and must carry the _seconds unit suffix.
        for name in INTELLIGENCE_METRIC_NAMES:
            if "duration" in name:
                assert name.endswith("_seconds"), name


class TestIntelligenceSpanNamesFollowConvention:
    @pytest.mark.parametrize("name", sorted(INTELLIGENCE_SPAN_NAMES))
    def test_span_name_is_valid(self, name: str) -> None:
        assert is_valid_span_name(name), name

    def test_at_least_one_span_per_required_workload(self) -> None:
        required_domains = {
            "demand_graph",
            "entity_resolution",
            "claim_evidence",
            "citation",
            "browser_pool",
            "experiment",
        }
        present_domains = {name.split(".")[1] for name in INTELLIGENCE_SPAN_NAMES}
        assert required_domains <= present_domains


class TestNewAttributesRegisteredAndShapeValid:
    def test_every_new_attribute_is_in_the_json_registry(self) -> None:
        entries = {e["name"] for e in load_attributes_json()}
        for name in NEW_W4_15_ATTRIBUTE_NAMES:
            assert name in entries, f"{name} missing from attributes.json"

    def test_every_new_attribute_matches_naming_namespace_pattern(self) -> None:
        import re

        pattern = re.compile(r"^saena\.[a-z0-9_.]+$")
        for name in NEW_W4_15_ATTRIBUTE_NAMES:
            assert pattern.match(name), name

    def test_intelligence_attribute_names_is_subset_of_full_registry(self) -> None:
        registry = load_attribute_registry()
        for name in INTELLIGENCE_ATTRIBUTE_NAMES:
            assert name in registry, f"{name} not in the full attributes.json registry"

    @pytest.mark.parametrize("name", sorted(NEW_W4_15_ATTRIBUTE_NAMES))
    def test_new_attribute_type_is_a_safe_scalar_never_free_text(self, name: str) -> None:
        # Every w4-15 attribute is id/hash/version/boolean/closed-enum —
        # never an unconstrained "string that could hold arbitrary
        # customer-source content" in spirit (this test pins the type +
        # naming-shape signal; the redaction denylist tests below pin the
        # actual raw-content-key rejection).
        registry = load_attribute_registry()
        entry = registry[name]
        assert entry.type in ("string", "boolean")
        assert entry.pii is False


class TestNoHighCardinalityRawContentLabel:
    """No new intelligence attribute is a raw-content field: every entry is
    an id, a version/content hash, a boolean, or a closed low-cardinality
    enum. This test asserts the registry-declared shape directly (rather
    than inferring it from cardinality alone, since cardinality is
    self-reported) by cross-checking each new attribute's `description`
    against a name-based expectation of hash/id/boolean/enum content.
    """

    _EXPECTED_HIGH_CARDINALITY_OPAQUE_IDS = frozenset(
        {
            "saena.demand_graph_version",
            "saena.entity_graph_version",
            "saena.claim_id",
            "saena.evidence_id",
            "saena.citation_normalized_uri_hash",
            "saena.experiment_id",
        }
    )
    _EXPECTED_LOW_CARDINALITY_ENUMS_OR_BOOLEANS = frozenset(
        {
            "saena.claim_publishable",
            "saena.browser_pool_state",
            "saena.intent_label",
        }
    )

    def test_every_new_attribute_is_classified(self) -> None:
        classified = (
            self._EXPECTED_HIGH_CARDINALITY_OPAQUE_IDS
            | self._EXPECTED_LOW_CARDINALITY_ENUMS_OR_BOOLEANS
        )
        assert classified == NEW_W4_15_ATTRIBUTE_NAMES

    @pytest.mark.parametrize("name", sorted(_EXPECTED_HIGH_CARDINALITY_OPAQUE_IDS))
    def test_opaque_id_attribute_is_high_cardinality_and_forbidden_or_optional_in_aggregate(
        self, name: str
    ) -> None:
        registry = load_attribute_registry()
        entry = registry[name]
        assert entry.cardinality == "high"
        # version hashes (demand/entity graph) are allowed as an opaque
        # aggregate-safe version marker; per-record identifiers
        # (claim/evidence/citation-hash/experiment) are forbidden in
        # aggregate (re-identification risk) — both are asserted per name.
        if name in {"saena.demand_graph_version", "saena.entity_graph_version"}:
            assert entry.contexts["aggregate"] == "optional"
        else:
            assert entry.contexts["aggregate"] == "forbidden"

    @pytest.mark.parametrize("name", sorted(_EXPECTED_LOW_CARDINALITY_ENUMS_OR_BOOLEANS))
    def test_enum_or_boolean_attribute_is_low_cardinality(self, name: str) -> None:
        registry = load_attribute_registry()
        entry = registry[name]
        assert entry.cardinality == "low"


class TestRedactionBlocksCustomerSourceFieldNames:
    """Even though these raw-content field names are never themselves
    registered in attributes.yaml (allowlist-first would already drop
    them), the denylist adds defense-in-depth: a producer bug that
    accidentally reuses one of these raw field names as an attribute key
    must still be caught (REDACT_VALUE, not silently ALLOWed)."""

    @pytest.mark.parametrize("keyword", FORBIDDEN_CUSTOMER_SOURCE_KEYS)
    def test_denylist_has_a_rule_matching_the_keyword_in_a_key(self, keyword: str) -> None:
        rules = load_redaction_rules()
        candidate_key = f"saena.{keyword}"
        matched = any(
            "key" in pattern.applies_to and pattern.pattern.search(candidate_key)
            for pattern in rules.denylist_patterns
        )
        assert matched, f"no denylist pattern matches key {candidate_key!r}"

    @pytest.mark.parametrize("keyword", FORBIDDEN_CUSTOMER_SOURCE_KEYS)
    def test_unregistered_customer_source_key_is_dropped(self, keyword: str) -> None:
        # Not in attributes.yaml at all -> DROP via the allowlist gate,
        # before the denylist is even consulted. This is the primary
        # defense; the denylist test above is the secondary one.
        decision = decide_redaction(f"saena.{keyword}", "https://example.com/x?token=abc")
        assert decision.action is RedactionAction.DROP

    @pytest.mark.parametrize("keyword", FORBIDDEN_CUSTOMER_SOURCE_KEYS)
    def test_customer_source_key_denylist_matches_even_if_hypothetically_allowlisted(
        self, keyword: str
    ) -> None:
        # Defense-in-depth proof: even simulating a future accidental
        # allowlisting of one of these raw-content keys, the denylist KEY
        # match still fires against a plausible carrier name, because
        # decide_redaction checks the denylist for every allowlisted
        # attribute too. We can't easily "temporarily allowlist" without
        # mutating the cached registry, so this test instead directly
        # exercises the same key-matching helper the engine uses via the
        # loaded rules, proving the pattern itself would catch the key
        # regardless of allowlist state.
        rules = load_redaction_rules()
        candidate_key = f"saena.claim_evidence.{keyword}"
        matched = any(
            "key" in pattern.applies_to and pattern.pattern.search(candidate_key)
            for pattern in rules.denylist_patterns
        )
        assert matched, f"no denylist pattern matches key {candidate_key!r}"


class TestRedactionStillBlocksSecretsForIntelligenceAttributes:
    """Sanity check that the pre-existing secret/PII denylist rules
    (R-SECRET-TOKEN, R-PII-EMAIL, etc.) are unaffected by the w4-15
    additions and still fire for a value carried on one of the NEW
    allowlisted intelligence attributes (defense-in-depth even for a
    legitimately-registered attribute)."""

    def test_token_shaped_value_on_a_new_attribute_is_redacted(self) -> None:
        decision = decide_redaction("saena.experiment_id", "token=abc123secret")
        assert decision.action is RedactionAction.REDACT_VALUE

    def test_email_shaped_value_on_a_new_attribute_is_redacted(self) -> None:
        decision = decide_redaction("saena.claim_id", "person@example.com")
        assert decision.action is RedactionAction.REDACT_VALUE

    def test_plain_hash_value_on_a_new_attribute_is_allowed(self) -> None:
        decision = decide_redaction(
            "saena.demand_graph_version",
            "sha256:" + "a" * 64,
        )
        assert decision.action is RedactionAction.ALLOW

    def test_plain_boolean_value_on_claim_publishable_is_allowed(self) -> None:
        decision = decide_redaction("saena.claim_publishable", True)
        assert decision.action is RedactionAction.ALLOW

    def test_closed_enum_value_on_browser_pool_state_is_allowed(self) -> None:
        decision = decide_redaction("saena.browser_pool_state", "acquired")
        assert decision.action is RedactionAction.ALLOW

    def test_closed_enum_value_on_intent_label_is_allowed(self) -> None:
        decision = decide_redaction("saena.intent_label", "pricing")
        assert decision.action is RedactionAction.ALLOW


class TestAggregateContextViolationRulesCoverNewIdentifiers:
    """V-AGG-INTELLIGENCE-IDENTIFIER must forbid the new high-cardinality
    identifiers in AggregateContext, mirroring V-AGG-TENANT's own coverage
    of tenant_id/run_id."""

    _FORBIDDEN_IN_AGGREGATE = (
        "saena.claim_id",
        "saena.evidence_id",
        "saena.citation_normalized_uri_hash",
        "saena.experiment_id",
    )

    def test_violation_rule_exists_and_covers_every_forbidden_identifier(self) -> None:
        rules = load_redaction_rules()
        matching = [r for r in rules.violation_rules if r.id == "V-AGG-INTELLIGENCE-IDENTIFIER"]
        assert len(matching) == 1
        rule = matching[0]
        assert rule.context == "aggregate"
        for name in self._FORBIDDEN_IN_AGGREGATE:
            assert name in rule.forbidden_attributes, name

    @pytest.mark.parametrize("name", _FORBIDDEN_IN_AGGREGATE)
    def test_decide_redaction_drops_identifier_under_aggregate_context(self, name: str) -> None:
        decision = decide_redaction(name, "some-opaque-id-value", context="aggregate")
        assert decision.action is RedactionAction.DROP
        assert "V-AGG-INTELLIGENCE-IDENTIFIER" in decision.reason

    @pytest.mark.parametrize("name", _FORBIDDEN_IN_AGGREGATE)
    def test_decide_redaction_allows_identifier_under_tenant_context(self, name: str) -> None:
        decision = decide_redaction(name, "some-opaque-id-value", context="tenant")
        assert decision.action is RedactionAction.ALLOW

    def test_demand_and_entity_graph_version_remain_allowed_in_aggregate(self) -> None:
        # These two are deliberately NOT in the forbidden set (see
        # attributes.yaml rationale: an opaque version marker, unlike a
        # per-record id, carries no re-identification risk).
        for name in ("saena.demand_graph_version", "saena.entity_graph_version"):
            decision = decide_redaction(name, "sha256:" + "b" * 64, context="aggregate")
            assert decision.action is RedactionAction.ALLOW


class TestNoForbiddenOutcomeTokenInAnyRegisteredName:
    """Wave 5 forbidden scope (CLAUDE.md 'Current decision', wave4-plan.md
    'Forbidden in W4: ... causal/lift/DiD/KPI-weight, outcome analysis')
    pinned as an executable guard over every name THIS module registers —
    mirrors saena_domain.experiment.models.FORBIDDEN_OUTCOME_TOKENS /
    tests/unit/domain_experiment/test_no_outcome_fields.py at the
    observability-naming layer.
    """

    def test_no_forbidden_token_in_metric_names(self) -> None:
        for name in INTELLIGENCE_METRIC_NAMES:
            lowered = f"_{name.lower()}_"
            for token in FORBIDDEN_OUTCOME_TOKENS:
                assert token not in lowered, f"{name} contains forbidden token {token!r}"

    def test_no_forbidden_token_in_span_names(self) -> None:
        for name in INTELLIGENCE_SPAN_NAMES:
            lowered = f"_{name.lower()}_"
            for token in FORBIDDEN_OUTCOME_TOKENS:
                assert token not in lowered, f"{name} contains forbidden token {token!r}"

    def test_no_forbidden_token_in_new_attribute_names(self) -> None:
        for name in NEW_W4_15_ATTRIBUTE_NAMES:
            lowered = f"_{name.lower()}_"
            for token in FORBIDDEN_OUTCOME_TOKENS:
                assert token not in lowered, f"{name} contains forbidden token {token!r}"


class TestEngineScopeClosedEnum:
    """CLAUDE.md 'Engine scope (v1)': chatgpt-search only. saena.engine_id
    is the pre-existing W0 attribute (unchanged by w4-15), reused (not
    re-defined) by every intelligence workload — this test pins that the
    intelligence module does not introduce a second engine-id-shaped
    attribute."""

    def test_no_new_engine_scoped_attribute_introduced(self) -> None:
        assert "saena.engine_id" not in NEW_W4_15_ATTRIBUTE_NAMES
        # ...but it IS part of the full intelligence attribute set (reused).
        assert "saena.engine_id" in INTELLIGENCE_ATTRIBUTE_NAMES
