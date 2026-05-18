#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""AR-Hand-Stop-Marker Listener — Cascade-Compute-Step.

Given the welle for which a stop-marker landed, compute three
cancel-target lists:

  * ``welle_targets``     — welle-N specific cutover workflows.
  * ``cascade_targets``   — welle-M (M > N) workflows blocked by
                            B2-cascade-coupling, **but only** if
                            welle-N is still missing a sign-off.
  * ``marathon_targets``  — marathon/pre-cutover workflows that
                            must pause for any open stop.

The exact workflow filename list is hard-pinned here (NOT
discovered from the filesystem) so the listener's behaviour is
deterministic across PRs that add new welle-validation workflows.
When ADR-0066 §Welle-Sequenz adds a Welle-N workflow, the
operator updates this table in lockstep.

Cascade-Coupling-Source
-----------------------

``state/ar-hand-stop-sign-off-welle-N.json`` existence is read
from the local checkout (cheat-sheet §I sign-off pattern). If
the sign-off-file exists for welle-N, no cascade is triggered
(the marker is being replayed historically and is no longer
blocking).

Sandbox-Boundary
----------------

Stdlib-only.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys


# ---------------------------------------------------------------------------
# Workflow inventory — hard-pinned, ADR-0066 §Welle-Sequenz.
# ---------------------------------------------------------------------------


# Welle-specific cutover-validation workflows (1..7).
WELLE_VALIDATION_WORKFLOWS: dict[int, list[str]] = {
    1: ["phase-3c-welle-1-validation.yml"],
    2: ["phase-3c-welle-2-validation.yml"],
    3: [
        "phase-3c-welle-3-validation.yml",
        "phase-3c-welle-3-hot-spot-probe.yml",
    ],
    4: ["phase-3c-welle-4-validation.yml"],
    5: ["phase-3c-welle-5-validation.yml"],
    6: ["phase-3c-welle-6-validation.yml"],
    7: ["phase-3c-welle-7-validation.yml"],
}

# Marathon / pre-cutover workflows. These run in the pre-cutover
# soak window and must pause for any open stop marker (ADR-0066
# §"keine offene Stops im Marathon-Slot").
MARATHON_WORKFLOWS: list[str] = [
    "phase-3c-pre-cutover-daily-probe.yml",
    "phase-3c-pre-cutover-marathon-dashboard.yml",
    "phase-3c-pre-cutover-sanity.yml",
    "phase-3-cutover-day-auto-scheduler.yml",
    "phase-3c-welle-status-dashboard.yml",
    "phase-3c-marathon-tracker-gate.yml",
]


def compute_cascade(
    *,
    welle: int,
    state_dir: pathlib.Path,
) -> dict[str, object]:
    """Compute the three cancel-target lists for a given welle.

    Returns a mapping with keys:
      welle_targets, cascade_targets, marathon_targets,
      cascade_blocked_welle.
    """

    if welle not in WELLE_VALIDATION_WORKFLOWS:
        raise ValueError(
            f"welle out of range: {welle} (expected 1..7)"
        )

    welle_targets = list(WELLE_VALIDATION_WORKFLOWS[welle])

    sign_off = state_dir / f"ar-hand-stop-sign-off-welle-{welle}.json"
    sign_off_present = sign_off.exists()

    cascade_targets: list[str] = []
    cascade_blocked_welle: list[int] = []
    if not sign_off_present:
        for downstream in range(welle + 1, 8):
            cascade_targets.extend(
                WELLE_VALIDATION_WORKFLOWS[downstream]
            )
            cascade_blocked_welle.append(downstream)

    marathon_targets = list(MARATHON_WORKFLOWS)

    return {
        "welle_targets": welle_targets,
        "cascade_targets": cascade_targets,
        "marathon_targets": marathon_targets,
        "cascade_blocked_welle": cascade_blocked_welle,
        "sign_off_present": sign_off_present,
    }


# ---------------------------------------------------------------------------
# CLI plumbing.
# ---------------------------------------------------------------------------


def _emit_outputs(out_path: pathlib.Path, mapping: dict[str, object]) -> None:
    """Emit GitHub-Actions outputs as JSON-encoded single-line values.

    Multi-line outputs are explicitly avoided by JSON-encoding the
    lists. Consumers (cancel + verdict steps) decode them via
    ``json.loads``.
    """

    lines = []
    for key, value in mapping.items():
        if isinstance(value, (list, tuple)):
            encoded = json.dumps(list(value))
        elif isinstance(value, bool):
            encoded = "true" if value else "false"
        else:
            encoded = str(value)
        if "\n" in encoded:
            raise ValueError(
                f"cascade output {key!r} produced multi-line value"
            )
        lines.append(f"{key}={encoded}")
    body = "\n".join(lines) + "\n"
    with out_path.open("a", encoding="utf-8") as fh:
        fh.write(body)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="ar-hand-stop-marker-listener-cascade")
    p.add_argument("--welle", required=True, type=int)
    p.add_argument("--state-dir", default="state")
    p.add_argument("--out", required=True, help="GITHUB_OUTPUT path")
    p.add_argument(
        "--repo-root",
        default=str(pathlib.Path.cwd()),
        help="repo-root for resolving state-dir",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = pathlib.Path(args.repo_root).resolve()
    state_dir = repo_root / args.state_dir

    try:
        cascade = compute_cascade(welle=args.welle, state_dir=state_dir)
    except ValueError as exc:
        print(f"ERROR: cascade compute failed: {exc}", file=sys.stderr)
        return 2

    _emit_outputs(pathlib.Path(args.out), cascade)
    print(f"cascade computed: {json.dumps(cascade, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
