#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Validate the Tag-62 Bulk-Activation Plan JSON envelope shape.

Hermetic, stdlib-only. Reads a plan-envelope file produced by
``tooling/ops/_bulk_activate_required_checks.py --json`` and asserts:

  - All required top-level keys are present
  - ``tag`` is ``tag-62``
  - ``target_pool_size`` is 7
  - ``required_status_checks`` is a dict with both ``strict`` and
    ``contexts``
  - ``required_status_checks.strict`` is true
  - ``required_status_checks.contexts`` is a 7-element list of
    non-empty unique strings

Exit code 0 on pass, 1 on failure with ::error:: lines.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


REQUIRED_TOP_LEVEL_KEYS = {
    "tag",
    "schema",
    "target_pool_size",
    "parsed_combined_count",
    "parsed_pool_bilanz_count",
    "endpoint",
    "required_status_checks",
    "errors",
    "verdict",
}


def validate(envelope: dict) -> list[str]:
    errs: list[str] = []

    missing = REQUIRED_TOP_LEVEL_KEYS - set(envelope.keys())
    if missing:
        errs.append(f"envelope missing keys: {sorted(missing)}")
        # Keep scanning so callers see the full report.

    tag = envelope.get("tag")
    if tag != "tag-62":
        errs.append(f"tag must be 'tag-62', got {tag!r}")

    tps = envelope.get("target_pool_size")
    if tps != 7:
        errs.append(f"target_pool_size must be 7, got {tps!r}")

    rsc = envelope.get("required_status_checks")
    if not isinstance(rsc, dict):
        errs.append("required_status_checks must be a dict")
        return errs

    if "strict" not in rsc or "contexts" not in rsc:
        errs.append("required_status_checks needs both 'strict' and 'contexts'")
        return errs

    if rsc["strict"] is not True:
        errs.append(f"required_status_checks.strict must be true, got {rsc['strict']!r}")

    ctx = rsc["contexts"]
    if not isinstance(ctx, list):
        errs.append("required_status_checks.contexts must be a list")
        return errs

    if len(ctx) != 7:
        errs.append(f"contexts must have 7 entries, got {len(ctx)}")

    if len(set(ctx)) != len(ctx):
        errs.append("contexts contains duplicates")

    for i, c in enumerate(ctx):
        if not isinstance(c, str):
            errs.append(f"contexts[{i}] not a string: {c!r}")
        elif not c.strip():
            errs.append(f"contexts[{i}] is empty / whitespace-only")

    return errs


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: validate_bulk_activation_envelope.py PATH", file=sys.stderr)
        return 1
    path = Path(argv[0])
    if not path.exists():
        print(f"::error::envelope file missing: {path}")
        return 1
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"::error::envelope is not valid JSON: {exc}")
        return 1
    errs = validate(envelope)
    if errs:
        for err in errs:
            print(f"::error::{err}")
        return 1
    ctx = envelope["required_status_checks"]["contexts"]
    print("envelope shape: OK")
    print(f"pool size      : {len(ctx)}")
    print(f"verdict        : {envelope['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
