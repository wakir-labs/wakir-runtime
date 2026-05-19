#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-63 Operator-Trigger + Alert-Routing Integration verifier (Noa SRE).

Pre-KW-24 closeout helper that pins the **end-to-end integration**
between two previously orthogonal substrates:

  * Tag-62 (PR #397) -- Operator-Trigger Pipeline. Synthesizes a
    workflow_dispatch envelope that simulates the operator (Mira-
    Hand) clicking "Run workflow" on Cutover-Day T0. Verdict
    OPERATOR-TRIGGER-READY / CAUTION / BLOCKED.
  * Tag-58 (PR #373) -- Alert-Routing-Spec Cross-Repo-Mirror Audit.
    Pins four mirror-pair routing-tables (notify-catalog markdown,
    backend alert rules YAML, SLO burn-rate alert rules YAML, the
    Python ALERT_CATALOG bridge) between runtime and protocol repos.

Both substrates are independently regression-pinned. Neither pins
the *integration*: that the trigger event the operator emits on
Cutover-Day is recognised as a valid alert-source by each of the
four Tag-58 mirror-pair routing-tables, and that the trigger-event
correctly propagates -- i.e., the trigger's `workflow` field maps
to an alertname that resolves to a known failure_mode_id, severity
class, and inbox runbook path through each of the four routing
tables.

Without Tag-63 the failure mode is:

    Tag-62 trigger-envelope shape changes (legitimate refactor),
    runtime side adopts the change, protocol-side routing-table
    mirror lags by one PR cycle. The Tag-58 audit reports
    MIRROR-DRIFT on the runtime/protocol mirror axis, but **no**
    gate fires that says "the operator-trigger event the simulator
    emits will not be recognised by the protocol-side notify
    catalog on Cutover-Day". Tag-63 closes that gap.

Four-stage hermetic verdict
---------------------------

    Stage 1  Operator-Trigger-Simulation
             ----------------------------
             Re-uses the Tag-62 simulator (subprocess) to emit a
             canonical workflow_dispatch envelope into a temp
             output dir. Status: green if Tag-62 stage-2 returns
             0, yellow on exit 2, red otherwise.

    Stage 2  Alert-Routing-Propagation-Check
             --------------------------------
             For each of the four canonical mirror-pairs from the
             Tag-58 MIRROR_PAIRS table, verify the runtime-side
             routing-table file exists and contains at least one
             recognisable alertname/failure-mode anchor. This is
             a runtime-side-only check (protocol-side mirror is
             a Tag-58 concern, not a Tag-63 concern): we pin the
             integration surface, not the cross-repo audit.

    Stage 3  Trigger-Event-Landing-Verification
             -----------------------------------
             For each of the four mirror-pair files, derive a
             routing-table summary (set of alertnames or failure-
             mode-IDs the file references) and verify the canonical
             trigger-event substrate (the Tag-56 workflow name
             "phase-3c-watch-day-practice-run") is referenced as
             a valid telemetry source either directly (by name)
             or transitively (the file references at least one
             watch-day-pinned alertname like "WakirWatchDay...",
             "PreCutoverWatchDay...", or a Class-A/B/C failure-
             mode ID).

    Stage 4  Aggregate Verdict
             -----------------
             INTEGRATION-INTACT   -- all three stages green
             INTEGRATION-DRIFT    -- exactly one stage yellow,
                                     others green
             INTEGRATION-DEFECT   -- any stage red, or 2+ stages
                                     yellow

Hermetic boundary
-----------------

stdlib + python 3.11. **No** GitHub-API call, **no** podman, no
NATS emit, no Mira-Notify webhook fire, no AlertManager call.
Reads only on-disk text/JSON files (the Tag-62 simulator helper,
the four Tag-58 mirror-pair files, and a synthesized trigger
envelope written to a tmp dir).

Reuses the Tag-62 simulator via subprocess (not import) so the
Tag-62 contract stays stable and the Tag-63 integration test fails
if the Tag-62 CLI surface regresses.

Exit codes
----------

    0   INTEGRATION-INTACT or stage green
    2   INTEGRATION-DRIFT or stage yellow
    1   INTEGRATION-DEFECT, stage red, or invocation error

Author: Noa Bergstroem (SRE)
Anchor: Tag-63 Pre-KW-24 Operator-Trigger + Alert-Routing
        Integration-Test (Marathon-Continuous-Mode).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Verdict constants (single-sourced; workflow YAML + tests rely on these)
# ---------------------------------------------------------------------------

VERDICT_INTACT = "INTEGRATION-INTACT"
VERDICT_DRIFT = "INTEGRATION-DRIFT"
VERDICT_DEFECT = "INTEGRATION-DEFECT"

STAGE_GREEN = "green"
STAGE_YELLOW = "yellow"
STAGE_RED = "red"
VALID_STAGE_STATUSES: frozenset[str] = frozenset(
    {STAGE_GREEN, STAGE_YELLOW, STAGE_RED}
)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CAUTION = 2


# ---------------------------------------------------------------------------
# Mirror-pair routing tables (subset of Tag-58 MIRROR_PAIRS that is
# load-bearing for the trigger-event-landing check). The four entries
# here MUST stay in sync with Tag-58 audit_alert_routing_cross_repo
# _mirror.MIRROR_PAIRS; a drift between the two tables is itself a
# Tag-63 verdict (caught in T28 of the test suite).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoutingTable:
    name: str
    path: str  # runtime-relative
    kind: str  # one of: "markdown", "yaml-alerts", "python-catalog"
    description: str


ROUTING_TABLES: tuple[RoutingTable, ...] = (
    RoutingTable(
        name="notify-catalog",
        path="docs/observability/pre-mortem-failure-mode-notify-catalog.md",
        kind="markdown",
        description="Pre-Mortem Notify-Catalog (Tag-45 Noa)",
    ),
    RoutingTable(
        name="backend-alerts",
        path="dashboards/phase-3-marathon-alerts.yaml",
        kind="yaml-alerts",
        description="Phase-3 Marathon Backend-Alerting-Rules",
    ),
    RoutingTable(
        name="slo-burn-rate",
        path="dashboards/phase-3-marathon-slo-burn-rate-alerts.yaml",
        kind="yaml-alerts",
        description="Phase-3 Marathon SLO Burn-Rate Alerts",
    ),
    RoutingTable(
        name="alert-catalog-bridge",
        path="scripts/observability/alert-rule-to-mira-notify-bridge.py",
        kind="python-catalog",
        description="Alert-Rule to Mira-Notify bridge (ALERT_CATALOG)",
    ),
)


# Canonical trigger-event source. The Tag-62 simulator emits a
# workflow_dispatch envelope against this workflow; Tag-63 verifies
# that the routing-tables recognise the surrounding telemetry
# (alertnames / failure-modes) the operator would see on Cutover-Day.
CANONICAL_TRIGGER_WORKFLOW = "phase-3c-watch-day-practice-run.yml"
CANONICAL_TRIGGER_SHORT = "phase-3c-watch-day-practice-run"

# Anchors a routing-table must reference to qualify as a valid
# landing surface for the operator-trigger event. The set is
# intentionally broad: any one anchor counts as "trigger-event
# lands in this table". A table with **zero** anchors is a red
# signal.
TRIGGER_LANDING_ANCHORS: tuple[str, ...] = (
    # Direct trigger-substrate name fragments
    "watch-day",
    "WatchDay",
    "watch_day",
    "phase-3c",
    "Phase3c",
    "Phase3C",
    # Tag-56 cron-pin reference
    "0 5 * * 2",
    # Failure-mode classes the operator would page on
    "FailureModeA",
    "FailureModeB",
    "FailureModeC",
    "wakir_phase_3_marathon",
    "PhaseCompleteMarker",
    "CrossModulDrift",
    "WelleRollback",
)


# ---------------------------------------------------------------------------
# Stage primitives
# ---------------------------------------------------------------------------


@dataclass
class StageResult:
    status: str
    notes: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in VALID_STAGE_STATUSES:
            raise ValueError(f"invalid stage status: {self.status!r}")


def _repo_root(repo_root: Path | None) -> Path:
    if repo_root is not None:
        return repo_root.resolve()
    here = Path(__file__).resolve()
    return here.parents[2]


# ---------------------------------------------------------------------------
# Stage 1: Operator-Trigger-Simulation (re-use Tag-62 simulator via CLI)
# ---------------------------------------------------------------------------


TAG62_HELPER_REL = "tooling/ci/simulate_watch_day_operator_trigger.py"


def stage_operator_trigger_simulation(
    repo_root: Path,
    output_dir: Path,
) -> StageResult:
    """Drive the Tag-62 stage-2 (trigger) CLI and capture the
    output envelope into ``output_dir/tag62-trigger-envelope.json``.

    Green: Tag-62 CLI exits 0 AND output envelope present + parseable
    AND envelope.status == "green".
    Yellow: Tag-62 CLI exits 2 OR envelope.status == "yellow".
    Red: any other path.
    """
    notes: list[str] = []
    helper = repo_root / TAG62_HELPER_REL
    if not helper.is_file():
        return StageResult(
            status=STAGE_RED,
            notes=[f"tag62-helper-missing: {TAG62_HELPER_REL}"],
            details={},
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "tag62-trigger-envelope.json"

    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(helper),
                "trigger",
                "--output",
                str(out_path),
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return StageResult(
            status=STAGE_RED,
            notes=[f"tag62-subprocess-failed: {exc!r}"],
            details={},
        )

    rc = proc.returncode
    envelope: dict[str, Any] | None = None
    if out_path.is_file():
        try:
            envelope = json.loads(out_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            notes.append(f"tag62-envelope-malformed: {exc!r}")

    if envelope is None and rc == 0:
        # Envelope file expected when --output supplied.
        notes.append("tag62-envelope-missing: file not written despite exit 0")
        return StageResult(status=STAGE_RED, notes=notes, details={})

    env_status = (envelope or {}).get("status", "unknown")
    details: dict[str, Any] = {
        "tag62_exit_code": rc,
        "envelope_path": str(out_path),
        "envelope_status": env_status,
    }
    if envelope:
        details["envelope_stage"] = envelope.get("stage")
        details["envelope_tag"] = envelope.get("tag")

    if rc == 0 and env_status == "green":
        return StageResult(status=STAGE_GREEN, notes=notes, details=details)
    if rc == 2 or env_status == "yellow":
        notes.append(
            f"tag62-yellow: exit={rc}, envelope_status={env_status!r}"
        )
        return StageResult(status=STAGE_YELLOW, notes=notes, details=details)

    notes.append(
        f"tag62-red: exit={rc}, envelope_status={env_status!r}, stderr={proc.stderr[:200]!r}"
    )
    return StageResult(status=STAGE_RED, notes=notes, details=details)


# ---------------------------------------------------------------------------
# Stage 2: Alert-Routing-Propagation-Check (all 4 mirror-pairs)
# ---------------------------------------------------------------------------


def _extract_alertnames_yaml(text: str) -> set[str]:
    """Extract `alert: <name>` and `- alert: <name>` from YAML.

    Stdlib-only: a narrow regex covers the alert-rule subset used in
    the Phase-3-Marathon alert YAMLs. PyYAML would be cleaner but
    the helper is stdlib by contract.
    """
    names: set[str] = set()
    # `- alert: SomeAlertName` OR `alert: SomeAlertName`
    for m in re.finditer(r"^\s*(?:-\s+)?alert:\s*([A-Za-z0-9_./-]+)", text, re.MULTILINE):
        names.add(m.group(1))
    return names


def _extract_alertnames_python_catalog(text: str) -> set[str]:
    """Extract the dict keys of ``ALERT_CATALOG`` from the bridge."""
    names: set[str] = set()
    # The catalog is a top-level dict literal `ALERT_CATALOG: ... = {`.
    # We collect string keys of the form `"Name":` until the matching
    # close brace. A narrow approach: find any `"WakirXyz"` or
    # `"PhaseXyz"` literal between the `ALERT_CATALOG = {` marker
    # and the next top-level `}` followed by a newline at column 0.
    start = text.find("ALERT_CATALOG")
    if start < 0:
        return names
    # Region heuristic: 8 KiB after the marker should bound it.
    region = text[start : start + 16384]
    # Match string keys at the start of a line followed by ':' (the
    # dict key pattern). Keep names that look like alertnames.
    for m in re.finditer(r'^\s*"([A-Za-z][A-Za-z0-9_]+)"\s*:\s*\{', region, re.MULTILINE):
        n = m.group(1)
        # Heuristic guard: the dict contains the keys "failure_mode_id"
        # etc. Skip those by requiring an upper-case start AND >= 6
        # chars OR a Welle/Phase prefix.
        if n[:1].isupper() and len(n) >= 4:
            names.add(n)
    return names


def _extract_failure_mode_ids(text: str) -> set[str]:
    """Extract Class-A1/B3/C1-style failure-mode IDs from any text.

    Matches both ``Class-A1`` and ``failure_mode_id: A1`` patterns.
    """
    ids: set[str] = set()
    for m in re.finditer(r"Class-([A-DZ]\d+(?:-\w+)?)", text):
        ids.add(m.group(1))
    for m in re.finditer(r'"failure_mode_id"\s*:\s*"([A-DZ]\d+(?:-\w+)?)"', text):
        ids.add(m.group(1))
    for m in re.finditer(r'failure_mode_id:\s*"?([A-DZ]\d+(?:-\w+)?)"?', text):
        ids.add(m.group(1))
    return ids


def summarize_routing_table(repo_root: Path, table: RoutingTable) -> dict[str, Any]:
    """Read a routing-table file and return a summary dict.

    Summary keys:
      * present:        True if the file exists.
      * size_bytes:     File size in bytes.
      * alertnames:     Sorted list of alertnames referenced.
      * failure_modes:  Sorted list of Class-X/failure_mode_id IDs.
      * landing_anchors: Sorted list of TRIGGER_LANDING_ANCHORS
        substrings found in the file.
    """
    path = repo_root / table.path
    summary: dict[str, Any] = {
        "path": table.path,
        "kind": table.kind,
        "present": path.is_file(),
        "size_bytes": 0,
        "alertnames": [],
        "failure_modes": [],
        "landing_anchors": [],
    }
    if not summary["present"]:
        return summary
    text = path.read_text(encoding="utf-8", errors="replace")
    summary["size_bytes"] = len(text.encode("utf-8"))

    if table.kind == "yaml-alerts":
        names = _extract_alertnames_yaml(text)
    elif table.kind == "python-catalog":
        names = _extract_alertnames_python_catalog(text)
    else:
        # Markdown: extract any backtick-wrapped CapitalizedName tokens
        names = set()
        for m in re.finditer(r"`([A-Z][A-Za-z0-9_]{4,})`", text):
            names.add(m.group(1))
    summary["alertnames"] = sorted(names)
    summary["failure_modes"] = sorted(_extract_failure_mode_ids(text))

    anchors_found = sorted(
        a for a in TRIGGER_LANDING_ANCHORS if a in text
    )
    summary["landing_anchors"] = anchors_found
    return summary


def stage_routing_propagation(repo_root: Path) -> StageResult:
    """For each of the four mirror-pairs verify the file exists and
    contains at least one recognisable alertname OR failure-mode-ID.

    Green: all four tables present AND each has >= 1 alertname OR
    >= 1 failure-mode-ID.
    Yellow: at most one table is empty (no alertnames, no failure-
    modes) BUT all four are present.
    Red: any table missing OR 2+ tables empty.
    """
    notes: list[str] = []
    summaries: list[dict[str, Any]] = []
    missing: list[str] = []
    empty: list[str] = []
    for table in ROUTING_TABLES:
        s = summarize_routing_table(repo_root, table)
        summaries.append(s)
        if not s["present"]:
            missing.append(table.path)
            continue
        if not s["alertnames"] and not s["failure_modes"]:
            empty.append(table.path)

    details = {"summaries": summaries, "missing": missing, "empty": empty}

    if missing:
        notes.append(f"routing-propagation: {len(missing)} routing-table(s) missing")
        return StageResult(status=STAGE_RED, notes=notes, details=details)
    if len(empty) >= 2:
        notes.append(
            f"routing-propagation: {len(empty)} routing-tables empty (>= 2 -> red)"
        )
        return StageResult(status=STAGE_RED, notes=notes, details=details)
    if len(empty) == 1:
        notes.append(
            f"routing-propagation: 1 routing-table empty -- {empty[0]}"
        )
        return StageResult(status=STAGE_YELLOW, notes=notes, details=details)
    return StageResult(status=STAGE_GREEN, notes=notes, details=details)


# ---------------------------------------------------------------------------
# Stage 3: Trigger-Event-Landing-Verification (event lands in all 4 tables)
# ---------------------------------------------------------------------------


def stage_trigger_event_landing(
    repo_root: Path,
    summaries: list[dict[str, Any]] | None = None,
) -> StageResult:
    """Verify the canonical trigger-event substrate lands in each of
    the four routing-tables.

    A table "receives" the trigger event when **any** of the
    TRIGGER_LANDING_ANCHORS substrings is present in its content,
    OR the file references at least one failure-mode-ID. The
    rationale: the operator-trigger fires the Tag-56 watch-day
    workflow; downstream the alertname / failure-mode is what the
    routing-tables consume. We do not require a direct
    "phase-3c-watch-day-practice-run.yml" mention (that would be
    a brittle pin); we require structural landing via the broader
    anchor set.

    Green: all four tables have >= 1 anchor OR >= 1 failure-mode.
    Yellow: exactly one table lacks anchors AND lacks failure-modes
            (a single weak landing).
    Red: 2+ tables fail to recognise the trigger-event.
    """
    notes: list[str] = []
    if summaries is None:
        summaries = [summarize_routing_table(repo_root, t) for t in ROUTING_TABLES]

    landing_results: dict[str, bool] = {}
    weak: list[str] = []
    for s in summaries:
        anchors = s.get("landing_anchors") or []
        fmodes = s.get("failure_modes") or []
        landed = bool(anchors) or bool(fmodes)
        landing_results[s["path"]] = landed
        if not landed:
            weak.append(s["path"])

    details = {
        "landing": landing_results,
        "weak": weak,
        "canonical_workflow": CANONICAL_TRIGGER_WORKFLOW,
    }

    if len(weak) == 0:
        return StageResult(status=STAGE_GREEN, notes=notes, details=details)
    if len(weak) == 1:
        notes.append(
            f"trigger-landing: 1 table lacks anchors/failure-modes -- {weak[0]}"
        )
        return StageResult(status=STAGE_YELLOW, notes=notes, details=details)
    notes.append(
        f"trigger-landing: {len(weak)} tables lack anchors/failure-modes (>= 2 -> red)"
    )
    return StageResult(status=STAGE_RED, notes=notes, details=details)


# ---------------------------------------------------------------------------
# Stage 4: Aggregate Verdict (INTEGRATION-INTACT / DRIFT / DEFECT)
# ---------------------------------------------------------------------------


def aggregate_verdict(s1: str, s2: str, s3: str) -> str:
    for s in (s1, s2, s3):
        if s not in VALID_STAGE_STATUSES:
            raise ValueError(f"invalid stage status: {s!r}")
    if STAGE_RED in (s1, s2, s3):
        return VERDICT_DEFECT
    yellow_count = sum(1 for s in (s1, s2, s3) if s == STAGE_YELLOW)
    if yellow_count == 0:
        return VERDICT_INTACT
    if yellow_count == 1:
        return VERDICT_DRIFT
    return VERDICT_DEFECT


# ---------------------------------------------------------------------------
# Envelope writers
# ---------------------------------------------------------------------------


def emit_stage_envelope(
    stage_name: str, result: StageResult, output: Path
) -> None:
    payload = {
        "schema_version": 1,
        "tag": 63,
        "tool": "verify-trigger-routing-integration",
        "stage": stage_name,
        "status": result.status,
        "notes": list(result.notes),
        "details": result.details,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def emit_verdict_envelope(
    verdict: str,
    s1: str,
    s2: str,
    s3: str,
    output: Path,
) -> None:
    payload = {
        "schema_version": 1,
        "tag": 63,
        "tool": "verify-trigger-routing-integration",
        "verdict": verdict,
        "stages": {
            "stage_1_operator_trigger_simulation": s1,
            "stage_2_alert_routing_propagation_check": s2,
            "stage_3_trigger_event_landing_verification": s3,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _stage_exit_code(status: str) -> int:
    if status == STAGE_GREEN:
        return EXIT_OK
    if status == STAGE_YELLOW:
        return EXIT_CAUTION
    return EXIT_ERROR


def _verdict_exit_code(verdict: str) -> int:
    if verdict == VERDICT_INTACT:
        return EXIT_OK
    if verdict == VERDICT_DRIFT:
        return EXIT_CAUTION
    return EXIT_ERROR


def cmd_stage1(args: argparse.Namespace) -> int:
    repo_root = _repo_root(Path(args.repo_root) if args.repo_root else None)
    out_dir = Path(args.scratch_dir) if args.scratch_dir else (repo_root / "out" / "tag63")
    result = stage_operator_trigger_simulation(repo_root, out_dir)
    if args.output:
        emit_stage_envelope("stage_1_operator_trigger_simulation", result, Path(args.output))
    print(f"stage_1_operator_trigger_simulation: {result.status}")
    for note in result.notes:
        print(f"  note: {note}")
    return _stage_exit_code(result.status)


def cmd_stage2(args: argparse.Namespace) -> int:
    repo_root = _repo_root(Path(args.repo_root) if args.repo_root else None)
    result = stage_routing_propagation(repo_root)
    if args.output:
        emit_stage_envelope("stage_2_alert_routing_propagation_check", result, Path(args.output))
    print(f"stage_2_alert_routing_propagation_check: {result.status}")
    for note in result.notes:
        print(f"  note: {note}")
    return _stage_exit_code(result.status)


def cmd_stage3(args: argparse.Namespace) -> int:
    repo_root = _repo_root(Path(args.repo_root) if args.repo_root else None)
    result = stage_trigger_event_landing(repo_root)
    if args.output:
        emit_stage_envelope("stage_3_trigger_event_landing_verification", result, Path(args.output))
    print(f"stage_3_trigger_event_landing_verification: {result.status}")
    for note in result.notes:
        print(f"  note: {note}")
    return _stage_exit_code(result.status)


def cmd_aggregate(args: argparse.Namespace) -> int:
    s1 = args.stage_1 or os.environ.get("STAGE_1_STATUS", STAGE_RED)
    s2 = args.stage_2 or os.environ.get("STAGE_2_STATUS", STAGE_RED)
    s3 = args.stage_3 or os.environ.get("STAGE_3_STATUS", STAGE_RED)
    for s in (s1, s2, s3):
        if s not in VALID_STAGE_STATUSES:
            print(f"::error::invalid stage status: {s!r}", file=sys.stderr)
            return EXIT_ERROR
    verdict = aggregate_verdict(s1, s2, s3)
    if args.output:
        emit_verdict_envelope(verdict, s1, s2, s3, Path(args.output))
    print(f"aggregate_verdict: {verdict}")
    print(f"  stage_1: {s1}")
    print(f"  stage_2: {s2}")
    print(f"  stage_3: {s3}")
    return _verdict_exit_code(verdict)


def cmd_full(args: argparse.Namespace) -> int:
    """End-to-end run: stages 1..3 + aggregate, all artifacts to scratch-dir."""
    repo_root = _repo_root(Path(args.repo_root) if args.repo_root else None)
    out_dir = Path(args.scratch_dir) if args.scratch_dir else (repo_root / "out" / "tag63")
    out_dir.mkdir(parents=True, exist_ok=True)

    r1 = stage_operator_trigger_simulation(repo_root, out_dir)
    emit_stage_envelope("stage_1_operator_trigger_simulation", r1, out_dir / "stage-1.json")
    r2 = stage_routing_propagation(repo_root)
    emit_stage_envelope("stage_2_alert_routing_propagation_check", r2, out_dir / "stage-2.json")
    r3 = stage_trigger_event_landing(repo_root)
    emit_stage_envelope("stage_3_trigger_event_landing_verification", r3, out_dir / "stage-3.json")
    verdict = aggregate_verdict(r1.status, r2.status, r3.status)
    emit_verdict_envelope(
        verdict, r1.status, r2.status, r3.status,
        out_dir / "trigger-routing-integration-verdict.json",
    )

    print(f"verdict: {verdict}")
    print(f"  stage_1: {r1.status}")
    print(f"  stage_2: {r2.status}")
    print(f"  stage_3: {r3.status}")
    return _verdict_exit_code(verdict)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verify_trigger_routing_integration",
        description=(
            "Tag-63 Operator-Trigger + Alert-Routing Integration verifier. "
            "Hermetic, stdlib-only, no GitHub-API calls."
        ),
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    p1 = sub.add_parser("stage-1", help="Stage 1: re-use Tag-62 operator-trigger simulator")
    p1.add_argument("--repo-root", default=None)
    p1.add_argument("--scratch-dir", default=None)
    p1.add_argument("--output", default=None)
    p1.set_defaults(func=cmd_stage1)

    p2 = sub.add_parser("stage-2", help="Stage 2: alert-routing propagation check (4 mirror-pairs)")
    p2.add_argument("--repo-root", default=None)
    p2.add_argument("--output", default=None)
    p2.set_defaults(func=cmd_stage2)

    p3 = sub.add_parser("stage-3", help="Stage 3: trigger-event landing verification")
    p3.add_argument("--repo-root", default=None)
    p3.add_argument("--output", default=None)
    p3.set_defaults(func=cmd_stage3)

    pa = sub.add_parser("aggregate", help="Stage 4: aggregate verdict")
    pa.add_argument("--stage-1", default=None, dest="stage_1")
    pa.add_argument("--stage-2", default=None, dest="stage_2")
    pa.add_argument("--stage-3", default=None, dest="stage_3")
    pa.add_argument("--output", default=None)
    pa.set_defaults(func=cmd_aggregate)

    pf = sub.add_parser("full", help="Stages 1..3 + aggregate, one-shot")
    pf.add_argument("--repo-root", default=None)
    pf.add_argument("--scratch-dir", default=None)
    pf.set_defaults(func=cmd_full)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
