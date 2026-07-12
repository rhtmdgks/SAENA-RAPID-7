"""`run_preflight` — load a values file and run every k3s spec §8.1 check.

This is the one function both the CLI (`saena_forgectl.cli`) and any future
programmatic caller (e.g. a CI job importing `saena_forgectl` directly)
should use — it owns the "load values, run all `ALL_CHECKS`, aggregate
into a `PreflightReport`" sequence so that behavior cannot drift between
entry points.
"""

from __future__ import annotations

from pathlib import Path

from saena_forgectl.checks import ALL_CHECKS
from saena_forgectl.models import PreflightReport
from saena_forgectl.values import load_values


def run_preflight(values_path: str | Path) -> PreflightReport:
    """Load `values_path` and run every preflight check against it.

    Raises `saena_forgectl.errors.ValuesFileError` if the values file
    cannot be loaded (propagated, not swallowed — the CLI is responsible
    for turning that into a clean exit-code-2 message; a caller invoking
    this programmatically gets the same structured exception `load_values`
    raises).
    """
    values = load_values(values_path)
    results = tuple(check(values) for check in ALL_CHECKS)
    return PreflightReport(checks=results)
