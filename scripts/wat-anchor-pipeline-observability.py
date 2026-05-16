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
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_TEXTFILE_OUTPUT = (
    "/var/lib/node_exporter/textfile_collector/wat_anchor_pipeline.prom"
)

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
    command = resolve_cli_command(args.cli_command)
    receipt, flags = build_snapshot(
        command,
        timeout_seconds=args.cli_timeout_seconds,
        env=env_map,
    )
    now = args.now if args.now is not None else int(time.time())
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
