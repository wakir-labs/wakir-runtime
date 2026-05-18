#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Render a Markdown Job-Summary fragment for the cross-welle envelope.

Reads ``out/cross-welle-hot-spot-verdict.json`` (or the path passed as
the first CLI argument), writes a Markdown fragment to stdout suitable
for piping into ``$GITHUB_STEP_SUMMARY``.

stdlib-only. No subprocess. No network.
"""

from __future__ import annotations

import json
import pathlib
import sys


def render(envelope: dict) -> str:
    """Return the Markdown fragment for the envelope's Job-Summary."""
    lines: list[str] = []
    lines.append("| Welle | Verdict | Dated-at | Counts(r/y/g) | Propagation |")
    lines.append("|------:|:--------|:---------|:--------------|:------------|")
    for s in envelope.get("per_welle_slots") or []:
        c = s.get("counts") or {}
        if c:
            counts = "{0}/{1}/{2}".format(
                c.get("red", "-"), c.get("yellow", "-"), c.get("green", "-")
            )
        else:
            counts = "-"
        prop_targets = s.get("propagation_targets") or []
        prop = ",".join(str(x) for x in prop_targets) or "-"
        welle = s["welle"]
        verdict = s["verdict"]
        dated = s.get("dated_at") or "-"
        lines.append(
            "| {0} | {1} | {2} | {3} | {4} |".format(
                welle, verdict, dated, counts, prop
            )
        )
    lines.append("")
    lines.append("## Cascade fan-out")
    lines.append("")
    fan = envelope.get("cascade_fan_out") or []
    if fan:
        lines.append("Transitively reached downstream wellen: " + str(sorted(fan)))
    else:
        lines.append("No propagation block fired.")
    lines.append("")
    lines.append("## Top hot-spots (ranked)")
    lines.append("")
    for i, t in enumerate(envelope.get("top_hot_spots") or [], start=1):
        targets = t.get("propagation_targets") or []
        lines.append(
            "{0}. Welle-{1} -- {2} (propagation_targets={3})".format(
                i, t["welle"], t["verdict"], targets
            )
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    path = pathlib.Path(
        argv[1] if len(argv) > 1 else "out/cross-welle-hot-spot-verdict.json"
    )
    envelope = json.loads(path.read_text(encoding="utf-8"))
    sys.stdout.write(render(envelope))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
