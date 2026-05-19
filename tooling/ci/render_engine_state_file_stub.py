#!/usr/bin/env python3
# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-68 Engine-Side State-File Render-Stub (Selin, audit-only).

This helper accompanies
``docs/persona-engine/state-file-producer-wiring-plan.md`` (Tag-68).
It is a **render-only** stub: given a ``(welle_number, kw_anchor)``
pair, it produces the canonical pending-status JSON for
``state/welle-N.json`` per the Tag-67 schema-pin
(``docs/quality-gates/welle-n-state-file-conventions.md``).

The stub is **audit-only**: it has no write-mode. Tag-68 is a
plan-doc-only deliverable; the actual write-path is the Tag-69+
engine-side writer's responsibility, as documented in
``state-file-producer-wiring-plan.md`` §5.

Usage (CLI)
-----------

::

    python3 tooling/ci/render_engine_state_file_stub.py \\
        --welle 3 --kw KW-25

    # Render all seven canonical stubs (pre-Cutover-T0 initial-state):
    python3 tooling/ci/render_engine_state_file_stub.py --all

Exit-code: 0 on success, 1 on invalid input.

Sandbox-Boundary
----------------

* stdlib-only (``argparse``, ``json``, ``sys``).
* No filesystem writes. No network. No subprocess.
* Output is to stdout exclusively (CLI) or returned as a Python
  ``dict`` / JSON string (library use).

This module is hermetic-by-construction per Mira's
Sandbox-vs-Host-Operations Trennung and the Tag-68 plan-doc §6.

Scope discipline (Selin)
------------------------
This stub does NOT modify persona definitions (Aisha-Domaene,
ADR-0043), WAT-core logic (Tomas-Domaene, Zone-K),
identity-substrate design (Reza-Domaene, Zone-L), or
container-infra (Kai-Domaene, Zone-J). It renders strings that
match the Tag-67 schema-pin (Amara-domain, QA).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Dict, List, Tuple

SCHEMA_VERSION = "tag-67-v1"
PHASE_LITERAL = "phase-3-marathon"

# Canonical KW-anchor map per the Marathon-Schedule, locked to the
# operational Source-of-Truth ``docs/quality-gates/pre-cutover-
# acceptance-run-order.md`` §3 per-Welle Run-Order table (lines 90..98).
# Wellen-Reihe (post Tag-74 reconciliation):
#   1=KW-22, 2=KW-23, 3=KW-25, 4=KW-26, 5=KW-26, 6=KW-26, 7=KW-27.
#
# Tag-74 W5-anchor reconciliation (Selin)
# ---------------------------------------
# The W5 default-map was previously KW-25 (Tag-67 render-helper default,
# inherited from a pre-ADR-0066 schedule that placed Welle-5 on KW-25 Fr
# 2026-06-19 as a solo-welle). ADR-0066 four-Wochen-Cadence locked the
# Doppel-Welle-4+5 to KW-26 (Cutover-Mittwoch 2026-06-24, Sign-off-
# Freitag 2026-06-26), which the operational Source-of-Truth
# ``pre-cutover-acceptance-run-order.md`` §3 table reflects.
#
# Source-of-Truth resolution
# --------------------------
# When the persona-engine helper-default disagrees with another
# canonical-doc reference, the operational Final-Reference
# ``docs/quality-gates/pre-cutover-acceptance-run-order.md`` wins.
# Rationale: it is the run-order doc Amara + Henrik + Aisha consult on
# cutover-Mittwoch + sign-off-Freitag; older docstrings (e.g. the
# ``handle_welle_5_signoff_event`` docstring's ``KW-25 Fr 2026-06-19``
# inherited string) are historical references that do not gate the
# producer-substrate's runtime behaviour (the producer is kw-anchor-
# agnostic at the transition-machine level -- the kw-anchor lives in
# the state-file's ``kw_cutover_anchor`` field, not in the transition
# guard).
#
# The reconciliation is documented in
# ``docs/persona-engine/welle-5-kw-anchor-reconciliation-tag74.md``.
# This Tag-74 render-helper fix changes ONLY the default-map; the
# ``state/welle-5.json`` on-disk file remains the operator-curated
# source-of-truth for the runtime ``kw_cutover_anchor`` field.
CANONICAL_KW_ANCHOR: Dict[int, str] = {
    1: "KW-22",
    2: "KW-23",
    3: "KW-25",
    4: "KW-26",
    5: "KW-26",
    6: "KW-26",
    7: "KW-27",
}

VALID_KW_ANCHORS = {f"KW-2{d}" for d in range(2, 8)}  # KW-22..KW-27
VALID_WELLE_NUMBERS = set(range(1, 8))  # 1..7
VALID_STATUS_ENUMS = {
    "pending",
    "in-progress",
    "signed-off",
    "rolled-back",
}


def _rollup_links(welle_number: int) -> Dict[str, str]:
    """Return the canonical rollup_links dict for welle-N."""
    return {
        "sign_off": f"state/welle-{welle_number}-sign-off.json",
        "validation_last_verdict": (
            f"state/welle-{welle_number}-validation-last-verdict.json"
        ),
        "hot_spot_trend_dir": f"state/welle-{welle_number}-hot-spot-trend/",
        "pre_auditor_decision": (
            f"state/welle-{welle_number}-pre-auditor-decision.json"
        ),
    }


def render_stub(welle_number: int, kw_anchor: str) -> Dict[str, object]:
    """Render the canonical pending-status stub for ``welle-N``.

    Returns a Python dict that, when serialised with
    ``json.dumps(..., indent=2)`` and a trailing newline,
    reproduces the Tag-67 stub-file shape exactly.

    Raises ``ValueError`` if ``welle_number`` is not in 1..7 or
    ``kw_anchor`` does not match ``^KW-2[2-7]$``.
    """
    if welle_number not in VALID_WELLE_NUMBERS:
        raise ValueError(
            f"welle_number must be in 1..7, got {welle_number!r}"
        )
    if kw_anchor not in VALID_KW_ANCHORS:
        raise ValueError(
            f"kw_anchor must match ^KW-2[2-7]$, got {kw_anchor!r}"
        )
    return {
        "welle_number": welle_number,
        "schema_version": SCHEMA_VERSION,
        "phase": PHASE_LITERAL,
        "kw_cutover_anchor": kw_anchor,
        "cutover_iso": "",
        "signoff_iso": "",
        "status": "pending",
        "rollup_links": _rollup_links(welle_number),
        "audit_trail_anchor": "",
    }


def render_all() -> List[Tuple[int, Dict[str, object]]]:
    """Render the seven canonical stubs for Welle-1..7.

    Returns a list of ``(welle_number, stub_dict)`` tuples in
    Welle-number order, using the canonical KW-anchor map.
    """
    return [
        (n, render_stub(n, CANONICAL_KW_ANCHOR[n]))
        for n in sorted(VALID_WELLE_NUMBERS)
    ]


def render_stub_json(welle_number: int, kw_anchor: str) -> str:
    """Convenience wrapper: render + serialise + trailing newline."""
    return json.dumps(render_stub(welle_number, kw_anchor), indent=2) + "\n"


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="render_engine_state_file_stub.py",
        description=(
            "Tag-68 Engine-Side State-File Render-Stub (audit-only). "
            "Renders canonical pending-status JSON for "
            "state/welle-N.json per Tag-67 schema-pin."
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--welle",
        type=int,
        help="Render the stub for a single Welle (1..7). Requires --kw.",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Render all seven canonical stubs in Welle-number order.",
    )
    parser.add_argument(
        "--kw",
        type=str,
        help="KW-anchor (KW-22..KW-27). Required with --welle.",
    )
    return parser


def main(argv: List[str]) -> int:
    parser = _build_argparser()
    args = parser.parse_args(argv)
    if args.all:
        for _, stub in render_all():
            print(json.dumps(stub, indent=2))
        return 0
    if args.welle is None:
        parser.error("--welle requires an int")
    if args.kw is None:
        parser.error("--welle requires --kw")
    try:
        out = render_stub_json(args.welle, args.kw)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
