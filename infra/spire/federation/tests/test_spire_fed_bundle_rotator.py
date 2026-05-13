# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic acceptance tests for the Phase-2 Sprint-8 Tag-3
``spire-fed-bundle-rotator`` CLI.

Rotation lifecycle covered:

  * Soft-Cutover: rotate produces a two-key JWKS; both keys verify
    accepted during the grace-window.
  * Hard-Revoke: expire after grace-window removes the old key;
    old kid no longer verifies.
  * Grace-Window: old key with ``_wakir_not_after`` in the past
    rejected with an explicit reason; new key valid.
  * Cross-Trust-Domain-Boundary: rotate ``wakir.test`` does NOT
    affect ``partner.test`` (and refuses to operate on a mismatched
    bundle).
  * Determinism: same inputs (trust-domain, now, grace-seconds,
    base JWKS) yield bit-identical JWKS.
  * Empty-bundle guard: expire refuses to leave zero valid keys.
  * Verify-kid: future ``_wakir_issued_at`` rejected (not-yet-issued
    case).
  * Future-now-rejected: list/verify with a future ``--now`` behave
    deterministically (no wall-clock leak).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
FED_DIR = HERE.parent
ROTATOR_PATH = FED_DIR / "bin" / "spire_fed_bundle_rotator.py"
FED_BUNDLE_PATH = FED_DIR / "bin" / "spire_fed_bundle.py"


@pytest.fixture(scope="module")
def rotator():
    spec = importlib.util.spec_from_file_location(
        "spire_fed_bundle_rotator", ROTATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["spire_fed_bundle_rotator"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def fed_bundle():
    spec = importlib.util.spec_from_file_location(
        "spire_fed_bundle", FED_BUNDLE_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["spire_fed_bundle"] = mod
    spec.loader.exec_module(mod)
    return mod


# Canonical hermetic test timestamps.
T0 = "2026-05-13T00:00:00+00:00"
T0_PLUS_1H = "2026-05-13T01:00:00+00:00"  # mid-grace (with 24h window)
T0_PLUS_25H = "2026-05-14T01:00:00+00:00"  # past grace (with 24h window)
GRACE_24H = 86400


def _export_base(fed_bundle, td: str, dst: Path) -> Path:
    """Use the Tag-1 spire-fed-bundle to seed the rotation input."""
    fed_bundle.main(["export", "--trust-domain", td, "--out", str(dst)])
    return dst


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------
# 1. Rotate produces a two-key JWKS (Soft-Cutover entry)
# ---------------------------------------------------------------------


def test_rotate_appends_new_key_keeps_old(
    rotator, fed_bundle, tmp_path: Path
) -> None:
    src = _export_base(fed_bundle, "wakir.test", tmp_path / "wakir-v1.jwks")
    dst = tmp_path / "wakir-v2.jwks"
    rc = rotator.main(
        [
            "rotate",
            "--trust-domain", "wakir.test",
            "--in-file", str(src),
            "--out", str(dst),
            "--now", T0,
            "--grace-seconds", str(GRACE_24H),
        ]
    )
    assert rc == 0
    doc = _load(dst)
    assert len(doc["keys"]) == 2, "rotate must produce a two-key JWKS"
    kids = {k["kid"] for k in doc["keys"]}
    assert any("rot1" in k for k in kids), "new key must carry rot1 suffix"
    # Old key now has _wakir_not_after = T0 + 24h.
    old_keys = [k for k in doc["keys"] if "_wakir_not_after" in k]
    new_keys = [k for k in doc["keys"] if "_wakir_not_after" not in k]
    assert len(old_keys) == 1 and len(new_keys) == 1


# ---------------------------------------------------------------------
# 2. Soft-Cutover: both keys verify accepted during grace
# ---------------------------------------------------------------------


def test_soft_cutover_both_keys_accepted_during_grace(
    rotator, fed_bundle, tmp_path: Path
) -> None:
    src = _export_base(fed_bundle, "wakir.test", tmp_path / "wakir-v1.jwks")
    dst = tmp_path / "wakir-v2.jwks"
    rotator.main(
        [
            "rotate",
            "--trust-domain", "wakir.test",
            "--in-file", str(src),
            "--out", str(dst),
            "--now", T0,
            "--grace-seconds", str(GRACE_24H),
        ]
    )
    doc = _load(dst)
    kids = [k["kid"] for k in doc["keys"]]
    # Both kids must verify accepted at T0+1h (mid-grace).
    for kid in kids:
        rc = rotator.main(
            [
                "verify",
                "--in-file", str(dst),
                "--kid", kid,
                "--now", T0_PLUS_1H,
            ]
        )
        assert rc == 0, (
            f"kid {kid!r} must verify accepted at T0+1h (mid-grace)"
        )


# ---------------------------------------------------------------------
# 3. Hard-Revoke: expire after grace-window removes the old key
# ---------------------------------------------------------------------


def test_hard_revoke_drops_expired_key(
    rotator, fed_bundle, tmp_path: Path
) -> None:
    src = _export_base(fed_bundle, "wakir.test", tmp_path / "wakir-v1.jwks")
    rotated = tmp_path / "wakir-v2.jwks"
    expired = tmp_path / "wakir-v3.jwks"

    rotator.main(
        [
            "rotate",
            "--trust-domain", "wakir.test",
            "--in-file", str(src),
            "--out", str(rotated),
            "--now", T0,
            "--grace-seconds", str(GRACE_24H),
        ]
    )

    # At T0+25h, the old key's _wakir_not_after (T0+24h) is in the past
    # → expire drops it.
    rc = rotator.main(
        [
            "expire",
            "--trust-domain", "wakir.test",
            "--in-file", str(rotated),
            "--out", str(expired),
            "--now", T0_PLUS_25H,
        ]
    )
    assert rc == 0
    doc = _load(expired)
    assert len(doc["keys"]) == 1, "expire must drop the old key"
    surviving = doc["keys"][0]
    # The surviving key is the rot1 generation (no _wakir_not_after,
    # _wakir_rotation_counter == 1).
    assert surviving.get("_wakir_rotation_counter") == 1
    assert "_wakir_not_after" not in surviving


# ---------------------------------------------------------------------
# 4. Grace-Window: old key with _wakir_not_after in past rejected
# ---------------------------------------------------------------------


def test_verify_rejects_expired_key_with_explicit_reason(
    rotator, fed_bundle, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    src = _export_base(fed_bundle, "wakir.test", tmp_path / "wakir-v1.jwks")
    rotated = tmp_path / "wakir-v2.jwks"
    rotator.main(
        [
            "rotate",
            "--trust-domain", "wakir.test",
            "--in-file", str(src),
            "--out", str(rotated),
            "--now", T0,
            "--grace-seconds", str(GRACE_24H),
        ]
    )
    doc = _load(rotated)
    old_kid = next(
        k["kid"] for k in doc["keys"] if "_wakir_not_after" in k
    )
    # At T0+25h, the old key is past its _wakir_not_after.
    rc = rotator.main(
        [
            "verify",
            "--in-file", str(rotated),
            "--kid", old_kid,
            "--now", T0_PLUS_25H,
        ]
    )
    assert rc == 2, "expired kid must reject with exit-code 2"
    err = capsys.readouterr().err
    assert "expired" in err, (
        "rejection reason must mention 'expired' for the operator log"
    )
    assert "_wakir_not_after" in err, (
        "rejection reason must cite the not_after marker"
    )


# ---------------------------------------------------------------------
# 5. Cross-Trust-Domain-Boundary: rotate refuses mismatched TD
# ---------------------------------------------------------------------


def test_rotate_refuses_cross_trust_domain(
    rotator, fed_bundle, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    src = _export_base(fed_bundle, "wakir.test", tmp_path / "wakir-v1.jwks")
    dst = tmp_path / "wakir-as-partner.jwks"
    rc = rotator.main(
        [
            "rotate",
            "--trust-domain", "partner.test",  # WRONG
            "--in-file", str(src),
            "--out", str(dst),
            "--now", T0,
            "--grace-seconds", str(GRACE_24H),
        ]
    )
    assert rc == 2, (
        "rotate with wrong --trust-domain must reject with exit-code 2"
    )
    err = capsys.readouterr().err
    assert "trust-domain mismatch" in err


def test_rotate_wakir_does_not_touch_partner_bundle(
    rotator, fed_bundle, tmp_path: Path
) -> None:
    wakir_src = _export_base(fed_bundle, "wakir.test", tmp_path / "w-v1.jwks")
    partner_src = _export_base(
        fed_bundle, "partner.test", tmp_path / "p-v1.jwks"
    )
    wakir_dst = tmp_path / "w-v2.jwks"
    rotator.main(
        [
            "rotate",
            "--trust-domain", "wakir.test",
            "--in-file", str(wakir_src),
            "--out", str(wakir_dst),
            "--now", T0,
            "--grace-seconds", str(GRACE_24H),
        ]
    )
    # partner_src must be unmodified (rotator never opened it).
    assert partner_src.read_bytes() == _export_base(
        fed_bundle, "partner.test", tmp_path / "p-v1-check.jwks"
    ).read_bytes(), "partner.test bundle must be unchanged by wakir rotation"


# ---------------------------------------------------------------------
# 6. Determinism
# ---------------------------------------------------------------------


def test_rotate_is_deterministic_for_same_inputs(
    rotator, fed_bundle, tmp_path: Path
) -> None:
    src = _export_base(fed_bundle, "wakir.test", tmp_path / "wakir-v1.jwks")
    dst_a = tmp_path / "rot-a.jwks"
    dst_b = tmp_path / "rot-b.jwks"
    for dst in (dst_a, dst_b):
        rotator.main(
            [
                "rotate",
                "--trust-domain", "wakir.test",
                "--in-file", str(src),
                "--out", str(dst),
                "--now", T0,
                "--grace-seconds", str(GRACE_24H),
            ]
        )
    assert dst_a.read_bytes() == dst_b.read_bytes(), (
        "two rotations with identical inputs must produce bit-identical JWKS"
    )


# ---------------------------------------------------------------------
# 7. Two consecutive rotations: counter increments, grace re-armed
# ---------------------------------------------------------------------


def test_two_consecutive_rotations_increment_counter(
    rotator, fed_bundle, tmp_path: Path
) -> None:
    src = _export_base(fed_bundle, "wakir.test", tmp_path / "v1.jwks")
    v2 = tmp_path / "v2.jwks"
    v3 = tmp_path / "v3.jwks"
    rotator.main(
        [
            "rotate",
            "--trust-domain", "wakir.test",
            "--in-file", str(src),
            "--out", str(v2),
            "--now", T0,
            "--grace-seconds", str(GRACE_24H),
        ]
    )
    rotator.main(
        [
            "rotate",
            "--trust-domain", "wakir.test",
            "--in-file", str(v2),
            "--out", str(v3),
            "--now", T0_PLUS_1H,
            "--grace-seconds", str(GRACE_24H),
        ]
    )
    doc_v3 = _load(v3)
    counters = sorted(
        k.get("_wakir_rotation_counter")
        for k in doc_v3["keys"]
        if "_wakir_rotation_counter" in k
    )
    # v3 must contain {0=base via _max_rotation_counter, 1=first rot,
    # 2=second rot}. The base export from Tag-1 has no
    # _wakir_rotation_counter, so _max_rotation_counter returned 0
    # and the first rotation assigned 1; second rotation assigned 2.
    assert counters == [1, 2], (
        f"after two rotations, counters must be [1, 2]; got {counters}"
    )


# ---------------------------------------------------------------------
# 8. Empty-bundle guard
# ---------------------------------------------------------------------


def test_expire_refuses_to_leave_empty_bundle(
    rotator, fed_bundle, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    # Build a single-key bundle where the only key is already expired.
    src = _export_base(fed_bundle, "wakir.test", tmp_path / "v1.jwks")
    # Inject _wakir_not_after = T0 into the only key, then call expire
    # at T0+1h.
    doc = _load(src)
    doc["keys"][0]["_wakir_not_after"] = T0
    src.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    out = tmp_path / "v2.jwks"
    rc = rotator.main(
        [
            "expire",
            "--trust-domain", "wakir.test",
            "--in-file", str(src),
            "--out", str(out),
            "--now", T0_PLUS_1H,
        ]
    )
    assert rc == 2, "expire that would empty the bundle must reject"
    err = capsys.readouterr().err
    assert "zero valid keys" in err
    assert "rotate first" in err


# ---------------------------------------------------------------------
# 9. Verify-kid: future _wakir_issued_at rejected (not-yet-issued)
# ---------------------------------------------------------------------


def test_verify_rejects_future_issued_at(
    rotator, fed_bundle, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    src = _export_base(fed_bundle, "wakir.test", tmp_path / "v1.jwks")
    rotated = tmp_path / "v2.jwks"
    rotator.main(
        [
            "rotate",
            "--trust-domain", "wakir.test",
            "--in-file", str(src),
            "--out", str(rotated),
            "--now", T0_PLUS_25H,  # rotation moment FAR in the future
            "--grace-seconds", str(GRACE_24H),
        ]
    )
    doc = _load(rotated)
    new_kid = next(
        k["kid"] for k in doc["keys"]
        if k.get("_wakir_rotation_counter") == 1
    )
    rc = rotator.main(
        [
            "verify",
            "--in-file", str(rotated),
            "--kid", new_kid,
            "--now", T0,  # verify BEFORE the issued_at
        ]
    )
    assert rc == 2, "kid issued in future of now must reject"
    err = capsys.readouterr().err
    assert "issued_at" in err and "future" in err


# ---------------------------------------------------------------------
# 10. List command: status field reflects time-of-evaluation
# ---------------------------------------------------------------------


def test_list_emits_per_key_status(
    rotator, fed_bundle, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    src = _export_base(fed_bundle, "wakir.test", tmp_path / "v1.jwks")
    rotated = tmp_path / "v2.jwks"
    rotator.main(
        [
            "rotate",
            "--trust-domain", "wakir.test",
            "--in-file", str(src),
            "--out", str(rotated),
            "--now", T0,
            "--grace-seconds", str(GRACE_24H),
        ]
    )
    # Mid-grace: one key 'grace', one 'valid'.
    rotator.main(
        [
            "list",
            "--in-file", str(rotated),
            "--now", T0_PLUS_1H,
            "--json",
        ]
    )
    rows_mid = json.loads(capsys.readouterr().out)
    statuses_mid = sorted(r["status"] for r in rows_mid)
    assert statuses_mid == ["grace", "valid"], (
        f"mid-grace statuses must be ['grace', 'valid']; got {statuses_mid}"
    )
    # Post-grace: one key 'expired', one 'valid'.
    rotator.main(
        [
            "list",
            "--in-file", str(rotated),
            "--now", T0_PLUS_25H,
            "--json",
        ]
    )
    rows_post = json.loads(capsys.readouterr().out)
    statuses_post = sorted(r["status"] for r in rows_post)
    assert statuses_post == ["expired", "valid"]


# ---------------------------------------------------------------------
# 11. Invalid timestamps rejected
# ---------------------------------------------------------------------


def test_naive_timestamp_rejected(rotator, fed_bundle, tmp_path: Path) -> None:
    src = _export_base(fed_bundle, "wakir.test", tmp_path / "v1.jwks")
    dst = tmp_path / "v2.jwks"
    rc = rotator.main(
        [
            "rotate",
            "--trust-domain", "wakir.test",
            "--in-file", str(src),
            "--out", str(dst),
            # Naive (no TZ suffix) — must reject.
            "--now", "2026-05-13T00:00:00",
            "--grace-seconds", str(GRACE_24H),
        ]
    )
    assert rc == 2


def test_non_utc_timestamp_rejected(rotator, fed_bundle, tmp_path: Path) -> None:
    src = _export_base(fed_bundle, "wakir.test", tmp_path / "v1.jwks")
    dst = tmp_path / "v2.jwks"
    rc = rotator.main(
        [
            "rotate",
            "--trust-domain", "wakir.test",
            "--in-file", str(src),
            "--out", str(dst),
            # +01:00 (non-UTC) — must reject.
            "--now", "2026-05-13T00:00:00+01:00",
            "--grace-seconds", str(GRACE_24H),
        ]
    )
    assert rc == 2


# ---------------------------------------------------------------------
# 12. Negative grace-seconds rejected
# ---------------------------------------------------------------------


def test_negative_grace_seconds_rejected(
    rotator, fed_bundle, tmp_path: Path
) -> None:
    src = _export_base(fed_bundle, "wakir.test", tmp_path / "v1.jwks")
    dst = tmp_path / "v2.jwks"
    rc = rotator.main(
        [
            "rotate",
            "--trust-domain", "wakir.test",
            "--in-file", str(src),
            "--out", str(dst),
            "--now", T0,
            "--grace-seconds", "-1",
        ]
    )
    assert rc == 2


# ---------------------------------------------------------------------
# 13. Z-suffix timestamps accepted (canonical SPIRE form)
# ---------------------------------------------------------------------


def test_z_suffix_timestamp_accepted(
    rotator, fed_bundle, tmp_path: Path
) -> None:
    src = _export_base(fed_bundle, "wakir.test", tmp_path / "v1.jwks")
    dst = tmp_path / "v2.jwks"
    rc = rotator.main(
        [
            "rotate",
            "--trust-domain", "wakir.test",
            "--in-file", str(src),
            "--out", str(dst),
            "--now", "2026-05-13T00:00:00Z",
            "--grace-seconds", str(GRACE_24H),
        ]
    )
    assert rc == 0
    doc = _load(dst)
    # The stored _wakir_not_after MUST be in canonical +00:00 form
    # (Z-suffix normalized on parse).
    old = next(k for k in doc["keys"] if "_wakir_not_after" in k)
    assert old["_wakir_not_after"].endswith("+00:00")


# ---------------------------------------------------------------------
# 14. Verify on absent kid rejects
# ---------------------------------------------------------------------


def test_verify_rejects_absent_kid(
    rotator, fed_bundle, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    src = _export_base(fed_bundle, "wakir.test", tmp_path / "v1.jwks")
    rc = rotator.main(
        [
            "verify",
            "--in-file", str(src),
            "--kid", "spiffe://wakir.test/spire/server/not-in-bundle",
            "--now", T0,
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "not in bundle" in err


# ---------------------------------------------------------------------
# 15. Full lifecycle: rotate → mid-grace verify → expire → post-grace
# ---------------------------------------------------------------------


def test_full_rotation_lifecycle_end_to_end(
    rotator, fed_bundle, tmp_path: Path
) -> None:
    """The acceptance scenario: Operator rotates, peer-side mid-grace
    verify accepts BOTH kids, operator expires after grace, post-grace
    verify accepts only the new kid.
    """
    v1 = _export_base(fed_bundle, "wakir.test", tmp_path / "v1.jwks")
    v2 = tmp_path / "v2.jwks"
    v3 = tmp_path / "v3.jwks"

    # 1. Rotate at T0 (24h grace).
    rotator.main(
        [
            "rotate",
            "--trust-domain", "wakir.test",
            "--in-file", str(v1),
            "--out", str(v2),
            "--now", T0,
            "--grace-seconds", str(GRACE_24H),
        ]
    )
    doc_v2 = _load(v2)
    old_kid = next(
        k["kid"] for k in doc_v2["keys"] if "_wakir_not_after" in k
    )
    new_kid = next(
        k["kid"] for k in doc_v2["keys"] if "_wakir_not_after" not in k
    )

    # 2. Mid-grace verify (T0+1h): both kids accepted.
    for kid in (old_kid, new_kid):
        rc = rotator.main(
            [
                "verify",
                "--in-file", str(v2),
                "--kid", kid,
                "--now", T0_PLUS_1H,
            ]
        )
        assert rc == 0, f"mid-grace verify must accept {kid!r}"

    # 3. Expire after grace (T0+25h).
    rotator.main(
        [
            "expire",
            "--trust-domain", "wakir.test",
            "--in-file", str(v2),
            "--out", str(v3),
            "--now", T0_PLUS_25H,
        ]
    )

    # 4. Post-grace verify: only new_kid accepted; old_kid 'not in bundle'.
    rc_new = rotator.main(
        [
            "verify",
            "--in-file", str(v3),
            "--kid", new_kid,
            "--now", T0_PLUS_25H,
        ]
    )
    assert rc_new == 0

    rc_old = rotator.main(
        [
            "verify",
            "--in-file", str(v3),
            "--kid", old_kid,
            "--now", T0_PLUS_25H,
        ]
    )
    assert rc_old == 2
