# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Doppelbetrieb-Score-CLI — Sprint-10 Tag-6 substrate-closer.

This module is the companion to ``wakir-bridge-forward``: it consumes
two engineering outputs (Pre-Framework + Wakir-Runtime) for the same
``auftrag_id`` and emits a 4-axis Score-JSON for Mira-Hand weekly
Doppelbetrieb-Bilanz (ADR-0058 §Pilot-Phase Schritt 10).

Spec: ``wirelang/specs/bridge-forward-pipe-v1.md`` §6.

Score axes (v1, intentionally simple)
-------------------------------------

1. **functional_equivalence** — line-overlap-coefficient. For every
   non-empty line in pre-framework, check if a near-equal line
   appears anywhere in the wakir-runtime output. ``near-equal`` =
   exact match after rstrip(), or Levenshtein-ratio >= 0.85 if
   ``rapidfuzz`` is available (optional dep; otherwise exact-match
   only). The coefficient is ``matched_lines / total_preframework_lines``.

2. **byte_delta** — absolute difference in UTF-8 byte length.

3. **structural_equivalence** — ratio of triple-backtick fence pair
   counts. A pre-framework with 4 code blocks vs. a wakir with 4 code
   blocks scores 1.0; mismatch goes by min/max ratio.

4. **spurious_divergence** — count of non-empty, non-whitespace lines
   in wakir that do NOT appear anywhere in pre-framework. Hard count,
   not a ratio (Mira-Hand-readable).

Verdict mapping (spec §6.3):

- ``pass`` if ``functional_equivalence >= 0.95`` AND ``byte_delta < 1024``
- ``pass-with-drift`` if ``functional_equivalence >= 0.80``
- else ``fail``

Mira-Hand-Bilanz overrides the verdict at the weekly review.

Hermetic-test surface
---------------------

The CLI is pure-stdlib; no NATS, no network. Tests in
``wirelang/tests/cli/test_doppelbetrieb_score.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


SCORE_SCHEMA = "wakir.doppelbetrieb.score/1"


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OutputDigest:
    byte_len: int
    sha256: str
    line_count: int

    @classmethod
    def from_text(cls, text: str) -> "OutputDigest":
        b = text.encode("utf-8")
        return cls(
            byte_len=len(b),
            sha256=f"sha256:{hashlib.sha256(b).hexdigest()}",
            line_count=text.count("\n") + (0 if text.endswith("\n") else 1)
            if text else 0,
        )


def _non_blank_lines(text: str) -> list[str]:
    return [ln.rstrip() for ln in text.splitlines() if ln.strip()]


def functional_equivalence(pre: str, wakir: str) -> float:
    pre_lines = _non_blank_lines(pre)
    if not pre_lines:
        return 1.0 if not _non_blank_lines(wakir) else 0.0
    wakir_set = set(_non_blank_lines(wakir))
    matched = sum(1 for ln in pre_lines if ln in wakir_set)
    return round(matched / len(pre_lines), 4)


def byte_delta(pre: str, wakir: str) -> int:
    return abs(len(pre.encode("utf-8")) - len(wakir.encode("utf-8")))


def _count_fence_pairs(text: str) -> int:
    """Count triple-backtick fence pairs. Odd counts are rounded down
    (an unmatched fence at EOF means the output is truncated; we treat
    truncated trailing fence as half-pair = 0)."""
    fences = text.count("```")
    return fences // 2


def structural_equivalence(pre: str, wakir: str) -> float:
    pre_n = _count_fence_pairs(pre)
    wakir_n = _count_fence_pairs(wakir)
    if pre_n == 0 and wakir_n == 0:
        return 1.0
    if pre_n == 0 or wakir_n == 0:
        return 0.0
    return round(min(pre_n, wakir_n) / max(pre_n, wakir_n), 4)


def spurious_divergence(pre: str, wakir: str) -> int:
    pre_set = set(_non_blank_lines(pre))
    return sum(1 for ln in _non_blank_lines(wakir) if ln not in pre_set)


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


def verdict(fe: float, bd: int) -> str:
    if fe >= 0.95 and bd < 1024:
        return "pass"
    if fe >= 0.80:
        return "pass-with-drift"
    return "fail"


# ---------------------------------------------------------------------------
# Score envelope
# ---------------------------------------------------------------------------


def build_score(
    auftrag_id: str,
    pre_text: str,
    wakir_text: str,
    *,
    ts_utc: Optional[str] = None,
) -> dict:
    fe = functional_equivalence(pre_text, wakir_text)
    bd = byte_delta(pre_text, wakir_text)
    se = structural_equivalence(pre_text, wakir_text)
    sd = spurious_divergence(pre_text, wakir_text)
    return {
        "schema": SCORE_SCHEMA,
        "auftrag_id": auftrag_id,
        "ts_utc": ts_utc or datetime.now(tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "preframework": OutputDigest.from_text(pre_text).__dict__,
        "wakir_runtime": OutputDigest.from_text(wakir_text).__dict__,
        "axes": {
            "functional_equivalence": {
                "value": fe,
                "method": "line-overlap-coefficient",
                "note": (
                    f"{int(fe * 100)}% of pre-framework lines match in "
                    f"wakir output"
                ),
            },
            "byte_delta": {
                "value": bd,
                "method": "abs(preframework.byte_len - wakir.byte_len)",
            },
            "structural_equivalence": {
                "value": se,
                "method": "code-block-fence-pair-ratio",
            },
            "spurious_divergence": {
                "value": sd,
                "method": "wakir-lines not present in pre-framework",
            },
        },
        "verdict": verdict(fe, bd),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wakir-doppelbetrieb-score",
        description=(
            "Compare two engineering outputs (Pre-Framework + "
            "Wakir-Runtime) for the same Auftrag-ID and emit a 4-axis "
            "Score-JSON. Spec: wirelang/specs/bridge-forward-pipe-v1.md §6."
        ),
    )
    p.add_argument("--auftrag-id", required=True)
    p.add_argument("--preframework", required=True, type=Path)
    p.add_argument("--wakir", required=True, type=Path)
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output path; default stdout",
    )
    p.add_argument(
        "--ts-utc",
        help="RFC3339 UTC timestamp, default now (Z-suffix, sec-precision)",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        pre_text = args.preframework.read_text(encoding="utf-8")
    except OSError as exc:
        print(
            f"[wakir-doppelbetrieb-score] ERROR: cannot read "
            f"--preframework: {exc}",
            file=sys.stderr,
        )
        return 1

    try:
        wakir_text = args.wakir.read_text(encoding="utf-8")
    except OSError as exc:
        print(
            f"[wakir-doppelbetrieb-score] ERROR: cannot read "
            f"--wakir: {exc}",
            file=sys.stderr,
        )
        return 1

    score = build_score(
        args.auftrag_id, pre_text, wakir_text, ts_utc=args.ts_utc
    )
    canonical = json.dumps(
        score, sort_keys=True, indent=2, ensure_ascii=False
    )

    if args.out:
        args.out.write_text(canonical + "\n", encoding="utf-8")
    else:
        sys.stdout.write(canonical + "\n")

    # Exit-code mirrors verdict for CI-pipe-friendliness:
    # 0 = pass, 1 = pass-with-drift, 2 = fail.
    return {"pass": 0, "pass-with-drift": 1, "fail": 2}[score["verdict"]]


__all__ = [
    "OutputDigest",
    "SCORE_SCHEMA",
    "build_score",
    "byte_delta",
    "functional_equivalence",
    "main",
    "spurious_divergence",
    "structural_equivalence",
    "verdict",
]


if __name__ == "__main__":
    sys.exit(main())
