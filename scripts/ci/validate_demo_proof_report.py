#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Validate a ``wakir-demo-proof/v1`` report for the proof-path CI gate.

This is the hard-fail half of ``.github/workflows/proof-path.yml``.
``scripts/demo-proof.sh`` deliberately exits 0 when a step is
``skipped`` (a fresh clone without wakir-verify must still produce a
usable report). The CI gate is stricter: every step must have run and
succeeded, and the report must describe the commit CI is actually
checking.

Rules (each violation is reported, any violation exits non-zero):

1. The file parses as a JSON object.
2. ``schema`` equals ``wakir-demo-proof/v1``.
3. ``steps`` is a list of exactly five objects whose ``name`` values
   are, in order: ``protocol_event``, ``runtime_bridge``,
   ``merkle_manifest``, ``inclusion_proof``, ``external_verify``.
4. Every step carries a ``status`` string and an integer ``exit_code``.
5. No step has status ``failed`` or ``not_run``.
6. With ``--require-external-verify-ok`` the ``external_verify`` step
   must have status ``ok`` (a ``skipped`` step is a hard failure).
7. ``commits.wakir_runtime`` equals the expected commit, taken from
   ``--expect-commit`` or, when that flag is absent, from the
   ``GITHUB_SHA`` environment variable. If neither is set the check
   is skipped with a note (local runs without CI context).
8. Top-level ``exit_code`` is ``0``.

Exit codes: ``0`` valid, ``1`` validation failure, ``2`` usage or
unreadable input. Stdlib only; no third-party imports.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable, List, Optional

REPORT_SCHEMA = "wakir-demo-proof/v1"

STEP_NAMES = (
    "protocol_event",
    "runtime_bridge",
    "merkle_manifest",
    "inclusion_proof",
    "external_verify",
)

FORBIDDEN_STATUSES = ("failed", "not_run")

EXIT_VALID = 0
EXIT_INVALID = 1
EXIT_USAGE = 2


def validate_report(
    report: Any,
    *,
    require_external_verify_ok: bool,
    expected_commit: Optional[str],
) -> List[str]:
    """Return a list of human-readable violations. Empty list == valid."""
    violations: List[str] = []

    if not isinstance(report, dict):
        return ["report is not a JSON object"]

    schema = report.get("schema")
    if schema != REPORT_SCHEMA:
        violations.append(f"schema: expected {REPORT_SCHEMA!r}, got {schema!r}")

    steps = report.get("steps")
    if not isinstance(steps, list):
        violations.append("steps: missing or not a list")
        steps = []

    names = [s.get("name") if isinstance(s, dict) else None for s in steps]
    if len(steps) != len(STEP_NAMES):
        violations.append(
            f"steps: expected exactly {len(STEP_NAMES)} steps, got {len(steps)}"
        )
    if names != list(STEP_NAMES):
        missing = [n for n in STEP_NAMES if n not in names]
        unexpected = [n for n in names if n not in STEP_NAMES]
        detail = []
        if missing:
            detail.append(f"missing={missing}")
        if unexpected:
            detail.append(f"unexpected={unexpected}")
        if not missing and not unexpected:
            detail.append("order differs")
        violations.append(
            f"steps: names/order mismatch; got {names}; expected {list(STEP_NAMES)}"
            f" ({', '.join(detail)})"
        )

    for idx, step in enumerate(steps):
        label = f"steps[{idx}]"
        if not isinstance(step, dict):
            violations.append(f"{label}: not an object")
            continue
        name = step.get("name")
        label = f"{label} ({name})" if isinstance(name, str) else label
        status = step.get("status")
        if not isinstance(status, str) or not status:
            violations.append(f"{label}: status missing or not a string")
        elif status in FORBIDDEN_STATUSES:
            reason = ""
            details = step.get("details")
            if isinstance(details, dict):
                reason = details.get("error") or details.get("reason") or ""
            violations.append(
                f"{label}: status {status!r} is not allowed in CI"
                + (f" — {reason}" if reason else "")
            )
        code = step.get("exit_code")
        if not isinstance(code, int) or isinstance(code, bool):
            violations.append(f"{label}: exit_code missing or not an integer")

    if require_external_verify_ok:
        ev = next(
            (
                s
                for s in steps
                if isinstance(s, dict) and s.get("name") == "external_verify"
            ),
            None,
        )
        if ev is None:
            violations.append("external_verify: step missing (required ok)")
        elif ev.get("status") != "ok":
            details = ev.get("details") if isinstance(ev.get("details"), dict) else {}
            reason = details.get("reason") or details.get("error") or ""
            violations.append(
                f"external_verify: status {ev.get('status')!r}, required 'ok'"
                + (f" — {reason}" if reason else "")
            )

    commits = report.get("commits")
    if not isinstance(commits, dict):
        violations.append("commits: missing or not an object")
        commits = {}
    if expected_commit:
        actual = commits.get("wakir_runtime")
        if actual != expected_commit:
            violations.append(
                f"commits.wakir_runtime: expected {expected_commit!r}, got {actual!r}"
            )

    top_code = report.get("exit_code")
    if top_code != 0 or isinstance(top_code, bool):
        violations.append(f"exit_code: expected 0, got {top_code!r}")

    return violations


def _load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="validate_demo_proof_report",
        description="Hard-fail validator for wakir-demo-proof/v1 reports (proof-path CI gate).",
    )
    parser.add_argument("report", type=Path, help="Path to demo-report.json")
    parser.add_argument(
        "--require-external-verify-ok",
        action="store_true",
        help="Fail unless the external_verify step has status 'ok'.",
    )
    parser.add_argument(
        "--expect-commit",
        default=None,
        help=(
            "Expected commits.wakir_runtime value. Defaults to $GITHUB_SHA when "
            "set; the check is skipped if neither is available."
        ),
    )
    return parser.parse_args(list(argv))


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)

    expected_commit = args.expect_commit or os.environ.get("GITHUB_SHA") or None

    try:
        report = _load(args.report)
    except FileNotFoundError:
        print(f"validate-demo-proof: report not found: {args.report}", file=sys.stderr)
        return EXIT_USAGE
    except json.JSONDecodeError as exc:
        print(f"validate-demo-proof: report is not valid JSON: {exc}", file=sys.stderr)
        return EXIT_USAGE

    violations = validate_report(
        report,
        require_external_verify_ok=args.require_external_verify_ok,
        expected_commit=expected_commit,
    )

    if violations:
        print(
            f"validate-demo-proof: FAIL — {len(violations)} violation(s) in {args.report}",
            file=sys.stderr,
        )
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return EXIT_INVALID

    statuses = [
        f"{s.get('name')}={s.get('status')}"
        for s in report.get("steps", [])
        if isinstance(s, dict)
    ]
    commit_note = (
        f"commit={expected_commit}" if expected_commit else "commit check skipped (no GITHUB_SHA)"
    )
    print(f"validate-demo-proof: OK — {', '.join(statuses)}; {commit_note}")
    return EXIT_VALID


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
