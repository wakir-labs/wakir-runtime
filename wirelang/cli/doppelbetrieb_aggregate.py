# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Doppelbetrieb-Aggregate-CLI — Sprint-Pengine-10 OI-PEFR-9.

Sprint-10 Tag-6 shipped :mod:`wirelang.cli.doppelbetrieb_score` which
emits a per-Auftrag 4-axis score JSON. Sprint-Pengine-10 adds this
aggregator: it consumes a directory of per-Auftrag score-JSONs and
emits a **weekly Bilanz** with per-axis sums + deltas for the
Mira-Hand-Bilanz weekly review (ADR-0058 §Pilot-Phase Schritt 10).

Input shape
-----------

The aggregator accepts:

- ``--scores-dir <path>`` — directory of per-Auftrag score JSONs
  (each conforming to schema ``wakir.doppelbetrieb.score/1``).
- ``--scores <path1> <path2> ...`` — explicit list of score-JSON paths.

Output shape
------------

::

    {
      "schema": "wakir.doppelbetrieb.aggregate/1",
      "ts_utc": "...",
      "input_count": 12,
      "verdicts": {
        "pass": 9,
        "pass-with-drift": 2,
        "fail": 1
      },
      "preframework_total": {
        "byte_len_sum": 65432,
        "line_count_sum": 1820
      },
      "wakir_runtime_total": {
        "byte_len_sum": 65120,
        "line_count_sum": 1812
      },
      "delta_stats": {
        "byte_len_delta_sum": 312,
        "byte_len_delta_mean": 26.0,
        "byte_len_delta_max": 95,
        "byte_len_delta_min": 0,
        "line_count_delta_sum": 8
      },
      "axes": {
        "functional_equivalence_mean": 0.94,
        "functional_equivalence_min": 0.82,
        "byte_delta_sum": 312,
        "structural_equivalence_mean": 0.99,
        "spurious_divergence_sum": 17
      },
      "auftrag_ids": ["...", ...]
    }

The aggregator is **pure-stdlib**; no NATS, no network. Verdict-mapping
mirrors the per-Auftrag score-CLI for consistency.

Hermetic-test surface
---------------------

Tests in ``wirelang/tests/test_cli_doppelbetrieb_aggregate.py`` cover:

- Empty input → empty Bilanz (input_count=0).
- Single score → counts match the input.
- Mixed verdicts → tallied correctly.
- Malformed score → InputError raised, CLI exit 1.

Exit codes
----------

- 0 — Bilanz written; no fail verdicts in input.
- 1 — Bilanz written; at least one fail verdict in input.
- 2 — Input error (missing files, malformed schema, no scores).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional


AGGREGATE_SCHEMA = "wakir.doppelbetrieb.aggregate/1"

EXPECTED_PER_SCORE_SCHEMA = "wakir.doppelbetrieb.score/1"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AggregateInputError(ValueError):
    """A score-JSON failed shape or schema validation."""


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _load_score(path: Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AggregateInputError(
            f"cannot read score-file {path}: {exc}"
        ) from exc
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AggregateInputError(
            f"score-file {path} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(obj, dict):
        raise AggregateInputError(
            f"score-file {path} root is not an object"
        )
    schema = obj.get("schema")
    if schema != EXPECTED_PER_SCORE_SCHEMA:
        raise AggregateInputError(
            f"score-file {path} has unexpected schema "
            f"{schema!r}; want {EXPECTED_PER_SCORE_SCHEMA!r}"
        )
    return obj


def _collect_score_paths(
    scores_dir: Optional[Path],
    scores: Optional[list[Path]],
) -> list[Path]:
    out: list[Path] = []
    if scores_dir is not None:
        if not scores_dir.is_dir():
            raise AggregateInputError(
                f"--scores-dir is not a directory: {scores_dir}"
            )
        out.extend(sorted(scores_dir.glob("*.json")))
    if scores:
        out.extend(scores)
    return out


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _safe_div(num: float, den: float) -> float:
    if den == 0:
        return 0.0
    return num / den


@dataclass
class AggregateResult:
    bilanz: dict
    has_any_fail: bool


def aggregate(score_paths: Iterable[Path], *, ts_utc: Optional[str] = None) -> AggregateResult:
    paths = list(score_paths)
    bilanz_ts = ts_utc or datetime.now(tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    if not paths:
        return AggregateResult(
            bilanz={
                "schema": AGGREGATE_SCHEMA,
                "ts_utc": bilanz_ts,
                "input_count": 0,
                "verdicts": {"pass": 0, "pass-with-drift": 0, "fail": 0},
                "preframework_total": {"byte_len_sum": 0, "line_count_sum": 0},
                "wakir_runtime_total": {"byte_len_sum": 0, "line_count_sum": 0},
                "delta_stats": {
                    "byte_len_delta_sum": 0,
                    "byte_len_delta_mean": 0.0,
                    "byte_len_delta_max": 0,
                    "byte_len_delta_min": 0,
                    "line_count_delta_sum": 0,
                },
                "axes": {
                    "functional_equivalence_mean": 0.0,
                    "functional_equivalence_min": 0.0,
                    "byte_delta_sum": 0,
                    "structural_equivalence_mean": 0.0,
                    "spurious_divergence_sum": 0,
                },
                "auftrag_ids": [],
            },
            has_any_fail=False,
        )

    verdicts = {"pass": 0, "pass-with-drift": 0, "fail": 0}
    pre_byte_sum = 0
    pre_line_sum = 0
    wakir_byte_sum = 0
    wakir_line_sum = 0
    fe_values: list[float] = []
    bd_values: list[int] = []
    se_values: list[float] = []
    sd_values: list[int] = []
    line_count_deltas: list[int] = []
    auftrag_ids: list[str] = []

    for path in paths:
        obj = _load_score(path)
        try:
            verdict = obj["verdict"]
            preframework = obj["preframework"]
            wakir_runtime = obj["wakir_runtime"]
            axes = obj["axes"]
            auftrag_id = obj["auftrag_id"]
        except KeyError as exc:
            raise AggregateInputError(
                f"score-file {path} missing required key: {exc}"
            ) from exc
        if verdict not in verdicts:
            raise AggregateInputError(
                f"score-file {path} has unknown verdict {verdict!r}"
            )
        verdicts[verdict] += 1
        pre_byte_sum += int(preframework.get("byte_len", 0))
        pre_line_sum += int(preframework.get("line_count", 0))
        wakir_byte_sum += int(wakir_runtime.get("byte_len", 0))
        wakir_line_sum += int(wakir_runtime.get("line_count", 0))
        line_count_deltas.append(
            int(preframework.get("line_count", 0))
            - int(wakir_runtime.get("line_count", 0))
        )
        fe_values.append(float(axes["functional_equivalence"]["value"]))
        bd_values.append(int(axes["byte_delta"]["value"]))
        se_values.append(float(axes["structural_equivalence"]["value"]))
        sd_values.append(int(axes["spurious_divergence"]["value"]))
        auftrag_ids.append(str(auftrag_id))

    bd_sum = sum(bd_values)
    bilanz = {
        "schema": AGGREGATE_SCHEMA,
        "ts_utc": bilanz_ts,
        "input_count": len(paths),
        "verdicts": verdicts,
        "preframework_total": {
            "byte_len_sum": pre_byte_sum,
            "line_count_sum": pre_line_sum,
        },
        "wakir_runtime_total": {
            "byte_len_sum": wakir_byte_sum,
            "line_count_sum": wakir_line_sum,
        },
        "delta_stats": {
            "byte_len_delta_sum": bd_sum,
            "byte_len_delta_mean": round(_safe_div(bd_sum, len(bd_values)), 4),
            "byte_len_delta_max": max(bd_values),
            "byte_len_delta_min": min(bd_values),
            "line_count_delta_sum": sum(line_count_deltas),
        },
        "axes": {
            "functional_equivalence_mean": round(
                _safe_div(sum(fe_values), len(fe_values)), 4,
            ),
            "functional_equivalence_min": round(min(fe_values), 4),
            "byte_delta_sum": bd_sum,
            "structural_equivalence_mean": round(
                _safe_div(sum(se_values), len(se_values)), 4,
            ),
            "spurious_divergence_sum": sum(sd_values),
        },
        "auftrag_ids": auftrag_ids,
    }
    return AggregateResult(
        bilanz=bilanz,
        has_any_fail=verdicts["fail"] > 0,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wakir-doppelbetrieb-aggregate",
        description=(
            "Aggregate per-Auftrag Doppelbetrieb-Score JSONs into a "
            "weekly Bilanz for Mira-Hand review. Spec: ADR-0058 "
            "§Pilot-Phase Schritt 10."
        ),
    )
    p.add_argument(
        "--scores-dir",
        type=Path,
        default=None,
        help="directory of per-Auftrag score JSONs (glob: *.json).",
    )
    p.add_argument(
        "--scores",
        nargs="+",
        type=Path,
        default=None,
        help="explicit list of score-JSON paths (combinable with --scores-dir).",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output path; default stdout.",
    )
    p.add_argument(
        "--ts-utc",
        help="RFC3339 UTC timestamp, default now (Z-suffix, sec-precision).",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.scores_dir is None and not args.scores:
        print(
            "[wakir-doppelbetrieb-aggregate] ERROR: supply --scores-dir "
            "and/or --scores",
            file=sys.stderr,
        )
        return 2

    try:
        paths = _collect_score_paths(args.scores_dir, args.scores)
        result = aggregate(paths, ts_utc=args.ts_utc)
    except AggregateInputError as exc:
        print(
            f"[wakir-doppelbetrieb-aggregate] ERROR: {exc}",
            file=sys.stderr,
        )
        return 2

    canonical = json.dumps(
        result.bilanz, sort_keys=True, indent=2, ensure_ascii=False,
    )
    if args.out:
        args.out.write_text(canonical + "\n", encoding="utf-8")
    else:
        sys.stdout.write(canonical + "\n")

    return 1 if result.has_any_fail else 0


__all__ = [
    "AGGREGATE_SCHEMA",
    "AggregateInputError",
    "AggregateResult",
    "aggregate",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())
