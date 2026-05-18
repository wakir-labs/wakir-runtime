#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Structural verifier for the Phase-3-COMPLETE-Marker workflow.

Used by ``.github/workflows/phase-3c-pre-cutover-sanity.yml`` Step 4
to confirm the marker-workflow YAML still contains the
five-conjunctive-AC topology (AC-1..AC-5 verify-jobs + emit-job that
``needs`` all five). This is a structural sanity check only - it
does NOT exercise the marker-workflow's dynamic semantics. Those
are covered by ``tests/ci/test_phase_3_complete_marker_workflow.py``.

Exit codes
----------

* ``0`` - structurally valid.
* ``2`` - structurally invalid (missing job, broken needs-edge,
  ``workflow_dispatch.dry_run`` input absent). Treated as
  ``yellow`` (CAUTION) by the parent workflow.
* ``1`` - YAML parse error or filesystem error. Treated as
  ``red`` (BLOCK) by the parent workflow.

Hermetic
--------

stdlib + pyyaml. No subprocess, no network.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

import yaml


REQUIRED_AC_JOBS = (
    "verify-ac-1-welle-sign-offs",
    "verify-ac-2-aggregate-consistency",
    "verify-ac-3-predecessor-closure",
    "verify-ac-4-henrik-ratification",
    "verify-ac-5-ar-hand-ratification",
)
EMIT_JOB = "emit-phase-3-complete-marker"


def _on_block(data: dict) -> dict:
    # PyYAML maps the bare ``on:`` key to Python True for some YAML
    # documents; accept both spellings.
    on = data.get("on", data.get(True))
    if not isinstance(on, dict):
        raise ValueError("workflow.on must be a mapping")
    return on


def _needs_list(value) -> Iterable[str]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(value)
    raise ValueError(f"unexpected `needs` type: {type(value).__name__}")


def verify(path: Path) -> int:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"::warning::Step 4: failed to parse {path}: {exc}")
        return 1
    if not isinstance(data, dict):
        print(f"::warning::Step 4: {path} did not parse as a mapping")
        return 1

    jobs = data.get("jobs", {})
    if not isinstance(jobs, dict):
        print(f"::warning::Step 4: jobs section missing or malformed in {path}")
        return 2

    missing_jobs = [j for j in (*REQUIRED_AC_JOBS, EMIT_JOB) if j not in jobs]
    if missing_jobs:
        print(
            f"::warning::Step 4: marker-workflow missing jobs: "
            f"{sorted(missing_jobs)}"
        )
        return 2

    emit = jobs[EMIT_JOB]
    if not isinstance(emit, dict):
        print(f"::warning::Step 4: emit job {EMIT_JOB!r} is not a mapping")
        return 2

    needs = list(_needs_list(emit.get("needs")))
    for ac in REQUIRED_AC_JOBS:
        if ac not in needs:
            print(f"::warning::Step 4: emit-job does not need {ac}")
            return 2

    # Trigger surface sanity: workflow_dispatch with dry_run input.
    try:
        on = _on_block(data)
    except Exception as exc:
        print(f"::warning::Step 4: bad on-block: {exc}")
        return 2
    wd = on.get("workflow_dispatch")
    if not isinstance(wd, dict):
        print("::warning::Step 4: workflow_dispatch trigger missing")
        return 2
    inputs = wd.get("inputs", {}) or {}
    if "dry_run" not in inputs:
        print("::warning::Step 4: workflow_dispatch.inputs.dry_run missing")
        return 2

    print(
        f"Step 4: marker-workflow {path} structurally valid "
        f"(5/5 AC jobs + emit-needs-all + dry_run input)."
    )
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <path-to-marker-workflow.yml>", file=sys.stderr)
        return 1
    path = Path(argv[1])
    if not path.is_file():
        print(f"::warning::Step 4: marker workflow not found at {path}")
        return 1
    return verify(path)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
