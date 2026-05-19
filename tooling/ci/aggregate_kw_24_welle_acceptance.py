#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""KW-24 Welle-1..7 Acceptance Aggregator -- Tag-66 (Amara, Continuous-Mode-Marathon).

Background
----------

Tag-66 (2026-05-19) pins the per-Welle acceptance-criteria for
the KW-24..KW-27 Cutover-Marathon (T0 = KW-24 Mo 2026-06-08).
See ``docs/quality-gates/kw-24-welle-1-7-acceptance-criteria.md``
for the full per-Welle stage-spec.

This aggregator folds the four per-Welle stage-statuses
(``W{N}_S1..S4_STATUS``) into a single per-Welle verdict
(``WELLE-{N}-{READY|DRIFT|DEFECT}``) using the Tag-63 E2E-Smoke
trinary-verdict-rule (any red collapses, any yellow degrades).

Decision rule (canonical)
-------------------------

.. code-block:: text

    inputs:  s1, s2, s3, s4 in {green, yellow, red}
    output:  WELLE-{N}-{READY|DRIFT|DEFECT}

    decide:
      any red                -> WELLE-{N}-DEFECT
      else any yellow        -> WELLE-{N}-DRIFT
      else                   -> WELLE-{N}-READY

Cross-Welle propagation
-----------------------

Welle-3 (Bridge-Audit) downstream-blocks Welle-4/5/7. If the
input Welle is 3 and the resulting verdict is WELLE-3-DEFECT,
the envelope ``downstream_blocks`` field lists welle-4, welle-5,
welle-7. The actual blocking happens in the downstream-Welle
workflows that consume this aggregator's verdict; the aggregator
only carries the data-only flag.

Hermetic posture
----------------

stdlib-only. No subprocess, no network, no third-party deps.
Reads stage-statuses from environment, writes a verdict envelope
JSON to ``--output`` (or stdout if omitted).

Scope discipline (Amara, ADR-0036/0043/0044/0066)
-------------------------------------------------

This aggregator pins only the Tag-66 per-Welle verdict surface.
It does NOT modify persona definitions (Aisha-Domaene), WAT-core /
V-907 logic (Tomas-Domaene, Zone-K), identity-substrate (Reza-
Domaene, Zone-L), container-infra (Kai-Domaene, Zone-J), or
persona-engine substrate (Selin-Domaene, Zone-O).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List, Tuple

VALID_STAGE_STATUSES = ("green", "yellow", "red")
VALID_VERDICTS = ("WELLE-{N}-READY", "WELLE-{N}-DRIFT", "WELLE-{N}-DEFECT")

WELLE_RANGE = (1, 2, 3, 4, 5, 6, 7)

WELLE_ANCHORS: Dict[int, Tuple[str, str, str]] = {
    1: ("KW-24", "Mo", "engine_cutover"),
    2: ("KW-24", "Mi", "doppelbetrieb_sealing"),
    3: ("KW-24", "Fr", "bridge_audit"),
    4: ("KW-25", "Mo", "state_backing"),
    5: ("KW-25", "Fr", "capability_token"),
    6: ("KW-26", "Fr", "cross_substrate_parity"),
    7: ("KW-27", "Fr", "final_sealing"),
}

# Welle-3 downstream-block targets per Tag-45 hot-spot-aggregator family
WELLE_3_DOWNSTREAM_BLOCKS: Tuple[int, ...] = (4, 5, 7)


def _normalize_status(raw: str) -> str:
    """Normalize stage-status to canonical lowercase token.

    Unknown -> 'red' (fail-closed).
    """
    s = (raw or "").strip().lower()
    if s in VALID_STAGE_STATUSES:
        return s
    return "red"


def decide(stages: List[str]) -> str:
    """Apply the trinary-verdict-rule to a list of stage-statuses.

    Returns one of READY / DRIFT / DEFECT (without the WELLE-{N}-
    prefix; caller composes the final verdict-string).
    """
    statuses = [_normalize_status(s) for s in stages]
    if any(s == "red" for s in statuses):
        return "DEFECT"
    if any(s == "yellow" for s in statuses):
        return "DRIFT"
    return "READY"


def build_envelope(
    welle: int,
    s1: str,
    s2: str,
    s3: str,
    s4: str,
    n1: str = "",
    n2: str = "",
    n3: str = "",
    n4: str = "",
) -> Dict:
    """Build the per-Welle verdict envelope (schema documented in §8.4)."""
    if welle not in WELLE_RANGE:
        raise ValueError(f"Welle out of range 1..7: {welle!r}")
    anchor_kw, anchor_weekday, substrate_focus = WELLE_ANCHORS[welle]
    stages = [s1, s2, s3, s4]
    verdict_token = decide(stages)
    verdict = f"WELLE-{welle}-{verdict_token}"

    notes_pairs = [
        (f"w{welle}_s1", n1),
        (f"w{welle}_s2", n2),
        (f"w{welle}_s3", n3),
        (f"w{welle}_s4", n4),
    ]
    notes = ";".join(f"{k}:{v}" for k, v in notes_pairs if v)

    downstream: List[str] = []
    if welle == 3 and verdict_token == "DEFECT":
        downstream = [f"welle-{n}" for n in WELLE_3_DOWNSTREAM_BLOCKS]

    return {
        "verdict": verdict,
        "welle": welle,
        "anchor_kw": anchor_kw,
        "anchor_weekday": anchor_weekday,
        "substrate_focus": substrate_focus,
        "stages": {
            "s1": _normalize_status(s1),
            "s2": _normalize_status(s2),
            "s3": _normalize_status(s3),
            "s4": _normalize_status(s4),
        },
        "notes": notes,
        "downstream_blocks": downstream,
        "pattern_lineage": (
            "tag-63-e2e-smoke-trinary-verdict + "
            "tag-45-welle-hot-spot-aggregator-family"
        ),
        "cross_review_markers": [
            "zone-M (Tomás aggregation)",
            "zone-N (Henrik audit, Welle-3+Welle-7 IIA-1130)",
        ],
        "doc_anchor": (
            "docs/quality-gates/kw-24-welle-1-7-acceptance-criteria.md"
        ),
    }


def _read_env_for_welle(welle: int) -> Tuple[str, str, str, str, str, str, str, str]:
    def _get(name: str) -> str:
        return os.environ.get(name, "") or ""

    s1 = _get(f"W{welle}_S1_STATUS")
    s2 = _get(f"W{welle}_S2_STATUS")
    s3 = _get(f"W{welle}_S3_STATUS")
    s4 = _get(f"W{welle}_S4_STATUS")
    n1 = _get(f"W{welle}_S1_NOTE")
    n2 = _get(f"W{welle}_S2_NOTE")
    n3 = _get(f"W{welle}_S3_NOTE")
    n4 = _get(f"W{welle}_S4_NOTE")
    return s1, s2, s3, s4, n1, n2, n3, n4


def _parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Tag-66 KW-24 Welle-1..7 Per-Welle Acceptance Aggregator. "
            "Reads W{N}_S{1..4}_STATUS env-vars, emits a per-Welle verdict-envelope."
        )
    )
    p.add_argument(
        "--welle",
        type=int,
        required=True,
        choices=list(WELLE_RANGE),
        help="Welle number 1..7",
    )
    p.add_argument(
        "--output",
        type=str,
        default="",
        help="Output JSON path (default: stdout)",
    )
    return p.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    s1, s2, s3, s4, n1, n2, n3, n4 = _read_env_for_welle(args.welle)
    envelope = build_envelope(args.welle, s1, s2, s3, s4, n1, n2, n3, n4)
    rendered = json.dumps(envelope, indent=2, sort_keys=True)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(rendered + "\n")
    else:
        sys.stdout.write(rendered + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
