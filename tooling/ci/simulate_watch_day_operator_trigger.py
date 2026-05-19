#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-62 Watch-Day Operator-Trigger Pipeline simulator (Noa SRE).

Pre-KW-24-Real-Run simulation helper for the Tag-56 Watch-Day-
Practice-Run CI gate (`.github/workflows/phase-3c-watch-day-
practice-run.yml`). The helper simulates the trigger-sequence the
operator (Mira-Hand) will execute on Cutover-Day T0 (Tue
2026-06-09):

    1. Pre-Trigger Health-Check    --mode pre-trigger
    2. Simulate Operator-Trigger   --mode trigger
    3. Post-Trigger Verification   --mode post-trigger
    4. Aggregate Verdict           --mode aggregate

The four stages compose into a single hermetic CI verdict:

    OPERATOR-TRIGGER-READY    -- all three stages green
    TRIGGER-CAUTION           -- exactly one stage yellow
    TRIGGER-BLOCKED           -- any stage red, or 2+ stages yellow

Coupling
--------

This Tag-62 substrate is **adjacent** to the Tag-56 / Tag-57 /
Tag-59 / Tag-61 substrates that already pin individual contracts
(verdict-formula, cron, path-filter, routing-table, replay-
stability). Tag-62 closes a remaining gap: nothing yet pins the
**operator-trigger-sequence** itself. If the operator's runbook
prescribes "open the Tag-56 workflow in the GitHub UI, click
Run workflow, supply diagnostic=true, watch verdict envelope
upload" and any step of that ceremony silently regresses, the
existing gates do not catch it. Tag-62 pins:

* Pre-trigger checklist: cron-pin INTACT, alert-routing OK,
  replay-fixtures INTACT (three explicit subordinate checks).
* Trigger event-shape: workflow_dispatch envelope matches the
  expected schema (workflow_name, ref, inputs.diagnostic).
* Post-trigger artifact-shape: output envelope JSON well-formed,
  carries verdict + stages map + tag identifier.
* Verdict-stability: post-trigger verdict matches expected READY
  for the GREEN fixture sample.

Hermetic boundary
-----------------

Stdlib + python 3.11. **No** GitHub-API call, **no** podman, no
NATS emit, no Mira-Notify webhook fire, no AlertManager call.
Reads the Tag-56 workflow YAML, the Tag-57 probe verifier helper,
the Tag-59 replay aggregator helper, and (optionally) a Tag-61
fixture artifact, all as on-disk text/JSON.

Exit codes (stable across modes; the workflow's bash dispatch
relies on them)
---------------------------------------------------------------

    0   READY     -- stage green / aggregate READY
    2   CAUTION   -- stage yellow / aggregate CAUTION
    1   BLOCKED   -- stage red / aggregate BLOCKED, or internal
                     error (missing file, malformed JSON)

Author: Noa Bergstroem (SRE)
Anchor: Tag-62 Pre-KW-24-Real-Run Operator-Trigger-Test-Pipeline
        (Marathon-Continuous-Mode).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants. Single-sourced so workflow YAML + tests stay aligned.
# ---------------------------------------------------------------------------

VERDICT_READY = "OPERATOR-TRIGGER-READY"
VERDICT_CAUTION = "TRIGGER-CAUTION"
VERDICT_BLOCKED = "TRIGGER-BLOCKED"

STAGE_GREEN = "green"
STAGE_YELLOW = "yellow"
STAGE_RED = "red"
VALID_STAGE_STATUSES: frozenset[str] = frozenset(
    {STAGE_GREEN, STAGE_YELLOW, STAGE_RED}
)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CAUTION = 2

# Pinned canonical values for the operator-trigger ceremony.
# The operator runbook section "Tag-56 trigger sequence" prescribes
# the value `true` for the diagnostic input; any drift here means
# the runbook and the workflow have diverged.
CANONICAL_WORKFLOW = "phase-3c-watch-day-practice-run.yml"
CANONICAL_REF = "refs/heads/main"
CANONICAL_INPUTS: dict[str, str] = {"diagnostic": "true"}
CANONICAL_DISPATCH_KEYS: tuple[str, ...] = (
    "event",
    "workflow",
    "ref",
    "inputs",
    "actor",
)

# Pre-trigger checklist substrates. Paths are repo-relative.
SUBSTRATE_TAG56_WORKFLOW = ".github/workflows/phase-3c-watch-day-practice-run.yml"
SUBSTRATE_TAG57_PROBE_WORKFLOW = ".github/workflows/watch-day-cron-pre-fire-probe.yml"
SUBSTRATE_TAG59_REPLAY_WORKFLOW = ".github/workflows/watch-day-practice-run-replay.yml"
SUBSTRATE_TAG54_SPEC = "docs/observability/pre-cutover-watch-day-spec.md"
SUBSTRATE_TAG56_AGGREGATOR = "tooling/ci/aggregate_watch_day_practice_run_verdict.py"
SUBSTRATE_TAG57_VERIFIER = "tooling/ci/verify_watch_day_cron_pre_fire_readiness.py"
SUBSTRATE_TAG61_FIXTURES: tuple[str, ...] = (
    "tests/observability/fixtures/watch-day-practice-run-sample-green.json",
    "tests/observability/fixtures/watch-day-practice-run-sample-caution.json",
    "tests/observability/fixtures/watch-day-practice-run-sample-red.json",
)

# Expected aggregate-verdict per fixture set (sampled in post-
# trigger verification stage 3). Pinned by Tag-54 §7.
EXPECTED_VERDICT_PER_FIXTURE: dict[str, str] = {
    "green": "READY",
    "caution": "CAUTION",
    "red": "BLOCK",
}


# ---------------------------------------------------------------------------
# Helpers
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
    # Fall back to walking up from this script.
    here = Path(__file__).resolve()
    return here.parents[2]


def _extract_cron(text: str) -> str | None:
    """Extract the first `cron: "..."` value from a workflow YAML."""
    m = re.search(r'cron:\s*"([^"]+)"', text)
    if m is None:
        return None
    return m.group(1)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Stage 1: Pre-Trigger Health-Check
# ---------------------------------------------------------------------------


def stage_pre_trigger(repo_root: Path) -> StageResult:
    """Three subordinate checks: cron INTACT, alert-routing OK,
    replay-fixtures INTACT.

    All three must be green to return ``green``. Any single red
    subordinate makes the stage red. A subordinate yellow propagates
    as stage yellow.
    """
    sub_results: dict[str, str] = {}
    notes: list[str] = []

    # Subordinate 1: cron-pin INTACT.
    wf_path = repo_root / SUBSTRATE_TAG56_WORKFLOW
    if not wf_path.is_file():
        sub_results["cron_pin"] = STAGE_RED
        notes.append("cron_pin: Tag-56 workflow missing")
    else:
        cron = _extract_cron(wf_path.read_text(encoding="utf-8"))
        if cron is None:
            sub_results["cron_pin"] = STAGE_RED
            notes.append("cron_pin: schedule.cron not found in Tag-56 workflow")
        elif cron != "0 5 * * 2":
            sub_results["cron_pin"] = STAGE_RED
            notes.append(f"cron_pin: drift -- got {cron!r}, expected '0 5 * * 2'")
        else:
            sub_results["cron_pin"] = STAGE_GREEN

    # Subordinate 2: alert-routing OK (spec mentions §6 routing).
    spec_path = repo_root / SUBSTRATE_TAG54_SPEC
    if not spec_path.is_file():
        sub_results["alert_routing"] = STAGE_RED
        notes.append("alert_routing: Tag-54 spec missing")
    else:
        spec_text = spec_path.read_text(encoding="utf-8")
        # Heuristic anchor: the spec must mention both Mira-Notify
        # (Page-class) and inbox/ (Ticket-class) routes by name.
        # A spec edit that removes either is caught.
        has_page = "Mira-Notify" in spec_text or "mira-notify" in spec_text
        has_ticket = "inbox/" in spec_text
        if has_page and has_ticket:
            sub_results["alert_routing"] = STAGE_GREEN
        elif has_page or has_ticket:
            sub_results["alert_routing"] = STAGE_YELLOW
            notes.append(
                "alert_routing: spec missing one of (Mira-Notify | inbox/) anchors"
            )
        else:
            sub_results["alert_routing"] = STAGE_RED
            notes.append(
                "alert_routing: spec missing both Page+Ticket route anchors"
            )

    # Subordinate 3: replay-fixtures INTACT.
    missing = []
    for rel in SUBSTRATE_TAG61_FIXTURES:
        if not (repo_root / rel).is_file():
            missing.append(rel)
    if not missing:
        sub_results["replay_fixtures"] = STAGE_GREEN
    elif len(missing) == len(SUBSTRATE_TAG61_FIXTURES):
        sub_results["replay_fixtures"] = STAGE_RED
        notes.append("replay_fixtures: all three Tag-61 fixtures missing")
    else:
        sub_results["replay_fixtures"] = STAGE_RED
        notes.append(
            f"replay_fixtures: missing {len(missing)}/{len(SUBSTRATE_TAG61_FIXTURES)}: "
            + ", ".join(missing)
        )

    # Aggregate stage status.
    statuses = list(sub_results.values())
    if STAGE_RED in statuses:
        status = STAGE_RED
    elif STAGE_YELLOW in statuses:
        status = STAGE_YELLOW
    else:
        status = STAGE_GREEN

    return StageResult(
        status=status,
        notes=notes,
        details={"subordinates": sub_results},
    )


# ---------------------------------------------------------------------------
# Stage 2: Simulate Operator-Trigger
# ---------------------------------------------------------------------------


def build_dispatch_envelope(
    workflow: str = CANONICAL_WORKFLOW,
    ref: str = CANONICAL_REF,
    inputs: dict[str, str] | None = None,
    actor: str = "mira-kessler",
) -> dict[str, Any]:
    """Synthesize a workflow_dispatch event-shape envelope.

    The envelope is a JSON dict that mirrors what GitHub Actions
    delivers to a workflow_dispatch handler -- minus the noise
    (sender, repository, installation, etc.). We only pin the
    fields the operator runbook references.
    """
    if inputs is None:
        inputs = dict(CANONICAL_INPUTS)
    return {
        "event": "workflow_dispatch",
        "workflow": workflow,
        "ref": ref,
        "inputs": dict(inputs),
        "actor": actor,
    }


def stage_trigger(envelope: dict[str, Any]) -> StageResult:
    """Validate the dispatch envelope shape.

    A green stage requires:
      * envelope.event == "workflow_dispatch"
      * envelope.workflow == CANONICAL_WORKFLOW
      * envelope.ref starts with "refs/" (branch or tag ref)
      * envelope.inputs is a dict, and "diagnostic" key present
        with literal "true" (matches the runbook prescription).
      * envelope contains all CANONICAL_DISPATCH_KEYS.

    Drift on the diagnostic input value is yellow (runbook may
    legitimately override on a hot-fix day); drift on the workflow
    or event-name is red.
    """
    notes: list[str] = []
    status = STAGE_GREEN

    missing_keys = [k for k in CANONICAL_DISPATCH_KEYS if k not in envelope]
    if missing_keys:
        notes.append("trigger: envelope missing keys: " + ",".join(missing_keys))
        return StageResult(status=STAGE_RED, notes=notes, details={"envelope": envelope})

    if envelope.get("event") != "workflow_dispatch":
        notes.append(
            f"trigger: event drift -- got {envelope.get('event')!r}, expected 'workflow_dispatch'"
        )
        status = STAGE_RED

    if envelope.get("workflow") != CANONICAL_WORKFLOW:
        notes.append(
            f"trigger: workflow drift -- got {envelope.get('workflow')!r}, expected {CANONICAL_WORKFLOW!r}"
        )
        status = STAGE_RED

    ref = envelope.get("ref", "")
    if not isinstance(ref, str) or not ref.startswith("refs/"):
        notes.append(f"trigger: ref drift -- got {ref!r}, expected 'refs/...'")
        status = STAGE_RED

    inputs = envelope.get("inputs")
    if not isinstance(inputs, dict):
        notes.append("trigger: inputs not a dict")
        status = STAGE_RED
    else:
        diag = inputs.get("diagnostic")
        if diag is None:
            notes.append("trigger: inputs.diagnostic missing")
            status = STAGE_RED if status != STAGE_RED else status
        elif diag != "true":
            notes.append(
                f"trigger: inputs.diagnostic drift -- got {diag!r}, expected 'true'"
            )
            if status == STAGE_GREEN:
                status = STAGE_YELLOW

    return StageResult(
        status=status,
        notes=notes,
        details={"envelope": envelope},
    )


# ---------------------------------------------------------------------------
# Stage 3: Post-Trigger Verification
# ---------------------------------------------------------------------------


def stage_post_trigger(
    output_envelope: dict[str, Any],
    expected_verdict: str = "READY",
) -> StageResult:
    """Verify the simulated post-trigger output envelope.

    A green stage requires:
      * output_envelope is a dict with keys {schema_version, tag,
        tool, verdict, stages}.
      * tag == 56 (the Tag-56 workflow being simulated).
      * verdict equals expected_verdict.
      * stages is a dict; non-empty.

    Drift on verdict where expected was READY but observed is
    CAUTION/BLOCK is red (operator must not proceed). Drift on
    schema_version is yellow (the envelope is still usable but
    runbook is out-of-date).
    """
    notes: list[str] = []
    status = STAGE_GREEN
    expected_keys = {"schema_version", "tag", "tool", "verdict", "stages"}

    if not isinstance(output_envelope, dict):
        return StageResult(
            status=STAGE_RED,
            notes=["post_trigger: envelope is not a dict"],
            details={},
        )

    missing = expected_keys - set(output_envelope.keys())
    if missing:
        notes.append("post_trigger: envelope missing keys: " + ",".join(sorted(missing)))
        return StageResult(
            status=STAGE_RED,
            notes=notes,
            details={"envelope": output_envelope},
        )

    if output_envelope.get("tag") != 56:
        notes.append(
            f"post_trigger: tag drift -- got {output_envelope.get('tag')!r}, expected 56"
        )
        if status == STAGE_GREEN:
            status = STAGE_YELLOW

    if output_envelope.get("schema_version") != 1:
        notes.append(
            f"post_trigger: schema_version drift -- got {output_envelope.get('schema_version')!r}, expected 1"
        )
        if status == STAGE_GREEN:
            status = STAGE_YELLOW

    actual_verdict = output_envelope.get("verdict")
    if actual_verdict != expected_verdict:
        notes.append(
            f"post_trigger: verdict drift -- got {actual_verdict!r}, expected {expected_verdict!r}"
        )
        status = STAGE_RED

    stages = output_envelope.get("stages")
    if not isinstance(stages, dict) or not stages:
        notes.append("post_trigger: stages map missing or empty")
        status = STAGE_RED

    return StageResult(
        status=status,
        notes=notes,
        details={"envelope": output_envelope, "expected_verdict": expected_verdict},
    )


# ---------------------------------------------------------------------------
# Aggregate verdict
# ---------------------------------------------------------------------------


def aggregate_verdict(
    pre: str,
    trigger: str,
    post: str,
) -> str:
    """Tri-state aggregation:

      OPERATOR-TRIGGER-READY  -- all three stages green
      TRIGGER-CAUTION         -- exactly one stage yellow, rest green
      TRIGGER-BLOCKED         -- any stage red, or 2+ stages yellow
    """
    for s in (pre, trigger, post):
        if s not in VALID_STAGE_STATUSES:
            raise ValueError(f"invalid stage status: {s!r}")
    if STAGE_RED in (pre, trigger, post):
        return VERDICT_BLOCKED
    yellow_count = sum(1 for s in (pre, trigger, post) if s == STAGE_YELLOW)
    if yellow_count == 0:
        return VERDICT_READY
    if yellow_count == 1:
        return VERDICT_CAUTION
    return VERDICT_BLOCKED


def emit_envelope(
    verdict: str,
    pre: str,
    trigger: str,
    post: str,
    output_path: Path,
) -> None:
    payload = {
        "schema_version": 1,
        "tag": 62,
        "tool": "watch-day-operator-trigger-simulation",
        "verdict": verdict,
        "stages": {
            "stage_1_pre_trigger": pre,
            "stage_2_trigger": trigger,
            "stage_3_post_trigger": post,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
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
    if verdict == VERDICT_READY:
        return EXIT_OK
    if verdict == VERDICT_CAUTION:
        return EXIT_CAUTION
    return EXIT_ERROR


def _write_stage_envelope(stage_name: str, result: StageResult, output: Path) -> None:
    payload = {
        "schema_version": 1,
        "tag": 62,
        "tool": "watch-day-operator-trigger-simulation",
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


def cmd_pre_trigger(args: argparse.Namespace) -> int:
    repo_root = _repo_root(Path(args.repo_root) if args.repo_root else None)
    result = stage_pre_trigger(repo_root)
    if args.output:
        _write_stage_envelope("pre_trigger", result, Path(args.output))
    print(f"stage_pre_trigger: {result.status}")
    for note in result.notes:
        print(f"  note: {note}")
    return _stage_exit_code(result.status)


def cmd_trigger(args: argparse.Namespace) -> int:
    inputs = dict(CANONICAL_INPUTS)
    if args.diagnostic_override is not None:
        inputs["diagnostic"] = args.diagnostic_override
    envelope = build_dispatch_envelope(
        workflow=args.workflow,
        ref=args.ref,
        inputs=inputs,
        actor=args.actor,
    )
    result = stage_trigger(envelope)
    if args.output:
        _write_stage_envelope("trigger", result, Path(args.output))
    print(f"stage_trigger: {result.status}")
    for note in result.notes:
        print(f"  note: {note}")
    return _stage_exit_code(result.status)


def cmd_post_trigger(args: argparse.Namespace) -> int:
    repo_root = _repo_root(Path(args.repo_root) if args.repo_root else None)
    fixture_set = args.fixture_set
    expected_verdict = EXPECTED_VERDICT_PER_FIXTURE.get(fixture_set, "READY")

    # Simulate the post-trigger output envelope by reading the
    # committed fixture for the chosen set. The Tag-56 workflow
    # would produce a similarly-shaped envelope on a real run.
    fixture_map = {
        "green": SUBSTRATE_TAG61_FIXTURES[0],
        "caution": SUBSTRATE_TAG61_FIXTURES[1],
        "red": SUBSTRATE_TAG61_FIXTURES[2],
    }
    if fixture_set not in fixture_map:
        print(f"::error::unknown fixture-set: {fixture_set!r}", file=sys.stderr)
        return EXIT_ERROR
    fx_path = repo_root / fixture_map[fixture_set]
    fx_data = _load_json(fx_path)
    if fx_data is None:
        print(f"::error::fixture missing or malformed: {fx_path}", file=sys.stderr)
        return EXIT_ERROR

    # Translate the practice-run fixture into the post-trigger
    # envelope shape that the Tag-56 step-5 aggregator emits.
    if fx_data.get("overall_pass") is True:
        derived_verdict = "READY"
    elif fx_data.get("failed", 0) > 0 and any(
        s.get("sequence_validation_ok") is False
        for s in fx_data.get("scenarios", [])
    ):
        derived_verdict = "BLOCK"
    elif fx_data.get("failed", 0) >= 2:
        derived_verdict = "BLOCK"
    else:
        derived_verdict = "CAUTION"

    output_envelope = {
        "schema_version": 1,
        "tag": 56,
        "tool": "phase-3c-watch-day-practice-run",
        "verdict": derived_verdict,
        "stages": {
            "step_1_inventory": "green",
            "step_2_practice_run": "green" if fx_data.get("overall_pass") else "yellow",
            "step_3_verdict_pin": "green" if fx_data.get("failed", 0) == 0 else "yellow",
            "step_4_sequence_validation": (
                "red"
                if any(
                    s.get("sequence_validation_ok") is False
                    for s in fx_data.get("scenarios", [])
                )
                else "green"
            ),
        },
    }

    result = stage_post_trigger(output_envelope, expected_verdict=expected_verdict)
    if args.output:
        _write_stage_envelope("post_trigger", result, Path(args.output))
    print(f"stage_post_trigger: {result.status} (fixture={fixture_set}, expected={expected_verdict})")
    for note in result.notes:
        print(f"  note: {note}")
    return _stage_exit_code(result.status)


def cmd_emit(args: argparse.Namespace) -> int:
    """Tag-68 surface addition: emit a canonical workflow_dispatch
    envelope to ``--output`` (or stdout if absent).

    The Tag-67 Pre-Cutover Live-Smoke Stage 4 calls this helper as
    ``simulate_watch_day_operator_trigger.py emit --output X`` and
    then asserts the JSON dict has the canonical key-set
    ``{event, workflow, ref, inputs}``. ``emit`` builds that envelope
    via ``build_dispatch_envelope()`` so the Stage-2-trigger
    canonical-shape contract and the Live-Smoke probe stay single-
    sourced. No drift surface.

    Exit codes:
      0  envelope written successfully and shape-valid (green path).
      1  internal error (cannot write to output path).
    """
    inputs = dict(CANONICAL_INPUTS)
    if args.diagnostic_override is not None:
        inputs["diagnostic"] = args.diagnostic_override
    envelope = build_dispatch_envelope(
        workflow=args.workflow,
        ref=args.ref,
        inputs=inputs,
        actor=args.actor,
    )
    # Self-check: the emitted envelope must satisfy the Stage-2
    # trigger validator. If our own canonical builder somehow
    # produced a drifted envelope, fail fast (this catches regressions
    # in CANONICAL_DISPATCH_KEYS vs build_dispatch_envelope drift).
    self_check = stage_trigger(envelope)
    if self_check.status == STAGE_RED:
        print(
            "::error::emit: self-check failed: "
            + "; ".join(self_check.notes),
            file=sys.stderr,
        )
        return EXIT_ERROR
    output_path = Path(args.output) if args.output else None
    if output_path is not None:
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(envelope, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"::error::emit: cannot write {output_path}: {exc}", file=sys.stderr)
            return EXIT_ERROR
    else:
        json.dump(envelope, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    print(f"emit: wrote canonical dispatch envelope (keys={sorted(envelope.keys())})")
    return EXIT_OK


def cmd_aggregate(args: argparse.Namespace) -> int:
    pre = os.environ.get("STAGE_1_STATUS", STAGE_RED)
    trigger = os.environ.get("STAGE_2_STATUS", STAGE_RED)
    post = os.environ.get("STAGE_3_STATUS", STAGE_RED)
    if args.stage_1:
        pre = args.stage_1
    if args.stage_2:
        trigger = args.stage_2
    if args.stage_3:
        post = args.stage_3
    for s in (pre, trigger, post):
        if s not in VALID_STAGE_STATUSES:
            print(f"::error::invalid stage status: {s!r}", file=sys.stderr)
            return EXIT_ERROR
    verdict = aggregate_verdict(pre, trigger, post)
    if args.output:
        emit_envelope(verdict, pre, trigger, post, Path(args.output))
    print(f"aggregate_verdict: {verdict}")
    print(f"  pre_trigger: {pre}")
    print(f"  trigger:     {trigger}")
    print(f"  post_trigger: {post}")
    return _verdict_exit_code(verdict)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simulate_watch_day_operator_trigger",
        description=(
            "Tag-62 Watch-Day Operator-Trigger Pipeline simulator. "
            "Hermetic, stdlib-only, no GitHub-API calls."
        ),
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    p_pre = subparsers.add_parser("pre-trigger", help="Stage 1: pre-trigger health-check")
    p_pre.add_argument("--repo-root", default=None)
    p_pre.add_argument("--output", default=None)
    p_pre.set_defaults(func=cmd_pre_trigger)

    p_trig = subparsers.add_parser("trigger", help="Stage 2: simulate operator-trigger event")
    p_trig.add_argument("--workflow", default=CANONICAL_WORKFLOW)
    p_trig.add_argument("--ref", default=CANONICAL_REF)
    p_trig.add_argument("--actor", default="mira-kessler")
    p_trig.add_argument(
        "--diagnostic-override",
        default=None,
        help="Override the diagnostic input value (default: 'true').",
    )
    p_trig.add_argument("--output", default=None)
    p_trig.set_defaults(func=cmd_trigger)

    p_post = subparsers.add_parser(
        "post-trigger", help="Stage 3: post-trigger verification"
    )
    p_post.add_argument("--repo-root", default=None)
    p_post.add_argument(
        "--fixture-set",
        default="green",
        choices=("green", "caution", "red"),
        help="Which Tag-61 fixture to drive the simulated output envelope from.",
    )
    p_post.add_argument("--output", default=None)
    p_post.set_defaults(func=cmd_post_trigger)

    p_agg = subparsers.add_parser("aggregate", help="Stage 4: aggregate verdict")
    p_agg.add_argument("--stage-1", default=None, dest="stage_1")
    p_agg.add_argument("--stage-2", default=None, dest="stage_2")
    p_agg.add_argument("--stage-3", default=None, dest="stage_3")
    p_agg.add_argument("--output", default=None)
    p_agg.set_defaults(func=cmd_aggregate)

    # Tag-68 addition: emit subcommand for Pre-Cutover Live-Smoke
    # Stage 4. Builds the canonical workflow_dispatch envelope and
    # writes it to --output as JSON (or stdout).
    p_emit = subparsers.add_parser(
        "emit",
        help=(
            "Tag-68: emit canonical workflow_dispatch envelope JSON "
            "(used by Tag-67 Live-Smoke Stage 4)"
        ),
    )
    p_emit.add_argument("--workflow", default=CANONICAL_WORKFLOW)
    p_emit.add_argument("--ref", default=CANONICAL_REF)
    p_emit.add_argument("--actor", default="mira-kessler")
    p_emit.add_argument(
        "--diagnostic-override",
        default=None,
        help="Override the diagnostic input value (default: 'true').",
    )
    p_emit.add_argument("--output", default=None)
    p_emit.set_defaults(func=cmd_emit)

    return parser


# Tag-68 addition: legacy --mode <name> invocation surface.
# The Tag-67 Pre-Cutover Live-Smoke Stage 4 invokes this script as
# `python simulate_watch_day_operator_trigger.py --mode emit --output X`,
# i.e. with a top-level --mode flag rather than the subcommand-style
# positional. We translate that surface to the subcommand surface to
# avoid drift between caller-style and parser-style. Subcommand-style
# invocations continue to work unchanged.
_MODE_FLAG_ALIASES: dict[str, str] = {
    "pre-trigger": "pre-trigger",
    "trigger": "trigger",
    "post-trigger": "post-trigger",
    "aggregate": "aggregate",
    "emit": "emit",
}


def _rewrite_mode_flag(argv: list[str]) -> list[str]:
    """Translate '--mode <name> ...' to '<name> ...' for argparse.

    If ``--mode <name>`` is the first or second token (with no
    preceding subcommand) and ``<name>`` is a known subcommand, we
    replace those two tokens with the bare subcommand name. This
    keeps the helper invocable both as a subcommand-style CLI and as
    a flag-style CLI without forking the parser.
    """
    if not argv:
        return argv
    # Find a leading '--mode <name>' pair before any subcommand token.
    out: list[str] = list(argv)
    for i, tok in enumerate(out):
        if tok in _MODE_FLAG_ALIASES:
            # Subcommand-style: nothing to do.
            return out
        if tok == "--mode" and i + 1 < len(out):
            name = out[i + 1]
            if name in _MODE_FLAG_ALIASES:
                return out[:i] + [_MODE_FLAG_ALIASES[name]] + out[i + 2:]
        if tok.startswith("--mode="):
            name = tok.split("=", 1)[1]
            if name in _MODE_FLAG_ALIASES:
                return out[:i] + [_MODE_FLAG_ALIASES[name]] + out[i + 1:]
    return out


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    argv = _rewrite_mode_flag(list(argv))
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
