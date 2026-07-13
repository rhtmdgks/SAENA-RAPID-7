"""Wave 4 intelligence workloads (w4-14) — `intelligence-worker` and
`chatgpt-observer` (browser-pool observer/coordinator Deployment) added to
the saena-forge chart. Mirrors `tests/unit/deploy/test_chart_render.py` and
`tests/unit/deploy/test_rbac_separation.py`'s approach: shells out to the
real `helm` binary and asserts on the rendered manifest, rather than
reimplementing Go-template evaluation.

Scope of this unit (see `deploy/charts/saena-forge/values.yaml`
`services.intelligenceWorker` / `services.chatgptObserver` comments for the
full design rationale):

- intelligence-worker: Worker-hosted module Deployment hosting the 4 P0
  intelligence capabilities (demand-graph, entity-resolution,
  claim-evidence, citation-intelligence). Zero Kubernetes API access.
- chatgpt-observer (this chart's NEW Deployment): the browser-pool
  observer/coordinator half of "Planned runtime | k3s Deployment + browser
  Jobs". It is READ-ONLY — zero Kubernetes API access, no Git credential —
  distinct from the ALREADY-EXISTING (w3-07) `executionJobs.browserPool.
  chatgptObserver` Job-kind ServiceAccount (`saena-chatgpt-observer`, no
  `-sa` suffix), which this unit does not modify.
- Both workloads get a dedicated ServiceAccount, least-privilege RBAC
  (Role/RoleBinding only where `rbac.rules` is non-empty — see
  `test_no_role_or_rolebinding_rendered_for_either_new_workload` below),
  readiness/liveness probes (inherited from `serviceDefaults`), a
  PodDisruptionBudget, and resource requests/limits — the same generic
  `.Values.services.<key>` shape every pre-existing service already gets,
  proven here because this unit added no per-service `if` branch to any
  shared template (deployments.yaml/services.yaml/pod-disruption-budgets.yaml
  /service-accounts.yaml/rbac/service-roles.yaml all stayed
  service-agnostic).
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

NEW_SERVICE_FULLNAMES = {
    "intelligence-worker": "saena-forge-intelligence-worker",
    "chatgpt-observer": "saena-forge-chatgpt-observer",
}

# The pre-existing (w3-07) browser-pool Job-kind ServiceAccount — distinct
# from this unit's new `saena-forge-chatgpt-observer-sa` coordinator SA.
# Asserted here (not just in test_rbac_separation.py) to prove the two
# never collide under this unit's changes.
PRE_EXISTING_JOB_SA_NAME = "saena-chatgpt-observer"


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


class TestBothNewWorkloadsRenderAsDeployments:
    def test_intelligence_worker_and_chatgpt_observer_deployments_present(
        self, chart_dir: Path
    ) -> None:
        docs = _rendered_docs(chart_dir)
        deployments = {d["metadata"]["name"] for d in docs if d["kind"] == "Deployment"}
        assert NEW_SERVICE_FULLNAMES["intelligence-worker"] in deployments
        assert NEW_SERVICE_FULLNAMES["chatgpt-observer"] in deployments

    def test_total_deployment_count_is_10(self, chart_dir: Path) -> None:
        """8 pre-existing independent-deployment services + the 2 new w4-14
        workloads = 10 (service-catalog.md v1 topology: 'total Deployment
        10 = independent 8 + worker host 2 (compute pool)')."""
        docs = _rendered_docs(chart_dir)
        deployments = [d for d in docs if d["kind"] == "Deployment"]
        assert len(deployments) == 10

    def test_both_new_deployments_are_in_saena_system_namespace(self, chart_dir: Path) -> None:
        docs = _rendered_docs(chart_dir)
        deployments = {d["metadata"]["name"]: d for d in docs if d["kind"] == "Deployment"}
        for name in NEW_SERVICE_FULLNAMES.values():
            assert deployments[name]["metadata"]["namespace"] == "saena-system"


class TestEachNewWorkloadHasServiceAccountNetworkPolicyProbesPdbAndLimits:
    """The w4-14 gate's named checklist: SA + NetworkPolicy + probes + PDB +
    resource limits for each new workload."""

    def test_each_new_workload_has_its_own_dedicated_service_account(self, chart_dir: Path) -> None:
        docs = _rendered_docs(chart_dir)
        sa_names = {d["metadata"]["name"] for d in docs if d["kind"] == "ServiceAccount"}
        assert "saena-forge-intelligence-worker-sa" in sa_names
        assert "saena-forge-chatgpt-observer-sa" in sa_names

    def test_each_new_deployment_pod_spec_references_its_own_service_account(
        self, chart_dir: Path
    ) -> None:
        docs = _rendered_docs(chart_dir)
        deployments = {d["metadata"]["name"]: d for d in docs if d["kind"] == "Deployment"}
        iw = deployments[NEW_SERVICE_FULLNAMES["intelligence-worker"]]
        co = deployments[NEW_SERVICE_FULLNAMES["chatgpt-observer"]]
        assert iw["spec"]["template"]["spec"]["serviceAccountName"] == (
            "saena-forge-intelligence-worker-sa"
        )
        assert co["spec"]["template"]["spec"]["serviceAccountName"] == (
            "saena-forge-chatgpt-observer-sa"
        )

    def test_default_deny_network_policy_covers_the_namespace_both_workloads_run_in(
        self, chart_dir: Path
    ) -> None:
        """Both new workloads render into `saena-system`, which already gets
        a `default-deny-all` NetworkPolicy (`podSelector: {}` — every pod in
        the namespace, including these two new Deployments) — same coverage
        model as the pre-existing 8 services (no per-service NetworkPolicy
        carve-out exists in this chart for ANY service; only the runner/
        browser Job POOLS get explicit allow rules, which is unchanged by
        this unit)."""
        docs = _rendered_docs(chart_dir)
        default_deny = [
            d
            for d in docs
            if d["kind"] == "NetworkPolicy"
            and d["metadata"]["name"] == "default-deny-all"
            and d["metadata"]["namespace"] == "saena-system"
        ]
        assert len(default_deny) == 1
        assert default_deny[0]["spec"]["podSelector"] == {}
        assert set(default_deny[0]["spec"]["policyTypes"]) == {"Ingress", "Egress"}

    def test_each_new_deployment_has_liveness_and_readiness_probes(self, chart_dir: Path) -> None:
        docs = _rendered_docs(chart_dir)
        deployments = {d["metadata"]["name"]: d for d in docs if d["kind"] == "Deployment"}
        for name in NEW_SERVICE_FULLNAMES.values():
            container = deployments[name]["spec"]["template"]["spec"]["containers"][0]
            assert container["livenessProbe"]["httpGet"]["path"] == "/health"
            assert container["readinessProbe"]["httpGet"]["path"] == "/health"

    def test_each_new_workload_has_a_poddisruptionbudget(self, chart_dir: Path) -> None:
        docs = _rendered_docs(chart_dir)
        pdbs = {d["metadata"]["name"] for d in docs if d["kind"] == "PodDisruptionBudget"}
        assert NEW_SERVICE_FULLNAMES["intelligence-worker"] in pdbs
        assert NEW_SERVICE_FULLNAMES["chatgpt-observer"] in pdbs

    def test_total_poddisruptionbudget_count_is_10(self, chart_dir: Path) -> None:
        docs = _rendered_docs(chart_dir)
        pdbs = [d for d in docs if d["kind"] == "PodDisruptionBudget"]
        assert len(pdbs) == 10

    def test_each_new_deployment_container_declares_resource_requests_and_limits(
        self, chart_dir: Path
    ) -> None:
        docs = _rendered_docs(chart_dir)
        deployments = {d["metadata"]["name"]: d for d in docs if d["kind"] == "Deployment"}
        for name in NEW_SERVICE_FULLNAMES.values():
            container = deployments[name]["spec"]["template"]["spec"]["containers"][0]
            resources = container["resources"]
            assert resources["requests"]["cpu"]
            assert resources["requests"]["memory"]
            assert resources["limits"]["cpu"]
            assert resources["limits"]["memory"]


class TestChatgptObserverCoordinatorIsReadOnlyWithNoGitCredential:
    """The w4-14 named MUST constraint: 'The browser-pool observer SA MUST
    carry NO Git credentials and be READ-ONLY (no write RBAC to any cluster
    resource)'. Applies to this unit's NEW coordinator Deployment SA
    (`saena-forge-chatgpt-observer-sa`) — distinct from the pre-existing
    (w3-07) Job-kind SA (`saena-chatgpt-observer`), which is asserted
    separately in `test_rbac_separation.py` / `test_service_accounts.py`
    and untouched by this unit."""

    def test_coordinator_service_account_name_differs_from_the_pre_existing_job_sa(
        self, chart_dir: Path
    ) -> None:
        docs = _rendered_docs(chart_dir)
        sa_names = {d["metadata"]["name"] for d in docs if d["kind"] == "ServiceAccount"}
        assert "saena-forge-chatgpt-observer-sa" in sa_names
        assert PRE_EXISTING_JOB_SA_NAME in sa_names
        assert PRE_EXISTING_JOB_SA_NAME != "saena-forge-chatgpt-observer-sa"

    def test_coordinator_service_account_has_automount_false(self, chart_dir: Path) -> None:
        docs = _rendered_docs(chart_dir)
        sa = next(
            d
            for d in docs
            if d["kind"] == "ServiceAccount"
            and d["metadata"]["name"] == "saena-forge-chatgpt-observer-sa"
        )
        assert sa["automountServiceAccountToken"] is False

    def test_coordinator_deployment_pod_spec_also_sets_automount_false(
        self, chart_dir: Path
    ) -> None:
        docs = _rendered_docs(chart_dir)
        dep = next(
            d
            for d in docs
            if d["kind"] == "Deployment"
            and d["metadata"]["name"] == NEW_SERVICE_FULLNAMES["chatgpt-observer"]
        )
        assert dep["spec"]["template"]["spec"]["automountServiceAccountToken"] is False

    def test_no_role_or_rolebinding_named_for_the_coordinator_service_account(
        self, chart_dir: Path
    ) -> None:
        """Least-privilege-by-omission: `rbac.rules: []` for chatgptObserver
        must render ZERO Role/RoleBinding (not an empty-rules Role) — same
        convention templates/rbac/execution-jobs-roles.yaml already
        documents for the Job-kind SAs, extended by this unit's
        templates/rbac/service-roles.yaml fix to the 8-service Role
        template too."""
        docs = _rendered_docs(chart_dir)
        role_names = {d["metadata"]["name"] for d in docs if d["kind"] == "Role"}
        rolebinding_names = {d["metadata"]["name"] for d in docs if d["kind"] == "RoleBinding"}
        assert "saena-forge-chatgpt-observer-role" not in role_names
        assert "saena-forge-chatgpt-observer-rolebinding" not in rolebinding_names

    def test_no_rolebinding_anywhere_names_the_coordinator_service_account_as_subject(
        self, chart_dir: Path
    ) -> None:
        docs = _rendered_docs(chart_dir)
        rolebindings = [d for d in docs if d["kind"] == "RoleBinding"]
        for rb in rolebindings:
            for subject in rb["subjects"]:
                assert subject["name"] != "saena-forge-chatgpt-observer-sa"

    def test_agent_orchestrator_remains_the_sole_batch_jobs_grant_holder(
        self, chart_dir: Path
    ) -> None:
        """Job launch/poll/cleanup (`batch/jobs` create/get/list/watch/
        delete) stays exclusively on agentOrchestrator's Role — the
        coordinator Deployment does NOT duplicate or widen that grant."""
        docs = _rendered_docs(chart_dir)
        roles = [d for d in docs if d["kind"] == "Role"]
        roles_with_batch_jobs = [
            r
            for r in roles
            if any(
                "batch" in rule.get("apiGroups", []) and "jobs" in rule.get("resources", [])
                for rule in r.get("rules", [])
            )
        ]
        assert {r["metadata"]["name"] for r in roles_with_batch_jobs} == {
            "saena-forge-agent-orchestrator-role"
        }

    def test_no_deployment_or_serviceaccount_mounts_a_git_credential_secret(
        self, chart_dir: Path
    ) -> None:
        """No Secret-backed volume or env reference anywhere in this chart
        names a git-credential secret for the coordinator Deployment (or
        any Deployment) — Git credentials are exclusively wired to the
        `agent-runner`/`repository-intake` Job kinds, out of this chart's
        rendered scope entirely (their consuming Job pod specs render in a
        separate patch unit, per templates/rbac/agent-runner-role.yaml)."""
        docs = _rendered_docs(chart_dir)
        deployments = [d for d in docs if d["kind"] == "Deployment"]
        for dep in deployments:
            spec = dep["spec"]["template"]["spec"]
            for vol in spec.get("volumes", []):
                secret_name = (vol.get("secret") or {}).get("secretName", "")
                assert "git" not in secret_name.lower(), dep["metadata"]["name"]
            for container in spec["containers"]:
                for env in container.get("env", []):
                    assert "git" not in env["name"].lower(), (
                        dep["metadata"]["name"],
                        env["name"],
                    )


class TestIntelligenceWorkerHasNoKubernetesApiAccess:
    def test_no_role_or_rolebinding_named_for_intelligence_worker(self, chart_dir: Path) -> None:
        docs = _rendered_docs(chart_dir)
        role_names = {d["metadata"]["name"] for d in docs if d["kind"] == "Role"}
        rolebinding_names = {d["metadata"]["name"] for d in docs if d["kind"] == "RoleBinding"}
        assert "saena-forge-intelligence-worker-role" not in role_names
        assert "saena-forge-intelligence-worker-rolebinding" not in rolebinding_names

    def test_intelligence_worker_service_account_keeps_automount_true(
        self, chart_dir: Path
    ) -> None:
        """intelligence-worker legitimately talks to Postgres/ClickHouse/
        vectorStore, not the Kubernetes API — its SA automount default
        (true, same as the 8 pre-existing services) is retained rather than
        disabled, unlike the read-only browser-pool coordinator above,
        because this is a distinct design decision (no K8s Role bound
        either way; automount here is simply left at the shared default
        since no chart evidence requires disabling it for this workload)."""
        docs = _rendered_docs(chart_dir)
        sa = next(
            d
            for d in docs
            if d["kind"] == "ServiceAccount"
            and d["metadata"]["name"] == "saena-forge-intelligence-worker-sa"
        )
        assert sa["automountServiceAccountToken"] is True


class TestClickhouseAndVectorStoreConnectionWiring:
    """ClickHouse/vector-store are referenced via SecretRef / connection
    metadata only — never an inline plaintext credential value
    (ADR-0020)."""

    def test_clickhouse_credentials_secret_ref_env_var_present_on_every_deployment(
        self, chart_dir: Path
    ) -> None:
        docs = _rendered_docs(chart_dir)
        deployments = [d for d in docs if d["kind"] == "Deployment"]
        assert len(deployments) == 10
        for dep in deployments:
            container = dep["spec"]["template"]["spec"]["containers"][0]
            env_names = {e["name"] for e in container.get("env", [])}
            assert "CLICKHOUSE_CREDENTIALS_SECRET_REF" in env_names

    def test_clickhouse_credentials_secret_ref_value_is_a_name_not_a_secret_value(
        self, chart_dir: Path
    ) -> None:
        docs = _rendered_docs(chart_dir)
        dep = next(
            d
            for d in docs
            if d["kind"] == "Deployment"
            and d["metadata"]["name"] == NEW_SERVICE_FULLNAMES["intelligence-worker"]
        )
        container = dep["spec"]["template"]["spec"]["containers"][0]
        env = {e["name"]: e["value"] for e in container["env"]}
        assert env["CLICKHOUSE_CREDENTIALS_SECRET_REF"] == "saena-clickhouse-credentials"

    def test_clickhouse_externalsecret_uses_a_valid_secretstore_kind(self, chart_dir: Path) -> None:
        docs = _rendered_docs(chart_dir)
        ext_secrets = {d["metadata"]["name"]: d for d in docs if d["kind"] == "ExternalSecret"}
        assert "saena-clickhouse-credentials" in ext_secrets
        kind = ext_secrets["saena-clickhouse-credentials"]["spec"]["secretStoreRef"]["kind"]
        assert kind in {"SecretStore", "ClusterSecretStore"}

    def test_infra_connection_configmap_carries_clickhouse_endpoint_metadata_only(
        self, chart_dir: Path
    ) -> None:
        docs = _rendered_docs(chart_dir)
        cm = next(
            d
            for d in docs
            if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "saena-forge-infra-connection"
        )
        data = cm["data"]
        assert data["CLICKHOUSE_HOST"]
        assert data["CLICKHOUSE_PORT"]
        assert data["CLICKHOUSE_DATABASE"]
        # non-secret metadata only — no key here is a credential VALUE
        for key in data:
            assert "password" not in key.lower()
            assert "secret" not in key.lower() or key.endswith("_REF")

    def test_vector_store_backend_and_index_prefix_env_vars_present(self, chart_dir: Path) -> None:
        docs = _rendered_docs(chart_dir)
        dep = next(
            d
            for d in docs
            if d["kind"] == "Deployment"
            and d["metadata"]["name"] == NEW_SERVICE_FULLNAMES["intelligence-worker"]
        )
        container = dep["spec"]["template"]["spec"]["containers"][0]
        env = {e["name"]: e["value"] for e in container["env"]}
        assert env["VECTOR_STORE_BACKEND"] == "pgvector"
        assert env["VECTOR_STORE_INDEX_PREFIX"]

    def test_vector_store_values_carry_no_separate_host_or_port(
        self, values_data: dict[str, Any]
    ) -> None:
        """pgvector runs inside the existing Postgres connection — the
        vectorStore values block documents this via
        `usesPostgresConnection: true` and intentionally has no `host`/
        `port` of its own."""
        vector_store = values_data["vectorStore"]
        assert vector_store["usesPostgresConnection"] is True
        assert "host" not in vector_store
        assert "port" not in vector_store


class TestNoPlaintextSecretLiteralsAnywhereInRenderedOutput:
    """No plaintext secret value leaks anywhere in the rendered manifest for
    the two new workloads specifically (chart-wide coverage already exists
    via values.schema.json's noPlaintextSecretFields def — this test proves
    the actual RENDERED output for w4-14's additions, not just the values
    schema, carries no literal secret material)."""

    _DENY_SUBSTRINGS = ("password", "passwd", "privatekey", "apikey")

    def test_intelligence_worker_and_chatgpt_observer_deployments_have_no_plaintext_secret_env(
        self, chart_dir: Path
    ) -> None:
        docs = _rendered_docs(chart_dir)
        deployments = {d["metadata"]["name"]: d for d in docs if d["kind"] == "Deployment"}
        for name in NEW_SERVICE_FULLNAMES.values():
            container = deployments[name]["spec"]["template"]["spec"]["containers"][0]
            for env in container.get("env", []):
                lowered_name = env["name"].lower()
                for deny in self._DENY_SUBSTRINGS:
                    assert deny not in lowered_name, (name, env["name"])
                # every credential-shaped env var must be a *_SECRET_REF
                # name, never a raw value
                if "secret" in lowered_name:
                    assert lowered_name.endswith("_secret_ref"), (name, env["name"])

    def test_clickhouse_and_vectorstore_values_blocks_reject_plaintext_secret_shapes(
        self, values_data: dict[str, Any], values_schema: dict[str, Any]
    ) -> None:
        import jsonschema

        deny_schema = {
            "type": "object",
            "allOf": [values_schema["$defs"]["noPlaintextSecretFields"]],
        }
        validator = jsonschema.Draft202012Validator(deny_schema)
        assert validator.is_valid(values_data["clickhouse"])
        assert validator.is_valid(values_data["vectorStore"])


class TestHelmLintAndPreflightStillPassWithTheseAdditions:
    def test_helm_lint_passes(self, chart_dir: Path) -> None:
        result = subprocess.run(
            ["helm", "lint", str(chart_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_default_values_render_without_error(self, chart_dir: Path) -> None:
        result = _run_helm_template(chart_dir)
        assert result.returncode == 0, result.stderr

    def test_no_clusterrole_or_clusterrolebinding_rendered(self, chart_dir: Path) -> None:
        docs = _rendered_docs(chart_dir)
        kinds = {d["kind"] for d in docs}
        assert "ClusterRole" not in kinds
        assert "ClusterRoleBinding" not in kinds
