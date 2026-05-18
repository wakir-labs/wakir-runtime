#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cross-Welle Hot-Spot Aggregator -- Tag-49 (Tomas / Henrik-Pre-Mortem-Folge).

Purpose
-------

Tag-45 (PR #288) and Tag-48 (PR #312) shipped per-welle hot-spot probes
for Welle-3, Welle-4, Welle-5, Welle-6, Welle-7. Each probe emits a
``out/welle-N-hot-spot-verdict.json`` envelope and mirrors a per-day
copy into ``state/welle-N-hot-spot-trend/<yyyy-mm-dd>.json`` for
trend retention.

The five per-welle probes answer the question

    "Is Welle-N standing on its own four hot-spot axes today?"

but they do not answer the cross-welle question

    "Looking across all seven cutover Wellen, what is the marathon
     hot-spot picture for the KW-25..KW-27 window?"

This aggregator answers the cross-welle question. It walks the
five per-welle trend directories, reads each welle's most recent
verdict-envelope (within a configurable window), composes a
marathon-level rollup, transitively closes the per-welle
``cross_welle_propagation`` blocks, and emits a single
``out/cross-welle-hot-spot-verdict.json`` envelope.

For Welle-1 (``v907_verify``, cutover already complete at Tag-34 per
PR #230) and Welle-2 (``svid_workload_identity``, cutover complete
at Tag-35 per PR #234) no daily hot-spot probe exists -- those
wellen are post-cutover and tracked by the weekly
``phase-3c-welle-{1,2}-validation`` workflows. This aggregator
records them as ``post-cutover`` status when no trend envelope is
found, NOT as ``UNKNOWN`` / loud-failure.

Decision rule
-------------

Per-welle status (verdict carried over from the per-welle envelope):

* ``CLEAR``    -- per-welle verdict ``CLEAR``.
* ``CAUTION``  -- per-welle verdict ``CAUTION``.
* ``BLOCK``    -- per-welle verdict ``BLOCK``.
* ``UNKNOWN``  -- no trend envelope found within ``--max-age-days``
  (default 2 days). Loud-failure on the per-welle slot.
* ``POST-CUTOVER`` -- welle in ``--post-cutover-wellen`` set AND
  no trend envelope found. Not a failure mode; recorded for context.

Marathon aggregate verdict (across the five live wellen 3..7):

* ``CLEAR``    -- all live-welle slots ``CLEAR``.
* ``CAUTION``  -- one or more ``CAUTION`` slots, zero ``BLOCK``,
  zero ``UNKNOWN``.
* ``BLOCK``    -- any ``BLOCK`` slot OR any ``UNKNOWN`` slot
  (loud-failure on missing telemetry).

``POST-CUTOVER`` slots are excluded from the marathon aggregate but
listed in the envelope for transparency.

Cascade-fan-out
---------------

Each per-welle envelope may carry a ``cross_welle_propagation`` block
identifying ``pre_conditional_blocked`` downstream wellen. This
aggregator transitively closes the propagation:

    welle-3 BLOCK -> propagates to {4, 5, 7}
    welle-4 BLOCK -> propagates to {5, 7}
    welle-5 BLOCK -> propagates to {7}

So a Welle-3 BLOCK with audit-trail-integrity red yields a
cascade-fan-out of {4, 5, 7} (and transitively {7} from any
mid-chain Welle-4 or Welle-5 propagation). The envelope's
``cascade_fan_out`` field lists the union of all propagation targets
across all live-welle slots.

Top hot-spot ranking
--------------------

The five live wellen are ranked by hot-spot severity using a tuple
sort:

    (block-count desc, caution-count desc, downstream-fan-out-size desc,
     welle-number asc)

block-count and caution-count come from the per-welle envelope's
``counts`` field (number of red and yellow per-welle checks);
downstream-fan-out-size is the length of the ``pre_conditional_blocked``
list (zero when no propagation block fires).

The top-3 entries are surfaced on the envelope and in the Job-Summary
so a Mira-Hand-Sichtung sees which welle to deep-dive first.

Hermetic posture
----------------

stdlib only. No subprocess. No network. No file-system writes
outside ``--output`` and ``--notify-out``. Reads the per-welle
trend directories via ``pathlib``.

Output
------

* ``--output PATH`` -- write the cross-welle verdict-envelope JSON.
* ``--notify-out PATH`` -- when marathon verdict is ``BLOCK`` (every
  run) or transitions into ``CAUTION`` (vs ``--prev-verdict``),
  append one JSON-line notify-event. Append-mode; canonical
  ``state/notify-events.jsonl`` feed.

Exit code: always 0. The marathon ``verdict`` field carries the
BLOCK/CAUTION/CLEAR signal; the calling workflow translates that
to step-exit semantics.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping


# Wellen tracked by daily hot-spot probes (Tag-45 + Tag-48).
LIVE_WELLEN: tuple[int, ...] = (3, 4, 5, 6, 7)

# Wellen whose cutover is complete (no daily hot-spot probe expected).
# Tag-34: Welle-1 (v907_verify) per PR #230.
# Tag-35: Welle-2 (svid_workload_identity) per PR #234.
DEFAULT_POST_CUTOVER_WELLEN: tuple[int, ...] = (1, 2)

VALID_PER_WELLE_VERDICTS = ("CLEAR", "CAUTION", "BLOCK")
VALID_MARATHON_VERDICTS = ("CLEAR", "CAUTION", "BLOCK")


def _trend_dir(state_root: Path, welle: int) -> Path:
    return state_root / f"welle-{welle}-hot-spot-trend"


def _parse_date(name: str) -> date | None:
    """Parse a ``yyyy-mm-dd.json`` filename to a date; ``None`` on miss."""
    if not name.endswith(".json"):
        return None
    stem = name[: -len(".json")]
    try:
        return datetime.strptime(stem, "%Y-%m-%d").date()
    except ValueError:
        return None


def _newest_envelope(
    trend_dir: Path, today: date, max_age_days: int
) -> tuple[dict | None, date | None]:
    """Return ``(envelope, dated_at)`` for the newest trend file within
    ``max_age_days`` of ``today`` (inclusive).

    Returns ``(None, None)`` when no qualifying file exists or the dir
    is missing.
    """
    if not trend_dir.is_dir():
        return None, None
    cutoff = today - timedelta(days=max_age_days)
    best: tuple[date, Path] | None = None
    for entry in trend_dir.iterdir():
        if not entry.is_file():
            continue
        d = _parse_date(entry.name)
        if d is None:
            continue
        if d < cutoff or d > today:
            continue
        if best is None or d > best[0]:
            best = (d, entry)
    if best is None:
        return None, None
    try:
        envelope = json.loads(best[1].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    if not isinstance(envelope, dict):
        return None, None
    return envelope, best[0]


def _per_welle_slot(
    welle: int,
    envelope: dict | None,
    dated_at: date | None,
    post_cutover_wellen: Iterable[int],
) -> dict:
    """Build a per-welle slot for the marathon envelope."""
    if envelope is None:
        if welle in post_cutover_wellen:
            return {
                "welle": welle,
                "verdict": "POST-CUTOVER",
                "dated_at": None,
                "counts": None,
                "failed_checks": [],
                "propagation_targets": [],
                "envelope_source": None,
            }
        return {
            "welle": welle,
            "verdict": "UNKNOWN",
            "dated_at": None,
            "counts": None,
            "failed_checks": [],
            "propagation_targets": [],
            "envelope_source": None,
        }

    raw_verdict = (envelope.get("verdict") or "").strip().upper()
    if raw_verdict not in VALID_PER_WELLE_VERDICTS:
        # Loud-failure: a malformed verdict treated as UNKNOWN.
        raw_verdict = "UNKNOWN"

    counts = envelope.get("counts")
    if not isinstance(counts, dict):
        counts = None

    failed = envelope.get("failed_checks") or []
    if not isinstance(failed, list):
        failed = []

    prop = envelope.get("cross_welle_propagation")
    if isinstance(prop, dict):
        targets_raw = prop.get("pre_conditional_blocked") or []
    else:
        targets_raw = []
    targets: list[int] = []
    for t in targets_raw:
        try:
            targets.append(int(t))
        except (TypeError, ValueError):
            continue
    targets = sorted(set(targets))

    return {
        "welle": welle,
        "verdict": raw_verdict,
        "dated_at": dated_at.isoformat() if dated_at is not None else None,
        "counts": counts,
        "failed_checks": list(failed),
        "propagation_targets": targets,
        "envelope_source": envelope.get("workflow"),
    }


def decide_marathon(slots: list[dict]) -> str:
    """Compute the marathon aggregate verdict from live-welle slots.

    Excludes ``POST-CUTOVER`` slots. Any ``BLOCK`` or ``UNKNOWN``
    drives ``BLOCK``; any ``CAUTION`` (with no block) drives
    ``CAUTION``; otherwise ``CLEAR``.
    """
    has_block = False
    has_caution = False
    for s in slots:
        v = s.get("verdict")
        if v == "POST-CUTOVER":
            continue
        if v in ("BLOCK", "UNKNOWN"):
            has_block = True
        elif v == "CAUTION":
            has_caution = True
    if has_block:
        return "BLOCK"
    if has_caution:
        return "CAUTION"
    return "CLEAR"


def _transitive_closure(
    slots: list[dict],
) -> tuple[list[int], dict[int, list[int]]]:
    """Compute the transitive closure of propagation targets.

    Returns ``(union, per_seed)`` where ``union`` is the sorted list
    of all wellen reached by any BLOCK seed's propagation, and
    ``per_seed`` maps each BLOCK seed welle to its transitively-
    reached set.
    """
    edges: dict[int, set[int]] = {}
    for s in slots:
        edges[s["welle"]] = set(s.get("propagation_targets") or [])

    per_seed: dict[int, list[int]] = {}
    union: set[int] = set()
    for s in slots:
        if s.get("verdict") != "BLOCK":
            continue
        seed = s["welle"]
        # BFS over edges from the seed.
        reached: set[int] = set()
        frontier = list(edges.get(seed, set()))
        while frontier:
            nxt = frontier.pop()
            if nxt in reached:
                continue
            reached.add(nxt)
            for t in edges.get(nxt, set()):
                if t not in reached:
                    frontier.append(t)
        per_seed[seed] = sorted(reached)
        union |= reached
    return sorted(union), per_seed


def _rank(slots: list[dict]) -> list[dict]:
    """Return slots sorted by hot-spot severity (highest first).

    Sort key:
      ( -block-count, -caution-count, -fan-out-size, welle-number )

    ``POST-CUTOVER`` slots get a sentinel that sorts them to the end.
    """

    def key(s: dict) -> tuple[int, int, int, int]:
        if s.get("verdict") == "POST-CUTOVER":
            return (1, 0, 0, s["welle"])
        counts = s.get("counts") or {}
        red = int(counts.get("red") or 0) if isinstance(counts, dict) else 0
        yellow = (
            int(counts.get("yellow") or 0)
            if isinstance(counts, dict)
            else 0
        )
        fan = len(s.get("propagation_targets") or [])
        # Unknown is "worse than block" for ranking visibility -- it
        # signals stale telemetry; surface it on top.
        unknown_bonus = 1 if s.get("verdict") == "UNKNOWN" else 0
        # The numeric tuple sorts ascending; we negate the "more is
        # worse" axes so the highest severity sorts first.
        return (-(red + unknown_bonus), -yellow, -fan, s["welle"])

    return sorted(slots, key=key)


def build_envelope(
    today: date,
    state_root: Path,
    *,
    live_wellen: Iterable[int] = LIVE_WELLEN,
    post_cutover_wellen: Iterable[int] = DEFAULT_POST_CUTOVER_WELLEN,
    max_age_days: int = 2,
    env: Mapping[str, str] | None = None,
) -> dict:
    """Build the cross-welle marathon hot-spot verdict envelope."""
    env = env if env is not None else os.environ
    post_set = set(post_cutover_wellen)

    # Build per-welle slots for both live and post-cutover wellen.
    all_wellen = sorted(set(live_wellen) | post_set)
    slots: list[dict] = []
    for w in all_wellen:
        envelope, dated_at = _newest_envelope(
            _trend_dir(state_root, w), today, max_age_days
        )
        slots.append(_per_welle_slot(w, envelope, dated_at, post_set))

    live_slots = [s for s in slots if s["welle"] in set(live_wellen)]
    verdict = decide_marathon(live_slots)
    cascade_union, cascade_per_seed = _transitive_closure(live_slots)
    ranking = _rank(live_slots)

    counts_summary = {"CLEAR": 0, "CAUTION": 0, "BLOCK": 0, "UNKNOWN": 0}
    for s in live_slots:
        v = s.get("verdict")
        if v in counts_summary:
            counts_summary[v] += 1

    return {
        "schema_version": 1,
        "workflow": "cross-welle-hot-spot-aggregator",
        "emitted_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ),
        "today": today.isoformat(),
        "max_age_days": max_age_days,
        "live_wellen": list(live_wellen),
        "post_cutover_wellen": sorted(post_set),
        "github_run_id": env.get("GITHUB_RUN_ID"),
        "github_sha": env.get("GITHUB_SHA"),
        "github_ref": env.get("GITHUB_REF"),
        "verdict": verdict,
        "live_welle_counts": counts_summary,
        "per_welle_slots": slots,
        "cascade_fan_out": cascade_union,
        "cascade_fan_out_per_seed": {
            str(k): v for k, v in cascade_per_seed.items()
        },
        "top_hot_spots": [
            {
                "welle": s["welle"],
                "verdict": s["verdict"],
                "counts": s.get("counts"),
                "propagation_targets": s.get("propagation_targets") or [],
            }
            for s in ranking[:3]
        ],
        "ranking": [
            {"welle": s["welle"], "verdict": s["verdict"]}
            for s in ranking
        ],
        "cross_substrate_links": {
            "henrik_pre_mortem_inbox": (
                "agents-workspaces/mira/inbox/"
                "2026-05-18-henrik-tag-44-pre-mortem-done.md"
            ),
            "henrik_mitigation_map_inbox": (
                "agents-workspaces/mira/inbox/"
                "2026-05-18-tag-45-mitigation-map-deep-dives.md"
            ),
            "welle_3_hot_spot_workflow": (
                ".github/workflows/phase-3c-welle-3-hot-spot-probe.yml"
            ),
            "welle_4_hot_spot_workflow": (
                ".github/workflows/phase-3c-welle-4-hot-spot-probe.yml"
            ),
            "welle_5_hot_spot_workflow": (
                ".github/workflows/phase-3c-welle-5-hot-spot-probe.yml"
            ),
            "welle_6_hot_spot_workflow": (
                ".github/workflows/phase-3c-welle-6-hot-spot-probe.yml"
            ),
            "welle_7_hot_spot_workflow": (
                ".github/workflows/phase-3c-welle-7-hot-spot-probe.yml"
            ),
            "all_seven_daily_probe": (
                ".github/workflows/phase-3c-pre-cutover-daily-probe.yml"
            ),
        },
    }


def emit_notify_event(
    envelope: dict, notify_path: Path, prev_verdict: str | None
) -> bool:
    """Append a notify-event JSON-line when warranted.

    A notify-event fires when:
      * marathon verdict is BLOCK (every run -- forensic trail).
      * marathon verdict is CAUTION AND ``prev_verdict != "CAUTION"``
        (transition into CAUTION).

    Returns True if a line was appended, False otherwise.
    """
    verdict = envelope.get("verdict")
    if verdict not in ("BLOCK", "CAUTION"):
        return False
    if verdict == "CAUTION" and prev_verdict == "CAUTION":
        return False
    event = {
        "schema_version": 1,
        "kind": "cross-welle-hot-spot-aggregator",
        "emitted_at_utc": envelope.get("emitted_at_utc"),
        "today": envelope.get("today"),
        "verdict": verdict,
        "live_welle_counts": envelope.get("live_welle_counts"),
        "cascade_fan_out": envelope.get("cascade_fan_out"),
        "top_hot_spots": envelope.get("top_hot_spots"),
        "github_run_id": envelope.get("github_run_id"),
        "github_sha": envelope.get("github_sha"),
    }
    notify_path.parent.mkdir(parents=True, exist_ok=True)
    with notify_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")
    return True


def _parse_today(value: str | None) -> date:
    if not value:
        return datetime.now(timezone.utc).date()
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_int_list(raw: str | None, default: tuple[int, ...]) -> tuple[int, ...]:
    if raw is None or not raw.strip():
        return default
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError as e:
            raise argparse.ArgumentTypeError(
                f"invalid welle in list: {part!r}"
            ) from e
    return tuple(out)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Aggregate the five per-welle hot-spot verdicts into a "
            "single cross-welle marathon verdict envelope."
        )
    )
    p.add_argument(
        "--state-root",
        type=Path,
        default=Path("state"),
        help="Root directory containing the per-welle trend dirs "
        "(``welle-N-hot-spot-trend/``). Default: ./state",
    )
    p.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the cross-welle verdict envelope JSON.",
    )
    p.add_argument(
        "--notify-out",
        type=Path,
        default=None,
        help=(
            "Optional path for append-mode notify-events.jsonl. "
            "When marathon verdict is BLOCK (every run) or transitions "
            "into CAUTION, one JSON-line event is appended."
        ),
    )
    p.add_argument(
        "--prev-verdict",
        default=None,
        help=(
            "Previous run's marathon verdict (CLEAR|CAUTION|BLOCK) for "
            "the notify-event transition rule. Optional; default None."
        ),
    )
    p.add_argument(
        "--today",
        default=None,
        help="Override snapshot date (yyyy-mm-dd; default UTC today).",
    )
    p.add_argument(
        "--max-age-days",
        type=int,
        default=2,
        help=(
            "Maximum age (in days) of a per-welle trend envelope for "
            "it to count as live telemetry. Older envelopes are "
            "treated as missing. Default: 2."
        ),
    )
    p.add_argument(
        "--live-wellen",
        default=None,
        help=(
            "Comma-separated list of live (probed-daily) welle numbers."
            " Default: 3,4,5,6,7."
        ),
    )
    p.add_argument(
        "--post-cutover-wellen",
        default=None,
        help=(
            "Comma-separated list of welle numbers whose cutover is "
            "complete (no daily probe expected). Default: 1,2."
        ),
    )
    p.add_argument(
        "--print-stdout",
        action="store_true",
        help="Also print the envelope to stdout.",
    )
    args = p.parse_args(argv[1:])

    today = _parse_today(args.today)
    live_wellen = _parse_int_list(args.live_wellen, LIVE_WELLEN)
    post_cutover = _parse_int_list(
        args.post_cutover_wellen, DEFAULT_POST_CUTOVER_WELLEN
    )

    envelope = build_envelope(
        today,
        args.state_root,
        live_wellen=live_wellen,
        post_cutover_wellen=post_cutover,
        max_age_days=args.max_age_days,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(envelope, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if args.notify_out is not None:
        emit_notify_event(envelope, args.notify_out, args.prev_verdict)

    if args.print_stdout:
        print(json.dumps(envelope, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
