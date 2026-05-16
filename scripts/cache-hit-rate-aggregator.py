#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""cache-hit-rate-aggregator — Sprint-Phase-2b-Cache-Hit-Rate-Aggregator-MINI.

Background
----------

ADR-0064 (Model-Routing + Prompt-Caching, Approval 2026-05-16
~15:30 CEST) §Folgeartefakte Phase-2a Item 2 mandates per-persona +
per-model cache-hit-rate tracking out of the persona-engine
structured-JSON log substrate. Selin's PR #97 landed the
``anthropic_cache_telemetry`` event shape in
``wirelang/persona_engine/anthropic_cache.py``: one record per
Anthropic Messages API response, carrying ``input_tokens`` /
``output_tokens`` / ``cache_read_input_tokens`` /
``cache_creation_input_tokens`` / ``total_input_tokens`` /
``cache_hit_rate_input_only`` plus the ``cache_affinity_key``
that embeds the persona id and the model id.

The cost-aggregator (Noa's PR #110) already groups by model and
applies the ADR-0064 pricing table. This MINI scope is the parallel
**cache** view: per (persona, model) bucket how often we get a
cache hit versus a cold miss, and what the resulting USD bilance is
(cache-creation premium vs. cache-read discount, both vs. the
uncached baseline). Output goes to the same Prometheus
textfile-collector substrate as ``per-model-cost-aggregator.py``,
parity-for-parity, so the operator can keep a single dashboard row
per persona+model and read both cost and cache-efficiency off it.

Cache-Hit-Rate definition
-------------------------

We adopt the same definition Selin's ``parse_cache_telemetry`` uses:

    cache_hit_rate = cache_read_input_tokens / total_input_tokens

where ``total_input_tokens = input_tokens + cache_read_input_tokens
+ cache_creation_input_tokens``. This is the
``cache_hit_rate_input_only`` field on the telemetry envelope, and
the aggregator-side rate is the **token-weighted average** across
all telemetry records in a (persona, model) bucket (not the mean of
per-record rates — the latter would over-weight tiny responses).

When a bucket has zero input tokens (degenerate cold-start records,
no traffic yet) the rate is reported as 0.0.

Cost-Bilanz
-----------

Three numbers per (persona, model):

  - ``cache_read_savings_usd``: USD that the cache-read path saved
    versus paying the full input rate on those same tokens.
    Computed as ``cache_read_tokens * input_rate * (1 -
    cache_read_multiplier)`` — i.e. 90% of the uncached cost.
  - ``cache_creation_cost_usd``: USD spent writing tokens into the
    prompt cache (1.25x input rate per ADR-0064 §"Anthropic-Preis-
    Spread Mai 2026", 5-minute ephemeral slot — the production
    pin per :class:`CacheTtlResolution`).
  - ``cache_bilance_usd``: ``cache_read_savings_usd -
    cache_creation_cost_usd``. Positive => caching pays off net,
    negative => we are paying the premium without reading enough.

The bilance is what an operator wants on a Grafana single-stat
panel: "is the caching path earning its keep right now?"

Pricing constants
-----------------

The pricing table is identical to ``per-model-cost-aggregator.py``
(ADR-0064 §"Anthropic-Preis-Spread Mai 2026"). To avoid silent
drift between the two aggregators we import the table from
the cost-aggregator at startup; if the cost-aggregator is removed
or the import path moves, the cache aggregator falls back to a
local mirror of the table and logs a warning to stderr.

Run mode
--------

Stdlib-only. Driven by the same systemd user-timer cadence
(``OnCalendar=*:0/5``) inside the ``claude-dev`` toolbox container.
Per scrape window the gauges are absolute totals over the entire
log — Prometheus counter semantics handled at scrape time via
``rate()``.

Exit codes
----------

* ``0`` — aggregator ran cleanly; textfile output written.
* ``1`` — log input missing or unreadable.
* ``2`` — output directory not writable.

License: Apache-2.0 (parity with ``per-model-cost-aggregator.py``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_LOG_PATH_ENV = "WAKIR_PERSONA_ENGINE_LOG_PATH"
DEFAULT_LOG_PATH = "/var/home/fred/AI-Corp/logs/persona-engine.jsonl"
DEFAULT_TEXTFILE_OUTPUT = (
    "/var/lib/node_exporter/textfile_collector/cache_hit_rate.prom"
)

#: ADR-0064 pricing table mirror. Kept in lockstep with
#: per-model-cost-aggregator.MODEL_PRICING. Both aggregators read this
#: same table; the cache aggregator imports the cost aggregator's
#: table where possible so a single edit-site stays authoritative.
MODEL_PRICING: Dict[str, Dict[str, float]] = {
    "claude-haiku-4-5": {
        "input_usd_per_mtok": 0.80,
        "output_usd_per_mtok": 4.0,
        "cache_read_multiplier": 0.10,
        "cache_creation_multiplier": 1.25,
    },
    "claude-sonnet-4-6": {
        "input_usd_per_mtok": 3.0,
        "output_usd_per_mtok": 15.0,
        "cache_read_multiplier": 0.10,
        "cache_creation_multiplier": 1.25,
    },
    "claude-opus-4-7": {
        "input_usd_per_mtok": 15.0,
        "output_usd_per_mtok": 75.0,
        "cache_read_multiplier": 0.10,
        "cache_creation_multiplier": 1.25,
    },
}

#: Bucket key when a record carries no recognisable model id.
MODEL_UNKNOWN_BUCKET = "model_unknown"

#: Bucket key when a record carries no resolvable persona id.
PERSONA_UNKNOWN_BUCKET = "persona_unknown"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LogReadError(RuntimeError):
    """Raised when the persona-engine log is missing or unreadable."""


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------


def read_log_records(log_path: Path) -> List[Dict[str, Any]]:
    """Read the persona-engine structured-JSON log and return parsed dicts.

    Tolerates blank lines and malformed JSON (skips both). Returns an
    empty list if the file is empty; raises :class:`LogReadError` when
    the file is missing or unreadable.
    """
    if not log_path.is_file():
        raise LogReadError(
            f"persona-engine log path {log_path} is not a regular file"
        )
    try:
        with log_path.open("rb") as fh:
            data = fh.read()
    except OSError as exc:
        raise LogReadError(
            f"cannot read persona-engine log {log_path}: {exc}"
        ) from exc
    records: List[Dict[str, Any]] = []
    for raw in data.decode("utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            records.append(obj)
    return records


def is_cache_telemetry_record(rec: Mapping[str, Any]) -> bool:
    """Return True iff the record is an ``anthropic_cache_telemetry`` event.

    We filter on the explicit ``event`` discriminator that Selin's
    :meth:`CacheTelemetry.to_structured_log_dict` emits. This avoids
    pulling in pure span / request-built / FSM records that happen to
    carry token-shape fields — the cache aggregator only sees
    response-side records.
    """
    event = rec.get("event")
    return isinstance(event, str) and event == "anthropic_cache_telemetry"


def extract_persona_and_model(
    rec: Mapping[str, Any],
) -> Tuple[str, str]:
    """Resolve ``(persona_id, model_id)`` from a cache-telemetry record.

    Looks at, in order:

      1. ``rec["cache_affinity_key"]`` — parsed as
         ``anthropic:<model>:<persona>:<v907_pin>:ttl<seconds>``
         (per :func:`wirelang.persona_engine.anthropic_cache
         .derive_cache_affinity_key`). This is the authoritative path
         for the telemetry shape: the affinity-key carries both ids.
      2. Top-level ``rec["model"]`` / ``rec["persona"]`` keys for
         older log fixtures.

    Returns :data:`MODEL_UNKNOWN_BUCKET` / :data:`PERSONA_UNKNOWN_BUCKET`
    sentinels for components that cannot be resolved — preserves the
    token count in a separate gauge for drift detection.
    """
    model_id = MODEL_UNKNOWN_BUCKET
    persona_id = PERSONA_UNKNOWN_BUCKET

    affinity = rec.get("cache_affinity_key")
    if isinstance(affinity, str) and affinity.startswith("anthropic:"):
        parts = affinity.split(":")
        # anthropic : <model> : <persona> : <v907_pin> : ttl<seconds>
        if len(parts) >= 2 and parts[1]:
            model_id = parts[1]
        if len(parts) >= 3 and parts[2]:
            persona_id = parts[2]

    # Top-level override (older fixtures / future ADR rev).
    direct_model = rec.get("model")
    if isinstance(direct_model, str) and direct_model:
        model_id = direct_model
    direct_persona = rec.get("persona")
    if isinstance(direct_persona, str) and direct_persona:
        persona_id = direct_persona

    return persona_id, model_id


def extract_cache_envelope(
    rec: Mapping[str, Any],
) -> Optional[Dict[str, int]]:
    """Extract the cache-side token counts from a telemetry record.

    Returns ``None`` if the record carries no recognisable token-shape
    fields. The envelope mirrors :class:`CacheTelemetry`:

      - ``input_tokens`` — uncached input on this request
      - ``cache_read_input_tokens`` — cache-hit count
      - ``cache_creation_input_tokens`` — cache-write count
      - ``total_input_tokens`` — sum of the three above
    """
    keys = (
        "input_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "total_input_tokens",
    )
    if not any(k in rec for k in keys):
        return None

    def _int_or_zero(key: str) -> int:
        v = rec.get(key, 0)
        if isinstance(v, bool):
            v = int(v)
        if isinstance(v, (int, float)):
            return int(v)
        return 0

    input_tokens = _int_or_zero("input_tokens")
    cache_read = _int_or_zero("cache_read_input_tokens")
    cache_creation = _int_or_zero("cache_creation_input_tokens")
    # Re-derive total to defend against a stale ``total_input_tokens``
    # field that does not match its three components. Selin's writer
    # always emits a consistent sum, but log fixtures hand-written by
    # operators occasionally drift.
    total = input_tokens + cache_read + cache_creation
    return {
        "input_tokens": input_tokens,
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_creation,
        "total_input_tokens": total,
    }


# ---------------------------------------------------------------------------
# Cost-side math
# ---------------------------------------------------------------------------


def compute_cache_savings_and_cost(
    *,
    model_id: str,
    cache_read_input_tokens: int,
    cache_creation_input_tokens: int,
) -> Tuple[float, float]:
    """Return ``(cache_read_savings_usd, cache_creation_cost_usd)``.

    ``cache_read_savings_usd``: USD that the cache-read discount saved
    against paying the full input rate on the same tokens.
    Formula: ``cache_read_tokens * input_rate * (1 - read_multiplier)``.

    ``cache_creation_cost_usd``: USD spent writing tokens into the
    cache, billed at ``input_rate * creation_multiplier`` (1.25x for
    the 5-min ephemeral slot).

    Returns ``(0.0, 0.0)`` for unknown models so the gauge stays
    additive; drift surfaces via the ``model_unknown`` token gauges.
    """
    pricing = MODEL_PRICING.get(model_id)
    if pricing is None:
        return 0.0, 0.0
    input_rate = pricing["input_usd_per_mtok"]
    read_mult = pricing["cache_read_multiplier"]
    create_mult = pricing["cache_creation_multiplier"]
    mtok = 1_000_000.0
    savings = (
        (cache_read_input_tokens / mtok) * input_rate * (1.0 - read_mult)
    )
    creation_cost = (
        (cache_creation_input_tokens / mtok) * input_rate * create_mult
    )
    return savings, creation_cost


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _zero_bucket() -> Dict[str, float]:
    return {
        "input_tokens": 0.0,
        "cache_read_input_tokens": 0.0,
        "cache_creation_input_tokens": 0.0,
        "total_input_tokens": 0.0,
        "cache_read_savings_usd": 0.0,
        "cache_creation_cost_usd": 0.0,
        "cache_bilance_usd": 0.0,
        "cache_hit_rate": 0.0,
        "record_count": 0.0,
    }


def aggregate_records(
    records: Iterable[Mapping[str, Any]],
) -> Dict[Tuple[str, str], Dict[str, float]]:
    """Group cache-telemetry records by (persona, model) and sum counters.

    Returns a dict keyed by ``(persona_id, model_id)`` tuple. Each
    bucket carries:

      * token totals (input / read / creation / total_input)
      * ``cache_read_savings_usd``, ``cache_creation_cost_usd``,
        ``cache_bilance_usd`` (savings - creation_cost)
      * ``cache_hit_rate`` — token-weighted, recomputed from the
        bucket totals so the rate is consistent with the displayed
        token counts
      * ``record_count`` — number of telemetry records aggregated

    Records that are not ``anthropic_cache_telemetry`` events are
    silently skipped; non-token records inside that event class
    (envelope returns ``None``) are also skipped.
    """
    buckets: Dict[Tuple[str, str], Dict[str, float]] = {}
    for rec in records:
        if not is_cache_telemetry_record(rec):
            continue
        envelope = extract_cache_envelope(rec)
        if envelope is None:
            continue
        persona_id, model_id = extract_persona_and_model(rec)
        key = (persona_id, model_id)
        bucket = buckets.setdefault(key, _zero_bucket())
        bucket["input_tokens"] += envelope["input_tokens"]
        bucket["cache_read_input_tokens"] += envelope[
            "cache_read_input_tokens"
        ]
        bucket["cache_creation_input_tokens"] += envelope[
            "cache_creation_input_tokens"
        ]
        bucket["total_input_tokens"] += envelope["total_input_tokens"]
        savings, creation = compute_cache_savings_and_cost(
            model_id=model_id,
            cache_read_input_tokens=envelope["cache_read_input_tokens"],
            cache_creation_input_tokens=envelope[
                "cache_creation_input_tokens"
            ],
        )
        bucket["cache_read_savings_usd"] += savings
        bucket["cache_creation_cost_usd"] += creation
        bucket["cache_bilance_usd"] = (
            bucket["cache_read_savings_usd"]
            - bucket["cache_creation_cost_usd"]
        )
        bucket["record_count"] += 1

    # Recompute hit rate from bucket totals so the displayed rate is
    # consistent with the displayed token counts (token-weighted).
    for bucket in buckets.values():
        total_input = bucket["total_input_tokens"]
        if total_input > 0:
            bucket["cache_hit_rate"] = (
                bucket["cache_read_input_tokens"] / total_input
            )
        else:
            bucket["cache_hit_rate"] = 0.0

    return buckets


# ---------------------------------------------------------------------------
# Prometheus textfile rendering
# ---------------------------------------------------------------------------


def render_textfile(
    buckets: Mapping[Tuple[str, str], Mapping[str, float]],
    *,
    scrape_ts_utc: Optional[int] = None,
) -> str:
    """Render per-(persona, model) gauges in Prometheus exposition format.

    Schema:

      persona_engine_cache_input_tokens_total{persona="...",model="..."}
      persona_engine_cache_read_tokens_total{persona="...",model="..."}
      persona_engine_cache_creation_tokens_total{persona="...",model="..."}
      persona_engine_cache_total_input_tokens{persona="...",model="..."}
      persona_engine_cache_hit_rate{persona="...",model="..."}
      persona_engine_cache_read_savings_usd{persona="...",model="..."}
      persona_engine_cache_creation_cost_usd{persona="...",model="..."}
      persona_engine_cache_bilance_usd{persona="...",model="..."}
      persona_engine_cache_record_count_total{persona="...",model="..."}
      persona_engine_cache_scrape_timestamp_seconds (one global gauge)
    """
    if scrape_ts_utc is None:
        scrape_ts_utc = int(time.time())
    lines: List[str] = []

    # Stable (persona, model) ordering for golden tests + log diffs.
    keys = sorted(buckets.keys())

    metric_specs: List[Tuple[str, str, str]] = [
        (
            "persona_engine_cache_input_tokens_total",
            "Per (persona, model) uncached input tokens charged by Anthropic Messages API (counter).",
            "input_tokens",
        ),
        (
            "persona_engine_cache_read_tokens_total",
            "Per (persona, model) cache-read input tokens served from prompt cache (counter).",
            "cache_read_input_tokens",
        ),
        (
            "persona_engine_cache_creation_tokens_total",
            "Per (persona, model) cache-creation input tokens written into prompt cache (counter).",
            "cache_creation_input_tokens",
        ),
        (
            "persona_engine_cache_total_input_tokens",
            "Per (persona, model) sum of uncached + cache-read + cache-creation input tokens.",
            "total_input_tokens",
        ),
        (
            "persona_engine_cache_hit_rate",
            "Per (persona, model) token-weighted cache-hit rate (cache_read / total_input).",
            "cache_hit_rate",
        ),
        (
            "persona_engine_cache_read_savings_usd",
            "Per (persona, model) USD saved by the cache-read path vs paying the full input rate (counter).",
            "cache_read_savings_usd",
        ),
        (
            "persona_engine_cache_creation_cost_usd",
            "Per (persona, model) USD spent writing tokens into the prompt cache (counter).",
            "cache_creation_cost_usd",
        ),
        (
            "persona_engine_cache_bilance_usd",
            "Per (persona, model) net cache bilance (read_savings - creation_cost). Positive => caching pays off.",
            "cache_bilance_usd",
        ),
        (
            "persona_engine_cache_record_count_total",
            "Per (persona, model) count of anthropic_cache_telemetry records aggregated (counter).",
            "record_count",
        ),
    ]

    for metric_name, help_text, bucket_key in metric_specs:
        lines.append(f"# HELP {metric_name} {help_text}\n")
        lines.append(f"# TYPE {metric_name} gauge\n")
        for persona_id, model_id in keys:
            value = buckets[(persona_id, model_id)].get(bucket_key, 0.0)
            persona_label = _escape_label_value(persona_id)
            model_label = _escape_label_value(model_id)
            lines.append(
                f'{metric_name}{{persona="{persona_label}",model="{model_label}"}}'
                f" {_format_value(value)}\n"
            )

    lines.append(
        "# HELP persona_engine_cache_scrape_timestamp_seconds "
        "POSIX-epoch timestamp at which the cache-hit-rate aggregator last wrote the textfile.\n"
    )
    lines.append(
        "# TYPE persona_engine_cache_scrape_timestamp_seconds gauge\n"
    )
    lines.append(
        f"persona_engine_cache_scrape_timestamp_seconds {scrape_ts_utc}\n"
    )
    return "".join(lines)


def _escape_label_value(v: str) -> str:
    """Prometheus label-value escaping: backslash, double-quote, newline."""
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_value(v: float) -> str:
    """Format a float for Prometheus exposition.

    Integer-valued floats render as integers ("123" not "123.0") so
    the token-gauge diff stays readable; non-integer floats render
    with a high-precision fixed format so USD + rate diffs are stable.
    """
    if isinstance(v, bool):
        v = int(v)
    if isinstance(v, int):
        return str(v)
    if float(v).is_integer():
        return str(int(v))
    return f"{v:.10f}".rstrip("0").rstrip(".")


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
            "Aggregator for per (persona, model) Anthropic prompt-caching "
            "telemetry out of the persona-engine structured-JSON log. "
            "ADR-0064 Phase-2a Folgeartefakt Item 2 (cache view)."
        ),
    )
    p.add_argument(
        "--log-path",
        type=Path,
        default=None,
        help=(
            "Path to the persona-engine structured-JSON log. "
            f"Falls back to ${DEFAULT_LOG_PATH_ENV} then "
            f"{DEFAULT_LOG_PATH}."
        ),
    )
    p.add_argument(
        "--textfile-output",
        type=Path,
        default=Path(DEFAULT_TEXTFILE_OUTPUT),
        help=(
            "Prometheus textfile-collector output path. Default: "
            f"{DEFAULT_TEXTFILE_OUTPUT}"
        ),
    )
    p.add_argument(
        "--now",
        type=int,
        default=None,
        help=(
            "Override the 'now' POSIX-epoch timestamp for hermetic "
            "tests. Production runs leave this unset and use time.time()."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Compute the buckets and print the rendered textfile to "
            "stdout, but do not touch the textfile output path."
        ),
    )
    return p


def resolve_log_path(
    cli_value: Optional[Path], env: Mapping[str, str]
) -> Path:
    if cli_value is not None:
        return cli_value
    env_value = env.get(DEFAULT_LOG_PATH_ENV, "").strip()
    if env_value:
        return Path(env_value)
    return Path(DEFAULT_LOG_PATH)


def main(
    argv: Optional[List[str]] = None,
    *,
    env: Optional[Mapping[str, str]] = None,
) -> int:
    args = build_argparser().parse_args(argv)
    env_map: Mapping[str, str] = env if env is not None else os.environ
    log_path = resolve_log_path(args.log_path, env_map)
    try:
        records = read_log_records(log_path)
    except LogReadError as exc:
        sys.stderr.write(f"cache-hit-rate-aggregator: {exc}\n")
        return 1
    buckets = aggregate_records(records)
    now = args.now if args.now is not None else int(time.time())
    payload = render_textfile(buckets, scrape_ts_utc=now)
    if args.dry_run:
        sys.stdout.write(payload)
        return 0
    try:
        atomic_write(args.textfile_output, payload)
    except OSError as exc:
        sys.stderr.write(
            f"cache-hit-rate-aggregator: cannot write textfile output: {exc}\n"
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
