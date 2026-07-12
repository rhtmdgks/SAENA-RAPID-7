"""`saena_forgectl.values.load_values` — YAML loading + clean error surface."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import fixture_path
from saena_forgectl.errors import ValuesFileError
from saena_forgectl.values import load_values


class TestLoadValuesSuccess:
    def test_loads_passing_fixture_as_dict(self) -> None:
        values = load_values(fixture_path("values-passing.yaml"))
        assert isinstance(values, dict)
        assert values["global"]["engineScope"]["chatgptSearch"] is True

    def test_accepts_path_object(self) -> None:
        values = load_values(Path(fixture_path("values-passing.yaml")))
        assert isinstance(values, dict)

    def test_accepts_string_path(self) -> None:
        values = load_values(str(fixture_path("values-passing.yaml")))
        assert isinstance(values, dict)


class TestLoadValuesMissingFile:
    def test_raises_values_file_error(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.yaml"
        with pytest.raises(ValuesFileError) as exc_info:
            load_values(missing)
        assert exc_info.value.error_code == "saena.forgectl.values_file_invalid"
        assert exc_info.value.path == str(missing)

    def test_no_traceback_leaks_oserror(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.yaml"
        try:
            load_values(missing)
        except ValuesFileError as exc:
            assert "could not read file" in exc.reason
        else:
            pytest.fail("expected ValuesFileError")


class TestLoadValuesInvalidSyntax:
    def test_raises_values_file_error(self) -> None:
        with pytest.raises(ValuesFileError) as exc_info:
            load_values(fixture_path("values-invalid-syntax.yaml"))
        assert "invalid YAML" in exc_info.value.reason


class TestLoadValuesNonMapping:
    def test_raises_values_file_error_for_list_document(self) -> None:
        with pytest.raises(ValuesFileError) as exc_info:
            load_values(fixture_path("values-malformed.yaml"))
        assert "must be a mapping" in exc_info.value.reason
        assert "list" in exc_info.value.reason

    def test_raises_values_file_error_for_empty_file(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.yaml"
        empty.write_text("", encoding="utf-8")
        with pytest.raises(ValuesFileError) as exc_info:
            load_values(empty)
        assert "NoneType" in exc_info.value.reason

    def test_raises_values_file_error_for_scalar_document(self, tmp_path: Path) -> None:
        scalar = tmp_path / "scalar.yaml"
        scalar.write_text("just a string\n", encoding="utf-8")
        with pytest.raises(ValuesFileError):
            load_values(scalar)
