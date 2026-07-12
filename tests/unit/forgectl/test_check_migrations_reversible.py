"""`saena_forgectl.checks.migrations_reversible` — k3s spec §8.1 condition 6."""

from __future__ import annotations

import copy
from typing import Any

from saena_forgectl.checks.migrations_reversible import check_migrations_reversible


class TestPassingFixture:
    def test_passes(self, passing_values: dict[str, Any]) -> None:
        result = check_migrations_reversible(passing_values)
        assert result.passed is True
        assert result.name == "migrations_reversible"
        assert result.context["count"] == 1


class TestNonReversibleFails:
    def test_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["migrations"][0]["reversible"] = False
        result = check_migrations_reversible(values)
        assert result.passed is False
        assert "non-reversible" in result.context["violations"][0]["problem"]


class TestUnreviewedFails:
    def test_missing_reviewer_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        del values["migrations"][0]["reviewedBy"]
        result = check_migrations_reversible(values)
        assert result.passed is False
        assert "unreviewed" in result.context["violations"][0]["problem"]

    def test_empty_reviewer_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["migrations"][0]["reviewedBy"] = "   "
        result = check_migrations_reversible(values)
        assert result.passed is False

    def test_null_reviewer_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["migrations"][0]["reviewedBy"] = None
        result = check_migrations_reversible(values)
        assert result.passed is False


class TestBothNonReversibleAndUnreviewedNamesBoth:
    def test_problem_names_both(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["migrations"][0]["reversible"] = False
        values["migrations"][0]["reviewedBy"] = None
        result = check_migrations_reversible(values)
        assert result.passed is False
        problem = result.context["violations"][0]["problem"]
        assert "non-reversible" in problem
        assert "unreviewed" in problem


class TestNoMigrationsDeclared:
    def test_absent_key_passes_vacuously(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        del values["migrations"]
        result = check_migrations_reversible(values)
        assert result.passed is True
        assert result.context["count"] == 0

    def test_non_list_value_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["migrations"] = {"not": "a list"}
        result = check_migrations_reversible(values)
        assert result.passed is False

    def test_malformed_entry_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["migrations"].append("not-a-mapping")
        result = check_migrations_reversible(values)
        assert result.passed is False
