# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Routing A/B-Test Diff — ADR-0064 §4 (diff-CLI substrate).

Overview
--------

ADR-0064 (Model-Routing + Prompt-Caching, approved 2026-05-16) §4
prescribes an A/B-test protocol to compare routing-mode candidates
(static vs. heuristic vs. llm_classifier) side-by-side. The
:class:`heuristic_router.HeuristicRoutingShim` and the
:class:`llm_classifier.LlmClassifierRouter` already emit structured
:class:`RoutingEvent` / :class:`LlmClassifierEvent` envelopes per call
(see PR #133 + PR #138). This module is the third pillar: a
**pure-stdlib library** that loads two such structured-JSON event logs
("baseline" + "candidate"), aligns them by ``auftrag_id``, and
produces a :class:`RoutingDiffReport` capturing:

- per-task decision-path delta (HAIKU/SONNET/OPUS),
- per-task cost-delta (relative cost-units, tier-weighted),
- decision-distribution buckets for each log,
- total-cost-delta (sum of per-task deltas),
- confidence histogram (llm_classifier only — for baseline /
  candidate sides where the events carry ``classifier_confidence``),
- consistency-score (share of paired tasks where
  ``baseline.effective_choice == candidate.effective_choice``) and
  a ``PASS / FAIL`` verdict against a configurable threshold.

The CLI in :mod:`bin/wakir-routing-diff` is a thin shim around the
:func:`compare_routing_logs` library entrypoint here.

Envelope contract — accepted shapes
-----------------------------------

The diff-engine reads each input log line-by-line as JSON. Each line
is *either* a :class:`RoutingEvent` (heuristic) *or* a
:class:`LlmClassifierEvent` (llm-classifier) — the parser sniffs by
the presence of the ``classifier_choice`` key (LlmClassifierEvent
marker) vs. ``heuristic_choice`` alone (RoutingEvent).

Fields read (both shapes):

- ``auftrag_id`` — alignment key (string; required).
- ``effective_choice`` — tier-name string (``haiku`` / ``sonnet`` /
  ``opus``); required. This is the *de facto* tier the engine would
  serve.
- ``persona_id`` — copied through into per-task diff rows (optional).
- ``routing_mode`` — copied through (optional, for the report header).
- ``ts_utc`` — copied through (optional, for the report header).

Fields read (LlmClassifierEvent only):

- ``classifier_confidence`` — float in [0, 1].
- ``used_fallback`` — bool.
- ``classifier_rationale`` — str.

Lines that fail to parse as JSON, lack ``auftrag_id``, or lack
``effective_choice`` are recorded in :attr:`RoutingDiffReport.parse_errors`
and excluded from the diff body. The diff never raises on a malformed
input line — the substrate keeps producing a report so operators can
inspect both the diff and the parse-error inventory in one pass.

Alignment + symmetric difference
--------------------------------

The diff aligns by ``auftrag_id``. The report distinguishes:

- ``paired_tasks`` — task-IDs present in both logs; the per-task diff
  rows describe these.
- ``baseline_only_tasks`` — task-IDs present in baseline but not in
  candidate (likely log-rotation skew).
- ``candidate_only_tasks`` — task-IDs present in candidate but not in
  baseline (likely a new run subset).

The consistency-score and PASS verdict are computed over
``paired_tasks`` only.

Tier cost-weight model
----------------------

Per-task cost is approximated from the *effective tier* using a
fixed relative-cost-unit table (chosen to mirror Anthropic-pricing-
page tiers as of 2026-05-16 list-price): Haiku=1, Sonnet=12, Opus=60.
The diff library does **not** read upstream token-counts (RoutingEvent
captures ``token_len_estimate`` but the LlmClassifierEvent envelope
re-uses the same field via its embedded ``inputs`` dict).

When ``token_len_estimate`` *is* available in the event ``inputs``
dict, the per-task cost is scaled by
``max(1, token_len_estimate)`` so longer tasks contribute more to the
total-cost delta. When the field is missing, the per-task cost
falls back to the bare tier-weight (1 unit). This keeps the
substrate working on the bare RoutingEvent / LlmClassifierEvent
shape without requiring an extra schema field.

The cost-weight table is exposed as :data:`TIER_COST_UNITS` so
operators / tests / Phase-3 tunings can substitute it.

Consistency-score + PASS verdict
--------------------------------

For each paired task, the row is *consistent* iff the baseline's
``effective_choice`` equals the candidate's ``effective_choice``.
``consistency_score`` is ``consistent_count / paired_count`` (float
in [0, 1]; 1.0 if there are no paired tasks — vacuously consistent,
but the report header flags the zero-pair case explicitly).

The PASS verdict is ``consistency_score >= threshold`` (default
0.95, configurable via :func:`compare_routing_logs` parameter or
the ``--threshold`` CLI flag).

Confidence histogram
--------------------

When either side carries LlmClassifierEvent entries with a
``classifier_confidence`` float, the report builds a 10-bucket
histogram per side: ``[0.0, 0.1), [0.1, 0.2), ..., [0.9, 1.0]`` (the
top bucket is closed on the right to include exact 1.0). The
histogram is keyed by side (``baseline`` / ``candidate``) and missing
for sides that have no classifier-events.

Hermetic-test surface
---------------------

All tests in ``wirelang/tests/persona_engine/test_routing_diff.py`` are
pure-stdlib. This module imports only ``dataclasses``, ``json``,
``pathlib``, ``typing`` from the stdlib.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Union

ROUTING_DIFF_SCHEMA = "wakir.routing.diff/1"
ROUTING_DIFF_VERSION = "v1"

# Relative tier-cost units (Anthropic list-price ratios 2026-05-16,
# rounded for cost-arithmetic readability).
TIER_COST_UNITS: dict[str, int] = {
    "haiku": 1,
    "sonnet": 12,
    "opus": 60,
}

# Default PASS-threshold for consistency-score (per Mira-Spec
# Sprint-AB-Routing-Diff-CLI-MINI 2026-05-17).
DEFAULT_CONSISTENCY_THRESHOLD = 0.95

# Confidence-histogram bucket boundaries: 10 equal-width buckets
# over [0.0, 1.0]; the topmost bucket is closed on the right so an
# exact 1.0 confidence lands in bucket "0.9-1.0".
_CONFIDENCE_BUCKET_COUNT = 10


# ---------------------------------------------------------------------------
# Parsed event row
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedRoutingRow:
    """One event-line parsed into a uniform shape for diffing.

    Both :class:`heuristic_router.RoutingEvent` and
    :class:`llm_classifier.LlmClassifierEvent` collapse to this shape.
    """

    auftrag_id: str
    persona_id: Optional[str]
    routing_mode: Optional[str]
    ts_utc: Optional[str]
    effective_choice: str
    classifier_confidence: Optional[float]
    used_fallback: Optional[bool]
    classifier_rationale: Optional[str]
    token_len_estimate: Optional[int]
    event_kind: str  # "routing_event" | "classifier_event"

    @classmethod
    def from_json_line(cls, raw: str) -> Optional["ParsedRoutingRow"]:
        """Parse a single JSON-line; return ``None`` on any failure.

        Failures are silent here so callers (typically
        :func:`compare_routing_logs`) decide how to record them.
        """
        raw = raw.strip()
        if not raw:
            return None
        try:
            obj = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if not isinstance(obj, dict):
            return None
        auftrag_id = obj.get("auftrag_id")
        effective_choice = obj.get("effective_choice")
        if not isinstance(auftrag_id, str) or not auftrag_id:
            return None
        if not isinstance(effective_choice, str) or not effective_choice:
            return None
        kind = (
            "classifier_event"
            if "classifier_choice" in obj
            else "routing_event"
        )
        token_len = None
        inputs = obj.get("inputs")
        if isinstance(inputs, dict):
            raw_tl = inputs.get("token_len_estimate")
            if isinstance(raw_tl, int) and raw_tl >= 0:
                token_len = raw_tl
        confidence_raw = obj.get("classifier_confidence")
        confidence: Optional[float]
        if isinstance(confidence_raw, (int, float)):
            confidence = float(confidence_raw)
        else:
            confidence = None
        used_fallback_raw = obj.get("used_fallback")
        used_fallback: Optional[bool]
        if isinstance(used_fallback_raw, bool):
            used_fallback = used_fallback_raw
        else:
            used_fallback = None
        rationale_raw = obj.get("classifier_rationale")
        rationale = rationale_raw if isinstance(rationale_raw, str) else None
        return cls(
            auftrag_id=auftrag_id,
            persona_id=obj.get("persona_id") if isinstance(
                obj.get("persona_id"), str
            ) else None,
            routing_mode=obj.get("routing_mode") if isinstance(
                obj.get("routing_mode"), str
            ) else None,
            ts_utc=obj.get("ts_utc") if isinstance(
                obj.get("ts_utc"), str
            ) else None,
            effective_choice=effective_choice.strip().lower(),
            classifier_confidence=confidence,
            used_fallback=used_fallback,
            classifier_rationale=rationale,
            token_len_estimate=token_len,
            event_kind=kind,
        )


# ---------------------------------------------------------------------------
# Per-task diff row
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoutingDiffRow:
    """One paired-task per-side diff row."""

    auftrag_id: str
    persona_id: Optional[str]
    baseline_choice: str
    candidate_choice: str
    consistent: bool
    baseline_cost_units: float
    candidate_cost_units: float
    cost_delta_units: float  # candidate - baseline
    baseline_confidence: Optional[float]
    candidate_confidence: Optional[float]


# ---------------------------------------------------------------------------
# Aggregated report
# ---------------------------------------------------------------------------


@dataclass
class RoutingDiffReport:
    """Aggregate diff report.

    Field semantics:

    - ``threshold`` — operator-supplied consistency-threshold; PASS iff
      ``consistency_score >= threshold``.
    - ``rows`` — per paired-task rows (sorted by ``auftrag_id``).
    - ``baseline_distribution`` / ``candidate_distribution`` — tier
      → count over the *full* baseline / candidate input (paired +
      side-only tasks). Keys are always all of ``{"haiku", "sonnet",
      "opus"}``; unobserved tiers map to ``0``.
    - ``baseline_only_tasks`` / ``candidate_only_tasks`` — task-IDs
      in only one side (sorted).
    - ``total_baseline_cost_units`` / ``total_candidate_cost_units`` —
      sum of per-task cost-units over *paired* rows only. Side-only
      tasks are excluded so the total-cost-delta is on like-for-like
      task population.
    - ``total_cost_delta_units`` — sum of per-row ``cost_delta_units``;
      equals ``total_candidate_cost_units - total_baseline_cost_units``.
    - ``confidence_histogram`` — ``{"baseline": [10 ints], "candidate":
      [10 ints]}``; absent side keys omitted when no classifier events.
    - ``parse_errors`` — dicts ``{"side": "baseline"|"candidate",
      "line_number": int, "reason": str}``; never raises on a bad line.
    - ``schema`` / ``version`` — wire-format markers.

    The report is serializable to byte-stable JSON via :meth:`to_json`
    (keys sorted, no whitespace).
    """

    threshold: float
    pair_count: int
    consistent_count: int
    consistency_score: float
    verdict: str  # "PASS" | "FAIL"
    rows: list[RoutingDiffRow] = field(default_factory=list)
    baseline_distribution: dict = field(default_factory=dict)
    candidate_distribution: dict = field(default_factory=dict)
    baseline_only_tasks: list[str] = field(default_factory=list)
    candidate_only_tasks: list[str] = field(default_factory=list)
    total_baseline_cost_units: float = 0.0
    total_candidate_cost_units: float = 0.0
    total_cost_delta_units: float = 0.0
    confidence_histogram: dict = field(default_factory=dict)
    parse_errors: list[dict] = field(default_factory=list)
    schema: str = field(default=ROUTING_DIFF_SCHEMA)
    version: str = field(default=ROUTING_DIFF_VERSION)

    def to_json(self) -> str:
        """Byte-stable JSON serialization (sorted keys, compact)."""
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))

    def to_summary(self) -> str:
        """Human-readable plain-text summary (multi-line)."""
        lines: list[str] = []
        lines.append(f"Routing-Diff Report ({self.schema} {self.version})")
        lines.append("=" * 60)
        lines.append(f"Threshold        : {self.threshold:.4f}")
        lines.append(f"Paired tasks     : {self.pair_count}")
        lines.append(f"Consistent       : {self.consistent_count}")
        lines.append(f"Consistency-Score: {self.consistency_score:.4f}")
        lines.append(f"Verdict          : {self.verdict}")
        lines.append(
            f"Baseline-only    : {len(self.baseline_only_tasks)}"
        )
        lines.append(
            f"Candidate-only   : {len(self.candidate_only_tasks)}"
        )
        lines.append("")
        lines.append("Decision Distribution (full input)")
        lines.append("-" * 60)
        lines.append("  Tier       Baseline   Candidate")
        for tier in ("haiku", "sonnet", "opus"):
            b = self.baseline_distribution.get(tier, 0)
            c = self.candidate_distribution.get(tier, 0)
            lines.append(f"  {tier:<10s} {b:>8d}   {c:>9d}")
        lines.append("")
        lines.append("Cost (paired-only, relative units)")
        lines.append("-" * 60)
        lines.append(f"  Baseline total : {self.total_baseline_cost_units:.2f}")
        lines.append(f"  Candidate total: {self.total_candidate_cost_units:.2f}")
        lines.append(f"  Delta (c-b)    : {self.total_cost_delta_units:+.2f}")
        if self.confidence_histogram:
            lines.append("")
            lines.append("Confidence Histogram (LlmClassifierEvent only)")
            lines.append("-" * 60)
            lines.append("  Bucket      Baseline  Candidate")
            for i in range(_CONFIDENCE_BUCKET_COUNT):
                lo = i / _CONFIDENCE_BUCKET_COUNT
                hi = (i + 1) / _CONFIDENCE_BUCKET_COUNT
                bracket = "]" if i == _CONFIDENCE_BUCKET_COUNT - 1 else ")"
                label = f"[{lo:.1f},{hi:.1f}{bracket}"
                b = (
                    self.confidence_histogram.get("baseline", [0] * _CONFIDENCE_BUCKET_COUNT)[i]
                )
                c = (
                    self.confidence_histogram.get("candidate", [0] * _CONFIDENCE_BUCKET_COUNT)[i]
                )
                lines.append(f"  {label:<10s} {b:>8d}   {c:>9d}")
        if self.parse_errors:
            lines.append("")
            lines.append(f"Parse Errors ({len(self.parse_errors)})")
            lines.append("-" * 60)
            for err in self.parse_errors[:20]:
                lines.append(
                    f"  side={err.get('side')} line={err.get('line_number')} "
                    f"reason={err.get('reason')}"
                )
            if len(self.parse_errors) > 20:
                lines.append(f"  ... ({len(self.parse_errors) - 20} more)")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _load_log_rows(
    text: str, *, side: str
) -> tuple[list[ParsedRoutingRow], list[dict]]:
    """Parse all lines of a log; return rows + parse-error inventory."""
    rows: list[ParsedRoutingRow] = []
    errors: list[dict] = []
    for idx, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        row = ParsedRoutingRow.from_json_line(stripped)
        if row is None:
            errors.append(
                {
                    "side": side,
                    "line_number": idx,
                    "reason": "malformed-or-missing-required-fields",
                }
            )
            continue
        rows.append(row)
    return rows, errors


def _read_path_or_str(source: Union[str, Path]) -> str:
    """Read ``source`` as a UTF-8 file path; pass strings through.

    The library accepts both for ergonomic test use; the CLI always
    passes a :class:`Path`.
    """
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8")
    return source


# ---------------------------------------------------------------------------
# Cost + distribution aggregation
# ---------------------------------------------------------------------------


def _cost_units_for_row(row: ParsedRoutingRow) -> float:
    """Compute per-task cost-units for one row.

    Cost = tier-weight * max(1, token_len_estimate). When
    ``token_len_estimate`` is missing the row contributes the bare
    tier-weight.
    """
    tier_weight = TIER_COST_UNITS.get(row.effective_choice, 0)
    tokens = row.token_len_estimate or 1
    if tokens < 1:
        tokens = 1
    return float(tier_weight * tokens)


def _distribution(rows: Iterable[ParsedRoutingRow]) -> dict:
    dist = {"haiku": 0, "sonnet": 0, "opus": 0}
    for row in rows:
        if row.effective_choice in dist:
            dist[row.effective_choice] += 1
    return dist


def _confidence_bucket(value: float) -> int:
    """Map a confidence ``[0, 1]`` value to a bucket index 0..9."""
    if value < 0.0:
        value = 0.0
    if value >= 1.0:
        return _CONFIDENCE_BUCKET_COUNT - 1
    return int(value * _CONFIDENCE_BUCKET_COUNT)


def _confidence_histogram(rows: Iterable[ParsedRoutingRow]) -> Optional[list[int]]:
    """Build a 10-bucket histogram; ``None`` if no rows carry confidence."""
    hist = [0] * _CONFIDENCE_BUCKET_COUNT
    any_confidence = False
    for row in rows:
        if row.classifier_confidence is None:
            continue
        any_confidence = True
        hist[_confidence_bucket(row.classifier_confidence)] += 1
    return hist if any_confidence else None


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def compare_routing_logs(
    baseline: Union[str, Path],
    candidate: Union[str, Path],
    *,
    threshold: float = DEFAULT_CONSISTENCY_THRESHOLD,
) -> RoutingDiffReport:
    """Compare two structured-JSON routing-event logs.

    Parameters:

    - ``baseline`` / ``candidate``: either a :class:`pathlib.Path` to
      a JSON-lines log file, or the raw text of such a log (string).
    - ``threshold``: PASS-cutoff for the consistency-score (default
      :data:`DEFAULT_CONSISTENCY_THRESHOLD`).

    Returns a :class:`RoutingDiffReport`. The function never raises on
    malformed input lines — parse errors are recorded in the report.
    """
    # Clamp threshold defensively to [0, 1] so a misconfigured CLI
    # never produces a vacuously PASS-ing or impossible verdict.
    if threshold < 0.0:
        threshold = 0.0
    if threshold > 1.0:
        threshold = 1.0

    baseline_text = _read_path_or_str(baseline)
    candidate_text = _read_path_or_str(candidate)

    baseline_rows, baseline_errors = _load_log_rows(
        baseline_text, side="baseline"
    )
    candidate_rows, candidate_errors = _load_log_rows(
        candidate_text, side="candidate"
    )

    # Last-write-wins de-duplication per auftrag_id: if a log contains
    # multiple events for the same task-id, the later line dominates.
    # Operators occasionally re-run a task and append a new event; the
    # comparison should reflect the last observed verdict.
    baseline_by_id: dict[str, ParsedRoutingRow] = {}
    for row in baseline_rows:
        baseline_by_id[row.auftrag_id] = row
    candidate_by_id: dict[str, ParsedRoutingRow] = {}
    for row in candidate_rows:
        candidate_by_id[row.auftrag_id] = row

    baseline_ids = set(baseline_by_id.keys())
    candidate_ids = set(candidate_by_id.keys())
    paired_ids = sorted(baseline_ids & candidate_ids)
    baseline_only = sorted(baseline_ids - candidate_ids)
    candidate_only = sorted(candidate_ids - baseline_ids)

    diff_rows: list[RoutingDiffRow] = []
    consistent_count = 0
    total_baseline_cost = 0.0
    total_candidate_cost = 0.0
    for tid in paired_ids:
        b = baseline_by_id[tid]
        c = candidate_by_id[tid]
        b_cost = _cost_units_for_row(b)
        c_cost = _cost_units_for_row(c)
        consistent = b.effective_choice == c.effective_choice
        if consistent:
            consistent_count += 1
        total_baseline_cost += b_cost
        total_candidate_cost += c_cost
        diff_rows.append(
            RoutingDiffRow(
                auftrag_id=tid,
                persona_id=b.persona_id or c.persona_id,
                baseline_choice=b.effective_choice,
                candidate_choice=c.effective_choice,
                consistent=consistent,
                baseline_cost_units=b_cost,
                candidate_cost_units=c_cost,
                cost_delta_units=c_cost - b_cost,
                baseline_confidence=b.classifier_confidence,
                candidate_confidence=c.classifier_confidence,
            )
        )

    pair_count = len(paired_ids)
    if pair_count == 0:
        consistency_score = 1.0  # vacuously consistent — see module doc
    else:
        consistency_score = consistent_count / pair_count
    verdict = "PASS" if consistency_score >= threshold else "FAIL"

    confidence_hist: dict = {}
    bh = _confidence_histogram(baseline_by_id.values())
    if bh is not None:
        confidence_hist["baseline"] = bh
    ch = _confidence_histogram(candidate_by_id.values())
    if ch is not None:
        confidence_hist["candidate"] = ch

    return RoutingDiffReport(
        threshold=threshold,
        pair_count=pair_count,
        consistent_count=consistent_count,
        consistency_score=consistency_score,
        verdict=verdict,
        rows=diff_rows,
        baseline_distribution=_distribution(baseline_by_id.values()),
        candidate_distribution=_distribution(candidate_by_id.values()),
        baseline_only_tasks=baseline_only,
        candidate_only_tasks=candidate_only,
        total_baseline_cost_units=total_baseline_cost,
        total_candidate_cost_units=total_candidate_cost,
        total_cost_delta_units=total_candidate_cost - total_baseline_cost,
        confidence_histogram=confidence_hist,
        parse_errors=baseline_errors + candidate_errors,
    )


# ---------------------------------------------------------------------------
# CLI entrypoint (thin — invoked from bin/wakir-routing-diff)
# ---------------------------------------------------------------------------


def _build_argparser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="wakir-routing-diff",
        description=(
            "Diff two structured-JSON routing-event logs "
            "(ADR-0064 §4 A/B-test). Compares heuristic / "
            "llm-classifier verdicts side-by-side."
        ),
    )
    parser.add_argument(
        "--baseline-log",
        required=True,
        type=Path,
        help="Path to the baseline routing-event log (JSON-lines).",
    )
    parser.add_argument(
        "--candidate-log",
        required=True,
        type=Path,
        help="Path to the candidate routing-event log (JSON-lines).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_CONSISTENCY_THRESHOLD,
        help=(
            f"Consistency PASS-threshold (default "
            f"{DEFAULT_CONSISTENCY_THRESHOLD})."
        ),
    )
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument(
        "--json",
        dest="output_format",
        action="store_const",
        const="json",
        help="Emit machine-readable JSON (default).",
    )
    fmt.add_argument(
        "--summary",
        dest="output_format",
        action="store_const",
        const="summary",
        help="Emit human-readable plain-text summary.",
    )
    parser.set_defaults(output_format="json")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry-point — returns exit-code (0 = PASS, 1 = FAIL).

    Exit-codes:

    - ``0`` — verdict is PASS.
    - ``1`` — verdict is FAIL (consistency-score below threshold).
    - ``2`` — input file missing or unreadable.
    """
    parser = _build_argparser()
    args = parser.parse_args(argv)
    try:
        report = compare_routing_logs(
            args.baseline_log,
            args.candidate_log,
            threshold=args.threshold,
        )
    except FileNotFoundError as exc:
        print(f"error: input file not found: {exc}", flush=True)
        return 2
    except OSError as exc:
        print(f"error: input file unreadable: {exc}", flush=True)
        return 2
    if args.output_format == "summary":
        print(report.to_summary())
    else:
        print(report.to_json())
    return 0 if report.verdict == "PASS" else 1


__all__ = [
    "DEFAULT_CONSISTENCY_THRESHOLD",
    "ParsedRoutingRow",
    "ROUTING_DIFF_SCHEMA",
    "ROUTING_DIFF_VERSION",
    "RoutingDiffReport",
    "RoutingDiffRow",
    "TIER_COST_UNITS",
    "compare_routing_logs",
    "main",
]
