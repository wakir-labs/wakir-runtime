# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the Routing A/B-test Diff (ADR-0064 §4).

All tests are pure-stdlib — no network, no LLM, no NATS. Test coverage
matrix (12 tests):

1.  ``ParsedRoutingRow.from_json_line``: valid RoutingEvent JSON.
2.  ``ParsedRoutingRow.from_json_line``: valid LlmClassifierEvent JSON.
3.  ``ParsedRoutingRow.from_json_line``: malformed JSON → None.
4.  ``ParsedRoutingRow.from_json_line``: missing required fields → None.
5.  ``compare_routing_logs``: identical logs → 1.0 consistency + PASS.
6.  ``compare_routing_logs``: one drift row drops the score below
    threshold → FAIL.
7.  ``compare_routing_logs``: symmetric-difference task-IDs land in
    baseline_only / candidate_only.
8.  ``compare_routing_logs``: tier-cost-delta = sum of per-row deltas.
9.  ``compare_routing_logs``: confidence histogram present iff
    LlmClassifierEvent rows exist.
10. ``compare_routing_logs``: parse_errors recorded for malformed
    lines without raising.
11. ``RoutingDiffReport.to_json``: byte-stable serialization
    (sort_keys + compact separators).
12. ``RoutingDiffReport.to_summary``: human-readable summary contains
    the verdict line.
13. ``main``: returns exit-code 0 on PASS, 1 on FAIL, 2 on missing
    input file.

The tests are deliberately tabular where the cardinality is small so
the substrate's deterministic contract is visible in the test source.
"""

from __future__ import annotations

import json

import pytest

from wirelang.persona_engine.routing_diff import (
    DEFAULT_CONSISTENCY_THRESHOLD,
    ParsedRoutingRow,
    RoutingDiffReport,
    TIER_COST_UNITS,
    compare_routing_logs,
    main,
)


# ---------------------------------------------------------------------------
# Test-fixture helpers
# ---------------------------------------------------------------------------


def _routing_event(
    *,
    auftrag_id: str,
    persona_id: str = "tomas",
    effective_choice: str = "sonnet",
    static_choice: str = "sonnet",
    heuristic_choice: str = "sonnet",
    token_len: int = 100,
) -> str:
    """Build a RoutingEvent-shaped JSON line."""
    obj = {
        "auftrag_id": auftrag_id,
        "persona_id": persona_id,
        "ts_utc": "2026-05-17T02:00:00Z",
        "routing_mode": "static",
        "static_choice": static_choice,
        "heuristic_choice": heuristic_choice,
        "effective_choice": effective_choice,
        "befugnis_override": None,
        "inputs": {
            "token_len_estimate": token_len,
            "token_len_score": 0,
            "schema_complexity_raw": 0,
            "schema_complexity_score": -1,
            "code_block_count": 0,
            "code_vs_prose_score": -1,
            "persona_role_band": "engineering",
            "persona_role_score": 0,
        },
        "router_version": "v1",
    }
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _classifier_event(
    *,
    auftrag_id: str,
    persona_id: str = "tomas",
    effective_choice: str = "sonnet",
    classifier_choice: str = "sonnet",
    confidence: float = 0.85,
    used_fallback: bool = False,
    token_len: int = 100,
) -> str:
    """Build an LlmClassifierEvent-shaped JSON line."""
    obj = {
        "auftrag_id": auftrag_id,
        "persona_id": persona_id,
        "ts_utc": "2026-05-17T02:00:00Z",
        "routing_mode": "llm_classifier",
        "backend_kind": "mock-haiku",
        "static_choice": "sonnet",
        "classifier_choice": classifier_choice,
        "classifier_confidence": confidence,
        "classifier_rationale": "test-rationale",
        "heuristic_choice": "sonnet",
        "heuristic_befugnis_override": None,
        "confidence_threshold": 0.8,
        "used_fallback": used_fallback,
        "effective_choice": effective_choice,
        "inputs": {
            "token_len_estimate": token_len,
            "token_len_score": 0,
            "schema_complexity_raw": 0,
            "schema_complexity_score": -1,
            "code_block_count": 0,
            "code_vs_prose_score": -1,
            "persona_role_band": "engineering",
            "persona_role_score": 0,
        },
        "router_version": "v1",
        "classifier_version": "v1",
    }
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


# ---------------------------------------------------------------------------
# 1. ParsedRoutingRow — valid RoutingEvent JSON
# ---------------------------------------------------------------------------


def test_parsed_row_from_routing_event_line():
    line = _routing_event(
        auftrag_id="T-001", effective_choice="haiku", token_len=42
    )
    row = ParsedRoutingRow.from_json_line(line)
    assert row is not None
    assert row.auftrag_id == "T-001"
    assert row.persona_id == "tomas"
    assert row.effective_choice == "haiku"
    assert row.event_kind == "routing_event"
    assert row.classifier_confidence is None
    assert row.used_fallback is None
    assert row.token_len_estimate == 42


# ---------------------------------------------------------------------------
# 2. ParsedRoutingRow — valid LlmClassifierEvent JSON
# ---------------------------------------------------------------------------


def test_parsed_row_from_classifier_event_line():
    line = _classifier_event(
        auftrag_id="T-002",
        effective_choice="opus",
        classifier_choice="opus",
        confidence=0.92,
        used_fallback=False,
        token_len=5000,
    )
    row = ParsedRoutingRow.from_json_line(line)
    assert row is not None
    assert row.event_kind == "classifier_event"
    assert row.classifier_confidence == 0.92
    assert row.used_fallback is False
    assert row.classifier_rationale == "test-rationale"
    assert row.token_len_estimate == 5000


# ---------------------------------------------------------------------------
# 3. ParsedRoutingRow — malformed JSON → None
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "not-a-json-line",
        "{unterminated",
        "[]",  # not a dict
        "null",  # not a dict
        "",  # empty
        "   ",  # whitespace only
    ],
)
def test_parsed_row_rejects_malformed_input(raw):
    assert ParsedRoutingRow.from_json_line(raw) is None


# ---------------------------------------------------------------------------
# 4. ParsedRoutingRow — missing required fields → None
# ---------------------------------------------------------------------------


def test_parsed_row_rejects_missing_required_fields():
    # Missing auftrag_id
    bad1 = json.dumps({"effective_choice": "haiku"})
    assert ParsedRoutingRow.from_json_line(bad1) is None
    # Missing effective_choice
    bad2 = json.dumps({"auftrag_id": "T-X"})
    assert ParsedRoutingRow.from_json_line(bad2) is None
    # Empty auftrag_id
    bad3 = json.dumps({"auftrag_id": "", "effective_choice": "haiku"})
    assert ParsedRoutingRow.from_json_line(bad3) is None


# ---------------------------------------------------------------------------
# 5. compare_routing_logs — identical logs → 1.0 + PASS
# ---------------------------------------------------------------------------


def test_compare_identical_logs_passes():
    lines = "\n".join(
        [
            _routing_event(auftrag_id="T-A", effective_choice="haiku"),
            _routing_event(auftrag_id="T-B", effective_choice="sonnet"),
            _routing_event(auftrag_id="T-C", effective_choice="opus"),
        ]
    )
    report = compare_routing_logs(lines, lines, threshold=0.95)
    assert report.pair_count == 3
    assert report.consistent_count == 3
    assert report.consistency_score == 1.0
    assert report.verdict == "PASS"
    assert report.total_cost_delta_units == 0.0
    assert report.baseline_distribution == {
        "haiku": 1,
        "sonnet": 1,
        "opus": 1,
    }
    assert report.candidate_distribution == report.baseline_distribution
    assert report.parse_errors == []


# ---------------------------------------------------------------------------
# 6. compare_routing_logs — drift drops score below threshold → FAIL
# ---------------------------------------------------------------------------


def test_compare_drift_below_threshold_fails():
    baseline = "\n".join(
        [
            _routing_event(auftrag_id=f"T-{i:03d}", effective_choice="sonnet")
            for i in range(10)
        ]
    )
    # Candidate flips 2 of 10 to a different tier → 0.80 consistency.
    candidate_rows = [
        _routing_event(
            auftrag_id=f"T-{i:03d}",
            effective_choice="opus" if i < 2 else "sonnet",
        )
        for i in range(10)
    ]
    candidate = "\n".join(candidate_rows)
    report = compare_routing_logs(baseline, candidate, threshold=0.95)
    assert report.pair_count == 10
    assert report.consistent_count == 8
    assert report.consistency_score == pytest.approx(0.8)
    assert report.verdict == "FAIL"
    # Per-row drift: 2 rows go sonnet→opus. cost-delta per row =
    # (60 - 12) * token_len_estimate = 48 * 100 = 4800. Two such
    # rows: 9600.
    assert report.total_cost_delta_units == pytest.approx(
        2 * (TIER_COST_UNITS["opus"] - TIER_COST_UNITS["sonnet"]) * 100
    )


# ---------------------------------------------------------------------------
# 7. compare_routing_logs — symmetric difference
# ---------------------------------------------------------------------------


def test_compare_symmetric_difference_tasks():
    baseline = "\n".join(
        [
            _routing_event(auftrag_id="T-A", effective_choice="haiku"),
            _routing_event(auftrag_id="T-B", effective_choice="sonnet"),
            _routing_event(auftrag_id="T-only-baseline", effective_choice="opus"),
        ]
    )
    candidate = "\n".join(
        [
            _routing_event(auftrag_id="T-A", effective_choice="haiku"),
            _routing_event(auftrag_id="T-B", effective_choice="sonnet"),
            _routing_event(auftrag_id="T-only-candidate", effective_choice="opus"),
        ]
    )
    report = compare_routing_logs(baseline, candidate, threshold=0.95)
    assert report.pair_count == 2
    assert report.baseline_only_tasks == ["T-only-baseline"]
    assert report.candidate_only_tasks == ["T-only-candidate"]
    assert report.consistency_score == 1.0
    assert report.verdict == "PASS"
    # Distribution covers full input (paired + side-only).
    assert report.baseline_distribution["opus"] == 1
    assert report.candidate_distribution["opus"] == 1


# ---------------------------------------------------------------------------
# 8. compare_routing_logs — cost-delta sums per-row deltas
# ---------------------------------------------------------------------------


def test_compare_cost_delta_sums_per_row():
    # Baseline: 3 sonnet @ token_len 100; candidate: 1 stays, 1 goes
    # haiku, 1 goes opus. Verify per-row delta + total.
    baseline = "\n".join(
        [
            _routing_event(auftrag_id="T-keep", effective_choice="sonnet", token_len=100),
            _routing_event(auftrag_id="T-down", effective_choice="sonnet", token_len=100),
            _routing_event(auftrag_id="T-up", effective_choice="sonnet", token_len=100),
        ]
    )
    candidate = "\n".join(
        [
            _routing_event(auftrag_id="T-keep", effective_choice="sonnet", token_len=100),
            _routing_event(auftrag_id="T-down", effective_choice="haiku", token_len=100),
            _routing_event(auftrag_id="T-up", effective_choice="opus", token_len=100),
        ]
    )
    report = compare_routing_logs(baseline, candidate, threshold=0.5)
    rows = {r.auftrag_id: r for r in report.rows}
    # Keep: sonnet→sonnet, delta 0.
    assert rows["T-keep"].cost_delta_units == 0.0
    # Down: sonnet (12) → haiku (1), delta = (1-12) * 100 = -1100.
    assert rows["T-down"].cost_delta_units == -1100.0
    # Up: sonnet (12) → opus (60), delta = (60-12) * 100 = +4800.
    assert rows["T-up"].cost_delta_units == 4800.0
    # Total delta = -1100 + 4800 = 3700.
    assert report.total_cost_delta_units == pytest.approx(3700.0)
    # Verdict: 1/3 consistent = 0.333... < 0.5 → FAIL.
    assert report.verdict == "FAIL"


# ---------------------------------------------------------------------------
# 9. compare_routing_logs — confidence histogram presence
# ---------------------------------------------------------------------------


def test_compare_confidence_histogram_presence():
    # Baseline = pure RoutingEvent (no confidence); candidate = mixed
    # with two classifier events.
    baseline = "\n".join(
        [
            _routing_event(auftrag_id="T-1", effective_choice="haiku"),
            _routing_event(auftrag_id="T-2", effective_choice="sonnet"),
        ]
    )
    candidate = "\n".join(
        [
            _classifier_event(
                auftrag_id="T-1",
                effective_choice="haiku",
                confidence=0.95,
            ),
            _classifier_event(
                auftrag_id="T-2",
                effective_choice="sonnet",
                confidence=0.55,
            ),
        ]
    )
    report = compare_routing_logs(baseline, candidate, threshold=0.95)
    assert "baseline" not in report.confidence_histogram
    assert "candidate" in report.confidence_histogram
    hist = report.confidence_histogram["candidate"]
    assert len(hist) == 10
    # 0.95 → bucket 9 (top-bucket [0.9, 1.0]).
    assert hist[9] == 1
    # 0.55 → bucket 5 ([0.5, 0.6)).
    assert hist[5] == 1
    # Other buckets empty.
    assert sum(hist) == 2


# ---------------------------------------------------------------------------
# 10. compare_routing_logs — parse_errors recorded, no raise
# ---------------------------------------------------------------------------


def test_compare_records_parse_errors_without_raising():
    baseline = "\n".join(
        [
            _routing_event(auftrag_id="T-OK", effective_choice="haiku"),
            "not-a-json-line",
            "{broken",
            "",  # empty line skipped silently
        ]
    )
    candidate = "\n".join(
        [
            _routing_event(auftrag_id="T-OK", effective_choice="haiku"),
            json.dumps({"missing": "fields"}),
        ]
    )
    # Must not raise.
    report = compare_routing_logs(baseline, candidate, threshold=0.95)
    # 2 baseline errors (not-a-json + broken; empty skipped) + 1
    # candidate error (missing required fields).
    sides = [err["side"] for err in report.parse_errors]
    assert sides.count("baseline") == 2
    assert sides.count("candidate") == 1
    # Good pair survives.
    assert report.pair_count == 1
    assert report.verdict == "PASS"


# ---------------------------------------------------------------------------
# 11. RoutingDiffReport.to_json — byte-stable
# ---------------------------------------------------------------------------


def test_report_json_is_byte_stable():
    text = "\n".join(
        [
            _routing_event(auftrag_id="T-A", effective_choice="haiku"),
            _routing_event(auftrag_id="T-B", effective_choice="sonnet"),
        ]
    )
    report = compare_routing_logs(text, text, threshold=0.95)
    s1 = report.to_json()
    s2 = report.to_json()
    assert s1 == s2
    # sorted-keys + compact separators contract.
    parsed = json.loads(s1)
    assert parsed["verdict"] == "PASS"
    # Re-serialize and compare to a deterministic re-pass.
    re_serialized = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    assert s1 == re_serialized


# ---------------------------------------------------------------------------
# 12. RoutingDiffReport.to_summary — contains verdict
# ---------------------------------------------------------------------------


def test_report_summary_contains_verdict_line():
    text = _routing_event(auftrag_id="T-A", effective_choice="haiku")
    report = compare_routing_logs(text, text, threshold=0.95)
    summary = report.to_summary()
    assert "Verdict          : PASS" in summary
    assert "Routing-Diff Report" in summary
    assert "Decision Distribution" in summary


# ---------------------------------------------------------------------------
# 13. main — exit-code contract
# ---------------------------------------------------------------------------


def test_main_returns_zero_on_pass(tmp_path, capsys):
    text = _routing_event(auftrag_id="T-A", effective_choice="haiku")
    base = tmp_path / "baseline.jsonl"
    cand = tmp_path / "candidate.jsonl"
    base.write_text(text + "\n", encoding="utf-8")
    cand.write_text(text + "\n", encoding="utf-8")
    rc = main(
        [
            "--baseline-log",
            str(base),
            "--candidate-log",
            str(cand),
            "--threshold",
            "0.95",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    # Default JSON output.
    parsed = json.loads(out.strip())
    assert parsed["verdict"] == "PASS"


def test_main_returns_one_on_fail(tmp_path, capsys):
    base_text = _routing_event(auftrag_id="T-A", effective_choice="haiku")
    cand_text = _routing_event(auftrag_id="T-A", effective_choice="opus")
    base = tmp_path / "baseline.jsonl"
    cand = tmp_path / "candidate.jsonl"
    base.write_text(base_text + "\n", encoding="utf-8")
    cand.write_text(cand_text + "\n", encoding="utf-8")
    rc = main(
        [
            "--baseline-log",
            str(base),
            "--candidate-log",
            str(cand),
            "--threshold",
            "0.95",
        ]
    )
    assert rc == 1


def test_main_returns_two_on_missing_input(tmp_path, capsys):
    rc = main(
        [
            "--baseline-log",
            str(tmp_path / "does-not-exist.jsonl"),
            "--candidate-log",
            str(tmp_path / "also-missing.jsonl"),
        ]
    )
    assert rc == 2


def test_main_summary_format(tmp_path, capsys):
    text = _routing_event(auftrag_id="T-A", effective_choice="haiku")
    base = tmp_path / "baseline.jsonl"
    cand = tmp_path / "candidate.jsonl"
    base.write_text(text + "\n", encoding="utf-8")
    cand.write_text(text + "\n", encoding="utf-8")
    rc = main(
        [
            "--baseline-log",
            str(base),
            "--candidate-log",
            str(cand),
            "--summary",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Routing-Diff Report" in out
    assert "Verdict" in out


# ---------------------------------------------------------------------------
# Defensive: default-threshold constant matches spec
# ---------------------------------------------------------------------------


def test_default_threshold_constant():
    assert DEFAULT_CONSISTENCY_THRESHOLD == 0.95
