#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Marathon-Dashboard aggregator for the Tag-42
``phase-3c-pre-cutover-marathon-dashboard.yml`` workflow.

Reads seven per-Welle probe verdicts plus optional cross-coupling
indicators from a directory of per-Welle JSON envelopes (one per
matrix-job, written by each Welle's matrix-leg) and emits a single
Marathon-Readiness envelope plus a rendered Markdown step-summary
table.

Per-Welle envelope contract
---------------------------

Each Welle-N matrix-leg writes a small JSON file with the shape::

    {
        "welle": 1,
        "component": "v907_verify",
        "probe_script": "scripts/phase-3c/welle-1-pre-cutover-probe.sh",
        "probe_present": true,
        "exit_code": 0,
        "verdict": "GREEN",
        "verdict_source": "probe-exit-code",
        "cutover_kw": 24,
        "cutover_pair_partner": 2,
        "cutover_mode": "parallel",
        "cutover_day_window": "2026-06-08T08:00:00+02:00/2026-06-08T10:00:00+02:00",
        "details": "axis breakdown ..."
    }

Verdict values: ``GREEN``, ``CAUTION``, ``BLOCK``, ``NOT-EXEC``.

Marathon-Readiness rule
-----------------------

* ``READY``    - all seven Welle-verdicts ``GREEN``.
* ``CAUTION``  - 1..2 ``CAUTION``/``NOT-EXEC``, zero ``BLOCK``.
* ``BLOCK``    - any ``BLOCK``, OR 3+ ``CAUTION``/``NOT-EXEC``.
* ``NOT-READY`` - all seven ``NOT-EXEC`` (sandbox-stub default; the
                 marathon hasn't actually been probed yet).

Cross-coupling indicators
-------------------------

ADR-0066 pins three doppel-welle pairs that must move together:

* KW-24: Welle-1 + Welle-2 (parallel read-side flips)
* KW-26: Welle-4 + Welle-5 (state-backing + FSM, cross-modul drift)
* KW-27: Welle-6 + Welle-7 (subscribe-loop + recovery)

Welle-3 is solo in KW-25. The aggregator emits a
``cross_coupling`` block that calls out per-pair drift, e.g. one
half ``GREEN`` and the other ``BLOCK`` is a hard couple-violation
that the operator must inspect before KW-24 starts.

Cutover-Day-Window recommendation
---------------------------------

Per Welle, the dashboard emits an ISO-8601 interval covering the
ADR-0066 Cutover-Day execution window: KW-24 Mon 08:00..10:00
CEST = 06:00..08:00 UTC; KW-25 Mon similarly; etc. The interval
is informational - it's the *recommended* window, not a hard
calendar pin.

Hermetic
--------

stdlib + (optional) ``json`` parse of per-Welle envelopes.
No subprocess, no GitHub API, no SSH.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping


# ---------------------------------------------------------------------------
# ADR-0066 calendar plan.  Pinned constants; any deviation should be a
# loud test failure.
# ---------------------------------------------------------------------------

VALID_VERDICTS = ("GREEN", "CAUTION", "BLOCK", "NOT-EXEC")

# Welle-N --> (component, kw, mode, pair-partner | None).
ADR_0066_PLAN: dict[int, dict] = {
    1: {
        "component": "v907_verify",
        "cutover_kw": 24,
        "cutover_mode": "parallel",
        "cutover_pair_partner": 2,
        # KW-24 lands Mon 2026-06-08; cutover window 08:00..10:00 CEST.
        "cutover_day_window": (
            "2026-06-08T08:00:00+02:00/2026-06-08T10:00:00+02:00"
        ),
    },
    2: {
        "component": "svid_workload_identity",
        "cutover_kw": 24,
        "cutover_mode": "parallel",
        "cutover_pair_partner": 1,
        "cutover_day_window": (
            "2026-06-08T08:00:00+02:00/2026-06-08T10:00:00+02:00"
        ),
    },
    3: {
        "component": "bridge_audit_writer",
        "cutover_kw": 25,
        "cutover_mode": "solo",
        "cutover_pair_partner": None,
        "cutover_day_window": (
            "2026-06-15T08:00:00+02:00/2026-06-15T10:00:00+02:00"
        ),
    },
    4: {
        "component": "state_backing",
        "cutover_kw": 26,
        "cutover_mode": "parallel",
        "cutover_pair_partner": 5,
        "cutover_day_window": (
            "2026-06-22T08:00:00+02:00/2026-06-22T10:00:00+02:00"
        ),
    },
    5: {
        "component": "lifecycle_state_machine",
        "cutover_kw": 26,
        "cutover_mode": "parallel",
        "cutover_pair_partner": 4,
        "cutover_day_window": (
            "2026-06-22T08:00:00+02:00/2026-06-22T10:00:00+02:00"
        ),
    },
    6: {
        "component": "subscribe_loop",
        "cutover_kw": 27,
        "cutover_mode": "parallel",
        "cutover_pair_partner": 7,
        "cutover_day_window": (
            "2026-06-29T08:00:00+02:00/2026-06-29T10:00:00+02:00"
        ),
    },
    7: {
        "component": "recovery_workflow",
        "cutover_kw": 27,
        "cutover_mode": "parallel",
        "cutover_pair_partner": 6,
        "cutover_day_window": (
            "2026-06-29T08:00:00+02:00/2026-06-29T10:00:00+02:00"
        ),
    },
}

CROSS_COUPLING_PAIRS: tuple[tuple[int, int, str], ...] = (
    (1, 2, "KW-24 read-side doppel-welle"),
    (4, 5, "KW-26 state-backing + FSM"),
    (6, 7, "KW-27 subscribe-loop + recovery"),
)


# ---------------------------------------------------------------------------
# Verdict normalisation
# ---------------------------------------------------------------------------


def _normalise_verdict(raw: str | None) -> str:
    """Coerce a verdict string to one of VALID_VERDICTS; empty -> NOT-EXEC."""
    if raw is None:
        return "NOT-EXEC"
    v = raw.strip().upper().replace("_", "-")
    # Common synonyms.
    if v in ("READY", "OK", "PASS"):
        return "GREEN"
    if v in ("WARN", "WARNING", "YELLOW"):
        return "CAUTION"
    if v in ("FAIL", "RED", "ERROR"):
        return "BLOCK"
    if v in ("NOT-EXEC", "NOT-EXECUTED", "SKIP", "SKIPPED", "MISSING"):
        return "NOT-EXEC"
    if v in VALID_VERDICTS:
        return v
    # Unknown values: treat as BLOCK (loud fail).
    return "BLOCK"


def _normalise_envelope(welle: int, env: Mapping) -> dict:
    """Apply pinned ADR-0066 plan fields + normalised verdict to an envelope."""
    plan = ADR_0066_PLAN[welle]
    verdict = _normalise_verdict(env.get("verdict"))
    exit_code = env.get("exit_code")
    try:
        exit_code = int(exit_code) if exit_code is not None else None
    except (TypeError, ValueError):
        exit_code = None
    probe_present_raw = env.get("probe_present")
    if isinstance(probe_present_raw, bool):
        probe_present = probe_present_raw
    elif isinstance(probe_present_raw, str):
        probe_present = probe_present_raw.strip().lower() in ("true", "1", "yes")
    else:
        probe_present = False
    return {
        "welle": welle,
        "component": str(env.get("component") or plan["component"]),
        "probe_script": str(
            env.get("probe_script")
            or f"scripts/phase-3c/welle-{welle}-pre-cutover-probe.sh"
        ),
        "probe_present": probe_present,
        "exit_code": exit_code,
        "verdict": verdict,
        "verdict_source": str(env.get("verdict_source") or "unknown"),
        "cutover_kw": plan["cutover_kw"],
        "cutover_pair_partner": plan["cutover_pair_partner"],
        "cutover_mode": plan["cutover_mode"],
        "cutover_day_window": plan["cutover_day_window"],
        "details": str(env.get("details") or ""),
    }


# ---------------------------------------------------------------------------
# Marathon-Readiness decision
# ---------------------------------------------------------------------------


def decide_marathon(per_welle_verdicts: Mapping[int, str]) -> str:
    """Aggregate seven per-Welle verdicts into the marathon verdict."""
    counts: dict[str, int] = {v: 0 for v in VALID_VERDICTS}
    for welle in (1, 2, 3, 4, 5, 6, 7):
        v = per_welle_verdicts.get(welle, "NOT-EXEC")
        counts[v] = counts.get(v, 0) + 1
    if counts["NOT-EXEC"] == 7:
        return "NOT-READY"
    if counts["BLOCK"] >= 1:
        return "BLOCK"
    soft_fail = counts["CAUTION"] + counts["NOT-EXEC"]
    if soft_fail >= 3:
        return "BLOCK"
    if soft_fail >= 1:
        return "CAUTION"
    if counts["GREEN"] == 7:
        return "READY"
    return "BLOCK"


# ---------------------------------------------------------------------------
# Cross-coupling indicators
# ---------------------------------------------------------------------------


def cross_coupling_report(
    per_welle_verdicts: Mapping[int, str],
) -> list[dict]:
    """Return a list of per-pair coupling diagnostics."""
    out: list[dict] = []
    for a, b, label in CROSS_COUPLING_PAIRS:
        va = per_welle_verdicts.get(a, "NOT-EXEC")
        vb = per_welle_verdicts.get(b, "NOT-EXEC")
        coupled = va == vb
        # A pair is "drift" if one half is green and the other is not,
        # or one is BLOCK and the other isn't.
        drift = False
        if va != vb:
            if "BLOCK" in (va, vb):
                drift = True
            elif "GREEN" in (va, vb) and "NOT-EXEC" in (va, vb):
                drift = True
            elif (va == "GREEN" and vb == "CAUTION") or (
                vb == "GREEN" and va == "CAUTION"
            ):
                drift = True
        out.append(
            {
                "pair": [a, b],
                "label": label,
                "verdicts": {str(a): va, str(b): vb},
                "coupled": coupled,
                "drift": drift,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Envelope build + markdown rendering
# ---------------------------------------------------------------------------


def _load_per_welle_envelopes(probe_dir: Path) -> dict[int, dict]:
    """Load any ``welle-N.json`` files from ``probe_dir`` (sparse OK)."""
    envelopes: dict[int, dict] = {}
    if not probe_dir.is_dir():
        return envelopes
    for welle in (1, 2, 3, 4, 5, 6, 7):
        p = probe_dir / f"welle-{welle}.json"
        if not p.is_file():
            continue
        try:
            envelopes[welle] = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # A corrupt envelope is a BLOCK signal; record it.
            envelopes[welle] = {
                "verdict": "BLOCK",
                "details": f"envelope-corrupt: {p}",
                "verdict_source": "envelope-corrupt",
            }
    return envelopes


def build_envelope(
    probe_envelopes: Mapping[int, Mapping],
    *,
    github_env: Mapping[str, str] | None = None,
) -> dict:
    github_env = github_env or {}
    normalised: dict[int, dict] = {}
    for welle in (1, 2, 3, 4, 5, 6, 7):
        env = probe_envelopes.get(welle)
        if env is None:
            # Probe didn't write an envelope -> NOT-EXEC default.
            env = {
                "verdict": "NOT-EXEC",
                "details": "probe-envelope-missing",
                "verdict_source": "absent",
                "probe_present": False,
                "exit_code": None,
            }
        normalised[welle] = _normalise_envelope(welle, env)

    per_welle_verdicts = {w: normalised[w]["verdict"] for w in normalised}
    marathon = decide_marathon(per_welle_verdicts)
    coupling = cross_coupling_report(per_welle_verdicts)

    counts = {v: 0 for v in VALID_VERDICTS}
    for v in per_welle_verdicts.values():
        counts[v] = counts.get(v, 0) + 1

    return {
        "schema_version": 1,
        "workflow": "phase-3c-pre-cutover-marathon-dashboard",
        "emitted_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "github_run_id": github_env.get("GITHUB_RUN_ID"),
        "github_sha": github_env.get("GITHUB_SHA"),
        "github_ref": github_env.get("GITHUB_REF"),
        "marathon_readiness": marathon,
        "welle_verdicts": [normalised[w] for w in (1, 2, 3, 4, 5, 6, 7)],
        "verdict_counts": counts,
        "cross_coupling": coupling,
        "calendar_plan": {
            "adr": "ADR-0066",
            "windows": [
                {"kw": 24, "welles": [1, 2], "mode": "parallel"},
                {"kw": 25, "welles": [3], "mode": "solo"},
                {"kw": 26, "welles": [4, 5], "mode": "parallel"},
                {"kw": 27, "welles": [6, 7], "mode": "parallel"},
            ],
        },
    }


def render_markdown(envelope: Mapping) -> str:
    """Render the marathon-dashboard as a GitHub Actions step-summary."""
    marathon = envelope["marathon_readiness"]
    lines: list[str] = []
    lines.append(
        f"## Phase-3c Pre-Cutover Marathon Dashboard: `{marathon}`"
    )
    lines.append("")
    lines.append(
        f"_Emitted: {envelope['emitted_at_utc']}_"
    )
    lines.append("")
    lines.append("### Per-Welle Verdicts")
    lines.append("")
    lines.append(
        "| Welle | Component | KW | Mode | Pair | Verdict | Probe present | Exit |"
    )
    lines.append(
        "|------:|-----------|---:|------|-----:|---------|---------------|-----:|"
    )
    for row in envelope["welle_verdicts"]:
        partner = (
            "-" if row["cutover_pair_partner"] is None
            else str(row["cutover_pair_partner"])
        )
        exit_code = "-" if row["exit_code"] is None else str(row["exit_code"])
        present = "yes" if row["probe_present"] else "no"
        lines.append(
            f"| {row['welle']} | `{row['component']}` "
            f"| {row['cutover_kw']} | {row['cutover_mode']} | {partner} "
            f"| `{row['verdict']}` | {present} | {exit_code} |"
        )
    lines.append("")
    lines.append("### Cross-Welle Coupling")
    lines.append("")
    lines.append("| Pair | Label | Verdicts | Drift |")
    lines.append("|------|-------|----------|------:|")
    for c in envelope["cross_coupling"]:
        a, b = c["pair"]
        va = c["verdicts"][str(a)]
        vb = c["verdicts"][str(b)]
        drift = "DRIFT" if c["drift"] else "ok"
        lines.append(
            f"| Welle-{a} + Welle-{b} | {c['label']} "
            f"| `{va}` / `{vb}` | {drift} |"
        )
    lines.append("")
    lines.append("### Cutover-Day Windows (ADR-0066)")
    lines.append("")
    lines.append("| Welle | Window (ISO-8601) |")
    lines.append("|------:|-------------------|")
    for row in envelope["welle_verdicts"]:
        lines.append(
            f"| {row['welle']} | `{row['cutover_day_window']}` |"
        )
    lines.append("")
    counts = envelope["verdict_counts"]
    lines.append(
        f"**Counts:** GREEN={counts.get('GREEN', 0)} "
        f"CAUTION={counts.get('CAUTION', 0)} "
        f"BLOCK={counts.get('BLOCK', 0)} "
        f"NOT-EXEC={counts.get('NOT-EXEC', 0)}"
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        description="Aggregate per-Welle marathon-probe envelopes."
    )
    p.add_argument(
        "--probe-dir",
        type=Path,
        required=True,
        help="Directory containing welle-N.json envelopes (1..7).",
    )
    p.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the marathon-readiness JSON envelope.",
    )
    p.add_argument(
        "--summary",
        type=Path,
        default=None,
        help="Path to write the rendered Markdown step-summary.",
    )
    p.add_argument(
        "--print-stdout",
        action="store_true",
        help="Also print the envelope JSON to stdout.",
    )
    args = p.parse_args(argv[1:])

    envelopes = _load_per_welle_envelopes(args.probe_dir)
    envelope = build_envelope(envelopes, github_env=os.environ)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(envelope, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.summary is not None:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(render_markdown(envelope), encoding="utf-8")
    if args.print_stdout:
        print(json.dumps(envelope, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
