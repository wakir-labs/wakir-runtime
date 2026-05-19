#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-66 Watch-Day Operator-Trigger Audit-Trail verifier (Noa SRE).

Context
-------

Tag-62 (PR #397) shipped the Watch-Day Operator-Trigger Pipeline
simulator. Tag-63 (PR #402) wired the Operator-Trigger + Alert-
Routing integration. Both substrates pin *what* the operator emits
on Cutover-Day T0 (Tue 2026-06-09 05:00 UTC) and *which* routing
table receives the event. Neither pins the **audit-trail conformance
of every individual trigger-event**: that each event the operator
(Mira-Hand) emits carries the canonical audit-trail-marker set
(workflow_name, ref, actor, dispatched_at, audit_marker_tag, trigger
sequence_id) so the post-mortem reconstruction is non-ambiguous.

Sibling concern: Tomás' Tag-66 AR-Override-Audit-Trail verifier pins
the analogous property for AR-hand override-flag events. This Tag-66
helper pins the same property for the operator-trigger side of the
Cutover-Day pipeline.

Without Tag-66 the failure mode is:

    The operator runs the Tag-56 workflow on Cutover-Day. The
    workflow_dispatch envelope is well-formed (Tag-62 green), the
    alert-routing recognises the source (Tag-63 green), but the
    envelope carries no actor field, no audit_marker_tag, and no
    dispatched_at timestamp -- the Mira-Hand-signature is missing.
    A post-incident audit cannot reconstruct *who* triggered *what*
    *when*, only that *something* dispatched. Tag-66 closes that gap.

Four-stage hermetic verdict
---------------------------

    Stage 1  Trigger-Event-Schema-Audit
             ---------------------------
             For every trigger-event envelope produced by the Tag-62
             simulator (single canonical envelope, or a fixture file
             containing one or more historical envelopes), verify the
             canonical audit-marker key-set is present:
                 - event ("workflow_dispatch")
                 - workflow (CANONICAL_WORKFLOW)
                 - ref (CANONICAL_REF)
                 - inputs (mapping; diagnostic key present)
                 - actor (non-empty string)
                 - dispatched_at (ISO-8601-ish timestamp)
                 - audit_marker_tag (matches AUDIT_MARKER_TAG_PATTERN)
                 - trigger_sequence_id (uuid-shaped string)
             Green: all required keys present + well-shaped.
             Yellow: actor / dispatched_at / sequence_id missing but
                     event/workflow/ref/inputs present (legacy
                     envelope shape pre-Tag-66).
             Red: event/workflow/ref/inputs missing or audit_marker_tag
                  malformed.

    Stage 2  Marker-Tag-Catalog-Conformance
             -------------------------------
             The audit_marker_tag value must match a recognised
             marker class in the canonical Audit-Trail-Marker
             catalog (see AUDIT_MARKER_CATALOG). The catalog
             enumerates the legitimate trigger sources (operator-
             hand, ar-hand, scheduled-cron, replay-driver). An
             unknown tag is red; a recognised tag but with the
             wrong source-class for a workflow_dispatch event is
             yellow.

    Stage 3  Cross-Substrate-Marker-Reference-Check
             ---------------------------------------
             Verify the canonical AUDIT_MARKER_CATALOG entries are
             *referenced* by the audit-trail downstream substrates:
                 - docs/observability/pre-mortem-failure-mode-notify-catalog.md
                 - dashboards/phase-3-marathon-alerts.yaml
                 - scripts/observability/alert-rule-to-mira-notify-bridge.py
             Each marker class must surface in at least one substrate
             (so the post-mortem timeline reconstruction has an
             entry-point). A marker class referenced by zero
             substrates is a yellow "orphan-marker" signal.

    Stage 4  Aggregate Verdict
             -----------------
             AUDIT-TRAIL-INTACT    -- all three stages green
             AUDIT-TRAIL-DRIFT     -- exactly one stage yellow,
                                      others green
             AUDIT-TRAIL-DEFECT    -- any stage red, or 2+ stages
                                      yellow

Hermetic boundary
-----------------

stdlib + python 3.11. **No** GitHub-API call, **no** podman, no
NATS emit, no Mira-Notify webhook fire, no AlertManager call. Reads
only on-disk text/JSON files (the Tag-62 simulator helper invoked
via subprocess + optional fixture envelopes + three downstream
substrate files).

Reuses the Tag-62 simulator via subprocess (not import) so the
Tag-62 contract stays stable. If the Tag-62 simulator CLI surface
regresses, Tag-66 Stage 1 fails red.

Exit codes (stable across modes; the workflow YAML dispatch relies
on them)
--------------------------------------------------------------

    0   AUDIT-TRAIL-INTACT or stage green
    2   AUDIT-TRAIL-DRIFT or stage yellow
    1   AUDIT-TRAIL-DEFECT, stage red, or invocation error

Author: Noa Bergstroem (SRE)
Anchor: Tag-66 Pre-KW-24 Watch-Day Operator-Trigger Audit-Trail
        Verifier (Marathon-Continuous-Mode).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Verdict constants (single-sourced; workflow YAML + tests rely on these)
# ---------------------------------------------------------------------------

VERDICT_INTACT = "AUDIT-TRAIL-INTACT"
VERDICT_DRIFT = "AUDIT-TRAIL-DRIFT"
VERDICT_DEFECT = "AUDIT-TRAIL-DEFECT"

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
# Canonical audit-marker schema. Tag-62 envelope schema + audit-trail
# overlay. The required-key set is the Tag-66 contract.
# ---------------------------------------------------------------------------


CANONICAL_EVENT = "workflow_dispatch"
CANONICAL_WORKFLOW = "phase-3c-watch-day-practice-run.yml"
CANONICAL_REF = "refs/heads/main"

# Required keys for full Tag-66-conformant envelope.
AUDIT_MARKER_REQUIRED_KEYS: tuple[str, ...] = (
    "event",
    "workflow",
    "ref",
    "inputs",
    "actor",
    "dispatched_at",
    "audit_marker_tag",
    "trigger_sequence_id",
)

# Subset required for "envelope at least matches Tag-62 pre-audit-trail
# shape". Missing audit-only keys downgrade to yellow, not red.
TAG62_BASE_KEYS: tuple[str, ...] = (
    "event",
    "workflow",
    "ref",
    "inputs",
)

AUDIT_ONLY_KEYS: tuple[str, ...] = (
    "actor",
    "dispatched_at",
    "audit_marker_tag",
    "trigger_sequence_id",
)

# Audit-marker-tag pattern: "watch-day-<source>-<YYYYMMDD>-<short-hash>".
# Example: "watch-day-operator-20260609-3bc7794"
AUDIT_MARKER_TAG_PATTERN = re.compile(
    r"^watch-day-(operator|ar|cron|replay)-(\d{8})-([0-9a-f]{7,12})$"
)

# ISO-8601-ish dispatched_at: "YYYY-MM-DDThh:mm:ss[Z|+HH:MM]". Tolerant
# of micro-seconds.
DISPATCHED_AT_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?$"
)

# trigger_sequence_id: canonical UUIDv4 string (Tag-62 simulator
# generates these via uuid.uuid4()).
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Audit-Marker-Catalog. The four source-classes enumerate every
# legitimate trigger origin that produces an audit-trail event in
# Phase-3 Marathon Cutover-Day. The catalog is single-sourced here;
# downstream substrates (notify-catalog markdown, alert rules,
# bridge ALERT_CATALOG) must reference at least one marker class.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MarkerClass:
    name: str          # short label, single token, lower-kebab.
    source: str        # tag-fragment used in audit_marker_tag.
    description: str   # one-line operator-facing description.
    expected_event: str  # which GitHub event-type emits this class.


AUDIT_MARKER_CATALOG: tuple[MarkerClass, ...] = (
    MarkerClass(
        name="operator-hand-dispatch",
        source="operator",
        description="Mira-Hand operator clicks Run workflow on Cutover-Day T0.",
        expected_event="workflow_dispatch",
    ),
    MarkerClass(
        name="ar-hand-override",
        source="ar",
        description="Aufsichtsrat override-flag dispatch (rare; Tag-65 AR listener).",
        expected_event="workflow_dispatch",
    ),
    MarkerClass(
        name="scheduled-cron",
        source="cron",
        description="Calendar-pinned cron trigger (Tag-56 watch-day, Tue 05:00 UTC).",
        expected_event="schedule",
    ),
    MarkerClass(
        name="replay-driver",
        source="replay",
        description="Tag-59 replay-driver re-dispatch for post-incident reconstruction.",
        expected_event="workflow_dispatch",
    ),
)

CATALOG_BY_SOURCE: dict[str, MarkerClass] = {
    m.source: m for m in AUDIT_MARKER_CATALOG
}

# Cross-substrate references the catalog must surface in. Each substrate
# file must reference at least one marker class (by name or source
# token) so the audit-trail timeline reconstruction has an entry-point.
DOWNSTREAM_SUBSTRATES: tuple[str, ...] = (
    # Canonical Tag-66 marker-catalog (single-source-of-truth; enumerates
    # every marker class by name + source-token explicitly).
    "docs/observability/watch-day-operator-trigger-audit-trail-marker-catalog.md",
    "docs/observability/pre-mortem-failure-mode-notify-catalog.md",
    "dashboards/phase-3-marathon-alerts.yaml",
    "scripts/observability/alert-rule-to-mira-notify-bridge.py",
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
# Envelope synthesis (when no fixture is supplied, synthesize a single
# canonical Tag-66-conformant envelope and write it next to the
# trigger-envelope produced by the Tag-62 simulator).
# ---------------------------------------------------------------------------


TAG62_HELPER_REL = "tooling/ci/simulate_watch_day_operator_trigger.py"


def synthesize_audit_trail_envelope(
    workflow: str = CANONICAL_WORKFLOW,
    ref: str = CANONICAL_REF,
    actor: str = "mira-hand-operator",
    dispatched_at: str = "2026-06-09T05:00:00Z",
    audit_source: str = "operator",
    short_hash: str = "3bc7794",
    sequence_id: str | None = None,
    diagnostic: str = "true",
) -> dict[str, Any]:
    """Synthesize a canonical Tag-66-conformant audit-trail envelope.

    Used by stage 1 when no fixture file is provided; also re-usable
    from tests to assert the shape contract.
    """
    if sequence_id is None:
        sequence_id = str(uuid.uuid4())
    # Tag-form: watch-day-<source>-YYYYMMDD-<short-hash>.
    date_part = dispatched_at[:10].replace("-", "")
    tag = f"watch-day-{audit_source}-{date_part}-{short_hash}"
    return {
        "event": CANONICAL_EVENT,
        "workflow": workflow,
        "ref": ref,
        "inputs": {"diagnostic": diagnostic},
        "actor": actor,
        "dispatched_at": dispatched_at,
        "audit_marker_tag": tag,
        "trigger_sequence_id": sequence_id,
    }


def _load_envelopes_from_fixture(path: Path) -> list[dict[str, Any]]:
    """Load one or more envelopes from a fixture file.

    The fixture may be a single JSON object (one envelope) or a JSON
    array of objects (multiple historical envelopes). Other shapes
    raise ValueError.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        out: list[dict[str, Any]] = []
        for i, item in enumerate(payload):
            if not isinstance(item, dict):
                raise ValueError(
                    f"fixture {path}: item {i} not an object"
                )
            out.append(item)
        return out
    raise ValueError(
        f"fixture {path}: top-level must be object or array, got {type(payload).__name__}"
    )


def _shape_envelope(envelope: dict[str, Any]) -> tuple[str, list[str]]:
    """Classify a single envelope as green/yellow/red.

    Returns (status, notes_for_this_envelope).
    """
    notes: list[str] = []
    # 1. Base Tag-62 keys must be present.
    missing_base = [k for k in TAG62_BASE_KEYS if k not in envelope]
    if missing_base:
        notes.append(f"missing-base-keys: {sorted(missing_base)}")
        return STAGE_RED, notes

    # 2. event/workflow/ref shape checks.
    if envelope["event"] != CANONICAL_EVENT:
        notes.append(
            f"event-mismatch: expected {CANONICAL_EVENT!r}, got {envelope['event']!r}"
        )
        return STAGE_RED, notes
    if not isinstance(envelope["inputs"], dict):
        notes.append("inputs-not-mapping")
        return STAGE_RED, notes

    # 3. Audit-only keys: missing = yellow (legacy Tag-62 shape).
    missing_audit = [k for k in AUDIT_ONLY_KEYS if k not in envelope]
    if missing_audit:
        notes.append(f"audit-keys-missing: {sorted(missing_audit)}")
        return STAGE_YELLOW, notes

    # 4. actor must be non-empty string.
    actor = envelope["actor"]
    if not isinstance(actor, str) or not actor.strip():
        notes.append("actor-empty-or-non-string")
        return STAGE_RED, notes

    # 5. dispatched_at must match ISO-8601-ish pattern.
    dispatched_at = envelope["dispatched_at"]
    if not isinstance(dispatched_at, str) or not DISPATCHED_AT_PATTERN.match(
        dispatched_at
    ):
        notes.append(f"dispatched-at-malformed: {dispatched_at!r}")
        return STAGE_RED, notes

    # 6. audit_marker_tag must match canonical pattern.
    tag = envelope["audit_marker_tag"]
    if not isinstance(tag, str) or not AUDIT_MARKER_TAG_PATTERN.match(tag):
        notes.append(f"audit-marker-tag-malformed: {tag!r}")
        return STAGE_RED, notes

    # 7. trigger_sequence_id must be UUID-shaped.
    seq = envelope["trigger_sequence_id"]
    if not isinstance(seq, str) or not UUID_PATTERN.match(seq):
        notes.append(f"trigger-sequence-id-malformed: {seq!r}")
        return STAGE_RED, notes

    return STAGE_GREEN, notes


# ---------------------------------------------------------------------------
# Stage 1: Trigger-Event-Schema-Audit
# ---------------------------------------------------------------------------


def stage_trigger_event_schema_audit(
    repo_root: Path,
    output_dir: Path,
    fixture: Path | None = None,
) -> StageResult:
    """Audit one or more trigger envelopes for canonical audit-marker
    key-set conformance.

    If ``fixture`` is provided, load envelopes from it. Else drive the
    Tag-62 simulator to produce one canonical envelope, then overlay
    the synthesized audit-trail keys.

    Stage status:
        green: all envelopes individually green.
        yellow: at least one yellow, no reds.
        red: any envelope red, or driver subprocess failed, or fixture
             unloadable.
    """
    notes: list[str] = []
    output_dir.mkdir(parents=True, exist_ok=True)

    envelopes: list[dict[str, Any]] = []
    per_envelope_results: list[dict[str, Any]] = []

    if fixture is not None:
        if not fixture.is_file():
            return StageResult(
                status=STAGE_RED,
                notes=[f"fixture-missing: {fixture}"],
                details={},
            )
        try:
            envelopes = _load_envelopes_from_fixture(fixture)
        except (json.JSONDecodeError, ValueError) as exc:
            return StageResult(
                status=STAGE_RED,
                notes=[f"fixture-malformed: {exc!r}"],
                details={},
            )
        if not envelopes:
            return StageResult(
                status=STAGE_RED,
                notes=["fixture-empty"],
                details={},
            )
    else:
        # Drive Tag-62 simulator + synthesize audit-trail overlay.
        helper = repo_root / TAG62_HELPER_REL
        if not helper.is_file():
            return StageResult(
                status=STAGE_RED,
                notes=[f"tag62-helper-missing: {TAG62_HELPER_REL}"],
                details={},
            )
        tag62_out = output_dir / "tag62-trigger-envelope.json"
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    str(helper),
                    "trigger",
                    "--output",
                    str(tag62_out),
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
        if proc.returncode not in (0, 2):
            return StageResult(
                status=STAGE_RED,
                notes=[
                    f"tag62-rc-unexpected: {proc.returncode}",
                    f"stderr: {proc.stderr.strip()[:200]}",
                ],
                details={},
            )
        if not tag62_out.is_file():
            return StageResult(
                status=STAGE_RED,
                notes=["tag62-envelope-not-written"],
                details={},
            )
        try:
            tag62_env = json.loads(tag62_out.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return StageResult(
                status=STAGE_RED,
                notes=[f"tag62-envelope-malformed: {exc!r}"],
                details={},
            )
        # Tag-62 envelope shape is the inner dispatch envelope from the
        # simulator. Synthesize the audit-trail overlay and merge.
        audit_overlay = synthesize_audit_trail_envelope()
        merged = dict(tag62_env)
        for k in AUDIT_ONLY_KEYS:
            merged.setdefault(k, audit_overlay[k])
        # Pin the canonical event/workflow/ref/inputs to the Tag-62
        # values where present; fall back to canonical defaults.
        merged.setdefault("event", CANONICAL_EVENT)
        merged.setdefault("workflow", CANONICAL_WORKFLOW)
        merged.setdefault("ref", CANONICAL_REF)
        merged.setdefault("inputs", {"diagnostic": "true"})
        envelopes = [merged]

    # Classify each envelope.
    statuses: list[str] = []
    for idx, env in enumerate(envelopes):
        st, per_notes = _shape_envelope(env)
        per_envelope_results.append(
            {
                "index": idx,
                "status": st,
                "notes": per_notes,
                "audit_marker_tag": env.get("audit_marker_tag"),
                "actor": env.get("actor"),
            }
        )
        statuses.append(st)

    if STAGE_RED in statuses:
        agg = STAGE_RED
    elif STAGE_YELLOW in statuses:
        agg = STAGE_YELLOW
    else:
        agg = STAGE_GREEN

    notes.append(f"envelopes-audited: {len(envelopes)}")
    notes.append(
        f"counts: green={statuses.count(STAGE_GREEN)} "
        f"yellow={statuses.count(STAGE_YELLOW)} red={statuses.count(STAGE_RED)}"
    )

    return StageResult(
        status=agg,
        notes=notes,
        details={"envelopes": per_envelope_results},
    )


# ---------------------------------------------------------------------------
# Stage 2: Marker-Tag-Catalog-Conformance
# ---------------------------------------------------------------------------


def _classify_marker_tag(tag: str) -> tuple[str, str | None, list[str]]:
    """Classify a single audit_marker_tag against AUDIT_MARKER_CATALOG.

    Returns (status, matched_source_or_none, notes).
        green: tag matches pattern + source is recognised + source's
               expected_event is "workflow_dispatch".
        yellow: tag matches pattern + source recognised, but source's
                expected_event != "workflow_dispatch" (i.e., scheduled-
                cron tag used in a workflow_dispatch event).
        red: tag does not match pattern, or source is not in catalog.
    """
    m = AUDIT_MARKER_TAG_PATTERN.match(tag)
    if m is None:
        return STAGE_RED, None, [f"tag-malformed: {tag!r}"]
    source = m.group(1)
    if source not in CATALOG_BY_SOURCE:
        return STAGE_RED, None, [f"unknown-source: {source!r}"]
    marker = CATALOG_BY_SOURCE[source]
    if marker.expected_event != CANONICAL_EVENT:
        return (
            STAGE_YELLOW,
            source,
            [
                f"source-event-mismatch: {source!r} expects "
                f"{marker.expected_event!r}, envelope is {CANONICAL_EVENT!r}"
            ],
        )
    return STAGE_GREEN, source, []


def stage_marker_tag_catalog_conformance(
    stage1_details: dict[str, Any],
) -> StageResult:
    """For every envelope from stage 1, classify the audit_marker_tag
    against the canonical AUDIT_MARKER_CATALOG.
    """
    notes: list[str] = []
    envelopes = stage1_details.get("envelopes", [])
    if not isinstance(envelopes, list) or not envelopes:
        return StageResult(
            status=STAGE_RED,
            notes=["stage1-details-missing-or-empty"],
            details={},
        )

    statuses: list[str] = []
    per_results: list[dict[str, Any]] = []
    for entry in envelopes:
        if not isinstance(entry, dict):
            continue
        tag = entry.get("audit_marker_tag")
        if not isinstance(tag, str):
            statuses.append(STAGE_RED)
            per_results.append(
                {
                    "index": entry.get("index"),
                    "status": STAGE_RED,
                    "notes": ["audit-marker-tag-not-string-or-missing"],
                }
            )
            continue
        st, source, per_notes = _classify_marker_tag(tag)
        statuses.append(st)
        per_results.append(
            {
                "index": entry.get("index"),
                "status": st,
                "audit_marker_tag": tag,
                "matched_source": source,
                "notes": per_notes,
            }
        )

    if STAGE_RED in statuses:
        agg = STAGE_RED
    elif STAGE_YELLOW in statuses:
        agg = STAGE_YELLOW
    else:
        agg = STAGE_GREEN

    notes.append(f"tags-classified: {len(statuses)}")
    notes.append(
        f"counts: green={statuses.count(STAGE_GREEN)} "
        f"yellow={statuses.count(STAGE_YELLOW)} red={statuses.count(STAGE_RED)}"
    )

    return StageResult(
        status=agg,
        notes=notes,
        details={"tags": per_results},
    )


# ---------------------------------------------------------------------------
# Stage 3: Cross-Substrate-Marker-Reference-Check
# ---------------------------------------------------------------------------


def _substrate_references_marker(text: str, marker: MarkerClass) -> bool:
    """Does the substrate text reference this marker class?

    Match heuristics (any-of is sufficient):
        - marker.name substring (e.g. "operator-hand-dispatch")
        - "watch-day-<source>-" prefix (the canonical audit_marker_tag stem)
        - marker.source token bracketed by word-boundaries (cautious;
          guard against false positives by requiring a watch-day or
          audit-trail context word on the same line).
    """
    if marker.name in text:
        return True
    stem = f"watch-day-{marker.source}-"
    if stem in text:
        return True
    # Word-boundary source-token, gated by an audit/watch context word
    # on the same line.
    pattern = re.compile(
        rf"(?m)^.*\b{re.escape(marker.source)}\b.*\b(audit|watch[-_ ]?day|marker|trigger)\b.*$",
        re.IGNORECASE,
    )
    return bool(pattern.search(text))


def stage_cross_substrate_marker_reference(
    repo_root: Path,
) -> StageResult:
    """For each AUDIT_MARKER_CATALOG entry, verify at least one of the
    DOWNSTREAM_SUBSTRATES references it.

    Status:
        green: every marker referenced by >=1 substrate.
        yellow: 1 marker has zero substrate references.
        red: 2+ markers have zero references, or any substrate is
             missing on disk.
    """
    notes: list[str] = []

    substrate_texts: dict[str, str] = {}
    missing: list[str] = []
    for rel in DOWNSTREAM_SUBSTRATES:
        path = repo_root / rel
        if not path.is_file():
            missing.append(rel)
            continue
        try:
            substrate_texts[rel] = path.read_text(encoding="utf-8")
        except OSError as exc:
            return StageResult(
                status=STAGE_RED,
                notes=[f"substrate-read-failed: {rel}: {exc!r}"],
                details={},
            )

    if missing:
        return StageResult(
            status=STAGE_RED,
            notes=[f"substrates-missing: {missing}"],
            details={"missing": missing},
        )

    per_marker: list[dict[str, Any]] = []
    orphans: list[str] = []
    for marker in AUDIT_MARKER_CATALOG:
        refs: list[str] = []
        for rel, text in substrate_texts.items():
            if _substrate_references_marker(text, marker):
                refs.append(rel)
        per_marker.append(
            {
                "name": marker.name,
                "source": marker.source,
                "references": refs,
            }
        )
        if not refs:
            orphans.append(marker.name)

    if len(orphans) == 0:
        agg = STAGE_GREEN
    elif len(orphans) == 1:
        agg = STAGE_YELLOW
        notes.append(f"orphan-marker: {orphans[0]}")
    else:
        agg = STAGE_RED
        notes.append(f"orphan-markers: {orphans}")

    notes.append(
        f"markers-checked: {len(AUDIT_MARKER_CATALOG)} "
        f"substrates: {len(DOWNSTREAM_SUBSTRATES)} orphans: {len(orphans)}"
    )

    return StageResult(
        status=agg,
        notes=notes,
        details={"per_marker": per_marker, "orphans": orphans},
    )


# ---------------------------------------------------------------------------
# Stage 4: Aggregate Verdict
# ---------------------------------------------------------------------------


def aggregate_verdict(s1: str, s2: str, s3: str) -> str:
    """INTACT if all green; DRIFT if exactly one yellow and rest green;
    DEFECT otherwise (any red, or 2+ yellow).
    """
    for s in (s1, s2, s3):
        if s not in VALID_STAGE_STATUSES:
            return VERDICT_DEFECT
    statuses = (s1, s2, s3)
    if all(s == STAGE_GREEN for s in statuses):
        return VERDICT_INTACT
    if STAGE_RED in statuses:
        return VERDICT_DEFECT
    yellow_count = sum(1 for s in statuses if s == STAGE_YELLOW)
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
        "tag": 66,
        "tool": "verify-watch-day-operator-trigger-audit-trail",
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
        "tag": 66,
        "tool": "verify-watch-day-operator-trigger-audit-trail",
        "verdict": verdict,
        "stages": {
            "stage_1_trigger_event_schema_audit": s1,
            "stage_2_marker_tag_catalog_conformance": s2,
            "stage_3_cross_substrate_marker_reference": s3,
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
    out_dir = (
        Path(args.scratch_dir)
        if args.scratch_dir
        else (repo_root / "out" / "tag66")
    )
    fixture = Path(args.fixture) if args.fixture else None
    result = stage_trigger_event_schema_audit(repo_root, out_dir, fixture=fixture)
    if args.output:
        emit_stage_envelope(
            "stage_1_trigger_event_schema_audit", result, Path(args.output)
        )
    print(f"stage_1_trigger_event_schema_audit: {result.status}")
    for note in result.notes:
        print(f"  note: {note}")
    return _stage_exit_code(result.status)


def cmd_stage2(args: argparse.Namespace) -> int:
    # Stage 2 consumes stage 1 details from --stage-1-envelope.
    if not args.stage_1_envelope:
        print(
            "::error::stage-2 requires --stage-1-envelope to read stage-1 details",
            file=sys.stderr,
        )
        return EXIT_ERROR
    path = Path(args.stage_1_envelope)
    if not path.is_file():
        print(f"::error::stage-1-envelope missing: {path}", file=sys.stderr)
        return EXIT_ERROR
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"::error::stage-1-envelope malformed: {exc!r}", file=sys.stderr)
        return EXIT_ERROR
    stage1_details = payload.get("details", {})
    result = stage_marker_tag_catalog_conformance(stage1_details)
    if args.output:
        emit_stage_envelope(
            "stage_2_marker_tag_catalog_conformance", result, Path(args.output)
        )
    print(f"stage_2_marker_tag_catalog_conformance: {result.status}")
    for note in result.notes:
        print(f"  note: {note}")
    return _stage_exit_code(result.status)


def cmd_stage3(args: argparse.Namespace) -> int:
    repo_root = _repo_root(Path(args.repo_root) if args.repo_root else None)
    result = stage_cross_substrate_marker_reference(repo_root)
    if args.output:
        emit_stage_envelope(
            "stage_3_cross_substrate_marker_reference", result, Path(args.output)
        )
    print(f"stage_3_cross_substrate_marker_reference: {result.status}")
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
    """End-to-end: stages 1..3 + aggregate, all artifacts to scratch-dir."""
    repo_root = _repo_root(Path(args.repo_root) if args.repo_root else None)
    out_dir = (
        Path(args.scratch_dir)
        if args.scratch_dir
        else (repo_root / "out" / "tag66")
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    fixture = Path(args.fixture) if args.fixture else None

    r1 = stage_trigger_event_schema_audit(repo_root, out_dir, fixture=fixture)
    emit_stage_envelope(
        "stage_1_trigger_event_schema_audit", r1, out_dir / "stage-1.json"
    )
    r2 = stage_marker_tag_catalog_conformance(r1.details)
    emit_stage_envelope(
        "stage_2_marker_tag_catalog_conformance", r2, out_dir / "stage-2.json"
    )
    r3 = stage_cross_substrate_marker_reference(repo_root)
    emit_stage_envelope(
        "stage_3_cross_substrate_marker_reference", r3, out_dir / "stage-3.json"
    )
    verdict = aggregate_verdict(r1.status, r2.status, r3.status)
    emit_verdict_envelope(
        verdict,
        r1.status,
        r2.status,
        r3.status,
        out_dir / "watch-day-operator-trigger-audit-trail-verdict.json",
    )

    print(f"verdict: {verdict}")
    print(f"  stage_1: {r1.status}")
    print(f"  stage_2: {r2.status}")
    print(f"  stage_3: {r3.status}")
    return _verdict_exit_code(verdict)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verify_watch_day_operator_trigger_audit_trail",
        description=(
            "Tag-66 Watch-Day Operator-Trigger Audit-Trail verifier. "
            "Hermetic, stdlib-only, no GitHub-API calls."
        ),
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    p1 = sub.add_parser(
        "stage-1",
        help="Stage 1: trigger-event-schema-audit (per-envelope shape check)",
    )
    p1.add_argument("--repo-root", default=None)
    p1.add_argument("--scratch-dir", default=None)
    p1.add_argument(
        "--fixture",
        default=None,
        help="Optional JSON fixture (object or array of objects).",
    )
    p1.add_argument("--output", default=None)
    p1.set_defaults(func=cmd_stage1)

    p2 = sub.add_parser(
        "stage-2",
        help="Stage 2: marker-tag-catalog-conformance (consumes stage-1 envelope)",
    )
    p2.add_argument(
        "--stage-1-envelope",
        default=None,
        dest="stage_1_envelope",
        help="Path to stage-1 envelope JSON (required).",
    )
    p2.add_argument("--output", default=None)
    p2.set_defaults(func=cmd_stage2)

    p3 = sub.add_parser(
        "stage-3",
        help="Stage 3: cross-substrate marker reference check",
    )
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
    pf.add_argument(
        "--fixture",
        default=None,
        help="Optional JSON fixture (object or array of objects).",
    )
    pf.set_defaults(func=cmd_full)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
