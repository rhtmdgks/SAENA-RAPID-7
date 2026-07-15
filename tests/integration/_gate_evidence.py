"""Runtime-backed EVIDENCE for the required measurement gates (Wave 5 Closure —
evidence-integrity remediation).

Why this exists
---------------
The CI job summaries previously emitted an UNCONDITIONAL static claim ("ran the
full hardcoded path set with the required env armed") from an `if: always()`
step — so the summary asserted success even when the gate step FAILED (exit 6)
or ran a partial subset. A summary must never claim an action happened merely
because the summary step itself ran.

This module lets the completeness guard (in the conftests) emit a MACHINE-
GENERATED evidence file describing what actually executed — including positive
runtime WITNESSES that real Postgres/ClickHouse/Temporal containers started —
bound to the current commit + CI run. A separate renderer
(`tools/validation/render_gate_evidence.py`) reads that file and renders the summary,
failing CLOSED (non-zero, `NOT PROVEN`/`FAILED`) when evidence is missing,
malformed, stale (wrong SHA/run), or reports an incomplete/failed gate. Real-
container execution is proven only by the recorded fixture witnesses, never
inferred from an env var or a test-selection string.

TEST-SUPPORT ONLY — never imported by any production/runtime package (it lives
under `tests/` and is imported only by the integration conftests + the renderer
+ the guard self-tests).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

#: Bump when the evidence JSON shape changes; the renderer pins this exact value
#: and fails closed on a mismatch (a stale evidence file from an older schema
#: must never render as success).
SCHEMA_VERSION = "saena.gate-evidence/v1"

#: The gate provides the fixture-recorded evidence PATH via this env var (set by
#: the `just measurement-*` recipe). When UNSET (plain local dev), the guard
#: no-ops the write — the process exit code stays authoritative and no stale
#: file is produced.
EVIDENCE_PATH_ENV = "SAENA_GATE_EVIDENCE_PATH"

#: A per-invocation nonce the recipe generates (uuid); recorded in the evidence
#: and echoed to the renderer so a file cannot be reused across invocations.
INVOCATION_ID_ENV = "SAENA_GATE_INVOCATION_ID"

# --------------------------------------------------------------------------- #
# Real-container witness registry. A fixture that ACTUALLY starts a real
# container/test-server records a positive witness here; the guard serializes
# them so "real_containers_proven" reflects runtime truth, not an env-var guess.
# Process-global (one gate invocation == one process). Reset defensively at
# import so a reused interpreter never inherits a prior run's witnesses.
# --------------------------------------------------------------------------- #
_WITNESSES: dict[str, dict[str, Any]] = {}


def record_container_witness(
    leg: str, *, image: str, container_id: str | None = None, detail: str | None = None
) -> None:
    """Called by a fixture the moment it has a RUNNING real container/test-server.
    ``leg`` is one of the backend legs (postgres/clickhouse/temporal). ``image``
    is the concrete image ref (or server identity for Temporal). Never records a
    secret."""
    _WITNESSES[leg] = {
        "leg": leg,
        "image": image,
        "container_id": container_id,
        "detail": detail,
        "started": True,
    }


def witnesses() -> dict[str, dict[str, Any]]:
    return {k: dict(v) for k, v in _WITNESSES.items()}


def reset_witnesses() -> None:
    _WITNESSES.clear()


def _git_head() -> str | None:
    try:
        out = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[2]),
            timeout=10,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def run_binding() -> dict[str, Any]:
    """Identity that binds an evidence file to THIS commit + CI run, so a stale
    file from a different SHA/run cannot render as success."""
    return {
        "commit_sha": os.environ.get("GITHUB_SHA") or _git_head(),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "invocation_id": os.environ.get(INVOCATION_ID_ENV),
    }


def evidence_path() -> Path | None:
    raw = os.environ.get(EVIDENCE_PATH_ENV)
    return Path(raw) if raw else None


def write_evidence(payload: dict[str, Any]) -> Path | None:
    """Serialize the gate's evidence to ``SAENA_GATE_EVIDENCE_PATH`` (atomic
    replace). No-op (returns None) when the path env is unset (plain local dev).
    Always stamps schema_version + run_binding so the renderer can verify
    freshness. Writes even on a FAILED/partial gate so the renderer sees the
    true (failing) state rather than a missing file it must guess about."""
    path = evidence_path()
    if path is None:
        return None
    full = {
        "schema_version": SCHEMA_VERSION,
        **payload,
        "run_binding": run_binding(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(full, indent=2, sort_keys=True))
    tmp.replace(path)
    return path
