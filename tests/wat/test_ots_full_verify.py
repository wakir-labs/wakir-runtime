# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for the off-default ``ots verify``-Voll-Integration.

Sprint-3 Tag-4 lands the ``--ots-full-verify`` flag, the
``WAKIR_OTS_FULL_VERIFY=1`` env var, and the ``ots_full_verify``
keyword on :func:`wat.verify.manifest_v2.verify_real_manifest_file`.
The default magic-header pin is unchanged; the new path additionally
shells out to ``wat.anchor.ots_anchor.verify_receipt`` which depends
on a Bitcoin source (local node OR Esplora HTTP fallback).

Test inventory
--------------

Hermetic (six tests, the default suite):

1. Default path stays magic-header-only — full_verify_attempted False.
2. ``ots_full_verify=True`` + verify_receipt -> True -> ok=True.
3. ``ots_full_verify=True`` + verify_receipt -> False -> ok=False
   with ``full_verify_ok=False`` and a populated ``failure_reason``.
4. ``ots_full_verify=True`` + verify_receipt raises AnchorError ->
   skipped_reason populated, ok=True (soft outcome at magic-header).
5. ``WAKIR_OTS_FULL_VERIFY=1`` env flips full-verify on without
   passing the kwarg.
6. CLI ``--ots-full-verify`` flag flows through main() into the
   pipeline and the JSON output carries the three new fields.

Live-gated (three tests, opt-in via ``OTS_INTEGRATION_TEST=1``):

7. Real TV-2 hour-receipt + ``ots_full_verify=True`` -> ok=True OR
   skipped_reason populated (network dependent — both outcomes are
   valid Tag-4 contracts; this test asserts the contract not the
   verdict).
8. Real TV-3 hour-receipt + same — single-hour-genesis cohort.
9. CLI smoke against a real fixture with ``--ots-full-verify`` —
   exit code 0 OR 1 (depending on Esplora availability) but the
   JSON output must always carry the three full-verify keys.
"""

# ruff: noqa: S101  — pytest's assert idiom is the whole point.

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from wat.anchor import ots_anchor
from wat.verify import manifest_v2
from wat.verify.manifest_v2 import (
    OtsAnchorCheck,
    verify_real_manifest_file,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TV2_FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "wat-tv2-real"
TV3_FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "wat-tv3-real"


# ---------------------------------------------------------------------------
# Hermetic tests
# ---------------------------------------------------------------------------


def _pick_tv2_hour() -> Path:
    """Return one TV-2 hour-receipt directory; the cohort has four."""
    candidates = sorted(p for p in TV2_FIXTURE_ROOT.iterdir() if p.is_dir())
    if not candidates:
        pytest.skip("TV-2 fixture cohort missing — run earlier sprint tests first.")
    return candidates[0]


def test_default_magic_header_only_unchanged() -> None:
    """Without the new flag the contract is identical to Sprint-2 Tag-5."""
    hour_dir = _pick_tv2_hour()
    result = verify_real_manifest_file(hour_dir / "manifest.json")
    assert result.ok is True
    assert result.ots_anchor.checked is True
    assert result.ots_anchor.ots_magic_ok is True
    # Crucial: the new fields stay False / empty by default.
    assert result.ots_anchor.full_verify_attempted is False
    assert result.ots_anchor.full_verify_ok is False
    assert result.ots_anchor.full_verify_skipped_reason == ""


def test_full_verify_kwarg_green(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ots_full_verify=True`` + verifier-True -> full_verify_ok=True."""
    hour_dir = _pick_tv2_hour()

    def fake_verify_receipt(
        receipt_path,  # type: ignore[no-untyped-def]
        merkle_root,  # type: ignore[no-untyped-def]
        *,
        esplora_fallback=True,  # type: ignore[no-untyped-def]
    ) -> bool:
        # Sanity: the helper passes the receipt path next to the manifest
        # and the raw 32-byte root. Both must look right or we have a
        # plumbing bug.
        assert Path(receipt_path).name == "root.bin.ots"
        assert isinstance(merkle_root, (bytes, bytearray))
        assert len(merkle_root) == 32
        assert esplora_fallback is True
        return True

    monkeypatch.setattr(ots_anchor, "verify_receipt", fake_verify_receipt)

    result = verify_real_manifest_file(
        hour_dir / "manifest.json", ots_full_verify=True
    )
    assert result.ok is True
    assert result.ots_anchor.full_verify_attempted is True
    assert result.ots_anchor.full_verify_ok is True
    assert result.ots_anchor.full_verify_skipped_reason == ""
    assert result.failure_reason == ""


def test_full_verify_kwarg_hard_reject(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifier returns False -> ok=False, full_verify_ok=False."""
    hour_dir = _pick_tv2_hour()

    monkeypatch.setattr(
        ots_anchor,
        "verify_receipt",
        lambda *a, **kw: False,  # noqa: ARG005 — signature-shaped stub.
    )

    result = verify_real_manifest_file(
        hour_dir / "manifest.json", ots_full_verify=True
    )
    assert result.ok is False
    assert result.ots_anchor.full_verify_attempted is True
    assert result.ots_anchor.full_verify_ok is False
    assert result.ots_anchor.full_verify_skipped_reason == ""
    # Magic-header sub-checks must still report green so the operator
    # sees that the failure is at the Bitcoin-attestation level, not
    # the side-file level.
    assert result.ots_anchor.ots_magic_ok is True
    assert result.ots_anchor.root_bin_matches_manifest is True
    assert "full ots verify rejected" in result.failure_reason


def test_full_verify_anchor_error_is_soft_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifier raises AnchorError -> skipped_reason; magic-header still ok."""
    hour_dir = _pick_tv2_hour()

    def boom(*a, **kw):  # noqa: ARG001 — signature-shaped stub.
        raise ots_anchor.AnchorError("ots CLI not found on PATH")

    monkeypatch.setattr(ots_anchor, "verify_receipt", boom)

    result = verify_real_manifest_file(
        hour_dir / "manifest.json", ots_full_verify=True
    )
    # ok stays True because the magic-header pin still holds and
    # the soft-skipped path does NOT gate the manifest pipeline.
    assert result.ok is True
    assert result.ots_anchor.full_verify_attempted is True
    assert result.ots_anchor.full_verify_ok is False
    assert (
        "ots verifier soft-failure"
        in result.ots_anchor.full_verify_skipped_reason
    )
    assert "ots CLI not found" in result.ots_anchor.full_verify_skipped_reason


def test_env_var_flips_full_verify_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """``WAKIR_OTS_FULL_VERIFY=1`` triggers full-verify without the kwarg."""
    hour_dir = _pick_tv2_hour()

    monkeypatch.setenv("WAKIR_OTS_FULL_VERIFY", "1")
    seen: dict[str, object] = {}

    def fake_verify_receipt(receipt_path, merkle_root, **kwargs):  # type: ignore[no-untyped-def]
        seen["receipt_path"] = receipt_path
        seen["merkle_root_len"] = len(merkle_root)
        return True

    monkeypatch.setattr(ots_anchor, "verify_receipt", fake_verify_receipt)

    # Note: ots_full_verify is NOT passed; env must do the lifting.
    result = verify_real_manifest_file(hour_dir / "manifest.json")
    assert result.ok is True
    assert result.ots_anchor.full_verify_attempted is True
    assert result.ots_anchor.full_verify_ok is True
    assert seen["merkle_root_len"] == 32
    assert Path(seen["receipt_path"]).name == "root.bin.ots"


def test_cli_flag_flows_through_main_with_json_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI ``--ots-full-verify`` produces the three new keys in JSON."""
    hour_dir = _pick_tv2_hour()
    monkeypatch.setattr(
        ots_anchor,
        "verify_receipt",
        lambda *a, **kw: True,  # noqa: ARG005 — signature-shaped stub.
    )

    rc = manifest_v2.main(
        [
            str(hour_dir / "manifest.json"),
            "--real-manifest",
            "--ots-full-verify",
            "--output",
            "json",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["ots_full_verify_attempted"] is True
    assert payload["ots_full_verify_ok"] is True
    assert payload["ots_full_verify_skipped_reason"] == ""
    # Older keys must continue to flow through.
    assert payload["ots_anchor_checked"] is True
    assert payload["ots_anchor_ok"] is True
    assert payload["schema_version"] == "wakir-verify-manifest-v2/0"


# ---------------------------------------------------------------------------
# Live-gated tests (OTS_INTEGRATION_TEST=1)
# ---------------------------------------------------------------------------


def _integration_enabled() -> bool:
    raw = os.environ.get("OTS_INTEGRATION_TEST", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


live_only = pytest.mark.skipif(
    not _integration_enabled(),
    reason=(
        "OTS_INTEGRATION_TEST is not set; skipping live full-verify tests. "
        "Export OTS_INTEGRATION_TEST=1 to run them. Politeness: each test "
        "may issue at most one network round-trip to the configured "
        "Esplora endpoint."
    ),
)


@live_only
def test_live_tv2_hour_full_verify_contract() -> None:
    """Live: TV-2 fixture full-verify must yield a definitive contract.

    ``ok=True`` (verifier confirmed), ``ok=False`` with
    ``full_verify_ok=False`` and no ``skipped_reason`` (verifier hard-
    rejected), or ``ok=True`` with ``skipped_reason`` (network glitch
    on the Esplora endpoint). All three are valid Tag-4 outcomes; we
    only assert the response shape, not the verdict.
    """
    if shutil.which("ots") is None:
        pytest.skip("ots CLI not on PATH; live full-verify cannot run.")

    hour_dir = _pick_tv2_hour()
    result = verify_real_manifest_file(
        hour_dir / "manifest.json", ots_full_verify=True
    )
    assert result.ots_anchor.full_verify_attempted is True
    if result.ots_anchor.full_verify_skipped_reason:
        assert result.ok is True  # soft outcome at magic-header
    else:
        # Definitive verdict: ok mirrors full_verify_ok.
        assert result.ok is result.ots_anchor.full_verify_ok


@live_only
def test_live_tv3_hour_full_verify_contract() -> None:
    """Live: TV-3 (single-hour run-genesis) yields the same contract shape."""
    if shutil.which("ots") is None:
        pytest.skip("ots CLI not on PATH; live full-verify cannot run.")

    candidates = sorted(p for p in TV3_FIXTURE_ROOT.iterdir() if p.is_dir())
    if not candidates:
        pytest.skip("TV-3 fixture cohort missing.")
    hour_dir = candidates[0]

    result = verify_real_manifest_file(
        hour_dir / "manifest.json", ots_full_verify=True
    )
    assert result.ots_anchor.full_verify_attempted is True
    # Same three-way contract as TV-2.
    if not result.ots_anchor.full_verify_skipped_reason:
        assert result.ok is result.ots_anchor.full_verify_ok


@live_only
def test_live_cli_smoke_full_verify_json_keys() -> None:
    """Live: CLI smoke must always emit the three new JSON keys."""
    if shutil.which("ots") is None:
        pytest.skip("ots CLI not on PATH; live full-verify cannot run.")

    hour_dir = _pick_tv2_hour()
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "wat.verify.manifest_v2",
            str(hour_dir / "manifest.json"),
            "--real-manifest",
            "--ots-full-verify",
            "--output",
            "json",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    # Exit code: 0 on green, 1 on hard-reject; both are valid here.
    assert proc.returncode in (0, 1)
    payload = json.loads(proc.stdout)
    for key in (
        "ots_full_verify_attempted",
        "ots_full_verify_ok",
        "ots_full_verify_skipped_reason",
    ):
        assert key in payload, f"missing {key} in CLI JSON output"
    assert payload["ots_full_verify_attempted"] is True
