#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Tag-59 ADR-Errata-Footer-Verifier CI-Pin
========================================

Cross-site audit regression gate. Consumes the
``audit_adr_errata_spec_drift.run_audit`` envelope and compares its
*stable* fields against a baseline snapshot committed in this
repository at ``tooling/audit/adr-errata-audit-baseline.json``.

Stability discipline
--------------------
The raw envelope contains ``adr_heads[].path`` and ``spec_path``
that may be absolute on the CI runner and relative in the
baseline. Path fields are *not* compared by value — only their
basenames (or canonical-form suffixes for the spec). All other
fields are compared by deep structural equality.

Verdict contract
----------------
The verifier emits one of three verdicts:

  * ``AUDIT-PIN-INTACT``     — observed envelope matches baseline
                                on every stable field. Exit 0.
  * ``AUDIT-PIN-DRIFT``      — at least one stable field diverges.
                                Exit 1. Diff printed to stderr.
  * ``AUDIT-PIN-SKIP``       — the AI-Corp decisions directory is
                                not available on the runner (e.g.
                                fork PR without the sibling clone).
                                Exit 0 with explicit skip line.

The skip path is the Tag-59 escape hatch: we do not want a
red gate on forks that legitimately cannot reach AI-Corp/decisions.
The skip line is grep-able for the operator (and for the
Tag-60+ follow-up that may decide to require the AI-Corp clone
on the runner unconditionally).

Pure stdlib. No JSON-schema validator, no network.

Tag-59, Amara-Hand, continuous-mode.
"""

from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import sys
from typing import Any


PIN_VERDICT_INTACT = "AUDIT-PIN-INTACT"
PIN_VERDICT_DRIFT = "AUDIT-PIN-DRIFT"
PIN_VERDICT_SKIP = "AUDIT-PIN-SKIP"


@dataclasses.dataclass(frozen=True)
class PinResult:
    verdict: str
    diffs: tuple[str, ...]
    decisions_dir: str
    spec_path: str
    baseline_path: str
    skip_reason: str | None = None

    def to_lines(self) -> tuple[str, ...]:
        lines = [
            f"adr-errata-audit-pin verdict: {self.verdict}",
            f"  decisions_dir: {self.decisions_dir}",
            f"  spec_path:     {self.spec_path}",
            f"  baseline:      {self.baseline_path}",
        ]
        if self.skip_reason is not None:
            lines.append(f"  skip_reason:   {self.skip_reason}")
        for d in self.diffs:
            lines.append(f"  drift: {d}")
        return tuple(lines)


def _normalise_adr_path(p: str) -> str:
    return pathlib.Path(p).name


def _normalise_spec_path(p: str) -> str:
    # Keep the last two segments (e.g. "specs/wirelang-spec-v0-4-3.md")
    # for stability across absolute/relative runner roots.
    parts = pathlib.Path(p).parts
    if len(parts) >= 2:
        return "/".join(parts[-2:])
    return parts[-1] if parts else p


def _normalise_envelope(env: dict[str, Any]) -> dict[str, Any]:
    """
    Return a deep-copy of ``env`` with path fields normalised so the
    baseline (relative paths) can be compared to a live runner
    envelope (absolute paths) by structural equality.
    """
    out = json.loads(json.dumps(env))  # cheap deep copy
    out["spec_path"] = _normalise_spec_path(out.get("spec_path", ""))
    for head in out.get("adr_heads", []):
        head["path"] = _normalise_adr_path(head.get("path", ""))
    return out


def _diff_lists(label: str, a: list[Any], b: list[Any]) -> list[str]:
    diffs: list[str] = []
    if len(a) != len(b):
        diffs.append(f"{label}: length {len(a)} != baseline {len(b)}")
        return diffs
    for i, (ai, bi) in enumerate(zip(a, b)):
        diffs.extend(_diff_nodes(f"{label}[{i}]", ai, bi))
    return diffs


def _diff_nodes(label: str, a: Any, b: Any) -> list[str]:
    if type(a) is not type(b):  # noqa: E721
        return [f"{label}: type {type(a).__name__} != baseline {type(b).__name__}"]
    if isinstance(a, dict):
        diffs: list[str] = []
        a_keys = set(a.keys())
        b_keys = set(b.keys())
        for k in sorted(a_keys - b_keys):
            diffs.append(f"{label}.{k}: present, not in baseline")
        for k in sorted(b_keys - a_keys):
            diffs.append(f"{label}.{k}: missing, in baseline")
        for k in sorted(a_keys & b_keys):
            diffs.extend(_diff_nodes(f"{label}.{k}", a[k], b[k]))
        return diffs
    if isinstance(a, list):
        return _diff_lists(label, a, b)
    if a != b:
        return [f"{label}: {a!r} != baseline {b!r}"]
    return []


def compare_envelope_against_baseline(
    observed: dict[str, Any],
    baseline: dict[str, Any],
) -> tuple[str, tuple[str, ...]]:
    """
    Compare a normalised observed envelope against the (also
    normalised) baseline. Returns the verdict and a tuple of diff
    lines (empty if INTACT).
    """
    obs_norm = _normalise_envelope(observed)
    base_norm = _normalise_envelope(baseline)
    diffs = _diff_nodes("envelope", obs_norm, base_norm)
    if diffs:
        return PIN_VERDICT_DRIFT, tuple(diffs)
    return PIN_VERDICT_INTACT, ()


def run_pin_check(
    *,
    decisions_dir: pathlib.Path,
    spec_path: pathlib.Path,
    baseline_path: pathlib.Path,
) -> PinResult:
    """
    Execute the Tag-59 pin gate.

    Skip discipline
    ---------------
    If ``decisions_dir`` does not exist (e.g. a CI runner without
    the AI-Corp sibling clone), return ``AUDIT-PIN-SKIP`` with a
    clear reason. We do not turn a missing sibling into a red
    gate — the gate is *only* a regression detector when the
    sibling is in place.
    """
    if not decisions_dir.exists():
        return PinResult(
            verdict=PIN_VERDICT_SKIP,
            diffs=(),
            decisions_dir=str(decisions_dir),
            spec_path=str(spec_path),
            baseline_path=str(baseline_path),
            skip_reason=f"decisions_dir not found on runner: {decisions_dir}",
        )
    if not spec_path.exists():
        return PinResult(
            verdict=PIN_VERDICT_SKIP,
            diffs=(),
            decisions_dir=str(decisions_dir),
            spec_path=str(spec_path),
            baseline_path=str(baseline_path),
            skip_reason=f"spec_path not found on runner: {spec_path}",
        )
    if not baseline_path.exists():
        return PinResult(
            verdict=PIN_VERDICT_DRIFT,
            diffs=(f"baseline file missing: {baseline_path}",),
            decisions_dir=str(decisions_dir),
            spec_path=str(spec_path),
            baseline_path=str(baseline_path),
        )

    # Import lazily so the verifier module is importable in tests
    # without forcing the audit module on the path at module-load.
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    try:
        from audit_adr_errata_spec_drift import run_audit  # type: ignore[import-not-found]
    finally:
        # Defensive: leave sys.path tidy if the caller cares.
        pass

    envelope = run_audit(decisions_dir=decisions_dir, spec_path=spec_path)
    observed = json.loads(envelope.to_json())
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    verdict, diffs = compare_envelope_against_baseline(observed, baseline)
    return PinResult(
        verdict=verdict,
        diffs=diffs,
        decisions_dir=str(decisions_dir),
        spec_path=str(spec_path),
        baseline_path=str(baseline_path),
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="adr_errata_audit_pin_verifier",
        description=(
            "Tag-59 ADR-Errata-Footer-Verifier CI-Pin: compare a "
            "fresh audit-helper run against the committed baseline."
        ),
    )
    parser.add_argument(
        "--decisions-dir",
        type=pathlib.Path,
        default=pathlib.Path(
            os.environ.get(
                "ADR_ERRATA_DECISIONS_DIR",
                "/var/home/fred/AI-Corp/decisions",
            )
        ),
        help="Path to AI-Corp/decisions/. Default: %(default)s",
    )
    parser.add_argument(
        "--spec",
        type=pathlib.Path,
        default=pathlib.Path("wirelang/specs/wirelang-spec-v0-4-3.md"),
        help="Path to the Wirelang spec file. Default: %(default)s",
    )
    parser.add_argument(
        "--baseline",
        type=pathlib.Path,
        default=pathlib.Path("tooling/audit/adr-errata-audit-baseline.json"),
        help="Path to baseline snapshot. Default: %(default)s",
    )
    args = parser.parse_args(argv)

    result = run_pin_check(
        decisions_dir=args.decisions_dir,
        spec_path=args.spec,
        baseline_path=args.baseline,
    )
    for line in result.to_lines():
        print(line)

    if result.verdict == PIN_VERDICT_INTACT:
        return 0
    if result.verdict == PIN_VERDICT_SKIP:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
