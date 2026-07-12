"""packages/contracts/openapi/contract-validation/v1/openapi.yaml composition
proof (w1-11, approved plan §2 "API 문서" / §6 "openapi" gate row).

Asserts:
  - the document parses as YAML (pyyaml).
  - all 15 components.schemas entries $ref-resolve to an existing file on
    disk (13 catalog contracts -- RunContext split into 2 files, ruling
    R10 -- plus common/envelope EventEnvelope + common/problem-detail
    ProblemDetail, per the file's own top-comment).
  - negative: a temp copy with a bogus $ref is detected by the same
    file-existence check function (proves the detector actually
    detects, not just vacuously passes on already-correct data).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
OPENAPI_PATH = (
    REPO_ROOT / "packages" / "contracts" / "openapi" / "contract-validation" / "v1" / "openapi.yaml"
)

EXPECTED_COMPONENT_COUNT = 15


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_openapi_file_exists() -> None:
    assert OPENAPI_PATH.is_file(), f"openapi.yaml missing at {OPENAPI_PATH}"


def test_openapi_parses_as_yaml() -> None:
    document = _load_yaml(OPENAPI_PATH)
    assert isinstance(document, dict)
    assert document.get("openapi", "").startswith("3.1")


def test_openapi_has_no_paths_key() -> None:
    """Composition-validation document, not a service API -- must declare
    no paths at all (approved plan '경로 0 -- 서비스 endpoint 금지 준수'),
    verified as fully absent (not `paths: {}`) per the document's own
    top-comment claim.
    """
    document = _load_yaml(OPENAPI_PATH)
    assert "paths" not in document, "openapi.yaml must omit 'paths' entirely (no service endpoints)"


def test_components_schemas_count_is_15() -> None:
    document = _load_yaml(OPENAPI_PATH)
    schemas = document["components"]["schemas"]
    assert len(schemas) == EXPECTED_COMPONENT_COUNT, (
        f"expected {EXPECTED_COMPONENT_COUNT} components.schemas entries, found {len(schemas)}: "
        f"{sorted(schemas)}"
    )


def _resolve_ref_file(ref: str, base_dir: Path) -> Path:
    ref_path_part = ref.split("#", 1)[0]
    return (base_dir / ref_path_part).resolve()


def find_dangling_schema_refs(document: dict[str, Any], base_dir: Path) -> list[str]:
    """Return a list of "<component-name>: <ref>" strings for every
    components.schemas entry whose $ref does not resolve to an existing
    file. Empty list = all refs resolve (the function this module's
    negative test proves is a real detector, not the module-level
    happy-path test alone).
    """
    dangling: list[str] = []
    schemas = document["components"]["schemas"]
    for name, value in schemas.items():
        ref = value.get("$ref")
        if ref is None:
            dangling.append(f"{name}: missing $ref entirely")
            continue
        resolved = _resolve_ref_file(ref, base_dir)
        if not resolved.is_file():
            dangling.append(f"{name}: $ref {ref!r} does not resolve to a file ({resolved})")
    return dangling


def test_all_component_refs_resolve_to_existing_files() -> None:
    document = _load_yaml(OPENAPI_PATH)
    dangling = find_dangling_schema_refs(document, OPENAPI_PATH.parent)
    assert not dangling, "dangling component $refs found:\n" + "\n".join(dangling)


def test_negative_bogus_ref_is_detected(tmp_path: Path) -> None:
    """Corrupt a temp copy of the parsed document with a bogus $ref on one
    component and assert `find_dangling_schema_refs` actually flags it --
    proves the detector function is live, not just happening to pass
    because the real document is already correct.
    """
    document = _load_yaml(OPENAPI_PATH)
    schema_names = list(document["components"]["schemas"])
    victim = schema_names[0]
    document["components"]["schemas"][victim] = {
        "$ref": "../../../json-schema/does/not/exist/v1/nonexistent.schema.json"
    }
    dangling = find_dangling_schema_refs(document, OPENAPI_PATH.parent)
    assert dangling, "expected the planted bogus $ref to be detected but detector found nothing"
    assert any(victim in entry for entry in dangling)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
