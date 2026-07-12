"""Exception hierarchy for `saena_forgectl`.

Mirrors the `error_code` + structured `context` convention used by
`saena_engine_gateway.errors` elsewhere in this repo, scoped to the one
failure family `forgectl preflight` needs to distinguish from an ordinary
check failure: the values file itself could not be turned into a mapping
at all (missing file, invalid YAML syntax, or a YAML document that parses
but is not a mapping — e.g. a bare list or scalar).
"""

from __future__ import annotations

from typing import Any


class ForgectlError(Exception):
    """Base class for every error raised by `saena_forgectl`."""

    error_code: str = "saena.forgectl.error"

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context: dict[str, Any] = dict(context) if context is not None else {}


class ValuesFileError(ForgectlError):
    """The values file could not be loaded as a YAML mapping.

    Raised for: a missing/unreadable path, invalid YAML syntax, or a
    syntactically valid YAML document whose top level is not a mapping
    (e.g. a list or a bare scalar) — `forgectl preflight` cannot run any
    check against that, and reports this as a clean, named error rather
    than letting a `yaml.YAMLError`/`AttributeError` traceback surface to
    the CLI user.
    """

    error_code = "saena.forgectl.values_file_invalid"

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(
            f"could not load values file {path!r}: {reason}",
            context={"path": path, "reason": reason},
        )
