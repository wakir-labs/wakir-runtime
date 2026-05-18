#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Bilanz-Output-Schema-Validator (Tag-44, Noa SRE).

Validates the JSON output produced by
``scripts/observability/phase-3-final-bilanz-generator.py`` against a
versioned, embedded JSON-Schema (schema_version = "1.0.0"). Stdlib-only;
no third-party ``jsonschema`` dependency so the validator can run in the
sandbox lane as well as the production lane.

Why a dedicated validator
-------------------------

The generator writes ``reports/phase-3-marathon-bilanz.json`` as the
machine-readable bilanz rollup. Downstream consumers (Henrik Internal
Audit, the Phase-4 pre-substanz-plan generator, the GitHub Actions
artefact uploader) all read that JSON. Any drift in the shape -- new
key added without coordination, value type silently flipped, schema
version bumped without consumers being notified -- breaks the
contract.

This validator is the contract guard. It is exercised by the hermetic
test suite (every test that runs ``assemble_bilanz`` then validates
the result) and is callable as a CLI for ops-time double-checks.

Hermetic split
--------------

Everything above the ``# --- CLI boundary ---`` marker is
pure-function and stdlib-only. The CLI layer reads JSON from disk and
exits with a non-zero code on validation failure.

Anchors
-------

  * ADR-0065 (Phase-3c Cutover Plan)
  * ADR-0066 (Phase-3c 4W-Beschleunigung)
  * Tag-43 Noa PR #280 (Phase-3 Final Bilanz Generator)
  * Tag-44 Noa task brief (validation-mock-run + schema validation)

-- Noa
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Stdlib-only by design. Do not import third-party packages.


# --------------------------------------------------------------------
# Schema constants
# --------------------------------------------------------------------

SCHEMA_VERSION: str = "1.0.0"

# Welle order is the canonical Phase-3 ordering. The validator does
# not require every welle to be present in ``per_welle`` -- the
# generator emits empty per-welle records for unstarted wellen -- but
# every welle that is present must use one of these keys.
WELLE_KEYS: Tuple[str, ...] = (
    "welle-1-v907-verify",
    "welle-2-svid-workload-identity",
    "welle-3-bridge-audit-writer",
    "welle-4-state-backing",
    "welle-5-lifecycle-state-machine",
    "welle-6-subscribe-loop",
    "welle-7-recovery-workflow",
)

LATENCY_STATUS_VALUES: Tuple[str, ...] = (
    "OK",
    "WARN",
    "BREACH",
    "NO_DATA",
    "NO_BUDGET",
)

DRIFT_STATUS_VALUES: Tuple[str, ...] = ("OK", "WARN", "BREACH", "NO_DATA")


# --------------------------------------------------------------------
# Pure validation helpers
# --------------------------------------------------------------------


def _is_int_or_none(value: Any) -> bool:
    return value is None or (isinstance(value, int) and not isinstance(value, bool))


def _is_number_or_none(value: Any) -> bool:
    return value is None or (
        isinstance(value, (int, float)) and not isinstance(value, bool)
    )


def _is_str_or_none(value: Any) -> bool:
    return value is None or isinstance(value, str)


def _validate_executive_summary(
    exe: Any, errors: List[str], path: str = "executive_summary"
) -> None:
    if not isinstance(exe, dict):
        errors.append(f"{path}: expected dict, got {type(exe).__name__}")
        return

    required_keys = {
        "wellen_total": int,
        "wellen_with_sign_off": int,
        "marathon_last_update": str,
        "aggregator_runs_total": int,
        "drift_status_counts": dict,
        "latency_status_counts": dict,
        "complete_marker_is_complete": bool,
        "audit_aggregate_ok": bool,
    }
    for key, expected_type in required_keys.items():
        if key not in exe:
            errors.append(f"{path}.{key}: missing")
            continue
        if expected_type is int and not isinstance(exe[key], int):
            errors.append(
                f"{path}.{key}: expected int, got {type(exe[key]).__name__}"
            )
        elif expected_type is bool and not isinstance(exe[key], bool):
            errors.append(
                f"{path}.{key}: expected bool, got {type(exe[key]).__name__}"
            )
        elif expected_type is str and not isinstance(exe[key], str):
            errors.append(
                f"{path}.{key}: expected str, got {type(exe[key]).__name__}"
            )
        elif expected_type is dict and not isinstance(exe[key], dict):
            errors.append(
                f"{path}.{key}: expected dict, got {type(exe[key]).__name__}"
            )

    # aggregator_failure_rate is float-or-None.
    if "aggregator_failure_rate" not in exe:
        errors.append(f"{path}.aggregator_failure_rate: missing")
    elif not _is_number_or_none(exe["aggregator_failure_rate"]):
        errors.append(
            f"{path}.aggregator_failure_rate: expected number or None"
        )

    # Drift status counts: every key must be a known status, value must
    # be a non-negative int.
    if isinstance(exe.get("drift_status_counts"), dict):
        for st, count in exe["drift_status_counts"].items():
            if st not in DRIFT_STATUS_VALUES:
                errors.append(
                    f"{path}.drift_status_counts: unknown status {st!r}"
                )
            if not isinstance(count, int) or count < 0:
                errors.append(
                    f"{path}.drift_status_counts.{st}: expected non-negative int"
                )

    if isinstance(exe.get("latency_status_counts"), dict):
        for st, count in exe["latency_status_counts"].items():
            if st not in LATENCY_STATUS_VALUES:
                errors.append(
                    f"{path}.latency_status_counts: unknown status {st!r}"
                )
            if not isinstance(count, int) or count < 0:
                errors.append(
                    f"{path}.latency_status_counts.{st}: expected non-negative int"
                )


def _validate_per_welle(
    per_welle: Any, errors: List[str], path: str = "per_welle"
) -> None:
    if not isinstance(per_welle, dict):
        errors.append(f"{path}: expected dict, got {type(per_welle).__name__}")
        return

    for wid, entry in per_welle.items():
        if wid not in WELLE_KEYS:
            errors.append(f"{path}: unknown welle-id {wid!r}")
            continue
        if not isinstance(entry, dict):
            errors.append(
                f"{path}.{wid}: expected dict, got {type(entry).__name__}"
            )
            continue
        for sub in ("short", "marathon", "backend_snapshots", "drift",
                    "latency_status", "latency_budget_ms"):
            if sub not in entry:
                errors.append(f"{path}.{wid}.{sub}: missing")
        # latency_status must be a known value.
        if "latency_status" in entry and entry["latency_status"] not in LATENCY_STATUS_VALUES:
            errors.append(
                f"{path}.{wid}.latency_status: unknown value "
                f"{entry['latency_status']!r}"
            )
        # latency_budget_ms must be a positive int.
        if "latency_budget_ms" in entry and (
            not isinstance(entry["latency_budget_ms"], int)
            or entry["latency_budget_ms"] <= 0
        ):
            errors.append(
                f"{path}.{wid}.latency_budget_ms: expected positive int"
            )
        # Marathon sub-section shape.
        marathon = entry.get("marathon")
        if isinstance(marathon, dict):
            for key in ("cutover_runs_total", "cutover_runs_rust",
                        "cutover_runs_python_fallback",
                        "decision_latency_ms_n"):
                if key in marathon and not isinstance(marathon[key], int):
                    errors.append(
                        f"{path}.{wid}.marathon.{key}: expected int"
                    )
            for key in ("rust_share", "decision_latency_ms_p50",
                        "decision_latency_ms_p95",
                        "decision_latency_ms_p99"):
                if key in marathon and not _is_number_or_none(marathon[key]):
                    errors.append(
                        f"{path}.{wid}.marathon.{key}: expected number or None"
                    )
        # Drift sub-section shape.
        drift = entry.get("drift")
        if isinstance(drift, dict):
            if "drift_status" in drift and drift["drift_status"] not in DRIFT_STATUS_VALUES:
                errors.append(
                    f"{path}.{wid}.drift.drift_status: unknown value "
                    f"{drift['drift_status']!r}"
                )


def _validate_aggregator_rollup(
    rollup: Any, errors: List[str], path: str = "aggregator_history_rollup"
) -> None:
    if not isinstance(rollup, dict):
        errors.append(f"{path}: expected dict, got {type(rollup).__name__}")
        return
    for key in ("runs_total", "runs_success", "runs_failure"):
        if key not in rollup:
            errors.append(f"{path}.{key}: missing")
        elif not isinstance(rollup[key], int) or rollup[key] < 0:
            errors.append(f"{path}.{key}: expected non-negative int")
    for key in ("failure_rate", "wait_loop_p50_s", "wait_loop_p95_s",
                "wait_loop_p99_s"):
        if key not in rollup:
            errors.append(f"{path}.{key}: missing")
        elif not _is_number_or_none(rollup[key]):
            errors.append(f"{path}.{key}: expected number or None")
    buckets = rollup.get("sub_workflow_failure_buckets")
    if buckets is None:
        errors.append(f"{path}.sub_workflow_failure_buckets: missing")
    elif not isinstance(buckets, dict):
        errors.append(f"{path}.sub_workflow_failure_buckets: expected dict")
    else:
        for sw, cnt in buckets.items():
            if not isinstance(sw, str):
                errors.append(
                    f"{path}.sub_workflow_failure_buckets: key {sw!r} not str"
                )
            if not isinstance(cnt, int) or cnt < 0:
                errors.append(
                    f"{path}.sub_workflow_failure_buckets.{sw}: "
                    "expected non-negative int"
                )


def _validate_complete_marker_section(
    cm: Any, errors: List[str], path: str = "complete_marker_validation"
) -> None:
    if not isinstance(cm, dict):
        errors.append(f"{path}: expected dict, got {type(cm).__name__}")
        return
    for key in ("present", "is_complete"):
        if key not in cm:
            errors.append(f"{path}.{key}: missing")
        elif not isinstance(cm[key], bool):
            errors.append(f"{path}.{key}: expected bool")
    if "validation_errors" not in cm:
        errors.append(f"{path}.validation_errors: missing")
    elif not isinstance(cm["validation_errors"], list):
        errors.append(f"{path}.validation_errors: expected list")
    else:
        for i, e in enumerate(cm["validation_errors"]):
            if not isinstance(e, str):
                errors.append(
                    f"{path}.validation_errors[{i}]: expected str"
                )


def _validate_audit_aggregate(
    aud: Any, errors: List[str], path: str = "audit_aggregate"
) -> None:
    if not isinstance(aud, dict):
        errors.append(f"{path}: expected dict, got {type(aud).__name__}")
        return
    for key in ("aggregate_audit_ok",):
        if key not in aud:
            errors.append(f"{path}.{key}: missing")
        elif not isinstance(aud[key], bool):
            errors.append(f"{path}.{key}: expected bool")
    for key in ("total_findings", "total_exceptions"):
        if key not in aud:
            errors.append(f"{path}.{key}: missing")
        elif not isinstance(aud[key], int) or aud[key] < 0:
            errors.append(f"{path}.{key}: expected non-negative int")
    if "missing_sign_offs" not in aud:
        errors.append(f"{path}.missing_sign_offs: missing")
    elif not isinstance(aud["missing_sign_offs"], list):
        errors.append(f"{path}.missing_sign_offs: expected list")
    if "by_welle" not in aud:
        errors.append(f"{path}.by_welle: missing")
    elif not isinstance(aud["by_welle"], dict):
        errors.append(f"{path}.by_welle: expected dict")


def _validate_followups(
    items: Any, errors: List[str], path: str = "phase_4_followups"
) -> None:
    if not isinstance(items, list):
        errors.append(f"{path}: expected list, got {type(items).__name__}")
        return
    if not items:
        errors.append(
            f"{path}: must be non-empty (generator emits no-followups placeholder)"
        )
    for i, item in enumerate(items):
        if not isinstance(item, str):
            errors.append(f"{path}[{i}]: expected str")


def validate_bilanz_dict(bilanz: Any) -> List[str]:
    """Validate a parsed bilanz JSON dict.

    Returns a list of error strings. Empty list means valid.
    """
    errors: List[str] = []

    if not isinstance(bilanz, dict):
        errors.append(f"root: expected dict, got {type(bilanz).__name__}")
        return errors

    # Top-level required keys.
    required_top = {
        "schema_version": str,
        "generated_at": str,
        "executive_summary": dict,
        "per_welle": dict,
        "aggregator_history_rollup": dict,
        "complete_marker_validation": dict,
        "audit_aggregate": dict,
        "phase_4_followups": list,
    }
    for key, expected_type in required_top.items():
        if key not in bilanz:
            errors.append(f"root.{key}: missing")
            continue
        if expected_type is dict and not isinstance(bilanz[key], dict):
            errors.append(f"root.{key}: expected dict")
        elif expected_type is list and not isinstance(bilanz[key], list):
            errors.append(f"root.{key}: expected list")
        elif expected_type is str and not isinstance(bilanz[key], str):
            errors.append(f"root.{key}: expected str")

    # Schema-version pin: validator only knows version 1.x.
    if isinstance(bilanz.get("schema_version"), str):
        major = bilanz["schema_version"].split(".")[0]
        if major != "1":
            errors.append(
                f"root.schema_version: unsupported major version "
                f"{bilanz['schema_version']!r} (validator handles 1.x)"
            )

    # Generated-at must look ISO-8601-ish (cheap check, not full parse).
    if isinstance(bilanz.get("generated_at"), str):
        gen = bilanz["generated_at"]
        if "T" not in gen or not (gen.endswith("Z") or "+" in gen):
            errors.append(
                f"root.generated_at: not ISO-8601-shaped: {gen!r}"
            )

    # Drill into sub-sections.
    if isinstance(bilanz.get("executive_summary"), dict):
        _validate_executive_summary(bilanz["executive_summary"], errors)
    if isinstance(bilanz.get("per_welle"), dict):
        _validate_per_welle(bilanz["per_welle"], errors)
    if isinstance(bilanz.get("aggregator_history_rollup"), dict):
        _validate_aggregator_rollup(bilanz["aggregator_history_rollup"], errors)
    if isinstance(bilanz.get("complete_marker_validation"), dict):
        _validate_complete_marker_section(
            bilanz["complete_marker_validation"], errors
        )
    if isinstance(bilanz.get("audit_aggregate"), dict):
        _validate_audit_aggregate(bilanz["audit_aggregate"], errors)
    if isinstance(bilanz.get("phase_4_followups"), list):
        _validate_followups(bilanz["phase_4_followups"], errors)

    return errors


# --------------------------------------------------------------------
# CLI boundary
# --------------------------------------------------------------------


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bilanz-output-schema-validator",
        description=(
            "Validate a Phase-3-Marathon-Bilanz JSON file against the "
            f"schema version {SCHEMA_VERSION}."
        ),
    )
    parser.add_argument(
        "path",
        help="Path to bilanz JSON file (typically reports/phase-3-marathon-bilanz.json).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress success output; only print on failure.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(list(argv) if argv is not None else sys.argv[1:])

    try:
        with open(args.path, "r", encoding="utf-8") as fh:
            bilanz = json.load(fh)
    except FileNotFoundError:
        print(f"ERROR: bilanz file missing: {args.path}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(
            f"ERROR: invalid JSON in {args.path}: {exc}",
            file=sys.stderr,
        )
        return 2

    errors = validate_bilanz_dict(bilanz)
    if errors:
        print(
            f"FAIL: bilanz {args.path} failed schema validation "
            f"(version {SCHEMA_VERSION}):",
            file=sys.stderr,
        )
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    if not args.quiet:
        print(
            f"OK: bilanz {args.path} matches schema version {SCHEMA_VERSION}.",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
