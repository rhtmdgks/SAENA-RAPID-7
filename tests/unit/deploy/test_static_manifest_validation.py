"""Static Kubernetes-manifest schema validation for the rendered saena-forge
chart (w2-23). Uses `kubeconform` (installed via `brew install kubeconform`
in this environment — no live cluster contacted, pure offline JSON-Schema
validation against bundled/downloaded Kubernetes API schemas) rather than
`kubectl apply --dry-run=client`; both are documented as acceptable in the
task brief, kubeconform was chosen because it needs no kubeconfig/API-server
reachability at all (not even a dry-run client-side call), matching this
environment's sandboxing constraints.

Skipped (not failed) if `kubeconform` is not on PATH — this test documents
and exercises static validation, it does not gate `just verify` on a tool
that may not be present in every environment this suite runs in.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("kubeconform") is None or shutil.which("helm") is None,
    reason="kubeconform and/or helm binary not available on PATH",
)


def _render_chart(chart_dir: Path, tmp_path: Path) -> Path:
    out_path = tmp_path / "rendered.yaml"
    result = subprocess.run(
        ["helm", "template", "saena-forge", str(chart_dir)],
        capture_output=True,
        text=True,
        check=True,
    )
    out_path.write_text(result.stdout, encoding="utf-8")
    return out_path


def _run_kubeconform(rendered: Path) -> subprocess.CompletedProcess[str]:
    # `-verbose` is required for `-output json` to emit a `resources[]`
    # entry per resource (valid AND skipped) — without it, JSON output
    # only lists non-valid resources, which is not enough to assert "the
    # only skipped resources are ExternalSecret CRDs" below.
    return subprocess.run(
        [
            "kubeconform",
            "-strict",
            "-kubernetes-version",
            "1.29.0",
            "-ignore-missing-schemas",
            "-verbose",
            "-output",
            "json",
            str(rendered),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


class TestKubeconformStaticValidation:
    def test_rendered_manifests_pass_kubeconform_strict(
        self, chart_dir: Path, tmp_path: Path
    ) -> None:
        rendered = _render_chart(chart_dir, tmp_path)
        result = _run_kubeconform(rendered)
        assert result.returncode == 0, result.stdout + result.stderr
        report = json.loads(result.stdout)
        resources = report["resources"]
        invalid = [r for r in resources if r["status"] == "statusInvalid"]
        errored = [r for r in resources if r["status"] == "statusError"]
        valid = [r for r in resources if r["status"] == "statusValid"]
        assert invalid == [], invalid
        assert errored == [], errored
        assert len(valid) >= 60

    def test_only_externalsecret_crd_resources_are_skipped(
        self, chart_dir: Path, tmp_path: Path
    ) -> None:
        """The only resources kubeconform can't validate (no bundled schema)
        should be the external-secrets-operator `ExternalSecret` CRD
        objects — every native Kubernetes kind this chart emits must have a
        schema kubeconform recognizes and must validate cleanly."""
        rendered = _render_chart(chart_dir, tmp_path)
        result = _run_kubeconform(rendered)
        report = json.loads(result.stdout)
        skipped = [r for r in report["resources"] if r["status"] == "statusSkipped"]
        assert skipped, "expected at least the 4 ExternalSecret resources to be skipped"
        for r in skipped:
            assert r["kind"] == "ExternalSecret"
