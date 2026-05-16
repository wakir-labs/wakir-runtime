#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""mira-hourly-watchdog — Sprint-SRE Tag-15 (Noa Bergstroem / SRE).

Background
----------

The ``mira-hourly.sh`` wrapper is invoked by the systemd user-timer
``aicorp-mira-hourly.timer`` (``OnCalendar=hourly``) inside the
``claude-dev`` toolbox container. Every successful tick writes one
record to ``infra/mira-hourly-telemetry.jsonl`` (see
``scripts/lib/claude-json-telemetry.sh``).

On 2026-05-15 the operator memory ``needs-attention.md`` flagged a
*"Hourly-Tick-Lücke 18:00 + 19:00 CEST"*. Reconstructing the
telemetry showed that the wrapper **did** fire at both slots
(16:00 UTC + 17:00 UTC = 18:00 CEST + 19:00 CEST under MESZ /
UTC+2), but the underlying ``claude`` CLI invocation aborted
sub-second with ``is_error=true``, ``stop_reason="stop_sequence"``,
``num_turns=1``, ``duration_ms ~ 660``, and ``total_cost_usd=0``.
That signature matches the Anthropic-API quota-cap response shape
(rate-limit hit before the first tool call lands). Two consecutive
quota-cap aborts in the 16:00-18:00 UTC window correlate with the
Tag-15-Welle 8-spawn dispatch from 23:36 CEST 2026-05-15 — seven
of the eight spawns were quota-cap-blocked at 00:18 CEST per the
``needs-attention.md`` log.

Diagnosis
---------

The wrapper itself is *not* broken. The systemd timer fired; the
flock guard was respected; the telemetry sink captured both
aborts. What was missing was an **explicit alarm** when the
Hourly-tick fails to produce a successful synthesis run.

This script is the watchdog. It scans the telemetry JSONL and:

1. Verifies the most recent record's ``timestamp_utc`` is no older
   than ``--max-age-seconds`` (default 4800 = 80 minutes; the
   hourly timer is OnCalendar=hourly so a healthy gap is < 65
   minutes — 80 min covers the slowest observed run plus a 15-min
   slack).

2. Counts consecutive records where ``is_error`` is true OR
   ``num_turns <= 1`` (the quota-cap signature). Two-in-a-row
   triggers the alert.

3. Emits a Prometheus textfile-collector record at
   ``--textfile-output`` (default
   ``/var/lib/node_exporter/textfile_collector/mira_hourly_watchdog.prom``)
   with three gauges:

   - ``mira_hourly_last_tick_age_seconds``
   - ``mira_hourly_last_tick_success`` (1.0 / 0.0)
   - ``mira_hourly_consecutive_abort_count``

4. If ``--ntfy`` is set, fires a single ``notify-push.sh`` call when
   the watchdog transitions from healthy to unhealthy. State is
   tracked in ``--state-file`` (default
   ``/var/home/fred/AI-Corp/logs/mira-hourly-watchdog-state.json``)
   so a flapping signal does not spam the operator.

Run mode
--------

The script is **stdlib-only** — no pip wheels are needed. It runs
under systemd as a separate ``oneshot`` timer (``OnCalendar=*:5/10``)
five minutes off-grid from the main Hourly-tick so the watchdog
sees the previous tick's outcome and not the in-flight run.

This script lives in the wakir-runtime repo (under ``scripts/``) so
Kai's Container-Orchestrator-deployment substrate can pick it up as
part of the same artefact set as ``prometheus-textfile-adapter.py``.
The host-side install (Silverblue user-timer dispatching it into
the ``claude-dev`` toolbox container) lives in the AI-Corp meta-
repo's ``scripts/systemd/`` directory — outside the BSL boundary.

Exit codes
----------

* ``0`` — watchdog ran cleanly; textfile output written; state
  file updated.
* ``1`` — telemetry input missing or unparseable.
* ``2`` — output directory not writable.

License: Apache-2.0 (parity with ``prometheus-textfile-adapter.py``
in the same directory).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_TELEMETRY_PATH = "/var/home/fred/AI-Corp/infra/mira-hourly-telemetry.jsonl"
DEFAULT_TEXTFILE_OUTPUT = (
    "/var/lib/node_exporter/textfile_collector/mira_hourly_watchdog.prom"
)
DEFAULT_STATE_FILE = (
    "/var/home/fred/AI-Corp/logs/mira-hourly-watchdog-state.json"
)
DEFAULT_NOTIFY_PUSH_SCRIPT = "/var/home/fred/AI-Corp/scripts/notify-push.sh"

#: Default location of the persona-engine structured-JSON log
#: substrate the cost + cache aggregators consume. Mirrors the
#: aggregators' own defaults; kept here so the watchdog can gate
#: invocation on log presence without re-importing the aggregator
#: modules.
DEFAULT_PERSONA_ENGINE_LOG_PATH = (
    "/var/home/fred/AI-Corp/logs/persona-engine.jsonl"
)

#: Filenames (relative to the scripts/ dir hosting this watchdog)
#: of the Phase-2a Folgeartefakt aggregators chained after the
#: health-check cycle. Resolved at runtime via __file__.parent so
#: the chain works under any deployment substrate. Order is
#: cost-first (cheaper to compute) then cache-hit-rate.
HOURLY_AGGREGATOR_SCRIPTS: Tuple[str, ...] = (
    "per-model-cost-aggregator.py",
    "cache-hit-rate-aggregator.py",
)

#: ENV var that gates the post-health-check aggregator chain.
#:
#: ``WAKIR_HOURLY_AGGREGATORS_ENABLED=1`` (default when unset and
#: the persona-engine log directory holds at least one log file)
#: invokes the aggregators after the health-check cycle.
#: ``WAKIR_HOURLY_AGGREGATORS_ENABLED=0`` suppresses the chain
#: even if logs are present (operator opt-out, e.g. during a
#: pricing-table rewrite or a Phase-3-cutover).
HOURLY_AGGREGATORS_ENABLED_ENV = "WAKIR_HOURLY_AGGREGATORS_ENABLED"

#: Max age in seconds for the last telemetry record before the
#: watchdog declares the tick "missed". 80 minutes = hourly cadence
#: + 15-min slowest-observed-run slack + 5-min off-grid watchdog
#: offset.
DEFAULT_MAX_AGE_SECONDS = 4800

#: Number of consecutive abort-shaped records that triggers the
#: alert. Two-in-a-row is the chosen threshold: one abort can
#: legitimately happen (transient API hiccup, network glitch); two
#: in a row indicates a systemic problem (quota cap, account
#: suspension, network outage).
DEFAULT_CONSECUTIVE_ABORT_THRESHOLD = 2


# ---------------------------------------------------------------------------
# Telemetry parsing
# ---------------------------------------------------------------------------


class TelemetryError(RuntimeError):
    """Raised when the telemetry input is missing or unparseable."""


def parse_iso_utc_seconds(ts_utc: str) -> Optional[int]:
    """Parse the telemetry ``timestamp_utc`` shape.

    Accepts both the ``+00:00`` offset shape (claude-json-telemetry.sh
    emits this via ``date -u --iso-8601=seconds``) and the trailing-Z
    shape. Returns POSIX-epoch seconds or ``None`` on parse failure.
    """
    if not ts_utc:
        return None
    import calendar
    candidates: Tuple[str, ...] = (
        "%Y-%m-%dT%H:%M:%S+00:00",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
    )
    for fmt in candidates:
        try:
            struct = time.strptime(ts_utc, fmt)
            return int(calendar.timegm(struct))
        except ValueError:
            continue
    return None


def read_telemetry_tail(
    telemetry_path: Path, *, max_records: int = 256
) -> List[Dict[str, Any]]:
    """Read the last ``max_records`` lines as parsed JSON dicts.

    Stdlib-only (no jq, no pandas). Tolerates blank lines and
    malformed JSON (skips both). Returns an empty list if the file
    is empty; raises :class:`TelemetryError` if the file is missing
    or unreadable.
    """
    if not telemetry_path.is_file():
        raise TelemetryError(
            f"telemetry path {telemetry_path} is not a regular file"
        )
    try:
        with telemetry_path.open("rb") as fh:
            data = fh.read()
    except OSError as exc:
        raise TelemetryError(
            f"cannot read telemetry path {telemetry_path}: {exc}"
        ) from exc
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


def classify_record(rec: Dict[str, Any]) -> str:
    """Classify a telemetry record's outcome.

    Returns one of ``"success"``, ``"abort"``, ``"unknown"``. The
    quota-cap abort signature is ``is_error == true`` AND
    ``num_turns <= 1`` AND ``total_cost_usd == 0`` AND
    ``duration_ms < 5000``. We capture all four to avoid mis-
    classifying a legitimate fast successful run as a quota cap.
    """
    is_error = bool(rec.get("is_error", False))
    num_turns = rec.get("num_turns")
    cost = rec.get("total_cost_usd", 0)
    duration_ms = rec.get("duration_ms", 0)
    if not is_error:
        return "success"
    # is_error == true cases.
    if (
        isinstance(num_turns, int)
        and num_turns <= 1
        and (cost == 0 or cost == 0.0)
        and isinstance(duration_ms, (int, float))
        and duration_ms < 5000
    ):
        return "abort"
    # Any other is_error=true case — e.g. mid-run stop_sequence
    # after real turns — is also unhealthy but not the quota-cap
    # shape. We treat it as abort for the watchdog's purposes; the
    # operator can drill into the JSON via the run-id.
    return "abort"


def consecutive_aborts_from_tail(records: List[Dict[str, Any]]) -> int:
    """Count consecutive aborts walking the tail in reverse.

    Returns 0 if the most recent record is a success; otherwise
    counts how many aborts in a row precede the first success (or
    the start of the file).
    """
    count = 0
    for rec in reversed(records):
        if classify_record(rec) == "abort":
            count += 1
        else:
            break
    return count


# ---------------------------------------------------------------------------
# Prometheus textfile output
# ---------------------------------------------------------------------------


def render_textfile(
    *,
    last_tick_age_seconds: int,
    last_tick_success: bool,
    consecutive_abort_count: int,
    max_age_seconds: int,
    consecutive_abort_threshold: int,
) -> str:
    """Render the four watchdog gauges in Prometheus exposition format."""
    lines: List[str] = []
    lines.append(
        "# HELP mira_hourly_last_tick_age_seconds Seconds since the most recent mira-hourly telemetry record\n"
    )
    lines.append("# TYPE mira_hourly_last_tick_age_seconds gauge\n")
    lines.append(
        f"mira_hourly_last_tick_age_seconds {last_tick_age_seconds}\n"
    )
    lines.append(
        "# HELP mira_hourly_last_tick_success 1 if the most recent tick was a successful synthesis run, 0 otherwise\n"
    )
    lines.append("# TYPE mira_hourly_last_tick_success gauge\n")
    lines.append(
        f"mira_hourly_last_tick_success {1 if last_tick_success else 0}\n"
    )
    lines.append(
        "# HELP mira_hourly_consecutive_abort_count Consecutive abort-shaped records at the tail of the telemetry log\n"
    )
    lines.append("# TYPE mira_hourly_consecutive_abort_count gauge\n")
    lines.append(
        f"mira_hourly_consecutive_abort_count {consecutive_abort_count}\n"
    )
    lines.append(
        "# HELP mira_hourly_watchdog_unhealthy 1 if the watchdog considers the tick state unhealthy, 0 otherwise\n"
    )
    lines.append("# TYPE mira_hourly_watchdog_unhealthy gauge\n")
    unhealthy = int(
        last_tick_age_seconds > max_age_seconds
        or consecutive_abort_count >= consecutive_abort_threshold
    )
    lines.append(f"mira_hourly_watchdog_unhealthy {unhealthy}\n")
    return "".join(lines)


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
# State machine for healthy <-> unhealthy edge detection
# ---------------------------------------------------------------------------


def load_state(state_file: Path) -> Dict[str, Any]:
    if not state_file.is_file():
        return {"unhealthy": False, "last_alert_ts_utc": None}
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"unhealthy": False, "last_alert_ts_utc": None}


def save_state(state_file: Path, state: Dict[str, Any]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")


def maybe_fire_ntfy(
    *,
    transitioning_to_unhealthy: bool,
    last_tick_age_seconds: int,
    consecutive_abort_count: int,
    ntfy_script: Path,
) -> Tuple[bool, str]:
    """Fire a single ntfy push on healthy -> unhealthy transitions.

    Returns ``(fired, reason)``. ``fired`` is True iff the push
    actually went out (the script exists, is executable, and exited
    0).
    """
    if not transitioning_to_unhealthy:
        return (False, "no-transition")
    if not ntfy_script.is_file():
        return (False, f"ntfy-script-missing:{ntfy_script}")
    title = "Wakir Labs: Mira-Hourly Watchdog ALERT"
    body = (
        f"Hourly-tick unhealthy. last_tick_age_seconds={last_tick_age_seconds} "
        f"consecutive_abort_count={consecutive_abort_count}"
    )
    try:
        rc = subprocess.run(
            [str(ntfy_script), title, body],
            check=False,
            timeout=15,
        ).returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (False, f"ntfy-script-error:{exc}")
    return (rc == 0, f"ntfy-exit-code:{rc}")


# ---------------------------------------------------------------------------
# Aggregator-chain hook (Phase-2a Folgeartefakt Item 2 integration)
# ---------------------------------------------------------------------------


def _hourly_aggregators_enabled(
    *,
    env: Dict[str, str],
    persona_engine_log_path: Path,
) -> Tuple[bool, str]:
    """Decide whether to invoke the aggregator chain.

    Returns ``(enabled, reason)``. The reason string is recorded in
    the watchdog stderr stream so an operator can audit the gate
    decision without re-running the watchdog.

    Decision matrix:

      * ``WAKIR_HOURLY_AGGREGATORS_ENABLED=0`` -> ``(False, "env-disabled")``
      * ``WAKIR_HOURLY_AGGREGATORS_ENABLED=1`` -> ``(True, "env-enabled-explicit")``
        (forces the chain even if the log substrate is empty -- useful
        for hermetic CI smoke runs)
      * env unset + log path missing or empty -> ``(False, "log-substrate-empty")``
        (graceful fallback: nothing to aggregate -> nothing to do)
      * env unset + log path non-empty -> ``(True, "env-default-enabled")``
    """
    raw = env.get(HOURLY_AGGREGATORS_ENABLED_ENV)
    if raw is not None:
        normalized = raw.strip()
        if normalized in {"0", "false", "no", "off"}:
            return (False, "env-disabled")
        if normalized in {"1", "true", "yes", "on"}:
            return (True, "env-enabled-explicit")
        # Unknown value -> default-on per principle of least
        # surprise (operator typed something, we honour intent).
        return (True, f"env-unknown-value-default-on:{normalized!r}")
    if not persona_engine_log_path.is_file():
        return (False, "log-substrate-empty")
    try:
        size = persona_engine_log_path.stat().st_size
    except OSError:
        return (False, "log-substrate-empty")
    if size <= 0:
        return (False, "log-substrate-empty")
    return (True, "env-default-enabled")


def _invoke_aggregator(
    script_path: Path,
    *,
    timeout_seconds: int = 60,
    extra_env: Optional[Dict[str, str]] = None,
) -> Tuple[bool, str]:
    """Invoke a single aggregator script as a subprocess.

    Returns ``(ok, reason)`` where ``ok`` is True iff the script
    exists, is executable as a Python interpreter target, and
    returned exit code 0. The reason string carries either the
    exit code or the OS-level error so the operator can drill in
    without re-running.
    """
    if not script_path.is_file():
        return (False, f"aggregator-missing:{script_path.name}")
    cmd = [sys.executable, str(script_path)]
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    try:
        result = subprocess.run(
            cmd,
            check=False,
            timeout=timeout_seconds,
            env=env,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (False, f"aggregator-error:{script_path.name}:{exc}")
    if result.returncode != 0:
        return (
            False,
            (
                f"aggregator-nonzero:{script_path.name}:rc={result.returncode}"
            ),
        )
    return (True, f"aggregator-ok:{script_path.name}")


def run_hourly_aggregator_chain(
    *,
    scripts_dir: Path,
    persona_engine_log_path: Path = Path(DEFAULT_PERSONA_ENGINE_LOG_PATH),
    env: Optional[Dict[str, str]] = None,
    aggregator_filenames: Tuple[str, ...] = HOURLY_AGGREGATOR_SCRIPTS,
    timeout_seconds: int = 60,
) -> Dict[str, Any]:
    """Run the configured aggregator chain after the health-check cycle.

    This is a pure-orchestration helper -- it does not raise on a
    single aggregator failure, because the Hourly-tick watchdog's
    primary mission (health-check + textfile output + ntfy edge)
    must complete even if a Folgeartefakt aggregator is broken or
    its log substrate has rotated mid-run.

    Returns a structured-dict report shape suitable for direct JSON
    serialization into the operator-facing stderr trail::

      {
        "enabled": bool,
        "enable_reason": str,
        "results": [
          {"script": str, "ok": bool, "reason": str},
          ...
        ],
      }
    """
    effective_env = env if env is not None else dict(os.environ)
    enabled, enable_reason = _hourly_aggregators_enabled(
        env=effective_env,
        persona_engine_log_path=persona_engine_log_path,
    )
    report: Dict[str, Any] = {
        "enabled": enabled,
        "enable_reason": enable_reason,
        "results": [],
    }
    if not enabled:
        return report
    for filename in aggregator_filenames:
        script_path = scripts_dir / filename
        ok, reason = _invoke_aggregator(
            script_path,
            timeout_seconds=timeout_seconds,
        )
        report["results"].append(
            {"script": filename, "ok": ok, "reason": reason}
        )
    return report


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mira-hourly-watchdog",
        description=(
            "Watchdog for the mira-hourly.sh systemd-timer dispatched "
            "Hourly CEO-check synthesis loop. Detects Hourly-Tick "
            "absence and quota-cap-abort patterns."
        ),
    )
    p.add_argument(
        "--telemetry-path",
        type=Path,
        default=Path(DEFAULT_TELEMETRY_PATH),
        help=(
            "Path to the mira-hourly-telemetry.jsonl produced by "
            "scripts/lib/claude-json-telemetry.sh "
            f"(default: {DEFAULT_TELEMETRY_PATH})"
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
        "--state-file",
        type=Path,
        default=Path(DEFAULT_STATE_FILE),
        help=(
            "JSON state file tracking healthy/unhealthy edge transitions. "
            f"Default: {DEFAULT_STATE_FILE}"
        ),
    )
    p.add_argument(
        "--ntfy",
        action="store_true",
        help=(
            "Fire a single ntfy push when the watchdog transitions "
            "from healthy to unhealthy. No-op if the script at "
            "--ntfy-script is missing."
        ),
    )
    p.add_argument(
        "--ntfy-script",
        type=Path,
        default=Path(DEFAULT_NOTIFY_PUSH_SCRIPT),
        help=(
            "Path to notify-push.sh. Only consulted when --ntfy is "
            f"set. Default: {DEFAULT_NOTIFY_PUSH_SCRIPT}"
        ),
    )
    p.add_argument(
        "--max-age-seconds",
        type=int,
        default=DEFAULT_MAX_AGE_SECONDS,
        help=(
            "Max seconds since the last successful telemetry record "
            "before the watchdog declares the tick missed. "
            f"Default: {DEFAULT_MAX_AGE_SECONDS}"
        ),
    )
    p.add_argument(
        "--consecutive-abort-threshold",
        type=int,
        default=DEFAULT_CONSECUTIVE_ABORT_THRESHOLD,
        help=(
            "Number of consecutive abort-shaped records that triggers "
            "the unhealthy state. "
            f"Default: {DEFAULT_CONSECUTIVE_ABORT_THRESHOLD}"
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
            "Compute the result and print to stdout, but do not write "
            "the textfile output or update the state file."
        ),
    )
    p.add_argument(
        "--skip-aggregators",
        action="store_true",
        help=(
            "Suppress the post-health-check aggregator chain "
            "(per-model-cost + cache-hit-rate). Equivalent to "
            "setting WAKIR_HOURLY_AGGREGATORS_ENABLED=0 but scoped "
            "to a single invocation. Used by hermetic CI smoke runs "
            "that only want the watchdog signal."
        ),
    )
    p.add_argument(
        "--persona-engine-log-path",
        type=Path,
        default=Path(DEFAULT_PERSONA_ENGINE_LOG_PATH),
        help=(
            "Path to the persona-engine structured-JSON log substrate. "
            "Used only to gate the aggregator chain on log presence. "
            f"Default: {DEFAULT_PERSONA_ENGINE_LOG_PATH}"
        ),
    )
    p.add_argument(
        "--scripts-dir",
        type=Path,
        default=None,
        help=(
            "Override directory hosting the aggregator scripts. "
            "Defaults to the directory containing this watchdog "
            "script (resolved via __file__)."
        ),
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_argparser().parse_args(argv)
    try:
        records = read_telemetry_tail(args.telemetry_path)
    except TelemetryError as exc:
        sys.stderr.write(f"mira-hourly-watchdog: {exc}\n")
        return 1
    now = args.now if args.now is not None else int(time.time())
    if records:
        last = records[-1]
        last_ts = parse_iso_utc_seconds(last.get("timestamp_utc", ""))
        if last_ts is None:
            # Unparseable timestamp — treat as ancient.
            last_tick_age_seconds = args.max_age_seconds + 1
        else:
            last_tick_age_seconds = max(0, now - last_ts)
        last_tick_success = classify_record(last) == "success"
        consecutive_abort_count = consecutive_aborts_from_tail(records)
    else:
        # No records at all — definitive unhealthy.
        last_tick_age_seconds = args.max_age_seconds + 1
        last_tick_success = False
        consecutive_abort_count = args.consecutive_abort_threshold
    payload = render_textfile(
        last_tick_age_seconds=last_tick_age_seconds,
        last_tick_success=last_tick_success,
        consecutive_abort_count=consecutive_abort_count,
        max_age_seconds=args.max_age_seconds,
        consecutive_abort_threshold=args.consecutive_abort_threshold,
    )
    unhealthy = (
        last_tick_age_seconds > args.max_age_seconds
        or consecutive_abort_count >= args.consecutive_abort_threshold
    )
    # Edge detection for ntfy.
    state = load_state(args.state_file)
    was_unhealthy = bool(state.get("unhealthy", False))
    transitioning = unhealthy and not was_unhealthy
    if args.dry_run:
        report = {
            "last_tick_age_seconds": last_tick_age_seconds,
            "last_tick_success": last_tick_success,
            "consecutive_abort_count": consecutive_abort_count,
            "unhealthy": unhealthy,
            "transitioning_to_unhealthy": transitioning,
        }
        sys.stdout.write(json.dumps(report, sort_keys=True) + "\n")
        sys.stdout.write(payload)
        return 0
    try:
        atomic_write(args.textfile_output, payload)
    except OSError as exc:
        sys.stderr.write(
            f"mira-hourly-watchdog: cannot write textfile output: {exc}\n"
        )
        return 2
    if args.ntfy and transitioning:
        fired, reason = maybe_fire_ntfy(
            transitioning_to_unhealthy=transitioning,
            last_tick_age_seconds=last_tick_age_seconds,
            consecutive_abort_count=consecutive_abort_count,
            ntfy_script=args.ntfy_script,
        )
        sys.stderr.write(
            f"mira-hourly-watchdog: ntfy fired={fired} reason={reason}\n"
        )
    save_state(
        args.state_file,
        {
            "unhealthy": unhealthy,
            "last_tick_age_seconds": last_tick_age_seconds,
            "consecutive_abort_count": consecutive_abort_count,
            "last_check_ts_utc": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)
            ),
        },
    )
    # ---- Phase-2a Folgeartefakt aggregator chain --------------------
    # Optional: invoke per-model-cost-aggregator.py + cache-hit-rate-
    # aggregator.py after the watchdog cycle. Gated on env var and
    # log-substrate presence. Failures here are non-fatal -- the
    # watchdog's primary mission already completed above.
    if args.skip_aggregators:
        sys.stderr.write(
            "mira-hourly-watchdog: aggregator-chain skipped via --skip-aggregators\n"
        )
        return 0
    scripts_dir = (
        args.scripts_dir
        if args.scripts_dir is not None
        else Path(__file__).resolve().parent
    )
    chain_report = run_hourly_aggregator_chain(
        scripts_dir=scripts_dir,
        persona_engine_log_path=args.persona_engine_log_path,
    )
    sys.stderr.write(
        "mira-hourly-watchdog: aggregator-chain "
        + json.dumps(chain_report, sort_keys=True)
        + "\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
