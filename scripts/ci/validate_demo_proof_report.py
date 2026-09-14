#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Validate a ``wakir-demo-proof/v1`` report for the proof-path CI gate.

This is the hard-fail half of ``.github/workflows/proof-path.yml``.
``scripts/demo-proof.sh`` deliberately exits 0 when a step is
``skipped`` (a fresh clone without wakir-verify must still produce a
usable report). This validator does not: **the default profile is
strict**, and strict means every step ran, succeeded, and carries
step details that do not contradict that verdict.

Profiles
--------

``strict`` (default, and the only profile CI runs)
    Every one of the five steps has status exactly ``ok`` and an
    ``exit_code`` that is exactly the integer ``0``. Missing,
    ``unknown``, ``skipped``, ``failed``, ``not_run`` and any status
    string the driver does not define are all rejected. The detail
    flags the driver writes for a successful step must agree with the
    status (see ``REQUIRED_TRUE_DETAILS`` below).

``--allow-skipped-external-verify`` (developer convenience, never CI)
    The one documented relaxation: ``external_verify`` may be
    ``skipped`` with ``exit_code`` 20, for a local run in an
    environment where ``wakir_verify`` is not importable. Every other
    rule stays in force. The proof path does not pass this flag, and
    ``tests/ci/test_validate_demo_proof_report.py`` pins that.

Rules (each violation is reported, any violation exits non-zero):

1. The file parses as a JSON object.
2. ``schema`` equals ``wakir-demo-proof/v1``.
3. ``steps`` is a list of exactly five objects whose ``name`` values
   are, in order: ``protocol_event``, ``runtime_bridge``,
   ``merkle_manifest``, ``inclusion_proof``, ``external_verify``.
4. Every step carries a ``status`` string from the allow-list of the
   active profile — ``ok`` for every step in the strict profile.
5. Every step's ``exit_code`` is the integer that the driver pairs
   with that status (``ok`` -> 0, ``skipped`` -> 20). Booleans are not
   integers here, and ``ok`` with a non-zero code is a contradiction,
   not a rounding error.
6. Step details do not contradict the step status: a successful
   ``external_verify`` carries ``manifest_consistent``, ``root_match``,
   ``leaf_present`` and ``proof_verified``, all boolean ``true``; a
   successful ``inclusion_proof`` carries ``verified: true``; a
   successful ``runtime_bridge`` carries ``bridge_status: "ok"``. No
   successful step carries ``fault_injected``, and a successful
   ``merkle_manifest`` states ``envelope_projection_used: false``
   (the spool, not the envelope, is the input of the manifest step —
   see ``scripts/demo_proof_helpers.py``).
7. ``commits.wakir_runtime`` equals the expected commit, taken from
   ``--expect-commit`` or, when that flag is absent, from the
   ``GITHUB_SHA`` environment variable. If neither is set the check
   is skipped with a note (local runs without CI context).
8. Top-level ``exit_code`` is the integer ``0``.

``--require-external-verify-ok`` is accepted for compatibility with
callers written against the old permissive default. It is a no-op:
the strict profile already requires it, and it additionally overrides
``--allow-skipped-external-verify`` if both are passed.

Exit codes: ``0`` valid, ``1`` validation failure, ``2`` usage or
unreadable input. Stdlib only; no third-party imports.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

REPORT_SCHEMA = "wakir-demo-proof/v1"

STEP_NAMES = (
    "protocol_event",
    "runtime_bridge",
    "merkle_manifest",
    "inclusion_proof",
    "external_verify",
)

#: Status -> the exit code ``scripts/demo_proof_helpers.py`` pairs with
#: it. A report that disagrees with this map is self-contradictory,
#: whatever the status string says.
EXIT_CODE_BY_STATUS: Dict[str, int] = {
    "ok": 0,
    "skipped": 20,
    "failed": 10,
    "not_run": 30,
}

#: The allow-list. Not a deny-list: an unknown status string
#: (``banana``, ``passed``, ``""``) must be rejected, not tolerated
#: because nobody thought to forbid it.
STRICT_ALLOWED_STATUSES: Tuple[str, ...] = ("ok",)

#: Detail flags the driver writes for a *successful* step. They are
#: the step's own verdict about its substance; a green status on top
#: of a false flag is the contradiction this validator exists to
#: catch. Keys must be present and boolean ``true``.
#: Source of truth: ``scripts/demo-proof.sh`` step 4 / step 5 and
#: ``do_external_verify`` in ``scripts/demo_proof_helpers.py``.
REQUIRED_TRUE_DETAILS: Dict[str, Tuple[str, ...]] = {
    "inclusion_proof": ("verified",),
    "external_verify": (
        "manifest_consistent",
        "root_match",
        "leaf_present",
        "proof_verified",
    ),
}

#: Detail fields that must carry an exact value on a successful step.
REQUIRED_DETAIL_VALUES: Dict[str, Dict[str, Any]] = {
    "runtime_bridge": {"bridge_status": "ok"},
}

#: Detail flags that must be **present and false** on a successful
#: step. ``envelope_projection_used`` says whether step 3 built the
#: manifest from the spool alone or filled fields in from
#: ``event.envelope.json``. A projected run is a developer artefact,
#: not a proof, so the strict profile insists the report answers the
#: question rather than leaving it out.
REQUIRED_FALSE_DETAILS: Dict[str, Tuple[str, ...]] = {
    "merkle_manifest": ("envelope_projection_used",),
}

#: Detail flags that must be absent or falsy on a successful step.
#: ``fault_injected`` is the driver's test-mode marker; a fault-injected
#: run is never a proof.
FORBIDDEN_TRUE_DETAILS: Dict[str, Tuple[str, ...]] = {
    "protocol_event": ("fault_injected",),
    "runtime_bridge": ("fault_injected",),
    "merkle_manifest": ("fault_injected",),
    "inclusion_proof": ("fault_injected",),
    "external_verify": ("fault_injected",),
}

EXIT_VALID = 0
EXIT_INVALID = 1
EXIT_USAGE = 2


def _is_true(value: Any) -> bool:
    """``True`` only for the JSON boolean, and for the strings the
    bash driver writes through ``--kv`` (which has no JSON types)."""
    if isinstance(value, bool):
        return value
    return isinstance(value, str) and value.strip().lower() == "true"


def _allowed_statuses(step_name: str, *, allow_skipped_external: bool) -> Tuple[str, ...]:
    if allow_skipped_external and step_name == "external_verify":
        return ("ok", "skipped")
    return STRICT_ALLOWED_STATUSES


def _check_details(step: Dict[str, Any], name: str, label: str) -> List[str]:
    """Cross-check a *successful* step's details against its status."""
    violations: List[str] = []
    details = step.get("details")
    if not isinstance(details, dict):
        violations.append(f"{label}: details missing or not an object")
        return violations

    for key in REQUIRED_TRUE_DETAILS.get(name, ()):
        if key not in details:
            violations.append(
                f"{label}: status 'ok' but details.{key} is missing; a successful "
                "step must carry its own verdict"
            )
        elif not _is_true(details[key]):
            violations.append(
                f"{label}: status 'ok' contradicts details.{key}={details[key]!r}"
            )

    for key, expected in REQUIRED_DETAIL_VALUES.get(name, {}).items():
        if key not in details:
            violations.append(
                f"{label}: status 'ok' but details.{key} is missing "
                f"(expected {expected!r})"
            )
        elif details[key] != expected:
            violations.append(
                f"{label}: status 'ok' contradicts details.{key}={details[key]!r}, "
                f"expected {expected!r}"
            )

    for key in REQUIRED_FALSE_DETAILS.get(name, ()):
        if key not in details:
            violations.append(
                f"{label}: status 'ok' but details.{key} is missing; the report "
                "must state whether the step used repaired input"
            )
        elif _is_true(details[key]):
            violations.append(
                f"{label}: status 'ok' contradicts details.{key}={details[key]!r}"
            )

    for key in FORBIDDEN_TRUE_DETAILS.get(name, ()):
        if key in details and _is_true(details[key]):
            violations.append(
                f"{label}: status 'ok' contradicts details.{key}={details[key]!r}"
            )

    return violations


def validate_report(
    report: Any,
    *,
    allow_skipped_external_verify: bool = False,
    expected_commit: Optional[str] = None,
    require_external_verify_ok: bool = False,
) -> List[str]:
    """Return a list of human-readable violations. Empty list == valid.

    ``allow_skipped_external_verify`` is the only relaxation; the
    default is the strict profile that ``proof-path.yml`` runs.
    ``require_external_verify_ok`` is the compatibility flag: it
    cancels the relaxation, so passing both is strict.
    """
    if require_external_verify_ok:
        allow_skipped_external_verify = False

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

        allowed = _allowed_statuses(
            name if isinstance(name, str) else "",
            allow_skipped_external=allow_skipped_external_verify,
        )
        status = step.get("status")
        status_ok = False
        if not isinstance(status, str) or not status:
            violations.append(f"{label}: status missing or not a string")
        elif status not in allowed:
            reason = ""
            details = step.get("details")
            if isinstance(details, dict):
                reason = details.get("error") or details.get("reason") or ""
            violations.append(
                f"{label}: status {status!r} is not accepted; allowed here: "
                f"{list(allowed)}" + (f" — {reason}" if reason else "")
            )
        else:
            status_ok = True

        code = step.get("exit_code")
        if not isinstance(code, int) or isinstance(code, bool):
            violations.append(f"{label}: exit_code missing or not an integer")
        elif status_ok:
            expected_code = EXIT_CODE_BY_STATUS[status]
            if code != expected_code:
                violations.append(
                    f"{label}: status {status!r} requires exit_code "
                    f"{expected_code}, got {code!r}"
                )

        if status_ok and status == "ok" and isinstance(name, str):
            violations.extend(_check_details(step, name, label))

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
    if not isinstance(top_code, int) or isinstance(top_code, bool) or top_code != 0:
        violations.append(f"exit_code: expected 0, got {top_code!r}")

    return violations


def _load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="validate_demo_proof_report",
        description=(
            "Hard-fail validator for wakir-demo-proof/v1 reports "
            "(proof-path CI gate). Strict by default."
        ),
    )
    parser.add_argument("report", type=Path, help="Path to demo-report.json")
    parser.add_argument(
        "--allow-skipped-external-verify",
        action="store_true",
        help=(
            "Developer convenience for a local run without wakir-verify: "
            "accept external_verify with status 'skipped' / exit_code 20. "
            "The CI proof path never sets this."
        ),
    )
    parser.add_argument(
        "--require-external-verify-ok",
        action="store_true",
        help=(
            "Compatibility no-op: the default profile already requires it. "
            "Overrides --allow-skipped-external-verify when both are given."
        ),
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
        allow_skipped_external_verify=args.allow_skipped_external_verify,
        expected_commit=expected_commit,
        require_external_verify_ok=args.require_external_verify_ok,
    )

    if violations:
        print(
            f"validate-demo-proof: FAIL — {len(violations)} violation(s) in {args.report}",
            file=sys.stderr,
        )
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return EXIT_INVALID

    profile = (
        "local (external_verify may be skipped)"
        if args.allow_skipped_external_verify and not args.require_external_verify_ok
        else "strict"
    )
    statuses = [
        f"{s.get('name')}={s.get('status')}"
        for s in report.get("steps", [])
        if isinstance(s, dict)
    ]
    commit_note = (
        f"commit={expected_commit}" if expected_commit else "commit check skipped (no GITHUB_SHA)"
    )
    print(
        f"validate-demo-proof: OK [{profile}] — {', '.join(statuses)}; {commit_note}"
    )
    return EXIT_VALID


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
