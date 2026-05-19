#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-67 Watch-Day Pre-Cutover Live-Smoke aggregator (Noa SRE).

Context
-------

Tag-56..Tag-66 shipped, piece-by-piece, the substrate that makes the
Watch-Day Practice-Run a defensible Pre-Cutover gate:

    Tag-56  Watch-Day-Practice-Run CI-Gate (phase-3c-watch-day-practice-run)
    Tag-57  Cron-Pre-Fire Probe (watch-day-cron-pre-fire-probe)
    Tag-59  Replay Workflow (watch-day-practice-run-replay)
    Tag-61  Multi-Sample Replay extension
    Tag-62  Operator-Trigger Pipeline (watch-day-operator-trigger-simulation)
    Tag-63  Operator-Trigger + Alert-Routing Integration
            (operator-trigger-alert-routing-integration)
    Tag-66  Operator-Trigger Audit-Trail Verifier
            (watch-day-operator-trigger-audit-trail-verify)

Each piece is a hermetic gate. Each piece runs in its own CI workflow.
What none of them does -- before Tag-67 -- is run **all six pieces, in
sequence, as one End-to-End hermetic Pre-Cutover probe**, and emit a
single tri-state verdict that says "the entire Coupling-Map between
Tag-54 and Tag-66 holds today".

Failure mode without Tag-67
---------------------------

The operator runs the Tag-56 workflow on Cutover-Day-Eve to "do a
final dry-run". Practice-Run is green. The operator declares all-
clear. But:

    * Tag-57 cron-pre-fire never re-ran -- the CronSpec drifted.
    * Tag-59 replay never re-ran -- the pinned fixture diverged.
    * Tag-62 operator-trigger simulator was never invoked -- the
      envelope shape regressed.
    * Tag-63 alert-routing integration was never invoked -- the
      routing table forgot the source.
    * Tag-66 audit-trail-verifier never re-ran -- the audit-marker
      catalog drifted.

Cutover-Day fires. The audit-trail is unverifiable because nobody
checked that all six gates *together* stayed green at the same
moment. Tag-67 closes that gap.

Six-stage aggregate verdict
---------------------------

Reads ``STAGE1_STATUS``..``STAGE6_STATUS`` from the environment and
emits a JSON verdict-envelope to ``--output``. Each stage is one of
``green`` / ``yellow`` / ``red``.

Verdict rules (single-sourced, mirrored in tests + workflow YAML):

    * LIVE-SMOKE-INTACT  -- all six stages green.
    * DRIFT              -- 1..2 stages yellow, the rest green,
                            no red.
    * DEFECT             -- any stage red, or >=3 stages yellow.

The thresholds are deliberately stricter than the Tag-56 4-stage
aggregator (which allowed exactly one yellow as CAUTION). The
Pre-Cutover probe runs at T-minus-hours to Cutover; the bar to
declare DRIFT versus DEFECT must be tight.

Modes
-----

* ``aggregate`` (default) -- reads ``STAGE1_STATUS``..``STAGE6_STATUS``
  from environment, emits verdict envelope.

* ``pin-substrate`` -- verify the substrate-inventory (workflows +
  helpers + tests) referenced by Tag-67 actually exists on disk.
  Used by tests to catch substrate-deletion-drift between Tag-56..66.

* ``coupling-map`` -- emit the canonical Tag-54..66 coupling-map as
  JSON for diagnostics. Used by tests + the workflow's diagnostic
  summary step.

The module is pure-stdlib. No third-party dependencies installed
in the workflow runner.

Anchor: Tag-67 Marathon-Continuous-Mode Pre-KW-24 Watch-Day
        Pre-Cutover Live-Smoke aggregator.
Author: Noa Bergstroem (SRE)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Substrate inventory. Single source of truth: every workflow + helper
# + test the Tag-67 live-smoke depends on.
# ---------------------------------------------------------------------------

# (anchor-tag, kind, path-relative-to-repo-root)
SUBSTRATE_INVENTORY: tuple[tuple[str, str, str], ...] = (
    # Tag-56 Practice-Run CI-Gate
    ("Tag-56", "workflow", ".github/workflows/phase-3c-watch-day-practice-run.yml"),
    ("Tag-56", "helper", "tooling/ci/aggregate_watch_day_practice_run_verdict.py"),
    ("Tag-56", "test", "tests/observability/test_watch_day_practice_run.py"),
    # Tag-57 Cron-Pre-Fire Probe
    ("Tag-57", "workflow", ".github/workflows/watch-day-cron-pre-fire-probe.yml"),
    (
        "Tag-57",
        "helper",
        "tooling/ci/verify_watch_day_cron_pre_fire_readiness.py",
    ),
    (
        "Tag-57",
        "test",
        "tests/observability/test_watch_day_cron_pre_fire_probe_tag57.py",
    ),
    # Tag-59 Replay Workflow
    (
        "Tag-59",
        "workflow",
        ".github/workflows/watch-day-practice-run-replay.yml",
    ),
    (
        "Tag-59",
        "test",
        "tests/observability/test_watch_day_practice_run_replay_tag59.py",
    ),
    # Tag-61 Multi-Sample Replay extension
    (
        "Tag-61",
        "test",
        "tests/observability/test_watch_day_replay_multi_sample_tag61.py",
    ),
    # Tag-62 Operator-Trigger Pipeline
    (
        "Tag-62",
        "workflow",
        ".github/workflows/watch-day-operator-trigger-simulation.yml",
    ),
    ("Tag-62", "helper", "tooling/ci/simulate_watch_day_operator_trigger.py"),
    (
        "Tag-62",
        "test",
        "tests/observability/test_watch_day_operator_trigger_pipeline_tag62.py",
    ),
    # Tag-63 Operator-Trigger + Alert-Routing Integration
    (
        "Tag-63",
        "workflow",
        ".github/workflows/operator-trigger-alert-routing-integration.yml",
    ),
    # Tag-66 Audit-Trail Verifier
    (
        "Tag-66",
        "workflow",
        ".github/workflows/watch-day-operator-trigger-audit-trail-verify.yml",
    ),
    (
        "Tag-66",
        "helper",
        "tooling/ci/verify_watch_day_operator_trigger_audit_trail.py",
    ),
    (
        "Tag-66",
        "test",
        "tests/observability/test_watch_day_audit_trail_tag66.py",
    ),
)


STAGE_KEYS: tuple[str, ...] = (
    "STAGE1_STATUS",
    "STAGE2_STATUS",
    "STAGE3_STATUS",
    "STAGE4_STATUS",
    "STAGE5_STATUS",
    "STAGE6_STATUS",
)


STAGE_LABELS: tuple[str, ...] = (
    "practice-run-ci-gate",         # Tag-56
    "cron-pre-fire-probe",          # Tag-57
    "replay-multi-sample",          # Tag-59 + Tag-61
    "operator-trigger-integration", # Tag-62 + Tag-63
    "audit-trail-verify",           # Tag-66
    "substrate-coupling-map",       # Tag-67 cross-check
)


VALID_STATUSES: frozenset[str] = frozenset({"green", "yellow", "red"})

VERDICT_INTACT = "LIVE-SMOKE-INTACT"
VERDICT_DRIFT = "DRIFT"
VERDICT_DEFECT = "DEFECT"


EXIT_OK = 0
EXIT_ERROR = 1
EXIT_DIVERGED = 2


# ---------------------------------------------------------------------------
# Mode: aggregate
# ---------------------------------------------------------------------------


def _classify_verdict(statuses: list[str]) -> str:
    if any(s == "red" for s in statuses):
        return VERDICT_DEFECT
    yellow_count = sum(1 for s in statuses if s == "yellow")
    if yellow_count == 0:
        return VERDICT_INTACT
    if yellow_count <= 2:
        return VERDICT_DRIFT
    return VERDICT_DEFECT


def _read_env_statuses(env: dict[str, str]) -> tuple[list[str] | None, str | None]:
    out: list[str] = []
    for key in STAGE_KEYS:
        raw = env.get(key, "")
        if raw == "":
            return None, f"missing env var: {key}"
        norm = raw.strip().lower()
        if norm not in VALID_STATUSES:
            return None, f"invalid status for {key}: {raw!r}"
        out.append(norm)
    return out, None


def _aggregate(args: argparse.Namespace, env: dict[str, str]) -> int:
    statuses, err = _read_env_statuses(env)
    if statuses is None:
        print(f"::error::{err}", file=sys.stderr)
        return EXIT_ERROR
    verdict = _classify_verdict(statuses)
    envelope = {
        "kind": "watch-day-pre-cutover-live-smoke-verdict",
        "verdict": verdict,
        "stages": [
            {"index": i + 1, "label": STAGE_LABELS[i], "status": statuses[i]}
            for i in range(len(STAGE_KEYS))
        ],
        "anchor": "Tag-67 Pre-Cutover Live-Smoke",
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n")
    print(f"verdict: {verdict}")
    for stage in envelope["stages"]:
        print(f"  stage {stage['index']} ({stage['label']}): {stage['status']}")
    if verdict == VERDICT_INTACT:
        return EXIT_OK
    if verdict == VERDICT_DRIFT:
        return EXIT_DIVERGED
    return EXIT_DIVERGED  # DEFECT also non-zero so the workflow step fails


# ---------------------------------------------------------------------------
# Mode: pin-substrate
# ---------------------------------------------------------------------------


def _pin_substrate(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    missing: list[tuple[str, str, str]] = []
    for tag, kind, rel in SUBSTRATE_INVENTORY:
        if not (repo_root / rel).is_file():
            missing.append((tag, kind, rel))
    if missing:
        for tag, kind, rel in missing:
            print(
                f"::error::substrate missing ({tag}, {kind}): {rel}",
                file=sys.stderr,
            )
        return EXIT_DIVERGED
    print(f"substrate-inventory OK: {len(SUBSTRATE_INVENTORY)} items present")
    return EXIT_OK


# ---------------------------------------------------------------------------
# Mode: coupling-map
# ---------------------------------------------------------------------------


def _coupling_map(args: argparse.Namespace) -> int:
    # Group inventory by anchor tag, preserve order.
    groups: dict[str, list[dict[str, str]]] = {}
    for tag, kind, rel in SUBSTRATE_INVENTORY:
        groups.setdefault(tag, []).append({"kind": kind, "path": rel})
    envelope = {
        "kind": "watch-day-pre-cutover-live-smoke-coupling-map",
        "anchor": "Tag-67 Pre-Cutover Live-Smoke",
        "tags": [
            {"tag": tag, "items": groups[tag]} for tag in groups
        ],
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n")
    print(f"coupling-map written: {out_path}")
    return EXIT_OK


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aggregate_watch_day_pre_cutover_live_smoke",
        description=(
            "Tag-67 Watch-Day Pre-Cutover Live-Smoke aggregator: "
            "tri-state verdict over six stages spanning Tag-56..66."
        ),
    )
    sub = p.add_subparsers(dest="mode", required=True)

    p_agg = sub.add_parser("aggregate", help="emit verdict from env STAGEn_STATUS")
    p_agg.add_argument("--output", required=True, help="path to verdict JSON")

    p_pin = sub.add_parser("pin-substrate", help="verify substrate inventory exists")
    p_pin.add_argument("--repo-root", required=True)

    p_cm = sub.add_parser("coupling-map", help="emit canonical coupling-map JSON")
    p_cm.add_argument("--output", required=True)

    return p


def main(argv: list[str] | None = None, env: dict[str, str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    env = env if env is not None else dict(os.environ)
    if args.mode == "aggregate":
        return _aggregate(args, env)
    if args.mode == "pin-substrate":
        return _pin_substrate(args)
    if args.mode == "coupling-map":
        return _coupling_map(args)
    parser.error(f"unknown mode: {args.mode}")
    return EXIT_ERROR  # unreachable, parser.error exits


if __name__ == "__main__":
    sys.exit(main())
