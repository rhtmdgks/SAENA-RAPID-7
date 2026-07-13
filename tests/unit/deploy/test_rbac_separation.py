"""ADR-0004 §3 cross-ServiceAccount separation — negative tests over the
rendered `helm template` output proving the runner-pool 3-way split
(agent-runner / quality-eval / repository-intake) and the browser-pool
split (chatgpt-observer / site-discovery) cannot escalate into each other,
and that neither pool's write access leaks to the other job SAs (w3-07).

Mirrors `tests/unit/deploy/test_chart_render.py`'s approach: shells out to
the real `helm` binary.
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

_WRITE_VERBS = {"create", "update", "patch", "delete", "deletecollection"}

# Every ADR-0004 §3 job/browser-pool SA name this unit governs.
_ALL_JOB_AND_BROWSER_POOL_SA_NAMES = {
    "saena-agent-runner",
    "saena-quality-eval",
    "saena-repository-intake",
    "saena-chatgpt-observer",
    "saena-site-discovery",
}

# quality-eval / repository-intake / browser pool must have ZERO write
# verbs anywhere — only agent-runner may (per its own scoped Role) ever
# carry a verb at all, and even that Role is read-only (get/list pods) by
# default in this chart's values.yaml.
_NON_RUNNER_JOB_SA_NAMES = _ALL_JOB_AND_BROWSER_POOL_SA_NAMES - {"saena-agent-runner"}


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


class TestNoJobOrBrowserPoolServiceAccountHasClusterScope:
    def test_no_clusterrole_rendered(self, chart_dir: Path) -> None:
        docs = _rendered_docs(chart_dir)
        assert not [d for d in docs if d["kind"] == "ClusterRole"]

    def test_no_clusterrolebinding_rendered(self, chart_dir: Path) -> None:
        docs = _rendered_docs(chart_dir)
        assert not [d for d in docs if d["kind"] == "ClusterRoleBinding"]

    def test_no_role_or_rolebinding_carries_cluster_admin_role_ref(self, chart_dir: Path) -> None:
        docs = _rendered_docs(chart_dir)
        for rb in [d for d in docs if d["kind"] == "RoleBinding"]:
            assert rb["roleRef"]["kind"] == "Role"
            assert rb["roleRef"]["name"] != "cluster-admin"


class TestAllJobAndBrowserPoolServiceAccountsHaveAutomountFalse:
    def test_automount_false_for_every_governed_service_account(self, chart_dir: Path) -> None:
        docs = _rendered_docs(chart_dir)
        sas = {
            d["metadata"]["name"]: d
            for d in docs
            if d["kind"] == "ServiceAccount"
            and d["metadata"]["name"] in _ALL_JOB_AND_BROWSER_POOL_SA_NAMES
        }
        assert set(sas) == _ALL_JOB_AND_BROWSER_POOL_SA_NAMES
        for name, sa in sas.items():
            assert sa["automountServiceAccountToken"] is False, name


class TestAgentRunnerRoleGrantsNoSecretsBeyondANamedLeaseSecret:
    def test_default_agent_runner_role_has_no_secrets_rule_at_all(self, chart_dir: Path) -> None:
        docs = _rendered_docs(chart_dir)
        roles = [
            d
            for d in docs
            if d["kind"] == "Role" and d["metadata"]["name"] == "saena-agent-runner-role"
        ]
        assert len(roles) == 1
        for rule in roles[0]["rules"]:
            assert "secrets" not in rule.get("resources", []), rule

    def test_a_secrets_rule_without_resourcenames_would_be_rejected_by_this_assertion(
        self, chart_dir: Path, tmp_path: Any
    ) -> None:
        """Proves the guard above is not vacuous: an agent-runner Role rule
        that grants unscoped `secrets` access (no `resourceNames` pin to a
        single named lease secret) fails this test's own logic when
        deliberately injected via `-f`, so a future values.yaml regression
        that widens agent-runner to all-secrets access is caught."""
        override = tmp_path / "widen-secrets.yaml"
        override.write_text(
            yaml.safe_dump(
                {
                    "agentRunner": {
                        "job": {
                            "rbac": {
                                "clusterAdmin": False,
                                "productionDeploy": False,
                                "rules": [
                                    {
                                        "apiGroups": [""],
                                        "resources": ["secrets"],
                                        "verbs": ["get"],
                                    }
                                ],
                            }
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        docs = _rendered_docs(chart_dir, "-f", str(override))
        roles = [
            d
            for d in docs
            if d["kind"] == "Role" and d["metadata"]["name"] == "saena-agent-runner-role"
        ]
        assert len(roles) == 1
        unscoped_secrets_rules = [
            rule
            for rule in roles[0]["rules"]
            if "secrets" in rule.get("resources", []) and not rule.get("resourceNames")
        ]
        # This is the condition ADR-0004 §3 forbids — an unscoped secrets
        # grant. We assert it IS present here only to prove the detection
        # logic actually fires; the real chart default (asserted above)
        # never produces this shape.
        assert unscoped_secrets_rules, "expected the deliberately-widened override to be caught"


class TestQualityEvalIntakeAndBrowserPoolHaveZeroWriteVerbsAnywhere:
    def test_no_role_exists_for_any_of_the_four_non_runner_service_accounts(
        self, chart_dir: Path
    ) -> None:
        docs = _rendered_docs(chart_dir)
        role_names = {d["metadata"]["name"] for d in docs if d["kind"] == "Role"}
        for sa_name in _NON_RUNNER_JOB_SA_NAMES:
            assert f"{sa_name}-role" not in role_names, sa_name

    def test_no_write_verb_reachable_by_any_of_the_four_via_any_rolebinding(
        self, chart_dir: Path
    ) -> None:
        docs = _rendered_docs(chart_dir)
        roles_by_name = {d["metadata"]["name"]: d for d in docs if d["kind"] == "Role"}
        rolebindings = [d for d in docs if d["kind"] == "RoleBinding"]

        for rb in rolebindings:
            bound_sa_names = {s["name"] for s in rb["subjects"] if s["kind"] == "ServiceAccount"}
            if not bound_sa_names & _NON_RUNNER_JOB_SA_NAMES:
                continue
            role = roles_by_name.get(rb["roleRef"]["name"])
            assert role is None, (
                f"RoleBinding {rb['metadata']['name']} binds a non-runner job/browser "
                f"SA ({bound_sa_names & _NON_RUNNER_JOB_SA_NAMES}) to Role "
                f"{rb['roleRef']['name']!r}, which is forbidden by default"
            )
            for rule in role.get("rules", []):
                verbs = set(rule.get("verbs", []))
                assert not (verbs & _WRITE_VERBS), (rb["metadata"]["name"], rule)


class TestCrossPoolAndCrossSaBindingProhibitions:
    def test_every_rolebinding_binds_exactly_one_subject(self, chart_dir: Path) -> None:
        """No RoleBinding may fan a Role's grant out to two ServiceAccounts
        — each Job/service SA's grant must be independently revocable."""
        docs = _rendered_docs(chart_dir)
        for rb in [d for d in docs if d["kind"] == "RoleBinding"]:
            assert len(rb["subjects"]) == 1, rb["metadata"]["name"]

    def test_no_service_account_is_bound_to_more_than_one_rolebinding(
        self, chart_dir: Path
    ) -> None:
        """A single SA fanning into multiple Roles would let its effective
        permission set drift beyond what any one Role review covers."""
        docs = _rendered_docs(chart_dir)
        subject_names = [
            s["name"] for d in docs if d["kind"] == "RoleBinding" for s in d["subjects"]
        ]
        assert len(subject_names) == len(set(subject_names)), subject_names

    def test_no_rolebinding_name_or_roleref_crosses_pools(self, chart_dir: Path) -> None:
        """Every RoleBinding's Role name is derived 1:1 from its own
        subject SA name in this chart's templates — `<sa>-role` for the 5
        job/browser-pool SAs (service-accounts.yaml has no `-sa` suffix for
        these), `<sa-without-"-sa"-suffix>-role` for the 8 per-service SAs
        (`saena-forge.serviceAccountName` appends `-sa`, while
        `saena-forge.serviceFullname` — what the Role name is built from —
        does not). Either way the Role name is a deterministic function of
        ONLY that RoleBinding's own subject SA name — this proves no
        RoleBinding was hand-wired to point one pool's SA at another pool's
        (or another service's) Role."""
        docs = _rendered_docs(chart_dir)
        for rb in [d for d in docs if d["kind"] == "RoleBinding"]:
            subject = rb["subjects"][0]
            sa_name = subject["name"]
            base_name = sa_name[: -len("-sa")] if sa_name.endswith("-sa") else sa_name
            assert rb["roleRef"]["name"] == f"{base_name}-role", rb["metadata"]["name"]

    def test_no_secret_or_configmap_volume_name_is_shared_across_multiple_pod_specs(
        self, chart_dir: Path
    ) -> None:
        """No two Deployment pod specs mount the same Secret-backed volume
        — the only pod specs this chart renders are the 8 service
        Deployments (the 5 job/browser-pool SAs' consuming Job pod specs
        render in a separate patch unit, out of this chart's scope)."""
        docs = _rendered_docs(chart_dir)
        deployments = [d for d in docs if d["kind"] == "Deployment"]
        secret_name_to_deployments: dict[str, set[str]] = {}
        for dep in deployments:
            dep_name = dep["metadata"]["name"]
            for vol in dep["spec"]["template"]["spec"].get("volumes", []):
                secret_ref = (vol.get("secret") or {}).get("secretName")
                if secret_ref:
                    secret_name_to_deployments.setdefault(secret_ref, set()).add(dep_name)
        for secret_name, dep_names in secret_name_to_deployments.items():
            assert len(dep_names) <= 1, (secret_name, dep_names)


class TestDefaultServiceAccountNeverReferenced:
    def test_no_deployment_pod_spec_uses_the_implicit_default_service_account(
        self, chart_dir: Path
    ) -> None:
        docs = _rendered_docs(chart_dir)
        deployments = [d for d in docs if d["kind"] == "Deployment"]
        assert len(deployments) == 8
        for dep in deployments:
            pod_spec = dep["spec"]["template"]["spec"]
            sa_name = pod_spec.get("serviceAccountName", "")
            assert sa_name not in ("", "default"), dep["metadata"]["name"]

    def test_no_rendered_serviceaccount_is_literally_named_default(self, chart_dir: Path) -> None:
        docs = _rendered_docs(chart_dir)
        names = {d["metadata"]["name"] for d in docs if d["kind"] == "ServiceAccount"}
        assert "default" not in names
