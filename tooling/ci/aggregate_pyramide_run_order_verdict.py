#!/usr/bin/env python3
"""Aggregate the 6-Layer Acceptance-Pyramide run-order verdict per
Welle and globally.

Tag-57 helper for `docs/quality-gates/pre-cutover-acceptance-run-order.md`.

The helper consumes per-layer outcome inputs (a JSON dict mapping
layer-stage keys to outcomes in {"GREEN","CAUTION","RED","SKIP"}) and
emits the per-Welle or Global verdict envelope per §7 of the doc.

This helper is stdlib-only (json, argparse, sys, typing). It is
designed to be invoked from CI but is also unit-testable in isolation.

Schema version: 1.0.0
Doc version: tag-57
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Dict, List, Optional, Tuple

SCHEMA_VERSION = "1.0.0"
DOC_VERSION = "tag-57"
DOC_ANCHOR = "docs/quality-gates/pre-cutover-acceptance-run-order.md"

VALID_OUTCOMES = frozenset({"GREEN", "CAUTION", "RED", "SKIP"})
VALID_VERDICTS = frozenset({"GREEN", "CAUTION", "RED"})

# Welle-N -> required layer-stage keys (Pre / Day / Post)
# Layer-stage key convention:
#   L1-smoke, L2-dryrun       (Pre, all wellen)
#   L4-full, L5-full, L6-full (Pre, Welle-1 only)
#   L4-smoke                  (Pre, Welle-N N>=2)
#   L6-smoke                  (Pre, Doppel-Welle entries: Welle-2,5,7)
#   L2-live, L2-shadow        (Day, all wellen)
#   L2-record-validation      (Post, all wellen)
#   L1-full, L3-full          (Post, Welle-7 only)
#   live-verify-gate          (Post, Welle-7 only)

DOPPEL_WELLE_ENTRIES = frozenset({2, 5, 7})


def required_layers_for_welle(welle_id: int) -> List[str]:
    """Return the list of layer-stage keys required for Welle-N.

    Order matches §7.1 of the doc.
    """
    if welle_id < 1 or welle_id > 7:
        raise ValueError(f"welle_id must be in 1..7, got {welle_id}")
    required: List[str] = []
    # Pre-Welle (all)
    required.append("L1-smoke")
    required.append("L2-dryrun")
    # Pre-Welle (Welle-1 marathon-entry)
    if welle_id == 1:
        required.extend(["L4-full", "L5-full", "L6-full"])
    else:
        required.append("L4-smoke")
    # Pre-Welle (Doppel-Welle entries)
    if welle_id in DOPPEL_WELLE_ENTRIES:
        required.append("L6-smoke")
    # Welle-Day
    required.extend(["L2-live", "L2-shadow"])
    # Post-Welle
    required.append("L2-record-validation")
    return required


def required_layers_for_global() -> List[str]:
    """Return the layer-stage keys required at Post-Welle-7 Global."""
    return ["L1-full", "L3-full", "live-verify-gate"]


def _validate_outcomes(outcomes: Dict[str, str]) -> None:
    for key, val in outcomes.items():
        if val not in VALID_OUTCOMES:
            raise ValueError(
                f"layer-outcome for {key!r} is {val!r}; must be one of {sorted(VALID_OUTCOMES)}"
            )


def _escalation_for_layer(layer_key: str, welle_id: Optional[int]) -> Tuple[str, str]:
    """Map a failing layer-stage to (escalation-target, reason).

    Mirrors §6 of the doc.
    """
    if layer_key == "L1-smoke":
        return ("Mira", "L1-smoke RED blocks marathon-entry / downstream wellen")
    if layer_key == "L2-dryrun":
        return ("Tomas", "L2-dryrun RED is operative; isolated per-Welle")
    if layer_key == "L4-smoke":
        return ("Mira", "L4-smoke RED indicates anti-pattern regression")
    if layer_key == "L4-full":
        return ("Mira+AR", "L4-full RED blocks marathon-entry")
    if layer_key == "L5-full":
        return ("Mira+Henrik", "L5-full RED indicates failure-mode coverage regression")
    if layer_key == "L6-full":
        return ("Mira+AR", "L6-full RED blocks marathon-entry; defence-in-depth regression")
    if layer_key == "L6-smoke":
        return ("Mira", "L6-smoke RED blocks Doppel-Welle entry")
    if layer_key == "L2-live":
        return ("Operator+Mira", "L2-live RED triggers rollback workflow")
    if layer_key == "L2-shadow":
        return ("Amara+Tomas", "L2-shadow RED indicates hermetic-CI substrate drift")
    if layer_key == "L2-record-validation":
        return ("Tomas", "L2-record-validation RED rejects per-Welle sign-off")
    if layer_key == "L1-full":
        return ("Mira+AR", "L1-full RED at Post-Welle-7 = Marathon failure")
    if layer_key == "L3-full":
        return ("Mira+AR", "L3-full RED at Post-Welle-7 = Marathon failure")
    if layer_key == "live-verify-gate":
        return ("Amara+Henrik", "Live-Verify-Gate drift is Zone-N substrate signal")
    return ("Mira", f"unknown layer-stage {layer_key} failed")


def compute_welle_verdict(
    welle_id: int, outcomes: Dict[str, str]
) -> Dict[str, object]:
    """Compute the per-Welle verdict envelope per §7.1.

    `outcomes` may include keys outside the required set; those are
    recorded but do not affect the verdict.
    """
    _validate_outcomes(outcomes)
    required = required_layers_for_welle(welle_id)
    layer_outcomes: Dict[str, str] = {}
    missing: List[str] = []
    failing: List[str] = []
    cautioning: List[str] = []
    for key in required:
        val = outcomes.get(key)
        if val is None:
            missing.append(key)
            layer_outcomes[key] = "MISSING"
        else:
            layer_outcomes[key] = val
            if val == "RED":
                failing.append(key)
            elif val == "CAUTION":
                cautioning.append(key)

    # Also record any extra outcomes the caller provided.
    for key, val in outcomes.items():
        if key not in layer_outcomes:
            layer_outcomes[key] = val

    if missing or failing:
        verdict = "RED"
        # Pick the first failure to set the escalation; missing
        # entries collapse to the same escalation as RED for that key.
        primary_failure = (failing + missing)[0]
        target, reason = _escalation_for_layer(primary_failure, welle_id)
        if missing and primary_failure in missing:
            reason = f"required layer-stage {primary_failure!r} missing"
        escalation = {"target": target, "reason": reason}
    elif cautioning:
        verdict = "CAUTION"
        # CAUTION special-case from §7.1: L2-shadow disagrees with
        # L2-live, or L4-smoke drift-flag. We just record the CAUTION
        # layers.
        escalation = {
            "target": "Amara",
            "reason": f"CAUTION on layer(s): {','.join(cautioning)}",
        }
    else:
        verdict = "GREEN"
        escalation = {"target": None, "reason": ""}

    return {
        "schema_version": SCHEMA_VERSION,
        "doc_version": DOC_VERSION,
        "welle_id": f"welle-{welle_id}",
        "verdict": verdict,
        "required_layers": required,
        "layer_outcomes": layer_outcomes,
        "escalation": escalation,
        "doc_anchor": DOC_ANCHOR,
    }


def compute_global_verdict(
    per_welle_verdicts: Dict[int, str],
    global_outcomes: Dict[str, str],
) -> Dict[str, object]:
    """Compute the Global verdict envelope per §7.2.

    `per_welle_verdicts` maps welle_id (1..7) to verdict string.
    `global_outcomes` maps the three Post-Welle-7 Global layer-stage
    keys ("L1-full", "L3-full", "live-verify-gate") to outcomes.
    """
    for wid, v in per_welle_verdicts.items():
        if wid < 1 or wid > 7:
            raise ValueError(f"welle_id must be 1..7, got {wid}")
        if v not in VALID_VERDICTS:
            raise ValueError(f"per-Welle verdict for {wid} is {v!r}; invalid")
    if set(per_welle_verdicts.keys()) != set(range(1, 8)):
        raise ValueError("per_welle_verdicts must cover all of welle 1..7")
    _validate_outcomes(global_outcomes)

    required = required_layers_for_global()
    layer_outcomes: Dict[str, str] = {}
    failing: List[str] = []
    cautioning: List[str] = []
    for key in required:
        val = global_outcomes.get(key)
        if val is None:
            layer_outcomes[key] = "MISSING"
            failing.append(key)
        else:
            layer_outcomes[key] = val
            if val == "RED":
                failing.append(key)
            elif val == "CAUTION":
                cautioning.append(key)

    any_welle_red = any(v == "RED" for v in per_welle_verdicts.values())
    any_welle_caution = any(v == "CAUTION" for v in per_welle_verdicts.values())

    l1 = global_outcomes.get("L1-full")
    l3 = global_outcomes.get("L3-full")
    lv = global_outcomes.get("live-verify-gate")

    if any_welle_red or l1 == "RED" or l1 is None or l3 == "RED" or l3 is None:
        verdict = "RED"
        target, reason = ("Mira+AR", "Global verdict RED; marker DOES NOT FIRE")
    elif l1 == "GREEN" and l3 == "GREEN" and lv == "GREEN" and not any_welle_caution:
        verdict = "GREEN"
        target, reason = (None, "")
    else:
        # All required green for marker, but Live-Verify-Gate CAUTION
        # or a per-Welle CAUTION present.
        verdict = "CAUTION"
        target, reason = (
            "Amara+Henrik",
            "Surface-1..5 cross-attestation drift or per-Welle CAUTION",
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "doc_version": DOC_VERSION,
        "welle_id": "global",
        "verdict": verdict,
        "required_layers": required,
        "layer_outcomes": layer_outcomes,
        "per_welle_verdicts": {f"welle-{k}": v for k, v in per_welle_verdicts.items()},
        "escalation": {"target": target, "reason": reason},
        "doc_anchor": DOC_ANCHOR,
    }


def _load_inputs(path: Optional[str]) -> Dict[str, object]:
    if path is None or path == "-":
        return json.load(sys.stdin)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate the 6-Layer Acceptance-Pyramide run-order verdict "
            "per Welle or globally (Tag-57)."
        )
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=["welle", "global"],
        help="welle: compute per-Welle verdict; global: compute Global Post-Welle-7 verdict.",
    )
    parser.add_argument(
        "--welle",
        type=int,
        default=None,
        help="Welle id (1..7) when --mode=welle.",
    )
    parser.add_argument(
        "--input",
        type=str,
        default="-",
        help="Path to JSON input (or '-' for stdin).",
    )
    args = parser.parse_args(argv)

    data = _load_inputs(args.input)
    if args.mode == "welle":
        if args.welle is None:
            parser.error("--welle required when --mode=welle")
        outcomes = data.get("layer_outcomes", {})
        if not isinstance(outcomes, dict):
            parser.error("input.layer_outcomes must be an object")
        envelope = compute_welle_verdict(args.welle, outcomes)
    else:
        per_welle = data.get("per_welle_verdicts", {})
        # Accept both "welle-N": V and N: V key-shapes.
        normalized: Dict[int, str] = {}
        for k, v in per_welle.items():
            if isinstance(k, int):
                normalized[k] = v
            elif isinstance(k, str):
                if k.startswith("welle-"):
                    normalized[int(k[len("welle-"):])] = v
                else:
                    normalized[int(k)] = v
        global_outcomes = data.get("layer_outcomes", {})
        envelope = compute_global_verdict(normalized, global_outcomes)
    json.dump(envelope, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
