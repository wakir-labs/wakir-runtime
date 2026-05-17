#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""wat-anchor-pipeline-observability — Sprint-WAT-Anchor-Pipeline-Live-Observability-MINI.

Background
----------

ADR-0064 §Folgeartefakte Phase-2-Observability (Approval 2026-05-16
~15:30 CEST) and Noa's PR #81 Zone-I-trigger ("WAT-Pipeline-SLOs as
Phase-2-Trigger") mandate live WAT-anchor-pipeline observability now
that Tomas' PR #124 (``wakir-anchor anchor-receipt`` CLI surface) is
on ``wakir-runtime/main``. The deferred Phase-2 SLO catalogue
(``docs/observability/sli-slo-wat-phase-2.md``) defines SLO-1
finalization-rate, SLO-2 anchor-latency-p99, and SLO-3 Bitcoin-block-
height-drift; this script is the gauge emitter that feeds those SLOs.

The script periodically invokes ``wakir-anchor anchor-receipt --latest
--json`` (Tomas' PR #124 subcommand), parses the structured-JSON
output that the WAT-core emits, and writes a Prometheus textfile-
collector record that Kai's node-exporter Quadlet already scrapes.
Pattern parity with ``mira-hourly-watchdog.py`` (Noa's PR #81) and
``per-model-cost-aggregator.py`` + ``cache-hit-rate-aggregator.py``
(Noa's PR #110 + #117): same stdlib-only floor, same atomic-write
discipline, same textfile-collector default location.

The CLI contract that this script depends on is documented in
``docs/observability/sli-slo-wat-phase-2.md`` §A.1. The shape Tomas'
PR #124 produces:

    {
      "schema_version": 1,
      "receipt_path": "meta/timestamps/wat/.../root.bin.ots",
      "anchor_root_hex": "<64-hex>",
      "verifier_state": "finalized" | "pending" | "failed",
      "bitcoin_block_height": <int | null>,
      "bitcoin_block_hash": "<64-hex | null>",
      "calendar_attestations": <int>,
      "anchor_timestamp_utc": "<ISO-8601 | null>",
      "finalized_timestamp_utc": "<ISO-8601 | null>",
      "age_seconds_since_anchor": <int | null>,
      "age_seconds_since_finalized": <int | null>,
      "spool_totals": {
          "finalized": <int>, "pending": <int>, "failed": <int>
      }
    }

The script is **read-only against the WAT pipeline** — it shells out
to the CLI Tomas owns, never touches the receipt-DB, never re-anchors,
never rewrites .ots files. Zone-I separation: Tomas owns the WAT-core,
Noa measures whether it runs as expected.

Failure modes that the script must survive without raising:

  - ``wakir-anchor`` CLI not installed (CI runner, dev container without
    WAT package): emit a single ``wat_anchor_cli_unavailable`` gauge =
    1.0 and exit 0. Production runs treat this as a Tier-2 ticket
    via Prometheus' ``up{job="wat-anchor"}`` semantics.
  - ``wakir-anchor`` exits non-zero (e.g. no receipts yet,
    OpenTimestamps calendar unreachable): emit the gauges with the
    last-observed values where possible and set
    ``wat_anchor_pipeline_cli_failure`` to 1.0. Exit 0 so the
    systemd timer keeps firing.
  - CLI output is not valid JSON: same path as CLI non-zero exit.

Run mode
--------

Stdlib-only. Driven by a systemd user-timer
(``OnCalendar=*:3/15``) inside the ``claude-dev`` toolbox container,
fifteen-minute cadence, three minutes off-grid from the mira-hourly
slot. Per scrape window the gauges are *absolute totals* (counters of
finalized/pending/failed receipts over the lifetime of the spool, plus
instantaneous age + Bitcoin-block-height gauges). Prometheus counter
semantics handled at scrape time via ``rate()``; the script writes
gauges so a script restart re-reads the spool from scratch without a
counter-reset alert storm.

Exit codes
----------

* ``0`` — script ran cleanly, textfile output written. CLI may have
  failed internally; that surfaces via gauges, not exit code.
* ``2`` — output directory not writable (textfile-collector path is
  broken; alert via host-side filesystem monitoring).

License: Apache-2.0 (parity with the other ``scripts/*.py`` aggregators).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_TEXTFILE_OUTPUT = (
    "/var/lib/node_exporter/textfile_collector/wat_anchor_pipeline.prom"
)

#: Default sliding-window size for per-anchor latency histograms.
#: ENV ``WAKIR_OBS_WINDOW_SIZE`` overrides; CLI ``--window`` overrides ENV.
#: 100 anchors gives meaningful p95/p99 quantiles (5 / 1 samples at the
#: tail) without unbounded memory growth in the JSONL tail-reader.
DEFAULT_WINDOW_SIZE = 100

#: ENV variable that overrides ``DEFAULT_WINDOW_SIZE``. CLI ``--window``
#: still wins over the ENV.
ENV_WINDOW_SIZE = "WAKIR_OBS_WINDOW_SIZE"

#: Default path of the per-anchor latency-observations JSONL emitted by
#: the WAT pipeline (Tomas owns the producer; Noa consumes). One JSON
#: object per line; the script tails the last ``--window`` lines.
DEFAULT_LATENCY_SOURCE = "/var/lib/wakir/wat-anchor-latencies.jsonl"

#: Ordered list of pipeline-stage names. The order is contractual:
#: dashboards, alert-rules, and the JSON / Prometheus output all key
#: off this sequence. Adding a stage is a schema-version bump; renaming
#: one is a breaking change.
PIPELINE_STAGES: Tuple[str, ...] = (
    "enqueue_to_pre_ots",
    "ots_call",
    "post_ots_commit",
    "wat_write",
)

#: JSONL field name carrying the per-stage timing dict. One observation
#: line is expected per anchored receipt.
LATENCY_STAGES_FIELD = "stages"

#: JSONL stage-field-name suffix for milliseconds. The producer emits
#: ``<stage>_ms``; the script converts to seconds for the Prometheus
#: exposition format (Prometheus convention is seconds, not ms).
LATENCY_STAGE_MS_SUFFIX = "_ms"

#: Prometheus histogram bucket boundaries (seconds). Chosen to span the
#: observed-and-plausible range for the OTS-anchor pipeline: sub-10ms
#: local writes, 100ms-1s typical OTS calls, multi-second tail on slow
#: calendars. The +Inf bucket is appended automatically by
#: ``render_prom_histogram``.
DEFAULT_HISTOGRAM_BUCKETS_SECONDS: Tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)

#: Output formats supported by ``--format``. ``prom`` emits Prometheus
#: histogram exposition format (``# TYPE histogram``) for scrape by the
#: existing prometheus textfile-collector; ``json`` emits a compact
#: summary for ad-hoc operator inspection and CI assertions.
SUPPORTED_OUTPUT_FORMATS: Tuple[str, ...] = ("json", "prom")

#: Default subprocess command. Tomas' PR #124 ships the
#: ``wakir-anchor anchor-receipt --latest --json`` subcommand. Overridable
#: via ``--cli-command`` for hermetic tests.
DEFAULT_CLI_COMMAND: Tuple[str, ...] = (
    "wakir-anchor",
    "anchor-receipt",
    "--latest",
    "--json",
)

#: Subprocess timeout (seconds). OTS-calendar HTTP probes inside the
#: CLI can stall on slow upstreams; we cap aggressively so the systemd
#: timer slot stays bounded.
DEFAULT_CLI_TIMEOUT_SECONDS = 30

#: Schema-version this script understands. Bumped together with Tomas'
#: PR #124 output shape. If the CLI returns a higher version we still
#: parse the fields we know about and set
#: ``wat_anchor_pipeline_schema_drift`` = 1.0.
EXPECTED_SCHEMA_VERSION = 1

#: Accepted verifier_state values. Anything else falls into the
#: ``unknown`` bucket and flips the schema-drift gauge to 1.0.
ACCEPTED_VERIFIER_STATES = ("finalized", "pending", "failed")


# ---------------------------------------------------------------------------
# CLI invocation
# ---------------------------------------------------------------------------


def cli_available(command: Tuple[str, ...]) -> bool:
    """Return True iff the CLI binary is on PATH or is an absolute path."""
    if not command:
        return False
    head = command[0]
    if "/" in head:
        return Path(head).is_file() and os.access(head, os.X_OK)
    return shutil.which(head) is not None


def invoke_cli(
    command: Tuple[str, ...],
    *,
    timeout_seconds: int = DEFAULT_CLI_TIMEOUT_SECONDS,
    env: Optional[Mapping[str, str]] = None,
) -> Tuple[int, str, str]:
    """Run the CLI and return ``(returncode, stdout, stderr)``.

    Does **not** raise on non-zero exit. Timeouts raise
    :class:`subprocess.TimeoutExpired` which the caller catches.
    """
    proc = subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        env=dict(env) if env is not None else None,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


def parse_cli_output(stdout: str) -> Optional[Dict[str, Any]]:
    """Parse the CLI's stdout as JSON. Returns ``None`` on parse failure.

    The CLI is contracted to emit exactly one JSON object on stdout when
    invoked with ``--json``. Leading / trailing whitespace is stripped;
    if multiple JSON objects appear we take the first dict line.
    """
    text = stdout.strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        # Tolerate a trailing newline-separated log line before the JSON
        # object (older CLI fixtures occasionally do that).
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                cand = json.loads(line)
                if isinstance(cand, dict):
                    return cand
            except json.JSONDecodeError:
                continue
        return None
    if isinstance(obj, dict):
        return obj
    return None


# ---------------------------------------------------------------------------
# Receipt-shape extraction
# ---------------------------------------------------------------------------


def extract_receipt(
    obj: Mapping[str, Any],
) -> Dict[str, Any]:
    """Extract the receipt fields, applying defaults for missing keys.

    Returns a dict with every field set — missing or wrong-typed values
    fall back to safe defaults so the gauge surface stays stable.
    """
    out: Dict[str, Any] = {
        "schema_version": _int_or_none(obj.get("schema_version")),
        "anchor_root_hex": _str_or_empty(obj.get("anchor_root_hex")),
        "verifier_state": _str_or_empty(obj.get("verifier_state")),
        "bitcoin_block_height": _int_or_none(obj.get("bitcoin_block_height")),
        "calendar_attestations": _int_or_zero(
            obj.get("calendar_attestations")
        ),
        "age_seconds_since_anchor": _int_or_none(
            obj.get("age_seconds_since_anchor")
        ),
        "age_seconds_since_finalized": _int_or_none(
            obj.get("age_seconds_since_finalized")
        ),
    }
    # Spool-wide counters. PR #124 contract: when ``--latest`` is invoked
    # the CLI also exposes the spool-aggregate counts so the observability
    # script can emit per-state totals without iterating the spool itself.
    spool = obj.get("spool_totals")
    if isinstance(spool, Mapping):
        out["spool_finalized"] = _int_or_zero(spool.get("finalized"))
        out["spool_pending"] = _int_or_zero(spool.get("pending"))
        out["spool_failed"] = _int_or_zero(spool.get("failed"))
    else:
        # Fallback: derive from verifier_state of the latest receipt only.
        # Coarse but additive so the dashboard still shows non-zero.
        out["spool_finalized"] = 0
        out["spool_pending"] = 0
        out["spool_failed"] = 0
        state = out["verifier_state"]
        if state == "finalized":
            out["spool_finalized"] = 1
        elif state == "pending":
            out["spool_pending"] = 1
        elif state == "failed":
            out["spool_failed"] = 1
    return out


def _int_or_zero(v: Any) -> int:
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    return 0


def _int_or_none(v: Any) -> Optional[int]:
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    return None


def _str_or_empty(v: Any) -> str:
    if isinstance(v, str):
        return v
    return ""


# ---------------------------------------------------------------------------
# Diagnostic flags (drift / failure surface)
# ---------------------------------------------------------------------------


def diagnose_receipt(
    receipt: Mapping[str, Any],
) -> Dict[str, float]:
    """Compute diagnostic flag gauges from a parsed receipt.

    Returns a dict with three keys:

      * ``schema_drift``: 1.0 if the schema_version is unknown or the
        verifier_state is outside the accepted set; 0.0 otherwise.
      * ``cli_unavailable``: always 0.0 here (set elsewhere when the
        CLI binary itself is missing).
      * ``cli_failure``: always 0.0 here (set elsewhere when subprocess
        returns non-zero or output is not JSON).
    """
    drift = 0.0
    schema = receipt.get("schema_version")
    if schema != EXPECTED_SCHEMA_VERSION:
        # ``None`` (missing) or higher/lower version both count as drift.
        drift = 1.0
    state = receipt.get("verifier_state")
    if state not in ACCEPTED_VERIFIER_STATES:
        drift = 1.0
    return {
        "schema_drift": drift,
        "cli_unavailable": 0.0,
        "cli_failure": 0.0,
    }


# ---------------------------------------------------------------------------
# Snapshot construction
# ---------------------------------------------------------------------------


def empty_snapshot() -> Dict[str, Any]:
    """Snapshot used when the CLI is unavailable or produces nothing."""
    return {
        "schema_version": None,
        "anchor_root_hex": "",
        "verifier_state": "",
        "bitcoin_block_height": None,
        "calendar_attestations": 0,
        "age_seconds_since_anchor": None,
        "age_seconds_since_finalized": None,
        "spool_finalized": 0,
        "spool_pending": 0,
        "spool_failed": 0,
    }


def build_snapshot(
    command: Tuple[str, ...],
    *,
    timeout_seconds: int = DEFAULT_CLI_TIMEOUT_SECONDS,
    env: Optional[Mapping[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, float]]:
    """Build the (receipt-snapshot, diagnostic-flags) tuple.

    Encapsulates the CLI invocation, output parsing, and the failure-
    mode handling. Never raises.
    """
    flags: Dict[str, float] = {
        "schema_drift": 0.0,
        "cli_unavailable": 0.0,
        "cli_failure": 0.0,
    }

    if not cli_available(command):
        flags["cli_unavailable"] = 1.0
        return empty_snapshot(), flags

    try:
        returncode, stdout, _stderr = invoke_cli(
            command, timeout_seconds=timeout_seconds, env=env
        )
    except (subprocess.TimeoutExpired, OSError):
        flags["cli_failure"] = 1.0
        return empty_snapshot(), flags

    if returncode != 0:
        flags["cli_failure"] = 1.0
        return empty_snapshot(), flags

    parsed = parse_cli_output(stdout)
    if parsed is None:
        flags["cli_failure"] = 1.0
        return empty_snapshot(), flags

    receipt = extract_receipt(parsed)
    diag = diagnose_receipt(receipt)
    flags["schema_drift"] = diag["schema_drift"]
    return receipt, flags


# ---------------------------------------------------------------------------
# Prometheus textfile rendering
# ---------------------------------------------------------------------------


def render_textfile(
    receipt: Mapping[str, Any],
    flags: Mapping[str, float],
    *,
    scrape_ts_utc: Optional[int] = None,
) -> str:
    """Render the WAT-anchor-pipeline gauges in Prometheus exposition format.

    Schema (per ``docs/observability/sli-slo-wat-phase-2.md`` §B):

      wat_anchor_finalized_count          (gauge, spool-wide counter)
      wat_anchor_pending_count            (gauge, spool-wide counter)
      wat_anchor_failed_count             (gauge, spool-wide counter)
      wat_anchor_calendar_attestations    (gauge, latest receipt)
      wat_last_anchor_age_seconds         (gauge, latest receipt)
      wat_last_finalized_age_seconds      (gauge, latest finalized receipt)
      wat_bitcoin_block_height_latest     (gauge, latest finalized receipt)
      wat_anchor_pipeline_schema_drift    (gauge, 0/1)
      wat_anchor_cli_unavailable          (gauge, 0/1)
      wat_anchor_pipeline_cli_failure     (gauge, 0/1)
      wat_anchor_pipeline_scrape_timestamp_seconds (gauge)
    """
    if scrape_ts_utc is None:
        scrape_ts_utc = int(time.time())
    lines: List[str] = []

    metric_specs: List[Tuple[str, str, str, str]] = [
        (
            "wat_anchor_finalized_count",
            "Spool-wide count of WAT anchor receipts in verifier_state=finalized.",
            "gauge",
            "spool_finalized",
        ),
        (
            "wat_anchor_pending_count",
            "Spool-wide count of WAT anchor receipts in verifier_state=pending.",
            "gauge",
            "spool_pending",
        ),
        (
            "wat_anchor_failed_count",
            "Spool-wide count of WAT anchor receipts in verifier_state=failed.",
            "gauge",
            "spool_failed",
        ),
        (
            "wat_anchor_calendar_attestations",
            "Calendar attestations on the latest WAT anchor receipt.",
            "gauge",
            "calendar_attestations",
        ),
    ]
    for metric_name, help_text, mtype, key in metric_specs:
        lines.append(f"# HELP {metric_name} {help_text}\n")
        lines.append(f"# TYPE {metric_name} {mtype}\n")
        value = receipt.get(key, 0)
        lines.append(f"{metric_name} {_format_value(value)}\n")

    # Age gauges — None means "no data yet"; we render -1 so the gauge
    # is always present and Prometheus alerts can use a "< 0" sentinel
    # check to distinguish missing-data from a real fresh anchor.
    age_specs: List[Tuple[str, str, str]] = [
        (
            "wat_last_anchor_age_seconds",
            "Seconds since the latest WAT anchor receipt was created (-1 if no data).",
            "age_seconds_since_anchor",
        ),
        (
            "wat_last_finalized_age_seconds",
            "Seconds since the latest WAT anchor receipt was finalized (-1 if no data).",
            "age_seconds_since_finalized",
        ),
    ]
    for metric_name, help_text, key in age_specs:
        lines.append(f"# HELP {metric_name} {help_text}\n")
        lines.append(f"# TYPE {metric_name} gauge\n")
        v = receipt.get(key)
        rendered = _format_value(v) if v is not None else "-1"
        lines.append(f"{metric_name} {rendered}\n")

    # Bitcoin block height — None means "not yet finalized"; we render
    # 0 so the gauge stays additive in dashboards. Alerts use the
    # schema-drift / pending-count gauges to disambiguate.
    lines.append(
        "# HELP wat_bitcoin_block_height_latest "
        "Bitcoin block height at which the latest WAT anchor was finalized (0 if pending).\n"
    )
    lines.append("# TYPE wat_bitcoin_block_height_latest gauge\n")
    bh = receipt.get("bitcoin_block_height")
    bh_rendered = _format_value(bh) if bh is not None else "0"
    lines.append(f"wat_bitcoin_block_height_latest {bh_rendered}\n")

    # Diagnostic flags.
    flag_specs: List[Tuple[str, str, str]] = [
        (
            "wat_anchor_pipeline_schema_drift",
            "1.0 if the CLI emitted an unknown schema_version or verifier_state, else 0.0.",
            "schema_drift",
        ),
        (
            "wat_anchor_cli_unavailable",
            "1.0 if the wakir-anchor CLI is not installed on PATH, else 0.0.",
            "cli_unavailable",
        ),
        (
            "wat_anchor_pipeline_cli_failure",
            "1.0 if the CLI returned non-zero or produced unparseable JSON, else 0.0.",
            "cli_failure",
        ),
    ]
    for metric_name, help_text, key in flag_specs:
        lines.append(f"# HELP {metric_name} {help_text}\n")
        lines.append(f"# TYPE {metric_name} gauge\n")
        lines.append(f"{metric_name} {_format_value(flags.get(key, 0.0))}\n")

    # Scrape timestamp.
    lines.append(
        "# HELP wat_anchor_pipeline_scrape_timestamp_seconds "
        "POSIX-epoch timestamp at which the observability script last wrote the textfile.\n"
    )
    lines.append("# TYPE wat_anchor_pipeline_scrape_timestamp_seconds gauge\n")
    lines.append(
        f"wat_anchor_pipeline_scrape_timestamp_seconds {scrape_ts_utc}\n"
    )

    return "".join(lines)


def _format_value(v: Any) -> str:
    """Format a numeric value for Prometheus exposition.

    Integer-valued floats render as integers; non-integer floats render
    with a high-precision fixed format. Non-numeric values render as 0.
    """
    if isinstance(v, bool):
        v = int(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v != v:  # NaN
            return "0"
        if float(v).is_integer():
            return str(int(v))
        return f"{v:.10f}".rstrip("0").rstrip(".")
    return "0"


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
# Per-anchor latency histograms (Tag-12 mini-welle, Phase-2-operations-reife)
# ---------------------------------------------------------------------------
#
# The receipt-emitter path above (build_snapshot -> render_textfile) covers
# *spool-wide* gauges: how many anchors are finalized, what is the age of
# the latest one, what is the current Bitcoin block height. That surface
# answers SLO-1 (finalization-rate) and SLO-3 (Bitcoin-block-height-drift)
# but it does *not* answer SLO-2 (anchor-latency-p99): for that we need
# per-anchor stage-level timings.
#
# Producer contract (Tomas, WAT-core)
# -----------------------------------
#
# The WAT-core writes one JSON object per finalized anchor to a JSONL
# observation file (default: ``/var/lib/wakir/wat-anchor-latencies.jsonl``).
# One line per anchor; append-only; rotation handled externally. Shape:
#
#     {
#       "anchor_root_hex": "<64-hex>",
#       "timestamp": "<ISO-8601>",
#       "stages": {
#         "enqueue_to_pre_ots_ms": <float | int>,
#         "ots_call_ms": <float | int>,
#         "post_ots_commit_ms": <float | int>,
#         "wat_write_ms": <float | int>
#       }
#     }
#
# Missing or malformed lines are silently skipped (defensive: the producer
# may be racing rotation, or the consumer may sample mid-write); the line
# is not counted toward the window.
#
# Consumer (Noa, SRE) — this script
# ----------------------------------
#
# Tail the last ``--window`` (default 100, ENV ``WAKIR_OBS_WINDOW_SIZE``)
# parseable lines, compute per-stage p50/p95/p99 quantiles plus a bucketed
# histogram, render as either JSON (operator inspection / CI assertions)
# or Prometheus ``# TYPE histogram`` exposition (node-exporter scrape).
#
# The histogram path is *additive* to the receipt-emitter path. ``--format``
# selects which output shape the script produces; default is the
# receipt-emitter textfile (unchanged behavior, for backward compat with
# the Tag-9 systemd timer).


def resolve_window_size(
    cli_value: Optional[int],
    *,
    env: Optional[Mapping[str, str]] = None,
) -> int:
    """Resolve the window size: CLI > ENV > default.

    ``cli_value`` of ``None`` means "not supplied". Non-positive values
    (zero, negative) are coerced to the default; this is a defensive
    choice — a window of zero would silently emit an empty histogram
    and we would rather fall back to the documented default than
    surface garbage.
    """
    if cli_value is not None and cli_value > 0:
        return cli_value
    env_map = env if env is not None else os.environ
    raw = env_map.get(ENV_WINDOW_SIZE)
    if raw is not None:
        try:
            parsed = int(raw)
        except ValueError:
            parsed = 0
        if parsed > 0:
            return parsed
    return DEFAULT_WINDOW_SIZE


def read_latency_samples(
    source: Path,
    *,
    window: int,
) -> List[Dict[str, float]]:
    """Read the last ``window`` parseable latency-observation lines.

    Returns a list of stage-name -> seconds dicts, oldest first. Lines
    that cannot be parsed as JSON, that are not objects, that miss the
    ``stages`` key, or whose ``stages`` block is not a dict, are skipped
    silently. Lines whose stage values are not numeric are also skipped
    (we do not surface a NaN into the histogram).

    The function reads the whole file (stdlib, no streaming-tail
    dependency); for the expected file size (one JSON line per anchor,
    anchors happen on the order of hourly cadence) this is fine. If the
    producer cadence ever grows to thousands per second a streaming
    tail-from-end implementation would be the natural follow-up.
    """
    if window <= 0:
        return []
    if not source.is_file():
        return []
    samples: List[Dict[str, float]] = []
    try:
        with source.open("r", encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                stages = obj.get(LATENCY_STAGES_FIELD)
                if not isinstance(stages, Mapping):
                    continue
                parsed = _parse_stage_block(stages)
                if parsed is None:
                    continue
                samples.append(parsed)
    except OSError:
        return []
    if len(samples) > window:
        samples = samples[-window:]
    return samples


def _parse_stage_block(stages: Mapping[str, Any]) -> Optional[Dict[str, float]]:
    """Convert one ``stages`` block into a ``{stage_name: seconds}`` dict.

    Returns ``None`` if any contractual stage is missing or non-numeric.
    Partial samples are not useful for per-stage percentiles — we either
    have the whole anchor or we drop the whole observation.
    """
    out: Dict[str, float] = {}
    for stage in PIPELINE_STAGES:
        key = stage + LATENCY_STAGE_MS_SUFFIX
        v = stages.get(key)
        if isinstance(v, bool):
            return None
        if not isinstance(v, (int, float)):
            return None
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        if v < 0:
            return None
        out[stage] = float(v) / 1000.0  # ms -> seconds
    return out


def compute_percentile(values: Sequence[float], percentile: float) -> float:
    """Compute a nearest-rank percentile from a sorted-on-demand sequence.

    Nearest-rank (ceil) is chosen over linear interpolation: it returns
    an actual observed value, which is what an operator wants when
    reading an alert ("the p99 was 1.2 s — yes, there really was an
    anchor that took 1.2 s"). For ``percentile=0`` returns the minimum,
    for ``percentile=100`` returns the maximum.

    Empty sequences return 0.0 (the histogram is empty; downstream
    callers should consult ``count`` before reading the percentiles).
    """
    if not values:
        return 0.0
    if percentile < 0:
        percentile = 0.0
    if percentile > 100:
        percentile = 100.0
    ordered = sorted(values)
    n = len(ordered)
    if percentile == 0:
        return ordered[0]
    # Nearest-rank: ceil(p/100 * n), 1-indexed -> 0-indexed.
    rank = math.ceil(percentile / 100.0 * n)
    idx = max(0, min(n - 1, rank - 1))
    return ordered[idx]


def bucketize(
    values: Sequence[float],
    buckets: Sequence[float] = DEFAULT_HISTOGRAM_BUCKETS_SECONDS,
) -> List[Tuple[float, int]]:
    """Bin ``values`` into cumulative (Prometheus-style) histogram buckets.

    Returns a list of ``(le, cumulative_count)`` tuples in the order of
    ``buckets`` with a trailing ``(+Inf, total)`` entry appended.
    Prometheus histogram semantics: each bucket counts samples with
    value <= le, so counts are monotonically non-decreasing across the
    returned list.
    """
    sorted_buckets = sorted(set(buckets))
    out: List[Tuple[float, int]] = []
    for le in sorted_buckets:
        count = sum(1 for v in values if v <= le)
        out.append((le, count))
    out.append((float("inf"), len(values)))
    return out


def summarize_stage(values: Sequence[float]) -> Dict[str, Any]:
    """Per-stage summary: count, sum, p50, p95, p99, bucket counts."""
    n = len(values)
    total = float(sum(values)) if values else 0.0
    return {
        "count": n,
        "sum_seconds": total,
        "p50_seconds": compute_percentile(values, 50.0),
        "p95_seconds": compute_percentile(values, 95.0),
        "p99_seconds": compute_percentile(values, 99.0),
        "buckets": [
            {"le": le, "count": c}
            for (le, c) in bucketize(values)
        ],
    }


def summarize_window(
    samples: Sequence[Mapping[str, float]],
) -> Dict[str, Any]:
    """Aggregate per-stage summaries across the sample window.

    ``samples`` is a list of ``{stage_name: seconds}`` dicts. Returns a
    dict with one entry per contractual ``PIPELINE_STAGES`` name plus a
    ``window_size`` sidecar for downstream renderers.
    """
    per_stage: Dict[str, Any] = {}
    for stage in PIPELINE_STAGES:
        vals: List[float] = []
        for sample in samples:
            v = sample.get(stage)
            if isinstance(v, (int, float)):
                vals.append(float(v))
        per_stage[stage] = summarize_stage(vals)
    return {
        "window_size": len(samples),
        "stages": per_stage,
    }


def render_json_summary(
    summary: Mapping[str, Any],
    *,
    scrape_ts_utc: Optional[int] = None,
) -> str:
    """Render the window summary as a single-object JSON document.

    Shape:

        {
          "schema_version": 1,
          "scrape_timestamp_seconds": <int>,
          "window_size": <int>,
          "stages": {
            "<stage_name>": {
              "count": <int>, "sum_seconds": <float>,
              "p50_seconds": <float>, "p95_seconds": <float>,
              "p99_seconds": <float>,
              "buckets": [{"le": <float>, "count": <int>}, ...]
            }
          }
        }

    Floats render with full precision; the consumer (operator CLI or
    CI assertion) is expected to round for display.
    """
    if scrape_ts_utc is None:
        scrape_ts_utc = int(time.time())
    doc = {
        "schema_version": 1,
        "scrape_timestamp_seconds": scrape_ts_utc,
        "window_size": int(summary.get("window_size", 0)),
        "stages": _json_safe_stages(summary.get("stages", {})),
    }
    return json.dumps(doc, indent=2, sort_keys=False) + "\n"


def _json_safe_stages(stages: Mapping[str, Any]) -> Dict[str, Any]:
    """Convert per-stage summaries into JSON-safe scalars (handles +Inf bucket)."""
    out: Dict[str, Any] = {}
    for stage_name in PIPELINE_STAGES:
        stage = stages.get(stage_name, {})
        if not isinstance(stage, Mapping):
            stage = {}
        out[stage_name] = {
            "count": int(stage.get("count", 0)),
            "sum_seconds": float(stage.get("sum_seconds", 0.0)),
            "p50_seconds": float(stage.get("p50_seconds", 0.0)),
            "p95_seconds": float(stage.get("p95_seconds", 0.0)),
            "p99_seconds": float(stage.get("p99_seconds", 0.0)),
            "buckets": [
                {
                    "le": ("+Inf" if math.isinf(b["le"]) else float(b["le"])),
                    "count": int(b["count"]),
                }
                for b in stage.get("buckets", [])
            ],
        }
    return out


def render_prom_histogram(
    summary: Mapping[str, Any],
    *,
    scrape_ts_utc: Optional[int] = None,
) -> str:
    """Render the window summary as Prometheus ``# TYPE histogram`` exposition.

    Emits one histogram per pipeline stage:

        wat_anchor_stage_latency_seconds{stage="<name>",le="0.005"} <count>
        ...
        wat_anchor_stage_latency_seconds{stage="<name>",le="+Inf"} <count>
        wat_anchor_stage_latency_seconds_sum{stage="<name>"} <seconds>
        wat_anchor_stage_latency_seconds_count{stage="<name>"} <count>

    Plus quantile summaries for dashboard reuse (Prometheus rewrites the
    quantiles via histogram_quantile() at query time; we expose the
    pre-computed values here for cheaper dashboards and for the JSON
    consumer parity):

        wat_anchor_stage_latency_p50_seconds{stage="<name>"} <seconds>
        wat_anchor_stage_latency_p95_seconds{stage="<name>"} <seconds>
        wat_anchor_stage_latency_p99_seconds{stage="<name>"} <seconds>

    Plus a window-size gauge for operator context:

        wat_anchor_latency_window_size <int>
        wat_anchor_latency_scrape_timestamp_seconds <int>
    """
    if scrape_ts_utc is None:
        scrape_ts_utc = int(time.time())
    stages = summary.get("stages", {})
    if not isinstance(stages, Mapping):
        stages = {}
    lines: List[str] = []

    histogram_name = "wat_anchor_stage_latency_seconds"
    lines.append(
        f"# HELP {histogram_name} "
        "Per-anchor pipeline-stage latency in seconds, "
        "bucketed for SLO-2 (anchor-latency-p99).\n"
    )
    lines.append(f"# TYPE {histogram_name} histogram\n")
    for stage_name in PIPELINE_STAGES:
        stage = stages.get(stage_name, {})
        if not isinstance(stage, Mapping):
            stage = {}
        buckets = stage.get("buckets") or []
        for b in buckets:
            le = b.get("le")
            count = int(b.get("count", 0))
            le_text = "+Inf" if (isinstance(le, float) and math.isinf(le)) else _format_le(le)
            lines.append(
                f'{histogram_name}_bucket{{stage="{stage_name}",le="{le_text}"}} {count}\n'
            )
        sum_seconds = float(stage.get("sum_seconds", 0.0))
        count = int(stage.get("count", 0))
        lines.append(
            f'{histogram_name}_sum{{stage="{stage_name}"}} {_format_float(sum_seconds)}\n'
        )
        lines.append(
            f'{histogram_name}_count{{stage="{stage_name}"}} {count}\n'
        )

    # Pre-computed percentile gauges — emitted alongside the histogram so
    # dashboard panels can reference them without histogram_quantile()
    # rewrites on every refresh. Quantile-on-the-server is the cheaper
    # path for the four-panel dashboard this PR ships; the bucket series
    # remain available for histogram_quantile-based custom queries.
    for percentile_label, percentile_key in (
        ("p50", "p50_seconds"),
        ("p95", "p95_seconds"),
        ("p99", "p99_seconds"),
    ):
        metric_name = f"wat_anchor_stage_latency_{percentile_label}_seconds"
        lines.append(
            f"# HELP {metric_name} Pre-computed {percentile_label} of the "
            f"per-stage latency over the current observation window.\n"
        )
        lines.append(f"# TYPE {metric_name} gauge\n")
        for stage_name in PIPELINE_STAGES:
            stage = stages.get(stage_name, {})
            if not isinstance(stage, Mapping):
                stage = {}
            v = float(stage.get(percentile_key, 0.0))
            lines.append(
                f'{metric_name}{{stage="{stage_name}"}} {_format_float(v)}\n'
            )

    # Window-size sidecar (operator context: dashboards should display
    # this so a sparse window is visible at a glance).
    lines.append(
        "# HELP wat_anchor_latency_window_size "
        "Number of parseable latency observations the script aggregated this run.\n"
    )
    lines.append("# TYPE wat_anchor_latency_window_size gauge\n")
    lines.append(
        f"wat_anchor_latency_window_size {int(summary.get('window_size', 0))}\n"
    )

    lines.append(
        "# HELP wat_anchor_latency_scrape_timestamp_seconds "
        "POSIX-epoch timestamp at which the latency-histogram script last wrote the textfile.\n"
    )
    lines.append("# TYPE wat_anchor_latency_scrape_timestamp_seconds gauge\n")
    lines.append(
        f"wat_anchor_latency_scrape_timestamp_seconds {scrape_ts_utc}\n"
    )

    return "".join(lines)


def _format_le(le: Any) -> str:
    """Format a bucket boundary value for Prometheus exposition."""
    if isinstance(le, (int, float)):
        if float(le).is_integer():
            return str(int(le))
        return f"{le:g}"
    return str(le)


def _format_float(v: float) -> str:
    """Format a float for Prometheus exposition (integer-valued -> int)."""
    if not isinstance(v, (int, float)):
        return "0"
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return "0"
    if float(v).is_integer():
        return str(int(v))
    # Trim trailing zeros so 0.005 renders as 0.005, not 0.00500000.
    return f"{v:.10f}".rstrip("0").rstrip(".")


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wat-anchor-pipeline-observability",
        description=(
            "Periodic emitter of Prometheus textfile-collector gauges for "
            "the WAT (Wakir Audit Trail) OTS-anchor pipeline. Consumes "
            "'wakir-anchor anchor-receipt --latest --json' (Tomas' PR "
            "#124) and feeds the SLO catalogue in "
            "docs/observability/sli-slo-wat-phase-2.md."
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
        "--cli-command",
        type=str,
        default=None,
        help=(
            "Override the wakir-anchor CLI command (space-separated). "
            "Default: 'wakir-anchor anchor-receipt --latest --json'."
        ),
    )
    p.add_argument(
        "--cli-timeout-seconds",
        type=int,
        default=DEFAULT_CLI_TIMEOUT_SECONDS,
        help=(
            "Subprocess timeout for the CLI invocation. Default: "
            f"{DEFAULT_CLI_TIMEOUT_SECONDS} s."
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
            "Build the snapshot and print the rendered textfile to "
            "stdout, but do not touch the textfile output path."
        ),
    )
    # ------------------------------------------------------------------
    # Per-anchor latency-histogram path (Tag-12 mini-welle).
    # ------------------------------------------------------------------
    p.add_argument(
        "--window",
        type=int,
        default=None,
        help=(
            "Sliding-window size (number of most-recent anchors) for the "
            "per-stage latency histogram. CLI > ENV WAKIR_OBS_WINDOW_SIZE "
            f"> default ({DEFAULT_WINDOW_SIZE})."
        ),
    )
    p.add_argument(
        "--format",
        choices=list(SUPPORTED_OUTPUT_FORMATS),
        default=None,
        help=(
            "Output format for the per-anchor latency-histogram path. "
            "'json' emits a structured summary for operator inspection / "
            "CI assertions; 'prom' emits Prometheus '# TYPE histogram' "
            "exposition. Omitting --format keeps the legacy receipt-emitter "
            "behavior (writes the gauge textfile from --textfile-output)."
        ),
    )
    p.add_argument(
        "--latency-source",
        type=Path,
        default=Path(DEFAULT_LATENCY_SOURCE),
        help=(
            "Path of the per-anchor latency-observations JSONL emitted by "
            "the WAT pipeline. One JSON object per line; missing or "
            "malformed lines are skipped. Default: "
            f"{DEFAULT_LATENCY_SOURCE}"
        ),
    )
    return p


def resolve_cli_command(cli_value: Optional[str]) -> Tuple[str, ...]:
    if cli_value is None or not cli_value.strip():
        return DEFAULT_CLI_COMMAND
    return tuple(cli_value.split())


def main(
    argv: Optional[List[str]] = None,
    *,
    env: Optional[Mapping[str, str]] = None,
) -> int:
    args = build_argparser().parse_args(argv)
    env_map: Optional[Mapping[str, str]] = env if env is not None else None
    now = args.now if args.now is not None else int(time.time())

    # New path: per-anchor latency histograms. Selected by --format.
    if args.format is not None:
        window = resolve_window_size(args.window, env=env_map)
        samples = read_latency_samples(args.latency_source, window=window)
        summary = summarize_window(samples)
        if args.format == "json":
            payload = render_json_summary(summary, scrape_ts_utc=now)
        else:  # "prom"
            payload = render_prom_histogram(summary, scrape_ts_utc=now)
        if args.dry_run:
            sys.stdout.write(payload)
            return 0
        # JSON+stdout is the operator-inspection default when --format is
        # used without --textfile-output explicitly overridden away from
        # the legacy receipt-emitter default. The receipt-emitter path
        # always writes the textfile; the histogram path emits to stdout
        # unless --textfile-output is explicitly different from the
        # default. We choose stdout-for-json to keep the operator CLI
        # ergonomics clean and avoid clobbering the receipt-emitter
        # textfile from a script invocation that asked for JSON.
        if args.format == "json" and args.textfile_output == Path(
            DEFAULT_TEXTFILE_OUTPUT
        ):
            sys.stdout.write(payload)
            return 0
        try:
            atomic_write(args.textfile_output, payload)
        except OSError as exc:
            sys.stderr.write(
                "wat-anchor-pipeline-observability: cannot write "
                f"latency-histogram output: {exc}\n"
            )
            return 2
        return 0

    # Legacy path: receipt-emitter (gauge textfile).
    command = resolve_cli_command(args.cli_command)
    receipt, flags = build_snapshot(
        command,
        timeout_seconds=args.cli_timeout_seconds,
        env=env_map,
    )
    payload = render_textfile(receipt, flags, scrape_ts_utc=now)
    if args.dry_run:
        sys.stdout.write(payload)
        return 0
    try:
        atomic_write(args.textfile_output, payload)
    except OSError as exc:
        sys.stderr.write(
            f"wat-anchor-pipeline-observability: cannot write textfile output: {exc}\n"
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
