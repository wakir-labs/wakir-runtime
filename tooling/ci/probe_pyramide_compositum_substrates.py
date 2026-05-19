#!/usr/bin/env python3
# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-62 Pyramide-Acceptance Pre-Cutover Compositum substrate-probes.

Helper invoked from the Tag-62 workflow YAML to probe individual
sub-gate substrates without embedding multi-line Python inside
shell heredocs (which collides with YAML literal-block indentation
and is brittle in practice -- per feedback_yaml_frontmatter_
disziplin.md).

Modes
-----

* ``layer-dag-verdict``  - read JSON from stdin (output of
  ``tooling/ci/verify_layer_dependency_dag.py --json``) and print
  the ``verdict`` field on stdout (or ``PARSE-ERROR`` if the input
  cannot be parsed). Exit 0 always.

* ``drift-allowlist``    - read the file path passed via ``--path``
  and print one of::

      OK:<count>            - file parses, entries valid, count >= 0
      MALFORMED:<repr>      - file does not parse as JSON
      SCHEMA:<reason>       - schema invariants violated
      NO-FOLLOWUP:<indices> - entries present without follow_up

  Exit 0 always; the caller switches on the prefix.

Hermetic
--------

Stdlib only.

Scope discipline (Amara, ADR-0044/0066)
---------------------------------------

This probe helper is a thin shell-side adapter and lives in the
QA-Pyramide CI surface. It does NOT modify persona definitions,
WAT-core / V-907 logic, identity-substrate, container-infra, or
persona-engine substrate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _probe_layer_dag_verdict(raw_stdin: str) -> str:
    """Extract the layer-dag verdict from a JSON envelope on stdin."""
    try:
        data = json.loads(raw_stdin)
    except Exception:
        return "PARSE-ERROR"
    if not isinstance(data, dict):
        return "PARSE-ERROR"
    verdict = data.get("verdict")
    if not isinstance(verdict, str) or not verdict:
        return "PARSE-ERROR"
    return verdict


def _probe_drift_allowlist(path: Path) -> str:
    """Probe the drift-allowlist file at ``path``."""
    if not path.exists():
        return "MALFORMED:FileNotFound"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"MALFORMED:{type(exc).__name__}"
    if not isinstance(data, dict):
        return "SCHEMA:not-object"
    if "_schema" not in data or "entries" not in data:
        return "SCHEMA:missing-keys"
    entries = data.get("entries") or []
    if not isinstance(entries, list):
        return "SCHEMA:entries-not-list"
    bad: list[str] = []
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            bad.append(str(idx))
            continue
        reason = entry.get("reason")
        follow_up = entry.get("follow_up")
        if not reason or not follow_up:
            bad.append(str(idx))
    if bad:
        return "NO-FOLLOWUP:" + ",".join(bad)
    return f"OK:{len(entries)}"


def main(argv: list[str]) -> int:
    """Probe-helper entry-point."""
    parser = argparse.ArgumentParser(
        description=(
            "Tag-62 Pyramide-Acceptance Pre-Cutover Compositum "
            "substrate-probes (layer-dag verdict extract, drift-"
            "allowlist file probe)."
        )
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=("layer-dag-verdict", "drift-allowlist"),
        help="Probe mode.",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Allowlist file path (required for --mode=drift-allowlist).",
    )
    args = parser.parse_args(argv[1:])
    if args.mode == "layer-dag-verdict":
        raw = sys.stdin.read()
        print(_probe_layer_dag_verdict(raw))
        return 0
    if args.mode == "drift-allowlist":
        if args.path is None:
            print("SCHEMA:no-path-given")
            return 0
        print(_probe_drift_allowlist(args.path))
        return 0
    print("SCHEMA:unknown-mode")  # pragma: no cover - argparse guards
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI dispatch
    sys.exit(main(sys.argv))
