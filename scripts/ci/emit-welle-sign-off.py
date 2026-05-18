#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Emit a ``state/welle-N-sign-off.json`` envelope from a Welle-N
cutover-acceptance-decision envelope. Tag-51 (Tomas).

Each Welle-N validation workflow renders an
``out/cutover-acceptance-decision.json`` envelope with the per-step
verdict for the cutover. The Tag-50 Marathon-Final-Bilanz aggregator
(``tooling/ci/marathon_final_bilanz_aggregator.py``) reads sign-off
envelopes from ``state/welle-N-sign-off.json`` to compute the Henrik
slot. This script bridges the two: it takes the decision envelope,
extracts the canonical fields, and writes a sign-off envelope shaped
to match the aggregator's schema expectations.

Sign-off envelope schema (``wakir.phase-3c.welle-sign-off/1``):

    {
      "schema": "wakir.phase-3c.welle-sign-off/1",
      "welle":            int (1..7),
      "welle_slug":       "welle-N",
      "component":        str (e.g. "v907_verify", "recovery_workflow"),
      "signed_off_by":    "henrik",
      "audit_ok":         bool,
      "verdict":          "READY" | "CAUTION" | "BLOCK",
      "signed_off_at":    ISO 8601 UTC timestamp,
      "source_envelope":  str (path to the decision envelope used),
      "decision_summary": {
          "ready_for_live_smoke": bool | None,
          "score_band_floor":     str | None,
          "observed_band":        str | None,
          "hard_block_reasons":   list[str],
      },
      "notes":            list[str],
    }

Decision-envelope normalisation
-------------------------------

Welle-1, Welle-2, Welle-4 emit a 4-step decision envelope with a
boolean ``ready_for_live_smoke`` field (true = READY, false = BLOCK).
Welle-3, Welle-5, Welle-6, Welle-7 emit a 5-step+ decision envelope
with an explicit ``verdict`` field (READY/CAUTION/BLOCK). The emitter
normalises both shapes into the canonical
``verdict``/``audit_ok`` pair:

* ``verdict``: READY if explicit, else READY if ``ready_for_live_smoke``
  is true, else BLOCK.
* ``audit_ok``: ``True`` if verdict is READY, else ``False``. CAUTION is
  marked as ``audit_ok=False`` so Henrik's slot picks it up in the
  bilanz aggregator (the aggregator's Henrik slot treats audit_ok=False
  as a PARTIAL verdict, which is the correct downstream signal for a
  CAUTION).

The ``hard_block_reasons`` list is preserved verbatim when present so
Henrik's downstream audit-bundle can trace BLOCK provenance. If the
decision envelope is missing ``hard_block_reasons``, the field defaults
to an empty list.

Sandbox posture
---------------

stdlib-only. No subprocess. No network. No filesystem writes outside
the configured ``--output``. The hermetic test suite is at
``tests/ci/test_emit_welle_sign_off.py``.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys
from typing import Any

SCHEMA_VERSION = "wakir.phase-3c.welle-sign-off/1"

# Component name canonicalisation: long-form (ADR-0065) keyed by Welle index.
WELLE_TO_COMPONENT = {
    1: "v907_verify",
    2: "svid_workload_identity",
    3: "bridge_audit_writer",
    4: "state_backing",
    5: "lifecycle_state_machine",
    6: "subscribe_loop",
    7: "recovery_workflow",
}

VALID_VERDICTS = ("READY", "CAUTION", "BLOCK")


def _read_json(path: pathlib.Path) -> Any:
    """Read JSON; return ``None`` on missing file, raise on parse error."""
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise SystemExit(f"FATAL: malformed JSON at {path}: {e}") from e


def derive_verdict(envelope: Any) -> str:
    """Normalise the envelope's verdict to READY/CAUTION/BLOCK.

    Precedence: explicit ``verdict`` field wins. Otherwise fall back to
    ``ready_for_live_smoke`` boolean. If neither is present or both are
    malformed, return ``BLOCK`` (conservative).
    """
    if isinstance(envelope, dict):
        v = envelope.get("verdict")
        if isinstance(v, str) and v.upper() in VALID_VERDICTS:
            return v.upper()
        rfls = envelope.get("ready_for_live_smoke")
        if isinstance(rfls, bool):
            return "READY" if rfls else "BLOCK"
    return "BLOCK"


def verdict_to_audit_ok(verdict: str) -> bool:
    """Map verdict to the boolean ``audit_ok`` flag.

    Only READY counts as ``audit_ok=True``. CAUTION and BLOCK both
    yield ``audit_ok=False`` because the Marathon-Final-Bilanz
    aggregator's Henrik slot treats any non-OK as PARTIAL (CAUTION
    must surface to Mira-Hand for sign-off before live-smoke).
    """
    return verdict == "READY"


def extract_decision_summary(envelope: Any) -> dict:
    """Pull the decision summary fields the sign-off envelope embeds.

    All fields are optional; missing fields collapse to ``None`` or
    empty list. The function never raises -- malformed input collapses
    to a stub summary so the sign-off envelope is always well-formed.
    """
    if not isinstance(envelope, dict):
        return {
            "ready_for_live_smoke": None,
            "score_band_floor": None,
            "observed_band": None,
            "hard_block_reasons": [],
        }
    rfls = envelope.get("ready_for_live_smoke")
    if not isinstance(rfls, bool):
        rfls = None
    band_floor = envelope.get("score_band_floor")
    if not isinstance(band_floor, str):
        band_floor = None
    observed_band = envelope.get("observed_band")
    if not isinstance(observed_band, str):
        observed_band = None
    hard_blocks = envelope.get("hard_block_reasons")
    if not isinstance(hard_blocks, list):
        hard_blocks = []
    # Filter to strings only -- defensive against malformed reasons.
    hard_blocks = [r for r in hard_blocks if isinstance(r, str)]
    return {
        "ready_for_live_smoke": rfls,
        "score_band_floor": band_floor,
        "observed_band": observed_band,
        "hard_block_reasons": hard_blocks,
    }


def build_sign_off(
    *,
    welle: int,
    decision_envelope: Any,
    source_envelope_path: str,
    signed_off_at: str,
    component_override: str | None = None,
    notes: list[str] | None = None,
) -> dict:
    """Build a complete sign-off envelope from the decision envelope.

    Args:
        welle: 1..7.
        decision_envelope: parsed ``cutover-acceptance-decision.json``.
        source_envelope_path: provenance path string for the envelope.
        signed_off_at: ISO 8601 UTC timestamp string.
        component_override: optional component name; defaults to the
            canonical name from ``WELLE_TO_COMPONENT``.
        notes: optional list of free-form note strings.
    Returns:
        Sign-off envelope dict.
    """
    if welle not in WELLE_TO_COMPONENT:
        raise SystemExit(
            f"FATAL: welle index {welle} out of range (expected 1..7)"
        )
    component = component_override or WELLE_TO_COMPONENT[welle]
    verdict = derive_verdict(decision_envelope)
    audit_ok = verdict_to_audit_ok(verdict)
    decision_summary = extract_decision_summary(decision_envelope)
    out_notes = list(notes or [])
    if verdict == "CAUTION":
        out_notes.append(
            "CAUTION verdict: audit_ok=false to surface Mira-Hand "
            "sign-off requirement; not a hard BLOCK."
        )
    if decision_envelope is None:
        out_notes.append(
            "Source decision envelope was absent or empty; verdict "
            "defaulted to BLOCK (conservative)."
        )
    return {
        "schema": SCHEMA_VERSION,
        "welle": welle,
        "welle_slug": f"welle-{welle}",
        "component": component,
        "signed_off_by": "henrik",
        "audit_ok": audit_ok,
        "verdict": verdict,
        "signed_off_at": signed_off_at,
        "source_envelope": source_envelope_path,
        "decision_summary": decision_summary,
        "notes": out_notes,
    }


def _now_utc_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Emit a Welle-N sign-off envelope from a "
        "cutover-acceptance-decision envelope (Tag-51 / Tomas).",
    )
    parser.add_argument(
        "--welle",
        type=int,
        required=True,
        choices=range(1, 8),
        help="Welle index (1..7).",
    )
    parser.add_argument(
        "--decision-envelope",
        required=True,
        help="Path to the cutover-acceptance-decision JSON envelope.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to write the sign-off envelope (typically "
        "state/welle-N-sign-off.json).",
    )
    parser.add_argument(
        "--component",
        default=None,
        help="Override the canonical component name (optional).",
    )
    parser.add_argument(
        "--signed-off-at",
        default=None,
        help="ISO 8601 UTC timestamp (defaults to now).",
    )
    parser.add_argument(
        "--note",
        action="append",
        default=None,
        help="Optional free-form note (may be repeated).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 when the resulting verdict is BLOCK (default: "
        "always exit 0; CI gate is the upstream validation workflow's "
        "own exit code).",
    )
    args = parser.parse_args(argv)

    decision_path = pathlib.Path(args.decision_envelope)
    output_path = pathlib.Path(args.output)

    decision_envelope = _read_json(decision_path)
    signed_off_at = args.signed_off_at or _now_utc_iso()

    sign_off = build_sign_off(
        welle=args.welle,
        decision_envelope=decision_envelope,
        source_envelope_path=str(decision_path),
        signed_off_at=signed_off_at,
        component_override=args.component,
        notes=args.note,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(sign_off, f, indent=2, sort_keys=True)
        f.write("\n")

    print(
        f"[emit-welle-sign-off] welle={args.welle} verdict={sign_off['verdict']} "
        f"audit_ok={sign_off['audit_ok']} out={output_path}",
        file=sys.stderr,
    )

    if args.strict and sign_off["verdict"] == "BLOCK":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
