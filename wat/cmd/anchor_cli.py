# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Part of the Wakir Audit Trail (WAT) module. Licensed under
# Business Source License 1.1; see ../LICENSE-BSL.md.

"""Console-script entry point for the WAT OTS anchor pipeline.

Subcommands
-----------

- ``stamp <root-hex> [--out DIR]`` — submit a Merkle root (hex
  string) to the configured calendars, write the pending receipt.
- ``upgrade <receipt-path>`` — attempt to upgrade a pending receipt
  to a Bitcoin attestation.
- ``verify <receipt-path> <root-hex>`` — verify a finalised receipt
  attests to the given root.

Body is intentionally thin: domain logic lives in
``wat.anchor.ots_anchor``. This module owns argparse plumbing,
hex<->bytes conversion, and exit-code translation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from wat.anchor.ots_anchor import (
    AnchorError,
    DEFAULT_MIN_CALENDARS,
    anchor_root,
    upgrade_pending,
    verify_receipt,
)


def build_parser() -> argparse.ArgumentParser:
    """Return the configured argument parser."""
    parser = argparse.ArgumentParser(
        prog="wakir-anchor",
        description="Anchor and verify WAT Merkle roots via OpenTimestamps.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_stamp = sub.add_parser("stamp", help="Submit a Merkle root to OTS calendars.")
    p_stamp.add_argument("root_hex", help="32-byte SHA-256 root in hex (64 chars).")
    p_stamp.add_argument(
        "--out",
        default="meta/timestamps/wat/_pending",
        help="Directory for root.bin and root.bin.ots (default: %(default)s).",
    )
    p_stamp.add_argument(
        "--min-calendars",
        type=int,
        default=DEFAULT_MIN_CALENDARS,
        help="Minimum calendar attestations required (default: %(default)s).",
    )

    p_upgrade = sub.add_parser("upgrade", help="Upgrade a pending receipt.")
    p_upgrade.add_argument("receipt", help="Path to a .ots receipt file.")

    p_verify = sub.add_parser("verify", help="Verify a finalised receipt.")
    p_verify.add_argument("receipt", help="Path to a .ots receipt file.")
    p_verify.add_argument("root_hex", help="Expected root in hex (64 chars).")

    return parser


def _hex_to_bytes(hexstr: str) -> bytes:
    raw = bytes.fromhex(hexstr)
    if len(raw) != 32:
        raise ValueError(f"root must decode to 32 bytes, got {len(raw)}")
    return raw


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Returns a Unix exit code (0 on success)."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.cmd == "stamp":
            receipt = anchor_root(
                merkle_root=_hex_to_bytes(args.root_hex),
                min_calendars=args.min_calendars,
                target_dir=Path(args.out),
            )
            print(f"pending receipt: {receipt.receipt_path}")
            for url, status in receipt.calendar_responses.items():
                print(f"  {url}: {status}")
            return 0

        if args.cmd == "upgrade":
            upgraded = upgrade_pending(args.receipt)
            if upgraded.is_finalised:
                print(
                    f"finalised: bitcoin block {upgraded.bitcoin_block_height} "
                    f"({upgraded.receipt_path})"
                )
                return 0
            print(f"still pending: {upgraded.receipt_path}")
            return 0

        if args.cmd == "verify":
            ok = verify_receipt(args.receipt, _hex_to_bytes(args.root_hex))
            print("ok" if ok else "FAIL")
            return 0 if ok else 1

    except AnchorError as exc:
        print(f"anchor error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"input error: {exc}", file=sys.stderr)
        return 64

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
