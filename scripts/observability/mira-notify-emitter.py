#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Mira-Notify Emitter (Phase-3c, Tag-46, Noa SRE).

Context
-------

The Tag-45 Pre-Mortem-Failure-Mode Notify-Catalog
(`docs/observability/pre-mortem-failure-mode-notify-catalog.md`)
maps each Henrik Tag-44 Pre-Mortem failure-mode to a Prometheus
alert rule, severity, runbook anchor and notify-path.  The catalog
specifies *what* should happen on a fire; this emitter is the
substance that produces a uniformly-formatted notify-event so
heterogeneous internal tools (Aggregator-Failure-Rate-Tracker,
Cutover-Day-Live-Stream-Aggregator, Pre-Cutover-Probe-Tracker,
Bilanz-Generator) can emit the same envelope without each
re-implementing field-naming and timestamp-discipline.

The companion `mira-notify-receiver.py` consumes the JSONL stream
this emitter writes (one event per line) and materialises Mira-Hand
inbox markdown files in `agents-workspaces/mira/inbox/`.

Scope of this emitter
---------------------

This is the *producer* side and is intentionally stdlib-only.  It
exposes two surfaces:

1. **Library API** (`emit_notify`, `make_event`, `validate_event`):
   call from another Python tool to produce a structured
   notify-event without shelling out.

2. **CLI** (`python mira-notify-emitter.py emit --severity page
   --alert-name ... --summary ... --runbook ...`):
   one-shot emission for shell-script callers (cutover-day-watch.sh,
   ad-hoc Operator-Hand emission).

In both surfaces the output is one JSON object written to:

* a JSONL append-stream (default `infra/notify-log.jsonl`), and
* optionally `stdout` (for piping to the receiver in --mode=stdin).

The emitter performs only the produce step.  It does not route to
PagerDuty or ntfy directly; those side-effects are the receiver's
responsibility once a Mira-Hand-inbox materialisation is durable.

Field schema
------------

The notify-event JSON object has the following fields:

* ``schema_version`` (str): currently ``"1"``.
* ``event_id`` (str): caller-supplied OR derived from
  ``sha256(alert_name|fired_at_utc|labels-json)`` (deterministic so
  receiver can dedupe).
* ``alert_name`` (str): exact Prometheus alert-name from catalog
  (Section 2 of `pre-mortem-failure-mode-notify-catalog.md`).
* ``severity`` (str): one of ``page``, ``warning``, ``info``.
  Severity ``page`` -> Mira-Hand-inbox (high priority) + ntfy + AR
  ticker.  Severity ``warning`` -> Mira-Hand-inbox (normal) + ntfy
  only.  Severity ``info`` -> Mira-Hand-inbox (low) only.
* ``fired_at_utc`` (str, ISO-8601 with ``Z``-suffix): the time the
  alert went active.  Caller supplies this; if absent the emitter
  fills in ``now``.
* ``failure_mode_id`` (str | null): Henrik Pre-Mortem ID (e.g. "A1",
  "C1").  Null when the notify is not catalogued (free-form).
* ``runbook_url`` (str | null): URL where the operator finds the
  response procedure.  Required for ``severity=page``.
* ``summary`` (str): one-line human description (<=200 chars).
* ``description`` (str | null): multi-line body, optional.
* ``labels`` (dict[str, str]): Prometheus-style labels copied through
  unmodified.  Used by receiver for dedupe + routing.
* ``annotations`` (dict[str, str]): optional extra fields.
* ``source`` (str): emitter-id; one of
  ``mira-notify-emitter``, ``aggregator-failure-rate-tracker``,
  ``cutover-day-live-stream-aggregator``, ``operator-hand``,
  or a free string.

The receiver validates these fields strictly.  An event with a
missing required field is logged to the receiver's dead-letter
file and **does NOT** materialise a Mira-Hand inbox entry.

Determinism + idempotency
-------------------------

The emitter is purposely deterministic: same input -> same
``event_id`` -> receiver dedupes on a second emission of the same
event.  This matters because Prometheus alert-rules in
``phase-3-marathon-alerts.yaml`` can fire repeatedly while the
underlying condition persists; without dedupe the Mira-Hand inbox
would flood.

Author: Noa Bergstroem (SRE)
Anchor: Tag-45 catalog PR #292; Tag-46 receiver substance.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "1"
DEFAULT_NOTIFY_LOG = "infra/notify-log.jsonl"
VALID_SEVERITIES = ("page", "warning", "info")
MAX_SUMMARY_LEN = 200


# ---------------------------------------------------------------------------
# Pure-function core (no I/O).  These are unit-tested in
# tests/observability/test_mira_notify_emitter.py.
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class NotifyEvent:
    """Validated notify-event payload.

    Use :func:`make_event` to construct; the dataclass is frozen so
    callers cannot mutate a validated instance.
    """

    schema_version: str
    event_id: str
    alert_name: str
    severity: str
    fired_at_utc: str
    failure_mode_id: str | None
    runbook_url: str | None
    summary: str
    description: str | None
    labels: Mapping[str, str]
    annotations: Mapping[str, str]
    source: str

    def to_dict(self) -> dict[str, Any]:
        """Render as a JSON-serialisable dict (sorted keys via json.dumps)."""
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "alert_name": self.alert_name,
            "severity": self.severity,
            "fired_at_utc": self.fired_at_utc,
            "failure_mode_id": self.failure_mode_id,
            "runbook_url": self.runbook_url,
            "summary": self.summary,
            "description": self.description,
            "labels": dict(self.labels),
            "annotations": dict(self.annotations),
            "source": self.source,
        }

    def to_jsonl_line(self) -> str:
        """Render as a single JSONL line (terminated with ``\\n``)."""
        return json.dumps(self.to_dict(), sort_keys=True) + "\n"


def now_utc_iso() -> str:
    """Return current UTC time as ISO-8601 with ``Z`` suffix.

    Separate function so tests can monkey-patch via the module-level
    name without monkey-patching ``datetime.datetime``.
    """
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def derive_event_id(
    alert_name: str,
    fired_at_utc: str,
    labels: Mapping[str, str],
) -> str:
    """Deterministic event-id derivation.

    The id is the SHA-256 of ``alert_name|fired_at_utc|sorted-labels``
    truncated to 16 hex chars.  Same input -> same id, so the
    receiver dedupes idempotently.
    """
    labels_json = json.dumps(dict(labels), sort_keys=True)
    payload = f"{alert_name}|{fired_at_utc}|{labels_json}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def validate_event(event: NotifyEvent) -> list[str]:
    """Return a list of validation-error messages (empty == OK)."""
    errors: list[str] = []

    if event.schema_version != SCHEMA_VERSION:
        errors.append(
            f"schema_version must be {SCHEMA_VERSION!r}, "
            f"got {event.schema_version!r}"
        )

    if not event.alert_name or not isinstance(event.alert_name, str):
        errors.append("alert_name must be a non-empty string")

    if event.severity not in VALID_SEVERITIES:
        errors.append(
            f"severity must be one of {VALID_SEVERITIES}, "
            f"got {event.severity!r}"
        )

    if not event.fired_at_utc.endswith("Z"):
        errors.append(
            "fired_at_utc must be ISO-8601 with Z suffix, "
            f"got {event.fired_at_utc!r}"
        )

    if not event.summary:
        errors.append("summary must be a non-empty string")
    elif len(event.summary) > MAX_SUMMARY_LEN:
        errors.append(
            f"summary length {len(event.summary)} exceeds "
            f"limit {MAX_SUMMARY_LEN}"
        )

    if event.severity == "page" and not event.runbook_url:
        errors.append("runbook_url is required for severity=page")

    # Labels must be a string->string mapping.
    for k, v in event.labels.items():
        if not isinstance(k, str) or not isinstance(v, str):
            errors.append(
                f"labels entry {k!r}={v!r} must be string->string"
            )
            break

    return errors


def make_event(
    *,
    alert_name: str,
    severity: str,
    summary: str,
    runbook_url: str | None = None,
    failure_mode_id: str | None = None,
    description: str | None = None,
    labels: Mapping[str, str] | None = None,
    annotations: Mapping[str, str] | None = None,
    source: str = "mira-notify-emitter",
    fired_at_utc: str | None = None,
    event_id: str | None = None,
) -> NotifyEvent:
    """Construct + validate a NotifyEvent.

    Raises :class:`ValueError` if validation fails.
    """
    labels = dict(labels or {})
    annotations = dict(annotations or {})
    fired_at_utc = fired_at_utc or now_utc_iso()
    event_id = event_id or derive_event_id(alert_name, fired_at_utc, labels)

    event = NotifyEvent(
        schema_version=SCHEMA_VERSION,
        event_id=event_id,
        alert_name=alert_name,
        severity=severity,
        fired_at_utc=fired_at_utc,
        failure_mode_id=failure_mode_id,
        runbook_url=runbook_url,
        summary=summary,
        description=description,
        labels=labels,
        annotations=annotations,
        source=source,
    )
    errors = validate_event(event)
    if errors:
        raise ValueError("invalid notify event: " + "; ".join(errors))
    return event


# ---------------------------------------------------------------------------
# I/O surface (small, isolated for testability).
# ---------------------------------------------------------------------------


def append_jsonl(path: Path, line: str) -> None:
    """Atomically append a single JSONL line.

    The append is a single ``write()`` of ``line`` (which already ends
    in ``\\n``).  We use ``open(..., "a")`` which is atomic for writes
    smaller than ``PIPE_BUF`` on POSIX (>=4 kB on Linux); our lines
    are bounded by MAX_SUMMARY_LEN + label-bytes <= ~2 kB.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def emit_notify(
    event: NotifyEvent,
    *,
    log_path: Path | None = None,
    also_stdout: bool = False,
) -> str:
    """Persist + optionally echo a notify-event.

    Returns the event_id of the emitted event.
    """
    line = event.to_jsonl_line()
    if log_path is not None:
        append_jsonl(log_path, line)
    if also_stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
    return event.event_id


# ---------------------------------------------------------------------------
# CLI surface.
# ---------------------------------------------------------------------------


def _kv_pairs(argv: list[str]) -> dict[str, str]:
    """Parse ``key=value`` pairs from a list (CLI flag --labels)."""
    out: dict[str, str] = {}
    for item in argv:
        if "=" not in item:
            raise SystemExit(
                f"--labels/--annotations entries must be key=value, got {item!r}"
            )
        k, v = item.split("=", 1)
        out[k] = v
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mira-notify-emitter",
        description="Emit a uniformly-formatted Mira-Notify event.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    emit = sub.add_parser("emit", help="Emit a single notify-event.")
    emit.add_argument("--alert-name", required=True)
    emit.add_argument(
        "--severity",
        required=True,
        choices=list(VALID_SEVERITIES),
    )
    emit.add_argument("--summary", required=True)
    emit.add_argument("--runbook", default=None, dest="runbook_url")
    emit.add_argument("--failure-mode-id", default=None)
    emit.add_argument("--description", default=None)
    emit.add_argument("--source", default="operator-hand")
    emit.add_argument(
        "--labels",
        nargs="*",
        default=[],
        help="Key=value pairs (Prometheus-style labels).",
    )
    emit.add_argument(
        "--annotations",
        nargs="*",
        default=[],
        help="Key=value pairs (optional extra fields).",
    )
    emit.add_argument(
        "--log-path",
        type=Path,
        default=Path(DEFAULT_NOTIFY_LOG),
        help=f"JSONL append-path (default {DEFAULT_NOTIFY_LOG}).",
    )
    emit.add_argument(
        "--stdout",
        action="store_true",
        help="Also echo the JSONL line to stdout.",
    )
    emit.add_argument(
        "--fired-at-utc",
        default=None,
        help="Override the fired-at timestamp (ISO-8601 Z).",
    )

    validate = sub.add_parser(
        "validate", help="Validate a JSONL file of notify events."
    )
    validate.add_argument("path", type=Path)

    return p


def cmd_emit(args: argparse.Namespace) -> int:
    try:
        event = make_event(
            alert_name=args.alert_name,
            severity=args.severity,
            summary=args.summary,
            runbook_url=args.runbook_url,
            failure_mode_id=args.failure_mode_id,
            description=args.description,
            labels=_kv_pairs(args.labels),
            annotations=_kv_pairs(args.annotations),
            source=args.source,
            fired_at_utc=args.fired_at_utc,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    eid = emit_notify(event, log_path=args.log_path, also_stdout=args.stdout)
    print(f"emitted event_id={eid} severity={event.severity}", file=sys.stderr)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    if not args.path.exists():
        print(f"ERROR: file not found: {args.path}", file=sys.stderr)
        return 2
    bad = 0
    total = 0
    for lineno, raw in enumerate(args.path.read_text("utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        total += 1
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"line {lineno}: invalid JSON ({exc})", file=sys.stderr)
            bad += 1
            continue
        try:
            event = NotifyEvent(
                schema_version=obj.get("schema_version", ""),
                event_id=obj.get("event_id", ""),
                alert_name=obj.get("alert_name", ""),
                severity=obj.get("severity", ""),
                fired_at_utc=obj.get("fired_at_utc", ""),
                failure_mode_id=obj.get("failure_mode_id"),
                runbook_url=obj.get("runbook_url"),
                summary=obj.get("summary", ""),
                description=obj.get("description"),
                labels=obj.get("labels", {}),
                annotations=obj.get("annotations", {}),
                source=obj.get("source", ""),
            )
        except Exception as exc:  # noqa: BLE001 - explicit operator surface
            print(f"line {lineno}: cannot construct ({exc})", file=sys.stderr)
            bad += 1
            continue
        errors = validate_event(event)
        if errors:
            print(f"line {lineno}: {'; '.join(errors)}", file=sys.stderr)
            bad += 1
    print(f"validated {total} event(s); {bad} invalid", file=sys.stderr)
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "emit":
        return cmd_emit(args)
    if args.cmd == "validate":
        return cmd_validate(args)
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
