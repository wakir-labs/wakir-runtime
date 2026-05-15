# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the Sprint-10 Tag-6 Doppelbetrieb-Score CLI.

Spec: ``wirelang/specs/bridge-forward-pipe-v1.md`` §6.
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

from wirelang.cli.doppelbetrieb_score import (
    SCORE_SCHEMA,
    build_score,
    byte_delta,
    functional_equivalence,
    main,
    spurious_divergence,
    structural_equivalence,
    verdict,
)


# ---------------------------------------------------------------------
# Per-axis unit tests
# ---------------------------------------------------------------------


def test_functional_equivalence_perfect_match():
    text = "alpha\nbeta\ngamma\n"
    assert functional_equivalence(text, text) == 1.0


def test_functional_equivalence_no_overlap():
    assert functional_equivalence("alpha\nbeta\n", "delta\nepsilon\n") == 0.0


def test_functional_equivalence_half_overlap():
    pre = "alpha\nbeta\ngamma\ndelta\n"
    wakir = "alpha\nbeta\nfoo\nbar\n"
    # 2 of 4 pre-lines match → 0.5
    assert functional_equivalence(pre, wakir) == 0.5


def test_functional_equivalence_ignores_blank_lines():
    pre = "alpha\n\n\nbeta\n"
    wakir = "alpha\nbeta\n"
    assert functional_equivalence(pre, wakir) == 1.0


def test_byte_delta_symmetric():
    assert byte_delta("abc", "abcdef") == 3
    assert byte_delta("abcdef", "abc") == 3


def test_byte_delta_zero_for_identity():
    assert byte_delta("hello", "hello") == 0


def test_structural_equivalence_zero_blocks_match():
    assert structural_equivalence("plain text", "more plain text") == 1.0


def test_structural_equivalence_block_count_match():
    pre = "intro\n```\ncode1\n```\nmid\n```\ncode2\n```\n"
    wakir = "```\nA\n```\n```\nB\n```\n"
    # Both have 2 fenced blocks (4 fences each) → 1.0
    assert structural_equivalence(pre, wakir) == 1.0


def test_structural_equivalence_mismatched_blocks():
    pre = "```\nA\n```\n"  # 1 block
    wakir = "```\nA\n```\n```\nB\n```\n"  # 2 blocks
    # min/max = 1/2 = 0.5
    assert structural_equivalence(pre, wakir) == 0.5


def test_spurious_divergence_counts_only_wakir_unique_lines():
    pre = "a\nb\nc\n"
    wakir = "a\nb\nc\nx\ny\n"
    assert spurious_divergence(pre, wakir) == 2


def test_spurious_divergence_zero_when_wakir_subset():
    pre = "a\nb\nc\n"
    wakir = "a\nb\n"
    assert spurious_divergence(pre, wakir) == 0


# ---------------------------------------------------------------------
# Verdict mapping
# ---------------------------------------------------------------------


def test_verdict_pass_path():
    assert verdict(0.97, 100) == "pass"
    assert verdict(0.95, 1023) == "pass"


def test_verdict_pass_with_drift_path():
    assert verdict(0.85, 2000) == "pass-with-drift"
    # fe=0.95 but byte_delta>=1024 → falls through to pass-with-drift
    assert verdict(0.95, 1024) == "pass-with-drift"


def test_verdict_fail_path():
    assert verdict(0.5, 100) == "fail"
    assert verdict(0.79, 0) == "fail"


# ---------------------------------------------------------------------
# build_score envelope shape
# ---------------------------------------------------------------------


def test_build_score_envelope_shape():
    pre = "alpha\nbeta\n"
    wakir = "alpha\nbeta\n"
    score = build_score(
        "sprint-10-tag-6",
        pre,
        wakir,
        ts_utc="2026-05-15T18:00:00Z",
    )
    assert score["schema"] == SCORE_SCHEMA
    assert score["auftrag_id"] == "sprint-10-tag-6"
    assert score["ts_utc"] == "2026-05-15T18:00:00Z"
    assert "preframework" in score
    assert "wakir_runtime" in score
    assert set(score["axes"].keys()) == {
        "functional_equivalence",
        "byte_delta",
        "structural_equivalence",
        "spurious_divergence",
    }
    assert score["verdict"] == "pass"


def test_build_score_deterministic_across_repeats():
    pre = "alpha\nbeta\n"
    wakir = "alpha\nbeta\ngamma\n"
    a = build_score("x", pre, wakir, ts_utc="2026-05-15T18:00:00Z")
    b = build_score("x", pre, wakir, ts_utc="2026-05-15T18:00:00Z")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


def _run_cli(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(argv)
    return rc, buf.getvalue()


def test_cli_pass_path_exit_0(tmp_path: Path):
    pre = tmp_path / "pre.txt"
    wakir = tmp_path / "wakir.txt"
    pre.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    wakir.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    rc, out = _run_cli([
        "--auftrag-id", "x",
        "--preframework", str(pre),
        "--wakir", str(wakir),
        "--ts-utc", "2026-05-15T18:00:00Z",
    ])
    assert rc == 0, out
    score = json.loads(out)
    assert score["verdict"] == "pass"


def test_cli_fail_path_exit_2(tmp_path: Path):
    pre = tmp_path / "pre.txt"
    wakir = tmp_path / "wakir.txt"
    pre.write_text("alpha\nbeta\ngamma\ndelta\n", encoding="utf-8")
    wakir.write_text("totally\ndifferent\noutput\n", encoding="utf-8")
    rc, out = _run_cli([
        "--auftrag-id", "x",
        "--preframework", str(pre),
        "--wakir", str(wakir),
        "--ts-utc", "2026-05-15T18:00:00Z",
    ])
    assert rc == 2, out
    score = json.loads(out)
    assert score["verdict"] == "fail"


def test_cli_pass_with_drift_exit_1(tmp_path: Path):
    pre_lines = [f"line-{i}" for i in range(100)]
    wakir_lines = pre_lines[:85] + [f"divergent-{i}" for i in range(20)]
    pre = tmp_path / "pre.txt"
    wakir = tmp_path / "wakir.txt"
    pre.write_text("\n".join(pre_lines) + "\n", encoding="utf-8")
    wakir.write_text("\n".join(wakir_lines) + "\n", encoding="utf-8")
    rc, out = _run_cli([
        "--auftrag-id", "x",
        "--preframework", str(pre),
        "--wakir", str(wakir),
        "--ts-utc", "2026-05-15T18:00:00Z",
    ])
    assert rc == 1, out
    score = json.loads(out)
    assert score["verdict"] == "pass-with-drift"


def test_cli_out_path_writes_to_disk(tmp_path: Path):
    pre = tmp_path / "pre.txt"
    wakir = tmp_path / "wakir.txt"
    pre.write_text("alpha\n", encoding="utf-8")
    wakir.write_text("alpha\n", encoding="utf-8")
    out_path = tmp_path / "score.json"
    rc, _ = _run_cli([
        "--auftrag-id", "x",
        "--preframework", str(pre),
        "--wakir", str(wakir),
        "--ts-utc", "2026-05-15T18:00:00Z",
        "--out", str(out_path),
    ])
    assert rc == 0
    assert out_path.exists()
    score = json.loads(out_path.read_text(encoding="utf-8"))
    assert score["schema"] == SCORE_SCHEMA
