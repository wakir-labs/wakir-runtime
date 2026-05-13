# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors

"""Command-line front-end for the 4-pole external verifier.

Surface:

    wat-verify --anchor <hash> --ots-proof <file>
               [--pols all|3-of-4|2-of-4]
               [--expected-block-height <H>]
               [--expected-block-hash <hex>]
               [--mempool-base-url <url>] [--esplora-base-url <url>]
               [--skip-pole pole_name ...]

Output: JSON to stdout. Exit codes:

* 0 — quorum reached.
* 1 — quorum not reached (audit-failure verdict).
* 2 — CLI usage error.

The CLI is intentionally JSON-only; an auditor pipes the output to
``jq`` or stores it next to the anchor for the audit trail. No
human-friendly text mode in Tag-1; that ships when an operator
asks for it.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from wat.anchor.external_verifier.aggregator import (
    QuorumPolicy,
    verify_wat_anchor,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wat-verify",
        description=(
            "4-pole cross-library verifier for WAT Bitcoin anchors. "
            "Runs an OTS proof file through four independent verifier "
            "poles and emits a quorum verdict as JSON."
        ),
    )
    p.add_argument(
        "--anchor",
        required=True,
        help="Lowercase 64-hex Merkle root anchored by the OTS receipt.",
    )
    p.add_argument(
        "--ots-proof",
        required=True,
        help="Path to the .ots receipt file.",
    )
    p.add_argument(
        "--pols",
        choices=[p.value for p in QuorumPolicy],
        default=QuorumPolicy.THREE_OF_FOUR.value,
        help="Quorum policy (default: 3-of-4).",
    )
    p.add_argument(
        "--expected-block-height",
        type=int,
        default=None,
        help=(
            "Bitcoin block height the receipt is expected to attest. "
            "Required for the two HTTP poles; without it those poles "
            "return 'unavailable' and the quorum falls back to the "
            "offline poles."
        ),
    )
    p.add_argument(
        "--expected-block-hash",
        type=str,
        default=None,
        help=(
            "Optional canonical block hash to assert against the "
            "HTTP-pole responses. When omitted, the HTTP poles run "
            "in witness-capture mode."
        ),
    )
    p.add_argument(
        "--mempool-base-url",
        type=str,
        default=None,
        help="Override base URL for the mempool.space pole.",
    )
    p.add_argument(
        "--esplora-base-url",
        type=str,
        default=None,
        help="Override base URL for the blockstream.info pole.",
    )
    p.add_argument(
        "--skip-pole",
        action="append",
        default=[],
        help=(
            "Disable a pole by name. Repeatable. Useful for "
            "operator-host-only verification (e.g. skip both HTTP "
            "poles for an offline brand-proof rerun)."
        ),
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    pole_overrides: dict[str, dict] = {}
    if args.expected_block_height is not None:
        for pole_name in ("pole_mempool_space", "pole_esplora_blockstream"):
            pole_overrides[pole_name] = {
                "expected_block_height": args.expected_block_height,
                "expected_block_hash": args.expected_block_hash,
            }
        pole_overrides["pole_python_stdlib"] = {
            "expected_block_height": args.expected_block_height,
        }
        pole_overrides["pole_ots_cli"] = {
            "expected_block_height": args.expected_block_height,
        }

    if args.mempool_base_url:
        pole_overrides.setdefault("pole_mempool_space", {})[
            "base_url"
        ] = args.mempool_base_url
    if args.esplora_base_url:
        pole_overrides.setdefault("pole_esplora_blockstream", {})[
            "base_url"
        ] = args.esplora_base_url

    enabled = [
        name
        for name in (
            "pole_python_stdlib",
            "pole_ots_cli",
            "pole_mempool_space",
            "pole_esplora_blockstream",
        )
        if name not in (args.skip_pole or [])
    ]
    if not enabled:
        parser.error("--skip-pole removed every pole; nothing to verify.")

    # If HTTP poles are enabled but the operator did not supply
    # --expected-block-height, the two HTTP poles cannot run at all
    # (they need a height to query). Trim them rather than letting
    # them fail-unavailable; the operator gets a clean offline-only
    # verdict instead of a noisy 2-of-4 fallback.
    if args.expected_block_height is None:
        enabled = [
            n
            for n in enabled
            if n not in ("pole_mempool_space", "pole_esplora_blockstream")
        ]

    try:
        verification = verify_wat_anchor(
            anchor_hash=args.anchor,
            ots_proof_path=args.ots_proof,
            quorum_policy=QuorumPolicy(args.pols),
            enabled_poles=enabled,
            pole_overrides=pole_overrides,
        )
    except ValueError as exc:
        parser.error(str(exc))
        return 2

    print(json.dumps(verification.to_dict(), indent=2, sort_keys=True))
    return 0 if verification.quorum else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
