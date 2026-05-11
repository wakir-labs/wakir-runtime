# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""External-verifier-script ``--real-tv2 --verify-signature`` driver tests.

Sprint-6 Tag-2 substance: wire the Sprint-5 Tag-5 hand-signing pattern
(``tests/wat/test_tv2_real_manifest_sig_verify.py::_stage_signed_hour``)
into the driver script ``scripts/external_verifier_validation.py`` so
external implementers can verify wakir-WAT manifests with a single
CLI invocation that exercises both the JSON-Schema parity layer AND
the signature-verification layer against the real TV-2 cohort.

What this module checks
-----------------------

Pre-condition pin (anchors the unsigned path):

1. ``--real-tv2`` (no signature flag) still works exactly as before —
   the four hour-receipts pass through ``verify_real_manifest_file``
   end-to-end with empty ``signature_status`` (backward-compat).

Substance:

2. The ``stage_signed_cohort`` helper writes the four TV-2 hour-slots
   to a tmp dir as signed copies. The original repo fixture is NOT
   mutated.

3. ``--real-tv2 --verify-signature`` runs the verifier against the
   staged signed cohort with the ephemeral pubkey and every hour-
   receipt's ``signature_status`` lands as ``"verified"``.

4. ``--real-tv2 --verify-signature --verify-signature-strict`` against
   the freshly-signed cohort still accepts every hour (strict and
   permissive both pass on signed copies; the flag affects only the
   unsigned-input branch).

5. ``--real-tv3 --verify-signature`` works the same way against the
   single-hour TV-3 cohort — same code path, smaller fixture.

Negative-path / misuse:

6. ``--verify-signature`` without ``--real-tv2`` / ``--real-tv3``
   exits non-zero with a clear message (synthetic vector mode does
   not yet stage signed copies).

7. ``--verify-signature-strict`` without ``--verify-signature``
   exits non-zero (flag composition guard).

Module-level pins:

8. ``stage_signed_cohort`` returns the staged-root path matching the
   ``out_root`` passed in (caller controls cleanup via
   ``tempfile.TemporaryDirectory`` or pytest ``tmp_path``).

9. ``run_real_manifest_pipeline_for`` with ``verify_signature=False``
   leaves the ``tool`` label unchanged (no spurious ``sig:...`` suffix);
   with ``verify_signature=True`` the suffix appears.

Why this is the Sprint-6 Tag-2 substance
-----------------------------------------

Sprint-5 Tag-5 closed the Python-API gap: ``verify_real_manifest_file``
accepts ``verify_signature=True`` end-to-end. The on-disk driver — what
an external operator actually invokes — still had no signature-aware
mode. Tag-2 lifts the test-module's ``_stage_signed_hour`` pattern into
``scripts/external_verifier_validation.py:stage_signed_cohort`` and
adds ``--verify-signature`` to the ``--real-tvN`` driver. This unblocks
the Brand-Demo TV-2-card external-verifier substrate: a third-party can
now run ``python scripts/external_verifier_validation.py --real-tv2
--verify-signature`` and see the full chain (schema-file parity across
three validators + integrity-rebuild + OTS-anchor + signature) green
in one invocation.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "external_verifier_validation.py"


def _import_validation_script():
    """Load the script as a module without polluting sys.modules permanently."""
    spec = importlib.util.spec_from_file_location(
        "external_verifier_validation_script_sig", SCRIPT_PATH
    )
    if spec is None or spec.loader is None:
        pytest.fail(f"cannot load script from {SCRIPT_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ===========================================================================
# 1. Backward-compat: --real-tv2 unsigned path still green
# ===========================================================================


def test_real_tv2_unsigned_path_unchanged(capsys):
    """``--real-tv2`` alone (no --verify-signature) keeps its Tag-1 verdict."""
    mod = _import_validation_script()
    rc = mod.main(["--real-tv2", "--python-only", "--quiet"])
    captured = capsys.readouterr()
    assert rc == 0, (
        f"--real-tv2 alone returned rc={rc}; stdout=\n{captured.out}\n"
        f"stderr=\n{captured.err}"
    )
    assert (
        "verify_real_manifest_file pipeline OK" in captured.out
    ), f"expected unsigned-pipeline OK line; got:\n{captured.out}"
    assert "signed cohort" not in captured.out, (
        "signed-cohort line leaked into unsigned run; flag wire-up bug:\n"
        + captured.out
    )


# ===========================================================================
# 2. stage_signed_cohort lifts the test pattern into the driver
# ===========================================================================


def test_stage_signed_cohort_writes_signed_copies(tmp_path):
    """Staged manifests carry a ``signature`` slot; originals are untouched."""
    import json

    from wat.identity.manifest_signing import SIGNATURE_FIELD

    mod = _import_validation_script()
    staged_root, priv_seed, pub_key = mod.stage_signed_cohort(
        mod.TV2_FIXTURE_ROOT,
        mod.TV2_HOUR_SLOTS,
        out_root=tmp_path,
    )
    assert staged_root == tmp_path
    assert len(priv_seed) == 32, "private seed must be raw 32-byte Ed25519"
    assert len(pub_key) == 32, "public key must be raw 32-byte Ed25519"

    for slot in mod.TV2_HOUR_SLOTS:
        signed_mp = staged_root / slot / "manifest.json"
        assert signed_mp.exists(), f"staged manifest missing for {slot}"
        signed = json.loads(signed_mp.read_text(encoding="utf-8"))
        assert SIGNATURE_FIELD in signed, (
            f"staged manifest for {slot} missing signature slot"
        )
        # Side-files copied byte-for-byte for the OTS-anchor check.
        assert (staged_root / slot / "root.bin").exists()
        assert (staged_root / slot / "root.bin.ots").exists()

        # Original fixture is NOT mutated -- the signed slot does not
        # appear in the on-disk repo manifest.
        original_mp = mod.TV2_FIXTURE_ROOT / slot / "manifest.json"
        original = json.loads(original_mp.read_text(encoding="utf-8"))
        assert SIGNATURE_FIELD not in original, (
            f"original fixture for {slot} was mutated -- driver bug"
        )


# ===========================================================================
# 3. --real-tv2 --verify-signature green end-to-end
# ===========================================================================


def test_real_tv2_verify_signature_all_green(capsys):
    """Every TV-2 hour-receipt verifies with signature_status='verified'."""
    mod = _import_validation_script()
    rc = mod.main(
        ["--real-tv2", "--verify-signature", "--python-only", "--quiet"]
    )
    captured = capsys.readouterr()
    assert rc == 0, (
        f"--real-tv2 --verify-signature returned rc={rc}; "
        f"stdout=\n{captured.out}\nstderr=\n{captured.err}"
    )
    assert (
        "verify_real_manifest_file (signed cohort) OK" in captured.out
    ), f"expected signed-cohort OK line; got:\n{captured.out}"
    assert "signature_status=['verified']" in captured.out, (
        "expected all-verified signature_status summary in stdout:\n"
        + captured.out
    )


# ===========================================================================
# 4. Strict mode still passes on freshly-signed cohort
# ===========================================================================


def test_real_tv2_verify_signature_strict_accepts_signed_cohort(capsys):
    """Strict mode on a freshly-signed cohort accepts every hour."""
    mod = _import_validation_script()
    rc = mod.main(
        [
            "--real-tv2",
            "--verify-signature",
            "--verify-signature-strict",
            "--python-only",
            "--quiet",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0, (
        f"strict mode returned rc={rc}; "
        f"stdout=\n{captured.out}\nstderr=\n{captured.err}"
    )
    assert "signature_status=['verified']" in captured.out


# ===========================================================================
# 5. --real-tv3 --verify-signature same code path
# ===========================================================================


def test_real_tv3_verify_signature_all_green(capsys):
    """TV-3 single-hour cohort exercises the same driver path."""
    mod = _import_validation_script()
    rc = mod.main(
        ["--real-tv3", "--verify-signature", "--python-only", "--quiet"]
    )
    captured = capsys.readouterr()
    assert rc == 0, (
        f"--real-tv3 --verify-signature returned rc={rc}; "
        f"stdout=\n{captured.out}\nstderr=\n{captured.err}"
    )
    assert (
        "verify_real_manifest_file (signed cohort) OK" in captured.out
    )
    assert "signature_status=['verified']" in captured.out


# ===========================================================================
# 6. Misuse: --verify-signature alone (no --real-tvN)
# ===========================================================================


def test_verify_signature_without_real_tvn_rejects(capsys):
    """``--verify-signature`` requires a real-cohort selector."""
    mod = _import_validation_script()
    rc = mod.main(["--verify-signature"])
    captured = capsys.readouterr()
    assert rc == 2, f"expected rc=2 misuse exit; got rc={rc}"
    assert (
        "--verify-signature requires --real-tv2 or --real-tv3"
        in captured.err
    ), f"expected misuse stderr; got:\n{captured.err}"


# ===========================================================================
# 7. Misuse: --verify-signature-strict without --verify-signature
# ===========================================================================


def test_verify_signature_strict_without_signature_rejects(capsys):
    """``--verify-signature-strict`` requires ``--verify-signature``."""
    mod = _import_validation_script()
    rc = mod.main(["--real-tv2", "--verify-signature-strict"])
    captured = capsys.readouterr()
    assert rc == 2
    assert (
        "--verify-signature-strict requires --verify-signature"
        in captured.err
    )


# ===========================================================================
# 8. (covered by test 2 -- staged_root == tmp_path assertion)
# ===========================================================================


# ===========================================================================
# 9. Tool-label honesty: sig-suffix appears only when signature gate ran
# ===========================================================================


def test_pipeline_tool_label_reflects_signature_mode(tmp_path):
    """The report ``tool`` field flags whether the signature gate ran."""
    mod = _import_validation_script()
    # Unsigned path: tool label has no sig suffix.
    unsigned_report = mod.run_real_manifest_pipeline_for(
        mod.TV2_FIXTURE_ROOT,
        mod.TV2_HOUR_SLOTS,
        "tv2",
        check_ots_anchor=True,
        use_schema_file=True,
    )
    assert unsigned_report["tool"] == (
        "wat.verify.manifest_v2.verify_real_manifest_file"
    )

    # Signed path: tool label flags the mode.
    staged_root, _priv, pub = mod.stage_signed_cohort(
        mod.TV2_FIXTURE_ROOT, mod.TV2_HOUR_SLOTS, out_root=tmp_path
    )
    signed_report = mod.run_real_manifest_pipeline_for(
        staged_root,
        mod.TV2_HOUR_SLOTS,
        "tv2",
        check_ots_anchor=True,
        use_schema_file=True,
        verify_signature=True,
        verify_signature_public_key=pub,
        verify_signature_strict=False,
    )
    assert "(sig:permissive)" in signed_report["tool"]

    strict_report = mod.run_real_manifest_pipeline_for(
        staged_root,
        mod.TV2_HOUR_SLOTS,
        "tv2",
        check_ots_anchor=True,
        use_schema_file=True,
        verify_signature=True,
        verify_signature_public_key=pub,
        verify_signature_strict=True,
    )
    assert "(sig:strict)" in strict_report["tool"]


# ===========================================================================
# 10. Per-result schema: signature_status field always present
# ===========================================================================


def test_pipeline_result_dict_carries_signature_status_field(tmp_path):
    """Every per-hour result dict carries the ``signature_status`` key.

    Even on the unsigned path the key is present (empty string), so
    downstream consumers can parse the report shape without branching
    on whether the signature gate ran.
    """
    mod = _import_validation_script()
    unsigned_report = mod.run_real_manifest_pipeline_for(
        mod.TV2_FIXTURE_ROOT,
        mod.TV2_HOUR_SLOTS,
        "tv2",
    )
    for r in unsigned_report["results"]:
        assert "signature_status" in r
        assert r["signature_status"] == ""  # unsigned path leaves it empty

    staged_root, _priv, pub = mod.stage_signed_cohort(
        mod.TV2_FIXTURE_ROOT, mod.TV2_HOUR_SLOTS, out_root=tmp_path
    )
    signed_report = mod.run_real_manifest_pipeline_for(
        staged_root,
        mod.TV2_HOUR_SLOTS,
        "tv2",
        verify_signature=True,
        verify_signature_public_key=pub,
    )
    for r in signed_report["results"]:
        assert r["signature_status"] == "verified"
