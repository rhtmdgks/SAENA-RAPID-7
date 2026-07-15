"""w5-21 integration: forgectl §8.1 preflight over the REAL saena-forge chart
values, positive and (engine-scope) negative. Marked `integration` — it shells
out to the forgectl CLI against the on-disk chart, not a synthetic fixture.
"""

from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.integration


def _preflight(values_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "saena_forgectl", "preflight", "--values", str(values_path)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_preflight_passes_for_the_real_measurement_values(values_file: Path) -> None:
    result = _preflight(values_file)
    assert "all checks passed" in result.stdout, result.stdout + result.stderr


@pytest.mark.parametrize("forbidden_key", ["gemini", "googleAiOverviews", "googleAiMode", "google"])
def test_preflight_fails_when_a_forbidden_engine_flag_is_enabled(
    values_file: Path, tmp_path: Path, forbidden_key: str
) -> None:
    values = yaml.safe_load(values_file.read_text())
    mutated = copy.deepcopy(values)
    mutated["global"]["engineScope"][forbidden_key] = True
    bad = tmp_path / "values-forbidden-engine.yaml"
    bad.write_text(yaml.safe_dump(mutated))

    result = _preflight(bad)
    assert "engine_flags" in result.stdout, result.stdout + result.stderr
    assert "FAILED" in result.stdout, result.stdout


def test_grs_policy_bundle_is_a_secret_ref_never_a_value(values_file: Path) -> None:
    values = yaml.safe_load(values_file.read_text())
    ext = {e["name"]: e for e in values["externalSecrets"]}
    assert "saena-grs-policy-bundle" in ext
    assert ext["saena-grs-policy-bundle"]["valueFrom"] in {"SecretStore", "ClusterSecretStore"}
