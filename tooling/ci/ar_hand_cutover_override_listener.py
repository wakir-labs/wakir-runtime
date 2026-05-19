#!/usr/bin/env python3
# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""AR-Hand Cutover-Day-Morgen Override-Flag Listener (Tag-65 Tomás).

The Tag-64 ``aggregate_cutover_day_morgen_verdict.py`` aggregator
(Selin) emits one of three verdicts on every cutover-week morning:

  * ``CUTOVER-DAY-MORGEN-READY``   -- all three top-level verdicts green.
  * ``CUTOVER-DAY-MORGEN-CAUTION`` -- at least one yellow, zero red.
  * ``CUTOVER-DAY-MORGEN-BLOCK``   -- at least one red, OR any envelope
    missing / unparseable.

Tag-65 closes the AR-Hand-Override gap that Selin's Tag-64 follow-up
item #3 surfaced: AR-Hand must be able to **override** a BLOCK verdict
on a documented accepted-risk basis (e.g. a known-yellow substrate
that AR-Hand has already triaged out-of-band). The pattern mirrors
Tag-44 Stop-Marker semantics exactly, but inverted: instead of
**halting** a proceed, it **resumes** a halt.

Design boundaries
-----------------

* **Read-only.** The listener never mutates verdict envelopes;
  it produces a *new* envelope-shaped object with the override
  applied. The Tag-64 aggregator envelope is preserved verbatim
  under ``input_verdict_envelope`` for full audit-trail.

* **BLOCK-only.** The override flag is **only** honoured against
  a ``CUTOVER-DAY-MORGEN-BLOCK`` input verdict. Applying an
  override to READY or CAUTION is a no-op (the override marker is
  recorded on the envelope but the verdict is unchanged) -- this
  avoids the failure mode where AR-Hand accidentally downgrades a
  READY to CAUTION through a stale marker file.

* **Audit-trail mandatory.** Every override marker MUST carry
  ``operator``, ``ts`` (RFC3339), ``reason`` (free-text, min 16
  chars), and ``accepted_risk_id`` (slug, e.g. ``ar-risk-tag-65-01``).
  The listener refuses markers that violate the schema.

* **Hermetic.** Stdlib only. No network, no NATS, no gh CLI. The
  marker file is read from a path supplied by the caller; the
  caller (workflow) is responsible for sourcing it from the repo
  checkout state directory.

Marker file schema (JSON)
-------------------------

::

  {
    "schema_version": 1,
    "kind": "ar-hand-cutover-override-flag",
    "operator": "<slug>",
    "ts": "<RFC3339 UTC>",
    "iso_week": <int, optional, 24..27 for cutover marathon>,
    "reason": "<free-text, min 16 chars>",
    "accepted_risk_id": "<slug>",
    "override_target_verdict": "CUTOVER-DAY-MORGEN-BLOCK",
    "post_override_verdict":   "CUTOVER-DAY-MORGEN-CAUTION"
  }

The ``post_override_verdict`` MUST be ``CUTOVER-DAY-MORGEN-CAUTION``
(never READY -- an overridden BLOCK never becomes clean-green).

Output envelope
---------------

The listener emits a new JSON envelope:

::

  {
    "schema_version": 1,
    "workflow": "ar-hand-cutover-override-listener",
    "tag": "tag-65",
    "emitted_at_utc": "<RFC3339>",
    "applied": <bool>,
    "verdict": "<post-override verdict OR input verdict if not applied>",
    "input_verdict": "<input envelope verdict>",
    "override_marker": <marker JSON OR null>,
    "input_verdict_envelope": <full Tag-64 envelope verbatim>,
    "audit_trail_note": "<short summary line>"
  }

Anchors
-------

* Tag-44 Stop-Marker pattern (Tomás).
* Tag-64 Cutover-Day-Morgen Auto-Scheduler (Selin).
* ADR-0070 ``ar-hand-cutover-override-flag`` (Mira-Hand
  pre-approval-sichten).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Schema constants.
# ---------------------------------------------------------------------------

MARKER_KIND: str = "ar-hand-cutover-override-flag"
MARKER_SCHEMA_VERSION: int = 1
OUTPUT_SCHEMA_VERSION: int = 1

# Mirror Tag-64 aggregator constants. Re-declared locally so this
# listener stays hermetic against the aggregator module.
VERDICT_READY: str = "CUTOVER-DAY-MORGEN-READY"
VERDICT_CAUTION: str = "CUTOVER-DAY-MORGEN-CAUTION"
VERDICT_BLOCK: str = "CUTOVER-DAY-MORGEN-BLOCK"

ALLOWED_VERDICTS: frozenset[str] = frozenset(
    {VERDICT_READY, VERDICT_CAUTION, VERDICT_BLOCK}
)

# Only BLOCK is a valid override target. The override never
# touches READY or CAUTION envelopes.
OVERRIDE_TARGET_VERDICT: str = VERDICT_BLOCK

# The post-override verdict is CAUTION, never READY. An AR-Hand
# override of a BLOCK leaves an "accepted yellow" residue on the
# marathon dashboard; it never claims green.
POST_OVERRIDE_VERDICT: str = VERDICT_CAUTION

# Required marker fields.
MARKER_REQUIRED_FIELDS: tuple[str, ...] = (
    "schema_version",
    "kind",
    "operator",
    "ts",
    "reason",
    "accepted_risk_id",
    "override_target_verdict",
    "post_override_verdict",
)

# Operator + risk-id slug pattern: lowercase letters, digits, hyphen.
_SLUG_RE: re.Pattern[str] = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")

# RFC3339 / ISO-8601 timestamp pattern (with timezone, second
# precision or finer).
_TS_RE: re.Pattern[str] = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?"
    r"(Z|[+-]\d{2}:\d{2})$"
)

REASON_MIN_LEN: int = 16
REASON_MAX_LEN: int = 1024

# Cutover marathon ISO-week window (mirrors Tag-64 aggregator).
CUTOVER_WINDOW_ISO_WEEKS: tuple[int, ...] = (24, 25, 26, 27)


# ---------------------------------------------------------------------------
# Exceptions.
# ---------------------------------------------------------------------------


class OverrideMarkerError(ValueError):
    """Raised when an override marker fails schema validation."""


class InputVerdictError(ValueError):
    """Raised when the Tag-64 input verdict envelope is malformed."""


# ---------------------------------------------------------------------------
# Marker validation.
# ---------------------------------------------------------------------------


def validate_marker(marker: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an override-marker payload and return a normalised copy.

    The normalised copy contains every required field, with types
    coerced to their canonical form. Optional fields (``iso_week``)
    are surfaced verbatim if present.

    Raises ``OverrideMarkerError`` on any schema violation.
    """
    if not isinstance(marker, Mapping):
        raise OverrideMarkerError(
            f"marker must be a JSON object, got {type(marker).__name__}"
        )

    missing = [f for f in MARKER_REQUIRED_FIELDS if f not in marker]
    if missing:
        raise OverrideMarkerError(
            f"marker missing required fields: {missing}"
        )

    schema_version = marker["schema_version"]
    if schema_version != MARKER_SCHEMA_VERSION:
        raise OverrideMarkerError(
            f"marker schema_version mismatch: got {schema_version!r}, "
            f"expected {MARKER_SCHEMA_VERSION}"
        )

    kind = marker["kind"]
    if kind != MARKER_KIND:
        raise OverrideMarkerError(
            f"marker kind mismatch: got {kind!r}, expected {MARKER_KIND!r}"
        )

    operator = marker["operator"]
    if not isinstance(operator, str) or not _SLUG_RE.match(operator):
        raise OverrideMarkerError(
            f"marker operator must be a slug (a-z0-9-, 2..64 chars): "
            f"{operator!r}"
        )

    ts = marker["ts"]
    if not isinstance(ts, str) or not _TS_RE.match(ts):
        raise OverrideMarkerError(
            f"marker ts must be RFC3339 UTC-or-offset: {ts!r}"
        )

    reason = marker["reason"]
    if not isinstance(reason, str):
        raise OverrideMarkerError(
            f"marker reason must be a string, got {type(reason).__name__}"
        )
    reason_stripped = reason.strip()
    if len(reason_stripped) < REASON_MIN_LEN:
        raise OverrideMarkerError(
            f"marker reason must be at least {REASON_MIN_LEN} chars "
            f"after strip(); got {len(reason_stripped)}"
        )
    if len(reason_stripped) > REASON_MAX_LEN:
        raise OverrideMarkerError(
            f"marker reason must be at most {REASON_MAX_LEN} chars "
            f"after strip(); got {len(reason_stripped)}"
        )

    accepted_risk_id = marker["accepted_risk_id"]
    if not isinstance(accepted_risk_id, str) or not _SLUG_RE.match(
        accepted_risk_id
    ):
        raise OverrideMarkerError(
            f"marker accepted_risk_id must be a slug: {accepted_risk_id!r}"
        )

    override_target = marker["override_target_verdict"]
    if override_target != OVERRIDE_TARGET_VERDICT:
        raise OverrideMarkerError(
            f"marker override_target_verdict must be "
            f"{OVERRIDE_TARGET_VERDICT!r}, got {override_target!r}"
        )

    post_override = marker["post_override_verdict"]
    if post_override != POST_OVERRIDE_VERDICT:
        raise OverrideMarkerError(
            f"marker post_override_verdict must be "
            f"{POST_OVERRIDE_VERDICT!r}, got {post_override!r}"
        )

    normalised: dict[str, Any] = {
        "schema_version": MARKER_SCHEMA_VERSION,
        "kind": MARKER_KIND,
        "operator": operator,
        "ts": ts,
        "reason": reason_stripped,
        "accepted_risk_id": accepted_risk_id,
        "override_target_verdict": OVERRIDE_TARGET_VERDICT,
        "post_override_verdict": POST_OVERRIDE_VERDICT,
    }

    iso_week = marker.get("iso_week")
    if iso_week is not None:
        if not isinstance(iso_week, int) or isinstance(iso_week, bool):
            raise OverrideMarkerError(
                f"marker iso_week must be int when present, got "
                f"{type(iso_week).__name__}"
            )
        if not (1 <= iso_week <= 53):
            raise OverrideMarkerError(
                f"marker iso_week out of range 1..53: {iso_week}"
            )
        normalised["iso_week"] = iso_week

    return normalised


def load_marker(path: Path | None) -> dict[str, Any] | None:
    """Read and validate an override-marker file.

    Returns ``None`` if ``path`` is ``None`` or the file does not
    exist. Raises ``OverrideMarkerError`` on any other failure
    (unreadable file, malformed JSON, schema violation).

    A missing marker is a *non-error* state: the absence of an
    override marker simply means no override is requested.
    """
    if path is None:
        return None
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OverrideMarkerError(
            f"cannot read override marker at {path}: {exc}"
        ) from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OverrideMarkerError(
            f"override marker is not valid JSON at {path}: {exc}"
        ) from exc
    return validate_marker(payload)


# ---------------------------------------------------------------------------
# Input verdict envelope loading.
# ---------------------------------------------------------------------------


def load_input_envelope(path: Path) -> dict[str, Any]:
    """Load the Tag-64 cutover-day-morgen verdict envelope.

    Raises ``InputVerdictError`` if the file is missing, malformed,
    or does not carry a recognised ``verdict`` field. The Tag-64
    aggregator always emits a verdict, so this is a contract
    violation if the envelope is unreadable.
    """
    if not path.exists():
        raise InputVerdictError(
            f"input verdict envelope not found: {path}"
        )
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InputVerdictError(
            f"cannot read input verdict envelope at {path}: {exc}"
        ) from exc
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InputVerdictError(
            f"input verdict envelope is not valid JSON at {path}: {exc}"
        ) from exc
    if not isinstance(envelope, dict):
        raise InputVerdictError(
            f"input verdict envelope must be a JSON object, "
            f"got {type(envelope).__name__}"
        )
    verdict = envelope.get("verdict")
    if not isinstance(verdict, str):
        raise InputVerdictError(
            f"input envelope missing string 'verdict' field: {path}"
        )
    if verdict not in ALLOWED_VERDICTS:
        raise InputVerdictError(
            f"input verdict {verdict!r} is not one of "
            f"{sorted(ALLOWED_VERDICTS)}"
        )
    return envelope


# ---------------------------------------------------------------------------
# Decision logic.
# ---------------------------------------------------------------------------


def decide_override(
    input_envelope: Mapping[str, Any],
    marker: Mapping[str, Any] | None,
) -> tuple[bool, str, str]:
    """Decide whether to apply an override.

    Returns ``(applied, verdict, audit_note)``.

    * ``applied`` -- ``True`` iff a valid marker is present AND the
      input verdict is BLOCK.
    * ``verdict`` -- the post-override verdict if applied,
      otherwise the input verdict verbatim.
    * ``audit_note`` -- one-line human-readable summary, always
      populated.
    """
    input_verdict = input_envelope["verdict"]

    if marker is None:
        return (
            False,
            input_verdict,
            f"no override marker; input verdict {input_verdict} unchanged",
        )

    if input_verdict != OVERRIDE_TARGET_VERDICT:
        # Marker present, but input is not BLOCK. Record the marker
        # but do not modify the verdict. This guards against the
        # stale-marker downgrade failure mode.
        return (
            False,
            input_verdict,
            (
                f"override marker present but input verdict is "
                f"{input_verdict} (not {OVERRIDE_TARGET_VERDICT}); "
                f"marker recorded, verdict unchanged"
            ),
        )

    return (
        True,
        POST_OVERRIDE_VERDICT,
        (
            f"AR-Hand override applied: BLOCK -> {POST_OVERRIDE_VERDICT} "
            f"(operator={marker['operator']}, "
            f"risk_id={marker['accepted_risk_id']})"
        ),
    )


def build_output_envelope(
    input_envelope: Mapping[str, Any],
    marker: Mapping[str, Any] | None,
    *,
    github_run_id: str | None = None,
    github_sha: str | None = None,
    github_ref: str | None = None,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Build the listener output envelope.

    The output envelope preserves the input envelope verbatim
    under ``input_verdict_envelope`` so downstream audit can
    replay the decision deterministically.
    """
    applied, verdict, audit_note = decide_override(input_envelope, marker)
    now = now_utc or datetime.now(timezone.utc)
    return {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "workflow": "ar-hand-cutover-override-listener",
        "tag": "tag-65",
        "emitted_at_utc": now.isoformat(timespec="seconds"),
        "github_run_id": github_run_id,
        "github_sha": github_sha,
        "github_ref": github_ref,
        "applied": applied,
        "verdict": verdict,
        "input_verdict": input_envelope["verdict"],
        "override_marker": dict(marker) if marker is not None else None,
        "input_verdict_envelope": dict(input_envelope),
        "audit_trail_note": audit_note,
        "decision_rule": {
            "applies_to_input": OVERRIDE_TARGET_VERDICT,
            "post_override_verdict": POST_OVERRIDE_VERDICT,
            "rationale": (
                "AR-Hand may override CUTOVER-DAY-MORGEN-BLOCK to "
                "CUTOVER-DAY-MORGEN-CAUTION on documented accepted-"
                "risk basis; READY/CAUTION inputs are never modified."
            ),
        },
    }


# ---------------------------------------------------------------------------
# CLI plumbing.
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ar_hand_cutover_override_listener",
        description=(
            "AR-Hand Cutover-Day-Morgen Override-Flag Listener. "
            "Reads a Tag-64 cutover-day-morgen verdict envelope and "
            "an optional AR-Hand override marker file; emits a new "
            "verdict envelope reflecting any applied override."
        ),
    )
    p.add_argument(
        "--input-verdict",
        type=Path,
        required=True,
        help="Path to the Tag-64 cutover-day-morgen verdict envelope JSON.",
    )
    p.add_argument(
        "--override-marker",
        type=Path,
        default=None,
        help=(
            "Optional path to an AR-Hand override marker file. "
            "If absent or missing on disk, no override is applied."
        ),
    )
    p.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the override-aware output envelope JSON.",
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
        "--strict-marker",
        action="store_true",
        help=(
            "If set, a present-but-invalid override marker causes "
            "the listener to exit non-zero. Default: invalid marker "
            "is logged to stderr and treated as 'no marker'."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    try:
        input_envelope = load_input_envelope(args.input_verdict)
    except InputVerdictError as exc:
        print(f"ERROR: input verdict load failed: {exc}", file=sys.stderr)
        return 2

    marker: dict[str, Any] | None = None
    try:
        marker = load_marker(args.override_marker)
    except OverrideMarkerError as exc:
        msg = f"override marker validation failed: {exc}"
        if args.strict_marker:
            print(f"ERROR: {msg}", file=sys.stderr)
            return 3
        print(f"WARN: {msg}; proceeding with no override", file=sys.stderr)
        marker = None

    envelope = build_output_envelope(
        input_envelope,
        marker,
        github_run_id=args.github_run_id,
        github_sha=args.github_sha,
        github_ref=args.github_ref,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(envelope, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(envelope["audit_trail_note"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
