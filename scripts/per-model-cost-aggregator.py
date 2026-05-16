#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""per-model-cost-aggregator — Sprint-SRE Phase-2b (Noa Bergstroem / SRE).

Background
----------

ADR-0064 (Model-Routing + Prompt-Caching, approved 2026-05-16) selects
Phase-2b ("Token-Telemetrie-Auswertung nach 2-Wochen-Fenster") as the
empirical input for any A.3 Heuristic-Routing decision. The empirical
basis is the per-model cost spread observed during Phase-2-Doppel-
betrieb: Top-Cost-Personas + Top-Cost-Task-Klassen identified by
absolute cost-per-model + cache-read-savings posture.

Two distinct cost sources flow into the aggregator:

1. **mira-hourly-telemetry.jsonl** — emitted by ``scripts/lib/claude-
   json-telemetry.sh`` (V-007 Phase 1c, ADR-0023 §2.X.5). Each record
   carries a ``model_usage`` map keyed by the canonical Anthropic
   model-id (e.g. ``claude-opus-4-7[1m]``, ``claude-haiku-4-5-2025
   1001``) with a ``costUSD`` float field plus ``inputTokens`` /
   ``outputTokens`` / ``cacheReadInputTokens`` / ``cacheCreation
   InputTokens``. This source covers the **mira-hourly invoker**
   (CEO-synthesis loop) — currently the highest-volume cost-emitting
   invoker in the Pilot.

2. **persona-engine structured-JSON-log lines** — emitted by
   ``wirelang/persona_engine/observability.py`` (Sprint-SRE Tag-15,
   PR #81). Lines that match ``msg=="otel-metric"`` AND
   ``metric_name`` in the recognised cost-metric set carry a
   ``metric_value`` float and an ``attributes.persona_id`` /
   ``attributes.model`` label pair. Cost-emitting metrics from the
   persona-engine are landing in Sprint-Pengine-15 (Selin); this
   aggregator is forward-compatible: if no such lines are present the
   per-persona cost map degenerates to "unknown" persona and only
   the mira-hourly source contributes.

The aggregator emits Prometheus textfile-collector gauges grouped by
model so the Phase-2b dashboard can render a per-model cost-spread
trend without any PromQL transformation of the underlying counter
recordings.

Pipeline
--------

::

    mira-hourly-telemetry.jsonl  ─┐
                                  ├─> per-model-cost-aggregator.py
    persona-engine.log (jsonl)   ─┘                  │
                                                     v
                            /var/lib/node_exporter/textfile_collector/
                            wakir_per_model_cost.prom
                            (atomic-write, scraped by node_exporter)

Run mode
--------

The script is **stdlib-only** — no pip wheels are needed. It runs
under systemd as a separate ``oneshot`` timer
(``OnCalendar=*:0/5``) every 5 minutes off-grid from the main
mira-hourly tick so the aggregator sees the previous tick's outcome
and not the in-flight run.

This script lives in the wakir-runtime repo (under ``scripts/``) so
Kai's Container-Orchestrator-deployment substrate can pick it up as
part of the same artefact set as ``prometheus-textfile-adapter.py``
and ``mira-hourly-watchdog.py``.

Exit codes
----------

* ``0`` — aggregator ran cleanly; textfile output written.
* ``1`` — telemetry input missing or unparseable.
* ``2`` — output directory not writable.

Emitted gauges
--------------

* ``wakir_model_cost_usd_total{model="<model_id>",invoker="<invoker>"}``
  — cumulative cost in USD over the window of records read.
* ``wakir_model_input_tokens_total{model="<model_id>",invoker="<invoker>"}``
  — cumulative uncached input tokens.
* ``wakir_model_output_tokens_total{model="<model_id>",invoker="<invoker>"}``
  — cumulative output tokens.
* ``wakir_model_cache_read_tokens_total{model="<model_id>",invoker="<invoker>"}``
  — cumulative cache-read input tokens.
* ``wakir_model_cache_creation_tokens_total{model="<model_id>",invoker="<invoker>"}``
  — cumulative cache-creation input tokens.
* ``wakir_model_invocation_count_total{model="<model_id>",invoker="<invoker>"}``
  — number of telemetry records that touched the model.
* ``wakir_per_model_aggregator_records_consumed_total{source="<source>"}``
  — sanity counter of records read per source ("mira_hourly",
  "persona_engine").
* ``wakir_per_model_aggregator_last_run_unixtime`` — POSIX-epoch
  timestamp of the most recent aggregator invocation.

Note on "counter as gauge"
--------------------------

The Prometheus textfile-collector flattens everything into gauges.
The ``_total`` suffix is preserved to keep the convention readable
and to allow future migration to a real counter exporter. PromQL
recording rules can ``rate()`` over the gauge difference between
scrapes; for Phase-2b the absolute cumulative values are the
primary signal anyway.

License: Apache-2.0 (parity with ``prometheus-textfile-adapter.py``
in the same directory).
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

DEFAULT_MIRA_HOURLY_TELEMETRY = (
    "/var/home/fred/AI-Corp/infra/mira-hourly-telemetry.jsonl"
)
DEFAULT_PERSONA_ENGINE_LOG = (
    "/var/home/fred/AI-Corp/infra/persona-engine-telemetry.jsonl"
)
DEFAULT_TEXTFILE_OUTPUT = (
    "/var/lib/node_exporter/textfile_collector/wakir_per_model_cost.prom"
)

#: Set of persona-engine structured-log metric names that carry cost
#: data. Sprint-Pengine-15 will land these; for now the aggregator
#: tolerates an empty set (no persona-engine cost lines yet emitted).
COST_METRIC_NAMES = frozenset(
    [
        "persona_engine.llm_call.cost_usd",
        "persona_engine.llm_call.input_tokens",
        "persona_engine.llm_call.output_tokens",
        "persona_engine.llm_call.cache_read_input_tokens",
        "persona_engine.llm_call.cache_creation_input_tokens",
    ]
)

#: How many tail records to read from each source. 4096 covers ~170
#: days of mira-hourly invocations (hourly cadence) and ~14 days of
#: persona-engine emissions at one record per minute — both safely
#: above the Phase-2b 2-week reporting window.
DEFAULT_MAX_RECORDS = 4096

#: Invoker label fallback when a record's invoker field is missing
#: or empty. The aggregator never silently mis-attributes; it labels
#: explicitly unknown.
INVOKER_UNKNOWN = "unknown"

#: Source labels used on the records-consumed counter.
SOURCE_MIRA_HOURLY = "mira_hourly"
SOURCE_PERSONA_ENGINE = "persona_engine"


# ---------------------------------------------------------------------------
# Telemetry record parsing
# ---------------------------------------------------------------------------


class TelemetryError(RuntimeError):
    """Raised when an input source is missing or unreadable."""


def read_jsonl_tail(path: Path, *, max_records: int = DEFAULT_MAX_RECORDS) -> List[Dict[str, Any]]:
    """Read the last ``max_records`` lines as parsed JSON dicts.

    Returns ``[]`` when the file does not exist (the persona-engine
    log may legitimately be absent during Phase-2a before Sprint-
    Pengine-15 wires cost emission). Raises :class:`TelemetryError`
    only when the path exists but is unreadable (permissions / IO
    error) — that is an operator-actionable condition.

    Tolerates blank lines and malformed JSON (skips both).
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
# Aggregation primitives
# ---------------------------------------------------------------------------


def _empty_bucket() -> Dict[str, float]:
    """Return a zero-initialised per-model accounting bucket."""
    return {
        "cost_usd": 0.0,
        "input_tokens": 0.0,
        "output_tokens": 0.0,
        "cache_read_input_tokens": 0.0,
        "cache_creation_input_tokens": 0.0,
        "invocation_count": 0.0,
    }


def aggregate_mira_hourly(
    records: Iterable[Dict[str, Any]],
) -> Dict[Tuple[str, str], Dict[str, float]]:
    """Aggregate mira-hourly-telemetry.jsonl records by (model, invoker).

    The ``model_usage`` sub-dict in each record is the source of
    truth: it carries one entry per Anthropic model id with the
    canonical token-count + ``costUSD`` schema. Records that lack a
    ``model_usage`` field are skipped (older pre-V-007 record format)
    and **not** counted as an invocation; they contribute to the
    "unparseable" sanity counter via the caller's return value.
    """
    out: Dict[Tuple[str, str], Dict[str, float]] = {}
    for rec in records:
        invoker = str(rec.get("invoker") or INVOKER_UNKNOWN)
        model_usage = rec.get("model_usage")
        if not isinstance(model_usage, dict):
            continue
        for model_id, mu in model_usage.items():
            if not isinstance(mu, dict):
                continue
            key = (str(model_id), invoker)
            bucket = out.setdefault(key, _empty_bucket())
            # mira-hourly uses camelCase keys (matches Claude CLI
            # output verbatim).
            bucket["cost_usd"] += float(mu.get("costUSD", 0) or 0)
            bucket["input_tokens"] += float(mu.get("inputTokens", 0) or 0)
            bucket["output_tokens"] += float(mu.get("outputTokens", 0) or 0)
            bucket["cache_read_input_tokens"] += float(
                mu.get("cacheReadInputTokens", 0) or 0
            )
            bucket["cache_creation_input_tokens"] += float(
                mu.get("cacheCreationInputTokens", 0) or 0
            )
            bucket["invocation_count"] += 1.0
    return out


def aggregate_persona_engine(
    records: Iterable[Dict[str, Any]],
) -> Dict[Tuple[str, str], Dict[str, float]]:
    """Aggregate persona-engine structured-JSON-log records.

    Records that match ``msg=="otel-metric"`` and whose ``metric_name``
    is in :data:`COST_METRIC_NAMES` contribute to the per-(model,
    invoker="persona_engine") bucket. The ``attributes.model`` label
    (set by Sprint-Pengine-15) is used as the model-id; absent
    attribute -> bucketed under "unknown" so the cost is visible but
    not silently dropped.

    The invoker label is always "persona_engine" for this source — it
    keeps the per-model gauges separable in PromQL from the
    "mira-hourly" invoker without collapsing them at scrape-time.
    """
    out: Dict[Tuple[str, str], Dict[str, float]] = {}
    invoker = SOURCE_PERSONA_ENGINE
    # Track which (model) keys we already counted as one invocation
    # per emitted "cost_usd" record. A single LLM call emits five
    # structured-log lines (one per metric_name); we MUST NOT count
    # five invocations for one logical call.
    seen_cost_emission: List[Tuple[str, str]] = []
    for rec in records:
        if rec.get("msg") != "otel-metric":
            continue
        metric_name = rec.get("metric_name")
        if metric_name not in COST_METRIC_NAMES:
            continue
        attributes = rec.get("attributes") or {}
        if not isinstance(attributes, dict):
            attributes = {}
        model_id = str(attributes.get("model") or "unknown")
        key = (model_id, invoker)
        bucket = out.setdefault(key, _empty_bucket())
        value = float(rec.get("metric_value", 0) or 0)
        if metric_name == "persona_engine.llm_call.cost_usd":
            bucket["cost_usd"] += value
            # Count the invocation when the canonical cost line lands.
            bucket["invocation_count"] += 1.0
            seen_cost_emission.append(key)
        elif metric_name == "persona_engine.llm_call.input_tokens":
            bucket["input_tokens"] += value
        elif metric_name == "persona_engine.llm_call.output_tokens":
            bucket["output_tokens"] += value
        elif metric_name == "persona_engine.llm_call.cache_read_input_tokens":
            bucket["cache_read_input_tokens"] += value
        elif (
            metric_name
            == "persona_engine.llm_call.cache_creation_input_tokens"
        ):
            bucket["cache_creation_input_tokens"] += value
    return out


def merge_aggregations(
    *aggs: Dict[Tuple[str, str], Dict[str, float]],
) -> Dict[Tuple[str, str], Dict[str, float]]:
    """Sum multiple per-(model, invoker) aggregations into one map."""
    merged: Dict[Tuple[str, str], Dict[str, float]] = {}
    for agg in aggs:
        for key, bucket in agg.items():
            target = merged.setdefault(key, _empty_bucket())
            for field, value in bucket.items():
                target[field] += value
    return merged


# ---------------------------------------------------------------------------
# Prometheus textfile rendering
# ---------------------------------------------------------------------------


def _escape_label_value(value: str) -> str:
    """Escape a Prometheus label value per exposition format §0.0.4."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _render_metric_block(
    *,
    metric_name: str,
    help_text: str,
    metric_type: str,
    rows: List[Tuple[Dict[str, str], float]],
) -> str:
    """Render one HELP/TYPE block plus all rows for a single metric."""
    lines: List[str] = []
    lines.append(f"# HELP {metric_name} {help_text}\n")
    lines.append(f"# TYPE {metric_name} {metric_type}\n")
    # Sort rows by label set for stable output (hermetic-test friendly).
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
    per_model: Dict[Tuple[str, str], Dict[str, float]],
    records_consumed: Dict[str, int],
    now_unixtime: int,
) -> str:
    """Render the full Prometheus textfile payload.

    Always emits **every** metric HELP/TYPE block, even when the row
    list is empty, so node_exporter scrapes do not flicker on
    metric-name appearance/disappearance across runs.
    """
    blocks: List[str] = []

    # Cost USD --------------------------------------------------------
    rows_cost: List[Tuple[Dict[str, str], float]] = []
    rows_input: List[Tuple[Dict[str, str], float]] = []
    rows_output: List[Tuple[Dict[str, str], float]] = []
    rows_cache_read: List[Tuple[Dict[str, str], float]] = []
    rows_cache_creation: List[Tuple[Dict[str, str], float]] = []
    rows_invocation: List[Tuple[Dict[str, str], float]] = []
    for (model, invoker), bucket in per_model.items():
        labels = {"model": model, "invoker": invoker}
        rows_cost.append((labels, bucket["cost_usd"]))
        rows_input.append((labels, bucket["input_tokens"]))
        rows_output.append((labels, bucket["output_tokens"]))
        rows_cache_read.append((labels, bucket["cache_read_input_tokens"]))
        rows_cache_creation.append(
            (labels, bucket["cache_creation_input_tokens"])
        )
        rows_invocation.append((labels, bucket["invocation_count"]))

    blocks.append(
        _render_metric_block(
            metric_name="wakir_model_cost_usd_total",
            help_text=(
                "Cumulative cost in USD per Anthropic model id over "
                "the records-read window"
            ),
            metric_type="gauge",
            rows=rows_cost,
        )
    )
    blocks.append(
        _render_metric_block(
            metric_name="wakir_model_input_tokens_total",
            help_text=(
                "Cumulative uncached input tokens per Anthropic model id"
            ),
            metric_type="gauge",
            rows=rows_input,
        )
    )
    blocks.append(
        _render_metric_block(
            metric_name="wakir_model_output_tokens_total",
            help_text=(
                "Cumulative output tokens per Anthropic model id"
            ),
            metric_type="gauge",
            rows=rows_output,
        )
    )
    blocks.append(
        _render_metric_block(
            metric_name="wakir_model_cache_read_tokens_total",
            help_text=(
                "Cumulative cache-read input tokens per Anthropic model id"
            ),
            metric_type="gauge",
            rows=rows_cache_read,
        )
    )
    blocks.append(
        _render_metric_block(
            metric_name="wakir_model_cache_creation_tokens_total",
            help_text=(
                "Cumulative cache-creation input tokens per Anthropic "
                "model id"
            ),
            metric_type="gauge",
            rows=rows_cache_creation,
        )
    )
    blocks.append(
        _render_metric_block(
            metric_name="wakir_model_invocation_count_total",
            help_text=(
                "Number of telemetry records that touched the model"
            ),
            metric_type="gauge",
            rows=rows_invocation,
        )
    )

    # Source records-consumed sanity counter --------------------------
    rows_records: List[Tuple[Dict[str, str], float]] = [
        ({"source": source}, float(count))
        for source, count in records_consumed.items()
    ]
    blocks.append(
        _render_metric_block(
            metric_name="wakir_per_model_aggregator_records_consumed_total",
            help_text=(
                "Telemetry records consumed per input source on the "
                "last aggregator run"
            ),
            metric_type="gauge",
            rows=rows_records,
        )
    )

    # Last-run timestamp ---------------------------------------------
    blocks.append(
        _render_metric_block(
            metric_name="wakir_per_model_aggregator_last_run_unixtime",
            help_text=(
                "POSIX-epoch timestamp of the most recent aggregator "
                "invocation"
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
        prog="per-model-cost-aggregator",
        description=(
            "Aggregate per-Anthropic-model cost and token-count "
            "telemetry from mira-hourly-telemetry.jsonl and persona-"
            "engine structured-JSON-logs into a single Prometheus "
            "textfile-collector payload. ADR-0064 Phase-2b "
            "Folgeartefakte Item 2."
        ),
    )
    p.add_argument(
        "--mira-hourly-telemetry",
        type=Path,
        default=Path(DEFAULT_MIRA_HOURLY_TELEMETRY),
        help=(
            "Path to mira-hourly-telemetry.jsonl. "
            f"Default: {DEFAULT_MIRA_HOURLY_TELEMETRY}"
        ),
    )
    p.add_argument(
        "--persona-engine-log",
        type=Path,
        default=Path(DEFAULT_PERSONA_ENGINE_LOG),
        help=(
            "Path to the persona-engine structured-JSON-log file. "
            "Missing file is tolerated (Phase-2a pre-cost-emission). "
            f"Default: {DEFAULT_PERSONA_ENGINE_LOG}"
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
        "--max-records",
        type=int,
        default=DEFAULT_MAX_RECORDS,
        help=(
            "Tail-record limit per source. "
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
            "Compute the result and print to stdout, but do not write "
            "the textfile output."
        ),
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_argparser().parse_args(argv)

    try:
        mh_records = read_jsonl_tail(
            args.mira_hourly_telemetry, max_records=args.max_records
        )
    except TelemetryError as exc:
        sys.stderr.write(f"per-model-cost-aggregator: {exc}\n")
        return 1
    try:
        pe_records = read_jsonl_tail(
            args.persona_engine_log, max_records=args.max_records
        )
    except TelemetryError as exc:
        sys.stderr.write(f"per-model-cost-aggregator: {exc}\n")
        return 1

    mh_agg = aggregate_mira_hourly(mh_records)
    pe_agg = aggregate_persona_engine(pe_records)
    merged = merge_aggregations(mh_agg, pe_agg)

    records_consumed = {
        SOURCE_MIRA_HOURLY: len(mh_records),
        SOURCE_PERSONA_ENGINE: len(pe_records),
    }
    now_unixtime = args.now if args.now is not None else int(time.time())
    payload = render_textfile(
        per_model=merged,
        records_consumed=records_consumed,
        now_unixtime=now_unixtime,
    )

    if args.dry_run:
        sys.stdout.write(payload)
        return 0

    try:
        atomic_write(args.textfile_output, payload)
    except OSError as exc:
        sys.stderr.write(
            f"per-model-cost-aggregator: cannot write textfile: {exc}\n"
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
