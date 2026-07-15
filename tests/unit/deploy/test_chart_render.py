"""`helm template` rendering assertions for the saena-forge chart (w2-23).

Requires the `helm` binary on PATH (present in this dev environment). These
tests shell out to the real `helm` CLI rather than reimplementing template
evaluation — the chart's actual rendering behavior is the thing under test,
so a Python-side Jinja/Go-template re-implementation would not prove
anything about the real artifact.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None, reason="helm binary not available on PATH"
)


def _run_helm_template(chart_dir: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["helm", "template", "saena-forge", str(chart_dir), *extra_args],
        capture_output=True,
        text=True,
        check=False,
    )


class TestHelmLintClean:
    def test_helm_lint_passes(self, chart_dir: Path) -> None:
        result = subprocess.run(
            ["helm", "lint", str(chart_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr


class TestHelmTemplateRendersCleanly:
    def test_default_values_render_without_error(self, chart_dir: Path) -> None:
        result = _run_helm_template(chart_dir)
        assert result.returncode == 0, result.stderr

    def test_renders_all_8_service_deployments(self, chart_dir: Path) -> None:
        result = _run_helm_template(chart_dir)
        docs = [d for d in yaml.safe_load_all(result.stdout) if d]
        deployments = [d for d in docs if d.get("kind") == "Deployment"]
        # 8 pre-Wave-4 independent-deployment services + 2 w4-14 intelligence
        # workloads (intelligence-worker, chatgpt-observer coordinator) = 10
        # — service-catalog.md v1 topology: "total Deployment 10 = independent
        # 8 + worker host 2 (compute pool)". Detailed per-workload assertions
        # for the 2 new Deployments live in
        # tests/unit/deploy/test_intelligence_workloads.py (w4-14).
        assert len(deployments) == 12  # 8 pre-Wave-4 + 2 w4-14 + 2 w5-21

    def test_renders_8_services_and_8_pdbs_and_13_service_accounts(self, chart_dir: Path) -> None:
        result = _run_helm_template(chart_dir)
        docs = [d for d in yaml.safe_load_all(result.stdout) if d]
        kinds: dict[str, int] = {}
        for d in docs:
            kinds[d["kind"]] = kinds.get(d["kind"], 0) + 1
        # 8 pre-Wave-4 + 2 w4-14 (intelligence-worker, chatgpt-observer) = 10
        # (this test's name keeps its original w2-23 title for history/diff
        # continuity; the counts below are the current, w4-14-updated ones —
        # see test_intelligence_workloads.py for the itemized w4-14 proof).
        assert kinds["Service"] == 12
        assert kinds["PodDisruptionBudget"] == 12
        # 12 service SAs (8 control-plane + 2 w4-14 + 2 w5-21 measurement) +
        # agent-runner + ADR-0004 SA 3-separation (quality-eval,
        # repository-intake) + browser pool (chatgpt-observer Job SA,
        # site-discovery) = 17 — see tests/unit/deploy/test_service_accounts.py
        # (w3-07), test_intelligence_workloads.py (w4-14), and
        # test_measurement_workloads.py (w5-21) for the detailed per-SA
        # assertions this count summarizes.
        assert kinds["ServiceAccount"] == 17
        # Role/RoleBinding count is UNCHANGED at 9 — neither w4-14 workload
        # adds a new Role: intelligenceWorker has empty rbac.rules (zero K8s
        # API need) and chatgptObserver's coordinator SA is deliberately
        # READ-ONLY (rbac.rules: [] — Job launch/poll/cleanup stays solely
        # on agentOrchestrator's existing Role). Least-privilege-by-omission
        # (templates/rbac/execution-jobs-roles.yaml's convention, extended
        # by w4-14 to templates/rbac/service-roles.yaml too), not an
        # oversight.
        assert kinds["Role"] == 9
        assert kinds["RoleBinding"] == 9

    def test_renders_3_system_namespaces(self, chart_dir: Path) -> None:
        result = _run_helm_template(chart_dir)
        docs = [d for d in yaml.safe_load_all(result.stdout) if d]
        namespaces = {d["metadata"]["name"] for d in docs if d.get("kind") == "Namespace"}
        assert namespaces == {"saena-system", "saena-data", "saena-observability"}

    def test_renders_default_deny_network_policies(self, chart_dir: Path) -> None:
        result = _run_helm_template(chart_dir)
        docs = [d for d in yaml.safe_load_all(result.stdout) if d]
        default_deny = [
            d
            for d in docs
            if d.get("kind") == "NetworkPolicy" and d["metadata"]["name"] == "default-deny-all"
        ]
        # saena-system, saena-data, saena-observability (no tenants by default)
        assert len(default_deny) == 3
        for np in default_deny:
            assert np["spec"]["podSelector"] == {}
            assert set(np["spec"]["policyTypes"]) == {"Ingress", "Egress"}

    def test_renders_6_dashboard_configmaps(self, chart_dir: Path) -> None:
        result = _run_helm_template(chart_dir)
        docs = [d for d in yaml.safe_load_all(result.stdout) if d]
        dashboard_cms = [
            d
            for d in docs
            if d.get("kind") == "ConfigMap"
            and d["metadata"]["name"].startswith("saena-forge-dashboard-")
        ]
        assert len(dashboard_cms) == 6
        sidecar_label = "grafana_dashboard"
        for cm in dashboard_cms:
            assert cm["metadata"]["labels"].get(sidecar_label) == "1"
            assert cm["metadata"]["namespace"] == "saena-observability"

    def test_no_clusterrole_or_clusterrolebinding_rendered(self, chart_dir: Path) -> None:
        result = _run_helm_template(chart_dir)
        docs = [d for d in yaml.safe_load_all(result.stdout) if d]
        kinds = {d["kind"] for d in docs}
        assert "ClusterRole" not in kinds
        assert "ClusterRoleBinding" not in kinds

    def test_no_rbac_rule_uses_wildcard_verb_or_resource(self, chart_dir: Path) -> None:
        result = _run_helm_template(chart_dir)
        docs = [d for d in yaml.safe_load_all(result.stdout) if d]
        roles = [d for d in docs if d.get("kind") == "Role"]
        assert len(roles) >= 1
        for role in roles:
            for rule in role.get("rules", []):
                assert "*" not in rule.get("verbs", [])
                assert "*" not in rule.get("resources", [])

    def test_every_container_security_context_is_hardened(self, chart_dir: Path) -> None:
        result = _run_helm_template(chart_dir)
        docs = [d for d in yaml.safe_load_all(result.stdout) if d]
        deployments = [d for d in docs if d.get("kind") == "Deployment"]
        assert len(deployments) == 12  # 8 pre-Wave-4 + 2 w4-14 + 2 w5-21
        for dep in deployments:
            for container in dep["spec"]["template"]["spec"]["containers"]:
                sc = container["securityContext"]
                assert sc["runAsNonRoot"] is True
                assert sc["readOnlyRootFilesystem"] is True
                assert sc["allowPrivilegeEscalation"] is False
                assert "ALL" in sc["capabilities"]["drop"]
                assert sc["seccompProfile"]["type"] == "RuntimeDefault"

    def test_every_deployment_image_is_digest_referenced_not_tag(self, chart_dir: Path) -> None:
        result = _run_helm_template(chart_dir)
        docs = [d for d in yaml.safe_load_all(result.stdout) if d]
        deployments = [d for d in docs if d.get("kind") == "Deployment"]
        for dep in deployments:
            for container in dep["spec"]["template"]["spec"]["containers"]:
                image = container["image"]
                assert "@sha256:" in image, image
                assert not image.rsplit("@", 1)[0].count(":") or "@" in image


class TestGoogleFlagRendersFailure:
    def test_gemini_enabled_via_set_fails_schema_validation(self, chart_dir: Path) -> None:
        result = _run_helm_template(
            chart_dir,
            "--set",
            "global.engineScope.gemini=true",
        )
        assert result.returncode != 0
        assert "engineScope" in result.stderr or "gemini" in result.stderr

    def test_google_key_enabled_via_values_file_fails(self, chart_dir: Path, tmp_path: Any) -> None:
        override = tmp_path / "google-on.yaml"
        override.write_text(
            yaml.safe_dump({"global": {"engineScope": {"chatgptSearch": True, "google": True}}}),
            encoding="utf-8",
        )
        result = _run_helm_template(chart_dir, "-f", str(override))
        assert result.returncode != 0
