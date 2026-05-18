#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Mira-Notify Receiver (Phase-3c, Tag-46, Noa SRE).

Context
-------

The Tag-45 Pre-Mortem-Failure-Mode Notify-Catalog
(`docs/observability/pre-mortem-failure-mode-notify-catalog.md`)
specifies that each catalogued alert routes to one or more
side-effects: PagerDuty, ntfy, Activity-Log append, Mira-Hand inbox.
The receiver substance here implements the **Mira-Hand inbox**
materialisation: it reads the JSONL stream written by
`mira-notify-emitter.py` and writes one markdown file per event
to `agents-workspaces/mira/inbox/notify-{timestamp}-{event_id}.md`.

The receiver is intentionally bounded to the Mira-Hand inbox side-
effect. PagerDuty and ntfy fan-out is deferred to a later substance
(Tag-47 candidate); both surfaces require external secrets which
Mira-Sandbox cannot resolve hermetically.

Modes
-----

The receiver supports three input modes:

1. ``--mode=file --input <path.jsonl>`` (default):
   one-shot read of an existing JSONL file (e.g. the snapshot the
   alert-manager wrote, or the emitter's append log).  Useful for
   batch backfill + hermetic-test fixtures.

2. ``--mode=stdin``:
   read JSONL events from stdin until EOF.  Useful for piping from
   the emitter (`mira-notify-emitter.py emit --stdout | receiver
   --mode=stdin`).

3. ``--mode=tail --input <path.jsonl>``:
   tail an append-only JSONL file similarly to ``tail -F``; new lines
   are processed as they arrive.  Position is held in an offset file
   (default ``<input>.receiver-offset``) so a restart resumes where
   the previous run left off.  ``--max-events N`` bounds the loop
   (useful for tests + cron-driven runs).

Dedupe
------

The receiver maintains an on-disk dedupe set
(``<inbox>/.notify-event-ids.txt``); any event whose ``event_id`` is
already in that set is dropped at intake.  Combined with the
emitter's deterministic event_id (hash of alert_name + timestamp +
labels) this lets a Prometheus alert fire repeatedly without
flooding the inbox.

Routing
-------

The materialised inbox file's filename embeds the severity prefix:

* ``severity=page``    -> ``notify-page-{ts}-{event_id}.md``
* ``severity=warning`` -> ``notify-warn-{ts}-{event_id}.md``
* ``severity=info``    -> ``notify-info-{ts}-{event_id}.md``

This lets Mira-Hand's mailbox-glob (e.g. ``inbox/notify-page-*.md``)
prioritise pages without parsing markdown.

Dead-letter
-----------

Events that fail validation are written to
``<inbox>/.notify-dead-letter.jsonl`` with an additional ``_error``
field describing why.  The receiver's exit-code is non-zero iff at
least one event was dead-lettered in the run.

Author: Noa Bergstroem (SRE)
Anchor: Tag-45 catalog PR #292; Tag-46 receiver substance.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator


# ---------------------------------------------------------------------------
# Load the emitter module (validate_event, NotifyEvent) from its
# hyphenated sibling-path.  We re-use the validator instead of
# duplicating field-discipline.
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_EMITTER_PATH = _HERE / "mira-notify-emitter.py"

_spec = importlib.util.spec_from_file_location(
    "mira_notify_emitter", str(_EMITTER_PATH)
)
assert _spec is not None and _spec.loader is not None
emitter = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("mira_notify_emitter", emitter)
_spec.loader.exec_module(emitter)

NotifyEvent = emitter.NotifyEvent
validate_event = emitter.validate_event
VALID_SEVERITIES = emitter.VALID_SEVERITIES


DEFAULT_INBOX = "agents-workspaces/mira/inbox"
DEFAULT_INPUT = "infra/notify-log.jsonl"
DEDUPE_FILENAME = ".notify-event-ids.txt"
DEAD_LETTER_FILENAME = ".notify-dead-letter.jsonl"
OFFSET_SUFFIX = ".receiver-offset"
SEVERITY_PREFIX = {
    "page": "notify-page",
    "warning": "notify-warn",
    "info": "notify-info",
}


# ---------------------------------------------------------------------------
# Pure-function core (no I/O).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IntakeResult:
    """Result of one ``run_intake`` call."""

    materialised: int
    deduped: int
    dead_lettered: int
    inbox_files: list[Path]

    def exit_code(self) -> int:
        return 1 if self.dead_lettered else 0


def parse_event_line(raw: str) -> tuple[NotifyEvent | None, str | None]:
    """Parse one JSONL line into a NotifyEvent.

    Returns ``(event, None)`` on success or ``(None, error_message)``
    on parse / validation failure.
    """
    raw = raw.strip()
    if not raw:
        return None, "empty line"
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"

    if not isinstance(obj, dict):
        return None, "JSON root is not an object"

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
    except Exception as exc:  # noqa: BLE001
        return None, f"cannot construct NotifyEvent: {exc}"

    if not event.event_id:
        return None, "missing event_id"

    errors = validate_event(event)
    if errors:
        return None, "; ".join(errors)
    return event, None


def render_inbox_markdown(event: NotifyEvent) -> str:
    """Render a Mira-Hand inbox markdown file body.

    The format follows the existing `agents-workspaces/mira/inbox/`
    convention: H1 title, YAML-ish header lines, then a free body.
    Operator parses by eye; tools that grep parse by H1 + the
    structured ``event_id``/``alert_name`` lines.
    """
    severity = event.severity.upper()
    title = f"# Mira-Notify [{severity}] - {event.alert_name}"
    failure_mode = event.failure_mode_id or "(none)"
    runbook = event.runbook_url or "(none - severity={})".format(event.severity)

    label_lines = "\n".join(
        f"  {k}: {v}" for k, v in sorted(event.labels.items())
    ) or "  (none)"
    annotation_lines = "\n".join(
        f"  {k}: {v}" for k, v in sorted(event.annotations.items())
    ) or "  (none)"

    description_block = (
        f"\n## Description\n\n{event.description}\n"
        if event.description
        else ""
    )

    return (
        f"{title}\n"
        f"\n"
        f"- event_id: `{event.event_id}`\n"
        f"- alert_name: `{event.alert_name}`\n"
        f"- severity: `{event.severity}`\n"
        f"- fired_at_utc: `{event.fired_at_utc}`\n"
        f"- failure_mode_id: `{failure_mode}`\n"
        f"- runbook: {runbook}\n"
        f"- source: `{event.source}`\n"
        f"\n## Summary\n\n{event.summary}\n"
        f"{description_block}"
        f"\n## Labels\n\n{label_lines}\n"
        f"\n## Annotations\n\n{annotation_lines}\n"
        f"\n---\n"
        f"_Generated by `mira-notify-receiver.py` (Tag-46)._\n"
    )


def inbox_filename(event: NotifyEvent) -> str:
    """Build the inbox filename for an event."""
    prefix = SEVERITY_PREFIX.get(event.severity, "notify")
    # Replace ":" so the filename is portable across filesystems.
    safe_ts = event.fired_at_utc.replace(":", "").replace("-", "")
    return f"{prefix}-{safe_ts}-{event.event_id}.md"


# ---------------------------------------------------------------------------
# I/O helpers.
# ---------------------------------------------------------------------------


def load_dedupe_set(inbox: Path) -> set[str]:
    path = inbox / DEDUPE_FILENAME
    if not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text("utf-8").splitlines()
        if line.strip()
    }


def append_dedupe(inbox: Path, event_id: str) -> None:
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / DEDUPE_FILENAME
    with path.open("a", encoding="utf-8") as fh:
        fh.write(event_id + "\n")


def write_dead_letter(inbox: Path, raw: str, error: str) -> None:
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / DEAD_LETTER_FILENAME
    record = {
        "_error": error,
        "_raw": raw.rstrip("\n"),
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def write_inbox_file(inbox: Path, event: NotifyEvent) -> Path:
    inbox.mkdir(parents=True, exist_ok=True)
    out = inbox / inbox_filename(event)
    out.write_text(render_inbox_markdown(event), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Intake drivers.
# ---------------------------------------------------------------------------


def iter_lines_from_file(path: Path) -> Iterator[str]:
    if not path.exists():
        return iter(())
    return iter(path.read_text("utf-8").splitlines())


def iter_lines_from_stdin() -> Iterator[str]:
    for line in sys.stdin:
        yield line.rstrip("\n")


def iter_lines_tail(
    path: Path,
    offset_path: Path,
    poll_seconds: float = 1.0,
    max_events: int | None = None,
    max_idle_seconds: float | None = None,
    sleep_func=time.sleep,
) -> Iterator[str]:
    """Tail-F a JSONL file from a persisted offset.

    Yields one line at a time.  Stops when ``max_events`` lines have
    been yielded, when ``max_idle_seconds`` of no-new-data elapse,
    or when interrupted.

    The offset file holds a single integer (byte position).  We
    re-read the file each poll cycle from that position; this is
    O(new-bytes) which is acceptable for our throughput regime
    (<10 events/min in normal operation).
    """
    offset = 0
    if offset_path.exists():
        try:
            offset = int(offset_path.read_text("utf-8").strip() or "0")
        except ValueError:
            offset = 0

    yielded = 0
    idle = 0.0
    pending = ""
    while True:
        if not path.exists():
            if max_idle_seconds is not None and idle >= max_idle_seconds:
                return
            sleep_func(poll_seconds)
            idle += poll_seconds
            continue

        with path.open("r", encoding="utf-8") as fh:
            fh.seek(offset)
            chunk = fh.read()
            new_offset = fh.tell()

        if not chunk:
            if max_idle_seconds is not None and idle >= max_idle_seconds:
                return
            if max_events is not None and yielded >= max_events:
                return
            sleep_func(poll_seconds)
            idle += poll_seconds
            continue

        idle = 0.0
        pending += chunk
        while "\n" in pending:
            line, pending = pending.split("\n", 1)
            yield line
            yielded += 1
            if max_events is not None and yielded >= max_events:
                # Persist offset to just past the consumed lines.
                consumed = new_offset - len(pending.encode("utf-8"))
                offset_path.parent.mkdir(parents=True, exist_ok=True)
                offset_path.write_text(str(consumed), encoding="utf-8")
                return
        # Persist offset for next poll.
        offset = new_offset - len(pending.encode("utf-8"))
        offset_path.parent.mkdir(parents=True, exist_ok=True)
        offset_path.write_text(str(offset), encoding="utf-8")


def run_intake(
    lines: Iterable[str],
    inbox: Path,
) -> IntakeResult:
    """Process a stream of JSONL lines into the Mira-Hand inbox.

    Returns counts + list of materialised files.
    """
    dedupe = load_dedupe_set(inbox)
    materialised = 0
    deduped = 0
    dead_lettered = 0
    files: list[Path] = []

    for raw in lines:
        if not raw.strip():
            continue
        event, error = parse_event_line(raw)
        if error is not None or event is None:
            write_dead_letter(inbox, raw, error or "unknown")
            dead_lettered += 1
            continue

        if event.event_id in dedupe:
            deduped += 1
            continue

        out = write_inbox_file(inbox, event)
        files.append(out)
        append_dedupe(inbox, event.event_id)
        dedupe.add(event.event_id)
        materialised += 1

    return IntakeResult(
        materialised=materialised,
        deduped=deduped,
        dead_lettered=dead_lettered,
        inbox_files=files,
    )


# ---------------------------------------------------------------------------
# CLI surface.
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mira-notify-receiver",
        description=(
            "Receive notify-events (JSONL) and materialise Mira-Hand "
            "inbox markdown files."
        ),
    )
    p.add_argument(
        "--mode",
        choices=("file", "stdin", "tail"),
        default="file",
    )
    p.add_argument(
        "--input",
        type=Path,
        default=Path(DEFAULT_INPUT),
        help=f"Input JSONL path for --mode=file/tail (default {DEFAULT_INPUT}).",
    )
    p.add_argument(
        "--inbox",
        type=Path,
        default=Path(DEFAULT_INBOX),
        help=f"Mira-Hand inbox dir (default {DEFAULT_INBOX}).",
    )
    p.add_argument(
        "--offset-file",
        type=Path,
        default=None,
        help="Override offset file path for --mode=tail.",
    )
    p.add_argument(
        "--max-events",
        type=int,
        default=None,
        help="Stop after N events (bounds --mode=tail).",
    )
    p.add_argument(
        "--max-idle-seconds",
        type=float,
        default=None,
        help="Stop --mode=tail after this many idle seconds.",
    )
    p.add_argument(
        "--poll-seconds",
        type=float,
        default=1.0,
        help="Poll interval for --mode=tail.",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-event stderr lines.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.mode == "stdin":
        lines: Iterable[str] = iter_lines_from_stdin()
    elif args.mode == "file":
        lines = iter_lines_from_file(args.input)
    elif args.mode == "tail":
        offset_path = args.offset_file or args.input.with_suffix(
            args.input.suffix + OFFSET_SUFFIX
        )
        lines = iter_lines_tail(
            args.input,
            offset_path,
            poll_seconds=args.poll_seconds,
            max_events=args.max_events,
            max_idle_seconds=args.max_idle_seconds,
        )
    else:  # pragma: no cover - argparse guards this
        return 2

    result = run_intake(lines, args.inbox)

    if not args.quiet:
        print(
            f"intake done: materialised={result.materialised} "
            f"deduped={result.deduped} "
            f"dead_lettered={result.dead_lettered}",
            file=sys.stderr,
        )
        for f in result.inbox_files:
            print(f"  -> {f}", file=sys.stderr)

    return result.exit_code()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
