"""`saena_forgectl.checks.network_policy` — k3s spec §8.1 condition 4."""

from __future__ import annotations

import copy
from typing import Any

from saena_forgectl.checks.network_policy import check_network_policy


class TestPassingFixture:
    def test_passes(self, passing_values: dict[str, Any]) -> None:
        result = check_network_policy(passing_values)
        assert result.passed is True
        assert result.name == "network_policy"


class TestBothLocationsFalseFails:
    def test_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["global"]["network"]["defaultDeny"] = False
        values["networkPolicy"]["defaultDeny"] = False
        result = check_network_policy(values)
        assert result.passed is False


class TestEitherLocationTrueIsSufficient:
    def test_global_only_passes(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["networkPolicy"]["defaultDeny"] = False
        result = check_network_policy(values)
        assert result.passed is True

    def test_top_level_only_passes(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["global"]["network"]["defaultDeny"] = False
        result = check_network_policy(values)
        assert result.passed is True


class TestAbsentDeclarationFailsClosed:
    def test_missing_both_sections_fails(self) -> None:
        result = check_network_policy({})
        assert result.passed is False

    def test_missing_network_key_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        del values["global"]["network"]
        del values["networkPolicy"]
        result = check_network_policy(values)
        assert result.passed is False

    def test_non_boolean_default_deny_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["global"]["network"]["defaultDeny"] = "yes"
        values["networkPolicy"]["defaultDeny"] = "yes"
        result = check_network_policy(values)
        assert result.passed is False
