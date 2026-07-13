"""`saena_forgectl.checks.image_digest_signature` — k3s spec §8.1 condition 1."""

from __future__ import annotations

import copy
from typing import Any

from saena_forgectl.checks.image_digest_signature import check_image_digest_signature


class TestPassingFixture:
    def test_passes(self, passing_values: dict[str, Any]) -> None:
        result = check_image_digest_signature(passing_values)
        assert result.passed is True
        assert result.name == "image_digest_signature"
        assert result.context["image_count"] == 2


class TestMissingDigest:
    def test_placeholder_digest_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["images"][0]["digest"] = "sha256:REPLACE"
        result = check_image_digest_signature(values)
        assert result.passed is False
        assert any(m["item"] == "forge-console-api" for m in result.context["missing"])

    def test_absent_digest_key_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        del values["images"][0]["digest"]
        result = check_image_digest_signature(values)
        assert result.passed is False

    def test_malformed_digest_shape_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["images"][0]["digest"] = "not-a-real-digest"
        result = check_image_digest_signature(values)
        assert result.passed is False


class TestMissingSignature:
    def test_absent_signature_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        del values["images"][0]["signature"]
        result = check_image_digest_signature(values)
        assert result.passed is False

    def test_empty_signature_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["images"][0]["signature"] = "   "
        result = check_image_digest_signature(values)
        assert result.passed is False


class TestMalformedImageEntry:
    def test_non_mapping_image_entry_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["images"].append("not-a-mapping")
        result = check_image_digest_signature(values)
        assert result.passed is False
        assert any(m["item"] == "images[]" for m in result.context["missing"])


class TestNoImagesDeclared:
    def test_empty_images_list_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["images"] = []
        result = check_image_digest_signature(values)
        assert result.passed is False

    def test_absent_images_key_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        del values["images"]
        result = check_image_digest_signature(values)
        assert result.passed is False


class TestBundleDigests:
    def test_missing_policy_bundle_digest_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        values["global"]["policyBundle"]["digest"] = "sha256:REPLACE"
        result = check_image_digest_signature(values)
        assert result.passed is False
        assert any(m["item"] == "policyBundle" for m in result.context["missing"])

    def test_missing_skill_bundle_digest_fails(self, passing_values: dict[str, Any]) -> None:
        values = copy.deepcopy(passing_values)
        del values["global"]["skillBundle"]
        result = check_image_digest_signature(values)
        assert result.passed is False
        assert any(m["item"] == "skillBundle" for m in result.context["missing"])

    def test_missing_global_section_fails(self) -> None:
        result = check_image_digest_signature({"images": []})
        assert result.passed is False
