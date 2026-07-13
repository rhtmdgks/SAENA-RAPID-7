"""The 6 required dashboards (k3s spec §9.2) — dashboards-as-code JSON
model files under `deploy/charts/saena-forge/dashboards/`. Each must parse
as valid JSON, be a syntactically valid Grafana dashboard model (title +
panels), and every panel `targets[].expr` PromQL metric name must conform to
the `saena.<domain>.<name>` naming rule (ADR-0016 / `naming.py`) —
Prometheus name transforms (dots -> underscores, per
`packages/observability/CONVENTIONS.md` "Prometheus name transforms ... are
out of scope for W0 ... W2C exporter responsibility") are accounted for by
converting `saena_<domain>_<name>` back to dot form before validating.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

REQUIRED_DASHBOARDS = {
    "01-workflow.json": "Workflow",
    "02-safety.json": "Safety",
    "03-quality.json": "Quality",
    "04-aeo.json": "AEO",
    "05-cost.json": "Cost",
    "06-drift.json": "Drift",
}

# Extract every saena_<...> identifier a panel's PromQL expr references
# (metric names only — this does not attempt full PromQL parsing).
_METRIC_TOKEN_RE = re.compile(r"\bsaena_[a-z0-9_]+\b")

# saena_observability naming.py validates dotted `saena.<domain>.<name>`
# names; Prometheus exposition uses underscores, so metric-name tokens are
# converted dot-form first. Only the metric-shaped tokens (not attribute
# tokens like saena_tenant_id, which are labels, not metric names) are
# checked against the naming rule.
_ATTRIBUTE_LABEL_NAMES = {
    "saena_tenant_id",
    "saena_run_id",
    "saena_engine_id",
    "saena_context",
    "saena_patch_unit_id",
    "saena_contract_hash",
    "saena_policy_bundle_hash",
    "saena_aggregate_scope_id",
}


def _load_dashboard(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    return data


class TestAllSixDashboardsPresent:
    def test_exactly_the_six_required_files_exist(self, dashboards_dir: Path) -> None:
        found = {p.name for p in dashboards_dir.glob("*.json")}
        assert found == set(REQUIRED_DASHBOARDS)


@pytest.mark.parametrize("filename", sorted(REQUIRED_DASHBOARDS))
class TestEachDashboardParsesAndHasRequiredShape:
    def test_parses_as_json(self, dashboards_dir: Path, filename: str) -> None:
        _load_dashboard(dashboards_dir / filename)

    def test_has_title_and_uid(self, dashboards_dir: Path, filename: str) -> None:
        dashboard = _load_dashboard(dashboards_dir / filename)
        assert isinstance(dashboard.get("title"), str) and dashboard["title"]
        assert isinstance(dashboard.get("uid"), str) and dashboard["uid"]

    def test_title_matches_expected_theme(self, dashboards_dir: Path, filename: str) -> None:
        dashboard = _load_dashboard(dashboards_dir / filename)
        assert REQUIRED_DASHBOARDS[filename] in dashboard["title"]

    def test_has_at_least_one_panel(self, dashboards_dir: Path, filename: str) -> None:
        dashboard = _load_dashboard(dashboards_dir / filename)
        panels = dashboard.get("panels")
        assert isinstance(panels, list) and len(panels) >= 1

    def test_every_panel_has_id_title_type_gridpos(
        self, dashboards_dir: Path, filename: str
    ) -> None:
        dashboard = _load_dashboard(dashboards_dir / filename)
        for panel in dashboard["panels"]:
            assert isinstance(panel.get("id"), int)
            assert isinstance(panel.get("title"), str) and panel["title"]
            assert isinstance(panel.get("type"), str) and panel["type"]
            assert isinstance(panel.get("gridPos"), dict)

    def test_every_panel_has_at_least_one_target_with_a_promql_expr(
        self, dashboards_dir: Path, filename: str
    ) -> None:
        dashboard = _load_dashboard(dashboards_dir / filename)
        for panel in dashboard["panels"]:
            targets = panel.get("targets")
            assert isinstance(targets, list) and len(targets) >= 1
            for target in targets:
                assert isinstance(target.get("expr"), str) and target["expr"]

    def test_schema_version_present(self, dashboards_dir: Path, filename: str) -> None:
        dashboard = _load_dashboard(dashboards_dir / filename)
        assert isinstance(dashboard.get("schemaVersion"), int)


@pytest.mark.parametrize("filename", sorted(REQUIRED_DASHBOARDS))
def test_every_metric_name_referenced_conforms_to_saena_naming_rule(
    dashboards_dir: Path, filename: str
) -> None:
    """Every `saena_<domain>_<name>`-shaped metric token in a panel's PromQL
    expr, converted back to dotted form, must pass `is_valid_metric_name`
    (ADR-0016 `saena.<domain>.<name>` rule) — guards against inventing a
    metric name shape that contradicts the naming convention. Attribute/
    label tokens (saena_tenant_id etc., real registry entries used as
    PromQL label matchers/`by (...)` grouping keys, not metric names) are
    excluded.
    """
    from saena_observability.naming import is_valid_metric_name

    dashboard = _load_dashboard(dashboards_dir / filename)
    metric_tokens: set[str] = set()
    for panel in dashboard["panels"]:
        for target in panel.get("targets", []):
            expr = target.get("expr", "")
            for token in _METRIC_TOKEN_RE.findall(expr):
                if token in _ATTRIBUTE_LABEL_NAMES:
                    continue
                # Strip a trailing Prometheus histogram suffix so the base
                # metric name (as declared in dashboard docstrings/panel
                # descriptions, dotted form) is what gets checked — the
                # `_bucket` suffix is a Prometheus histogram exposition
                # convention (W2C exporter concern), not part of the OTel
                # metric name itself.
                base_token = token
                for suffix in ("_bucket", "_sum", "_count"):
                    if base_token.endswith(suffix):
                        base_token = base_token[: -len(suffix)]
                        break
                metric_tokens.add(base_token)

    assert metric_tokens, f"{filename}: no saena_* metric tokens found in any panel expr"
    for token in sorted(metric_tokens):
        # Reconstruct dotted `saena.<domain>.<name>` from
        # `saena_<domain>_<name>`: domain is the first underscore-delimited
        # segment after `saena_`, the remainder (which itself may contain
        # underscores, e.g. `lead_time_seconds`) is the `<name>` segment —
        # matches how every metric in this dashboard set was named.
        remainder = token[len("saena_") :]
        domain, _, name = remainder.partition("_")
        dotted = f"saena.{domain}.{name}"
        assert is_valid_metric_name(dotted), f"{filename}: {token!r} -> {dotted!r} is invalid"
