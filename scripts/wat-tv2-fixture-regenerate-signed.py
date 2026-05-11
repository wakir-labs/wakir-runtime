#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Regenerate the signed TV-2 sub-cohort under ``tests/fixtures/
wat-tv2-real-signed/`` from the stock ``wat-tv2-real/*`` fixtures.

Sprint-6-Tag-5 follow-up to Sprint-6-Tag-3 Item 1 (Mira-multi-item-
box Tag-5 Item 1): pre-bake signed Variants of the TV-2 hour-receipt
cohort so verifier tests no longer have to hand-sign manifest copies
on the hot path of every run. The stock unsigned cohort is preserved
unchanged -- backward-compat for the Sprint-3 Tag-2 / Sprint-5 Tag-5
tests that assert on the unsigned default behaviour.

What this script does
---------------------

For each hour-slot in ``tests/fixtures/wat-tv2-real/``:

1. Read the stock unsigned manifest.json.
2. Sign it via ``wat.identity.manifest_signing.sign_manifest`` using
   the doc-pinned demo Ed25519 seed below (NOT a production key --
   it is checked in, used only for fixture-build determinism).
3. Write the signed manifest to ``tests/fixtures/wat-tv2-real-signed/
   <hour>/manifest.json``.
4. Copy ``root.bin`` and ``root.bin.ots`` byte-for-byte alongside it
   so the OTS-anchor gate verifies against the same bytes the
   original receipt anchored.
5. Write a README.md into the signed sub-cohort root that documents
   the demo seed, the kid, the public key, and the regeneration
   command. The README is part of the audit-trail substrate: any
   auditor can re-derive the public key and re-verify the cohort
   end-to-end without trusting the script output.

Why a sub-cohort (and not in-place replacement)
-----------------------------------------------

The stock ``wat-tv2-real/*`` cohort underwrites the Sprint-5 Tag-5
unsigned-strict / signature_status="" backward-compat tests
(``test_tv2_strict_rejects_stock_unsigned_real_manifest``,
``test_tv2_stock_cohort_signature_status_empty_under_default``).
Replacing those fixtures in-place would break those guarantees.
A sibling sub-cohort gives the verifier-test-vereinfachung benefit
for the signed path without sacrificing the unsigned regression
substrate.

Determinism
-----------

The script is idempotent: running it twice produces byte-identical
output (modulo the manifest's own pretty-printing). The demo seed,
the kid, and the canonical-JCS-signing primitive all factor through
:func:`wat.identity.manifest_signing.sign_manifest`, so the
signature bytes are stable given the same unsigned manifest input.

Usage
-----

From the repo root::

    python3 scripts/wat-tv2-fixture-regenerate-signed.py

Optional flags::

    --src-root PATH    Override the stock TV-2 fixture root.
    --dst-root PATH    Override the signed sub-cohort destination.
    --dry-run          Print what would be written without writing.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT_DEFAULT = REPO_ROOT / "tests" / "fixtures" / "wat-tv2-real"
DST_ROOT_DEFAULT = REPO_ROOT / "tests" / "fixtures" / "wat-tv2-real-signed"

# Doc-pinned demo seed -- NOT a production key. The 32-byte raw
# Ed25519 seed below is a fixed test value; it is published in the
# README.md alongside the regenerated cohort. Any party can re-derive
# the corresponding public key and re-verify the signed fixtures.
#
# The Sprint-6-Tag-5 regeneration uses this seed so the on-disk
# signature bytes are stable across re-runs and across operators --
# CI in particular needs byte-deterministic fixtures.
DEMO_SEED_HEX = (
    "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff"
)
DEMO_KID = "wat-tv2-fixture-demo-key"


def _read_manifest(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_manifest(manifest: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _readme_body(public_key_hex: str, hour_slots: list[str]) -> str:
    """Return the README body for the signed sub-cohort.

    The README is the trust substrate: it pins the demo seed, the
    derived public key, and the kid so an auditor can re-verify the
    signed cohort with zero source-of-truth assumptions about the
    script that produced it.
    """
    hours_list = "\n".join(f"- ``{h}``" for h in hour_slots)
    return (
        "# wat-tv2-real-signed -- Aggregator-signed TV-2 sub-cohort\n"
        "\n"
        "This directory holds the Aggregator-signed Variants of the\n"
        "stock ``../wat-tv2-real/`` TV-2 hour-receipt cohort. Pre-baking\n"
        "the signed manifests on-disk is the Sprint-6-Tag-5 simplification\n"
        "of the verifier test substrate: tests no longer need to hand-\n"
        "sign manifest copies on the hot path; they consume the\n"
        "checked-in signed manifests directly.\n"
        "\n"
        "## Demo key material\n"
        "\n"
        "These fixtures are signed with a doc-pinned demo Ed25519 seed.\n"
        "The seed is **NOT a production key** -- it is published below\n"
        "and is used only for fixture-build determinism.\n"
        "\n"
        f"- Private seed (hex, 32 bytes): ``{DEMO_SEED_HEX}``\n"
        f"- Public key (hex, 32 bytes): ``{public_key_hex}``\n"
        f"- Key identifier (``kid``): ``{DEMO_KID}``\n"
        "- Signature algorithm: ``Ed25519`` (RFC 8032)\n"
        "\n"
        "Any party can re-derive the public key from the seed via the\n"
        "``cryptography`` Python package or any conformant Ed25519\n"
        "implementation, and re-verify every signed manifest in this\n"
        "directory end-to-end.\n"
        "\n"
        "## Cohort contents\n"
        "\n"
        f"{hours_list}\n"
        "\n"
        "Each hour-slot directory carries:\n"
        "\n"
        "- ``manifest.json`` -- the Aggregator-signed manifest.\n"
        "- ``root.bin`` -- byte-identical copy of the stock cohort's\n"
        "  receipt root file.\n"
        "- ``root.bin.ots`` -- byte-identical copy of the stock cohort's\n"
        "  OpenTimestamps anchor proof.\n"
        "\n"
        "The ``root.bin`` and ``root.bin.ots`` files are byte-identical\n"
        "copies of the stock cohort. The Merkle root in each signed\n"
        "manifest matches the stock cohort's Merkle root (deterministic\n"
        "Aggregator contract); the OTS-anchor check verifies against\n"
        "the same bytes the original receipt anchored.\n"
        "\n"
        "## Regeneration\n"
        "\n"
        "From the repo root::\n"
        "\n"
        "    python3 scripts/wat-tv2-fixture-regenerate-signed.py\n"
        "\n"
        "The script is idempotent: re-running it produces byte-identical\n"
        "output. Determinism is enforced by the doc-pinned demo seed\n"
        "above and by the canonical JCS-signing primitive in\n"
        "``wat.identity.manifest_signing``.\n"
        "\n"
        "## Test consumption\n"
        "\n"
        "See ``tests/wat/test_tv2_real_signed_fixture.py`` for the\n"
        "verifier-side regression pins.\n"
    )


def regenerate(
    src_root: Path,
    dst_root: Path,
    *,
    dry_run: bool = False,
) -> dict:
    """Regenerate the signed sub-cohort. Returns a stats dict."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    from wat.identity.manifest_signing import (
        SIGNATURE_FIELD,
        sign_manifest,
    )

    seed = bytes.fromhex(DEMO_SEED_HEX)
    if len(seed) != 32:
        raise RuntimeError(
            f"DEMO_SEED_HEX must decode to 32 bytes; got {len(seed)}"
        )

    priv = Ed25519PrivateKey.from_private_bytes(seed)
    public_key = priv.public_key().public_bytes_raw()
    public_key_hex = public_key.hex()

    hour_dirs = sorted(
        p for p in src_root.iterdir() if p.is_dir()
    )
    if not hour_dirs:
        raise RuntimeError(f"no hour subdirectories found under {src_root}")

    hour_slots = [p.name for p in hour_dirs]

    stats = {
        "hours_regenerated": [],
        "public_key_hex": public_key_hex,
        "kid": DEMO_KID,
        "dst_root": str(dst_root),
        "dry_run": dry_run,
    }

    for src_dir in hour_dirs:
        slot = src_dir.name
        dst_dir = dst_root / slot

        src_manifest = _read_manifest(src_dir / "manifest.json")
        signed = sign_manifest(src_manifest, seed, kid=DEMO_KID)
        signed_manifest = dict(signed.manifest)
        signed_manifest[SIGNATURE_FIELD] = dict(signed.signature)

        if dry_run:
            print(
                f"[dry-run] would write signed {slot} to "
                f"{dst_dir / 'manifest.json'}"
            )
        else:
            _write_manifest(signed_manifest, dst_dir / "manifest.json")
            shutil.copyfile(
                src_dir / "root.bin",
                dst_dir / "root.bin",
            )
            shutil.copyfile(
                src_dir / "root.bin.ots",
                dst_dir / "root.bin.ots",
            )
        stats["hours_regenerated"].append(slot)

    if not dry_run:
        readme_path = dst_root / "README.md"
        readme_path.write_text(
            _readme_body(public_key_hex, hour_slots),
            encoding="utf-8",
        )

    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wat-tv2-fixture-regenerate-signed",
        description=(
            "Regenerate the Aggregator-signed TV-2 sub-cohort under "
            "tests/fixtures/wat-tv2-real-signed/ from the stock "
            "wat-tv2-real/ cohort."
        ),
    )
    parser.add_argument(
        "--src-root",
        default=str(SRC_ROOT_DEFAULT),
        help=(
            f"Stock TV-2 fixture root (default: {SRC_ROOT_DEFAULT})"
        ),
    )
    parser.add_argument(
        "--dst-root",
        default=str(DST_ROOT_DEFAULT),
        help=(
            f"Signed sub-cohort destination "
            f"(default: {DST_ROOT_DEFAULT})"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan without writing fixtures.",
    )
    args = parser.parse_args(argv)

    src_root = Path(args.src_root)
    dst_root = Path(args.dst_root)
    if not src_root.is_dir():
        print(
            f"ERROR: source root {src_root} is not a directory",
            file=sys.stderr,
        )
        return 2

    stats = regenerate(src_root, dst_root, dry_run=args.dry_run)
    print(
        f"regenerated {len(stats['hours_regenerated'])} hours under "
        f"{stats['dst_root']}: {stats['hours_regenerated']}"
    )
    print(f"kid: {stats['kid']}")
    print(f"public_key_hex: {stats['public_key_hex']}")
    if args.dry_run:
        print("dry-run: no files written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
