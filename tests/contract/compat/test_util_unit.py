"""Unit tests for harness.util (fixture-metadata stripping / tempfile
helper, promoted from test_envelope_fixtures.py's
_strip_metadata_to_tempfile pattern -- see harness/util.py docstring).
"""

from __future__ import annotations

import json
from pathlib import Path

from harness import util as util_mod


def test_strip_metadata_removes_documented_keys() -> None:
    data = {
        "tenant_id": "acme",
        "_expected_violation": "missing required field",
        "_note": "intentionally schema-valid",
    }
    stripped = util_mod.strip_metadata(data)
    assert stripped == {"tenant_id": "acme"}


def test_strip_metadata_removes_any_underscore_prefixed_key() -> None:
    """Superset behavior: any top-level "_"-prefixed key is stripped, not
    just the two currently-documented ones.
    """
    data = {"a": 1, "_future_metadata_key": "x"}
    stripped = util_mod.strip_metadata(data)
    assert stripped == {"a": 1}


def test_strip_metadata_leaves_non_metadata_untouched() -> None:
    data = {"a": 1, "b": {"nested": True}}
    stripped = util_mod.strip_metadata(data)
    assert stripped == data


def test_write_stripped_to_tempfile_writes_clean_json(tmp_path: Path) -> None:
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(
        json.dumps({"tenant_id": "acme", "_expected_violation": "bad"}), encoding="utf-8"
    )
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    out_path = util_mod.write_stripped_to_tempfile(fixture_path, out_dir)

    assert out_path.name == "fixture.json"
    assert out_path.parent == out_dir
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written == {"tenant_id": "acme"}


def test_metadata_keys_constant_matches_readme_convention() -> None:
    assert util_mod.METADATA_KEYS == ("_expected_violation", "_note")
