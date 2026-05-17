#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""routing-decision-observability — Tag-16 Routing-Decision-Aggregator (SRE).

Background
----------

ADR-0064 (Model-Routing + Prompt-Caching, Approval 2026-05-16 ~15:30
CEST) Phase-2b (PR #159 — heuristic-routing production-wiring) and
Phase-2c (Selin Tag-16 — LLM-classifier production-wiring) both
emit a per-decision JSONL record to the path configured via
``WAKIR_ROUTING_DECISION_JSONL``. The schema is documented in
``wirelang/persona_engine/anthropic_call.py``::

    {
        "timestamp": "<rfc3339>",
        "task_id": "<auftrag_id>",
        "mode": "static|heuristic|llm_classifier|llm_classifier_fallback_heuristic",
        "classified_class": "haiku|sonnet|opus|null",
        "chosen_model": "<model-id>|null",
        "decision_latency_us": <int>,
        "used_fallback": true,            # only when fallback path taken
        "fallback_reason": "<string>"     # only when fallback path taken
    }

This aggregator is the SRE-side observability surface on top of that
substrate. It is the **routing-decision parallel** to the existing
per-model **cost** aggregator (Noa PR #110) and per-(persona, model)
**cache** aggregator (Noa PR #112). Together those three views give
an operator a complete operational picture of the persona-engine hot
path: which model was chosen, how fast the decision ran, which
routing mode resolved it, and how often the classifier path resolved
without falling back. The companion Grafana dashboard is
``dashboards/persona-engine-routing-decisions.json``.

Sliding-window semantics
------------------------

Routing-decision JSONL grows unboundedly with traffic. For an
operational scrape we do not want to re-aggregate the whole file on
every tick — we want the **last N decisions** (most-recent records)
so the gauges reflect recent traffic, not the long-tail historical
average. The window size N is operator-tunable via the
``WAKIR_ROUTING_OBS_WINDOW`` env-var (default 1000). When the file
holds fewer than N records the whole file is aggregated; the
returned counts reflect the actual sample size, so an operator can
distinguish a "fresh-start" reading from a "saturated-window"
reading via the ``routing_decision_sample_size`` gauge.

The window is applied **after** parsing: we read the full file,
discard malformed lines, then keep the tail. This keeps the
implementation stdlib-only (no reverse-seek-by-byte gymnastics) at
the cost of one full-file read per scrape — operationally fine at
the cadence we expect (5-minute systemd-timer ticks, file sizes in
the low-MB range).

Cache-hit-rate semantics
------------------------

The routing-decision substrate does **not** carry an Anthropic
prompt-cache view (that lives in ``cache-hit-rate-aggregator.py``).
What we *can* measure off the routing-decision JSONL is the
**classifier-hit-rate**: of all decisions taken in a classifier mode
(``llm_classifier`` or ``llm_classifier_fallback_heuristic``), the
share that resolved **without** a fallback. A high rate means the
classifier path is doing its job; a low rate is an early warning
that the classifier backend is degrading and traffic is silently
landing on the heuristic-fallback path.

We expose this rate under the metric name
``persona_engine_routing_classifier_hit_rate`` (gauge, 0..1) plus
the underlying counts (``classifier_attempts_total``,
``classifier_fallbacks_total``) so an operator can compute a
window-anchored rate at scrape time. The dashboard Cache-Hit-Rate
gauge consumes this rate.

Aggregations
------------

The aggregator returns a single envelope dict with these top-level
keys:

  - ``sample_size``: number of decisions aggregated (0..N).
  - ``window_size``: configured N (so the dashboard can render
    "X of N decisions" copy without re-reading the env).
  - ``count_per_model``: dict ``{model_id -> int}`` of decision
    counts grouped by ``chosen_model``. ``null`` chosen-model
    records are bucketed under the sentinel ``model_unknown``.
  - ``count_per_mode``: dict ``{mode -> int}`` of decision counts
    grouped by ``mode``. Unknown modes are bucketed under
    ``mode_unknown``.
  - ``avg_decision_latency_us``: arithmetic mean over the window
    (float). Returns 0.0 for an empty sample.
  - ``latency_per_mode``: dict ``{mode -> {p50, p95, p99, count}}``
    with **nearest-rank percentile** semantics (stdlib-only,
    deterministic). ``p50/p95/p99`` are integers (microseconds);
    ``count`` is the per-mode sample size.
  - ``classifier_attempts``: count of decisions taken in a
    classifier mode (``llm_classifier`` ∪
    ``llm_classifier_fallback_heuristic``).
  - ``classifier_fallbacks``: count of those decisions where
    ``used_fallback`` is ``True``.
  - ``classifier_hit_rate``: ``1 - (fallbacks / attempts)``; 0.0
    when ``attempts == 0``.

Outputs
-------

The aggregator supports two output formats:

  - ``--format=json``: the envelope above written as a single JSON
    object. Operator-facing tools (jq, ad-hoc shell pipelines) read
    this. Default when stdout is a terminal.
  - ``--format=prometheus``: Prometheus exposition format suitable
    for the node-exporter textfile collector. Mirrors the parity
    contract used by ``per-model-cost-aggregator.py`` and
    ``cache-hit-rate-aggregator.py``.

The two formats expose the *same* numbers — the JSON form is for
operators and tests, the Prometheus form is for Grafana via the
existing textfile-collector substrate. The dashboard
``dashboards/persona-engine-routing-decisions.json`` consumes the
Prometheus gauges.

Run mode
--------

Stdlib-only (parity with the other observability scripts). Driven
by a 5-minute systemd-user-timer cadence inside the ``claude-dev``
toolbox container — the same substrate Kai already runs for the
cost + cache aggregators.

Exit codes
----------

* ``0`` — aggregator ran cleanly.
* ``1`` — routing-decision JSONL path missing or unreadable.
* ``2`` — textfile output directory not writable (Prometheus mode).

License: Apache-2.0 (parity with the sibling aggregators).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


# ---------------------------------------------------------------------------
# ENV contract + defaults
# ---------------------------------------------------------------------------

#: Env-var the persona-engine writes JSONL to (mirrors
#: ``wirelang.persona_engine.anthropic_call.WAKIR_ROUTING_DECISION_JSONL_ENV``).
WAKIR_ROUTING_DECISION_JSONL_ENV = "WAKIR_ROUTING_DECISION_JSONL"

#: Env-var the aggregator reads to size the sliding window.
WAKIR_ROUTING_OBS_WINDOW_ENV = "WAKIR_ROUTING_OBS_WINDOW"

#: Default sliding-window size when ``WAKIR_ROUTING_OBS_WINDOW`` is
#: unset or non-positive. Chosen to give a stable second-percentile
#: read on a 5-minute scrape window at typical Wakir-internal traffic.
DEFAULT_WINDOW_SIZE = 1000

#: Default textfile-collector output path (parity with
#: ``cache-hit-rate-aggregator.py``).
DEFAULT_TEXTFILE_OUTPUT = (
    "/var/lib/node_exporter/textfile_collector/routing_decisions.prom"
)

#: Routing modes per ADR-0064. Mirror of the constants in
#: ``wirelang.persona_engine.anthropic_call``. Kept locally so the
#: aggregator stays stdlib-only and does not import the package.
ROUTING_MODE_STATIC = "static"
ROUTING_MODE_HEURISTIC = "heuristic"
ROUTING_MODE_LLM_CLASSIFIER = "llm_classifier"
ROUTING_MODE_LLM_CLASSIFIER_FALLBACK_HEURISTIC = (
    "llm_classifier_fallback_heuristic"
)

KNOWN_ROUTING_MODES = (
    ROUTING_MODE_STATIC,
    ROUTING_MODE_HEURISTIC,
    ROUTING_MODE_LLM_CLASSIFIER,
    ROUTING_MODE_LLM_CLASSIFIER_FALLBACK_HEURISTIC,
)

#: Classifier-mode set — used to scope the classifier-hit-rate
#: numerator/denominator.
CLASSIFIER_MODES = frozenset(
    {
        ROUTING_MODE_LLM_CLASSIFIER,
        ROUTING_MODE_LLM_CLASSIFIER_FALLBACK_HEURISTIC,
    }
)

#: Bucket key for records whose ``chosen_model`` field is null /
#: missing. We do not silently drop these — drift surfaces in the
#: model-unknown gauge.
MODEL_UNKNOWN_BUCKET = "model_unknown"

#: Bucket key for records whose ``mode`` field is missing or not in
#: the ADR-0064 set. Same drift-surface property as the model bucket.
MODE_UNKNOWN_BUCKET = "mode_unknown"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class JsonlReadError(RuntimeError):
    """Raised when the routing-decision JSONL is missing or unreadable."""


# ---------------------------------------------------------------------------
# JSONL parsing + sliding-window selection
# ---------------------------------------------------------------------------


def read_decision_records(jsonl_path: Path) -> List[Dict[str, Any]]:
    """Parse the routing-decision JSONL into a list of dicts.

    Tolerates blank lines and malformed JSON (skips both). Returns an
    empty list when the file is empty; raises :class:`JsonlReadError`
    when the file is missing or unreadable. Mirrors the tolerance
    posture of the cost + cache aggregators.
    """
    if not jsonl_path.is_file():
        raise JsonlReadError(
            f"routing-decision JSONL {jsonl_path} is not a regular file"
        )
    try:
        with jsonl_path.open("rb") as fh:
            data = fh.read()
    except OSError as exc:
        raise JsonlReadError(
            f"cannot read routing-decision JSONL {jsonl_path}: {exc}"
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


def select_window(
    records: List[Dict[str, Any]], window_size: int
) -> List[Dict[str, Any]]:
    """Return the trailing ``window_size`` records (or all if shorter).

    A non-positive ``window_size`` is normalised to
    :data:`DEFAULT_WINDOW_SIZE` so a misconfigured env-var cannot
    silently disable windowing.
    """
    if window_size <= 0:
        window_size = DEFAULT_WINDOW_SIZE
    if len(records) <= window_size:
        return list(records)
    return records[-window_size:]


def read_window_size_from_env(env: Mapping[str, str]) -> int:
    """Return the configured window size from the env-map.

    Invalid values (non-int, <= 0) fall back to
    :data:`DEFAULT_WINDOW_SIZE`. The aggregator never raises on a
    bad env-var — operator misconfiguration must not break the
    metrics pipeline.
    """
    raw = env.get(WAKIR_ROUTING_OBS_WINDOW_ENV, "").strip()
    if not raw:
        return DEFAULT_WINDOW_SIZE
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_WINDOW_SIZE
    if value <= 0:
        return DEFAULT_WINDOW_SIZE
    return value


# ---------------------------------------------------------------------------
# Field extraction helpers
# ---------------------------------------------------------------------------


def _safe_str(value: Any, sentinel: str) -> str:
    """Coerce ``value`` to a non-empty str, falling back to ``sentinel``."""
    if isinstance(value, str) and value:
        return value
    return sentinel


def _safe_int_latency(value: Any) -> Optional[int]:
    """Return a non-negative int latency or ``None`` on bad input.

    Tolerates int and float (truncates). Rejects negatives and
    non-numeric types — operationally the substrate clamps to >=0,
    but we defend against fixture drift.
    """
    if isinstance(value, bool):
        # bool is an int subclass, but we do not want True == 1us.
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        ival = int(value)
        return ival if ival >= 0 else None
    return None


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _nearest_rank_percentile(
    sorted_values: List[int], pct: float
) -> int:
    """Compute a nearest-rank percentile from a sorted ``int`` list.

    Returns 0 for an empty list. Pct is in [0, 100]. The nearest-rank
    method (NIST) is preferred over linear interpolation here because
    we want a *real measured latency* on the dashboard, not an
    interpolated phantom value that no decision actually exhibited.
    """
    n = len(sorted_values)
    if n == 0:
        return 0
    # Clamp to [0, 100] defensively.
    pct = max(0.0, min(100.0, pct))
    # Nearest-rank: ceil(p/100 * n), 1-indexed → 0-indexed by -1.
    rank = max(1, math.ceil((pct / 100.0) * n))
    rank = min(rank, n)
    return sorted_values[rank - 1]


def aggregate_decisions(
    records: Iterable[Mapping[str, Any]], *, window_size: int
) -> Dict[str, Any]:
    """Aggregate a sequence of decision records into the envelope.

    See module docstring for the envelope schema. ``window_size`` is
    embedded into the envelope so downstream consumers can render
    "X of N" labels without re-reading the env-var.
    """
    records_list = list(records)
    sample = select_window(records_list, window_size)

    count_per_model: Dict[str, int] = {}
    count_per_mode: Dict[str, int] = {}
    latency_by_mode: Dict[str, List[int]] = {}
    latency_sum_us = 0
    latency_n = 0

    classifier_attempts = 0
    classifier_fallbacks = 0

    for rec in sample:
        model_id = _safe_str(rec.get("chosen_model"), MODEL_UNKNOWN_BUCKET)
        count_per_model[model_id] = count_per_model.get(model_id, 0) + 1

        raw_mode = rec.get("mode")
        mode = (
            raw_mode
            if isinstance(raw_mode, str) and raw_mode in KNOWN_ROUTING_MODES
            else MODE_UNKNOWN_BUCKET
        )
        count_per_mode[mode] = count_per_mode.get(mode, 0) + 1

        latency = _safe_int_latency(rec.get("decision_latency_us"))
        if latency is not None:
            latency_sum_us += latency
            latency_n += 1
            latency_by_mode.setdefault(mode, []).append(latency)

        if mode in CLASSIFIER_MODES:
            classifier_attempts += 1
            if rec.get("used_fallback") is True:
                classifier_fallbacks += 1

    avg_decision_latency_us = (
        latency_sum_us / latency_n if latency_n > 0 else 0.0
    )

    latency_per_mode: Dict[str, Dict[str, int]] = {}
    for mode, vals in latency_by_mode.items():
        vals_sorted = sorted(vals)
        latency_per_mode[mode] = {
            "p50": _nearest_rank_percentile(vals_sorted, 50.0),
            "p95": _nearest_rank_percentile(vals_sorted, 95.0),
            "p99": _nearest_rank_percentile(vals_sorted, 99.0),
            "count": len(vals_sorted),
        }

    if classifier_attempts > 0:
        classifier_hit_rate = (
            1.0 - (classifier_fallbacks / classifier_attempts)
        )
    else:
        classifier_hit_rate = 0.0

    return {
        "sample_size": len(sample),
        "window_size": window_size,
        "count_per_model": count_per_model,
        "count_per_mode": count_per_mode,
        "avg_decision_latency_us": avg_decision_latency_us,
        "latency_per_mode": latency_per_mode,
        "classifier_attempts": classifier_attempts,
        "classifier_fallbacks": classifier_fallbacks,
        "classifier_hit_rate": classifier_hit_rate,
    }


# ---------------------------------------------------------------------------
# Prometheus textfile rendering
# ---------------------------------------------------------------------------


def render_prometheus(
    envelope: Mapping[str, Any], *, scrape_ts_utc: Optional[int] = None
) -> str:
    """Render the envelope as Prometheus exposition text.

    Metric schema (all gauges — counters are conceptually counters
    but exposed as gauges in keeping with the textfile-collector
    posture of the sibling aggregators)::

        persona_engine_routing_decisions_sample_size
        persona_engine_routing_decisions_window_size
        persona_engine_routing_decisions_per_model{model="..."}
        persona_engine_routing_decisions_per_mode{mode="..."}
        persona_engine_routing_decision_latency_us_avg
        persona_engine_routing_decision_latency_us{mode="...",quantile="0.5|0.95|0.99"}
        persona_engine_routing_decision_count_per_mode{mode="..."}
        persona_engine_routing_classifier_attempts_total
        persona_engine_routing_classifier_fallbacks_total
        persona_engine_routing_classifier_hit_rate
        persona_engine_routing_scrape_timestamp_seconds
    """
    if scrape_ts_utc is None:
        scrape_ts_utc = int(time.time())
    lines: List[str] = []

    def _emit_help(name: str, help_text: str, mtype: str = "gauge") -> None:
        lines.append(f"# HELP {name} {help_text}\n")
        lines.append(f"# TYPE {name} {mtype}\n")

    _emit_help(
        "persona_engine_routing_decisions_sample_size",
        "Number of routing-decision records aggregated in the current window.",
    )
    lines.append(
        f"persona_engine_routing_decisions_sample_size {envelope['sample_size']}\n"
    )

    _emit_help(
        "persona_engine_routing_decisions_window_size",
        "Configured sliding-window size (WAKIR_ROUTING_OBS_WINDOW).",
    )
    lines.append(
        f"persona_engine_routing_decisions_window_size {envelope['window_size']}\n"
    )

    _emit_help(
        "persona_engine_routing_decisions_per_model",
        "Per chosen-model count of routing decisions in the current window.",
    )
    for model in sorted(envelope["count_per_model"].keys()):
        value = envelope["count_per_model"][model]
        lines.append(
            f'persona_engine_routing_decisions_per_model{{model="{_escape_label(model)}"}} {value}\n'
        )

    _emit_help(
        "persona_engine_routing_decisions_per_mode",
        "Per routing-mode count of decisions in the current window.",
    )
    for mode in sorted(envelope["count_per_mode"].keys()):
        value = envelope["count_per_mode"][mode]
        lines.append(
            f'persona_engine_routing_decisions_per_mode{{mode="{_escape_label(mode)}"}} {value}\n'
        )

    _emit_help(
        "persona_engine_routing_decision_latency_us_avg",
        "Arithmetic-mean decision latency (microseconds) over the current window.",
    )
    lines.append(
        "persona_engine_routing_decision_latency_us_avg "
        f"{_format_value(envelope['avg_decision_latency_us'])}\n"
    )

    _emit_help(
        "persona_engine_routing_decision_latency_us",
        "Per-mode nearest-rank decision-latency percentile (microseconds).",
    )
    for mode in sorted(envelope["latency_per_mode"].keys()):
        bucket = envelope["latency_per_mode"][mode]
        for q_label, q_key in (("0.5", "p50"), ("0.95", "p95"), ("0.99", "p99")):
            lines.append(
                f'persona_engine_routing_decision_latency_us{{mode="{_escape_label(mode)}",quantile="{q_label}"}}'
                f" {bucket[q_key]}\n"
            )

    _emit_help(
        "persona_engine_routing_decision_count_per_mode",
        "Per-mode sample-count contributing to the latency percentile (mirror of count_per_mode but filtered to records with a valid latency).",
    )
    for mode in sorted(envelope["latency_per_mode"].keys()):
        bucket = envelope["latency_per_mode"][mode]
        lines.append(
            f'persona_engine_routing_decision_count_per_mode{{mode="{_escape_label(mode)}"}} {bucket["count"]}\n'
        )

    _emit_help(
        "persona_engine_routing_classifier_attempts_total",
        "Count of decisions in a classifier mode (numerator universe for the hit-rate).",
    )
    lines.append(
        f"persona_engine_routing_classifier_attempts_total {envelope['classifier_attempts']}\n"
    )

    _emit_help(
        "persona_engine_routing_classifier_fallbacks_total",
        "Count of classifier-mode decisions that fell back to the heuristic router.",
    )
    lines.append(
        f"persona_engine_routing_classifier_fallbacks_total {envelope['classifier_fallbacks']}\n"
    )

    _emit_help(
        "persona_engine_routing_classifier_hit_rate",
        "Share of classifier-mode decisions that resolved without falling back (1.0 = perfect, 0.0 = always-fallback or no traffic).",
    )
    lines.append(
        "persona_engine_routing_classifier_hit_rate "
        f"{_format_value(envelope['classifier_hit_rate'])}\n"
    )

    _emit_help(
        "persona_engine_routing_scrape_timestamp_seconds",
        "POSIX-epoch timestamp at which the routing-decision aggregator last wrote the textfile.",
    )
    lines.append(
        f"persona_engine_routing_scrape_timestamp_seconds {scrape_ts_utc}\n"
    )

    return "".join(lines)


def _escape_label(v: str) -> str:
    """Prometheus label-value escaping: backslash, double-quote, newline."""
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_value(v: float) -> str:
    """Format a float for Prometheus exposition (parity with sibling aggregators)."""
    if isinstance(v, bool):
        v = int(v)
    if isinstance(v, int):
        return str(v)
    if float(v).is_integer():
        return str(int(v))
    return f"{v:.10f}".rstrip("0").rstrip(".")


# ---------------------------------------------------------------------------
# Atomic textfile write (parity with cache-hit-rate-aggregator)
# ---------------------------------------------------------------------------


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
# CLI
# ---------------------------------------------------------------------------


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="routing-decision-observability",
        description=(
            "Aggregator for per-decision routing telemetry out of the "
            "persona-engine JSONL sink (WAKIR_ROUTING_DECISION_JSONL). "
            "Outputs JSON for operators or Prometheus exposition for the "
            "node-exporter textfile collector. ADR-0064 Phase-2b/2c "
            "observability artefact."
        ),
    )
    p.add_argument(
        "--jsonl-path",
        type=Path,
        default=None,
        help=(
            "Path to the routing-decision JSONL. Falls back to "
            f"${WAKIR_ROUTING_DECISION_JSONL_ENV}."
        ),
    )
    p.add_argument(
        "--window-size",
        type=int,
        default=None,
        help=(
            "Sliding-window size (most recent N decisions). Falls back "
            f"to ${WAKIR_ROUTING_OBS_WINDOW_ENV} then "
            f"{DEFAULT_WINDOW_SIZE}."
        ),
    )
    p.add_argument(
        "--format",
        choices=("json", "prometheus"),
        default="json",
        help="Output format: json (default, operator-facing) or prometheus.",
    )
    p.add_argument(
        "--textfile-output",
        type=Path,
        default=Path(DEFAULT_TEXTFILE_OUTPUT),
        help=(
            "Prometheus textfile-collector output path (only used when "
            f"--format=prometheus). Default: {DEFAULT_TEXTFILE_OUTPUT}"
        ),
    )
    p.add_argument(
        "--now",
        type=int,
        default=None,
        help=(
            "Override the 'now' POSIX-epoch timestamp for hermetic tests. "
            "Production runs leave this unset and use time.time()."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "In --format=prometheus mode: render to stdout instead of "
            "writing the textfile. In --format=json mode: no-op."
        ),
    )
    return p


def resolve_jsonl_path(
    cli_value: Optional[Path], env: Mapping[str, str]
) -> Optional[Path]:
    if cli_value is not None:
        return cli_value
    env_value = env.get(WAKIR_ROUTING_DECISION_JSONL_ENV, "").strip()
    if env_value:
        return Path(env_value)
    return None


def resolve_window_size(
    cli_value: Optional[int], env: Mapping[str, str]
) -> int:
    if cli_value is not None:
        if cli_value <= 0:
            return DEFAULT_WINDOW_SIZE
        return cli_value
    return read_window_size_from_env(env)


def main(
    argv: Optional[List[str]] = None,
    *,
    env: Optional[Mapping[str, str]] = None,
) -> int:
    args = build_argparser().parse_args(argv)
    env_map: Mapping[str, str] = env if env is not None else os.environ

    jsonl_path = resolve_jsonl_path(args.jsonl_path, env_map)
    if jsonl_path is None:
        sys.stderr.write(
            "routing-decision-observability: no JSONL path configured "
            f"(set --jsonl-path or ${WAKIR_ROUTING_DECISION_JSONL_ENV}).\n"
        )
        return 1

    try:
        records = read_decision_records(jsonl_path)
    except JsonlReadError as exc:
        sys.stderr.write(f"routing-decision-observability: {exc}\n")
        return 1

    window_size = resolve_window_size(args.window_size, env_map)
    envelope = aggregate_decisions(records, window_size=window_size)

    if args.format == "json":
        sys.stdout.write(json.dumps(envelope, sort_keys=True, indent=2))
        sys.stdout.write("\n")
        return 0

    # Prometheus path.
    now = args.now if args.now is not None else int(time.time())
    payload = render_prometheus(envelope, scrape_ts_utc=now)
    if args.dry_run:
        sys.stdout.write(payload)
        return 0
    try:
        atomic_write(args.textfile_output, payload)
    except OSError as exc:
        sys.stderr.write(
            f"routing-decision-observability: cannot write textfile output: {exc}\n"
        )
        return 2
    return 0


__all__ = [
    "CLASSIFIER_MODES",
    "DEFAULT_TEXTFILE_OUTPUT",
    "DEFAULT_WINDOW_SIZE",
    "JsonlReadError",
    "KNOWN_ROUTING_MODES",
    "MODEL_UNKNOWN_BUCKET",
    "MODE_UNKNOWN_BUCKET",
    "ROUTING_MODE_HEURISTIC",
    "ROUTING_MODE_LLM_CLASSIFIER",
    "ROUTING_MODE_LLM_CLASSIFIER_FALLBACK_HEURISTIC",
    "ROUTING_MODE_STATIC",
    "WAKIR_ROUTING_DECISION_JSONL_ENV",
    "WAKIR_ROUTING_OBS_WINDOW_ENV",
    "aggregate_decisions",
    "atomic_write",
    "build_argparser",
    "main",
    "read_decision_records",
    "read_window_size_from_env",
    "render_prometheus",
    "resolve_jsonl_path",
    "resolve_window_size",
    "select_window",
]


if __name__ == "__main__":
    sys.exit(main())
