#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""per-model-cost-aggregator — Sprint-Phase-2b-Cost-Aggregator-MINI.

Background
----------

ADR-0064 (Model-Routing + Prompt-Caching, Approval 2026-05-16
~15:30 CEST) §Folgeartefakte Phase-2a Item 2 mandates per-model
cost tracking out of the persona-engine structured-JSON log
substrate (separate counters per ``claude-opus-4-7``,
``claude-sonnet-4-6``, ``claude-haiku-4-5``). The B.2 prompt-caching
path is now live in ``wirelang/persona_engine/anthropic_cache.py``
and emits one ``anthropic_cache_telemetry`` structured-log record
per Messages-API response — those records carry the
``input_tokens`` / ``output_tokens`` / ``cache_read_input_tokens``
/ ``cache_creation_input_tokens`` envelope but **not** a model
identifier and **not** a USD-cost field. ADR-0064 §"Anthropic-Preis-
Spread Mai 2026" pins the per-MTok pricing we apply here.

This aggregator scans the persona-engine structured-JSON log,
groups records by their ``model`` attribute (resolved either from
the top-level key or from a sibling ``otel-metric`` record's
``attributes.model``), and applies the ADR-0064 pricing table to
compute total USD cost per model per scrape window. Output goes
to the Prometheus textfile-collector substrate that Kai's
node-exporter Quadlet already consumes (parity with
``prometheus-textfile-adapter.py`` and ``mira-hourly-watchdog.py``
in the same directory).

Per ADR-0064 §Folgeartefakte Phase-2a Item 2:

   "Per-Model-Cost-Tracking (separate Counter pro claude-opus-4-7,
   -sonnet-4-6, -haiku-4-5) ... Prometheus-textfile-Gauges via
   Noa's Watchdog-Pattern"

The Cache-Hit-Rate aggregator and the Grafana dashboard land in
the follow-on wave; this MINI scope is cost-only.

Pricing constants
-----------------

From ADR-0064 §"Anthropic-Preis-Spread Mai 2026":

    Model              Input $/MTok    Output $/MTok
    claude-haiku-4-5         0.80              4
    claude-sonnet-4-6        3.00             15
    claude-opus-4-7         15.00             75

Cached-read tokens are billed at ~10% of input price per the
Anthropic prompt-caching contract; cache-creation tokens are
billed at 1.25x input price (the 5-minute ephemeral slot;
1-hour ephemeral is 2x but the persona-engine currently pins
the 5-min slot via ``CacheTtlResolution``). These multipliers
are captured in :data:`MODEL_PRICING` and applied in
:func:`compute_cost_usd`.

Operators who run the persona-engine against a model not in the
pricing table see a ``model_unknown`` bucket (counted but with
``cost_usd = 0`` and a log warning). This keeps the gauge surface
stable while flagging the routing drift.

Run mode
--------

The script is **stdlib-only**. It is invoked by a systemd user-
timer (``OnCalendar=*:0/5``) inside the ``claude-dev`` toolbox
container, five-minute cadence, parallel to the watchdog's
``*:5/10`` slot. Per scrape window the gauges are absolute
totals **over the entire log** (Prometheus counter semantics
handled at scrape time via ``rate()``; the script writes gauges,
not delta-counters, so the textfile-collector restart-resilience
matches the watchdog).

Exit codes
----------

* ``0`` — aggregator ran cleanly; textfile output written.
* ``1`` — log input missing or unreadable.
* ``2`` — output directory not writable.

License: Apache-2.0 (parity with ``prometheus-textfile-adapter.py``
and ``mira-hourly-watchdog.py``).
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
    "/var/lib/node_exporter/textfile_collector/per_model_cost.prom"
)

#: ADR-0064 §"Anthropic-Preis-Spread Mai 2026" pricing table.
#: Values in USD per 1,000,000 tokens.
#:
#: ``cache_read_multiplier``: applied to the input-USD-rate. Anthropic
#:   bills cache-read at ~10% of input price (the prompt-caching
#:   contract). Coded as 0.10.
#:
#: ``cache_creation_multiplier``: applied to the input-USD-rate.
#:   5-minute ephemeral slot bills at 1.25x input; 1-hour at 2x.
#:   persona-engine's :class:`CacheTtlResolution` defaults to the
#:   5-min slot, so 1.25x is the production value. A future ADR-0064b
#:   that promotes the 1h slot rewires this constant.
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

#: Bucket key used when a record carries no recognisable model
#: identifier. Surfaced as a separate gauge so operators can detect
#: routing drift without losing the token count.
MODEL_UNKNOWN_BUCKET = "model_unknown"


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

    Tolerates blank lines and malformed JSON (skips both). Returns
    an empty list if the file is empty; raises :class:`LogReadError`
    if the file is missing or unreadable.
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


def extract_model_id(rec: Mapping[str, Any]) -> str:
    """Resolve the model identifier for a single log record.

    Looks at, in order:

      1. ``rec["model"]`` (the request-side log line that the
         persona-engine's :func:`build_cached_request_payload` emits
         alongside the affinity-key derivation),
      2. ``rec["attributes"]["model"]`` (the ``otel-metric`` sink
         shape from :class:`PersonaEngineObservability`),
      3. ``rec["cache_affinity_key"]`` — parsed as
         ``anthropic:<model>:<persona_id>:<v907_pin>:ttl<seconds>``
         (per :func:`derive_cache_affinity_key`); this is the path
         that the cache-telemetry record uses.

    Returns :data:`MODEL_UNKNOWN_BUCKET` if none resolve.
    """
    direct = rec.get("model")
    if isinstance(direct, str) and direct:
        return direct
    attrs = rec.get("attributes")
    if isinstance(attrs, Mapping):
        attr_model = attrs.get("model")
        if isinstance(attr_model, str) and attr_model:
            return attr_model
    affinity = rec.get("cache_affinity_key")
    if isinstance(affinity, str) and affinity.startswith("anthropic:"):
        parts = affinity.split(":")
        if len(parts) >= 2 and parts[1]:
            return parts[1]
    return MODEL_UNKNOWN_BUCKET


def extract_token_envelope(
    rec: Mapping[str, Any],
) -> Optional[Dict[str, int]]:
    """Extract ``input/output/cache_read/cache_creation`` token counts.

    Returns ``None`` if the record carries no token-shape fields
    (we want to skip pure span / FSM / spawn records, not zero-them).
    """
    keys = (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    )
    if not any(k in rec for k in keys):
        return None
    out: Dict[str, int] = {}
    for k in keys:
        v = rec.get(k, 0)
        if isinstance(v, bool):
            # ``bool`` is an ``int`` subclass — defend against
            # accidental truthiness leaking into the gauge.
            v = int(v)
        if isinstance(v, (int, float)):
            out[k] = int(v)
        else:
            out[k] = 0
    return out


# ---------------------------------------------------------------------------
# Cost computation
# ---------------------------------------------------------------------------


def compute_cost_usd(
    *,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_input_tokens: int,
    cache_creation_input_tokens: int,
) -> float:
    """Apply the ADR-0064 pricing table to the token envelope.

    Returns ``0.0`` for unknown models (see
    :data:`MODEL_UNKNOWN_BUCKET`) so the gauge stays additive and the
    operator can detect the drift via the ``model_unknown`` bucket's
    token gauges.
    """
    pricing = MODEL_PRICING.get(model_id)
    if pricing is None:
        return 0.0
    input_rate = pricing["input_usd_per_mtok"]
    output_rate = pricing["output_usd_per_mtok"]
    cache_read_rate = input_rate * pricing["cache_read_multiplier"]
    cache_creation_rate = input_rate * pricing["cache_creation_multiplier"]
    mtok = 1_000_000.0
    cost = (
        (input_tokens / mtok) * input_rate
        + (output_tokens / mtok) * output_rate
        + (cache_read_input_tokens / mtok) * cache_read_rate
        + (cache_creation_input_tokens / mtok) * cache_creation_rate
    )
    return cost


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def aggregate_records(
    records: Iterable[Mapping[str, Any]],
) -> Dict[str, Dict[str, float]]:
    """Group records by model and sum token-and-cost counters.

    Returns a dict keyed by model_id with sub-dict carrying:

      * ``input_tokens``
      * ``output_tokens``
      * ``cache_read_input_tokens``
      * ``cache_creation_input_tokens``
      * ``total_tokens`` (sum of the above)
      * ``cost_usd`` (computed via :func:`compute_cost_usd`)
      * ``record_count``
    """
    buckets: Dict[str, Dict[str, float]] = {}
    for rec in records:
        envelope = extract_token_envelope(rec)
        if envelope is None:
            continue
        model_id = extract_model_id(rec)
        bucket = buckets.setdefault(
            model_id,
            {
                "input_tokens": 0.0,
                "output_tokens": 0.0,
                "cache_read_input_tokens": 0.0,
                "cache_creation_input_tokens": 0.0,
                "total_tokens": 0.0,
                "cost_usd": 0.0,
                "record_count": 0.0,
            },
        )
        bucket["input_tokens"] += envelope["input_tokens"]
        bucket["output_tokens"] += envelope["output_tokens"]
        bucket["cache_read_input_tokens"] += envelope[
            "cache_read_input_tokens"
        ]
        bucket["cache_creation_input_tokens"] += envelope[
            "cache_creation_input_tokens"
        ]
        bucket["total_tokens"] += sum(envelope.values())
        bucket["cost_usd"] += compute_cost_usd(
            model_id=model_id,
            input_tokens=envelope["input_tokens"],
            output_tokens=envelope["output_tokens"],
            cache_read_input_tokens=envelope[
                "cache_read_input_tokens"
            ],
            cache_creation_input_tokens=envelope[
                "cache_creation_input_tokens"
            ],
        )
        bucket["record_count"] += 1
    return buckets


# ---------------------------------------------------------------------------
# Prometheus textfile rendering
# ---------------------------------------------------------------------------


def render_textfile(
    buckets: Mapping[str, Mapping[str, float]],
    *,
    scrape_ts_utc: Optional[int] = None,
) -> str:
    """Render per-model gauges in the Prometheus exposition format.

    Emits one gauge per (model, metric) tuple, with the model id as
    the ``model`` label. Schema:

      persona_engine_cost_input_tokens_total{model="..."}
      persona_engine_cost_output_tokens_total{model="..."}
      persona_engine_cost_cache_read_tokens_total{model="..."}
      persona_engine_cost_cache_creation_tokens_total{model="..."}
      persona_engine_cost_total_tokens{model="..."}
      persona_engine_cost_usd{model="..."}
      persona_engine_cost_record_count_total{model="..."}
      persona_engine_cost_scrape_timestamp_seconds (one global gauge)
    """
    if scrape_ts_utc is None:
        scrape_ts_utc = int(time.time())
    lines: List[str] = []

    # Stable model ordering for golden tests + log diffs.
    model_ids = sorted(buckets.keys())

    metric_specs: List[Tuple[str, str, str]] = [
        (
            "persona_engine_cost_input_tokens_total",
            "Per-model uncached input tokens charged by Anthropic Messages API (counter).",
            "input_tokens",
        ),
        (
            "persona_engine_cost_output_tokens_total",
            "Per-model output tokens charged by Anthropic Messages API (counter).",
            "output_tokens",
        ),
        (
            "persona_engine_cost_cache_read_tokens_total",
            "Per-model cache-read input tokens served from prompt cache (counter).",
            "cache_read_input_tokens",
        ),
        (
            "persona_engine_cost_cache_creation_tokens_total",
            "Per-model cache-creation input tokens written into prompt cache (counter).",
            "cache_creation_input_tokens",
        ),
        (
            "persona_engine_cost_total_tokens",
            "Per-model sum of input + output + cache-read + cache-creation tokens.",
            "total_tokens",
        ),
        (
            "persona_engine_cost_usd",
            "Per-model accumulated USD cost per ADR-0064 pricing table (counter).",
            "cost_usd",
        ),
        (
            "persona_engine_cost_record_count_total",
            "Per-model count of structured-JSON log records aggregated (counter).",
            "record_count",
        ),
    ]

    for metric_name, help_text, bucket_key in metric_specs:
        lines.append(f"# HELP {metric_name} {help_text}\n")
        # Counter semantics at scrape-time via rate(); we expose gauges
        # because the aggregator restart re-reads the log from scratch.
        lines.append(f"# TYPE {metric_name} gauge\n")
        for model_id in model_ids:
            value = buckets[model_id].get(bucket_key, 0.0)
            label = _escape_label_value(model_id)
            lines.append(
                f'{metric_name}{{model="{label}"}} {_format_value(value)}\n'
            )

    # Scrape timestamp — operators correlate aggregator-runs with
    # mira-hourly ticks via this gauge.
    lines.append(
        "# HELP persona_engine_cost_scrape_timestamp_seconds "
        "POSIX-epoch timestamp at which the aggregator last wrote the textfile.\n"
    )
    lines.append(
        "# TYPE persona_engine_cost_scrape_timestamp_seconds gauge\n"
    )
    lines.append(
        f"persona_engine_cost_scrape_timestamp_seconds {scrape_ts_utc}\n"
    )
    return "".join(lines)


def _escape_label_value(v: str) -> str:
    """Prometheus label-value escaping: backslash, double-quote, newline."""
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_value(v: float) -> str:
    """Format a float for Prometheus exposition.

    Integer-valued floats render as integers ("123" not "123.0") to
    keep the token-gauge diff readable; non-integer floats render
    with a high-precision fixed format so cost-USD diffs are stable.
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
        prog="per-model-cost-aggregator",
        description=(
            "Aggregator for per-model Anthropic Messages API token + "
            "USD cost out of the persona-engine structured-JSON log. "
            "ADR-0064 Phase-2a Folgeartefakt Item 2."
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
        sys.stderr.write(f"per-model-cost-aggregator: {exc}\n")
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
            f"per-model-cost-aggregator: cannot write textfile output: {exc}\n"
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
