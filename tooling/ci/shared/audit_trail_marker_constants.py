#!/usr/bin/env python3
# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Shared audit-trail marker constants (Tag-67, Tomás).

Single-source-of-truth for the audit-trail marker primitives that
are referenced by **both** Tag-66 verifier helpers:

* ``tooling/ci/verify_ar_hand_override_audit_trail.py``
  (Tomás Tag-66, PR #420) -- pins the AR-Hand Override-Flag event
  audit-trail-schema.

* ``tooling/ci/verify_watch_day_operator_trigger_audit_trail.py``
  (Noa Tag-66, PR #423) -- pins the Watch-Day Operator-Trigger
  event audit-trail-schema.

Before Tag-67 each helper carried a private copy of:

* the canonical marker source classes (``operator`` / ``ar`` /
  ``cron`` / ``replay``),
* the audit_marker_tag regex (the
  ``watch-day-<source>-<YYYYMMDD>-<short-hash>`` shape),
* the common timestamp / slug / UUID regex primitives,
* the audit-trail schema field tuples.

Two copies drift. Tag-67 extracts these into this module so a
single canonical definition is consumed by both helpers (and any
future verifier in the audit-trail family).

Discipline
----------

* **Additive refactor.** Both helpers continue to re-export their
  pre-Tag-67 module-level names verbatim; the existing Tag-66
  test-suites for both helpers MUST stay green without edit.
* **stdlib only.** No third-party deps. python >= 3.11.
* **Read-only.** This module defines constants, dataclasses, and
  compiled regexes. No I/O, no subprocess, no side effects on
  import.
* **Frozen dataclasses + tuples + frozensets.** The constants are
  immutable; downstream callers MUST NOT mutate them.

Anchors
-------

* Tag-66 AR-Hand Override-Audit-Trail Verifier (PR #420, Tomás).
* Tag-66 Watch-Day Operator-Trigger Audit-Trail Verifier (PR #423,
  Noa).
* ADR-0070 Override-Flag pattern (audit-replay-SLA budget).
* Tag-65 AR-Hand Cutover-Day-Morgen Override-Flag Listener
  (``tooling/ci/ar_hand_cutover_override_listener.py``).
* Tag-62 Watch-Day Operator-Trigger Pipeline simulator
  (``tooling/ci/simulate_watch_day_operator_trigger.py``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final


# ---------------------------------------------------------------------------
# Canonical audit-trail event constants (GitHub workflow_dispatch shape).
# ---------------------------------------------------------------------------

#: The GitHub workflow event type that every audit-trail-marker
#: envelope is built around for the Cutover-Day pipeline. Scheduled
#: cron triggers emit ``"schedule"`` (see CATALOG_BY_SOURCE), but
#: the canonical event the Watch-Day verifier checks against is
#: ``workflow_dispatch``.
CANONICAL_EVENT: Final[str] = "workflow_dispatch"

#: The Tag-56 phase-3c watch-day workflow filename. Pinned by both
#: helpers + the workflow YAML itself.
CANONICAL_WORKFLOW: Final[str] = "phase-3c-watch-day-practice-run.yml"

#: Canonical Git ref the operator dispatches against on Cutover-Day.
CANONICAL_REF: Final[str] = "refs/heads/main"


# ---------------------------------------------------------------------------
# Marker source classes -- the four legitimate trigger origins that
# produce an audit-trail event in Phase-3 Marathon Cutover-Day.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MarkerSourceClass:
    """One legitimate audit-trail-marker source class.

    A marker source class identifies *who/what* dispatched the
    workflow that produced the audit-trail event. The four classes
    enumerated below cover every legitimate trigger origin for the
    Cutover-Day pipeline; an envelope whose audit_marker_tag does
    not parse into one of these sources is a Tag-66 schema
    violation.

    Attributes
    ----------
    name
        Short label, single token, lower-kebab. Stable identifier
        used by downstream substrates (docs, dashboards, bridges).
    source
        Tag-fragment used in the audit_marker_tag string
        (``watch-day-<source>-<date>-<hash>``).
    description
        One-line operator-facing description.
    expected_event
        Which GitHub event-type this class normally emits. For
        operator-hand / ar-hand / replay-driver this is
        ``workflow_dispatch``; for scheduled-cron it is
        ``schedule``.
    """

    name: str
    source: str
    description: str
    expected_event: str


#: Canonical marker source classes. Ordering is stable; consumers
#: may iterate by index for deterministic output. Do not reorder.
MARKER_SOURCE_CLASSES: Final[tuple[MarkerSourceClass, ...]] = (
    MarkerSourceClass(
        name="operator-hand-dispatch",
        source="operator",
        description=(
            "Mira-Hand operator clicks Run workflow on Cutover-Day T0."
        ),
        expected_event="workflow_dispatch",
    ),
    MarkerSourceClass(
        name="ar-hand-override",
        source="ar",
        description=(
            "Aufsichtsrat override-flag dispatch (rare; Tag-65 AR "
            "listener)."
        ),
        expected_event="workflow_dispatch",
    ),
    MarkerSourceClass(
        name="scheduled-cron",
        source="cron",
        description=(
            "Calendar-pinned cron trigger (Tag-56 watch-day, Tue "
            "05:00 UTC)."
        ),
        expected_event="schedule",
    ),
    MarkerSourceClass(
        name="replay-driver",
        source="replay",
        description=(
            "Tag-59 replay-driver re-dispatch for post-incident "
            "reconstruction."
        ),
        expected_event="workflow_dispatch",
    ),
)

#: Lookup table by source-token (``operator`` / ``ar`` / ``cron`` /
#: ``replay``). Built once at import time; do not mutate.
MARKER_SOURCE_CLASSES_BY_SOURCE: Final[dict[str, MarkerSourceClass]] = {
    m.source: m for m in MARKER_SOURCE_CLASSES
}

#: Same lookup but keyed by ``name``. Useful when consumers carry the
#: friendly label instead of the tag-fragment.
MARKER_SOURCE_CLASSES_BY_NAME: Final[dict[str, MarkerSourceClass]] = {
    m.name: m for m in MARKER_SOURCE_CLASSES
}

#: Frozenset of all valid source-tokens. Used for fast membership
#: checks in verifier hot-loops.
MARKER_SOURCE_TOKENS: Final[frozenset[str]] = frozenset(
    m.source for m in MARKER_SOURCE_CLASSES
)


# ---------------------------------------------------------------------------
# Regex primitives -- shared by both verifiers.
# ---------------------------------------------------------------------------

#: Slug pattern: lower-case ASCII letter or digit start, then up to
#: 63 more letters/digits/hyphens. Used for operator slugs,
#: accepted-risk-id slugs, and marker-source tokens.
SLUG_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[a-z0-9][a-z0-9-]{1,63}$"
)

#: RFC3339-ish timestamp pattern. Accepts ``YYYY-MM-DDThh:mm:ss``
#: with optional fractional seconds and a Z or +/-HH:MM offset.
#: Slightly stricter than ``datetime.fromisoformat`` (we want the
#: trailing offset to be explicit so audit-replay never has to
#: guess the timezone).
RFC3339_TIMESTAMP_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?"
    r"(Z|[+-]\d{2}:\d{2})$"
)

#: Tolerant ISO-8601-ish dispatched_at pattern (Tag-66 Noa-side).
#: Same as ``RFC3339_TIMESTAMP_PATTERN`` but the trailing offset is
#: optional (legacy Tag-62 envelopes may omit it). Audit-replay
#: tolerates absence; new envelopes should always carry the offset.
DISPATCHED_AT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?$"
)

#: UUIDv4 pattern (case-insensitive). Used for trigger_sequence_id.
UUID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

#: Watch-Day audit-marker-tag pattern:
#: ``watch-day-<source>-<YYYYMMDD>-<short-hash>``.
#: Example: ``watch-day-operator-20260609-3bc7794``.
AUDIT_MARKER_TAG_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^watch-day-(operator|ar|cron|replay)-(\d{8})-([0-9a-f]{7,12})$"
)


# ---------------------------------------------------------------------------
# Audit-trail schema field tuples.
# ---------------------------------------------------------------------------

#: Required top-level keys for the Tag-65 AR-Hand Override-Flag
#: Listener output envelope (Tomás Tag-66 verifier schema).
AR_OVERRIDE_ENVELOPE_REQUIRED_KEYS: Final[tuple[str, ...]] = (
    "schema_version",
    "workflow",
    "tag",
    "emitted_at_utc",
    "applied",
    "verdict",
    "input_verdict",
    "override_marker",
    "input_verdict_envelope",
    "audit_trail_note",
    "decision_rule",
)

#: Required fields for the AR-Hand override marker payload (sub-
#: schema inside ``override_marker``; Tomás Tag-66 schema).
AR_OVERRIDE_MARKER_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "schema_version",
    "kind",
    "operator",
    "ts",
    "reason",
    "accepted_risk_id",
    "override_target_verdict",
    "post_override_verdict",
)

#: Required keys for a Tag-66-fully-conformant Watch-Day Operator-
#: Trigger envelope (Noa Tag-66 schema).
WATCH_DAY_ENVELOPE_REQUIRED_KEYS: Final[tuple[str, ...]] = (
    "event",
    "workflow",
    "ref",
    "inputs",
    "actor",
    "dispatched_at",
    "audit_marker_tag",
    "trigger_sequence_id",
)

#: Subset of WATCH_DAY_ENVELOPE_REQUIRED_KEYS that matches the legacy
#: Tag-62 pre-audit-trail shape. Missing audit-only keys downgrades
#: the envelope verdict to yellow rather than red.
WATCH_DAY_BASE_KEYS_TAG62: Final[tuple[str, ...]] = (
    "event",
    "workflow",
    "ref",
    "inputs",
)

#: The audit-only delta -- keys that Tag-66 adds on top of
#: ``WATCH_DAY_BASE_KEYS_TAG62``. Missing any of these moves the
#: envelope from green to yellow (audit-keys-missing).
WATCH_DAY_AUDIT_ONLY_KEYS: Final[tuple[str, ...]] = (
    "actor",
    "dispatched_at",
    "audit_marker_tag",
    "trigger_sequence_id",
)


# ---------------------------------------------------------------------------
# AR-Hand Override-Flag marker schema constants (Tag-65 listener).
# ---------------------------------------------------------------------------

#: The ``kind`` value that an AR-Hand override marker MUST carry.
AR_OVERRIDE_MARKER_KIND: Final[str] = "ar-hand-cutover-override-flag"

#: Schema version for the AR-Hand override marker payload.
AR_OVERRIDE_MARKER_SCHEMA_VERSION: Final[int] = 1

#: Minimum / maximum reason length (after strip) for the AR-Hand
#: override marker.
AR_OVERRIDE_REASON_MIN_LEN: Final[int] = 16
AR_OVERRIDE_REASON_MAX_LEN: Final[int] = 1024


# ---------------------------------------------------------------------------
# Cutover-Day verdict tokens (Tomás Tag-66 schema).
# ---------------------------------------------------------------------------

VERDICT_CUTOVER_DAY_READY: Final[str] = "CUTOVER-DAY-MORGEN-READY"
VERDICT_CUTOVER_DAY_CAUTION: Final[str] = "CUTOVER-DAY-MORGEN-CAUTION"
VERDICT_CUTOVER_DAY_BLOCK: Final[str] = "CUTOVER-DAY-MORGEN-BLOCK"

#: All legitimate Cutover-Day verdict tokens for input/output checks.
CUTOVER_DAY_VERDICTS: Final[frozenset[str]] = frozenset(
    {
        VERDICT_CUTOVER_DAY_READY,
        VERDICT_CUTOVER_DAY_CAUTION,
        VERDICT_CUTOVER_DAY_BLOCK,
    }
)

#: Override transition pinned by ADR-0070: BLOCK -> CAUTION, never
#: BLOCK -> READY.
AR_OVERRIDE_TARGET_VERDICT: Final[str] = VERDICT_CUTOVER_DAY_BLOCK
AR_OVERRIDE_POST_VERDICT: Final[str] = VERDICT_CUTOVER_DAY_CAUTION


# ---------------------------------------------------------------------------
# Watch-Day audit-trail four-stage verdict tokens (Noa Tag-66 schema).
# ---------------------------------------------------------------------------

WATCH_DAY_VERDICT_INTACT: Final[str] = "AUDIT-TRAIL-INTACT"
WATCH_DAY_VERDICT_DRIFT: Final[str] = "AUDIT-TRAIL-DRIFT"
WATCH_DAY_VERDICT_DEFECT: Final[str] = "AUDIT-TRAIL-DEFECT"

WATCH_DAY_AUDIT_TRAIL_VERDICTS: Final[frozenset[str]] = frozenset(
    {
        WATCH_DAY_VERDICT_INTACT,
        WATCH_DAY_VERDICT_DRIFT,
        WATCH_DAY_VERDICT_DEFECT,
    }
)

#: Stage status tokens for the four-stage hermetic verdict.
STAGE_STATUS_GREEN: Final[str] = "green"
STAGE_STATUS_YELLOW: Final[str] = "yellow"
STAGE_STATUS_RED: Final[str] = "red"

VALID_STAGE_STATUSES: Final[frozenset[str]] = frozenset(
    {STAGE_STATUS_GREEN, STAGE_STATUS_YELLOW, STAGE_STATUS_RED}
)


# ---------------------------------------------------------------------------
# Audit-trail-note canonical substrings (Tomás Tag-66 verifier).
# ---------------------------------------------------------------------------

#: Substring that an applied-override audit_trail_note MUST contain.
NOTE_OVERRIDE_APPLIED_PREFIX: Final[str] = "AR-Hand override applied"

#: Tokens (any-of) that a stale-marker-guard audit_trail_note MUST
#: reference when ``applied == false`` AND a marker is present.
NOTE_STALE_MARKER_GUARD_TOKENS: Final[tuple[str, ...]] = (
    "marker recorded",
    "verdict unchanged",
)

#: Substring that the no-marker pass-through audit_trail_note MUST
#: contain when ``applied == false`` AND no marker is present.
NOTE_NO_MARKER_TOKEN: Final[str] = "no override marker"


# ---------------------------------------------------------------------------
# Helpers (pure functions; no I/O).
# ---------------------------------------------------------------------------


def parse_audit_marker_tag_source(tag: str) -> str | None:
    """Return the source-token of a well-formed audit_marker_tag.

    Returns the source fragment (``operator`` / ``ar`` / ``cron`` /
    ``replay``) if ``tag`` matches ``AUDIT_MARKER_TAG_PATTERN``, else
    ``None``. Read-only convenience used by both verifiers.
    """
    if not isinstance(tag, str):
        return None
    m = AUDIT_MARKER_TAG_PATTERN.match(tag)
    if m is None:
        return None
    return m.group(1)


def build_audit_marker_tag(
    source: str, date_yyyymmdd: str, short_hash: str
) -> str:
    """Compose a canonical audit_marker_tag string.

    Inputs are validated against the canonical patterns; raises
    ``ValueError`` on any violation. The intent is to make the
    composition lossless and to keep tag-mints synchronised across
    helpers (and tests).

    Parameters
    ----------
    source
        One of the recognised source tokens (see
        ``MARKER_SOURCE_TOKENS``).
    date_yyyymmdd
        Eight-digit date string, e.g. ``"20260609"``.
    short_hash
        7-12 hex chars, lowercase.
    """
    if source not in MARKER_SOURCE_TOKENS:
        raise ValueError(
            f"unknown marker source token: {source!r} "
            f"(expected one of {sorted(MARKER_SOURCE_TOKENS)})"
        )
    if not re.fullmatch(r"\d{8}", date_yyyymmdd):
        raise ValueError(
            f"date_yyyymmdd must be 8 digits, got {date_yyyymmdd!r}"
        )
    if not re.fullmatch(r"[0-9a-f]{7,12}", short_hash):
        raise ValueError(
            f"short_hash must be 7-12 lowercase hex chars, "
            f"got {short_hash!r}"
        )
    tag = f"watch-day-{source}-{date_yyyymmdd}-{short_hash}"
    # Belt-and-braces: composed value must satisfy the pattern.
    assert AUDIT_MARKER_TAG_PATTERN.match(tag), (
        f"built tag does not match canonical pattern: {tag!r}"
    )
    return tag


# ---------------------------------------------------------------------------
# Module-level metadata (introspection helpers).
# ---------------------------------------------------------------------------

#: Schema version of this shared-constants module. Bump when a
#: breaking change is made to any frozen tuple / dataclass shape.
SHARED_CONSTANTS_SCHEMA_VERSION: Final[int] = 1


__all__ = (
    # Event constants
    "CANONICAL_EVENT",
    "CANONICAL_WORKFLOW",
    "CANONICAL_REF",
    # Marker source classes
    "MarkerSourceClass",
    "MARKER_SOURCE_CLASSES",
    "MARKER_SOURCE_CLASSES_BY_SOURCE",
    "MARKER_SOURCE_CLASSES_BY_NAME",
    "MARKER_SOURCE_TOKENS",
    # Regex primitives
    "SLUG_PATTERN",
    "RFC3339_TIMESTAMP_PATTERN",
    "DISPATCHED_AT_PATTERN",
    "UUID_PATTERN",
    "AUDIT_MARKER_TAG_PATTERN",
    # Schema field tuples
    "AR_OVERRIDE_ENVELOPE_REQUIRED_KEYS",
    "AR_OVERRIDE_MARKER_REQUIRED_FIELDS",
    "WATCH_DAY_ENVELOPE_REQUIRED_KEYS",
    "WATCH_DAY_BASE_KEYS_TAG62",
    "WATCH_DAY_AUDIT_ONLY_KEYS",
    # AR-Hand marker constants
    "AR_OVERRIDE_MARKER_KIND",
    "AR_OVERRIDE_MARKER_SCHEMA_VERSION",
    "AR_OVERRIDE_REASON_MIN_LEN",
    "AR_OVERRIDE_REASON_MAX_LEN",
    # Cutover-Day verdict tokens
    "VERDICT_CUTOVER_DAY_READY",
    "VERDICT_CUTOVER_DAY_CAUTION",
    "VERDICT_CUTOVER_DAY_BLOCK",
    "CUTOVER_DAY_VERDICTS",
    "AR_OVERRIDE_TARGET_VERDICT",
    "AR_OVERRIDE_POST_VERDICT",
    # Watch-Day verdict tokens
    "WATCH_DAY_VERDICT_INTACT",
    "WATCH_DAY_VERDICT_DRIFT",
    "WATCH_DAY_VERDICT_DEFECT",
    "WATCH_DAY_AUDIT_TRAIL_VERDICTS",
    "STAGE_STATUS_GREEN",
    "STAGE_STATUS_YELLOW",
    "STAGE_STATUS_RED",
    "VALID_STAGE_STATUSES",
    # Audit-trail-note tokens
    "NOTE_OVERRIDE_APPLIED_PREFIX",
    "NOTE_STALE_MARKER_GUARD_TOKENS",
    "NOTE_NO_MARKER_TOKEN",
    # Helpers
    "parse_audit_marker_tag_source",
    "build_audit_marker_tag",
    # Module metadata
    "SHARED_CONSTANTS_SCHEMA_VERSION",
)
