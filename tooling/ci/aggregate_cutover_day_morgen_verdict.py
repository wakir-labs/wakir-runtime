#!/usr/bin/env python3
# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-64 Cutover-Day-Morgen Auto-Scheduler verdict aggregator (Selin).

The Tag-64 Cutover-Day-Morgen Auto-Scheduler reads the three
top-level pre-cutover-acceptance verdicts that the Phase-3c
marathon has converged on by Tag-63 and emits a single aggregated
``CUTOVER-DAY-MORGEN-READY`` / ``CUTOVER-DAY-MORGEN-CAUTION`` /
``CUTOVER-DAY-MORGEN-BLOCK`` verdict that operator-hand / AR-Hand
can read every cutover-week morning (KW-24..27 Mo-Fr 06:00 UTC).

Three top-level verdicts aggregated
-----------------------------------

* ``V1`` engine_composite
    Selin Tag-61/63 Persona-Engine Pre-Cutover-Final-Acceptance-
    Composite verdict. Reads the envelope schema emitted by
    ``tooling/ci/aggregate_persona_engine_pre_cutover_final.py``
    (workflow: ``persona-engine-pre-cutover-final-acceptance-
    composite.yml``). The envelope's ``verdict`` field is one of
    ``PRE-CUTOVER-READY`` (-> green), ``PRE-CUTOVER-DRIFT``
    (-> yellow), or ``PRE-CUTOVER-DEFECT`` (-> red).

* ``V2`` pyramide_composite
    Amara Tag-62 Pyramide-Acceptance Pre-Cutover Compositum
    verdict. Reads the envelope schema emitted by
    ``tooling/ci/aggregate_pyramide_acceptance_pre_cutover.py``
    (workflow: ``pyramide-acceptance-pre-cutover-compositum.yml``).
    The envelope's ``verdict`` field is one of
    ``ACCEPTANCE-PYRAMIDE-READY`` (-> green),
    ``ACCEPTANCE-PYRAMIDE-DRIFT`` (-> yellow), or
    ``ACCEPTANCE-PYRAMIDE-DEFECT`` (-> red).

* ``V3`` e2e_smoke
    Amara Tag-63 Pre-Cutover-Final-Acceptance E2E-Smoke verdict.
    Reads the envelope schema emitted by
    ``tooling/ci/aggregate_pre_cutover_e2e_smoke_verdict.py``
    (workflow: ``pre-cutover-final-acceptance-e2e-smoke.yml``).
    The envelope's ``verdict`` field is one of ``E2E-READY``
    (-> green), ``E2E-DRIFT`` (-> yellow), or ``E2E-DEFECT``
    (-> red).

Aggregated verdict
------------------

The Tag-64 decision rule mirrors the Tag-53 sanity-gate trinary:

* ``CUTOVER-DAY-MORGEN-READY`` -- all three top-level verdicts
  green. The cutover-day-morning read is clean; operator-hand
  / AR-Hand has full confidence to proceed with the day's
  cutover-acceptance work.
* ``CUTOVER-DAY-MORGEN-CAUTION`` -- at least one yellow, zero
  red. Operator-hand reads the per-substrate notes; degraded
  signal is not a blocker but the marathon-dashboard should
  surface the source.
* ``CUTOVER-DAY-MORGEN-BLOCK`` -- at least one red. Operator-
  hand pauses on the failing substrate before continuing.

Exit code
---------

Always ``0``. The verdict-envelope's ``verdict`` field carries
the signal; workflow-step decisioning is downstream of this
helper.

Window gating
-------------

The aggregator does NOT enforce the KW-24..27 cron window itself
(that is the workflow's cron-expression + the workflow_dispatch
override surface). The aggregator is hermetic over the three
input verdict envelopes and the optional ``--iso-week`` argument,
which it surfaces on the output envelope for marathon-dashboard
correlation only -- not for gating.

Hermetic envelope
-----------------

Stdlib only. No network, no NATS, no SPIRE, no gRPC. The three
input envelopes are read from disk paths supplied by the caller;
the aggregator does not attempt to fetch them via gh CLI or
GitHub API (that is the workflow's job).

Tag-65 notify-cascade extension
-------------------------------

The ``--emit-notify-cascade`` mode (Tag-65) writes a ntfy-shaped
audit-only JSON envelope when the aggregated verdict warrants
operator-hand attention. The cascade fires unconditionally on
BLOCK and conditionally on CAUTION (transition rule). READY and
stable-CAUTION emit a "suppressed" stub instead so the workflow
artifact-upload always has a deterministic file. The aggregator
NEVER performs an HTTP POST to ntfy.sh - that is operator-hand
territory per ADR-0034 sandbox-host-separation. See
``.github/workflows/cutover-day-morgen-notify-cascade.yml``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---- Substrate ordering --------------------------------------------------

# Canonical order: engine-composite -> pyramide-composite -> E2E-smoke.
# The auto-scheduler workflow exposes these as V1/V2/V3 envelope
# paths. The order is the same as the chronological order they
# emerged on the marathon (Tag-61 -> Tag-62 -> Tag-63).
SUBSTRATES: tuple[str, ...] = (
    "engine_composite",
    "pyramide_composite",
    "e2e_smoke",
)


# ---- Per-substrate verdict-to-status mapping -----------------------------

# Each input envelope emits a domain-specific verdict string. The
# Tag-64 aggregator normalises to a uniform trinary status so the
# decision rule below can be stated symmetrically.
ENGINE_VERDICT_MAP: dict[str, str] = {
    "PRE-CUTOVER-READY": "green",
    "PRE-CUTOVER-DRIFT": "yellow",
    "PRE-CUTOVER-DEFECT": "red",
}

PYRAMIDE_VERDICT_MAP: dict[str, str] = {
    "ACCEPTANCE-PYRAMIDE-READY": "green",
    "ACCEPTANCE-PYRAMIDE-DRIFT": "yellow",
    "ACCEPTANCE-PYRAMIDE-DEFECT": "red",
}

E2E_VERDICT_MAP: dict[str, str] = {
    "E2E-READY": "green",
    "E2E-DRIFT": "yellow",
    "E2E-DEFECT": "red",
}

SUBSTRATE_VERDICT_MAPS: dict[str, dict[str, str]] = {
    "engine_composite": ENGINE_VERDICT_MAP,
    "pyramide_composite": PYRAMIDE_VERDICT_MAP,
    "e2e_smoke": E2E_VERDICT_MAP,
}


VALID_STATUSES: frozenset[str] = frozenset({"green", "yellow", "red"})


# ---- Aggregated verdict constants ----------------------------------------

VERDICT_READY: str = "CUTOVER-DAY-MORGEN-READY"
VERDICT_CAUTION: str = "CUTOVER-DAY-MORGEN-CAUTION"
VERDICT_BLOCK: str = "CUTOVER-DAY-MORGEN-BLOCK"


# ---- Window-gating constants ---------------------------------------------

# Cutover-marathon window: KW-24 .. KW-27 in 2026 (Mo-Fr 06:00 UTC
# cron). The aggregator surfaces these on the envelope for the
# downstream notify-cascade; the workflow-cron is the actual gate.
CUTOVER_WINDOW_ISO_WEEKS: tuple[int, ...] = (24, 25, 26, 27)


# ---- Notify-cascade constants (Tag-65, audit-only) -----------------------

# The notify-cascade is the Tag-65 follow-up substrate that wires
# the Tag-64 verdict into Noa's ntfy-routing table. The cascade is
# AUDIT-ONLY: this aggregator emits a ntfy-shaped JSON envelope to
# disk; the workflow uploads it as an artifact; NO actual HTTPS POST
# to ntfy.sh happens at this stage. The audit-only boundary is per
# ADR-0034 sandbox-host-separation: only operator-hand fires the
# actual ntfy POST, after reviewing the audit-payload.
#
# Routing table (from Noa Tag-64 docs/observability/mira-notify-
# runbook.md + pre-mortem-failure-mode-notify-catalog.md):
#   * BLOCK   -> ntfy topic ``wakir-ar-hand-critical``, priority 5,
#                tags ``rotating_light``, ``cutover-day-morgen``
#   * CAUTION -> ntfy topic ``wakir-ar-hand``,          priority 4,
#                tags ``warning``,          ``cutover-day-morgen``
#   * READY   -> no notify-cascade fires (suppressed).
#
# Audit semantics:
#   * BLOCK fires every run (forensic trail; operator-hand reads).
#   * CAUTION fires only on transition (prev_verdict != CAUTION)
#     to avoid spamming Noa's notify-log during stable degraded
#     states.
#   * READY suppresses unconditionally.

NOTIFY_CASCADE_TOPIC_BLOCK: str = "wakir-ar-hand-critical"
NOTIFY_CASCADE_TOPIC_CAUTION: str = "wakir-ar-hand"

NOTIFY_CASCADE_PRIORITY_MAP: dict[str, int] = {
    VERDICT_BLOCK: 5,
    VERDICT_CAUTION: 4,
}

NOTIFY_CASCADE_TAGS_MAP: dict[str, list[str]] = {
    VERDICT_BLOCK: ["rotating_light", "cutover-day-morgen"],
    VERDICT_CAUTION: ["warning", "cutover-day-morgen"],
}

NOTIFY_CASCADE_KIND: str = "cutover-day-morgen-notify-cascade-payload"

# Audit-only marker. The workflow MUST NOT POST this payload to
# ntfy.sh; that is operator-hand territory.
NOTIFY_CASCADE_AUDIT_ONLY: bool = True


# ---- Helpers --------------------------------------------------------------


def _load_envelope(path: Path | None) -> dict[str, Any] | None:
    """Read a verdict-envelope JSON from disk.

    Returns ``None`` if the path is ``None`` or does not exist or
    cannot be parsed; the decision rule treats a missing envelope
    as a red signal on that substrate (block-on-missing).
    """
    if path is None:
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _normalise_status(
    substrate: str, envelope: Mapping[str, Any] | None
) -> tuple[str, str]:
    """Map an input envelope's ``verdict`` to a uniform trinary status.

    Returns a ``(status, note)`` tuple. ``status`` is one of
    ``green`` / ``yellow`` / ``red``. ``note`` is a short
    human-readable string for the per-substrate-notes envelope
    field (empty on green-with-known-verdict).
    """
    if envelope is None:
        return "red", f"{substrate}: envelope missing or unparseable"
    raw_verdict = envelope.get("verdict")
    if not isinstance(raw_verdict, str):
        return "red", f"{substrate}: envelope has no string 'verdict' field"
    verdict_map = SUBSTRATE_VERDICT_MAPS.get(substrate)
    if verdict_map is None:
        # Defensive: caller passed a substrate key we do not know
        # how to interpret. Should be unreachable given SUBSTRATES.
        return "red", f"{substrate}: unknown substrate key"
    status = verdict_map.get(raw_verdict)
    if status is None:
        return "red", f"{substrate}: unknown verdict '{raw_verdict}'"
    if status == "green":
        return status, ""
    return status, f"{substrate}: verdict='{raw_verdict}'"


def decide(steps: Mapping[str, str]) -> str:
    """Apply the Tag-64 decision rule.

    Trinary mirroring the Tag-53 sanity-gate pattern: any red
    collapses to BLOCK; any yellow degrades to CAUTION; all green
    yields READY.
    """
    reds = sum(1 for v in steps.values() if v == "red")
    yellows = sum(1 for v in steps.values() if v == "yellow")
    greens = sum(1 for v in steps.values() if v == "green")
    if reds >= 1:
        return VERDICT_BLOCK
    if yellows >= 1:
        return VERDICT_CAUTION
    if greens == len(steps):
        return VERDICT_READY
    # Defensive default. With _normalise_status above, every value
    # is in VALID_STATUSES, so this branch should be unreachable.
    return VERDICT_BLOCK


def is_in_cutover_window(iso_week: int | None) -> bool:
    """Return ``True`` iff ``iso_week`` is in the KW-24..27 window.

    Returns ``False`` for ``None`` (no window claim made).
    """
    if iso_week is None:
        return False
    return iso_week in CUTOVER_WINDOW_ISO_WEEKS


def _env_key(substrate: str) -> str:
    """Map a substrate key to its workflow env-var name.

    ``engine_composite`` -> ``V1_ENVELOPE_PATH`` (1-indexed by
    position in SUBSTRATES). Keeps a single ordering source of
    truth between the workflow YAML and the aggregator.
    """
    idx = SUBSTRATES.index(substrate) + 1
    return f"V{idx}_ENVELOPE_PATH"


def build_envelope(
    envelopes: Mapping[str, Mapping[str, Any] | None],
    *,
    iso_week: int | None = None,
    github_run_id: str | None = None,
    github_sha: str | None = None,
    github_ref: str | None = None,
) -> dict[str, Any]:
    """Build the aggregated verdict envelope.

    Parameters
    ----------
    envelopes
        Mapping of substrate-key (one of ``SUBSTRATES``) to the
        already-loaded input envelope (``dict``) or ``None`` if
        the envelope was missing / unparseable.
    iso_week
        Optional ISO calendar week for marathon-dashboard
        correlation. Surfaced on the envelope as
        ``window.iso_week``; does NOT affect the verdict.
    github_run_id, github_sha, github_ref
        Optional GitHub Actions context surfaced verbatim.
    """
    steps: dict[str, str] = {}
    per_note: dict[str, str] = {}
    for substrate in SUBSTRATES:
        status, note = _normalise_status(substrate, envelopes.get(substrate))
        steps[substrate] = status
        if note:
            per_note[substrate] = note
    reds = sum(1 for v in steps.values() if v == "red")
    yellows = sum(1 for v in steps.values() if v == "yellow")
    greens = sum(1 for v in steps.values() if v == "green")
    verdict = decide(steps)
    failed = [k for k, v in steps.items() if v != "green"]
    return {
        "schema_version": 1,
        "workflow": "cutover-day-morgen-auto-scheduler",
        "tag": "tag-64",
        "emitted_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ),
        "github_run_id": github_run_id,
        "github_sha": github_sha,
        "github_ref": github_ref,
        "verdict": verdict,
        "step_results": steps,
        "failed_steps": failed,
        "per_substrate_notes": per_note,
        "counts": {"green": greens, "yellow": yellows, "red": reds},
        "window": {
            "iso_week": iso_week,
            "in_cutover_window": is_in_cutover_window(iso_week),
            "cutover_iso_weeks": list(CUTOVER_WINDOW_ISO_WEEKS),
        },
        "input_verdicts": {
            substrate: (
                envelopes[substrate].get("verdict")
                if envelopes.get(substrate) is not None
                else None
            )
            for substrate in SUBSTRATES
        },
        "decision_rule": {
            "ready": (
                "all three top-level verdicts green "
                "(engine_composite + pyramide_composite + e2e_smoke)"
            ),
            "caution": "at least one yellow, zero red",
            "block": "at least one red, OR any envelope missing",
        },
    }


# ---- Notify-cascade builder (Tag-65, audit-only) -------------------------


def should_emit_notify_cascade(
    verdict: str, prev_verdict: str | None
) -> bool:
    """Decide whether the notify-cascade fires for the current verdict.

    Audit semantics (Tag-65):

    * ``CUTOVER-DAY-MORGEN-BLOCK``   -> always fires (forensic trail).
    * ``CUTOVER-DAY-MORGEN-CAUTION`` -> fires only on transition,
      i.e. ``prev_verdict != "CUTOVER-DAY-MORGEN-CAUTION"``.
    * ``CUTOVER-DAY-MORGEN-READY``   -> never fires (suppressed).
    * Any unknown verdict             -> never fires (defensive).
    """
    if verdict == VERDICT_BLOCK:
        return True
    if verdict == VERDICT_CAUTION:
        return prev_verdict != VERDICT_CAUTION
    return False


def build_notify_cascade_payload(
    envelope: Mapping[str, Any],
    *,
    prev_verdict: str | None = None,
) -> dict[str, Any] | None:
    """Build the ntfy-shaped audit-only notify-cascade payload.

    Returns ``None`` if the verdict does not warrant a notify-cascade
    fire (READY, or stable CAUTION). Otherwise returns a JSON-
    serialisable dict carrying the ntfy.sh-publish-as-JSON contract
    (``topic`` / ``title`` / ``message`` / ``priority`` / ``tags``)
    plus the audit-only marker and a forensic ``verdict_summary``
    field carrying the Tag-64 aggregator envelope's decision signal.

    The ``operator_curl_hint`` field documents how operator-hand
    fires the actual ntfy POST after reviewing this audit artifact;
    the workflow does NOT execute the curl itself (per ADR-0034
    sandbox-host-separation).
    """
    verdict = envelope.get("verdict")
    if not isinstance(verdict, str):
        return None
    if not should_emit_notify_cascade(verdict, prev_verdict):
        return None
    topic = (
        NOTIFY_CASCADE_TOPIC_BLOCK
        if verdict == VERDICT_BLOCK
        else NOTIFY_CASCADE_TOPIC_CAUTION
    )
    priority = NOTIFY_CASCADE_PRIORITY_MAP[verdict]
    tags = list(NOTIFY_CASCADE_TAGS_MAP[verdict])
    iso_week = envelope.get("window", {}).get("iso_week")
    in_window = envelope.get("window", {}).get("in_cutover_window", False)
    step_results = envelope.get("step_results", {}) or {}
    failed_steps = envelope.get("failed_steps", []) or []
    counts = envelope.get("counts", {}) or {}
    per_notes = envelope.get("per_substrate_notes", {}) or {}
    title = f"Cutover-Day-Morgen {verdict} (KW-{iso_week})"
    message_lines = [
        f"Verdict: {verdict}",
        f"ISO week: KW-{iso_week} (in_window={in_window})",
        (
            f"Substrates: "
            f"engine_composite={step_results.get('engine_composite', '?')} "
            f"pyramide_composite={step_results.get('pyramide_composite', '?')} "
            f"e2e_smoke={step_results.get('e2e_smoke', '?')}"
        ),
        (
            f"Counts: green={counts.get('green', 0)} "
            f"yellow={counts.get('yellow', 0)} "
            f"red={counts.get('red', 0)}"
        ),
    ]
    if failed_steps:
        message_lines.append(f"Failed substrates: {', '.join(failed_steps)}")
    for substrate, note in sorted(per_notes.items()):
        message_lines.append(f"- {substrate}: {note}")
    return {
        "schema_version": 1,
        "kind": NOTIFY_CASCADE_KIND,
        "audit_only": NOTIFY_CASCADE_AUDIT_ONLY,
        "topic": topic,
        "title": title,
        "message": "\n".join(message_lines),
        "priority": priority,
        "tags": tags,
        "verdict_summary": {
            "verdict": verdict,
            "prev_verdict": prev_verdict,
            "iso_week": iso_week,
            "in_cutover_window": in_window,
            "step_results": dict(step_results),
            "failed_steps": list(failed_steps),
            "counts": dict(counts),
            "per_substrate_notes": dict(per_notes),
            "github_run_id": envelope.get("github_run_id"),
            "github_sha": envelope.get("github_sha"),
            "github_ref": envelope.get("github_ref"),
        },
        "operator_curl_hint": (
            "curl -fsSL -X POST -H 'Content-Type: application/json' "
            "-d @notify-cascade-payload.json https://ntfy.sh"
        ),
        "emitted_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ),
    }


# ---- CLI -----------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aggregate_cutover_day_morgen_verdict",
        description=(
            "Aggregate the three top-level pre-cutover-acceptance "
            "verdict envelopes into a single Cutover-Day-Morgen "
            "verdict for the KW-24..27 auto-scheduler."
        ),
    )
    p.add_argument(
        "--engine-envelope",
        type=Path,
        default=None,
        help="Path to Selin Tag-61/63 engine-composite verdict envelope JSON.",
    )
    p.add_argument(
        "--pyramide-envelope",
        type=Path,
        default=None,
        help="Path to Amara Tag-62 pyramide-composite verdict envelope JSON.",
    )
    p.add_argument(
        "--e2e-envelope",
        type=Path,
        default=None,
        help="Path to Amara Tag-63 E2E-smoke verdict envelope JSON.",
    )
    p.add_argument(
        "--iso-week",
        type=int,
        default=None,
        help="Optional ISO calendar week (1..53) for envelope correlation.",
    )
    p.add_argument(
        "--github-run-id",
        type=str,
        default=None,
        help="Optional GitHub Actions run-id to surface verbatim.",
    )
    p.add_argument(
        "--github-sha",
        type=str,
        default=None,
        help="Optional GitHub Actions SHA to surface verbatim.",
    )
    p.add_argument(
        "--github-ref",
        type=str,
        default=None,
        help="Optional GitHub Actions ref to surface verbatim.",
    )
    p.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the verdict-envelope JSON.",
    )
    p.add_argument(
        "--emit-notify-cascade",
        type=Path,
        default=None,
        help=(
            "Optional path for the audit-only notify-cascade payload "
            "JSON (Tag-65). When the aggregated verdict is BLOCK "
            "(always) or CAUTION (only on transition from non-CAUTION), "
            "a ntfy-shaped audit envelope is written to this path. "
            "The aggregator NEVER performs an HTTP POST; that is "
            "operator-hand territory per ADR-0034."
        ),
    )
    p.add_argument(
        "--prev-verdict",
        type=str,
        default=None,
        help=(
            "Optional previous run's aggregated verdict "
            "(CUTOVER-DAY-MORGEN-READY/CAUTION/BLOCK) for the "
            "notify-cascade transition rule. Default: None."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    envelopes: dict[str, dict[str, Any] | None] = {
        "engine_composite": _load_envelope(args.engine_envelope),
        "pyramide_composite": _load_envelope(args.pyramide_envelope),
        "e2e_smoke": _load_envelope(args.e2e_envelope),
    }
    envelope = build_envelope(
        envelopes,
        iso_week=args.iso_week,
        github_run_id=args.github_run_id,
        github_sha=args.github_sha,
        github_ref=args.github_ref,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(envelope, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    # Tag-65 audit-only notify-cascade emission. Always writes a
    # file when --emit-notify-cascade is set: either the payload
    # (BLOCK / transition-CAUTION) or a "suppressed" stub (READY /
    # stable-CAUTION) so downstream tooling (artifact-upload) has a
    # deterministic file to consume.
    if args.emit_notify_cascade is not None:
        cascade_payload = build_notify_cascade_payload(
            envelope, prev_verdict=args.prev_verdict
        )
        if cascade_payload is None:
            cascade_payload = {
                "schema_version": 1,
                "kind": NOTIFY_CASCADE_KIND,
                "audit_only": NOTIFY_CASCADE_AUDIT_ONLY,
                "suppressed": True,
                "suppression_reason": (
                    "READY-verdict-no-cascade"
                    if envelope.get("verdict") == VERDICT_READY
                    else "stable-CAUTION-no-cascade"
                ),
                "verdict_summary": {
                    "verdict": envelope.get("verdict"),
                    "prev_verdict": args.prev_verdict,
                    "iso_week": envelope.get("window", {}).get("iso_week"),
                },
                "emitted_at_utc": datetime.now(timezone.utc).isoformat(
                    timespec="seconds"
                ),
            }
        args.emit_notify_cascade.parent.mkdir(parents=True, exist_ok=True)
        args.emit_notify_cascade.write_text(
            json.dumps(cascade_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
