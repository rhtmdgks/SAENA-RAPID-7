"""ADR-0024(f) uri-field structural ban — reject `?`/`#` in stored uri fields.

`packages/schemas/saena_schemas/domain/patch_artifact_v1`'s generated
`UriRef` RootModel already enforces
`^[a-z0-9+.-]+://[^?#]+$` on `PatchArtifact.artifact_uri`/`.manifest_uri` at
pydantic-validation time (codegen from `packages/contracts`, ADR-0024f) —
this module exists for two things pydantic's own error alone does not give
the service layer:

1. A stable `error_code`/`ArtifactRegistryError` mapped to RFC 9457 400 via
   `problem.py`, rather than a raw pydantic `ValidationError`.
2. Defense in depth against ANY other uri-shaped field a manifest might
   carry beyond the two the generated model already declares (e.g. a nested
   free-form field in `manifest` extras) — `validate_uri_fields` walks the
   full manifest dict recursively and applies the same ADR-0024(f) pattern
   to every string value under a key ending in `_uri`.
"""

from __future__ import annotations

import re
from typing import Any

from saena_artifact_registry.errors import InvalidUriFieldError

#: ADR-0024(f) common uri-field pattern — scheme + `://` + no `?`/`#`.
URI_FIELD_PATTERN = re.compile(r"^[a-z0-9+.-]+://[^?#]+$")


def _is_uri_key(key: str) -> bool:
    return key.endswith("_uri") or key == "uri"


def validate_uri_fields(manifest: dict[str, Any], *, path: str = "") -> None:
    """Recursively validate every `*_uri`/`uri` string value in `manifest`.

    Raises `InvalidUriFieldError` (400) on the first violation — a
    non-string value under a uri-shaped key, or a string that does not
    match `URI_FIELD_PATTERN` (missing scheme, or containing `?`/`#`).
    """
    for key, value in manifest.items():
        field_path = f"{path}.{key}" if path else key
        if isinstance(value, dict):
            validate_uri_fields(value, path=field_path)
            continue
        if isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    validate_uri_fields(item, path=f"{field_path}[{index}]")
            continue
        if _is_uri_key(key) and (not isinstance(value, str) or not URI_FIELD_PATTERN.match(value)):
            raise InvalidUriFieldError(
                f"field {field_path!r} is not a valid ADR-0024(f) uri "
                "(scheme required, '?'/'#' forbidden)",
                context={"field": field_path},
            )


__all__ = ["URI_FIELD_PATTERN", "validate_uri_fields"]
