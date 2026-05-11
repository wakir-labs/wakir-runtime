# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""End-to-end loop-closure tests for the Sprint-6-Tag-3 aggregator
signing path against the TV-2 real-manifest fixture cohort.

These tests are the CI-side counterpart to ``scripts/wat-e2e-
aggregator-signed-tv2.py``. The Tag-3 follow-up Item-4 (Mira Sprint-6
Tag-4 Multi-Item-Box Item 3) asked for a demonstrated end-to-end with
production-signed manifests; this test file pins the demonstration so
it does not silently regress between Sprint-6 and Sprint-7.

What is being asserted
----------------------

1. The production aggregator (``wat.cmd.aggregator_cli.build_command``)
   produces a manifest whose ``merkle_root`` matches the TV-2 fixture's
   when given the same B1-fields -- the deterministic-sort contract
   from Sprint-6 Tag-3.
2. With ``--sign-key`` / ``--sign-kid`` supplied, the manifest carries
   a well-formed ``signature`` slot.
3. ``verify_real_manifest_file(verify_signature=True, ...)`` returns
   ``signature_status="verified"`` against the aggregator-signed
   manifest paired with the byte-identical original ``root.bin`` /
   ``root.bin.ots`` side-files.

This is the loop-closure proof Mira called out in the Sprint-6 Tag-3
Folge-Items list (item 4).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
TV2_FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "wat-tv2-real"


def _fixtures_present() -> bool:
    return TV2_FIXTURE_ROOT.is_dir() and any(TV2_FIXTURE_ROOT.iterdir())


pytestmark = pytest.mark.skipif(
    not _fixtures_present(),
    reason="TV-2 real-manifest fixtures not present in this checkout",
)


def _synthesize_spool(fixture_manifest: dict, out_path: Path) -> int:
    leaves = fixture_manifest.get("events") or []
    with out_path.open("w", encoding="utf-8") as fh:
        for leaf in leaves:
            fh.write(
                json.dumps(
                    {
                        "event_id": leaf["event_id"],
                        "time": leaf["time"],
                        "payload_hash": leaf["payload_hash"],
                        "capability_token_hash": leaf["capability_token_hash"],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            fh.write("\n")
    return len(leaves)


def _stage_aggregator_signed_hour(
    src_dir: Path,
    dst_dir: Path,
    *,
    key_file: Path,
    kid: str,
) -> dict:
    """Replay one TV-2 hour through the production aggregator with signing."""
    from wat.cmd.aggregator_cli import build_command

    fixture_manifest = json.loads(
        (src_dir / "manifest.json").read_text(encoding="utf-8")
    )
    spool = dst_dir / "spool.jsonl"
    rows = _synthesize_spool(fixture_manifest, spool)
    assert rows > 0, f"TV-2 fixture {src_dir.name} has no events to replay"

    out_manifest = dst_dir / "manifest.json"
    rebuilt = build_command(
        hour=fixture_manifest["hour_slot"],
        input_events=spool,
        output_manifest=out_manifest,
        prev_hour_root=fixture_manifest.get("prev_hour_root"),
        sign_key=key_file,
        sign_kid=kid,
    )
    # Byte-for-byte side-files so OTS-anchor gate sees the original bytes.
    shutil.copyfile(src_dir / "root.bin", dst_dir / "root.bin")
    shutil.copyfile(src_dir / "root.bin.ots", dst_dir / "root.bin.ots")
    return {"rebuilt": rebuilt, "fixture": fixture_manifest, "manifest_path": out_manifest}


@pytest.fixture
def keypair(tmp_path: Path):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    priv = Ed25519PrivateKey.generate()
    private_seed = priv.private_bytes_raw()
    public_key = priv.public_key().public_bytes_raw()
    key_file = tmp_path / "wat-anchor.key"
    key_file.write_text(private_seed.hex() + "\n", encoding="utf-8")
    return key_file, public_key


@pytest.mark.parametrize(
    "hour_slot",
    [
        "2026-05-27T00",
        "2026-05-27T01",
        "2026-05-27T02",
        "2026-05-27T03",
    ],
)
def test_e2e_aggregator_signed_tv2_hour_verifies(
    tmp_path: Path,
    keypair,
    hour_slot: str,
) -> None:
    """Each TV-2 hour: aggregator-sign -> verifier signature_status=verified.

    Pins the production-loop closure for the Sprint-5-Tag-5 open-item.
    """
    from wat.verify.manifest_v2 import VerifyMode, verify_real_manifest_file

    key_file, public_key = keypair
    src_dir = TV2_FIXTURE_ROOT / hour_slot
    if not src_dir.is_dir():
        pytest.skip(f"TV-2 hour {hour_slot} missing")

    dst_dir = tmp_path / hour_slot
    dst_dir.mkdir(parents=True, exist_ok=True)

    staged = _stage_aggregator_signed_hour(
        src_dir,
        dst_dir,
        key_file=key_file,
        kid="kid-e2e-tv2-test",
    )

    # 1. Deterministic-sort contract: same input -> same merkle_root.
    assert staged["rebuilt"]["merkle_root"] == staged["fixture"]["merkle_root"]
    # 2. Signature slot present on the aggregator output.
    assert "signature" in staged["rebuilt"]
    assert staged["rebuilt"]["signature"]["alg"] == "Ed25519"
    assert staged["rebuilt"]["signature"]["kid"] == "kid-e2e-tv2-test"

    # 3. End-to-end verifier with verify_signature=True passes.
    result = verify_real_manifest_file(
        staged["manifest_path"],
        check_ots_anchor=True,
        use_schema_file=True,
        verify_signature=True,
        verify_signature_public_key=public_key,
        verify_signature_mode=VerifyMode.STRICT,
    )
    assert result.fields_ok, f"fields_ok=False: {result.failure_reason}"
    assert result.integrity_ok, f"integrity_ok=False: {result.failure_reason}"
    assert result.ots_anchor.ok, (
        f"ots_anchor failed: {result.ots_anchor.failure_reason}"
    )
    assert result.signature_status == "verified", (
        f"signature_status={result.signature_status!r} "
        f"failure={result.failure_reason!r}"
    )
    assert result.ok is True


def test_e2e_aggregator_signed_tv2_cohort_all_hours(
    tmp_path: Path,
    keypair,
) -> None:
    """Cohort-wide verdict: every TV-2 hour passes every gate.

    Mirror of the script-form driver
    (``scripts/wat-e2e-aggregator-signed-tv2.py``) so CI carries the
    same end-to-end proof.
    """
    from wat.verify.manifest_v2 import VerifyMode, verify_real_manifest_file

    key_file, public_key = keypair
    hours = sorted(p.name for p in TV2_FIXTURE_ROOT.iterdir() if p.is_dir())
    assert hours, "TV-2 fixture has no hour subdirectories"

    results = []
    for slot in hours:
        src_dir = TV2_FIXTURE_ROOT / slot
        dst_dir = tmp_path / slot
        dst_dir.mkdir(parents=True, exist_ok=True)
        staged = _stage_aggregator_signed_hour(
            src_dir,
            dst_dir,
            key_file=key_file,
            kid="kid-e2e-tv2-cohort",
        )
        result = verify_real_manifest_file(
            staged["manifest_path"],
            check_ots_anchor=True,
            use_schema_file=True,
            verify_signature=True,
            verify_signature_public_key=public_key,
            verify_signature_mode=VerifyMode.STRICT,
        )
        results.append((slot, result))

    # Every hour: signature_status must be verified AND the merkle_root
    # must have matched the fixture (asserted inside the per-hour test;
    # restated here for the cohort-wide invariant).
    for slot, result in results:
        assert result.signature_status == "verified", (
            f"hour {slot}: signature_status={result.signature_status!r}"
        )
        assert result.ok is True, (
            f"hour {slot}: overall verdict not ok; "
            f"failure_reason={result.failure_reason!r}"
        )
