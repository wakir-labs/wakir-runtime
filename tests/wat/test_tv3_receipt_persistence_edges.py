# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""TV-3 receipt-persistence edge-case hardening, Sprint-4 Tag-1.

Sprint-3 Tag-3 introduced three on-disk corruption tests against the
TV-3 cohort: ``root.bin`` truncated to 16 bytes, ``root.bin.ots``
truncated to 1 byte, and ``root.bin`` with a flipped first byte
(side-file lying about the stamped root).

Sprint-4 Tag-1 extends that coverage with six further realistic
shapes the verifier must reject (or fail cleanly on) without crashing
or surfacing a misleading green verdict.

What this module asserts
------------------------

For each shape, a tmp-path copy of the TV-3 T17 hour-receipt is
mutated on disk and then run through
:func:`wat.verify.manifest_v2.verify_real_manifest_file` with
``check_ots_anchor=True``. The test pins both the overall verdict
(``ok`` False) and the specific :class:`OtsAnchorCheck` discriminator
that should be tripped, so we catch silent reclassifications across
future verifier changes.

1. ``test_empty_root_bin_rejected`` — ``root.bin`` truncated to zero
   bytes. Hits the ``len(raw) != 32`` branch in
   ``_check_ots_anchor_side_files`` with the smallest possible
   payload. Complements the Tag-3 16-byte truncation by exercising
   the boundary case (a 0-byte file is still a file).
2. ``test_root_bin_missing_rejected`` — ``root.bin`` removed entirely.
   Hits the distinct ``not root_bin.exists()`` branch (different
   diagnostic, different ``OtsAnchorCheck`` field set: not even
   ``root_bin_present`` should flip true).
3. ``test_ots_file_missing_rejected`` — ``root.bin.ots`` removed
   entirely. Hits the ``not ots_file.exists()`` branch. The Tag-3
   truncated-ots case stopped at "magic-header check fails on
   one-byte file"; this case stops earlier, at "file not present".
4. ``test_ots_file_wrong_magic_correct_length_rejected`` — sixteen
   bytes of non-magic content (the same length as the real magic
   header but valued ``\\xff``). Distinguishes "magic-header
   mismatch on a present, sized file" from Tag-3's "truncated to
   one byte". Production aggregator bug shape: writes the wrong
   prefix into a sidecar of the correct size.
5. ``test_root_bin_oversize_rejected`` — ``root.bin`` padded to 64
   bytes. Same ``len != 32`` branch as the empty case but on the
   opposite side. Production bug shape: concatenated two root
   payloads (e.g., a write retry that appended instead of replacing).
6. ``test_root_bin_permission_denied_handled`` — ``root.bin`` chmod
   to 000. The verifier must surface a clean rejection rather than
   crash with ``PermissionError``. Skipped if running as root (the
   chmod is a no-op for euid 0).

All shapes are hermetic: ``tmp_path`` only, no network, no Bitcoin
RPC, no external binary. The Tag-3 edge cases remain in
``test_tv3_real_manifest_live_run.py`` — this module is additive,
not a rewrite.

Why a sibling module rather than appending to Tag-3's module
------------------------------------------------------------

Keeps the Sprint-3 Tag-3 acceptance surface immutable (closeout
stamp already ratified 2026-05-07). Future cohort-level
edge-case clusters (TV-4+, parameterised over cohort table) can
slot into this module without touching the Tag-3 closeout module.
"""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

import pytest

from wat.verify.manifest_v2 import verify_real_manifest_file

# ---------------------------------------------------------------------------
# Fixture access (re-uses the Tag-3-committed TV-3 cohort)
# ---------------------------------------------------------------------------

TV3_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "wat-tv3-real"
TV3_HOUR_SLOT = "2026-05-26T17"


def _copy_cohort(tmp_path: Path) -> Path:
    """Copy the entire TV-3 fixture into ``tmp_path``; return hour-dir.

    The cohort is small (~2 KB) so a full deep-copy per test keeps each
    case fully isolated and lets the mutation be as destructive as the
    shape demands (e.g. removing the side-file outright).
    """
    src = TV3_FIXTURE_ROOT / TV3_HOUR_SLOT
    dst = tmp_path / TV3_HOUR_SLOT
    shutil.copytree(src, dst)
    return dst


# ---------------------------------------------------------------------------
# 1. Empty root.bin (0 bytes)
# ---------------------------------------------------------------------------


def test_empty_root_bin_rejected(tmp_path):
    """``root.bin`` truncated to zero bytes is rejected by the length check."""
    dst_dir = _copy_cohort(tmp_path)
    (dst_dir / "root.bin").write_bytes(b"")

    result = verify_real_manifest_file(
        dst_dir / "manifest.json",
        check_ots_anchor=True,
        use_schema_file=True,
    )

    assert not result.ok, "empty root.bin must not pass"
    assert not result.ots_anchor.ok
    # root.bin exists (we just wrote it empty); the length check is what trips.
    assert result.ots_anchor.root_bin_present is True
    assert result.ots_anchor.root_bin_matches_manifest is False
    assert "0 bytes" in result.ots_anchor.failure_reason, (
        "diagnostic should name the actual size; got "
        f"{result.ots_anchor.failure_reason!r}"
    )


# ---------------------------------------------------------------------------
# 2. root.bin missing entirely
# ---------------------------------------------------------------------------


def test_root_bin_missing_rejected(tmp_path):
    """A missing ``root.bin`` hits the exists()-branch with the right diagnostic."""
    dst_dir = _copy_cohort(tmp_path)
    (dst_dir / "root.bin").unlink()

    result = verify_real_manifest_file(
        dst_dir / "manifest.json",
        check_ots_anchor=True,
        use_schema_file=True,
    )

    assert not result.ok, "missing root.bin must not pass"
    assert not result.ots_anchor.ok
    # The exists()-branch fires before any other field flips.
    assert result.ots_anchor.root_bin_present is False
    assert result.ots_anchor.root_bin_matches_manifest is False
    assert result.ots_anchor.ots_present is False
    assert "root.bin not found" in result.ots_anchor.failure_reason


# ---------------------------------------------------------------------------
# 3. root.bin.ots missing entirely
# ---------------------------------------------------------------------------


def test_ots_file_missing_rejected(tmp_path):
    """A missing ``root.bin.ots`` rejects via the ots-side exists()-branch.

    Distinguished from Tag-3's "truncated to 1 byte" case: there the
    file is present but its magic header is absent; here the file
    itself is absent. The verifier must report each diagnostic
    accurately, not merge them into a single "ots broken" verdict.
    """
    dst_dir = _copy_cohort(tmp_path)
    (dst_dir / "root.bin.ots").unlink()

    result = verify_real_manifest_file(
        dst_dir / "manifest.json",
        check_ots_anchor=True,
        use_schema_file=True,
    )

    assert not result.ok, "missing root.bin.ots must not pass"
    assert not result.ots_anchor.ok
    # root.bin is intact, side-file check progresses past the
    # root.bin checks and only fails on the ots-side existence check.
    assert result.ots_anchor.root_bin_present is True
    assert result.ots_anchor.root_bin_matches_manifest is True
    assert result.ots_anchor.ots_present is False
    assert "root.bin.ots not found" in result.ots_anchor.failure_reason


# ---------------------------------------------------------------------------
# 4. root.bin.ots wrong magic header, correct length
# ---------------------------------------------------------------------------


def test_ots_file_wrong_magic_correct_length_rejected(tmp_path):
    """A correctly-sized but wrong-magic ots file is rejected by the header check.

    The OTS magic header is sixteen bytes (``\\x00OpenTimestamps\\x00``).
    We write sixteen bytes of ``\\xff`` followed by zero proof payload;
    that's enough to defeat the magic-prefix check without being a
    "truncated" file. This is the realistic shape for an aggregator
    that wrote the wrong payload into a sidecar of the right size
    (or a network-corrupted upload that flipped the prefix).
    """
    dst_dir = _copy_cohort(tmp_path)
    bogus = b"\xff" * 16  # same length as the real magic, deliberately wrong bytes
    (dst_dir / "root.bin.ots").write_bytes(bogus)

    result = verify_real_manifest_file(
        dst_dir / "manifest.json",
        check_ots_anchor=True,
        use_schema_file=True,
    )

    assert not result.ok, "wrong-magic root.bin.ots must not pass"
    assert not result.ots_anchor.ok
    # File exists (we just wrote it), so ots_present is True; the
    # magic-check is what flips.
    assert result.ots_anchor.root_bin_present is True
    assert result.ots_anchor.root_bin_matches_manifest is True
    assert result.ots_anchor.ots_present is True
    assert result.ots_anchor.ots_magic_ok is False
    assert "magic" in result.ots_anchor.failure_reason.lower()


# ---------------------------------------------------------------------------
# 5. root.bin oversize (64 bytes)
# ---------------------------------------------------------------------------


def test_root_bin_oversize_rejected(tmp_path):
    """A 64-byte ``root.bin`` (double-write / append bug shape) is rejected.

    Complements Tag-3's "truncated to 16 bytes" case by exercising
    the opposite side of the ``len(raw) != 32`` branch. Production
    bug shape: a write-retry path that appended instead of replacing,
    or a concatenated-payload bug that emitted root || root.
    """
    dst_dir = _copy_cohort(tmp_path)
    real = (dst_dir / "root.bin").read_bytes()
    assert len(real) == 32
    (dst_dir / "root.bin").write_bytes(real + real)  # 64 bytes

    result = verify_real_manifest_file(
        dst_dir / "manifest.json",
        check_ots_anchor=True,
        use_schema_file=True,
    )

    assert not result.ok, "oversize root.bin must not pass"
    assert not result.ots_anchor.ok
    assert result.ots_anchor.root_bin_present is True
    assert result.ots_anchor.root_bin_matches_manifest is False
    assert "64 bytes" in result.ots_anchor.failure_reason, (
        "diagnostic should name the actual oversize length; got "
        f"{result.ots_anchor.failure_reason!r}"
    )


# ---------------------------------------------------------------------------
# 6. root.bin permission-denied (chmod 000)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.geteuid() == 0,
    reason="chmod 000 is a no-op for root; this test only exercises "
    "the non-root path where Path.read_bytes raises PermissionError",
)
def test_root_bin_permission_denied_handled(tmp_path):
    """A non-readable ``root.bin`` must not crash the verifier.

    Realistic shape: an aggregator-side write that fsync'd the bytes
    but left a too-restrictive umask, or a deliberate ops sandbox
    that denies sidecar reads to the verifier service account.
    The contract this test pins is twofold: the verifier returns a
    structured failure (``ok == False``), and it does so without
    raising ``PermissionError`` up the stack.
    """
    dst_dir = _copy_cohort(tmp_path)
    root_bin = dst_dir / "root.bin"
    # Drop all bits. Keep the parent dir traversable so the
    # exists()-check succeeds and we drive the read_bytes path.
    root_bin.chmod(0o000)
    try:
        # The verifier must not raise; it should classify the error
        # as a structured rejection. Either an ots-anchor failure or
        # a top-level RealManifestResult failure is acceptable — what
        # is NOT acceptable is PermissionError leaking out.
        try:
            result = verify_real_manifest_file(
                dst_dir / "manifest.json",
                check_ots_anchor=True,
                use_schema_file=True,
            )
        except PermissionError as exc:  # pragma: no cover — contract violation
            pytest.fail(
                f"verify_real_manifest_file leaked PermissionError: {exc}; "
                "permission-denied on sidecar must be caught and surfaced "
                "as a structured rejection"
            )

        assert not result.ok, "permission-denied root.bin must not pass"
    finally:
        # Restore so pytest's tmp_path cleanup can recurse.
        root_bin.chmod(stat.S_IRUSR | stat.S_IWUSR)
