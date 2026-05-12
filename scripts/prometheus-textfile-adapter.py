#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Prometheus textfile-collector adapter for the orchestrator health checks.

This adapter consumes the JSON report emitted by either of the two
Sprint-2 health-check tools and rewrites it into the Prometheus
node_exporter ``textfile_collector`` format. It is deliberately
small (single-pass, stdlib-only) and runs as a systemd-timer-driven
``oneshot`` after the corresponding health-check unit finishes.

Pipeline:

    health-check.py --> /var/log/wakir/<name>.json
                    --> prometheus-textfile-adapter.py --> /var/lib/node_exporter/textfile_collector/<name>.prom
                    (read by node_exporter, scraped by Prometheus)

The adapter is designed for the documented JSON contracts:

* ``check-nats-kv-health.py`` — top-level keys ``servers``,
  ``jsz_url``, ``dry_run``, ``jsz``, ``summary`` (counters
  ok/missing/drift/error/total), ``checks`` (per-bucket records).

* ``check-federation-evaluator-health.py`` — top-level keys
  ``bucket``, ``bucket_name``, ``dry_run``, ``evaluator``, ``jsz``,
  ``jsz_url``, ``servers``, ``snapshot`` (counters total/active/
  expired/not_yet_active/with_wat_anchor + ``poisoned_keys`` list).

The adapter detects the report flavour by inspecting the top-level
keys. Both flavours emit the same set of "transport" gauges (jsz_up,
substrate_reachable) so an alert rule that fires on either tool
becomes uniform.

Atomic write contract: the textfile_collector requires that the
target file is written atomically (rename over). The adapter writes
to a temporary sibling file and ``os.replace``-s into place. A
partial read by node_exporter is therefore impossible.

Exit codes:

* ``0`` -- adapter ran cleanly; output file was written.
* ``1`` -- input JSON missing, malformed, or unknown flavour;
  output file is left untouched.
* ``2`` -- output directory is not writable.

The adapter never opens a network socket and never imports
``nats``-anything; it is a pure JSON-to-Prometheus translator.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable, Mapping


# ---------------------------------------------------------------------
# Metric writer helpers (Prometheus exposition format §0.0.4)
# ---------------------------------------------------------------------


def _help(metric: str, text: str) -> str:
    return f"# HELP {metric} {text}\n"


def _type(metric: str, kind: str) -> str:
    return f"# TYPE {metric} {kind}\n"


def _label(value: str) -> str:
    """Quote a label value per the Prometheus exposition format.

    Backslash, double-quote, and newline must be escaped. The input is
    expected to be a short identifier (bucket name, route id), so we
    keep the implementation deliberately minimal.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _line(metric: str, labels: Mapping[str, str], value: float) -> str:
    if labels:
        rendered = ",".join(
            f'{k}="{_label(v)}"' for k, v in sorted(labels.items())
        )
        return f"{metric}{{{rendered}}} {value}\n"
    return f"{metric} {value}\n"


# ---------------------------------------------------------------------
# Flavour detection
# ---------------------------------------------------------------------


FLAVOUR_NATS_KV = "nats_kv"
FLAVOUR_FEDERATION = "federation_evaluator"


def detect_flavour(report: Mapping[str, Any]) -> str:
    """Identify which health-check emitted ``report``.

    The two shapes are disjoint at the top level: ``checks`` is a
    NATS-KV invariant; ``snapshot`` and ``bucket_name`` are
    federation-evaluator invariants. Reject ambiguous or unknown
    payloads with ``ValueError``.
    """
    has_checks = "checks" in report and "summary" in report
    has_snapshot = "snapshot" in report and "bucket_name" in report
    if has_checks and not has_snapshot:
        return FLAVOUR_NATS_KV
    if has_snapshot and not has_checks:
        return FLAVOUR_FEDERATION
    raise ValueError(
        "report does not match either documented flavour "
        "(nats-kv-health or federation-evaluator-health)"
    )


# ---------------------------------------------------------------------
# Render: NATS-KV
# ---------------------------------------------------------------------


def _jsz_up(jsz_block: Mapping[str, Any]) -> int:
    return 1 if jsz_block.get("status") == "ok" else 0


def _bucket_status_value(status: str) -> int:
    """Numeric encoding of the per-bucket status enum.

    Stable across releases; the cron consumer can rely on the integer
    space.
    """
    return {
        "ok": 0,
        "missing": 1,
        "drift": 2,
        "error": 3,
    }.get(status, -1)


def render_nats_kv(report: Mapping[str, Any]) -> str:
    """Translate a NATS-KV health-check report to textfile format."""
    out: list[str] = []
    summary = report.get("summary", {})
    jsz = report.get("jsz", {})
    servers = str(report.get("servers", ""))

    out.append(_help("wakir_nats_kv_jsz_up",
                     "1 if /jsz HTTP probe returned 2xx, else 0"))
    out.append(_type("wakir_nats_kv_jsz_up", "gauge"))
    out.append(_line("wakir_nats_kv_jsz_up", {"servers": servers},
                     _jsz_up(jsz)))

    out.append(_help("wakir_nats_kv_buckets_total",
                     "Total documented buckets in the inventory"))
    out.append(_type("wakir_nats_kv_buckets_total", "gauge"))
    out.append(_line("wakir_nats_kv_buckets_total", {},
                     int(summary.get("total", 0))))

    for status_key in ("ok", "missing", "drift", "error"):
        metric = f"wakir_nats_kv_buckets_{status_key}"
        out.append(_help(metric,
                         f"Number of buckets in '{status_key}' state"))
        out.append(_type(metric, "gauge"))
        out.append(_line(metric, {}, int(summary.get(status_key, 0))))

    out.append(_help("wakir_nats_kv_bucket_status",
                     "Per-bucket status (0=ok 1=missing 2=drift 3=error)"))
    out.append(_type("wakir_nats_kv_bucket_status", "gauge"))
    for check in report.get("checks", []):
        if not isinstance(check, Mapping):
            continue
        name = str(check.get("name", ""))
        status = str(check.get("status", "error"))
        out.append(_line("wakir_nats_kv_bucket_status",
                         {"bucket": name},
                         _bucket_status_value(status)))

    return "".join(out)


# ---------------------------------------------------------------------
# Render: federation-evaluator
# ---------------------------------------------------------------------


def _bucket_block_value(status: str) -> int:
    return {
        "ok": 0,
        "missing": 1,
        "drift": 2,
        "error": 3,
    }.get(status, -1)


def _evaluator_value(status: str) -> int:
    return {
        "ok": 0,
        "skipped": 1,
        "reject": 2,
        "error": 3,
    }.get(status, -1)


def render_federation(report: Mapping[str, Any]) -> str:
    """Translate a federation-evaluator report to textfile format."""
    out: list[str] = []
    snapshot = report.get("snapshot", {})
    bucket = report.get("bucket", {})
    evaluator = report.get("evaluator", {})
    jsz = report.get("jsz", {})
    servers = str(report.get("servers", ""))
    bucket_name = str(report.get("bucket_name", ""))

    out.append(_help("wakir_federation_evaluator_jsz_up",
                     "1 if /jsz HTTP probe returned 2xx, else 0"))
    out.append(_type("wakir_federation_evaluator_jsz_up", "gauge"))
    out.append(_line("wakir_federation_evaluator_jsz_up",
                     {"servers": servers}, _jsz_up(jsz)))

    out.append(_help("wakir_federation_evaluator_bucket_status",
                     "Federation-routes bucket status "
                     "(0=ok 1=missing 2=drift 3=error)"))
    out.append(_type("wakir_federation_evaluator_bucket_status", "gauge"))
    out.append(_line("wakir_federation_evaluator_bucket_status",
                     {"bucket": bucket_name},
                     _bucket_block_value(str(bucket.get("status", "error")))))

    for key in ("total", "active", "expired", "not_yet_active",
                "with_wat_anchor"):
        metric = f"wakir_federation_evaluator_routes_{key}"
        out.append(_help(metric,
                         f"Federation route registry counter '{key}'"))
        out.append(_type(metric, "gauge"))
        out.append(_line(metric, {}, int(snapshot.get(key, 0) or 0)))

    poisoned = snapshot.get("poisoned_keys") or []
    out.append(_help("wakir_federation_evaluator_poisoned_keys_total",
                     "Number of registry keys flagged as poisoned"))
    out.append(_type("wakir_federation_evaluator_poisoned_keys_total",
                     "gauge"))
    out.append(_line("wakir_federation_evaluator_poisoned_keys_total",
                     {}, len(poisoned)))

    out.append(_help("wakir_federation_evaluator_probe_status",
                     "Optional N2-evaluator probe "
                     "(0=ok 1=skipped 2=reject 3=error)"))
    out.append(_type("wakir_federation_evaluator_probe_status", "gauge"))
    out.append(_line("wakir_federation_evaluator_probe_status", {},
                     _evaluator_value(str(evaluator.get("status",
                                                        "skipped")))))

    return "".join(out)


# ---------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------


def render(report: Mapping[str, Any], *, now: float | None = None) -> str:
    """Render ``report`` to textfile format, prefixed with a write
    stamp so a stuck adapter is observable in Prometheus.
    """
    flavour = detect_flavour(report)
    if flavour == FLAVOUR_NATS_KV:
        body = render_nats_kv(report)
    elif flavour == FLAVOUR_FEDERATION:
        body = render_federation(report)
    else:  # pragma: no cover (detect_flavour raises on unknown)
        raise ValueError(f"unknown flavour: {flavour}")

    ts = float(now) if now is not None else time.time()
    head: list[str] = []
    head.append(_help(
        f"wakir_{flavour}_adapter_last_run_seconds",
        "Unix timestamp of the most recent adapter run "
        "(monotonic on a single host, used to alert on stale outputs)",
    ))
    head.append(_type(f"wakir_{flavour}_adapter_last_run_seconds", "gauge"))
    head.append(_line(f"wakir_{flavour}_adapter_last_run_seconds", {}, ts))
    return "".join(head) + body


def write_atomic(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically.

    The textfile_collector requires that node_exporter never observes
    a partial file. We achieve this with a temp file in the target
    directory followed by ``os.replace`` (atomic on POSIX when source
    and dest are on the same filesystem).
    """
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(prefix=path.name + ".", dir=str(parent))
    tmp = Path(tmp_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


def _parse_args(argv: Iterable[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="prometheus-textfile-adapter.py",
        description=(
            "Translate a Wakir orchestrator health-check JSON report "
            "to Prometheus textfile-collector format."
        ),
    )
    p.add_argument(
        "--input", "-i", required=True, type=Path,
        help="Path to the health-check JSON report (read-only).",
    )
    p.add_argument(
        "--output", "-o", required=True, type=Path,
        help=(
            "Path to the textfile-collector .prom output (atomic "
            "rename target). Parent directory is created if missing."
        ),
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Render to stdout; do not touch the output path.",
    )
    return p.parse_args(list(argv))


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    try:
        with args.input.open("r", encoding="utf-8") as fh:
            report = json.load(fh)
    except FileNotFoundError:
        print(f"adapter: input not found: {args.input}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"adapter: input is not valid JSON: {exc}", file=sys.stderr)
        return 1

    try:
        content = render(report)
    except ValueError as exc:
        print(f"adapter: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        sys.stdout.write(content)
        return 0

    try:
        write_atomic(args.output, content)
    except (OSError, PermissionError) as exc:
        print(f"adapter: cannot write {args.output}: {exc}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
