"""`saena_forgectl.checks.service_account_permissions` — k3s spec §8.1 condition 5."""

from __future__ import annotations

import copy
from typing import Any

from saena_forgectl.checks.service_account_permissions import (
    check_service_account_permissions,
)


class TestPassingFixture:
    def test_passes(self, passing_values: dict[str, Any]) -> None:
        result = check_service_account_permissions(passing_values)
        assert result.passed is True
        assert result.name == "service_account_permissions"


class TestClusterAdminFlagFails:
    def test_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["agentRunner"]["job"]["rbac"]["clusterAdmin"] = True
        result = check_service_account_permissions(values)
        assert result.passed is False
        assert any("clusterAdmin" in p for p in result.context["problems"])


class TestProductionDeployFlagFails:
    def test_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["agentRunner"]["job"]["rbac"]["productionDeploy"] = True
        result = check_service_account_permissions(values)
        assert result.passed is False
        assert any("productionDeploy" in p for p in result.context["problems"])


class TestWildcardRuleFails:
    def test_wildcard_verb_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["agentRunner"]["job"]["rbac"]["rules"] = [
            {"apiGroups": ["*"], "resources": ["*"], "verbs": ["*"]}
        ]
        result = check_service_account_permissions(values)
        assert result.passed is False

    def test_wildcard_resource_only_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["agentRunner"]["job"]["rbac"]["rules"] = [
            {"apiGroups": [""], "resources": ["*"], "verbs": ["get"]}
        ]
        result = check_service_account_permissions(values)
        assert result.passed is False

    def test_non_list_rules_does_not_grant_dangerous_access(
        self, passing_values: dict[str, Any]
    ) -> None:
        values = copy.deepcopy(passing_values)
        values["agentRunner"]["job"]["rbac"]["rules"] = "not-a-list"
        result = check_service_account_permissions(values)
        assert result.passed is True

    def test_non_mapping_rule_entry_is_skipped_not_dangerous(
        self, passing_values: dict[str, Any]
    ) -> None:
        values = copy.deepcopy(passing_values)
        values["agentRunner"]["job"]["rbac"]["rules"] = ["not-a-mapping"]
        result = check_service_account_permissions(values)
        assert result.passed is True


class TestClusterAdminRoleRefFails:
    def test_direct_cluster_admin_reference_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["agentRunner"]["job"]["clusterRoleRef"] = "cluster-admin"
        result = check_service_account_permissions(values)
        assert result.passed is False


class TestMissingRbacFailsClosed:
    def test_absent_rbac_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        del values["agentRunner"]["job"]["rbac"]
        result = check_service_account_permissions(values)
        assert result.passed is False

    def test_non_mapping_rbac_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["agentRunner"]["job"]["rbac"] = "not-a-mapping"
        result = check_service_account_permissions(values)
        assert result.passed is False
