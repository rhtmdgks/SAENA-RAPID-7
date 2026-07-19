"""Discovery seam — honest UNKNOWN default, adapter protocol (w6-12 fills)."""

from __future__ import annotations

from pathlib import Path

from saena_pilot.discovery import (
    UNKNOWN_RESULT,
    DiscoveryResult,
    SupportStatus,
    discover,
)


class _StaticAdapter:
    def detect(self, customer_root: Path) -> DiscoveryResult | None:
        if (customer_root / "index.html").is_file():
            return DiscoveryResult(
                framework="static", status=SupportStatus.SUPPORTED, detail="index.html found"
            )
        return None


def test_default_is_unknown_never_a_guess(tmp_path: Path) -> None:
    result = discover(tmp_path)
    assert result is UNKNOWN_RESULT
    assert result.status is SupportStatus.UNKNOWN
    assert result.framework == "unknown"


def test_no_matching_adapter_stays_unknown(tmp_path: Path) -> None:
    assert discover(tmp_path, adapters=[_StaticAdapter()]).status is SupportStatus.UNKNOWN


def test_positive_adapter_detection_wins(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    result = discover(tmp_path, adapters=[_StaticAdapter()])
    assert result.status is SupportStatus.SUPPORTED
    assert result.framework == "static"


def test_result_serializes_for_reports(tmp_path: Path) -> None:
    assert UNKNOWN_RESULT.to_dict() == {
        "framework": "unknown",
        "status": "UNKNOWN",
        "detail": UNKNOWN_RESULT.detail,
    }
