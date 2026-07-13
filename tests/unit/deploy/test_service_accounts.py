"""ADR-0004 §3 ServiceAccount 3-separation — rendered-manifest assertions
for the runner-pool-extended (quality-eval, repository-intake) and browser-
pool (chatgpt-observer, site-discovery) ServiceAccounts, plus agent-runner
(w3-07).

Mirrors `tests/unit/deploy/test_chart_render.py`'s approach: shells out to
the real `helm` binary rather than reimplementing Go-template evaluation,
so the actual rendered artifact is what gets asserted on.
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

# The 5 ADR-0004 §3 job/browser-pool ServiceAccounts (excludes the 8
# long-running service SAs, which legitimately keep
# automountServiceAccountToken: true — they talk to their own scoped Role
# directly from a Deployment pod, unlike these five, whose consuming Job
# pod specs render in a separate patch unit).
JOB_AND_BROWSER_POOL_SA_NAMES = {
    "saena-agent-runner": "runner",
    "saena-quality-eval": "runner",
    "saena-repository-intake": "runner",
    "saena-chatgpt-observer": "browser",
    "saena-site-discovery": "browser",
}


def _run_helm_template(chart_dir: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["helm", "template", "saena-forge", str(chart_dir), *extra_args],
        capture_output=True,
        text=True,
        check=False,
    )


def _rendered_docs(chart_dir: Path, *extra_args: str) -> list[dict[str, Any]]:
    result = _run_helm_template(chart_dir, *extra_args)
    assert result.returncode == 0, result.stderr
    return [d for d in yaml.safe_load_all(result.stdout) if d]


class TestFiveJobAndBrowserPoolServiceAccountsRendered:
    def test_all_five_service_accounts_present_by_name(self, chart_dir: Path) -> None:
        docs = _rendered_docs(chart_dir)
        names = {d["metadata"]["name"] for d in docs if d["kind"] == "ServiceAccount"}
        assert JOB_AND_BROWSER_POOL_SA_NAMES.keys() <= names

    def test_all_five_are_namespace_scoped_in_saena_system(self, chart_dir: Path) -> None:
        docs = _rendered_docs(chart_dir)
        sas = {
            d["metadata"]["name"]: d
            for d in docs
            if d["kind"] == "ServiceAccount"
            and d["metadata"]["name"] in JOB_AND_BROWSER_POOL_SA_NAMES
        }
        assert set(sas) == set(JOB_AND_BROWSER_POOL_SA_NAMES)
        for sa in sas.values():
            assert sa["metadata"]["namespace"] == "saena-system"

    def test_all_five_have_automount_service_account_token_false(self, chart_dir: Path) -> None:
        docs = _rendered_docs(chart_dir)
        sas = [
            d
            for d in docs
            if d["kind"] == "ServiceAccount"
            and d["metadata"]["name"] in JOB_AND_BROWSER_POOL_SA_NAMES
        ]
        assert len(sas) == 5
        for sa in sas:
            assert sa["automountServiceAccountToken"] is False, sa["metadata"]["name"]

    def test_each_service_account_carries_its_expected_pool_label(self, chart_dir: Path) -> None:
        docs = _rendered_docs(chart_dir)
        sas = {
            d["metadata"]["name"]: d
            for d in docs
            if d["kind"] == "ServiceAccount"
            and d["metadata"]["name"] in JOB_AND_BROWSER_POOL_SA_NAMES
        }
        for name, expected_pool in JOB_AND_BROWSER_POOL_SA_NAMES.items():
            assert sas[name]["metadata"]["labels"]["saena.io/pool"] == expected_pool, name

    def test_the_8_service_accounts_are_unaffected_and_keep_automount_true(
        self, chart_dir: Path
    ) -> None:
        """Proves this unit's change is additive — the pre-existing 8
        long-running service SAs still default to automount: true (they
        need it, unlike the 5 job/browser-pool SAs above).

        w4-14 adds 2 more service-shaped SAs on top of these 8:
        `saena-forge-intelligence-worker-sa` (keeps automount: true, same
        reasoning as the original 8 — see
        test_intelligence_workloads.py::TestIntelligenceWorkerHasNoKubernetesApiAccess)
        and `saena-forge-chatgpt-observer-sa` (the NEW browser-pool
        coordinator SA, deliberately automount: false — READ-ONLY per
        w4-14's named MUST constraint, see
        test_intelligence_workloads.py::TestChatgptObserverCoordinatorIsReadOnlyWithNoGitCredential).
        Both new SAs are excluded from this specific "unaffected 8"
        assertion by name (rather than widening `JOB_AND_BROWSER_POOL_SA_NAMES`,
        which names the 5 Job-kind SAs specifically, not either of these 2
        new Deployment-backed SAs)."""
        w4_14_new_service_sa_names = {
            "saena-forge-intelligence-worker-sa",
            "saena-forge-chatgpt-observer-sa",
        }
        docs = _rendered_docs(chart_dir)
        service_sas = [
            d
            for d in docs
            if d["kind"] == "ServiceAccount"
            and d["metadata"]["name"] not in JOB_AND_BROWSER_POOL_SA_NAMES
            and d["metadata"]["name"] not in w4_14_new_service_sa_names
        ]
        assert len(service_sas) == 8
        for sa in service_sas:
            assert sa["automountServiceAccountToken"] is True, sa["metadata"]["name"]


class TestNoClusterScopeForAnyJobOrBrowserPoolServiceAccount:
    def test_no_clusterrole_or_clusterrolebinding_rendered_at_all(self, chart_dir: Path) -> None:
        docs = _rendered_docs(chart_dir)
        kinds = {d["kind"] for d in docs}
        assert "ClusterRole" not in kinds
        assert "ClusterRoleBinding" not in kinds

    def test_no_rolebinding_subject_references_a_service_account_outside_saena_system(
        self, chart_dir: Path
    ) -> None:
        docs = _rendered_docs(chart_dir)
        rolebindings = [d for d in docs if d["kind"] == "RoleBinding"]
        assert rolebindings, "expected at least the pre-existing 9 RoleBindings"
        for rb in rolebindings:
            for subject in rb["subjects"]:
                assert subject["kind"] == "ServiceAccount"
                assert subject["namespace"] == "saena-system"


class TestQualityEvalIntakeAndBrowserPoolHaveZeroKubernetesApiAccessByDefault:
    """quality-eval / repository-intake / chatgpt-observer / site-discovery
    (everything except agent-runner) get ZERO Kubernetes API access by
    default — no Role, no RoleBinding at all (least privilege: omit the
    Role rather than bind an empty one)."""

    NO_ROLE_SA_NAMES = {
        "saena-quality-eval",
        "saena-repository-intake",
        "saena-chatgpt-observer",
        "saena-site-discovery",
    }

    def test_no_role_named_for_any_of_the_four_service_accounts(self, chart_dir: Path) -> None:
        docs = _rendered_docs(chart_dir)
        role_names = {d["metadata"]["name"] for d in docs if d["kind"] == "Role"}
        for sa_name in self.NO_ROLE_SA_NAMES:
            assert f"{sa_name}-role" not in role_names, sa_name

    def test_no_rolebinding_subject_names_any_of_the_four_service_accounts(
        self, chart_dir: Path
    ) -> None:
        docs = _rendered_docs(chart_dir)
        bound_sa_names = {
            subject["name"] for d in docs if d["kind"] == "RoleBinding" for subject in d["subjects"]
        }
        assert bound_sa_names.isdisjoint(self.NO_ROLE_SA_NAMES)


class TestExecutionJobsSchemaRejectsClusterAdminEscalation:
    """Mirrors test_chart_render.py::TestGoogleFlagRendersFailure — a
    hypothetical `--set` attempting to grant cluster-admin to any of the
    ADR-0004 §3 execution-Job/browser-pool SAs fails schema validation, the
    same way `agentRunner.job.rbac.clusterAdmin=true` already does."""

    @pytest.mark.parametrize(
        "set_path",
        [
            "executionJobs.qualityEval.rbac.clusterAdmin=true",
            "executionJobs.repositoryIntake.rbac.clusterAdmin=true",
            "executionJobs.browserPool.chatgptObserver.rbac.clusterAdmin=true",
            "executionJobs.browserPool.siteDiscovery.rbac.clusterAdmin=true",
            "executionJobs.qualityEval.rbac.productionDeploy=true",
        ],
    )
    def test_cluster_admin_or_production_deploy_set_fails_schema_validation(
        self, chart_dir: Path, set_path: str
    ) -> None:
        result = _run_helm_template(chart_dir, "--set", set_path)
        assert result.returncode != 0
        assert "value must be false" in result.stderr or "clusterAdmin" in result.stderr

    def test_agent_runner_cluster_admin_set_still_fails_schema_validation(
        self, chart_dir: Path
    ) -> None:
        """Pre-existing agentRunner protection (w2-23) — asserted here too
        so this file is a complete escalation-resistance proof for every SA
        this unit is responsible for."""
        result = _run_helm_template(chart_dir, "--set", "agentRunner.job.rbac.clusterAdmin=true")
        assert result.returncode != 0
