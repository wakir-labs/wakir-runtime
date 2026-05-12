#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""End-to-end demonstration: aggregator-signed manifest -> real-tv2
verifier pipeline with signature verification.

This is the substantive Sprint-6-Tag-3 follow-up Item 4 (Mira-Multi-
Item-Box Sprint-6-Tag-4, Item 3): tie the production-side signing
that Tag-3 landed (``--sign-key`` / ``--sign-kid`` on the aggregator)
to the verifier-side signature-status gate from Sprint-5-Tag-5,
running over the TV-2 real-manifest fixture cohort.

What this script does
---------------------

1. Synthesize a per-hour spool from each TV-2 fixture's leaf list
   (B1-fields are byte-identical to the fixture; the raw spool is
   not checked into the repo).
2. Generate one fresh Ed25519 keypair for the whole run.
3. For each TV-2 hour slot, invoke the production aggregator
   (``wat.cmd.aggregator_cli.build_command``) with the synthesized
   spool AND ``--sign-key`` / ``--sign-kid`` -- i.e. the SAME code
   path the cron driver will exercise in production.
4. Copy the original ``root.bin`` and ``root.bin.ots`` side-files
   next to the aggregator-signed manifest (byte-for-byte; the
   OTS-anchor check verifies against the same bytes the original
   receipt anchored).
5. Assert ``manifest["merkle_root"]`` equals the fixture's
   ``merkle_root`` -- this is the deterministic-sort contract from
   Sprint-6 Tag-3.
6. Run ``verify_real_manifest_file(verify_signature=True, ...)``
   against the aggregator-signed copy and require
   ``signature_status == "verified"`` on every hour.

Exit codes
----------

0  every hour passed every gate (fields + integrity + ots-anchor +
   signature) AND merkle_root matched the fixture
1  any hour failed any gate

This is a closing-the-loop driver -- it does NOT live-anchor anything
new, it consumes the pre-existing OTS receipts in the fixture cohort.
The point is to demonstrate that the Tag-3 aggregator's signed output
flows cleanly into the Sprint-5-Tag-5 verifier substrate end-to-end.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TV2_FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "wat-tv2-real"
DEFAULT_HOUR_SLOTS = (
    "2026-05-27T00",
    "2026-05-27T01",
    "2026-05-27T02",
    "2026-05-27T03",
)


def _synthesize_spool(fixture_manifest: dict, out_path: Path) -> int:
    """Reconstruct a synthetic spool from the fixture's leaf/event list.

    Returns the number of rows written. B1-fields are taken verbatim
    from the fixture so the rebuilt manifest hashes to the same
    merkle_root as the original.
    """
    leaves = fixture_manifest.get("events") or []
    rows = [
        {
            "event_id": leaf["event_id"],
            "time": leaf["time"],
            "payload_hash": leaf["payload_hash"],
            "capability_token_hash": leaf["capability_token_hash"],
        }
        for leaf in leaves
    ]
    with out_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, separators=(",", ":")))
            fh.write("\n")
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wat-e2e-aggregator-signed-tv2",
        description=(
            "End-to-end driver: aggregator-signed TV-2 cohort -> "
            "verify_real_manifest_file(verify_signature=True). Exit 0 "
            "iff every hour passes every gate."
        ),
    )
    parser.add_argument(
        "--fixture-root",
        default=str(TV2_FIXTURE_ROOT),
        help=f"TV-2 fixture root (default: {TV2_FIXTURE_ROOT})",
    )
    parser.add_argument(
        "--hour-slots",
        nargs="+",
        default=list(DEFAULT_HOUR_SLOTS),
        help=(
            "TV-2 hour slots to drive end-to-end (default: the four "
            "stock cohort slots)."
        ),
    )
    parser.add_argument(
        "--kid",
        default="wat-anchor-e2e-tv2-driver",
        help="kid value embedded in the signed manifests.",
    )
    parser.add_argument(
        "--keep-staging",
        action="store_true",
        help=(
            "Leave the staging tmp directory in place after the run "
            "(useful for post-mortems). Default: cleaned up."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-hour progress; emit only the verdict line.",
    )
    args = parser.parse_args(argv)

    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    from wat.cmd.aggregator_cli import build_command
    from wat.verify.manifest_v2 import VerifyMode, verify_real_manifest_file

    fixture_root = Path(args.fixture_root)
    if not fixture_root.is_dir():
        print(
            f"ERROR: fixture root {fixture_root} is not a directory",
            file=sys.stderr,
        )
        return 2

    # One keypair per run; the same public key verifies every hour.
    priv = Ed25519PrivateKey.generate()
    private_seed = priv.private_bytes_raw()
    public_key = priv.public_key().public_bytes_raw()

    staging_ctx = tempfile.TemporaryDirectory(
        prefix="wat-e2e-aggregator-signed-tv2-"
    )
    staging_root = Path(staging_ctx.name)
    # Write the private seed once as a 64-hex-char file -- the
    # aggregator reads it back the same way the operator runbook
    # describes the production --sign-key flag.
    key_file = staging_root / "wat-anchor.key"
    key_file.write_text(private_seed.hex() + "\n", encoding="utf-8")

    all_ok = True
    per_hour: list[dict] = []

    try:
        for slot in args.hour_slots:
            src_dir = fixture_root / slot
            if not src_dir.is_dir():
                print(
                    f"ERROR: fixture hour {slot} not found at {src_dir}",
                    file=sys.stderr,
                )
                return 2

            fixture_manifest_path = src_dir / "manifest.json"
            fixture_manifest = json.loads(
                fixture_manifest_path.read_text(encoding="utf-8")
            )

            hour_staging = staging_root / slot
            hour_staging.mkdir(parents=True, exist_ok=True)

            spool = hour_staging / "spool.jsonl"
            row_count = _synthesize_spool(fixture_manifest, spool)

            out_manifest = hour_staging / "manifest.json"

            # Drive the PRODUCTION aggregator with signing enabled.
            rebuilt = build_command(
                hour=fixture_manifest["hour_slot"],
                input_events=spool,
                output_manifest=out_manifest,
                prev_hour_root=fixture_manifest.get("prev_hour_root"),
                sign_key=key_file,
                sign_kid=args.kid,
            )

            # Deterministic-sort contract: same B1-fields in, same
            # root out. If this drifts the rest is moot.
            merkle_match = rebuilt["merkle_root"] == fixture_manifest["merkle_root"]

            # Byte-for-byte side-file copy so the OTS-anchor gate
            # in verify_real_manifest_file sees the same bytes the
            # original receipt anchored. The aggregator does not
            # touch the OTS path on its own; this is the boundary
            # condition for an honest end-to-end.
            shutil.copyfile(src_dir / "root.bin", hour_staging / "root.bin")
            shutil.copyfile(
                src_dir / "root.bin.ots",
                hour_staging / "root.bin.ots",
            )

            # And run the verifier with signature mode on.
            result = verify_real_manifest_file(
                out_manifest,
                check_ots_anchor=True,
                use_schema_file=True,
                verify_signature=True,
                verify_signature_public_key=public_key,
                verify_signature_mode=VerifyMode.STRICT,
            )

            ots_ok = bool(result.ots_anchor.ok)
            hour_ok = bool(
                merkle_match
                and result.fields_ok
                and result.integrity_ok
                and ots_ok
                and result.signature_status == "verified"
            )
            all_ok = all_ok and hour_ok
            per_hour.append(
                {
                    "hour_slot": slot,
                    "rows": row_count,
                    "merkle_match": merkle_match,
                    "fields_ok": result.fields_ok,
                    "integrity_ok": result.integrity_ok,
                    "ots_anchor_ok": ots_ok,
                    "signature_status": result.signature_status,
                    "verdict": "OK" if hour_ok else "FAIL",
                }
            )

            if not args.quiet:
                print(
                    f"[{slot}] rows={row_count} merkle_match={merkle_match} "
                    f"fields={result.fields_ok} integrity={result.integrity_ok} "
                    f"ots={ots_ok} "
                    f"signature_status={result.signature_status} "
                    f"verdict={'OK' if hour_ok else 'FAIL'}"
                )

        if not args.quiet:
            print("---")
            print(
                f"end-to-end verdict: "
                f"{'OK (every hour: fields+integrity+ots+signature verified)' if all_ok else 'FAIL'}"
            )
            print(f"hours processed: {len(per_hour)}")
            print(
                f"signature kid: {args.kid}  "
                f"public_key_hex: {public_key.hex()}"
            )
            if args.keep_staging:
                print(f"staging dir (preserved): {staging_root}")
        else:
            print("OK" if all_ok else "FAIL")

        return 0 if all_ok else 1
    finally:
        if not args.keep_staging:
            staging_ctx.cleanup()


if __name__ == "__main__":
    sys.exit(main())
