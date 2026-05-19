#!/usr/bin/env python3
# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""AR-Hand Override Audit-Trail Verifier (Tag-66 Tomás).

Companion verifier for the Tag-65 AR-Hand Cutover-Day-Morgen
Override-Flag Listener (``tooling/ci/ar_hand_cutover_override_listener.py``).

The Tag-65 listener produces an output envelope that carries an
``audit_trail_note`` plus the full input verdict envelope verbatim
under ``input_verdict_envelope``. That payload IS the audit-marker
for AR-Hand override actions. Tag-66 closes the verification gap:
**every override output envelope produced for a real override action
MUST satisfy the Audit-Trail-Schema** below, so Henrik (Internal
Audit) can replay the AR-Hand override decisions deterministically
and count them against the ADR-0070 §Audit-SLA budget.

Scope
-----

The verifier scans one or more candidate envelope JSON files and
classifies each as one of:

* ``PASS``    -- envelope is schema-conformant *and* internally
  consistent (decision-rule matches verdict, marker matches input,
  audit_trail_note matches the (applied, verdicts, operator, risk-id)
  tuple, REUSE wrapper intact).
* ``ADVISORY`` -- envelope is schema-conformant but carries a soft
  warning (e.g. no override applied because input was already
  CAUTION/READY; this is the "stale marker downgrade guard" case
  and is *expected* behaviour, but flagged so audit can see it).
* ``FAIL``    -- envelope violates the schema or carries
  inconsistent fields. Henrik MUST review.

The verifier is **read-only**. It never mutates files, never writes
to network sources, never spawns subprocesses. Stdlib only.

Decision rules (mirror Tag-65 listener)
---------------------------------------

* If ``applied == true`` then:
    - ``input_verdict`` MUST be ``CUTOVER-DAY-MORGEN-BLOCK``.
    - ``verdict`` MUST be ``CUTOVER-DAY-MORGEN-CAUTION``.
    - ``override_marker`` MUST be a valid marker payload.
    - ``audit_trail_note`` MUST contain the substring
      ``"AR-Hand override applied"`` and reference the operator
      and the accepted-risk-id verbatim.
* If ``applied == false`` and a marker is present:
    - ``input_verdict`` MUST be in
      ``{CUTOVER-DAY-MORGEN-READY, CUTOVER-DAY-MORGEN-CAUTION}``.
    - ``verdict`` MUST equal ``input_verdict``.
    - ``audit_trail_note`` MUST mention "marker recorded" or
      "verdict unchanged" (the stale-marker downgrade guard
      message family).
* If ``applied == false`` and no marker is present:
    - ``verdict`` MUST equal ``input_verdict`` (no-op pass-through).
    - ``override_marker`` MUST be ``null``.

Schema (v1) -- required top-level keys
--------------------------------------

::

  schema_version, workflow, tag, emitted_at_utc, applied,
  verdict, input_verdict, override_marker,
  input_verdict_envelope, audit_trail_note, decision_rule

If ``override_marker`` is non-null, it MUST satisfy the Tag-65
marker schema (operator slug, RFC3339 ts, reason >= 16 chars,
accepted_risk_id slug, override_target_verdict ==
``CUTOVER-DAY-MORGEN-BLOCK``, post_override_verdict ==
``CUTOVER-DAY-MORGEN-CAUTION``).

Output
------

The verifier emits a single roll-up JSON to ``--output``::

  {
    "schema_version": 1,
    "tag": "tag-66",
    "tool": "verify_ar_hand_override_audit_trail",
    "scanned_at_utc": "<RFC3339>",
    "input_count": <int>,
    "pass_count": <int>,
    "advisory_count": <int>,
    "fail_count": <int>,
    "verdict": "PASS" | "ADVISORY" | "FAIL",
    "per_envelope": [
      {
        "path": "<str>",
        "verdict": "PASS" | "ADVISORY" | "FAIL",
        "applied": <bool|null>,
        "input_verdict": "<str|null>",
        "audit_trail_note": "<str|null>",
        "violations": ["<reason1>", ...],
        "advisories": ["<reason1>", ...]
      },
      ...
    ]
  }

Exit codes
----------

* ``0`` -- aggregate verdict is ``PASS`` or ``ADVISORY``.
* ``1`` -- aggregate verdict is ``FAIL`` (at least one envelope
  failed schema validation or invariants).
* ``2`` -- helper-internal usage error (no inputs, unreadable
  directory, etc.).

This verifier is wired as an *audit-mode* workflow
(``.github/workflows/ar-hand-override-audit-trail-verify.yml``) so
it never gates merges -- it surfaces violations to Henrik via
Pull-Request comments and artifact upload, mirroring the Tag-44
audit-mode pattern. Required-status-check enforcement is operator-
hand (feedback_branch_protection_check_names.md).

Anchors
-------

* Tag-65 Override-Flag Listener
  (``tooling/ci/ar_hand_cutover_override_listener.py``).
* ADR-0070 Override-Flag pattern (vorlage in
  ``docs/decisions/`` -- migration to AI-Corp/decisions/ is
  Mira-Hand).
* Tag-44 Audit-Marker pattern
  (``tooling/ci/emit_marathon_rollback_audit_marker.py``).
* Henrik Internal-Audit replay-budget (ADR-0070 §Audit-SLA).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Tag-67 sys.path bootstrap: when this helper runs as
# ``python tooling/ci/verify_ar_hand_override_audit_trail.py`` (CLI
# invocation, used by the audit-mode workflow YAML), Python adds only
# the script directory to ``sys.path``. The shared-constants module
# lives at ``tooling/ci/shared/...`` and needs the *repo root* on
# the path for ``from tooling.ci.shared import ...`` to resolve.
# Add it idempotently before the import. Pytest test-collection
# already inserts the repo root via repo-root ``conftest.py``, so
# this is a no-op in that mode.
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Tag-67 single-source-of-truth for audit-trail constants. The local
# module-level names below are kept as aliases for the shared values
# so this helper's behaviour and Tag-66 test contract are unchanged
# (additive refactor).
from tooling.ci.shared import audit_trail_marker_constants as _shared  # noqa: E402


# ---------------------------------------------------------------------------
# Schema constants (mirror Tag-65 listener verbatim, sourced from
# tooling/ci/shared/audit_trail_marker_constants.py since Tag-67).
# ---------------------------------------------------------------------------

OUTPUT_SCHEMA_VERSION: int = 1
TAG66_TOOL_NAME: str = "verify_ar_hand_override_audit_trail"

# Verdict tokens.
VERDICT_READY: str = _shared.VERDICT_CUTOVER_DAY_READY
VERDICT_CAUTION: str = _shared.VERDICT_CUTOVER_DAY_CAUTION
VERDICT_BLOCK: str = _shared.VERDICT_CUTOVER_DAY_BLOCK
ALLOWED_VERDICTS: frozenset[str] = _shared.CUTOVER_DAY_VERDICTS

# Listener-output envelope required keys.
ENVELOPE_REQUIRED_KEYS: tuple[str, ...] = (
    _shared.AR_OVERRIDE_ENVELOPE_REQUIRED_KEYS
)

# Marker schema (must match Tag-65 listener exactly).
MARKER_KIND: str = _shared.AR_OVERRIDE_MARKER_KIND
MARKER_SCHEMA_VERSION: int = _shared.AR_OVERRIDE_MARKER_SCHEMA_VERSION
MARKER_REQUIRED_FIELDS: tuple[str, ...] = (
    _shared.AR_OVERRIDE_MARKER_REQUIRED_FIELDS
)
MARKER_OVERRIDE_TARGET: str = _shared.AR_OVERRIDE_TARGET_VERDICT
MARKER_POST_OVERRIDE: str = _shared.AR_OVERRIDE_POST_VERDICT

_SLUG_RE: re.Pattern[str] = _shared.SLUG_PATTERN
_TS_RE: re.Pattern[str] = _shared.RFC3339_TIMESTAMP_PATTERN
REASON_MIN_LEN: int = _shared.AR_OVERRIDE_REASON_MIN_LEN
REASON_MAX_LEN: int = _shared.AR_OVERRIDE_REASON_MAX_LEN

# Audit-trail-note canonical substrings.
NOTE_APPLIED_PREFIX: str = _shared.NOTE_OVERRIDE_APPLIED_PREFIX
NOTE_GUARD_TOKENS: tuple[str, ...] = _shared.NOTE_STALE_MARKER_GUARD_TOKENS
NOTE_NO_MARKER_TOKEN: str = _shared.NOTE_NO_MARKER_TOKEN


# ---------------------------------------------------------------------------
# Result types.
# ---------------------------------------------------------------------------


class _EnvelopeResult:
    """Per-envelope verdict accumulator (internal)."""

    __slots__ = (
        "path",
        "violations",
        "advisories",
        "applied",
        "input_verdict",
        "audit_trail_note",
    )

    def __init__(self, path: str) -> None:
        self.path: str = path
        self.violations: list[str] = []
        self.advisories: list[str] = []
        self.applied: bool | None = None
        self.input_verdict: str | None = None
        self.audit_trail_note: str | None = None

    def verdict(self) -> str:
        if self.violations:
            return "FAIL"
        if self.advisories:
            return "ADVISORY"
        return "PASS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "verdict": self.verdict(),
            "applied": self.applied,
            "input_verdict": self.input_verdict,
            "audit_trail_note": self.audit_trail_note,
            "violations": list(self.violations),
            "advisories": list(self.advisories),
        }


# ---------------------------------------------------------------------------
# Marker validation (read-only mirror of Tag-65 listener.validate_marker).
# ---------------------------------------------------------------------------


def _validate_marker_inline(
    marker: Mapping[str, Any], result: _EnvelopeResult
) -> None:
    """Validate marker payload, accumulating violations on ``result``.

    This is a read-only mirror of the Tag-65 listener's
    ``validate_marker`` -- but instead of raising, it appends to
    ``result.violations`` so the verifier can report every problem
    in a single pass.
    """
    if not isinstance(marker, Mapping):
        result.violations.append(
            f"override_marker is not a JSON object "
            f"(got {type(marker).__name__})"
        )
        return

    missing = [f for f in MARKER_REQUIRED_FIELDS if f not in marker]
    if missing:
        result.violations.append(
            f"override_marker missing required fields: {missing}"
        )
        # continue; we can still check what is present

    sv = marker.get("schema_version")
    if sv is not None and sv != MARKER_SCHEMA_VERSION:
        result.violations.append(
            f"override_marker schema_version mismatch: got {sv!r}, "
            f"expected {MARKER_SCHEMA_VERSION}"
        )

    kind = marker.get("kind")
    if kind is not None and kind != MARKER_KIND:
        result.violations.append(
            f"override_marker kind mismatch: got {kind!r}, "
            f"expected {MARKER_KIND!r}"
        )

    op = marker.get("operator")
    if op is not None and (
        not isinstance(op, str) or not _SLUG_RE.match(op)
    ):
        result.violations.append(
            f"override_marker operator is not a slug: {op!r}"
        )

    ts = marker.get("ts")
    if ts is not None and (
        not isinstance(ts, str) or not _TS_RE.match(ts)
    ):
        result.violations.append(
            f"override_marker ts is not RFC3339: {ts!r}"
        )

    reason = marker.get("reason")
    if reason is not None:
        if not isinstance(reason, str):
            result.violations.append(
                f"override_marker reason is not a string "
                f"(got {type(reason).__name__})"
            )
        else:
            stripped = reason.strip()
            if len(stripped) < REASON_MIN_LEN:
                result.violations.append(
                    f"override_marker reason too short "
                    f"(< {REASON_MIN_LEN} chars after strip)"
                )
            if len(stripped) > REASON_MAX_LEN:
                result.violations.append(
                    f"override_marker reason too long "
                    f"(> {REASON_MAX_LEN} chars after strip)"
                )

    risk_id = marker.get("accepted_risk_id")
    if risk_id is not None and (
        not isinstance(risk_id, str) or not _SLUG_RE.match(risk_id)
    ):
        result.violations.append(
            f"override_marker accepted_risk_id is not a slug: "
            f"{risk_id!r}"
        )

    tgt = marker.get("override_target_verdict")
    if tgt is not None and tgt != MARKER_OVERRIDE_TARGET:
        result.violations.append(
            f"override_marker override_target_verdict must be "
            f"{MARKER_OVERRIDE_TARGET!r}, got {tgt!r}"
        )

    post = marker.get("post_override_verdict")
    if post is not None and post != MARKER_POST_OVERRIDE:
        result.violations.append(
            f"override_marker post_override_verdict must be "
            f"{MARKER_POST_OVERRIDE!r}, got {post!r}"
        )


# ---------------------------------------------------------------------------
# Envelope verification.
# ---------------------------------------------------------------------------


def _check_top_level_schema(
    envelope: Mapping[str, Any], result: _EnvelopeResult
) -> bool:
    """Check required-keys + basic types. Returns True if safe to drill in."""
    missing = [k for k in ENVELOPE_REQUIRED_KEYS if k not in envelope]
    if missing:
        result.violations.append(
            f"envelope missing required keys: {missing}"
        )
        return False

    sv = envelope.get("schema_version")
    if sv != OUTPUT_SCHEMA_VERSION:
        result.violations.append(
            f"envelope schema_version mismatch: got {sv!r}, "
            f"expected {OUTPUT_SCHEMA_VERSION}"
        )

    applied = envelope.get("applied")
    if not isinstance(applied, bool):
        result.violations.append(
            f"envelope.applied must be bool, got {type(applied).__name__}"
        )
        return False

    return True


def _check_decision_consistency(
    envelope: Mapping[str, Any], result: _EnvelopeResult
) -> None:
    """Verify the (applied, verdicts, marker, note) tuple matches the rule."""
    applied = bool(envelope["applied"])
    verdict = envelope["verdict"]
    input_verdict = envelope["input_verdict"]
    marker = envelope["override_marker"]
    note = envelope["audit_trail_note"]

    result.applied = applied
    result.input_verdict = (
        input_verdict if isinstance(input_verdict, str) else None
    )
    result.audit_trail_note = (
        note if isinstance(note, str) else None
    )

    # Verdict tokens must be known.
    if input_verdict not in ALLOWED_VERDICTS:
        result.violations.append(
            f"envelope.input_verdict not in allowed set: {input_verdict!r}"
        )
    if verdict not in ALLOWED_VERDICTS:
        result.violations.append(
            f"envelope.verdict not in allowed set: {verdict!r}"
        )

    if not isinstance(note, str) or not note.strip():
        result.violations.append(
            "envelope.audit_trail_note must be a non-empty string"
        )
        note = ""  # for downstream substring checks

    if applied:
        # Override-applied branch.
        if input_verdict != VERDICT_BLOCK:
            result.violations.append(
                f"applied=true but input_verdict is {input_verdict!r}, "
                f"must be {VERDICT_BLOCK!r}"
            )
        if verdict != VERDICT_CAUTION:
            result.violations.append(
                f"applied=true but post-override verdict is "
                f"{verdict!r}, must be {VERDICT_CAUTION!r}"
            )
        if not isinstance(marker, Mapping):
            result.violations.append(
                "applied=true but override_marker is null or non-object"
            )
        else:
            _validate_marker_inline(marker, result)
            # Note must reference operator and accepted_risk_id verbatim.
            if NOTE_APPLIED_PREFIX not in note:
                result.violations.append(
                    f"applied=true but audit_trail_note missing "
                    f"prefix {NOTE_APPLIED_PREFIX!r}"
                )
            op = marker.get("operator") if isinstance(marker, Mapping) else None
            risk_id = (
                marker.get("accepted_risk_id")
                if isinstance(marker, Mapping)
                else None
            )
            if isinstance(op, str) and op and op not in note:
                result.violations.append(
                    f"applied=true but audit_trail_note does not "
                    f"reference operator {op!r}"
                )
            if (
                isinstance(risk_id, str)
                and risk_id
                and risk_id not in note
            ):
                result.violations.append(
                    f"applied=true but audit_trail_note does not "
                    f"reference accepted_risk_id {risk_id!r}"
                )
    else:
        # applied=false branch.
        if marker is None:
            # No marker -- pass-through.
            if verdict != input_verdict:
                result.violations.append(
                    f"applied=false, no marker, but verdict {verdict!r} "
                    f"!= input_verdict {input_verdict!r}"
                )
            if NOTE_NO_MARKER_TOKEN not in note:
                result.violations.append(
                    f"applied=false, no marker, but audit_trail_note "
                    f"missing {NOTE_NO_MARKER_TOKEN!r} token"
                )
        elif isinstance(marker, Mapping):
            # Marker present but not applied -- stale-marker guard.
            _validate_marker_inline(marker, result)
            if verdict != input_verdict:
                result.violations.append(
                    f"applied=false but verdict {verdict!r} != "
                    f"input_verdict {input_verdict!r} "
                    f"(stale-marker downgrade guard violated)"
                )
            if input_verdict == VERDICT_BLOCK:
                result.violations.append(
                    "applied=false with marker present AND "
                    "input_verdict=BLOCK: this combination contradicts "
                    "the Tag-65 decision rule (BLOCK + valid marker => "
                    "must apply)"
                )
            if not any(tok in note for tok in NOTE_GUARD_TOKENS):
                result.violations.append(
                    f"applied=false, marker present, but "
                    f"audit_trail_note missing guard token "
                    f"(any of {list(NOTE_GUARD_TOKENS)})"
                )
            # Soft advisory: stale-marker case is expected but
            # worth surfacing for Henrik.
            result.advisories.append(
                "marker present but not applied: stale-marker "
                "downgrade guard fired (expected behaviour)"
            )
        else:
            result.violations.append(
                f"override_marker has unexpected type "
                f"{type(marker).__name__}; must be object or null"
            )


def _check_decision_rule_block(
    envelope: Mapping[str, Any], result: _EnvelopeResult
) -> None:
    """Check the embedded decision_rule block is intact."""
    rule = envelope.get("decision_rule")
    if not isinstance(rule, Mapping):
        result.violations.append(
            "envelope.decision_rule must be an object"
        )
        return
    if rule.get("applies_to_input") != VERDICT_BLOCK:
        result.violations.append(
            f"decision_rule.applies_to_input must be "
            f"{VERDICT_BLOCK!r}, got {rule.get('applies_to_input')!r}"
        )
    if rule.get("post_override_verdict") != VERDICT_CAUTION:
        result.violations.append(
            f"decision_rule.post_override_verdict must be "
            f"{VERDICT_CAUTION!r}, "
            f"got {rule.get('post_override_verdict')!r}"
        )
    rationale = rule.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        result.violations.append(
            "decision_rule.rationale must be a non-empty string"
        )


def _check_input_envelope_preservation(
    envelope: Mapping[str, Any], result: _EnvelopeResult
) -> None:
    """The input verdict envelope MUST be preserved verbatim."""
    inp = envelope.get("input_verdict_envelope")
    if not isinstance(inp, Mapping):
        result.violations.append(
            "envelope.input_verdict_envelope must be a JSON object"
        )
        return
    inp_v = inp.get("verdict")
    if inp_v != envelope.get("input_verdict"):
        result.violations.append(
            f"input_verdict_envelope.verdict ({inp_v!r}) does not "
            f"match top-level input_verdict "
            f"({envelope.get('input_verdict')!r}); "
            f"input envelope has been mutated"
        )


def verify_envelope(
    envelope: Mapping[str, Any], path: str
) -> _EnvelopeResult:
    """Run all checks for one envelope. Returns the result accumulator."""
    result = _EnvelopeResult(path=path)
    if not isinstance(envelope, Mapping):
        result.violations.append(
            f"envelope root must be a JSON object, "
            f"got {type(envelope).__name__}"
        )
        return result
    if not _check_top_level_schema(envelope, result):
        return result
    _check_decision_consistency(envelope, result)
    _check_decision_rule_block(envelope, result)
    _check_input_envelope_preservation(envelope, result)
    return result


# ---------------------------------------------------------------------------
# File / directory plumbing.
# ---------------------------------------------------------------------------


def _iter_candidate_paths(inputs: Iterable[Path]) -> list[Path]:
    """Expand directory inputs into a sorted list of *.json files."""
    out: list[Path] = []
    for inp in inputs:
        if inp.is_dir():
            out.extend(sorted(inp.rglob("*.json")))
        elif inp.is_file():
            out.append(inp)
        # missing paths are silently skipped here; caller surfaces
        # the absence via the input_count = 0 advisory below.
    return out


def _load_envelope(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Load JSON, returning (envelope, error_message)."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"cannot read file: {exc}"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"not valid JSON: {exc}"
    if not isinstance(payload, dict):
        return None, (
            f"top-level JSON is not an object "
            f"(got {type(payload).__name__})"
        )
    return payload, None


def aggregate(
    results: list[_EnvelopeResult],
    *,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Roll per-envelope results up into the final verdict payload."""
    fail_count = sum(1 for r in results if r.verdict() == "FAIL")
    advisory_count = sum(1 for r in results if r.verdict() == "ADVISORY")
    pass_count = sum(1 for r in results if r.verdict() == "PASS")

    if fail_count > 0:
        verdict = "FAIL"
    elif advisory_count > 0:
        verdict = "ADVISORY"
    else:
        verdict = "PASS"

    now = now_utc or datetime.now(timezone.utc)
    return {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "tag": "tag-66",
        "tool": TAG66_TOOL_NAME,
        "scanned_at_utc": now.isoformat(timespec="seconds"),
        "input_count": len(results),
        "pass_count": pass_count,
        "advisory_count": advisory_count,
        "fail_count": fail_count,
        "verdict": verdict,
        "per_envelope": [r.to_dict() for r in results],
    }


# ---------------------------------------------------------------------------
# CLI plumbing.
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=TAG66_TOOL_NAME,
        description=(
            "Verify Tag-65 AR-Hand Override-Listener output envelopes "
            "against the Tag-66 Audit-Trail-Schema. Read-only, stdlib, "
            "audit-mode."
        ),
    )
    p.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help=(
            "One or more paths to listener output envelope JSON files, "
            "or directories containing such files (recursed)."
        ),
    )
    p.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the aggregate audit-trail-verifier JSON.",
    )
    p.add_argument(
        "--allow-empty",
        action="store_true",
        help=(
            "If set, zero candidate envelopes is an ADVISORY rather "
            "than a usage error. Default: zero inputs exits 2."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    paths = _iter_candidate_paths(args.inputs)

    results: list[_EnvelopeResult] = []
    for path in paths:
        envelope, err = _load_envelope(path)
        if err is not None:
            r = _EnvelopeResult(path=str(path))
            r.violations.append(err)
            results.append(r)
            continue
        assert envelope is not None
        results.append(verify_envelope(envelope, str(path)))

    if not results:
        if not args.allow_empty:
            print(
                "ERROR: no candidate envelopes found; pass --allow-empty "
                "to treat zero-input as advisory.",
                file=sys.stderr,
            )
            return 2
        # Emit an empty-but-valid rollup with ADVISORY verdict.
        empty = aggregate([])
        empty["verdict"] = "ADVISORY"
        empty["per_envelope"] = []
        empty.setdefault("notes", []).append(
            "no envelopes scanned (allow-empty mode)"
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(empty, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print("verify_ar_hand_override_audit_trail: ADVISORY (no inputs)")
        return 0

    payload = aggregate(results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"verify_ar_hand_override_audit_trail: {payload['verdict']} "
        f"(pass={payload['pass_count']}, "
        f"advisory={payload['advisory_count']}, "
        f"fail={payload['fail_count']}, "
        f"total={payload['input_count']})"
    )
    return 1 if payload["verdict"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
