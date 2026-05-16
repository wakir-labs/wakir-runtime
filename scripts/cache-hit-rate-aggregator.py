#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""cache-hit-rate-aggregator — Sprint-SRE Phase-2b (Noa Bergstroem / SRE).

Background
----------

ADR-0064 Phase-2b §"Folgeartefakte Item 3" requires the cache-hit-rate
heatmap as the empirical anchor for the Phase-2 telemetry-auswertung.
The cache-creation-cost-vs-read-savings balance is the deciding
quantity for whether prompt-caching is *net* cost-positive on a given
persona+model combination — if cache-creation cost exceeds the
cache-read-savings over the 2-week window, the breakpoint placement
is mis-tuned for that surface (Persona-Def too short, TTL too short
relative to inter-call cadence, or the prefix changes too often to
retain cache affinity).

PR #97 (Selin, Sprint-Pengine-14) added the
``anthropic_cache_telemetry`` structured-log event in
``wirelang/persona_engine/anthropic_cache.py``. Each event carries:

    {
      "event": "anthropic_cache_telemetry",
      "cache_affinity_key": "anthropic:<model>:<persona_id>:<v907_pin>:ttl<N>",
      "input_tokens": <int>,
      "output_tokens": <int>,
      "cache_read_input_tokens": <int>,
      "cache_creation_input_tokens": <int>,
      "total_input_tokens": <int>,
      "cache_hit_rate_input_only": <float>,
      "cache_ephemeral_5m_input_tokens": <int|null>,
      "cache_ephemeral_1h_input_tokens": <int|null>
    }

The aggregator parses the ``cache_affinity_key`` to extract model and
persona-id, accumulates token counts per (persona_id, model) tuple
across the window, and emits Prometheus gauges that the Phase-2b
dashboard renders as a heatmap.

Cache-cost-vs-savings calculation
---------------------------------

Anthropic's prompt-caching pricing (URL-200-stamped 2026-05-16 via
https://docs.claude.com/en/docs/build-with-claude/prompt-caching):

* Cache writes cost ~125% of the base input-token rate (5-minute
  TTL) or ~200% (1-hour TTL).
* Cache reads cost ~10% of the base input-token rate.

The aggregator does NOT bake the base-rate-per-model dollar amounts
into the script — those live in per-model-cost-aggregator.py's
upstream source (mira-hourly-telemetry.jsonl ``costUSD`` field).
Instead it emits the **input-token counts** that the dashboard
multiplies by the per-model rate to render the dollar deltas. This
keeps the price-table out of the SRE substrate (per-token prices
change quarterly; price-update would require a code release if the
rates were hard-coded here).

Pipeline
--------

::

    persona-engine.log (jsonl)  ─>  cache-hit-rate-aggregator.py
                                                 │
                                                 v
                            /var/lib/node_exporter/textfile_collector/
                            wakir_cache_hit_rate.prom

Run mode
--------

The script is **stdlib-only**. It runs under systemd as a separate
``oneshot`` timer (``OnCalendar=*:0/5``).

Emitted gauges
--------------

* ``wakir_cache_hit_rate_input_only{persona_id="<p>",model="<m>"}``
  — last-known cache_hit_rate_input_only ratio for the (persona,
  model) tuple. Aggregator picks the most recent event in the
  window per tuple (telemetry already carries the ratio per call).
* ``wakir_cache_hit_rate_window_average{persona_id="<p>",model="<m>"}``
  — window-average hit-rate computed as
  ``sum(cache_read) / sum(cache_read + cache_creation + input)``
  across all events in the read window.
* ``wakir_cache_read_input_tokens_total{persona_id="<p>",model="<m>"}``
  — cumulative cache-read input tokens (the savings side).
* ``wakir_cache_creation_input_tokens_total{persona_id="<p>",model="<m>"}``
  — cumulative cache-creation input tokens (the cost side).
* ``wakir_cache_ephemeral_5m_input_tokens_total{persona_id="<p>",model="<m>"}``
  — cumulative 5-minute-slot cache-creation input tokens.
* ``wakir_cache_ephemeral_1h_input_tokens_total{persona_id="<p>",model="<m>"}``
  — cumulative 1-hour-slot cache-creation input tokens.
* ``wakir_cache_telemetry_event_count_total{persona_id="<p>",model="<m>"}``
  — number of ``anthropic_cache_telemetry`` events observed per tuple.
* ``wakir_cache_aggregator_last_run_unixtime`` — POSIX-epoch
  timestamp of the most recent aggregator run.
* ``wakir_cache_aggregator_records_consumed_total`` — sanity counter
  of events read.

Exit codes
----------

* ``0`` — aggregator ran cleanly; textfile output written.
* ``1`` — telemetry input present but unreadable / malformed.
* ``2`` — output directory not writable.

License: Apache-2.0.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_PERSONA_ENGINE_LOG = (
    "/var/home/fred/AI-Corp/infra/persona-engine-telemetry.jsonl"
)
DEFAULT_TEXTFILE_OUTPUT = (
    "/var/lib/node_exporter/textfile_collector/wakir_cache_hit_rate.prom"
)
DEFAULT_MAX_RECORDS = 8192  # ~5 days of cache-events at one per minute

#: The cache_affinity_key format defined in
#: wirelang/persona_engine/anthropic_cache.py:
#:    anthropic:<model>:<persona_id>:<v907_pin>:ttl<seconds>
#: We split on ':' from the left up to four times so persona_id may
#: contain dashes / underscores but MUST NOT contain ':'. The 5-segment
#: shape is the only one the aggregator recognises.
CACHE_AFFINITY_KEY_PROVIDER_PREFIX = "anthropic:"

#: The structured-log event name the aggregator listens for.
TELEMETRY_EVENT_NAME = "anthropic_cache_telemetry"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class TelemetryError(RuntimeError):
    """Raised when the persona-engine telemetry source is unreadable."""


# ---------------------------------------------------------------------------
# Cache-affinity-key parsing
# ---------------------------------------------------------------------------


def parse_cache_affinity_key(key: str) -> Optional[Tuple[str, str]]:
    """Parse an Anthropic cache-affinity-key string.

    Returns a ``(model, persona_id)`` tuple, or ``None`` if the key
    does not match the documented 5-segment shape
    ``anthropic:<model>:<persona_id>:<v907_pin>:ttl<seconds>``.

    Format invariants enforced:

    - Starts with literal ``anthropic:`` (other provider prefixes
      should never appear in this aggregator's input but are silently
      ignored).
    - Has at least 5 ``:``-separated segments.
    - The fifth segment starts with literal ``ttl``.

    Persona-ids and model-ids that contain a ``:`` are NOT supported;
    the affinity-key contract in ``anthropic_cache.py`` forbids them.
    """
    if not key or not isinstance(key, str):
        return None
    if not key.startswith(CACHE_AFFINITY_KEY_PROVIDER_PREFIX):
        return None
    segments = key.split(":")
    if len(segments) < 5:
        return None
    # segments[0] == "anthropic", segments[1] == model,
    # segments[2] == persona_id, segments[3] == v907_pin,
    # segments[4] starts with "ttl".
    if not segments[4].startswith("ttl"):
        return None
    model = segments[1]
    persona_id = segments[2]
    if not model or not persona_id:
        return None
    return (model, persona_id)


# ---------------------------------------------------------------------------
# Telemetry record parsing
# ---------------------------------------------------------------------------


def read_jsonl_tail(
    path: Path, *, max_records: int = DEFAULT_MAX_RECORDS
) -> List[Dict[str, Any]]:
    """Read the last ``max_records`` lines as parsed JSON dicts.

    Returns ``[]`` when the file does not exist (the persona-engine
    log may legitimately be absent before Sprint-Pengine-15 lands).
    Raises :class:`TelemetryError` only when the path exists but is
    unreadable.

    Tolerates blank lines and malformed JSON.
    """
    if not path.exists():
        return []
    if not path.is_file():
        raise TelemetryError(f"{path} exists but is not a regular file")
    try:
        with path.open("rb") as fh:
            data = fh.read()
    except OSError as exc:
        raise TelemetryError(f"cannot read {path}: {exc}") from exc
    raw_lines = data.decode("utf-8", errors="replace").splitlines()
    records: List[Dict[str, Any]] = []
    for raw in raw_lines[-max_records:]:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                records.append(obj)
        except json.JSONDecodeError:
            continue
    return records


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _empty_bucket() -> Dict[str, Any]:
    """Return a zero-initialised per-tuple cache accounting bucket."""
    return {
        "input_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_ephemeral_5m_input_tokens": 0,
        "cache_ephemeral_1h_input_tokens": 0,
        "event_count": 0,
        "last_hit_rate_input_only": 0.0,
    }


def aggregate_cache_telemetry(
    records: Iterable[Dict[str, Any]],
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Aggregate ``anthropic_cache_telemetry`` events per (persona, model).

    Records that don't match the expected event name or have an
    unparseable cache-affinity key are silently skipped; the caller
    can see the total consumed-record count via
    ``len(records_consumed)``.

    The ``last_hit_rate_input_only`` field is overwritten on each
    event (records are walked in order, so the final write is the
    most recent event in the window).
    """
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for rec in records:
        if rec.get("event") != TELEMETRY_EVENT_NAME:
            continue
        affinity_key = rec.get("cache_affinity_key")
        parsed = parse_cache_affinity_key(affinity_key)
        if parsed is None:
            continue
        model, persona_id = parsed
        key = (persona_id, model)
        bucket = out.setdefault(key, _empty_bucket())
        bucket["input_tokens"] += int(rec.get("input_tokens", 0) or 0)
        bucket["cache_read_input_tokens"] += int(
            rec.get("cache_read_input_tokens", 0) or 0
        )
        bucket["cache_creation_input_tokens"] += int(
            rec.get("cache_creation_input_tokens", 0) or 0
        )
        # Ephemeral slot breakdowns may be null in the older API
        # response shape — treat null as zero contribution.
        eph_5m = rec.get("cache_ephemeral_5m_input_tokens")
        eph_1h = rec.get("cache_ephemeral_1h_input_tokens")
        if isinstance(eph_5m, int):
            bucket["cache_ephemeral_5m_input_tokens"] += eph_5m
        if isinstance(eph_1h, int):
            bucket["cache_ephemeral_1h_input_tokens"] += eph_1h
        bucket["event_count"] += 1
        hit_rate = rec.get("cache_hit_rate_input_only")
        if isinstance(hit_rate, (int, float)):
            bucket["last_hit_rate_input_only"] = float(hit_rate)
    return out


def compute_window_average_hit_rate(bucket: Dict[str, Any]) -> float:
    """Compute the window-average input-only cache hit-rate for a bucket.

    Mirrors the formula in
    ``wirelang.persona_engine.anthropic_cache.parse_cache_telemetry``:

        cache_read / (input + cache_read + cache_creation)

    Returns 0.0 when the denominator is zero (degenerate window with
    no input tokens at all).
    """
    denom = (
        bucket["input_tokens"]
        + bucket["cache_read_input_tokens"]
        + bucket["cache_creation_input_tokens"]
    )
    if denom <= 0:
        return 0.0
    return bucket["cache_read_input_tokens"] / denom


# ---------------------------------------------------------------------------
# Prometheus textfile rendering
# ---------------------------------------------------------------------------


def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _render_metric_block(
    *,
    metric_name: str,
    help_text: str,
    metric_type: str,
    rows: List[Tuple[Dict[str, str], float]],
) -> str:
    lines: List[str] = []
    lines.append(f"# HELP {metric_name} {help_text}\n")
    lines.append(f"# TYPE {metric_name} {metric_type}\n")
    for labels, value in sorted(
        rows, key=lambda kv: tuple(sorted(kv[0].items()))
    ):
        if labels:
            rendered = ",".join(
                f'{k}="{_escape_label_value(v)}"'
                for k, v in sorted(labels.items())
            )
            lines.append(f"{metric_name}{{{rendered}}} {value}\n")
        else:
            lines.append(f"{metric_name} {value}\n")
    return "".join(lines)


def render_textfile(
    *,
    per_tuple: Dict[Tuple[str, str], Dict[str, Any]],
    records_consumed: int,
    now_unixtime: int,
) -> str:
    """Render the full Prometheus textfile payload."""
    blocks: List[str] = []

    rows_hit_rate: List[Tuple[Dict[str, str], float]] = []
    rows_window_avg: List[Tuple[Dict[str, str], float]] = []
    rows_cache_read: List[Tuple[Dict[str, str], float]] = []
    rows_cache_creation: List[Tuple[Dict[str, str], float]] = []
    rows_eph_5m: List[Tuple[Dict[str, str], float]] = []
    rows_eph_1h: List[Tuple[Dict[str, str], float]] = []
    rows_event_count: List[Tuple[Dict[str, str], float]] = []

    for (persona_id, model), bucket in per_tuple.items():
        labels = {"persona_id": persona_id, "model": model}
        rows_hit_rate.append(
            (labels, float(bucket["last_hit_rate_input_only"]))
        )
        rows_window_avg.append(
            (labels, compute_window_average_hit_rate(bucket))
        )
        rows_cache_read.append(
            (labels, float(bucket["cache_read_input_tokens"]))
        )
        rows_cache_creation.append(
            (labels, float(bucket["cache_creation_input_tokens"]))
        )
        rows_eph_5m.append(
            (labels, float(bucket["cache_ephemeral_5m_input_tokens"]))
        )
        rows_eph_1h.append(
            (labels, float(bucket["cache_ephemeral_1h_input_tokens"]))
        )
        rows_event_count.append((labels, float(bucket["event_count"])))

    blocks.append(
        _render_metric_block(
            metric_name="wakir_cache_hit_rate_input_only",
            help_text=(
                "Most recent input-only cache-hit-rate ratio per "
                "(persona_id, model) tuple"
            ),
            metric_type="gauge",
            rows=rows_hit_rate,
        )
    )
    blocks.append(
        _render_metric_block(
            metric_name="wakir_cache_hit_rate_window_average",
            help_text=(
                "Window-average input-only cache-hit-rate "
                "(cache_read / (input + cache_read + cache_creation)) "
                "per (persona_id, model)"
            ),
            metric_type="gauge",
            rows=rows_window_avg,
        )
    )
    blocks.append(
        _render_metric_block(
            metric_name="wakir_cache_read_input_tokens_total",
            help_text=(
                "Cumulative cache-read input tokens (savings side) "
                "per (persona_id, model)"
            ),
            metric_type="gauge",
            rows=rows_cache_read,
        )
    )
    blocks.append(
        _render_metric_block(
            metric_name="wakir_cache_creation_input_tokens_total",
            help_text=(
                "Cumulative cache-creation input tokens (cost side) "
                "per (persona_id, model)"
            ),
            metric_type="gauge",
            rows=rows_cache_creation,
        )
    )
    blocks.append(
        _render_metric_block(
            metric_name="wakir_cache_ephemeral_5m_input_tokens_total",
            help_text=(
                "Cumulative 5-minute-slot cache-creation input tokens "
                "per (persona_id, model)"
            ),
            metric_type="gauge",
            rows=rows_eph_5m,
        )
    )
    blocks.append(
        _render_metric_block(
            metric_name="wakir_cache_ephemeral_1h_input_tokens_total",
            help_text=(
                "Cumulative 1-hour-slot cache-creation input tokens "
                "per (persona_id, model)"
            ),
            metric_type="gauge",
            rows=rows_eph_1h,
        )
    )
    blocks.append(
        _render_metric_block(
            metric_name="wakir_cache_telemetry_event_count_total",
            help_text=(
                "Number of anthropic_cache_telemetry events observed "
                "per (persona_id, model)"
            ),
            metric_type="gauge",
            rows=rows_event_count,
        )
    )

    blocks.append(
        _render_metric_block(
            metric_name="wakir_cache_aggregator_records_consumed_total",
            help_text=(
                "Cache-telemetry records consumed on the last "
                "aggregator run"
            ),
            metric_type="gauge",
            rows=[({}, float(records_consumed))],
        )
    )
    blocks.append(
        _render_metric_block(
            metric_name="wakir_cache_aggregator_last_run_unixtime",
            help_text=(
                "POSIX-epoch timestamp of the most recent cache-hit-"
                "rate-aggregator invocation"
            ),
            metric_type="gauge",
            rows=[({}, float(now_unixtime))],
        )
    )

    return "".join(blocks)


def atomic_write(target: Path, payload: str) -> None:
    """Write ``payload`` to ``target`` atomically via os.replace."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=str(target.parent),
        prefix=target.name + ".",
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        tmp.write(payload)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, target)


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cache-hit-rate-aggregator",
        description=(
            "Aggregate Anthropic prompt-cache-hit-rate telemetry "
            "events emitted by wirelang/persona_engine/anthropic_"
            "cache.py into Prometheus textfile-collector gauges. "
            "ADR-0064 Phase-2b Folgeartefakte Item 3."
        ),
    )
    p.add_argument(
        "--persona-engine-log",
        type=Path,
        default=Path(DEFAULT_PERSONA_ENGINE_LOG),
        help=(
            "Path to the persona-engine structured-JSON-log carrying "
            "anthropic_cache_telemetry events. Missing file is tolerated. "
            f"Default: {DEFAULT_PERSONA_ENGINE_LOG}"
        ),
    )
    p.add_argument(
        "--textfile-output",
        type=Path,
        default=Path(DEFAULT_TEXTFILE_OUTPUT),
        help=(
            "Prometheus textfile-collector output path. "
            f"Default: {DEFAULT_TEXTFILE_OUTPUT}"
        ),
    )
    p.add_argument(
        "--max-records",
        type=int,
        default=DEFAULT_MAX_RECORDS,
        help=(
            "Tail-record limit. "
            f"Default: {DEFAULT_MAX_RECORDS}"
        ),
    )
    p.add_argument(
        "--now",
        type=int,
        default=None,
        help=(
            "Override the 'now' POSIX-epoch timestamp for hermetic "
            "tests. Production leaves this unset (uses time.time())."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Compute the result and print to stdout, but do not "
            "write the textfile output."
        ),
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_argparser().parse_args(argv)
    try:
        records = read_jsonl_tail(
            args.persona_engine_log, max_records=args.max_records
        )
    except TelemetryError as exc:
        sys.stderr.write(f"cache-hit-rate-aggregator: {exc}\n")
        return 1
    per_tuple = aggregate_cache_telemetry(records)
    now_unixtime = args.now if args.now is not None else int(time.time())
    payload = render_textfile(
        per_tuple=per_tuple,
        records_consumed=len(records),
        now_unixtime=now_unixtime,
    )
    if args.dry_run:
        sys.stdout.write(payload)
        return 0
    try:
        atomic_write(args.textfile_output, payload)
    except OSError as exc:
        sys.stderr.write(
            f"cache-hit-rate-aggregator: cannot write textfile: {exc}\n"
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
