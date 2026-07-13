"""`deploy/charts/saena-forge/values.schema.json` — the values-file gate
that must independently reject Google/Gemini engine flags, floating (non-
digest) image tags, and inline/plaintext secret values (w2-23).
"""

from __future__ import annotations

import copy
from typing import Any

import jsonschema
import pytest


def _validator(schema: dict[str, Any]) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(schema)


class TestSchemaItselfIsValid:
    def test_values_schema_conforms_to_2020_12_metaschema(
        self, values_schema: dict[str, Any]
    ) -> None:
        jsonschema.Draft202012Validator.check_schema(values_schema)


class TestPassingValuesFile:
    def test_values_yaml_validates_against_its_own_schema(
        self, values_data: dict[str, Any], values_schema: dict[str, Any]
    ) -> None:
        validator = _validator(values_schema)
        errors = list(validator.iter_errors(values_data))
        assert errors == [], "\n".join(str(e) for e in errors)


class TestEngineScopeClosedEnumRejection:
    """The named w2-23 gate: schema INVALID for any google/gemini/bard key
    or value — mirrors forgectl's `engine_flags` check (`_KNOWN_FLAG_KEYS`),
    which tolerates the three well-known non-v1 keys present-and-false but
    fails on enablement or an unrecognized key. This schema mirrors that
    exact behavior at the values-file layer.
    """

    @pytest.fixture
    def engine_scope_schema(self, values_schema: dict[str, Any]) -> dict[str, Any]:
        return values_schema["$defs"]["engineScope"]

    def test_chatgpt_search_only_is_valid(self, engine_scope_schema: dict[str, Any]) -> None:
        assert _validator(engine_scope_schema).is_valid({"chatgptSearch": True})

    def test_documented_disabled_google_keys_are_valid(
        self, engine_scope_schema: dict[str, Any]
    ) -> None:
        payload = {
            "chatgptSearch": True,
            "googleAiOverviews": False,
            "googleAiMode": False,
            "gemini": False,
        }
        assert _validator(engine_scope_schema).is_valid(payload)

    @pytest.mark.parametrize(
        "payload",
        [
            {"chatgptSearch": True, "gemini": True},
            {"chatgptSearch": True, "googleAiOverviews": True},
            {"chatgptSearch": True, "googleAiMode": True},
            {"chatgptSearch": True, "google": True},
            {"chatgptSearch": True, "bard": False},
            {"chatgptSearch": True, "google-generative-search": True},
        ],
    )
    def test_any_google_gemini_bard_key_or_enablement_is_invalid(
        self, engine_scope_schema: dict[str, Any], payload: dict[str, Any]
    ) -> None:
        assert not _validator(engine_scope_schema).is_valid(payload)

    def test_full_values_file_with_gemini_enabled_is_rejected(
        self, values_data: dict[str, Any], values_schema: dict[str, Any]
    ) -> None:
        mutated = copy.deepcopy(values_data)
        mutated["global"]["engineScope"]["gemini"] = True
        assert not _validator(values_schema).is_valid(mutated)

    def test_full_values_file_with_unrecognized_google_key_is_rejected(
        self, values_data: dict[str, Any], values_schema: dict[str, Any]
    ) -> None:
        mutated = copy.deepcopy(values_data)
        mutated["global"]["engineScope"]["google"] = True
        assert not _validator(values_schema).is_valid(mutated)


class TestImageDigestPinning:
    @pytest.fixture
    def digest_schema(self, values_schema: dict[str, Any]) -> dict[str, Any]:
        return values_schema["$defs"]["imageDigest"]

    def test_valid_sha256_digest_accepted(self, digest_schema: dict[str, Any]) -> None:
        assert _validator(digest_schema).is_valid("sha256:" + "a" * 64)

    @pytest.mark.parametrize(
        "bad_value",
        ["latest", "v1.2.3", "sha256:REPLACE", "sha256:tooshort", "", "sha512:" + "a" * 128],
    )
    def test_floating_tag_or_placeholder_rejected(
        self, digest_schema: dict[str, Any], bad_value: str
    ) -> None:
        assert not _validator(digest_schema).is_valid(bad_value)

    def test_every_declared_image_in_values_yaml_is_digest_pinned(
        self, values_data: dict[str, Any], values_schema: dict[str, Any]
    ) -> None:
        digest_schema = values_schema["$defs"]["imageDigest"]
        validator = _validator(digest_schema)
        for image in values_data["images"]:
            assert validator.is_valid(image["digest"]), image

    def test_every_service_image_in_values_yaml_is_digest_pinned(
        self, values_data: dict[str, Any], values_schema: dict[str, Any]
    ) -> None:
        digest_schema = values_schema["$defs"]["imageDigest"]
        validator = _validator(digest_schema)
        for service_key, service in values_data["services"].items():
            assert validator.is_valid(service["image"]["digest"]), service_key

    def test_policy_and_skill_bundle_digests_are_pinned(
        self, values_data: dict[str, Any], values_schema: dict[str, Any]
    ) -> None:
        digest_schema = values_schema["$defs"]["imageDigest"]
        validator = _validator(digest_schema)
        assert validator.is_valid(values_data["global"]["policyBundle"]["digest"])
        assert validator.is_valid(values_data["global"]["skillBundle"]["digest"])


class TestNoPlaintextSecretFields:
    @pytest.fixture
    def deny_schema(self, values_schema: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "allOf": [values_schema["$defs"]["noPlaintextSecretFields"]],
        }

    @pytest.mark.parametrize(
        "key",
        ["password", "Password", "PASSWORD", "secret", "Secret", "token", "apiKey", "privateKey"],
    )
    def test_bare_plaintext_secret_key_rejected(
        self, deny_schema: dict[str, Any], key: str
    ) -> None:
        assert not _validator(deny_schema).is_valid({key: "hunter2"})

    @pytest.mark.parametrize(
        "key",
        [
            "credentialsSecretRef",
            "dbSecretName",
            "postgresCredentialsSecretRef",
            "host",
            "port",
        ],
    )
    def test_reference_shaped_or_unrelated_key_accepted(
        self, deny_schema: dict[str, Any], key: str
    ) -> None:
        assert _validator(deny_schema).is_valid({key: "some-value"})

    def test_postgres_block_in_values_yaml_has_no_plaintext_secret_field(
        self, values_data: dict[str, Any], values_schema: dict[str, Any]
    ) -> None:
        schema = {"type": "object", "allOf": [values_schema["$defs"]["noPlaintextSecretFields"]]}
        assert _validator(schema).is_valid(values_data["postgres"])

    def test_object_storage_block_in_values_yaml_has_no_plaintext_secret_field(
        self, values_data: dict[str, Any], values_schema: dict[str, Any]
    ) -> None:
        schema = {"type": "object", "allOf": [values_schema["$defs"]["noPlaintextSecretFields"]]}
        assert _validator(schema).is_valid(values_data["objectStorage"])

    def test_event_bus_block_in_values_yaml_has_no_plaintext_secret_field(
        self, values_data: dict[str, Any], values_schema: dict[str, Any]
    ) -> None:
        schema = {"type": "object", "allOf": [values_schema["$defs"]["noPlaintextSecretFields"]]}
        assert _validator(schema).is_valid(values_data["eventBus"])


class TestExternalSecretsValueFromClosedEnum:
    def test_config_map_backend_is_not_a_permitted_valuefrom(
        self, values_schema: dict[str, Any]
    ) -> None:
        item_schema = values_schema["properties"]["externalSecrets"]["items"]
        validator = _validator(item_schema)
        assert not validator.is_valid(
            {"name": "x", "source": "external-secrets-operator", "valueFrom": "ConfigMap"}
        )

    @pytest.mark.parametrize("kind", ["SecretStore", "ClusterSecretStore"])
    def test_permitted_secret_store_kinds_accepted(
        self, values_schema: dict[str, Any], kind: str
    ) -> None:
        item_schema = values_schema["properties"]["externalSecrets"]["items"]
        validator = _validator(item_schema)
        assert validator.is_valid({"name": "x", "source": "esops", "valueFrom": kind})

    @pytest.mark.parametrize(
        "invalid_kind", ["VaultSecret", "ConfigMap", "Secret", "AWSSecret", ""]
    )
    def test_non_secret_store_kinds_rejected(
        self, values_schema: dict[str, Any], invalid_kind: str
    ) -> None:
        # secretStoreRef.kind's only real ESO values are SecretStore /
        # ClusterSecretStore. VaultSecret (a provider, not a kind) was the
        # critic MUST-FIX; ConfigMap is the k3s §8.1 condition-3 plaintext fail.
        item_schema = values_schema["properties"]["externalSecrets"]["items"]
        validator = _validator(item_schema)
        assert not validator.is_valid({"name": "x", "source": "esops", "valueFrom": invalid_kind})

    def test_every_external_secret_in_values_yaml_uses_a_valid_store_kind(
        self, values_data: dict[str, Any]
    ) -> None:
        valid_kinds = {"SecretStore", "ClusterSecretStore"}
        for entry in values_data["externalSecrets"]:
            assert entry["valueFrom"] in valid_kinds, entry
