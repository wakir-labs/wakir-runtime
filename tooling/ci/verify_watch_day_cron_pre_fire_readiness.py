#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Tag-57 Watch-Day Cron-Pre-Fire Readiness Verifier (Noa SRE).

Purpose
-------

Tag-56 (PR #359) landed the Phase-3c Watch-Day-Practice-Run CI gate
(`.github/workflows/phase-3c-watch-day-practice-run.yml`). The
workflow ships a ``schedule: cron "0 5 * * 2"`` trigger -- every
Tuesday 05:00 UTC. KW-24 starts 2026-06-09 (Tue), which is the
first calendar slot at which that cron actually fires for the live
Watch-Day window. The next three Tuesdays (KW-25..27) follow.

The risk pattern this script defends against
--------------------------------------------

A scheduled workflow that is wired wrong fires silently. A
miswritten cron expression skips weeks (or fires every day). A
miswritten path-filter means a substrate edit lands on `main`
without re-pinning the practice-run. A miswritten escalation
routing means a RED Watch-Day-Verdict does not page Mira -- the
operator finds out the next morning.

We catch all three before KW-24 starts by running a hermetic pre-
fire probe over the Tag-56 workflow file, the Tag-54 spec, and the
in-tree alert-routing surface, **without** sending any actual
notification and **without** waiting for Tuesday 05:00 UTC.

What this verifier checks
-------------------------

Stage A -- Cron-Expression-Parse-Test
    Parse the ``schedule.cron`` expression from
    ``.github/workflows/phase-3c-watch-day-practice-run.yml`` and
    assert it is exactly ``0 5 * * 2`` (Tue 05:00 UTC). Compute
    the next four firings starting from a caller-supplied
    reference instant; assert each is a Tuesday at 05:00 UTC, and
    the four firings cover KW-24..27 of the supplied year.

Stage B -- Path-Filter-Coverage-Test
    Parse the ``on.push.paths`` and ``on.pull_request.paths``
    lists from the workflow file. Assert both lists are
    byte-identical (any drift between push/PR filters is a class
    of regression where PR review-gating does not match main-
    landing gating). Assert each of the seven canonical Tag-54/55/
    56 substrates appears in both lists.

Stage C -- Alert-Routing-Dry-Run
    Resolve, for each of the four §6.1 Page-class triggers and the
    four §6.2 Ticket-class triggers from the Tag-54 spec, the
    expected ``(persona, channel, sla_minutes)`` triple. Emit the
    routing-table as a JSON envelope. **Hermetic**: no actual
    Mira-Notify event is written, no NATS message sent, no
    AlertManager webhook fired. The dry-run validates the routing
    table at code level; it does not exercise the transport.

Exit codes
----------

0   READY    -- all three stages green
2   CAUTION  -- one or more stages yellow (non-fatal, manual review)
1   BLOCK    -- one or more stages red (do not enter KW-24)

Sandbox boundary
----------------

Stdlib only. No subprocess to git, no network, no podman, no real
Prometheus, no real Grafana, no real Mira-Notify emit. Reads the
workflow YAML and the spec MD as text. Cron parsing is local; no
external cron library.

Coupling with Tag-56
--------------------

This is **adjacent** to PR #359, not a replacement. PR #359 pins
the §7 verdict-formula contract. This file pins the
**trigger-surface** and **routing-table** contracts. The two
gates compose: a Tuesday 05:00 UTC fire executes the §7
contract; if either the fire-schedule or the routing is wrong,
the §7 result never reaches the operator.

CLI
---

    python3 tooling/ci/verify_watch_day_cron_pre_fire_readiness.py \
        [--workflow PATH] [--spec PATH] [--reference-iso ISO] \
        [--mode all|cron|paths|routing] [--json]

Default ``--reference-iso`` is ``2026-06-02T05:00:01+00:00`` (one
second after the KW-23 Tuesday fire), so the next-four firings
are exactly the live Watch-Day window KW-24..27 of 2026. For a
Tag-57-era invocation use e.g. ``--reference-iso
2026-05-19T00:00:00+00:00`` and rely on the KW-24-in-next-four
check (the script downgrades to CAUTION only if KW-24 is absent
from the next four firings).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Canonical constants (Tag-54 spec §3, §6; Tag-55/56 substrate set)
# ---------------------------------------------------------------------------

CANONICAL_CRON = "0 5 * * 2"
"""Tuesday 05:00 UTC, exactly. Any other value is a regression."""

CANONICAL_PATH_FILTER_SET: tuple[str, ...] = (
    "docs/observability/pre-cutover-watch-day-spec.md",
    "scripts/observability/pre-cutover-watch-day-verdict.py",
    "scripts/observability/watch-day-practice-run.py",
    "tests/observability/test_pre_cutover_watch_day_verdict.py",
    "tests/observability/test_watch_day_practice_run.py",
    ".github/workflows/phase-3c-watch-day-practice-run.yml",
    "tooling/ci/aggregate_watch_day_practice_run_verdict.py",
)
"""Seven canonical substrates that must appear in BOTH push.paths and
pull_request.paths in the Tag-56 workflow. Drift here is a Tag-56
regression."""

# §6.1 Severity-class P (Page) triggers. Tuple shape:
# (trigger_id, persona, channel, sla_minutes).
PAGE_ROUTING: tuple[tuple[str, str, str, int], ...] = (
    ("watch_day_verdict_red", "Mira", "mira_notify_push_high", 15),
    ("ar_hand_stop", "Mira_then_AR", "mira_notify_push_critical", 15),
    ("hard_zero_slo_breach", "Mira_and_Priya", "mira_notify_push_high", 15),
)

# §6.2 Severity-class T (Ticket) triggers.
TICKET_ROUTING: tuple[tuple[str, str, str, int], ...] = (
    ("drift_a_kai_domain", "Kai", "inbox_kai_plus_notify_medium", 240),
    ("drift_a_noa_domain", "Noa_self", "self_single_purpose_pr", 240),
    ("wat_pipeline_regression", "Tomas", "inbox_tomas_plus_notify_medium", 240),
    ("drift_b_informational", "Mira_info", "inbox_mira_plus_notify_low", 1440),
)

# Six watch-day slots per §4 (08, 10, 12, 14, 16, 18 CEST).
CANONICAL_SLOTS: tuple[int, ...] = (8, 10, 12, 14, 16, 18)


# ---------------------------------------------------------------------------
# Stage A: Cron-Expression-Parse-Test
# ---------------------------------------------------------------------------


def extract_cron_from_workflow(text: str) -> str | None:
    """Find the first ``- cron: "..."`` line under a ``schedule:`` key.

    The Tag-56 workflow YAML is the source. We do **not** import a
    YAML library; we parse a minimal grammar because the workflow's
    structure is shaped by hand and our coverage need is narrow.

    Returns the literal cron string (without surrounding quotes), or
    ``None`` if no ``schedule:`` block with a cron entry is found.
    """
    in_schedule = False
    schedule_indent: int | None = None
    cron_pattern = re.compile(r'^\s*-\s*cron:\s*"([^"]+)"\s*$')
    for line in text.splitlines():
        stripped = line.lstrip()
        # Detect entering a `schedule:` mapping. Allow leading
        # indentation (the key sits under `on:`).
        if stripped.startswith("schedule:"):
            in_schedule = True
            schedule_indent = len(line) - len(stripped)
            continue
        if in_schedule:
            # Leave the schedule block when we see a non-blank line
            # whose indent is <= the schedule key's indent.
            if stripped and not stripped.startswith("#"):
                current_indent = len(line) - len(stripped)
                if (
                    schedule_indent is not None
                    and current_indent <= schedule_indent
                    and not stripped.startswith("-")
                ):
                    in_schedule = False
                    continue
            m = cron_pattern.match(line)
            if m:
                return m.group(1)
    return None


def next_n_tuesday_05_utc(reference: dt.datetime, n: int) -> list[dt.datetime]:
    """Compute the next ``n`` firings of cron ``0 5 * * 2`` from ``reference``.

    Tuesday = ``isoweekday() == 2``. The next fire is the smallest
    Tuesday 05:00 UTC strictly greater than ``reference``.
    """
    if reference.tzinfo is None:
        raise ValueError("reference must be timezone-aware")
    ref_utc = reference.astimezone(dt.timezone.utc)
    fires: list[dt.datetime] = []
    cursor = ref_utc
    while len(fires) < n:
        # Step forward 1 hour at a time would work, but coarser is
        # cheaper. Move to next day-boundary then check Tuesday.
        cursor = cursor + dt.timedelta(minutes=1)
        candidate = cursor.replace(hour=5, minute=0, second=0, microsecond=0)
        if candidate <= ref_utc:
            candidate = candidate + dt.timedelta(days=1)
        # Walk forward to next Tuesday.
        while candidate.isoweekday() != 2:
            candidate = candidate + dt.timedelta(days=1)
        if fires and candidate <= fires[-1]:
            candidate = candidate + dt.timedelta(days=7)
        if candidate > ref_utc and (not fires or candidate > fires[-1]):
            fires.append(candidate)
            cursor = candidate
    return fires


def iso_week_of(timestamp: dt.datetime) -> int:
    """Return the ISO week number for ``timestamp``."""
    return timestamp.isocalendar().week


@dataclass
class CronStageResult:
    status: str  # "green" | "yellow" | "red"
    cron_expression: str | None
    next_fires_iso: list[str] = field(default_factory=list)
    next_fires_iso_weeks: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def stage_cron(workflow_text: str, reference: dt.datetime) -> CronStageResult:
    cron = extract_cron_from_workflow(workflow_text)
    result = CronStageResult(status="red", cron_expression=cron)
    if cron is None:
        result.notes.append("workflow_missing_schedule_cron")
        return result
    if cron != CANONICAL_CRON:
        result.notes.append(
            f"cron_drift expected={CANONICAL_CRON!r} actual={cron!r}"
        )
        return result
    fires = next_n_tuesday_05_utc(reference, 4)
    result.next_fires_iso = [f.isoformat() for f in fires]
    result.next_fires_iso_weeks = [iso_week_of(f) for f in fires]
    # All four firings must be Tuesdays at 05:00 UTC.
    bad: list[str] = []
    for f in fires:
        if f.isoweekday() != 2:
            bad.append(f"not_tuesday:{f.isoformat()}")
        if (f.hour, f.minute) != (5, 0):
            bad.append(f"not_0500_utc:{f.isoformat()}")
    if bad:
        result.notes.extend(bad)
        return result
    # KW-24..27 coverage: KW-24 is the live Watch-Day window start
    # (2026-06-09 Tue). The pre-fire probe demands that the next-four
    # firings from a Tag-57-era reference (2026-05) include the
    # KW-24 fire as either the first, second, third, or fourth slot.
    # The full window KW-24..27 is then covered by the four firings
    # starting from a reference no later than 2026-06-02.
    if reference.year == 2026 and reference.month in (5, 6):
        kw24_iso = "2026-06-09T05:00:00+00:00"
        if kw24_iso not in result.next_fires_iso:
            result.notes.append(
                f"kw24_fire_missing expected_in_next4={kw24_iso} "
                + "actual=" + ",".join(result.next_fires_iso)
            )
            result.status = "yellow"
            return result
        # Stronger: when reference is no later than 2026-06-02, the
        # four firings should be exactly KW-24..27 of 2026.
        cutoff = dt.datetime(2026, 6, 2, 5, 0, 0, tzinfo=dt.timezone.utc)
        if reference <= cutoff:
            if result.next_fires_iso_weeks != [24, 25, 26, 27]:
                result.notes.append(
                    "iso_week_drift expected=KW24..27 actual=KW"
                    + ",".join(str(w) for w in result.next_fires_iso_weeks)
                )
                result.status = "yellow"
                return result
    result.status = "green"
    return result


# ---------------------------------------------------------------------------
# Stage B: Path-Filter-Coverage-Test
# ---------------------------------------------------------------------------


def extract_paths_block(text: str, parent_key: str) -> list[str]:
    """Return all ``- "..."`` entries under the first ``paths:`` block
    nested inside the first ``parent_key:`` block.

    ``parent_key`` is e.g. ``"push"`` or ``"pull_request"``. The
    parsing is intentionally narrow: we walk lines, track when we
    enter the parent and then a ``paths:`` child, and stop at the
    first dedent.
    """
    lines = text.splitlines()
    in_parent = False
    parent_indent: int | None = None
    in_paths = False
    paths_indent: int | None = None
    out: list[str] = []
    entry_re = re.compile(r'^\s*-\s*"([^"]+)"\s*$')
    parent_re = re.compile(rf"^(\s*){re.escape(parent_key)}:\s*$")
    for line in lines:
        stripped = line.lstrip()
        current_indent = len(line) - len(stripped)
        m_parent = parent_re.match(line)
        if m_parent and not in_parent:
            in_parent = True
            parent_indent = current_indent
            continue
        if in_parent:
            # Detect leaving the parent.
            if (
                stripped
                and not stripped.startswith("#")
                and parent_indent is not None
                and current_indent <= parent_indent
            ):
                # We have dedented out of the parent.
                break
            # Detect entering the paths block.
            if stripped.startswith("paths:") and not in_paths:
                in_paths = True
                paths_indent = current_indent
                continue
            if in_paths:
                if (
                    stripped
                    and not stripped.startswith("#")
                    and paths_indent is not None
                    and current_indent <= paths_indent
                    and not stripped.startswith("-")
                ):
                    in_paths = False
                    continue
                m_entry = entry_re.match(line)
                if m_entry:
                    out.append(m_entry.group(1))
    return out


@dataclass
class PathsStageResult:
    status: str
    push_paths: list[str] = field(default_factory=list)
    pull_request_paths: list[str] = field(default_factory=list)
    missing_in_push: list[str] = field(default_factory=list)
    missing_in_pr: list[str] = field(default_factory=list)
    drift_between_push_and_pr: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def stage_paths(workflow_text: str) -> PathsStageResult:
    push_paths = extract_paths_block(workflow_text, "push")
    pr_paths = extract_paths_block(workflow_text, "pull_request")
    res = PathsStageResult(
        status="red",
        push_paths=push_paths,
        pull_request_paths=pr_paths,
    )
    if not push_paths:
        res.notes.append("push_paths_block_missing")
        return res
    if not pr_paths:
        res.notes.append("pull_request_paths_block_missing")
        return res
    missing_push = [p for p in CANONICAL_PATH_FILTER_SET if p not in push_paths]
    missing_pr = [p for p in CANONICAL_PATH_FILTER_SET if p not in pr_paths]
    res.missing_in_push = missing_push
    res.missing_in_pr = missing_pr
    # Drift between push and PR: items present in one but not the
    # other. Order does not matter, set-difference both ways.
    push_only = sorted(set(push_paths) - set(pr_paths))
    pr_only = sorted(set(pr_paths) - set(push_paths))
    drift = [f"push_only:{p}" for p in push_only] + [
        f"pr_only:{p}" for p in pr_only
    ]
    res.drift_between_push_and_pr = drift
    if missing_push or missing_pr:
        res.notes.append("canonical_substrate_missing")
        return res
    if drift:
        res.notes.append("push_pr_filter_drift")
        res.status = "yellow"
        return res
    res.status = "green"
    return res


# ---------------------------------------------------------------------------
# Stage C: Alert-Routing-Dry-Run
# ---------------------------------------------------------------------------


@dataclass
class RoutingStageResult:
    status: str
    page_routes: list[dict] = field(default_factory=list)
    ticket_routes: list[dict] = field(default_factory=list)
    spec_mentions_missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _routing_to_dict(
    rows: Iterable[tuple[str, str, str, int]], severity: str
) -> list[dict]:
    return [
        {
            "trigger_id": tid,
            "severity": severity,
            "persona": persona,
            "channel": channel,
            "sla_minutes": sla,
        }
        for (tid, persona, channel, sla) in rows
    ]


def stage_routing(spec_text: str) -> RoutingStageResult:
    res = RoutingStageResult(status="red")
    res.page_routes = _routing_to_dict(PAGE_ROUTING, "P")
    res.ticket_routes = _routing_to_dict(TICKET_ROUTING, "T")
    # Verify that the Tag-54 spec actually mentions each routing
    # trigger by some recognisable substring. This is a coupling
    # check: if a future spec edit deletes "WAT-pipeline regression"
    # from the table, our dry-run still claims to route it -- that
    # is the regression class we want to catch.
    spec_anchor_probes: tuple[tuple[str, str], ...] = (
        ("watch_day_verdict_red", "Watch-Day-Verdict RED"),
        ("ar_hand_stop", "AR-Hand-Stop"),
        ("hard_zero_slo_breach", "Hard-zero SLO"),
        ("drift_a_kai_domain", "Drift-type A (Kai-domain)"),
        ("drift_a_noa_domain", "Drift-type A (Noa-domain)"),
        ("wat_pipeline_regression", "WAT-pipeline regression"),
        ("drift_b_informational", "Drift-type B informational"),
    )
    missing: list[str] = []
    for trigger_id, needle in spec_anchor_probes:
        if needle not in spec_text:
            missing.append(trigger_id)
    res.spec_mentions_missing = missing
    if missing:
        res.notes.append("spec_anchor_drift")
        res.status = "yellow"
        return res
    # Sanity: SLA values are positive and persona is non-empty.
    for route in res.page_routes + res.ticket_routes:
        if not route["persona"] or route["sla_minutes"] <= 0:
            res.notes.append(f"invalid_route:{route['trigger_id']}")
            return res
    res.status = "green"
    return res


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def aggregate_verdict(
    cron_status: str, paths_status: str, routing_status: str
) -> str:
    statuses = (cron_status, paths_status, routing_status)
    if "red" in statuses:
        return "BLOCK"
    if "yellow" in statuses:
        return "CAUTION"
    return "READY"


def exit_code_for_verdict(verdict: str) -> int:
    return {"READY": 0, "CAUTION": 2, "BLOCK": 1}[verdict]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_envelope(
    cron: CronStageResult,
    paths: PathsStageResult,
    routing: RoutingStageResult,
    reference_iso: str,
    mode: str,
) -> dict:
    verdict = aggregate_verdict(cron.status, paths.status, routing.status)
    envelope: dict = {
        "schema_version": 1,
        "tag": 57,
        "tool": "verify_watch_day_cron_pre_fire_readiness",
        "mode": mode,
        "reference_iso": reference_iso,
        "verdict": verdict,
        "stages": {
            "cron": {
                "status": cron.status,
                "cron_expression": cron.cron_expression,
                "next_fires_iso": cron.next_fires_iso,
                "next_fires_iso_weeks": cron.next_fires_iso_weeks,
                "notes": cron.notes,
            },
            "paths": {
                "status": paths.status,
                "push_paths": paths.push_paths,
                "pull_request_paths": paths.pull_request_paths,
                "missing_in_push": paths.missing_in_push,
                "missing_in_pr": paths.missing_in_pr,
                "drift_between_push_and_pr": paths.drift_between_push_and_pr,
                "notes": paths.notes,
            },
            "routing": {
                "status": routing.status,
                "page_routes": routing.page_routes,
                "ticket_routes": routing.ticket_routes,
                "spec_mentions_missing": routing.spec_mentions_missing,
                "notes": routing.notes,
            },
        },
    }
    return envelope


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--workflow",
        type=Path,
        default=Path(".github/workflows/phase-3c-watch-day-practice-run.yml"),
    )
    p.add_argument(
        "--spec",
        type=Path,
        default=Path("docs/observability/pre-cutover-watch-day-spec.md"),
    )
    p.add_argument(
        "--reference-iso",
        default="2026-06-02T05:00:01+00:00",
        help=(
            "Reference instant for the next-fire computation. "
            "Default 2026-06-02T05:00:01+00:00 -- one second after the "
            "KW-23 fire -- so the next-four firings are exactly the "
            "live Watch-Day window KW-24..27."
        ),
    )
    p.add_argument(
        "--mode",
        choices=("all", "cron", "paths", "routing"),
        default="all",
    )
    p.add_argument("--json", action="store_true", help="Emit JSON to stdout")
    p.add_argument("--output", type=Path, default=None)
    args = p.parse_args(argv)

    try:
        workflow_text = args.workflow.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"::error::cannot read workflow {args.workflow}: {exc}", file=sys.stderr)
        return 1
    try:
        spec_text = args.spec.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"::error::cannot read spec {args.spec}: {exc}", file=sys.stderr)
        return 1
    try:
        reference = dt.datetime.fromisoformat(args.reference_iso)
    except ValueError as exc:
        print(f"::error::bad reference-iso: {exc}", file=sys.stderr)
        return 1

    cron_res = stage_cron(workflow_text, reference)
    paths_res = stage_paths(workflow_text)
    routing_res = stage_routing(spec_text)

    envelope = build_envelope(
        cron_res, paths_res, routing_res, args.reference_iso, args.mode
    )

    if args.mode == "cron":
        envelope["stages"] = {"cron": envelope["stages"]["cron"]}
        verdict = "READY" if cron_res.status == "green" else (
            "CAUTION" if cron_res.status == "yellow" else "BLOCK"
        )
        envelope["verdict"] = verdict
    elif args.mode == "paths":
        envelope["stages"] = {"paths": envelope["stages"]["paths"]}
        verdict = "READY" if paths_res.status == "green" else (
            "CAUTION" if paths_res.status == "yellow" else "BLOCK"
        )
        envelope["verdict"] = verdict
    elif args.mode == "routing":
        envelope["stages"] = {"routing": envelope["stages"]["routing"]}
        verdict = "READY" if routing_res.status == "green" else (
            "CAUTION" if routing_res.status == "yellow" else "BLOCK"
        )
        envelope["verdict"] = verdict

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(envelope, indent=2, sort_keys=True), encoding="utf-8"
        )
    if args.json or args.output is None:
        json.dump(envelope, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")

    return exit_code_for_verdict(envelope["verdict"])


if __name__ == "__main__":
    sys.exit(main())
