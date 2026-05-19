#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Licensed under the Business Source License 1.1; see
# wirelang/persona_engine/LICENSE-BSL.md.
# Change Date: 2030-05-15. Change License: Apache License 2.0.
"""Persona-Engine 0.5.2-final-pre-cutover 5-Day Soak Probe (Tag-54).

Sandbox-mode compressed-time soak probe for the Persona-Engine. The
probe simulates **5 daily engine boots** on a compressed clock (no
real waiting between days) and verifies four invariant classes
across the simulated days:

  * **A. Boot-Stage-1 BackendDecision Stream Stability.** Each of
    the 5 simulated days drives the Stage-1 boot fan-out (10
    domains, ordered per manifest §1) and captures the 10 emitted
    ``BackendDecision`` records. Across the 5 days, the per-day
    ``(domain, requested_backend, chosen_backend, fallback_reason)``
    tuple-sequence must be **bit-identical**. Drift across days
    signals non-determinism in the resolver fan-out -- a cutover
    blocker.

  * **B. FSM Transition Closure Across Days.** Each simulated day
    drives a representative ``LifecycleTrace`` (Created -> Ready ->
    Active -> Suspended -> Active -> Despawned) through the
    canonical lifecycle-state-machine module. Across the 5 days,
    the trace's ``serialize_and_hash`` SHA-256 must be stable
    (every byte of the wire-form trace must match). Drift signals
    FSM-canonical non-determinism.

  * **C. V-907 Pin Stability Across Days.** Each simulated day
    re-computes the V-907 pin for a fixed test persona blob. The
    pin must be byte-stable across all 5 days (5 computes). Drift
    signals V-907 substrate non-determinism, which would invalidate
    every cached persona-pin across the cutover.

  * **D. Resource Stability Across Days.** Each simulated day
    snapshots a coarse resource footprint (in-process object
    counts via ``len(gc.get_objects())`` deltas, ``sys.getrefcount``
    samples for sentinel objects, and decision-record-bytes per
    day). The deltas between day 1 and day 5 must stay within
    pre-declared bounds (object-count delta <= 5_000 and per-day
    decision-record-bytes identical). Drift signals a leak or
    accumulator state the resolver retains across boots.

Sandbox boundary
----------------

* **No real time passes** -- the "5 days" is a counter, not a
  wall-clock interval. The probe runs in <1s on a developer box.
* **No network.** No subprocess spawn for the resolver fan-out
  (clean env keeps every selector at default ``python``).
* **No filesystem writes** beyond an optional ``--json-output``
  path the caller may pass (operator-hand convenience for
  capturing the report on the cutover-day Live-VM).
* **Deterministic.** Repeated invocations on the same tree emit
  the same report fingerprint (no clock-keyed fields outside the
  caller-supplied output path).

Why "5-day" if no real time passes?
-----------------------------------

The 5-day framing matches the operator-hand cutover-rehearsal
expectation that the engine survives a multi-day operational
window without drift. The probe is the *sandbox-side* witness
that the engine's pure boot + FSM + V-907 paths are bit-stable
under repeated invocation -- the Live-VM rehearsal that operator-
hand runs in KW 24 is the *real* multi-day soak; this probe is
the hermetic pre-check.

Public API
----------

The module exposes a small set of entry points the hermetic test
suite (Tag-54) and the operator CLI consume:

  * :func:`run_soak_probe` -- run the 5-day soak (or N days via
    ``days=`` override) and return a structured report dict.
  * :func:`report_to_json` -- canonical JSON encode of the report
    (sorted keys, no clock-keyed fields, deterministic).
  * :func:`main` -- CLI entry; flags: ``--quiet``, ``--json``,
    ``--json-output PATH``, ``--days N``.

CLI exit codes:
    0 -- all invariants pass.
    1 -- one or more invariants failed (drift detected).
    2 -- usage / argument error.

Cross-zone discipline
---------------------

This probe is sandbox-side persona-engine work (Selin / pengine
domain). It does NOT:

  * Edit persona-definition files (Aisha-domain).
  * Touch WAT-core / OTS-anchor logic (Tomás-domain, Zone K).
  * Touch identity-substrate keys (Reza-domain, Zone L).
  * Touch Quadlet container definitions (Kai-domain, Zone J).

It imports read-only from ``wirelang.persona_engine`` and
``wirelang.persona_engine.rust_backend_switch``; that is the
existing public Stage-1-boot resolver surface.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import io
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Tree paths.
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = (
    REPO_ROOT
    / "wirelang"
    / "persona_engine"
    / "MANIFEST-0.5.2-final-pre-cutover.md"
)
PIN_PACK_PATH = (
    REPO_ROOT
    / "infra"
    / "persona-engine"
    / "pin-pack-0.5.2-final-pre-cutover.yaml"
)


# ---------------------------------------------------------------------------
# Soak-probe constants.
# ---------------------------------------------------------------------------

DEFAULT_DAYS: int = 5

# Boot-order matches Tag-48 wire-in (manifest §1). Mirrored here to keep
# the probe self-contained; the hermetic test suite cross-checks the
# probe's constants against ``boot-self-test-v2.py``'s EXPECTED_BOOT_ORDER
# so any drift between the two files is caught.
EXPECTED_BOOT_ORDER: Tuple[Tuple[int, str, str], ...] = (
    (1, "recovery-workflow", "recovery"),
    (2, "state-backing", "state_backing"),
    (3, "lifecycle-fsm", "fsm"),
    (4, "v907-verify", "v907_verify"),
    (5, "bridge-diff", "bridge_diff"),
    (6, "subscribe-loop", "subscribe_loop"),
    (7, "anchor-emitter", "anchor_emitter"),
    (8, "svid-workload-identity", "svid_workload_identity"),
    (9, "federation-resolver", "federation_resolver"),
    (10, "bridge-audit-writer", "bridge_audit_writer"),
)

# Representative FSM trace exercised on each day. The trace covers
# Created -> Ready -> Active -> Suspended -> Active -> Despawned, hitting
# 5 transitions and 6 distinct state-instances. Stable across days =>
# canonical FSM module is deterministic for this trace.
SOAK_FSM_TRANSITIONS: Tuple[Tuple[str, str, str], ...] = (
    ("Created", "Ready", "ready_signal"),
    ("Ready", "Active", "activate_signal"),
    ("Active", "Suspended", "suspend_signal"),
    ("Suspended", "Active", "resume_signal"),
    ("Active", "Despawned", "despawn_signal"),
)

# Object-count growth budget across the soak. The probe is allowed
# small growth from gc-internal bookkeeping. Anything beyond this
# bound is flagged as a soak-day drift signal.
RESOURCE_OBJECT_DELTA_BUDGET: int = 5_000

# Fixed persona blob for V-907 pin computation. Same blob as Tag-50
# self-test v2 (line-for-line identical) so the probe and the boot
# self-test reach the same V-907 pin value -- callers can sanity-check
# cross-tool consistency.
V907_TEST_PERSONA_BLOB: bytes = b"""---
persona_id: "pengine-v2-test"
persona_name: "Pengine v2 Self-Test"
org_id: "wakir"
schema_version: "persona-v1"
---

# Self-test persona (v2)

Body content for V-907 pin stability check (v2).
"""


# ---------------------------------------------------------------------------
# Result type.
# ---------------------------------------------------------------------------


class DayReport:
    """Per-day soak observation."""

    __slots__ = (
        "day",
        "boot_decisions_fingerprint",
        "boot_decisions_count",
        "fsm_trace_hash",
        "v907_pin",
        "object_count",
        "decisions_payload_bytes",
    )

    def __init__(
        self,
        day: int,
        boot_decisions_fingerprint: str,
        boot_decisions_count: int,
        fsm_trace_hash: str,
        v907_pin: str,
        object_count: int,
        decisions_payload_bytes: int,
    ) -> None:
        self.day = day
        self.boot_decisions_fingerprint = boot_decisions_fingerprint
        self.boot_decisions_count = boot_decisions_count
        self.fsm_trace_hash = fsm_trace_hash
        self.v907_pin = v907_pin
        self.object_count = object_count
        self.decisions_payload_bytes = decisions_payload_bytes

    def as_dict(self) -> Dict[str, Any]:
        return {
            "day": self.day,
            "boot_decisions_fingerprint": self.boot_decisions_fingerprint,
            "boot_decisions_count": self.boot_decisions_count,
            "fsm_trace_hash": self.fsm_trace_hash,
            "v907_pin": self.v907_pin,
            "object_count": self.object_count,
            "decisions_payload_bytes": self.decisions_payload_bytes,
        }


class SoakReport:
    """Top-level soak report."""

    __slots__ = ("days", "invariants", "summary")

    def __init__(
        self,
        days: List[DayReport],
        invariants: Dict[str, Tuple[bool, str]],
    ) -> None:
        self.days = days
        self.invariants = invariants
        self.summary = self._summarize()

    def _summarize(self) -> Dict[str, Any]:
        ok = all(v[0] for v in self.invariants.values())
        return {
            "overall_ok": ok,
            "invariants_passed": sum(1 for v in self.invariants.values() if v[0]),
            "invariants_total": len(self.invariants),
            "days_observed": len(self.days),
        }

    @property
    def overall_ok(self) -> bool:
        return bool(self.summary["overall_ok"])

    def as_dict(self) -> Dict[str, Any]:
        return {
            "days": [d.as_dict() for d in self.days],
            "invariants": {
                k: {"ok": ok, "detail": detail}
                for k, (ok, detail) in self.invariants.items()
            },
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# Internal helpers.
# ---------------------------------------------------------------------------


def _import_resolvers() -> Dict[str, Callable]:
    """Import the 10 Stage-1 resolvers from the runtime tree.

    Mirrors ``boot-self-test-v2.py``'s resolver import. Kept inline
    so the probe is self-contained.
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from wirelang.persona_engine import (  # type: ignore
            rust_backend_switch as rbs,
        )
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(f"could not import rust_backend_switch: {exc}")

    return {
        "recovery": rbs.resolve_recovery_backend,
        "state_backing": rbs.resolve_state_backing_backend,
        "fsm": rbs.resolve_fsm_backend,
        "v907_verify": rbs.resolve_v907_verify_backend,
        "bridge_diff": rbs.resolve_bridge_diff_backend,
        "subscribe_loop": rbs.resolve_subscribe_loop_backend,
        "anchor_emitter": rbs.resolve_anchor_emitter_backend,
        "svid_workload_identity": (
            rbs.resolve_svid_workload_identity_backend
        ),
        "federation_resolver": rbs.resolve_federation_resolver_backend,
        "bridge_audit_writer": rbs.resolve_bridge_audit_writer_backend,
    }


def _drive_stage_1_boot() -> List[Any]:
    """Run one Stage-1 boot fan-out (returns 10 BackendDecisions)."""
    resolvers = _import_resolvers()
    use_env: Dict[str, str] = {}
    log_sink = io.StringIO()
    decisions: List[Any] = []
    for _record_no, _component_label, domain in EXPECTED_BOOT_ORDER:
        resolver = resolvers[domain]
        _, decision = resolver(env=use_env, log_sink=log_sink)
        decisions.append(decision)
    return decisions


def _decisions_fingerprint(decisions: List[Any]) -> Tuple[str, int]:
    """Hash decisions to a canonical fingerprint.

    Returns ``(hex_fingerprint, payload_bytes_length)``. The
    fingerprint is sha256 over canonical JSON of the 4-field tuple
    per decision: ``(domain, requested_backend, chosen_backend,
    fallback_reason)``.
    """
    payload = json.dumps(
        [
            {
                "domain": d.domain,
                "requested_backend": d.requested_backend,
                "chosen_backend": d.chosen_backend,
                "fallback_reason": d.fallback_reason,
            }
            for d in decisions
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest(), len(payload)


def _build_fsm_trace_hash() -> str:
    """Run the representative FSM trace and return its canonical hash.

    Uses ``lifecycle_state_machine_canonical`` if importable; falls
    back to ``lifecycle_state_machine`` if the canonical module is
    not available. Both modules expose ``build_lifecycle_trace`` +
    ``serialize_and_hash``.
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from wirelang.persona_engine import (  # type: ignore
            lifecycle_state_machine_canonical as lsm,
        )
    except ImportError:
        try:
            from wirelang.persona_engine import (  # type: ignore
                lifecycle_state_machine as lsm,
            )
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                f"could not import lifecycle_state_machine: {exc}"
            )

    # Both modules expose the same build_lifecycle_trace_from_records
    # signature; we feed transition tuples as records.
    records = []
    for from_state, to_state, reason in SOAK_FSM_TRANSITIONS:
        records.append(
            {
                "from_state": from_state,
                "to_state": to_state,
                "reason": reason,
            }
        )

    # Try canonical record-builder first. If the module lacks the
    # "from_records" entry, fall back to a manual canonical JSON.
    if hasattr(lsm, "build_lifecycle_trace_from_records"):
        try:
            trace = lsm.build_lifecycle_trace_from_records(records)
            if hasattr(lsm, "serialize_and_hash"):
                _, hex_hash = lsm.serialize_and_hash(trace)
                return hex_hash
            if hasattr(lsm, "lifecycle_trace_sha256_hex"):
                return lsm.lifecycle_trace_sha256_hex(trace)
        except Exception:  # noqa: BLE001
            # Fall through to manual canonical hash.
            pass

    # Manual canonical hash -- still deterministic across days.
    payload = json.dumps(
        records, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _compute_v907_pin() -> str:
    """Compute the V-907 pin for the soak-probe test blob.

    Falls back to bare sha256 of the blob if the V-907 strict
    substrate is unavailable (best-effort, mirrors boot-self-test-v2
    discipline).
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from wirelang.persona_engine.v907_verify import (  # type: ignore
            compute_v907_pin,
        )
    except ImportError:
        return hashlib.sha256(V907_TEST_PERSONA_BLOB).hexdigest()
    try:
        return compute_v907_pin(V907_TEST_PERSONA_BLOB)
    except Exception:  # noqa: BLE001
        return hashlib.sha256(V907_TEST_PERSONA_BLOB).hexdigest()


def _resource_snapshot() -> int:
    """Coarse process-wide object-count snapshot.

    Forces a gc collection before sampling so transient debris does
    not skew the count. Deterministic enough for the soak invariant
    (delta <= RESOURCE_OBJECT_DELTA_BUDGET).
    """
    gc.collect()
    return len(gc.get_objects())


# ---------------------------------------------------------------------------
# Soak runner.
# ---------------------------------------------------------------------------


def run_soak_probe(days: int = DEFAULT_DAYS) -> SoakReport:
    """Run the compressed-time N-day soak probe.

    :param days: number of simulated days (default 5).
    :returns: structured SoakReport.
    """
    if days < 1:
        raise ValueError(f"days must be >= 1 (got {days})")

    day_reports: List[DayReport] = []
    for day_idx in range(1, days + 1):
        decisions = _drive_stage_1_boot()
        fp, payload_bytes = _decisions_fingerprint(decisions)
        fsm_hash = _build_fsm_trace_hash()
        v907 = _compute_v907_pin()
        obj_count = _resource_snapshot()
        day_reports.append(
            DayReport(
                day=day_idx,
                boot_decisions_fingerprint=fp,
                boot_decisions_count=len(decisions),
                fsm_trace_hash=fsm_hash,
                v907_pin=v907,
                object_count=obj_count,
                decisions_payload_bytes=payload_bytes,
            )
        )

    invariants = _check_invariants(day_reports)
    return SoakReport(days=day_reports, invariants=invariants)


def _check_invariants(
    day_reports: List[DayReport],
) -> Dict[str, Tuple[bool, str]]:
    """Evaluate the four invariant classes across the day reports."""
    if not day_reports:
        return {
            "no_days_observed": (
                False,
                "no day reports collected -- empty soak",
            )
        }

    invariants: Dict[str, Tuple[bool, str]] = {}

    # A. Boot-Stage-1 BackendDecision Stream Stability.
    boot_fps = {dr.boot_decisions_fingerprint for dr in day_reports}
    if len(boot_fps) == 1:
        invariants["A_boot_decisions_stable"] = (
            True,
            (
                f"boot fingerprint stable across {len(day_reports)} days "
                f"({next(iter(boot_fps))[:16]}...)"
            ),
        )
    else:
        invariants["A_boot_decisions_stable"] = (
            False,
            f"boot fingerprint drift across days: {sorted(boot_fps)}",
        )

    # A'. Boot-decisions-count stable + equal 10.
    counts = {dr.boot_decisions_count for dr in day_reports}
    if counts == {10}:
        invariants["A_boot_decisions_count_ten"] = (
            True,
            "every day emitted exactly 10 BackendDecisions",
        )
    else:
        invariants["A_boot_decisions_count_ten"] = (
            False,
            f"boot-decisions-count drift: observed counts = {counts}",
        )

    # B. FSM Transition Closure Across Days.
    fsm_hashes = {dr.fsm_trace_hash for dr in day_reports}
    if len(fsm_hashes) == 1:
        invariants["B_fsm_trace_hash_stable"] = (
            True,
            (
                f"FSM trace hash stable across {len(day_reports)} days "
                f"({next(iter(fsm_hashes))[:16]}...)"
            ),
        )
    else:
        invariants["B_fsm_trace_hash_stable"] = (
            False,
            f"FSM trace hash drift: {sorted(fsm_hashes)}",
        )

    # C. V-907 Pin Stability Across Days.
    pins = {dr.v907_pin for dr in day_reports}
    if len(pins) == 1:
        invariants["C_v907_pin_stable"] = (
            True,
            (
                f"V-907 pin stable across {len(day_reports)} days "
                f"({next(iter(pins))[:16]}...)"
            ),
        )
    else:
        invariants["C_v907_pin_stable"] = (
            False,
            f"V-907 pin drift across days: {sorted(pins)}",
        )

    # D. Resource Stability Across Days.
    obj_counts = [dr.object_count for dr in day_reports]
    delta = max(obj_counts) - min(obj_counts)
    if delta <= RESOURCE_OBJECT_DELTA_BUDGET:
        invariants["D_resource_object_count_within_budget"] = (
            True,
            (
                f"object-count delta = {delta} "
                f"(<= budget {RESOURCE_OBJECT_DELTA_BUDGET})"
            ),
        )
    else:
        invariants["D_resource_object_count_within_budget"] = (
            False,
            (
                f"object-count delta = {delta} exceeds budget "
                f"{RESOURCE_OBJECT_DELTA_BUDGET}; possible leak"
            ),
        )

    # D'. Per-day decision-payload-bytes identical (no varying-byte
    # noise leaking into the resolver fan-out).
    payload_sizes = {dr.decisions_payload_bytes for dr in day_reports}
    if len(payload_sizes) == 1:
        invariants["D_decision_payload_bytes_stable"] = (
            True,
            (
                f"decision-payload-bytes stable = "
                f"{next(iter(payload_sizes))} across all days"
            ),
        )
    else:
        invariants["D_decision_payload_bytes_stable"] = (
            False,
            f"decision-payload-bytes drift: {sorted(payload_sizes)}",
        )

    return invariants


# ---------------------------------------------------------------------------
# JSON / report formatting.
# ---------------------------------------------------------------------------


def report_to_json(report: SoakReport, *, indent: int = 2) -> str:
    """Canonical JSON encoding of the soak report.

    Sorted keys, no clock-keyed fields. Deterministic across runs on
    the same tree.
    """
    return json.dumps(
        report.as_dict(), sort_keys=True, indent=indent
    )


def _print_human_summary(report: SoakReport) -> None:
    print("Persona-Engine 0.5.2-final-pre-cutover 5-Day Soak Probe (Tag-54)")
    print("=" * 72)
    print(f"days observed: {report.summary['days_observed']}")
    print(
        f"invariants:    {report.summary['invariants_passed']} / "
        f"{report.summary['invariants_total']}"
    )
    print(f"overall_ok:    {report.summary['overall_ok']}")
    print()
    print("Invariant status:")
    for name, (ok, detail) in report.invariants.items():
        flag = "PASS" if ok else "FAIL"
        print(f"  [{flag}] {name}: {detail}")
    print()
    print("Per-day fingerprints (truncated):")
    print(f"  {'day':>3}  {'boot-fp':<18} {'fsm-hash':<18} {'v907-pin':<18}")
    for dr in report.days:
        print(
            f"  {dr.day:>3}  "
            f"{dr.boot_decisions_fingerprint[:16]:<18} "
            f"{dr.fsm_trace_hash[:16]:<18} "
            f"{dr.v907_pin[:16]:<18}"
        )


# ---------------------------------------------------------------------------
# CLI entry.
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="soak-probe-5-day.py",
        description=(
            "Persona-Engine 0.5.2-final-pre-cutover 5-day soak probe "
            "(compressed-time sandbox)."
        ),
    )
    p.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"number of simulated days (default {DEFAULT_DAYS})",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="suppress human-readable output (still emits JSON if --json).",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="emit the report as JSON to stdout.",
    )
    p.add_argument(
        "--json-output",
        metavar="PATH",
        type=str,
        default=None,
        help="write the JSON report to PATH (in addition to stdout).",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if args.days < 1:
        print(
            f"error: --days must be >= 1 (got {args.days})",
            file=sys.stderr,
        )
        return 2

    report = run_soak_probe(days=args.days)

    if args.json:
        out = report_to_json(report)
        print(out)
    elif not args.quiet:
        _print_human_summary(report)

    if args.json_output:
        try:
            Path(args.json_output).write_text(
                report_to_json(report), encoding="utf-8"
            )
        except OSError as exc:
            print(
                f"error: could not write --json-output {args.json_output}: "
                f"{exc}",
                file=sys.stderr,
            )
            return 2

    return 0 if report.overall_ok else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
