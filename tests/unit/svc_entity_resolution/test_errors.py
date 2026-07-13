"""Unit tests: `saena_entity_resolution.errors` — error shape/context/
`to_job_error()` rendering conventions."""

from __future__ import annotations

from saena_domain.execution import JobError
from saena_entity_resolution.errors import (
    AliasConflictError,
    CompetitorOwnershipDeniedError,
    CrossTenantEntityAccessError,
    EmptyAliasSetError,
    EntityGraphNotFoundError,
    EntityResolutionError,
)

_ALL_ERROR_CLASSES = (
    EntityResolutionError,
    CompetitorOwnershipDeniedError,
    AliasConflictError,
    EmptyAliasSetError,
    CrossTenantEntityAccessError,
    EntityGraphNotFoundError,
)


class TestErrorShape:
    def test_every_error_has_a_saena_dot_prefixed_error_code(self) -> None:
        for cls in _ALL_ERROR_CLASSES:
            assert cls.error_code.startswith("saena.")

    def test_every_error_code_is_unique(self) -> None:
        codes = [cls.error_code for cls in _ALL_ERROR_CLASSES]
        assert len(codes) == len(set(codes))

    def test_context_defaults_to_empty_dict(self) -> None:
        err = EntityResolutionError("boom")
        assert err.context == {}

    def test_context_is_stored_and_copied_not_aliased(self) -> None:
        original_context = {"key": "value"}
        err = EntityResolutionError("boom", context=original_context)
        original_context["key"] = "mutated"
        assert err.context["key"] == "value"

    def test_to_dict_includes_error_code_message_and_context(self) -> None:
        err = CompetitorOwnershipDeniedError("boom", context={"entity_id": "e1"})
        rendered = err.to_dict()
        assert rendered["error_code"] == CompetitorOwnershipDeniedError.error_code
        assert rendered["message"] == "boom"
        assert rendered["entity_id"] == "e1"

    def test_to_job_error_produces_valid_job_error(self) -> None:
        err = CrossTenantEntityAccessError("cross tenant denied")
        job_error = err.to_job_error()
        assert isinstance(job_error, JobError)
        assert job_error.error_code == CrossTenantEntityAccessError.error_code
        assert job_error.summary == "cross tenant denied"
        assert job_error.retryable is False

    def test_every_error_category_is_a_known_job_error_category(self) -> None:
        from saena_domain.execution.job_error import KNOWN_ERROR_CATEGORIES

        for cls in _ALL_ERROR_CLASSES:
            category = cls.error_code.split(".")[1]
            assert category in KNOWN_ERROR_CATEGORIES, cls.error_code

    def test_to_job_error_never_raises_for_any_declared_error_class(self) -> None:
        for cls in _ALL_ERROR_CLASSES:
            instance = cls("test message")
            # Must not raise JobErrorValidationError.
            instance.to_job_error()
