"""F-5 dedicated skill-bundle integrity verifier (saena_domain.execution.skill_bundle)."""

from __future__ import annotations

import os

import pytest
from saena_domain.execution import (
    SkillBundleHashMalformedError,
    SkillBundleHashMismatchError,
    SkillBundleHashMissingError,
    SkillBundleMissingError,
    SkillBundleUnreadableError,
    compute_skill_bundle_hash,
    read_skill_bundle,
    verify_skill_bundle,
)

_BUNDLE = {
    "claude/skill.md": b"# skill\nrun approved-command\n",
    "portable/allowlist.txt": b"approved-command\n",
    "third-party/ponytail-pinned/tool.py": b"print('pinned')\n",
}


def _pin(bundle: dict[str, bytes]) -> str:
    return compute_skill_bundle_hash(bundle)


class TestDeterminism:
    def test_same_bundle_three_times_is_byte_identical(self) -> None:
        h1 = compute_skill_bundle_hash(dict(_BUNDLE))
        h2 = compute_skill_bundle_hash(dict(_BUNDLE))
        h3 = compute_skill_bundle_hash(dict(_BUNDLE))
        assert h1 == h2 == h3
        assert h1.startswith("sha256:") and len(h1) == len("sha256:") + 64

    def test_insertion_order_does_not_change_hash(self) -> None:
        reordered = {k: _BUNDLE[k] for k in reversed(list(_BUNDLE))}
        assert compute_skill_bundle_hash(reordered) == compute_skill_bundle_hash(dict(_BUNDLE))

    def test_backslash_and_dotslash_paths_normalize_equal(self) -> None:
        a = {"claude/skill.md": b"x"}
        b = {"claude\\skill.md": b"x"}
        c = {"./claude/skill.md": b"x"}
        assert (
            compute_skill_bundle_hash(a)
            == compute_skill_bundle_hash(b)
            == compute_skill_bundle_hash(c)
        )


class TestVerifyAllowAndDeny:
    def test_valid_pinned_bundle_allows(self) -> None:
        pin = _pin(dict(_BUNDLE))
        assert verify_skill_bundle(expected_hash=pin, bundle=dict(_BUNDLE)) == pin

    def test_one_byte_modification_denies(self) -> None:
        pin = _pin(dict(_BUNDLE))
        tampered = dict(_BUNDLE)
        tampered["claude/skill.md"] = b"# skill\nrun EVIL-command\n"
        with pytest.raises(SkillBundleHashMismatchError):
            verify_skill_bundle(expected_hash=pin, bundle=tampered)

    def test_file_added_denies(self) -> None:
        pin = _pin(dict(_BUNDLE))
        extra = dict(_BUNDLE)
        extra["claude/extra.md"] = b"new\n"
        with pytest.raises(SkillBundleHashMismatchError):
            verify_skill_bundle(expected_hash=pin, bundle=extra)

    def test_file_deleted_denies(self) -> None:
        pin = _pin(dict(_BUNDLE))
        fewer = dict(_BUNDLE)
        del fewer["portable/allowlist.txt"]
        with pytest.raises(SkillBundleHashMismatchError):
            verify_skill_bundle(expected_hash=pin, bundle=fewer)

    def test_file_renamed_denies(self) -> None:
        pin = _pin(dict(_BUNDLE))
        renamed = dict(_BUNDLE)
        renamed["claude/renamed.md"] = renamed.pop("claude/skill.md")
        with pytest.raises(SkillBundleHashMismatchError):
            verify_skill_bundle(expected_hash=pin, bundle=renamed)

    def test_missing_expected_hash_denies(self) -> None:
        with pytest.raises(SkillBundleHashMissingError):
            verify_skill_bundle(expected_hash=None, bundle=dict(_BUNDLE))
        with pytest.raises(SkillBundleHashMissingError):
            verify_skill_bundle(expected_hash="", bundle=dict(_BUNDLE))

    @pytest.mark.parametrize(
        "bad",
        ["deadbeef", "sha256:xyz", "sha256:" + "g" * 64, "sha256:" + "a" * 63, "md5:" + "a" * 32],
    )
    def test_malformed_expected_hash_denies(self, bad: str) -> None:
        with pytest.raises(SkillBundleHashMalformedError):
            verify_skill_bundle(expected_hash=bad, bundle=dict(_BUNDLE))

    def test_missing_bundle_denies(self) -> None:
        pin = _pin(dict(_BUNDLE))
        with pytest.raises(SkillBundleMissingError):
            verify_skill_bundle(expected_hash=pin, bundle=None)

    def test_contract_hash_unchanged_but_bundle_changed_still_denies(self) -> None:
        # The whole point of F-5: the ActionContract (and its contract_hash)
        # is identical; only a bundle file changed. The dedicated verifier
        # must still deny — the contract-hash gate would not.
        pin = _pin(dict(_BUNDLE))
        swapped = dict(_BUNDLE)
        swapped["third-party/ponytail-pinned/tool.py"] = b"print('BACKDOOR')\n"
        with pytest.raises(SkillBundleHashMismatchError):
            verify_skill_bundle(expected_hash=pin, bundle=swapped)


class TestPathSafety:
    @pytest.mark.parametrize("bad", ["../escape.md", "a/../../escape", "/etc/passwd", "..\\win"])
    def test_traversal_or_absolute_path_in_bundle_denies(self, bad: str) -> None:
        with pytest.raises(SkillBundleUnreadableError):
            compute_skill_bundle_hash({bad: b"x"})

    def test_non_bytes_content_denies(self) -> None:
        with pytest.raises(SkillBundleUnreadableError):
            compute_skill_bundle_hash({"a": "not-bytes"})  # type: ignore[dict-item]


class TestSecretRedaction:
    def test_mismatch_error_never_echoes_bundle_content(self) -> None:
        secret = b"AWS_SECRET=AKIAPLANTEDDONOTECHO12345"
        pin = _pin(dict(_BUNDLE))
        tampered = dict(_BUNDLE)
        tampered["claude/skill.md"] = secret
        with pytest.raises(SkillBundleHashMismatchError) as ei:
            verify_skill_bundle(expected_hash=pin, bundle=tampered)
        exc = ei.value
        assert b"AKIAPLANTEDDONOTECHO" not in str(exc).encode()
        for v in exc.context.values():
            assert "AKIAPLANTEDDONOTECHO" not in str(v)
        # only the two digests appear in context
        assert set(exc.context.keys()) == {"expected", "actual"}


class TestRealFilesystemReader:
    def test_reads_named_files_and_hashes_match_in_memory(self, tmp_path) -> None:
        for rel, content in _BUNDLE.items():
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
        read = read_skill_bundle(str(tmp_path), relpaths=list(_BUNDLE))
        assert compute_skill_bundle_hash(read) == compute_skill_bundle_hash(dict(_BUNDLE))

    def test_symlink_entry_denies(self, tmp_path) -> None:
        outside = tmp_path / "outside.txt"
        outside.write_bytes(b"secret outside bundle")
        root = tmp_path / "bundle"
        root.mkdir()
        link = root / "link.md"
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            pytest.skip("symlink unsupported on this platform")
        with pytest.raises(SkillBundleUnreadableError):
            read_skill_bundle(str(root), relpaths=["link.md"])

    def test_symlinked_parent_escape_denies(self, tmp_path) -> None:
        secret_dir = tmp_path / "secrets"
        secret_dir.mkdir()
        (secret_dir / "key.txt").write_bytes(b"k")
        root = tmp_path / "bundle"
        root.mkdir()
        try:
            os.symlink(secret_dir, root / "sub")
        except (OSError, NotImplementedError):
            pytest.skip("symlink unsupported on this platform")
        with pytest.raises(SkillBundleUnreadableError):
            read_skill_bundle(str(root), relpaths=["sub/key.txt"])

    def test_missing_file_denies(self, tmp_path) -> None:
        root = tmp_path / "bundle"
        root.mkdir()
        with pytest.raises(SkillBundleMissingError):
            read_skill_bundle(str(root), relpaths=["nope.md"])

    def test_missing_root_denies(self, tmp_path) -> None:
        with pytest.raises(SkillBundleMissingError):
            read_skill_bundle(str(tmp_path / "nonexistent"), relpaths=["a"])
