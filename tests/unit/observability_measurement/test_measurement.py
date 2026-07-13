"""Wave 5 (Measurement / B-layer) observability tests — w5-17.

Mirrors the w4-15 `test_intelligence.py` conventions and covers the w5-17
mission's explicit gate list:

- new metric/span names follow the naming convention
  (`saena.<domain>.<name>` / `saena.<capability>.<operation>`), UCUM unit
  suffixes valid (`*_total` counters, `*_duration_seconds` histograms);
- every new attribute is registered in attributes.json, matches the
  namespace pattern, and is an id/hash/closed-enum — NEVER raw
  customer-source content;
- redaction blocks measurement raw-content/identity field names
  (confirmer_identity / reason_message / evidence_snapshot / query_text)
  even when passed as an attribute key, and still blocks the pre-existing
  secret/PII shapes on the new allowlisted attributes;
- low-cardinality label enums are CLOSED and bounded: verdict is EXACTLY
  three values (pass|fail|undetermined); reason_code/grs_decision/
  intake_decision are bounded closed enums;
- the aggregate-context tenant_id exclusion rule (V-AGG-TENANT) is intact,
  and a parallel V-AGG-MEASUREMENT-IDENTIFIER forbids the new
  high-cardinality measurement identifiers in aggregate;
- no outcome/effect/lift MAGNITUDE token appears in any new metric/span/
  attribute name (the `did` OPERATION-name token is deliberately allowed,
  because deterministic DiD is an in-scope Wave-5 deliverable — this test
  pins both halves of that distinction).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from saena_observability.measurement import (
    FORBIDDEN_OUTCOME_MAGNITUDE_TOKENS,
    MEASUREMENT_ATTRIBUTE_NAMES,
    MEASUREMENT_METRIC_NAMES,
    MEASUREMENT_SPAN_NAMES,
    MEASUREMENT_VERDICT_ENUM,
)
from saena_observability.naming import is_valid_metric_name, is_valid_span_name
from saena_observability.redaction import RedactionAction, decide_redaction
from saena_observability.registry import load_attribute_registry, load_redaction_rules

REGISTRY_DIR = Path(__file__).resolve().parents[3] / "packages" / "observability" / "registry"
ATTRIBUTES_JSON_PATH = REGISTRY_DIR / "attributes.json"

#: The seven new w5-17 attribute names (a strict subset of
#: MEASUREMENT_ATTRIBUTE_NAMES, which also includes the reused W0 core set +
#: saena.experiment_id).
NEW_W5_17_ATTRIBUTE_NAMES = frozenset(
    {
        "saena.measurement.window_id",
        "saena.measurement.verdict",
        "saena.measurement.reason_code",
        "saena.measurement.grs_decision",
        "saena.measurement.intake_decision",
        "saena.measurement.evidence_bundle_id",
        "saena.measurement.evidence_bundle_hash",
    }
)

#: The exactly-three closed verdict enum (Algorithm §3.7-5 / w5-06).
CLOSED_VERDICT_VALUES = frozenset({"pass", "fail", "undetermined"})

#: Raw-content / identity field names that must NEVER be a measurement
#: telemetry attribute key.
FORBIDDEN_MEASUREMENT_RAW_KEYS = (
    "confirmer_identity",
    "reason_message",
    "evidence_snapshot",
    "evidence_content",
    "bundle_content",
    "snapshot_content",
    "query_text",
)

_NAMESPACE_RE = re.compile(r"^saena\.[a-z0-9_.]+$")


def load_attributes_json() -> list[dict[str, Any]]:
    with ATTRIBUTES_JSON_PATH.open(encoding="utf-8") as fh:
        result: list[dict[str, Any]] = json.load(fh)
        return result


class TestMeasurementMetricNamesFollowConvention:
    @pytest.mark.parametrize("name", sorted(MEASUREMENT_METRIC_NAMES))
    def test_metric_name_is_valid(self, name: str) -> None:
        assert is_valid_metric_name(name), name

    @pytest.mark.parametrize("name", sorted(MEASUREMENT_METRIC_NAMES))
    def test_metric_name_has_saena_prefix_and_domain(self, name: str) -> None:
        assert name.startswith("saena.")
        domain, _, rest = name.removeprefix("saena.").partition(".")
        assert domain == "measurement", name
        assert rest, name

    def test_counter_metrics_carry_total_ucum_suffix(self) -> None:
        # Every counter in this set must carry the OTel/UCUM `_total`
        # suffix; every duration histogram must carry `_seconds`. A metric
        # that is neither a `_total` counter nor a `_duration_seconds`
        # histogram is a gauge (none in this set today) — assert the two
        # suffix families are internally consistent.
        for name in MEASUREMENT_METRIC_NAMES:
            if "duration" in name:
                assert name.endswith("_duration_seconds"), name
            else:
                assert name.endswith("_total"), name

    def test_at_least_one_metric_per_required_measurement_workload(self) -> None:
        # w5-17 mission: metrics for windows-started, b-verdicts,
        # undetermined-reasons, did-signals-evaluated,
        # confirmations-rejected, evidence-bundles-sealed (+ grs, intake).
        present = {n for n in MEASUREMENT_METRIC_NAMES}
        required = {
            "saena.measurement.windows_started_total",
            "saena.measurement.b_verdicts_total",
            "saena.measurement.undetermined_reasons_total",
            "saena.measurement.did_signals_evaluated_total",
            "saena.measurement.confirmations_rejected_total",
            "saena.measurement.evidence_bundles_sealed_total",
            "saena.measurement.grs_eligibility_evaluated_total",
            "saena.measurement.skill_bank_intake_total",
        }
        missing = required - present
        assert not missing, f"missing required measurement metrics: {sorted(missing)}"


class TestMeasurementSpanNamesFollowConvention:
    @pytest.mark.parametrize("name", sorted(MEASUREMENT_SPAN_NAMES))
    def test_span_name_is_valid(self, name: str) -> None:
        assert is_valid_span_name(name), name

    def test_required_measurement_spans_present(self) -> None:
        required = {
            "saena.measurement.confirm_deployment",
            "saena.measurement.start_window",
            "saena.measurement.compute_did_attribution",
            "saena.measurement.decide_b_gate",
            "saena.measurement.seal_evidence_bundle",
            "saena.measurement.grs_eligibility",
            "saena.measurement.skill_bank_intake",
        }
        missing = required - MEASUREMENT_SPAN_NAMES
        assert not missing, f"missing required measurement spans: {sorted(missing)}"


class TestNewAttributesRegisteredAndShapeValid:
    def test_every_new_attribute_is_in_the_json_registry(self) -> None:
        entries = {e["name"] for e in load_attributes_json()}
        for name in NEW_W5_17_ATTRIBUTE_NAMES:
            assert name in entries, f"{name} missing from attributes.json"

    @pytest.mark.parametrize("name", sorted(NEW_W5_17_ATTRIBUTE_NAMES))
    def test_new_attribute_matches_naming_namespace_pattern(self, name: str) -> None:
        assert _NAMESPACE_RE.match(name), name

    def test_measurement_attribute_names_is_subset_of_full_registry(self) -> None:
        registry = load_attribute_registry()
        for name in MEASUREMENT_ATTRIBUTE_NAMES:
            assert name in registry, f"{name} not in the full attributes.json registry"

    def test_new_attributes_are_subset_of_measurement_attribute_names(self) -> None:
        assert NEW_W5_17_ATTRIBUTE_NAMES <= MEASUREMENT_ATTRIBUTE_NAMES

    @pytest.mark.parametrize("name", sorted(NEW_W5_17_ATTRIBUTE_NAMES))
    def test_new_attribute_type_is_a_safe_scalar_never_free_text(self, name: str) -> None:
        # Every w5-17 attribute is an id / content hash / closed-enum
        # string — never an unconstrained free-text field. pii is always
        # False.
        registry = load_attribute_registry()
        entry = registry[name]
        assert entry.type == "string"
        assert entry.pii is False

    def test_experiment_id_is_reused_not_redefined(self) -> None:
        # A measurement runs against a pre-registered experiment; it REUSES
        # saena.experiment_id (w4-15) rather than defining a second
        # experiment-id-shaped attribute.
        assert "saena.experiment_id" in MEASUREMENT_ATTRIBUTE_NAMES
        assert "saena.experiment_id" not in NEW_W5_17_ATTRIBUTE_NAMES


class TestLowCardinalityLabelEnumsAreClosed:
    """verdict must be EXACTLY three values; reason_code / grs_decision /
    intake_decision are bounded closed enums. These are the low-cardinality
    label attributes that partition the measurement counters."""

    _LOW_CARDINALITY_ENUMS = (
        "saena.measurement.verdict",
        "saena.measurement.reason_code",
        "saena.measurement.grs_decision",
        "saena.measurement.intake_decision",
    )

    @pytest.mark.parametrize("name", _LOW_CARDINALITY_ENUMS)
    def test_enum_attribute_is_low_cardinality(self, name: str) -> None:
        registry = load_attribute_registry()
        assert registry[name].cardinality == "low"

    def test_verdict_description_pins_exactly_three_closed_values(self) -> None:
        # The verdict enum is EXACTLY pass|fail|undetermined (Algorithm
        # §3.7-5, w5-06). The registry description is the human-readable
        # contract; assert every one of the three values is named and no
        # fourth verdict word has crept in.
        registry = load_attribute_registry()
        desc = registry["saena.measurement.verdict"].description.lower()
        for value in CLOSED_VERDICT_VALUES:
            assert value in desc, f"verdict value {value!r} missing from description"
        # A verdict must never be a numeric strength/magnitude — pin that
        # the description forbids it explicitly.
        assert "magnitude" in desc or "strength" in desc

    def test_grs_decision_is_fail_closed_deny_default(self) -> None:
        registry = load_attribute_registry()
        desc = registry["saena.measurement.grs_decision"].description.lower()
        assert "deny" in desc
        assert "fail-closed" in desc

    def test_high_cardinality_identifiers_are_marked_high(self) -> None:
        registry = load_attribute_registry()
        for name in (
            "saena.measurement.window_id",
            "saena.measurement.evidence_bundle_id",
            "saena.measurement.evidence_bundle_hash",
        ):
            assert registry[name].cardinality == "high", name


class TestRedactionBlocksMeasurementRawContentKeys:
    """A producer bug that reuses a raw measurement field name
    (confirmer_identity / reason_message / evidence_snapshot / query_text)
    as an attribute key must be caught: dropped by the allowlist gate
    (primary) and matched by a denylist key rule (defense-in-depth)."""

    @pytest.mark.parametrize("keyword", FORBIDDEN_MEASUREMENT_RAW_KEYS)
    def test_denylist_has_a_rule_matching_the_keyword_in_a_key(self, keyword: str) -> None:
        rules = load_redaction_rules()
        candidate_key = f"saena.measurement.{keyword}"
        matched = any(
            "key" in pattern.applies_to and pattern.pattern.search(candidate_key)
            for pattern in rules.denylist_patterns
        )
        assert matched, f"no denylist pattern matches key {candidate_key!r}"

    @pytest.mark.parametrize("keyword", FORBIDDEN_MEASUREMENT_RAW_KEYS)
    def test_unregistered_raw_key_is_dropped_by_allowlist(self, keyword: str) -> None:
        decision = decide_redaction(f"saena.measurement.{keyword}", "some raw value with token=abc")
        assert decision.action is RedactionAction.DROP

    def test_reason_code_is_allowed_but_reason_message_is_not(self) -> None:
        # The closed CODE is telemetry-safe; the free-text MESSAGE is not.
        code = decide_redaction("saena.measurement.reason_code", "single-layer")
        assert code.action is RedactionAction.ALLOW
        message = decide_redaction(
            "saena.measurement.reason_message", "rejected because confirmer bob@x.com"
        )
        assert message.action is RedactionAction.DROP


class TestRedactionStillBlocksSecretsForMeasurementAttributes:
    """The pre-existing secret/PII denylist (R-SECRET-TOKEN, R-PII-EMAIL)
    still fires for a value carried on one of the NEW allowlisted
    measurement attributes (defense-in-depth for a legitimate key)."""

    def test_token_shaped_value_on_a_new_attribute_is_redacted(self) -> None:
        decision = decide_redaction("saena.measurement.window_id", "token=abc123secret")
        assert decision.action is RedactionAction.REDACT_VALUE

    def test_email_shaped_value_on_a_new_attribute_is_redacted(self) -> None:
        decision = decide_redaction("saena.measurement.window_id", "person@example.com")
        assert decision.action is RedactionAction.REDACT_VALUE

    def test_plain_hash_value_on_bundle_hash_is_allowed(self) -> None:
        decision = decide_redaction("saena.measurement.evidence_bundle_hash", "sha256:" + "a" * 64)
        assert decision.action is RedactionAction.ALLOW

    def test_closed_enum_value_on_verdict_is_allowed(self) -> None:
        decision = decide_redaction("saena.measurement.verdict", "undetermined")
        assert decision.action is RedactionAction.ALLOW


class TestAggregateContextRules:
    """V-AGG-TENANT (tenant_id/run_id) must stay intact, and a parallel
    V-AGG-MEASUREMENT-IDENTIFIER must forbid the new high-cardinality
    measurement identifiers in AggregateContext while leaving the
    aggregate-safe hash + closed enums allowed."""

    _FORBIDDEN_IN_AGGREGATE = (
        "saena.measurement.window_id",
        "saena.measurement.evidence_bundle_id",
    )
    _ALLOWED_IN_AGGREGATE = (
        "saena.measurement.evidence_bundle_hash",
        "saena.measurement.verdict",
        "saena.measurement.reason_code",
        "saena.measurement.grs_decision",
        "saena.measurement.intake_decision",
    )

    def test_tenant_run_id_aggregate_exclusion_rule_intact(self) -> None:
        # The pre-existing V-AGG-TENANT rule must not have been disturbed.
        rules = load_redaction_rules()
        matching = [r for r in rules.violation_rules if r.id == "V-AGG-TENANT"]
        assert len(matching) == 1
        rule = matching[0]
        assert rule.context == "aggregate"
        assert "saena.tenant_id" in rule.forbidden_attributes
        assert "saena.run_id" in rule.forbidden_attributes

    def test_tenant_id_still_dropped_in_aggregate(self) -> None:
        decision = decide_redaction("saena.tenant_id", "tenant-xyz", context="aggregate")
        assert decision.action is RedactionAction.DROP
        assert "V-AGG-TENANT" in decision.reason

    def test_measurement_violation_rule_exists_and_covers_identifiers(self) -> None:
        rules = load_redaction_rules()
        matching = [r for r in rules.violation_rules if r.id == "V-AGG-MEASUREMENT-IDENTIFIER"]
        assert len(matching) == 1
        rule = matching[0]
        assert rule.context == "aggregate"
        for name in self._FORBIDDEN_IN_AGGREGATE:
            assert name in rule.forbidden_attributes, name
        # The aggregate-safe hash must NOT be in the forbidden set.
        assert "saena.measurement.evidence_bundle_hash" not in rule.forbidden_attributes

    @pytest.mark.parametrize("name", _FORBIDDEN_IN_AGGREGATE)
    def test_identifier_dropped_under_aggregate_context(self, name: str) -> None:
        decision = decide_redaction(name, "some-opaque-id", context="aggregate")
        assert decision.action is RedactionAction.DROP
        assert "V-AGG-MEASUREMENT-IDENTIFIER" in decision.reason

    @pytest.mark.parametrize("name", _FORBIDDEN_IN_AGGREGATE)
    def test_identifier_allowed_under_tenant_context(self, name: str) -> None:
        decision = decide_redaction(name, "some-opaque-id", context="tenant")
        assert decision.action is RedactionAction.ALLOW

    @pytest.mark.parametrize("name", _ALLOWED_IN_AGGREGATE)
    def test_aggregate_safe_attribute_allowed_in_aggregate(self, name: str) -> None:
        # Hash marker + closed enums are safe category/version labels in
        # de-identified aggregate rollups.
        value = "sha256:" + "b" * 64 if name.endswith("_hash") else "pass"
        decision = decide_redaction(name, value, context="aggregate")
        assert decision.action is RedactionAction.ALLOW

    def test_registry_marks_forbidden_identifiers_aggregate_forbidden(self) -> None:
        # The documentation-only `contexts` column must agree with the
        # executable violation rule (matching the w4-15 discipline).
        registry = load_attribute_registry()
        for name in self._FORBIDDEN_IN_AGGREGATE:
            assert registry[name].contexts["aggregate"] == "forbidden", name


class TestNoForbiddenOutcomeMagnitudeTokenInAnyName:
    """Outcome/effect/lift MAGNITUDE tokens must never appear in a
    registered measurement name (CLAUDE.md 'increase evidence not claim';
    wave5-plan.md 'Unverified external-lift claims' FORBIDDEN). The `did`
    OPERATION-name token is DELIBERATELY allowed (deterministic DiD is an
    in-scope Wave-5 deliverable) — this test pins BOTH halves."""

    def _lowered(self, name: str) -> str:
        return f"_{name.lower()}_"

    def test_no_magnitude_token_in_metric_names(self) -> None:
        for name in MEASUREMENT_METRIC_NAMES:
            lowered = self._lowered(name)
            for token in FORBIDDEN_OUTCOME_MAGNITUDE_TOKENS:
                assert token not in lowered, f"{name} contains forbidden token {token!r}"

    def test_no_magnitude_token_in_span_names(self) -> None:
        for name in MEASUREMENT_SPAN_NAMES:
            lowered = self._lowered(name)
            for token in FORBIDDEN_OUTCOME_MAGNITUDE_TOKENS:
                assert token not in lowered, f"{name} contains forbidden token {token!r}"

    def test_no_magnitude_token_in_new_attribute_names(self) -> None:
        for name in NEW_W5_17_ATTRIBUTE_NAMES:
            lowered = self._lowered(name)
            for token in FORBIDDEN_OUTCOME_MAGNITUDE_TOKENS:
                assert token not in lowered, f"{name} contains forbidden token {token!r}"

    def test_magnitude_value_tokens_are_forbidden(self) -> None:
        # The true magnitude-VALUE tokens stay banned.
        for token in ("lift", "uplift", "effect", "causal", "estimate", "p_value"):
            assert token in FORBIDDEN_OUTCOME_MAGNITUDE_TOKENS

    def test_critic_s1_widened_tokens_are_forbidden(self) -> None:
        # w5-17 critic S1: widened generic magnitude words (collision-checked).
        for token in ("value", "magnitude", "score", "point", "coefficient"):
            assert token in FORBIDDEN_OUTCOME_MAGNITUDE_TOKENS
        # `att` deliberately excluded — would false-positive the legitimate
        # span saena.measurement.compute_did_attribution.
        assert "att" not in FORBIDDEN_OUTCOME_MAGNITUDE_TOKENS
        # Adversarial names the widened set must now catch:
        for bad in ("did_value_total", "did_magnitude_total", "did_score_total"):
            lowered = f"_{bad.lower()}_"
            assert any(token in lowered for token in FORBIDDEN_OUTCOME_MAGNITUDE_TOKENS), bad

    def test_verdict_enum_is_executable_and_exactly_three(self) -> None:
        """w5-17 critic S2: the registry's closed-verdict claim is executable.

        The vocabulary owner is the domain layer (saena_domain.measurement
        .b_gate / .reason_codes); this pins the registry-side mirror so the
        attributes.yaml description cannot silently drift from the contract.
        """
        assert frozenset({"pass", "fail", "undetermined"}) == MEASUREMENT_VERDICT_ENUM
        # The registry description must name every enum member.
        entry = load_attribute_registry()["saena.measurement.verdict"]
        for member in MEASUREMENT_VERDICT_ENUM:
            assert member in entry.description, member

    def test_did_operation_token_is_deliberately_allowed(self) -> None:
        # `did` is NOT in the Wave-5 magnitude-token set (unlike Wave 4's
        # `_did_` ban) — deterministic DiD is an in-scope deliverable.
        assert "did" not in FORBIDDEN_OUTCOME_MAGNITUDE_TOKENS
        assert "_did_" not in FORBIDDEN_OUTCOME_MAGNITUDE_TOKENS
        # ...and at least one registered name legitimately uses it.
        assert any("did" in n for n in MEASUREMENT_METRIC_NAMES)
        assert any("did" in n for n in MEASUREMENT_SPAN_NAMES)


class TestEngineScopeAndNoNewEngineAttribute:
    """CLAUDE.md 'Engine scope (v1)': chatgpt-search only. The measurement
    module reuses saena.engine_id, never introduces a second
    engine-id-shaped attribute."""

    def test_engine_id_reused_not_redefined(self) -> None:
        assert "saena.engine_id" in MEASUREMENT_ATTRIBUTE_NAMES
        assert "saena.engine_id" not in NEW_W5_17_ATTRIBUTE_NAMES
