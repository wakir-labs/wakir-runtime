# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the cross-repo-drift Enforce-Flip readiness layer.

Follow-up to PR #105 / PR #111 per ADR-0062 Cut-2/Cut-3.

PR #105 introduced ``.github/workflows/cross-repo-drift-audit.yml`` in
**audit-only** mode because the Day-1 baseline measurement was
``6/10`` mirror-pairs drifting. This sprint delivers the *readiness*
contract: which drift each pair carries today, which resolution
strategy applies, which allowlist entries are valid, and which
acceptance-gate thresholds must be met before the env default
flips from ``'false'`` to ``'true'``.

The hermetic tests below pin three artefacts:

1. The readiness document
   ``docs/operations/cross-repo-drift-enforce-flip-readiness.md``
   exists, has a parseable mirror-pair inventory matching the
   workflow's ``pairs=( ... )`` array, and records a status per pair.
2. The resolution-strategy mapper (re-implemented in pure Python
   below — same shape as the doc's §3.5 decision table) returns the
   documented default per drift-type.
3. The allowlist-entry validator (also re-implemented in pure
   Python below) enforces the §5 schema, and the acceptance-gate
   evaluator (also pure Python) enforces the §6 thresholds.

We deliberately re-implement the readiness primitives in Python and
parse the markdown inventory back out of the doc, so a change to the
*document* (the operator's source of truth) must be coordinated
with a change to the *tests* (CI tripwire). The contract direction
matches PR #105's hermetic test pattern.

Trade-off
---------
The readiness primitives live here (Python) and in the doc (markdown
prose). A future sprint can promote them into a shared module under
``wirelang/`` if a second consumer appears; for now the duplication
cost is one file and the contract is small.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
READINESS_DOC = (
    REPO_ROOT / "docs" / "operations" / "cross-repo-drift-enforce-flip-readiness.md"
)
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "cross-repo-drift-audit.yml"

# ---------------------------------------------------------------------------
# Pure-Python re-implementation of the readiness primitives.
#
# Kept tiny and side-effect-free so the contract is testable without
# external state. All four functions mirror the doc's wording in §3.5
# (resolution-strategy decision table), §5 (allowlist-entry schema),
# and §6 (acceptance-gate thresholds).
# ---------------------------------------------------------------------------


# Status names emitted by the audit workflow.
_KNOWN_STATUSES = {
    "clean",
    "drift",
    "drift-allowed",
    "missing-runtime",
    "missing-protocol",
    "missing-both",
}

# Resolution-strategy names recognised by the operator-doc §3.
_KNOWN_STRATEGIES = {
    "re-sync-protocol-from-runtime",
    "re-sync-runtime-from-protocol",
    "allowlist-spdx-header-only",
    "allowlist-divergent-variant",
    "delete-mirror-pair",
}


def recommend_strategy(drift_type: str, *, runtime_newer: bool | None = None) -> str:
    """Recommend a default resolution-strategy for a drift type.

    Mirrors the decision table in the doc's §3.5. The ``runtime_newer``
    knob disambiguates the symmetric ``drift`` (substance differs) case;
    callers that do not know which side is newer should pass ``None``
    and accept the default of "protocol-from-runtime" (the runtime is
    the BUSL reference implementation and is generally the one that
    evolves first in this org).
    """
    if drift_type == "drift-spdx-header-only":
        return "allowlist-spdx-header-only"
    if drift_type == "drift-divergent-variant":
        return "allowlist-divergent-variant"
    if drift_type == "drift":
        if runtime_newer is False:
            return "re-sync-runtime-from-protocol"
        return "re-sync-protocol-from-runtime"
    if drift_type == "missing-runtime":
        return "re-sync-runtime-from-protocol"
    if drift_type == "missing-protocol":
        return "re-sync-protocol-from-runtime"
    if drift_type == "missing-both":
        return "delete-mirror-pair"
    if drift_type in ("clean", "drift-allowed"):
        return "noop"
    raise ValueError(f"unknown drift type: {drift_type!r}")


def validate_allowlist_entry(entry: dict, known_pairs: set[tuple[str, str]]) -> list[str]:
    """Validate one ``.cross-repo-drift-allowlist.yaml`` entry.

    Returns the list of error strings (empty list = valid). Enforces the
    schema in the doc's §5: required ``runtime`` + ``protocol`` + non-
    empty ``reason``; the ``(runtime, protocol)`` pair must be in the
    set of known workflow mirror-pairs; optional ``follow_up`` must be
    ADR-NNNN / sprint-<slug> / "permanent" when present.
    """
    errors: list[str] = []
    if not isinstance(entry, dict):
        return ["entry must be a mapping"]

    runtime = entry.get("runtime")
    protocol = entry.get("protocol")
    reason = entry.get("reason")
    follow_up = entry.get("follow_up")

    if not runtime or not isinstance(runtime, str):
        errors.append("missing or empty 'runtime' key")
    if not protocol or not isinstance(protocol, str):
        errors.append("missing or empty 'protocol' key")
    if not reason or not isinstance(reason, str) or not reason.strip():
        errors.append("missing or empty 'reason' key")

    if runtime and protocol and (runtime, protocol) not in known_pairs:
        errors.append(
            f"pair ({runtime!r}, {protocol!r}) is not a known workflow mirror-pair"
        )

    if follow_up is not None:
        if not isinstance(follow_up, str) or not follow_up.strip():
            errors.append("'follow_up' present but not a non-empty string")
        else:
            ok = (
                follow_up == "permanent"
                or re.fullmatch(r"ADR-\d{4}", follow_up)
                or re.fullmatch(r"sprint-[a-z0-9-]+", follow_up)
            )
            if not ok:
                errors.append(
                    f"'follow_up' {follow_up!r} must be ADR-NNNN, sprint-<slug>, or 'permanent'"
                )

    return errors


def evaluate_acceptance_gate(
    *,
    drift_count: int,
    missing_count: int,
    allowed_drift_count: int,
    ok_count: int,
    pair_count: int,
    cross_review_signoffs: set[str],
    baseline_run_id: str | None,
) -> tuple[bool, list[str]]:
    """Evaluate the Enforce-Flip acceptance gate per the doc's §6.

    Returns ``(flip_ready, reasons)`` where ``reasons`` is the list of
    threshold-failure strings (empty list = flip_ready=True).
    """
    reasons: list[str] = []
    if drift_count != 0:
        reasons.append(f"drift_count={drift_count} (must be 0)")
    if missing_count != 0:
        reasons.append(f"missing_count={missing_count} (must be 0)")
    if allowed_drift_count > 3:
        reasons.append(
            f"allowed_drift_count={allowed_drift_count} (soft cap is 3)"
        )
    if ok_count + allowed_drift_count != pair_count:
        reasons.append(
            f"ok_count + allowed_drift_count = {ok_count + allowed_drift_count} "
            f"(must equal pair_count={pair_count})"
        )
    required_signoffs = {"reza", "tomas"}
    missing_signoffs = required_signoffs - {s.lower() for s in cross_review_signoffs}
    if missing_signoffs:
        reasons.append(
            f"cross-review sign-off missing from: {sorted(missing_signoffs)}"
        )
    if not baseline_run_id:
        reasons.append("baseline run-id is empty (needed for rollback per Step 8)")
    return (not reasons, reasons)


def readiness_score(
    *,
    drift_count: int,
    missing_count: int,
    allowed_drift_count: int,
    ok_count: int,
    pair_count: int,
) -> float:
    """Compute a 0.0..1.0 readiness score per mirror-pair inventory.

    The score is purely advisory (the binary flip decision is
    ``evaluate_acceptance_gate``); it is exposed as a single number
    for status-report dashboards. Definition:

    * ``ok`` and ``drift-allowed`` count as resolved (1.0 weight each).
    * ``drift`` and ``missing`` count as unresolved (0.0 weight each).
    * Score is ``resolved / pair_count``, clamped to ``[0.0, 1.0]``.
    """
    if pair_count <= 0:
        return 0.0
    resolved = ok_count + allowed_drift_count
    # Defensive clamp — drift+missing can't exceed pair_count by construction
    # but explicit clamp keeps the function total-defined.
    raw = resolved / pair_count
    if raw < 0.0:
        return 0.0
    if raw > 1.0:
        return 1.0
    return raw


# ---------------------------------------------------------------------------
# Helpers for parsing the doc's mirror-pair inventory table out of §2.
# ---------------------------------------------------------------------------


def _extract_doc_inventory() -> list[dict]:
    """Pull the §2 mirror-pair inventory rows out of the readiness doc.

    Each row is returned as a dict with keys ``runtime``, ``protocol``,
    ``status``, ``strategy``. We parse the table by row count + column
    position so a future column rename in the doc has to be reflected
    here on purpose.
    """
    assert READINESS_DOC.is_file(), f"missing readiness doc: {READINESS_DOC}"
    text = READINESS_DOC.read_text(encoding="utf-8")
    # Capture the inventory table that lives under the §2 heading.
    section_pat = re.compile(
        r"## 2\. Mirror-pair inventory.*?\| # \| Runtime path \|"
        r" Protocol path \| Status \| Resolution-Strategy \| Owner \|"
        r"(.*?)Tally:",
        re.DOTALL,
    )
    m = section_pat.search(text)
    assert m, "could not locate §2 inventory table in readiness doc"
    body = m.group(1)

    rows: list[dict] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        # Strip the header-separator "|---|..." line.
        if set(line.replace("|", "").strip()) <= {"-", ":"}:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 6:
            continue
        # First cell is the row index — skip header-row "#".
        if cells[0] == "#":
            continue
        runtime = cells[1].strip("`")
        protocol = cells[2].strip("`")
        status = cells[3].strip("`")
        strategy = cells[4].strip("`")
        rows.append(
            {
                "runtime": runtime,
                "protocol": protocol,
                "status": status,
                "strategy": strategy,
            }
        )
    return rows


def _extract_workflow_pairs() -> list[tuple[str, str]]:
    """Mirror of PR #105's hermetic extractor.

    Returns the ``(runtime, protocol)`` pair list from the workflow's
    ``pairs=( ... )`` literal.
    """
    assert WORKFLOW_PATH.is_file(), f"workflow missing: {WORKFLOW_PATH}"
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    m = re.search(r"pairs=\(\s*(.*?)\s*\)\s*\n", text, re.DOTALL)
    assert m, "could not locate pairs=(...) literal"
    pairs: list[tuple[str, str]] = []
    for raw_line in m.group(1).splitlines():
        line = raw_line.strip().strip('"')
        if not line or "|" not in line:
            continue
        r, p = line.split("|", 1)
        pairs.append((r, p))
    return pairs


# ---------------------------------------------------------------------------
# TV-RDY-01 — readiness doc exists and references the workflow.
# ---------------------------------------------------------------------------


def test_tv_rdy_01_readiness_doc_exists_and_references_workflow():
    """TV-RDY-01: the readiness doc lives at the expected path and
    explicitly names the workflow + PR #105. This is the smallest
    possible link-check that the doc is wired into the cross-repo-
    drift audit story rather than being an orphan."""
    assert READINESS_DOC.is_file(), f"missing: {READINESS_DOC}"
    body = READINESS_DOC.read_text(encoding="utf-8")
    assert ".github/workflows/cross-repo-drift-audit.yml" in body
    assert "PR #105" in body
    assert "ADR-0062" in body
    # And the doc must self-reference its hermetic test so a future
    # rename of either file fails fast on the other side.
    assert "test_cross_repo_drift_enforce_readiness" in body


# ---------------------------------------------------------------------------
# TV-RDY-02 — readiness-score primitive.
# ---------------------------------------------------------------------------


def test_tv_rdy_02_readiness_score_per_mirror_pair_inventory():
    """TV-RDY-02: the readiness-score primitive returns the expected
    fractional resolution rate across a representative set of
    inventory tallies. Pinning the numeric contract here makes the
    score safe to consume from a status-report dashboard."""
    # All clean -> 1.0.
    assert (
        readiness_score(
            drift_count=0,
            missing_count=0,
            allowed_drift_count=0,
            ok_count=10,
            pair_count=10,
        )
        == 1.0
    )
    # Day-1 baseline per PR #105: 4 clean + 6 drift -> 0.4.
    assert (
        readiness_score(
            drift_count=6,
            missing_count=0,
            allowed_drift_count=0,
            ok_count=4,
            pair_count=10,
        )
        == 0.4
    )
    # Mid-cleanup: 6 clean + 2 allowed + 2 drift -> 0.8.
    assert (
        readiness_score(
            drift_count=2,
            missing_count=0,
            allowed_drift_count=2,
            ok_count=6,
            pair_count=10,
        )
        == 0.8
    )
    # Empty inventory is 0.0, not a crash.
    assert (
        readiness_score(
            drift_count=0,
            missing_count=0,
            allowed_drift_count=0,
            ok_count=0,
            pair_count=0,
        )
        == 0.0
    )


# ---------------------------------------------------------------------------
# TV-RDY-03 — resolution-strategy recommendation per drift type.
# ---------------------------------------------------------------------------


def test_tv_rdy_03_resolution_strategy_recommendation_per_drift_type():
    """TV-RDY-03: the strategy mapper returns the exact defaults from
    the doc's §3.5 decision table for each drift type. Locks in the
    operator-facing recommendation so the doc and the code can't
    drift apart silently."""
    # Symmetric "drift" — runtime newer by default.
    assert recommend_strategy("drift") == "re-sync-protocol-from-runtime"
    assert (
        recommend_strategy("drift", runtime_newer=True)
        == "re-sync-protocol-from-runtime"
    )
    assert (
        recommend_strategy("drift", runtime_newer=False)
        == "re-sync-runtime-from-protocol"
    )

    # SPDX-header-only and divergent-variant.
    assert (
        recommend_strategy("drift-spdx-header-only")
        == "allowlist-spdx-header-only"
    )
    assert (
        recommend_strategy("drift-divergent-variant")
        == "allowlist-divergent-variant"
    )

    # Missing cases.
    assert recommend_strategy("missing-runtime") == "re-sync-runtime-from-protocol"
    assert recommend_strategy("missing-protocol") == "re-sync-protocol-from-runtime"
    assert recommend_strategy("missing-both") == "delete-mirror-pair"

    # Clean / drift-allowed are no-ops.
    assert recommend_strategy("clean") == "noop"
    assert recommend_strategy("drift-allowed") == "noop"

    # Unknown drift type is a hard error (so a future status name
    # change can't silently fall through to a default).
    with pytest.raises(ValueError):
        recommend_strategy("schroedingers-drift")


# ---------------------------------------------------------------------------
# TV-RDY-04 — allowlist-entry validator.
# ---------------------------------------------------------------------------


def test_tv_rdy_04_allowlist_entry_validation():
    """TV-RDY-04: the allowlist-entry validator enforces the §5 schema.

    Pinning the validator into CI is the difference between "allowlist
    can be silently extended" and "every waiver is named, justified,
    and bounded by a follow-up". The doc states the contract; this
    test makes it executable.
    """
    known_pairs = set(_extract_workflow_pairs())

    # Pick a known pair to use as the valid-baseline.
    valid_pair = next(iter(known_pairs))

    # Valid entry — all required fields, known pair.
    entry_ok = {
        "runtime": valid_pair[0],
        "protocol": valid_pair[1],
        "reason": "SPDX-header-only between BUSL and Apache",
        "follow_up": "permanent",
    }
    assert validate_allowlist_entry(entry_ok, known_pairs) == []

    # Valid entry with an ADR follow_up.
    entry_adr = dict(entry_ok)
    entry_adr["follow_up"] = "ADR-0062"
    assert validate_allowlist_entry(entry_adr, known_pairs) == []

    # Valid entry with a sprint follow_up.
    entry_sprint = dict(entry_ok)
    entry_sprint["follow_up"] = "sprint-cross-repo-enforce-readiness-mini"
    assert validate_allowlist_entry(entry_sprint, known_pairs) == []

    # Missing required keys -> errors collected, not raised.
    bad_missing_reason = {
        "runtime": valid_pair[0],
        "protocol": valid_pair[1],
        "reason": "",
    }
    errs = validate_allowlist_entry(bad_missing_reason, known_pairs)
    assert any("reason" in e for e in errs)

    # Unknown pair -> rejected.
    bad_unknown_pair = {
        "runtime": "wirelang/schemas/ghost.json",
        "protocol": "wakir_protocol/schemas/ghost.json",
        "reason": "Trying to sneak in a contract surface",
    }
    errs = validate_allowlist_entry(bad_unknown_pair, known_pairs)
    assert any("not a known workflow mirror-pair" in e for e in errs)

    # Bad follow_up shape -> rejected.
    bad_followup = dict(entry_ok)
    bad_followup["follow_up"] = "soonish"
    errs = validate_allowlist_entry(bad_followup, known_pairs)
    assert any("follow_up" in e for e in errs)

    # Non-mapping entry -> single error.
    assert validate_allowlist_entry("not-a-dict", known_pairs) == [
        "entry must be a mapping"
    ]


# ---------------------------------------------------------------------------
# TV-RDY-05 — acceptance-gate threshold evaluator.
# ---------------------------------------------------------------------------


def test_tv_rdy_05_acceptance_thresholds():
    """TV-RDY-05: the acceptance-gate evaluator implements the §6
    thresholds. The six thresholds (drift=0, missing=0,
    allowed_drift<=3, ok+allowed==pair_count, both sign-offs, baseline
    run-id present) are all required for ``flip_ready=True``."""
    pair_count = 10

    # Flip-ready run.
    ok, reasons = evaluate_acceptance_gate(
        drift_count=0,
        missing_count=0,
        allowed_drift_count=2,
        ok_count=8,
        pair_count=pair_count,
        cross_review_signoffs={"Reza", "Tomas"},
        baseline_run_id="run-12345",
    )
    assert ok is True
    assert reasons == []

    # Drift > 0 blocks.
    ok, reasons = evaluate_acceptance_gate(
        drift_count=1,
        missing_count=0,
        allowed_drift_count=2,
        ok_count=7,
        pair_count=pair_count,
        cross_review_signoffs={"reza", "tomas"},
        baseline_run_id="run-12345",
    )
    assert ok is False
    assert any("drift_count" in r for r in reasons)

    # Missing > 0 blocks.
    ok, reasons = evaluate_acceptance_gate(
        drift_count=0,
        missing_count=1,
        allowed_drift_count=2,
        ok_count=7,
        pair_count=pair_count,
        cross_review_signoffs={"reza", "tomas"},
        baseline_run_id="run-12345",
    )
    assert ok is False
    assert any("missing_count" in r for r in reasons)

    # Soft-cap on allowed_drift_count > 3 blocks.
    ok, reasons = evaluate_acceptance_gate(
        drift_count=0,
        missing_count=0,
        allowed_drift_count=4,
        ok_count=6,
        pair_count=pair_count,
        cross_review_signoffs={"reza", "tomas"},
        baseline_run_id="run-12345",
    )
    assert ok is False
    assert any("allowed_drift_count" in r for r in reasons)

    # ok + allowed != pair_count blocks (catches __MALFORMED__ allowlist).
    ok, reasons = evaluate_acceptance_gate(
        drift_count=0,
        missing_count=0,
        allowed_drift_count=2,
        ok_count=7,  # 7 + 2 = 9, not 10
        pair_count=pair_count,
        cross_review_signoffs={"reza", "tomas"},
        baseline_run_id="run-12345",
    )
    assert ok is False
    assert any("ok_count + allowed_drift_count" in r for r in reasons)

    # Missing sign-off blocks.
    ok, reasons = evaluate_acceptance_gate(
        drift_count=0,
        missing_count=0,
        allowed_drift_count=2,
        ok_count=8,
        pair_count=pair_count,
        cross_review_signoffs={"reza"},
        baseline_run_id="run-12345",
    )
    assert ok is False
    assert any("sign-off" in r for r in reasons)

    # Missing baseline run-id blocks.
    ok, reasons = evaluate_acceptance_gate(
        drift_count=0,
        missing_count=0,
        allowed_drift_count=2,
        ok_count=8,
        pair_count=pair_count,
        cross_review_signoffs={"reza", "tomas"},
        baseline_run_id=None,
    )
    assert ok is False
    assert any("baseline run-id" in r for r in reasons)


# ---------------------------------------------------------------------------
# TV-RDY-06 — doc inventory matches workflow pairs literally.
# ---------------------------------------------------------------------------


def test_tv_rdy_06_doc_inventory_matches_workflow_pairs():
    """TV-RDY-06: the §2 inventory table in the readiness doc has
    exactly the same ``(runtime, protocol)`` pairs in the same order
    as the workflow's ``pairs=( ... )`` array literal.

    This is the critical cross-link: the operator reads the doc; the
    CI reads the workflow. They must agree pair-for-pair or the
    Enforce-Flip is operating on a different inventory than the
    operator just verified.
    """
    workflow_pairs = _extract_workflow_pairs()
    doc_rows = _extract_doc_inventory()
    doc_pairs = [(row["runtime"], row["protocol"]) for row in doc_rows]

    assert doc_pairs == workflow_pairs, (
        "mirror-pair inventory in readiness doc does not match workflow "
        "literal — operator and CI would diverge on the Enforce-Flip"
    )


# ---------------------------------------------------------------------------
# TV-RDY-07 — every documented status and strategy is known.
# ---------------------------------------------------------------------------


def test_tv_rdy_07_documented_statuses_and_strategies_are_known():
    """TV-RDY-07: every status in the §2 inventory is a known audit
    status, and every strategy reference is a known resolution
    strategy. Guards against a typo turning into an undetected
    "this row has no resolution path".
    """
    doc_rows = _extract_doc_inventory()
    assert doc_rows, "doc inventory is empty — extractor likely broke"

    for row in doc_rows:
        assert row["status"] in _KNOWN_STATUSES, (
            f"unknown status {row['status']!r} in row {row['runtime']!r}"
        )
        # "—" is the documented sentinel for clean rows / no strategy.
        strategy = row["strategy"]
        if strategy in {"—", "-", ""}:
            assert row["status"] in {"clean", "drift-allowed"}, (
                f"row {row['runtime']!r} has no strategy but status "
                f"{row['status']!r} requires one"
            )
            continue
        assert strategy in _KNOWN_STRATEGIES, (
            f"unknown strategy {strategy!r} in row {row['runtime']!r}"
        )


# ---------------------------------------------------------------------------
# TV-RDY-08 — Day-1 baseline of 6/10 drift is documented.
# ---------------------------------------------------------------------------


def test_tv_rdy_08_day1_baseline_tally_matches_reza_measurement():
    """TV-RDY-08: the §2 inventory documents Reza's Day-1 baseline
    measurement of ``drift=6 / clean=4 / missing=0 / pair_count=10``.

    If a future sprint resolves drift and updates the inventory, this
    test will fail — that is the intended signal: update the doc's
    tally line and this test together, never one without the other.
    """
    doc_rows = _extract_doc_inventory()
    tally = {"clean": 0, "drift": 0, "missing": 0, "other": 0}
    for row in doc_rows:
        s = row["status"]
        if s == "clean":
            tally["clean"] += 1
        elif s == "drift":
            tally["drift"] += 1
        elif s in ("missing-runtime", "missing-protocol", "missing-both"):
            tally["missing"] += 1
        else:
            tally["other"] += 1

    assert tally["clean"] == 4
    assert tally["drift"] == 6
    assert tally["missing"] == 0
    assert tally["other"] == 0
    assert len(doc_rows) == 10
