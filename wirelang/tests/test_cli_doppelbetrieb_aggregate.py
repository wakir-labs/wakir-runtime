# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for wakir-doppelbetrieb-aggregate (Sprint-Pengine-10 OI-PEFR-9).

Tests cover:
- Empty input shape.
- Single-score aggregation.
- Multi-score aggregation with mixed verdicts.
- Malformed score rejection.
- Output schema correctness.
- Verdict-driven exit codes.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import pytest

from wirelang.cli.doppelbetrieb_aggregate import (
    AGGREGATE_SCHEMA,
    AggregateInputError,
    aggregate,
    main,
)


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


def _write_score(
    path: Path,
    *,
    auftrag_id: str,
    verdict: str = "pass",
    fe: float = 0.98,
    bd: int = 10,
    se: float = 1.0,
    sd: int = 0,
    pre_byte: int = 500,
    pre_line: int = 20,
    wakir_byte: int = 510,
    wakir_line: int = 20,
) -> Path:
    obj = {
        "schema": "wakir.doppelbetrieb.score/1",
        "auftrag_id": auftrag_id,
        "ts_utc": "2026-05-15T22:00:00Z",
        "preframework": {
            "byte_len": pre_byte,
            "sha256": "sha256:" + "0" * 64,
            "line_count": pre_line,
        },
        "wakir_runtime": {
            "byte_len": wakir_byte,
            "sha256": "sha256:" + "1" * 64,
            "line_count": wakir_line,
        },
        "axes": {
            "functional_equivalence": {"value": fe, "method": "x", "note": ""},
            "byte_delta": {"value": bd, "method": "x"},
            "structural_equivalence": {"value": se, "method": "x"},
            "spurious_divergence": {"value": sd, "method": "x"},
        },
        "verdict": verdict,
    }
    path.write_text(json.dumps(obj, sort_keys=True, indent=2))
    return path


# ---------------------------------------------------------------------
# aggregate() core
# ---------------------------------------------------------------------


def test_aggregate_empty_input():
    res = aggregate([], ts_utc="2026-05-15T22:00:00Z")
    assert res.bilanz["schema"] == AGGREGATE_SCHEMA
    assert res.bilanz["input_count"] == 0
    assert res.bilanz["verdicts"] == {"pass": 0, "pass-with-drift": 0, "fail": 0}
    assert res.has_any_fail is False


def test_aggregate_single_pass(tmp_path: Path):
    p = _write_score(tmp_path / "s1.json", auftrag_id="a-1")
    res = aggregate([p], ts_utc="2026-05-15T22:00:00Z")
    assert res.bilanz["input_count"] == 1
    assert res.bilanz["verdicts"]["pass"] == 1
    assert res.bilanz["verdicts"]["fail"] == 0
    assert res.has_any_fail is False


def test_aggregate_single_fail(tmp_path: Path):
    p = _write_score(tmp_path / "s.json", auftrag_id="a", verdict="fail", fe=0.5)
    res = aggregate([p])
    assert res.bilanz["verdicts"]["fail"] == 1
    assert res.has_any_fail is True


def test_aggregate_mixed_verdicts(tmp_path: Path):
    paths = [
        _write_score(tmp_path / "p1.json", auftrag_id="p1", verdict="pass"),
        _write_score(tmp_path / "p2.json", auftrag_id="p2", verdict="pass"),
        _write_score(
            tmp_path / "p3.json", auftrag_id="p3",
            verdict="pass-with-drift", fe=0.85,
        ),
        _write_score(
            tmp_path / "p4.json", auftrag_id="p4", verdict="fail", fe=0.5,
        ),
    ]
    res = aggregate(paths)
    assert res.bilanz["verdicts"] == {
        "pass": 2, "pass-with-drift": 1, "fail": 1,
    }


def test_aggregate_byte_sums_correct(tmp_path: Path):
    paths = [
        _write_score(tmp_path / "p1.json", auftrag_id="p1", pre_byte=100, wakir_byte=110),
        _write_score(tmp_path / "p2.json", auftrag_id="p2", pre_byte=200, wakir_byte=180),
    ]
    res = aggregate(paths)
    assert res.bilanz["preframework_total"]["byte_len_sum"] == 300
    assert res.bilanz["wakir_runtime_total"]["byte_len_sum"] == 290


def test_aggregate_line_sums_correct(tmp_path: Path):
    paths = [
        _write_score(tmp_path / "p1.json", auftrag_id="p1", pre_line=10, wakir_line=12),
        _write_score(tmp_path / "p2.json", auftrag_id="p2", pre_line=20, wakir_line=18),
    ]
    res = aggregate(paths)
    assert res.bilanz["preframework_total"]["line_count_sum"] == 30
    assert res.bilanz["wakir_runtime_total"]["line_count_sum"] == 30


def test_aggregate_byte_delta_stats(tmp_path: Path):
    paths = [
        _write_score(tmp_path / "p1.json", auftrag_id="p1", bd=10),
        _write_score(tmp_path / "p2.json", auftrag_id="p2", bd=50),
        _write_score(tmp_path / "p3.json", auftrag_id="p3", bd=20),
    ]
    res = aggregate(paths)
    assert res.bilanz["delta_stats"]["byte_len_delta_sum"] == 80
    assert res.bilanz["delta_stats"]["byte_len_delta_max"] == 50
    assert res.bilanz["delta_stats"]["byte_len_delta_min"] == 10
    assert abs(res.bilanz["delta_stats"]["byte_len_delta_mean"] - (80/3)) < 0.01


def test_aggregate_axes_mean(tmp_path: Path):
    paths = [
        _write_score(tmp_path / "p1.json", auftrag_id="p1", fe=1.0),
        _write_score(tmp_path / "p2.json", auftrag_id="p2", fe=0.8),
    ]
    res = aggregate(paths)
    assert abs(res.bilanz["axes"]["functional_equivalence_mean"] - 0.9) < 0.001


def test_aggregate_fe_min(tmp_path: Path):
    paths = [
        _write_score(tmp_path / "p1.json", auftrag_id="p1", fe=1.0),
        _write_score(tmp_path / "p2.json", auftrag_id="p2", fe=0.82),
        _write_score(tmp_path / "p3.json", auftrag_id="p3", fe=0.95),
    ]
    res = aggregate(paths)
    assert res.bilanz["axes"]["functional_equivalence_min"] == 0.82


def test_aggregate_spurious_divergence_sum(tmp_path: Path):
    paths = [
        _write_score(tmp_path / "p1.json", auftrag_id="p1", sd=2),
        _write_score(tmp_path / "p2.json", auftrag_id="p2", sd=5),
    ]
    res = aggregate(paths)
    assert res.bilanz["axes"]["spurious_divergence_sum"] == 7


def test_aggregate_auftrag_ids_collected(tmp_path: Path):
    paths = [
        _write_score(tmp_path / "p1.json", auftrag_id="a-1"),
        _write_score(tmp_path / "p2.json", auftrag_id="a-2"),
    ]
    res = aggregate(paths)
    assert "a-1" in res.bilanz["auftrag_ids"]
    assert "a-2" in res.bilanz["auftrag_ids"]


def test_aggregate_rejects_wrong_schema(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "wakir.other/1"}))
    with pytest.raises(AggregateInputError):
        aggregate([bad])


def test_aggregate_rejects_non_json(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    with pytest.raises(AggregateInputError):
        aggregate([bad])


def test_aggregate_rejects_missing_file(tmp_path: Path):
    with pytest.raises(AggregateInputError):
        aggregate([tmp_path / "nonexistent.json"])


def test_aggregate_rejects_unknown_verdict(tmp_path: Path):
    p = tmp_path / "s.json"
    obj = {
        "schema": "wakir.doppelbetrieb.score/1",
        "auftrag_id": "a", "ts_utc": "x",
        "preframework": {"byte_len": 0, "sha256": "x", "line_count": 0},
        "wakir_runtime": {"byte_len": 0, "sha256": "x", "line_count": 0},
        "axes": {
            "functional_equivalence": {"value": 0.9, "method": "x"},
            "byte_delta": {"value": 0, "method": "x"},
            "structural_equivalence": {"value": 1.0, "method": "x"},
            "spurious_divergence": {"value": 0, "method": "x"},
        },
        "verdict": "maybe",
    }
    p.write_text(json.dumps(obj))
    with pytest.raises(AggregateInputError):
        aggregate([p])


# ---------------------------------------------------------------------
# CLI main()
# ---------------------------------------------------------------------


def test_main_writes_to_stdout(tmp_path: Path):
    s1 = _write_score(tmp_path / "s1.json", auftrag_id="a-1")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--scores", str(s1)])
    assert rc == 0
    obj = json.loads(buf.getvalue())
    assert obj["input_count"] == 1


def test_main_writes_to_out_file(tmp_path: Path):
    s1 = _write_score(tmp_path / "s1.json", auftrag_id="a-1")
    out = tmp_path / "bilanz.json"
    rc = main(["--scores", str(s1), "--out", str(out)])
    assert rc == 0
    obj = json.loads(out.read_text())
    assert obj["input_count"] == 1


def test_main_scores_dir(tmp_path: Path):
    d = tmp_path / "scores"
    d.mkdir()
    _write_score(d / "p1.json", auftrag_id="a-1")
    _write_score(d / "p2.json", auftrag_id="a-2")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--scores-dir", str(d)])
    assert rc == 0
    obj = json.loads(buf.getvalue())
    assert obj["input_count"] == 2


def test_main_exit_one_on_any_fail(tmp_path: Path):
    p = _write_score(tmp_path / "s.json", auftrag_id="a", verdict="fail", fe=0.5)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--scores", str(p)])
    assert rc == 1


def test_main_exit_zero_on_all_pass(tmp_path: Path):
    p = _write_score(tmp_path / "s.json", auftrag_id="a", verdict="pass")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--scores", str(p)])
    assert rc == 0


def test_main_missing_input_returns_two():
    err = io.StringIO()
    with redirect_stderr(err):
        rc = main([])
    assert rc == 2


def test_main_bad_score_file_returns_two(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    err = io.StringIO()
    with redirect_stderr(err):
        rc = main(["--scores", str(bad)])
    assert rc == 2


def test_main_scores_dir_and_scores_combine(tmp_path: Path):
    d = tmp_path / "scores"
    d.mkdir()
    _write_score(d / "p1.json", auftrag_id="dir-1")
    extra = _write_score(tmp_path / "extra.json", auftrag_id="extra-1")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--scores-dir", str(d), "--scores", str(extra)])
    assert rc == 0
    obj = json.loads(buf.getvalue())
    assert obj["input_count"] == 2
    assert "dir-1" in obj["auftrag_ids"]
    assert "extra-1" in obj["auftrag_ids"]


def test_main_ts_utc_override(tmp_path: Path):
    p = _write_score(tmp_path / "s.json", auftrag_id="a")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--scores", str(p), "--ts-utc", "2026-12-31T23:59:59Z"])
    assert rc == 0
    obj = json.loads(buf.getvalue())
    assert obj["ts_utc"] == "2026-12-31T23:59:59Z"


def test_main_empty_dir_returns_zero(tmp_path: Path):
    """Empty scores-dir should be a clean zero (no fail verdicts)."""
    d = tmp_path / "scores"
    d.mkdir()
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--scores-dir", str(d)])
    assert rc == 0
    obj = json.loads(buf.getvalue())
    assert obj["input_count"] == 0


def test_main_help_works():
    try:
        main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
