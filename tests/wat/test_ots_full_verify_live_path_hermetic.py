# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic live-path coverage for ``ots verify``-Voll-Integration.

Sprint-4 Tag-2. The Tag-4 hermetic suite in
``test_ots_full_verify.py`` monkey-patches
:func:`wat.anchor.ots_anchor.verify_receipt` directly. That pins the
verifier-contract surface of :mod:`wat.verify.manifest_v2` but it does
**not** pin :func:`verify_receipt` itself: the subprocess plumbing
that shells out to the ``ots`` CLI, the parsing of the local-node
``Success!`` line, the Esplora HTTP fallback chain that consumes
``ots info`` output and resolves block heights to confirmed block
hashes. All of those branches were only covered by the live-gated
``OTS_INTEGRATION_TEST=1`` smokes that need a real ``ots`` binary on
``$PATH`` and a network round-trip to a public Esplora endpoint.

This module covers the same branches hermetically by mocking the two
boundaries that ``verify_receipt`` reaches out to:

1. ``subprocess.run`` (used by :func:`wat.anchor.ots_anchor._run_ots`
   to invoke ``ots verify`` / ``ots info``) — replaced with a fake
   that returns a fixture :class:`subprocess.CompletedProcess`.
2. :func:`wat.anchor.esplora.lookup_block_with_cache` — replaced with
   a fake that returns a fixture :class:`BlockLookupResult` or raises
   :class:`EsploraError`, so the fallback path can be exercised
   without ever opening a socket.

The TV-3 single-hour-genesis fixture under
``tests/fixtures/wat-tv3-real`` is reused: the on-disk ``root.bin`` /
``root.bin.ots`` side-files and the manifest are the realistic
substrate the manifest-v2 verifier reads. Only the two outbound
boundaries are mocked; everything else (file I/O, JSON parsing,
shape validation, header pinning) runs the production code.

Test inventory (5 hermetic tests, all default-enabled):

1. ``test_local_node_success_path`` — ``ots verify`` returns
   ``Success!`` directly; Esplora is not consulted; ``ok=True``,
   ``full_verify_ok=True``.
2. ``test_local_node_pending_then_esplora_confirms`` — ``ots verify``
   returns a "pending" stdout; ``ots info`` lists one
   ``BitcoinBlockHeaderAttestation`` line; Esplora confirms; final
   verdict ``ok=True``, ``full_verify_ok=True``.
3. ``test_local_node_pending_no_heights_in_info_rejects`` — ``ots
   verify`` is pending; ``ots info`` lists no
   ``BitcoinBlockHeaderAttestation`` lines (truly unfinalised);
   ``verify_receipt`` returns False, manifest-v2 emits a hard
   rejection (``ok=False``, ``failure_reason`` populated).
4. ``test_local_node_pending_esplora_unreachable_hard_reject`` —
   ``ots verify`` is pending; ``ots info`` lists one height;
   :func:`lookup_block_with_cache` raises ``EsploraError``; the
   fallback returns False -> ``ok=False``,
   ``full_verify_ok=False``.
5. ``test_subprocess_timeout_is_soft_skip`` — ``ots verify`` raises
   :class:`subprocess.TimeoutExpired`; ``verify_receipt`` translates
   that into ``AnchorError``; the manifest-v2 wrapper surfaces it as
   ``full_verify_skipped_reason`` and keeps ``ok=True`` (magic-header
   pin still authoritative).

Why not pin the cohort-level ``ok`` only? The discriminator fields
on :class:`OtsAnchorCheck` (``full_verify_attempted``,
``full_verify_ok``, ``full_verify_skipped_reason``) distinguish the
three Tag-4 verdict shapes (local-node green, hard-reject, soft-skip)
and the verifier promises each shape semantically. Pinning the
discriminators — not just ``ok`` — means a future refactor that
silently reclassifies a hard reject as a soft skip breaks the test.
"""

# ruff: noqa: S101  — pytest's assert idiom is the whole point.

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from wat.anchor import esplora, ots_anchor
from wat.verify.manifest_v2 import verify_real_manifest_file

REPO_ROOT = Path(__file__).resolve().parents[2]
TV3_FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "wat-tv3-real"


def _pick_tv3_hour() -> Path:
    """Return one TV-3 hour-receipt directory from the live fixture."""
    candidates = sorted(p for p in TV3_FIXTURE_ROOT.iterdir() if p.is_dir())
    if not candidates:
        pytest.skip("TV-3 fixture cohort missing — run sprint-3-tag-3 first.")
    return candidates[0]


def _make_completed(
    args: list[str], returncode: int, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    """Build a CompletedProcess that looks like an ``ots`` subprocess result."""
    return subprocess.CompletedProcess(
        args=args, returncode=returncode, stdout=stdout, stderr=stderr
    )


def _fake_resolve_binary() -> str:
    """Stub ``_resolve_ots_binary`` so tests do not need ``ots`` on $PATH."""
    return "/usr/bin/ots-mock"


# ---------------------------------------------------------------------------
# 1. Local-node green path
# ---------------------------------------------------------------------------


def test_local_node_success_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ots verify`` returns Success! -> verdict locked at local-node level."""
    hour_dir = _pick_tv3_hour()

    calls: list[list[str]] = []

    def fake_run(
        cmd: list[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        # The wrapper in ``_run_ots`` rewrites the binary path; capture
        # the second positional (the subcommand) for the assertion.
        if "verify" in cmd:
            return _make_completed(cmd, 0, stdout="Success!\n")
        # The Esplora fallback would call ``info``; if we land here the
        # test contract is violated (local node should have decided).
        raise AssertionError(
            f"Esplora fallback unexpectedly invoked via ots info; cmd={cmd}"
        )

    monkeypatch.setattr(ots_anchor, "_resolve_ots_binary", _fake_resolve_binary)
    monkeypatch.setattr(ots_anchor.subprocess, "run", fake_run)

    result = verify_real_manifest_file(
        hour_dir / "manifest.json", ots_full_verify=True
    )

    assert result.ok is True
    assert result.ots_anchor.full_verify_attempted is True
    assert result.ots_anchor.full_verify_ok is True
    assert result.ots_anchor.full_verify_skipped_reason == ""
    assert result.failure_reason == ""
    # The verifier must have shelled out exactly once (ots verify);
    # the Esplora fallback path must not have been touched.
    assert len(calls) == 1
    assert "verify" in calls[0]


# ---------------------------------------------------------------------------
# 2. Esplora fallback green path
# ---------------------------------------------------------------------------


def test_local_node_pending_then_esplora_confirms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local-node pending + Esplora confirms -> verdict locked at fallback."""
    hour_dir = _pick_tv3_hour()

    seen_cmds: list[list[str]] = []
    lookup_args: list[int] = []

    info_blob = (
        "Got 1 attestation(s) from "
        "BitcoinBlockHeaderAttestation(840000)\n"
    )

    def fake_run(
        cmd: list[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        seen_cmds.append(cmd)
        if "verify" in cmd:
            # Local node could not resolve -> not "Success!".
            return _make_completed(
                cmd, 0, stdout="Calendar response: pending\n"
            )
        if "info" in cmd:
            return _make_completed(cmd, 0, stdout=info_blob)
        raise AssertionError(f"unexpected ots subcommand: {cmd}")

    def fake_lookup(height: int, cache_dir: Path, **kwargs: Any):
        lookup_args.append(height)
        return esplora.BlockLookupResult(
            height=height,
            block_hash="0" * 64,
            cached=False,
        )

    monkeypatch.setattr(ots_anchor, "_resolve_ots_binary", _fake_resolve_binary)
    monkeypatch.setattr(ots_anchor.subprocess, "run", fake_run)
    monkeypatch.setattr(esplora, "lookup_block_with_cache", fake_lookup)

    result = verify_real_manifest_file(
        hour_dir / "manifest.json", ots_full_verify=True
    )

    assert result.ok is True
    assert result.ots_anchor.full_verify_attempted is True
    assert result.ots_anchor.full_verify_ok is True
    assert result.ots_anchor.full_verify_skipped_reason == ""
    # Local-node verify + ots info both fired; Esplora resolved once.
    assert any("verify" in c for c in seen_cmds)
    assert any("info" in c for c in seen_cmds)
    assert lookup_args == [840000]


# ---------------------------------------------------------------------------
# 3. Truly-unfinalised hard reject (no heights at all)
# ---------------------------------------------------------------------------


def test_local_node_pending_no_heights_in_info_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No BitcoinBlockHeaderAttestation in ``ots info`` -> hard False."""
    hour_dir = _pick_tv3_hour()

    def fake_run(
        cmd: list[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        if "verify" in cmd:
            return _make_completed(cmd, 0, stdout="Pending\n")
        if "info" in cmd:
            # Calendar attestations only — no Bitcoin attestation at
            # all -> truly pending; fallback must return False.
            return _make_completed(
                cmd,
                0,
                stdout=(
                    "PendingAttestation('https://alice.btc.calendar.opentimestamps.org')\n"
                ),
            )
        raise AssertionError(f"unexpected ots subcommand: {cmd}")

    def lookup_must_not_be_called(*args: Any, **kwargs: Any):
        raise AssertionError(
            "lookup_block_with_cache must not be called when info "
            "yields zero heights"
        )

    monkeypatch.setattr(ots_anchor, "_resolve_ots_binary", _fake_resolve_binary)
    monkeypatch.setattr(ots_anchor.subprocess, "run", fake_run)
    monkeypatch.setattr(
        esplora, "lookup_block_with_cache", lookup_must_not_be_called
    )

    result = verify_real_manifest_file(
        hour_dir / "manifest.json", ots_full_verify=True
    )

    # Hard reject: verifier reached a definitive negative verdict.
    assert result.ok is False
    assert result.ots_anchor.full_verify_attempted is True
    assert result.ots_anchor.full_verify_ok is False
    assert result.ots_anchor.full_verify_skipped_reason == ""
    # Magic-header sub-checks must still report green so the operator
    # sees that the failure is at the Bitcoin-attestation level.
    assert result.ots_anchor.ots_magic_ok is True
    assert result.ots_anchor.root_bin_matches_manifest is True
    assert "full ots verify rejected" in result.failure_reason


# ---------------------------------------------------------------------------
# 4. Esplora unreachable -> hard reject
# ---------------------------------------------------------------------------


def test_local_node_pending_esplora_unreachable_hard_reject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Heights present but Esplora errors -> verify_receipt returns False."""
    hour_dir = _pick_tv3_hour()

    info_blob = (
        "Got 1 attestation(s) from "
        "BitcoinBlockHeaderAttestation(900000)\n"
    )

    def fake_run(
        cmd: list[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        if "verify" in cmd:
            return _make_completed(cmd, 0, stdout="pending\n")
        if "info" in cmd:
            return _make_completed(cmd, 0, stdout=info_blob)
        raise AssertionError(f"unexpected ots subcommand: {cmd}")

    def fake_lookup_raises(height: int, cache_dir: Path, **kwargs: Any):
        raise esplora.EsploraError(
            f"HTTP 503 from Esplora for height {height}"
        )

    monkeypatch.setattr(ots_anchor, "_resolve_ots_binary", _fake_resolve_binary)
    monkeypatch.setattr(ots_anchor.subprocess, "run", fake_run)
    monkeypatch.setattr(esplora, "lookup_block_with_cache", fake_lookup_raises)

    result = verify_real_manifest_file(
        hour_dir / "manifest.json", ots_full_verify=True
    )

    # Fallback exhausted -> hard False from verify_receipt. The
    # manifest-v2 wrapper translates that into a hard manifest reject.
    assert result.ok is False
    assert result.ots_anchor.full_verify_attempted is True
    assert result.ots_anchor.full_verify_ok is False
    # Crucially: this is a HARD reject, not a soft skip — even though
    # the Esplora HTTP call failed, the verifier reached a definitive
    # verdict (no confirmed block at any attested height).
    assert result.ots_anchor.full_verify_skipped_reason == ""
    assert "full ots verify rejected" in result.failure_reason


# ---------------------------------------------------------------------------
# 5. Subprocess timeout -> soft skip
# ---------------------------------------------------------------------------


def test_subprocess_timeout_is_soft_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ots verify`` timing out -> AnchorError -> soft skip; ok stays True."""
    hour_dir = _pick_tv3_hour()

    def fake_run(
        cmd: list[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        # ots_anchor.SUBPROCESS_TIMEOUT_S is 90s in production.
        raise subprocess.TimeoutExpired(
            cmd=cmd, timeout=ots_anchor.SUBPROCESS_TIMEOUT_S
        )

    monkeypatch.setattr(ots_anchor, "_resolve_ots_binary", _fake_resolve_binary)
    monkeypatch.setattr(ots_anchor.subprocess, "run", fake_run)

    result = verify_real_manifest_file(
        hour_dir / "manifest.json", ots_full_verify=True
    )

    # Magic-header pin still holds -> ok=True.
    assert result.ok is True
    assert result.ots_anchor.full_verify_attempted is True
    assert result.ots_anchor.full_verify_ok is False
    assert "soft-failure" in result.ots_anchor.full_verify_skipped_reason
    assert "timed out" in result.ots_anchor.full_verify_skipped_reason
