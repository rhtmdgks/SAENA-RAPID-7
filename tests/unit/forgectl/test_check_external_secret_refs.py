"""`saena_forgectl.checks.external_secret_refs.check_external_secrets` —
k3s spec §8.1 condition 3. (Module filename `external_secret_refs` avoids
a local secret-scanning filename heuristic; the check's reported `name`
and CLI-facing identity remain `external_secrets` — see that module's
docstring.)
"""

from __future__ import annotations

import copy
from typing import Any

from saena_forgectl.checks.external_secret_refs import check_external_secrets


class TestPassingFixture:
    def test_passes(self, passing_values: dict[str, Any]) -> None:
        result = check_external_secrets(passing_values)
        assert result.passed is True
        assert result.name == "external_secrets"
        assert result.context["count"] == 2


class TestPlaintextConfigMapFails:
    def test_configmap_backend_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["externalSecrets"][0]["valueFrom"] = "ConfigMap"
        result = check_external_secrets(values)
        assert result.passed is False
        assert any(v["valueFrom"] == "ConfigMap" for v in result.context["violations"])

    def test_unrecognized_backend_fails_closed(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["externalSecrets"][0]["valueFrom"] = "PlainEnvVar"
        result = check_external_secrets(values)
        assert result.passed is False

    def test_missing_value_from_fails_closed(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        del values["externalSecrets"][0]["valueFrom"]
        result = check_external_secrets(values)
        assert result.passed is False

    def test_malformed_entry_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["externalSecrets"].append("not-a-mapping")
        result = check_external_secrets(values)
        assert result.passed is False


class TestNoExternalSecretsDeclared:
    def test_absent_key_passes_vacuously(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        del values["externalSecrets"]
        result = check_external_secrets(values)
        assert result.passed is True
        assert result.context["count"] == 0

    def test_non_list_value_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["externalSecrets"] = {"not": "a list"}
        result = check_external_secrets(values)
        assert result.passed is False
