"""Redaction guarantees (task instructions: "Redaction: reason/detail never
contain secret values or source file contents (test with planted
secret)")."""

from __future__ import annotations

from hooks_runtime_factories import RUN_ID, TENANT_ID, TRACE_ID, TS, make_budget, make_contract
from saena_hooks_runtime.hooks.session_start import SecretFinding, SessionStartInput, session_start
from saena_hooks_runtime.redact import redact_known, redact_patterns


def test_redact_known_strips_literal_secret_value() -> None:
    secret = "sk-thisIsAPlantedFakeSecretValue1234567890"
    text = f"found credential {secret} in config"
    redacted = redact_known(text, (secret,))
    assert secret not in redacted
    assert "[REDACTED]" in redacted


def test_redact_known_prefers_longer_secret_first() -> None:
    short = "abc123"
    long = "abc123-extended-secret-suffix"
    text = f"leaked: {long}"
    redacted = redact_known(text, (short, long))
    assert long not in redacted
    assert short not in redacted


def test_redact_patterns_masks_aws_key() -> None:
    text = "AKIAABCDEFGHIJKLMNOP leaked in log"
    redacted = redact_patterns(text)
    assert "AKIAABCDEFGHIJKLMNOP" not in redacted


def test_redact_patterns_masks_github_token() -> None:
    text = "token ghp_1234567890abcdefghijklmnopqrstuvwx leaked"
    redacted = redact_patterns(text)
    assert "ghp_1234567890abcdefghijklmnopqrstuvwx" not in redacted


def test_redact_patterns_masks_private_key_block() -> None:
    text = (
        "-----BEGIN PRIVATE KEY-----\n"
        "MIIBVgIBADANBgkqhkiG9w0BAQEFAASCAT8wggE7AgEAAkEA\n"
        "-----END PRIVATE KEY-----"
    )
    redacted = redact_patterns(text)
    assert "MIIBVgIBADANBgkqhkiG9w0BAQEFAASCAT8wggE7AgEAAkEA" not in redacted


def test_session_start_secret_scan_detail_never_carries_raw_value() -> None:
    """End-to-end planted-secret test through the actual `session_start`
    hook, not just the `redact` module in isolation."""
    planted_secret = "sk-plantedTestSecretDoNotLeakThisValue000111"
    finding = SecretFinding(
        location="src/app/config.ts:42",
        rule_id="openai-secret-key",
        raw_value=planted_secret,
    )
    result = session_start(
        SessionStartInput(
            ts=TS,
            run_id=RUN_ID,
            tenant_id=TENANT_ID,
            trace_id=TRACE_ID,
            contract=make_contract(),
            worktree_dirty=False,
            policy_signature_valid=True,
            secret_findings=(finding,),
            budget=make_budget("session_start"),
        )
    )
    assert planted_secret not in result.detail
    assert planted_secret not in result.audit.detail
    # the location/rule id (non-secret metadata) IS allowed through.
    assert "src/app/config.ts:42" in result.detail
