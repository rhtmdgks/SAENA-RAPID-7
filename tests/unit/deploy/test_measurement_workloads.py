"""Wave 5 measurement/B-layer workloads (w5-21) — `experiment-attribution`
(the measurement plane's worker-host Deployment: persistence + event boundary
+ fail-closed pipeline + durable Temporal measurement workflow worker, one
pod per ADR-0002 rev.3 module consolidation — no extraction trigger met) and
`strategy-skill-bank` (the B-verified-only intake boundary Deployment) added
to the saena-forge chart. Mirrors `tests/unit/deploy/test_intelligence_
workloads.py`: shells out to the real `helm` binary and asserts on the
rendered manifest rather than reimplementing Go-template evaluation.

Both workloads use the generic `.Values.services.<key>` shape (no per-service
`if` branch was added to any shared template), inherit the hardened
`serviceDefaults` security context (non-root, read-only root fs, drop-ALL
caps, seccomp RuntimeDefault, resource limits, liveness/readiness probes,
PDB), get a dedicated least-privilege ServiceAccount with ZERO Kubernetes API
access (`rbac.rules: []` -> no Role/RoleBinding, no ClusterRole), and connect
to the external Postgres/ClickHouse/Temporal/Redpanda + the new signed GRS
policy bundle purely via SecretRef env vars (never a plaintext value). Engine
scope stays ChatGPT Search only — enforced globally, asserted here for the
new workloads' env.
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

MEASUREMENT_FULLNAMES = {
    "experiment-attribution": "saena-forge-experiment-attribution",
    "strategy-skill-bank": "saena-forge-strategy-skill-bank",
}
MEASUREMENT_SA_NAMES = {
    "saena-forge-experiment-attribution-sa",
    "saena-forge-strategy-skill-bank-sa",
}


def _rendered_docs(chart_dir: Path, *extra_args: str) -> list[dict[str, Any]]:
    result = subprocess.run(
        ["helm", "template", "saena-forge", str(chart_dir), *extra_args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return [d for d in yaml.safe_load_all(result.stdout) if d]


def _measurement_deployments(docs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        d["metadata"]["name"]: d
        for d in docs
        if d["kind"] == "Deployment" and d["metadata"]["name"] in MEASUREMENT_FULLNAMES.values()
    }


class TestBothMeasurementWorkloadsRenderAsDeployments:
    def test_both_measurement_deployments_present(self, chart_dir: Path) -> None:
        deployments = _measurement_deployments(_rendered_docs(chart_dir))
        assert set(deployments) == set(MEASUREMENT_FULLNAMES.values())

    def test_images_are_digest_pinned_never_floating_tags(self, chart_dir: Path) -> None:
        for dep in _measurement_deployments(_rendered_docs(chart_dir)).values():
            image = dep["spec"]["template"]["spec"]["containers"][0]["image"]
            assert "@sha256:" in image, image
            assert not image.endswith((":latest", ":main", ":stable")), image


class TestMeasurementWorkloadsAreHardenedByDefault:
    def test_non_root_readonly_fs_drop_all_caps_seccomp(self, chart_dir: Path) -> None:
        for dep in _measurement_deployments(_rendered_docs(chart_dir)).values():
            sc = dep["spec"]["template"]["spec"]["containers"][0]["securityContext"]
            assert sc["runAsNonRoot"] is True
            assert sc["readOnlyRootFilesystem"] is True
            assert sc["allowPrivilegeEscalation"] is False
            assert sc["capabilities"]["drop"] == ["ALL"]
            assert sc["seccompProfile"]["type"] == "RuntimeDefault"

    def test_liveness_and_readiness_probes_and_resource_limits(self, chart_dir: Path) -> None:
        for dep in _measurement_deployments(_rendered_docs(chart_dir)).values():
            container = dep["spec"]["template"]["spec"]["containers"][0]
            assert container["livenessProbe"]["httpGet"]["path"]
            assert container["readinessProbe"]["httpGet"]["path"]
            assert container["resources"]["limits"]["cpu"]
            assert container["resources"]["limits"]["memory"]

    def test_each_workload_has_a_pod_disruption_budget(self, chart_dir: Path) -> None:
        docs = _rendered_docs(chart_dir)
        pdbs = {
            d["spec"]["selector"]["matchLabels"]["app.kubernetes.io/component"]
            for d in docs
            if d["kind"] == "PodDisruptionBudget"
        }
        assert "experiment-attribution" in pdbs
        assert "strategy-skill-bank" in pdbs


class TestMeasurementWorkloadsHaveNoKubernetesApiAccess:
    def test_dedicated_service_accounts_present(self, chart_dir: Path) -> None:
        docs = _rendered_docs(chart_dir)
        sa_names = {d["metadata"]["name"] for d in docs if d["kind"] == "ServiceAccount"}
        assert sa_names >= MEASUREMENT_SA_NAMES

    def test_no_role_or_rolebinding_for_either_measurement_workload(self, chart_dir: Path) -> None:
        """`rbac.rules: []` -> zero Role/RoleBinding: the measurement plane
        reads/writes only its own datastores (Postgres/ClickHouse/Temporal via
        SecretRef), never the Kubernetes API. Least-privilege-by-omission,
        same as intelligenceWorker."""
        docs = _rendered_docs(chart_dir)
        for kind in ("Role", "RoleBinding"):
            for d in (x for x in docs if x["kind"] == kind):
                comp = d["metadata"].get("labels", {}).get("app.kubernetes.io/component", "")
                assert comp not in ("experiment-attribution", "strategy-skill-bank"), d["metadata"][
                    "name"
                ]

    def test_no_clusterrole_or_clusterrolebinding_anywhere(self, chart_dir: Path) -> None:
        docs = _rendered_docs(chart_dir)
        cluster_scoped = [d for d in docs if d["kind"] in ("ClusterRole", "ClusterRoleBinding")]
        assert cluster_scoped == []

    def test_pods_use_dedicated_sa_never_the_implicit_default(self, chart_dir: Path) -> None:
        for dep in _measurement_deployments(_rendered_docs(chart_dir)).values():
            sa = dep["spec"]["template"]["spec"]["serviceAccountName"]
            assert sa in MEASUREMENT_SA_NAMES


class TestMeasurementWorkloadsSecretsAndEngineScope:
    def test_connections_are_secret_refs_never_plaintext_values(self, chart_dir: Path) -> None:
        """Every credential-bearing env var carries only the NAME of an
        external secret, never a secret value."""
        for dep in _measurement_deployments(_rendered_docs(chart_dir)).values():
            env = {
                e["name"]: e.get("value", "")
                for e in dep["spec"]["template"]["spec"]["containers"][0].get("env", [])
            }
            for name, value in env.items():
                if name.endswith("_SECRET_REF"):
                    # A name reference (points AT an external secret), not a value.
                    assert value.startswith("saena-"), (name, value)

    def test_grs_policy_bundle_is_a_signed_external_secret_no_values(self, chart_dir: Path) -> None:
        docs = _rendered_docs(chart_dir)
        ext = {d["metadata"]["name"]: d for d in docs if d["kind"] == "ExternalSecret"}
        assert "saena-grs-policy-bundle" in ext, "GRS policy bundle must be an ExternalSecret"
        kind = ext["saena-grs-policy-bundle"]["spec"]["secretStoreRef"]["kind"]
        assert kind in {"SecretStore", "ClusterSecretStore"}

    def test_no_grs_threshold_value_appears_anywhere_in_the_rendered_chart(
        self, chart_dir: Path
    ) -> None:
        """Production GRS threshold/SLA/credit VALUES stay BLOCKED(human) —
        they must NEVER be baked into the chart. Assert no numeric-threshold-
        shaped GRS config leaks into any rendered manifest."""
        result = subprocess.run(
            ["helm", "template", "saena-forge", str(chart_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        rendered = result.stdout.lower()
        for forbidden in ("grs_threshold", "grsthreshold", "min_grs", "grs_min", "sla_credit"):
            assert forbidden not in rendered, forbidden

    def test_engine_scope_env_is_chatgpt_search_only(self, chart_dir: Path) -> None:
        for dep in _measurement_deployments(_rendered_docs(chart_dir)).values():
            env = {
                e["name"]: e.get("value", "")
                for e in dep["spec"]["template"]["spec"]["containers"][0].get("env", [])
            }
            # No Google/Gemini engine env var of any spelling.
            for name in env:
                lowered = name.lower()
                assert "google" not in lowered
                assert "gemini" not in lowered
                assert "bard" not in lowered

    def test_no_google_gemini_string_in_measurement_manifests(self, chart_dir: Path) -> None:
        docs = _measurement_deployments(_rendered_docs(chart_dir))
        blob = yaml.safe_dump(docs).lower()
        for forbidden in ("googleai", "google-ai", "gemini", "aioverview", "aimode", "bard"):
            assert forbidden not in blob, forbidden
