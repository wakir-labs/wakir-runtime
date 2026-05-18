#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Mira-Notify Dead-Letter-Queue + Replay CLI (Phase-3c, Tag-51, Noa SRE).

Context
-------

Tag-46 PR #296 shipped the Mira-Notify Emitter + Receiver substance.
The receiver writes events that fail intake (invalid JSON, missing
event_id, validation errors) to a per-inbox dead-letter file
(``<inbox>/.notify-dead-letter.jsonl``) and proceeds with the rest of
the stream.  At that time, the dead-letter file was a leaf-of-line
artefact: written, never inspected, never replayed.

The Tag-49 Pre-Mortem-Coverage-Sweep and the Tag-50 Welle-N-Specific
Alert-Rules raised the alert-rule count to 18 distinct alarms, each
of which can route through the emitter.  The Marathon-Day window
(Tag-44..49 plus Cutover-Day) puts the notify-pipeline under
sustained load: a transient producer-side bug, a schema-version
mismatch during a rolling upgrade, or a labels-shape regression
upstream can populate the dead-letter file with tens of events that
*should* have materialised inbox entries but did not.

Without a replay path, dead-lettered events stay invisible to
Mira-Hand: the operator may never see that A1-Welle-3-Bridge-Drift
fired during Wave-3 because the matching emitter version had a typo
in ``severity``.  This is an SRE-grade reliability gap: the system
silently drops alerts.

Scope of this tool
------------------

A single stdlib-only CLI with three sub-commands:

1. **``inspect``** -- summarise the dead-letter file:

   * Total dead-lettered events.
   * Histogram of error categories (parse-error vs.
     validation-error vs. missing-event-id).
   * Histogram by alert-name (when extractable).
   * Earliest + latest dead-letter timestamps (from the raw payload
     ``fired_at_utc`` when available, otherwise ``(unknown)``).
   * JSON or Markdown output.

2. **``replay``** -- attempt to re-process dead-lettered events:

   * Read ``<inbox>/.notify-dead-letter.jsonl``.
   * For each record, try to parse the original ``_raw`` payload.
   * Apply zero or more **patch rules** (CLI flags) to repair the
     payload before re-validation.  Patches are deliberately
     restricted to well-defined, low-risk repairs (set
     schema_version, fill missing fired_at_utc, force severity
     normalisation).
   * Re-attempt receiver intake; on success, write a normal inbox
     file and **remove** the record from the dead-letter file.  On
     failure, leave the record in place (the dead-letter file
     remains the source of truth for un-recoverable events).
   * ``--dry-run`` does not mutate the dead-letter file (default
     ``--dry-run`` is True; replay requires explicit ``--apply``).

3. **``prune``** -- evacuate already-resolved entries:

   * Drop records whose ``event_id`` (derivable from the raw
     payload after patches) is in the inbox dedupe-set (i.e. the
     event was materialised via a later emitter run).
   * Useful after a producer-side fix re-emits the corrected event;
     the dead-letter copy is now redundant.

Determinism + idempotency
-------------------------

Like the emitter and receiver, this tool is stdlib-only and
deterministic.  Repeated ``replay --apply`` invocations are
idempotent: events successfully replayed in run N are no longer
present in the dead-letter file when run N+1 starts.

The tool never invents data: a record that cannot be repaired by an
explicitly-named patch rule is left untouched.  The operator must
diagnose why the event was malformed at the source.

Sandbox posture
---------------

Strict hermetic: stdlib only.  No network egress, no podman, no
filesystem writes outside ``--inbox`` and the dead-letter file's
parent directory.  All tests use ``tmp_path`` to enforce isolation.

Anchor
------

* Tag-46 PR #296: emitter + receiver substance (the source of the
  dead-letter file).
* Tag-50 PR #324: 18 Welle-N alert-rules (the load profile that
  motivates a DLQ-replay path).
* This tool, Tag-51: closes the dead-letter -> inbox loop.

Author: Noa Bergstroem (SRE)
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Load sibling emitter + receiver modules from their hyphenated paths.
# The DLQ tool reuses NotifyEvent / validate_event / parse_event_line /
# render_inbox_markdown / inbox_filename rather than duplicating field
# discipline.  This keeps the schema authoritative in one place.
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_EMITTER_PATH = _HERE / "mira-notify-emitter.py"
_RECEIVER_PATH = _HERE / "mira-notify-receiver.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


emitter = _load_module("mira_notify_emitter", _EMITTER_PATH)
receiver = _load_module("mira_notify_receiver", _RECEIVER_PATH)

NotifyEvent = emitter.NotifyEvent
make_event = emitter.make_event
validate_event = emitter.validate_event
derive_event_id = emitter.derive_event_id
now_utc_iso = emitter.now_utc_iso
SCHEMA_VERSION = emitter.SCHEMA_VERSION
VALID_SEVERITIES = emitter.VALID_SEVERITIES

parse_event_line = receiver.parse_event_line
render_inbox_markdown = receiver.render_inbox_markdown
inbox_filename = receiver.inbox_filename
load_dedupe_set = receiver.load_dedupe_set
append_dedupe = receiver.append_dedupe
write_inbox_file = receiver.write_inbox_file

DEAD_LETTER_FILENAME = receiver.DEAD_LETTER_FILENAME
DEDUPE_FILENAME = receiver.DEDUPE_FILENAME


# ---------------------------------------------------------------------------
# Error categorisation.  parse_event_line returns a freeform error
# string; we classify these into a small bounded set for the inspect
# histogram so the operator sees patterns (e.g. "90% of dead-letters
# are missing schema_version") rather than 100 unique strings.
# ---------------------------------------------------------------------------


ERROR_CATEGORY_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^empty line$"), "empty_line"),
    (re.compile(r"invalid JSON"), "invalid_json"),
    (re.compile(r"JSON root is not an object"), "json_root_not_object"),
    (re.compile(r"cannot construct NotifyEvent"), "construct_error"),
    (re.compile(r"^missing event_id$"), "missing_event_id"),
    (re.compile(r"schema_version must be"), "schema_version_mismatch"),
    (re.compile(r"alert_name must be"), "missing_alert_name"),
    (re.compile(r"severity must be one of"), "invalid_severity"),
    (re.compile(r"fired_at_utc must be"), "invalid_fired_at_utc"),
    (re.compile(r"summary must be"), "missing_summary"),
    (re.compile(r"summary length"), "summary_too_long"),
    (re.compile(r"runbook_url is required"), "missing_runbook_for_page"),
    (re.compile(r"labels entry"), "invalid_labels_shape"),
]


def classify_error(error: str) -> str:
    """Map a freeform error string into one of a bounded set of categories."""
    for pat, cat in ERROR_CATEGORY_RULES:
        if pat.search(error):
            return cat
    return "other"


# ---------------------------------------------------------------------------
# Pure-function core (no I/O).
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class DeadLetterRecord:
    """A single record from ``.notify-dead-letter.jsonl``.

    The on-disk format is ``{"_error": "...", "_raw": "{...}"}`` as
    written by ``mira-notify-receiver.write_dead_letter``.  We parse
    this envelope and (lazily, when needed) the inner raw payload.
    """

    error: str
    raw: str
    line_no: int  # 1-based index in the dead-letter file (provenance)

    def category(self) -> str:
        return classify_error(self.error)

    def inner_obj(self) -> dict[str, Any] | None:
        """Best-effort parse of the inner raw payload.

        Returns ``None`` when the raw payload itself is not JSON
        (the producer wrote garbage).  In that case there is nothing
        the replay path can do without operator-supplied repair.
        """
        try:
            obj = json.loads(self.raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(obj, dict):
            return None
        return obj

    def alert_name(self) -> str | None:
        obj = self.inner_obj()
        if obj is None:
            return None
        v = obj.get("alert_name")
        return v if isinstance(v, str) and v else None

    def fired_at_utc(self) -> str | None:
        obj = self.inner_obj()
        if obj is None:
            return None
        v = obj.get("fired_at_utc")
        return v if isinstance(v, str) and v else None


def read_dead_letter_file(path: Path) -> list[DeadLetterRecord]:
    """Read + parse the dead-letter envelope JSONL into records."""
    if not path.exists():
        return []
    records: list[DeadLetterRecord] = []
    for lineno, raw in enumerate(
        path.read_text("utf-8").splitlines(), start=1
    ):
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            # The dead-letter file itself is corrupted on this line;
            # surface as a synthetic record so the operator sees it.
            records.append(
                DeadLetterRecord(
                    error="(dead-letter file: corrupted envelope line)",
                    raw=raw,
                    line_no=lineno,
                )
            )
            continue
        if not isinstance(obj, dict):
            records.append(
                DeadLetterRecord(
                    error="(dead-letter file: envelope is not a JSON object)",
                    raw=raw,
                    line_no=lineno,
                )
            )
            continue
        records.append(
            DeadLetterRecord(
                error=str(obj.get("_error", "(unknown error)")),
                raw=str(obj.get("_raw", "")),
                line_no=lineno,
            )
        )
    return records


def write_dead_letter_file(path: Path, records: list[DeadLetterRecord]) -> None:
    """Re-write the dead-letter file from a list of records.

    Used by ``replay --apply`` and ``prune --apply`` to remove
    successfully-resolved entries.  The write is whole-file, not
    in-place mutation, so a concurrent appender from the receiver
    is safe by mtime ordering: the operator is expected to run
    replay/prune outside the receiver's tail window.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        # Truncate the file rather than delete it; the receiver will
        # re-create on next dead-letter write.
        path.write_text("", encoding="utf-8")
        return
    lines = []
    for rec in records:
        envelope = {"_error": rec.error, "_raw": rec.raw}
        lines.append(json.dumps(envelope, sort_keys=True))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Inspect (read-only).
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class InspectReport:
    """Summary of one ``inspect`` run."""

    total: int
    by_category: dict[str, int]
    by_alert_name: dict[str, int]
    earliest_fired_at_utc: str | None
    latest_fired_at_utc: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "by_category": dict(self.by_category),
            "by_alert_name": dict(self.by_alert_name),
            "earliest_fired_at_utc": self.earliest_fired_at_utc,
            "latest_fired_at_utc": self.latest_fired_at_utc,
        }


def build_inspect_report(records: list[DeadLetterRecord]) -> InspectReport:
    cat_counter: Counter[str] = Counter()
    alert_counter: Counter[str] = Counter()
    fired_at_seen: list[str] = []
    for rec in records:
        cat_counter[rec.category()] += 1
        an = rec.alert_name()
        if an is not None:
            alert_counter[an] += 1
        ts = rec.fired_at_utc()
        if ts is not None:
            fired_at_seen.append(ts)
    earliest = min(fired_at_seen) if fired_at_seen else None
    latest = max(fired_at_seen) if fired_at_seen else None
    return InspectReport(
        total=len(records),
        by_category=dict(sorted(cat_counter.items())),
        by_alert_name=dict(sorted(alert_counter.items())),
        earliest_fired_at_utc=earliest,
        latest_fired_at_utc=latest,
    )


def render_inspect_markdown(report: InspectReport) -> str:
    lines: list[str] = []
    lines.append("# Mira-Notify DLQ Inspect Report")
    lines.append("")
    lines.append(f"- total dead-lettered events: **{report.total}**")
    lines.append(
        f"- earliest fired_at_utc: `{report.earliest_fired_at_utc or '(none)'}`"
    )
    lines.append(
        f"- latest fired_at_utc:   `{report.latest_fired_at_utc or '(none)'}`"
    )
    lines.append("")
    lines.append("## By error category")
    lines.append("")
    if not report.by_category:
        lines.append("_(no entries)_")
    else:
        lines.append("| category | count |")
        lines.append("|---|---|")
        for cat, n in sorted(
            report.by_category.items(), key=lambda kv: (-kv[1], kv[0])
        ):
            lines.append(f"| `{cat}` | {n} |")
    lines.append("")
    lines.append("## By alert_name")
    lines.append("")
    if not report.by_alert_name:
        lines.append("_(no alert_name extractable)_")
    else:
        lines.append("| alert_name | count |")
        lines.append("|---|---|")
        for name, n in sorted(
            report.by_alert_name.items(), key=lambda kv: (-kv[1], kv[0])
        ):
            lines.append(f"| `{name}` | {n} |")
    lines.append("")
    lines.append("---")
    lines.append("_Generated by `mira-notify-dlq.py` (Tag-51)._")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Replay patches.
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class PatchOptions:
    """Replay-time payload patches.

    Each option is opt-in via CLI flag.  Patches are deliberately
    restricted to well-defined, low-risk repairs.  Anything more
    invasive (e.g. inventing a missing alert_name) is out of scope:
    the operator should fix the producer rather than the DLQ tool.
    """

    set_schema_version: bool = False
    fill_missing_fired_at_utc: bool = False
    normalise_severity: bool = False
    default_severity: str | None = None  # used when severity is missing


def apply_patches(
    obj: dict[str, Any], opts: PatchOptions
) -> dict[str, Any]:
    """Apply patch rules to a payload dict (returns a new dict)."""
    out = dict(obj)
    if opts.set_schema_version:
        if out.get("schema_version") != SCHEMA_VERSION:
            out["schema_version"] = SCHEMA_VERSION
    if opts.fill_missing_fired_at_utc:
        if not out.get("fired_at_utc"):
            out["fired_at_utc"] = now_utc_iso()
    if opts.normalise_severity:
        sev = out.get("severity")
        if isinstance(sev, str):
            low = sev.strip().lower()
            if low in VALID_SEVERITIES:
                out["severity"] = low
        elif opts.default_severity and opts.default_severity in VALID_SEVERITIES:
            out["severity"] = opts.default_severity
    elif opts.default_severity and not out.get("severity"):
        if opts.default_severity in VALID_SEVERITIES:
            out["severity"] = opts.default_severity
    # Always backfill labels/annotations to empty dict if missing so
    # NotifyEvent construction does not blow up on .items().
    if not isinstance(out.get("labels"), dict):
        out["labels"] = {}
    if not isinstance(out.get("annotations"), dict):
        out["annotations"] = {}
    # Backfill event_id deterministically if missing AND we now have
    # enough fields to derive it.  This mirrors emitter.make_event.
    if not out.get("event_id"):
        an = out.get("alert_name")
        ts = out.get("fired_at_utc")
        if isinstance(an, str) and an and isinstance(ts, str) and ts:
            out["event_id"] = derive_event_id(an, ts, out["labels"])
    return out


def try_construct_event(obj: dict[str, Any]) -> tuple[NotifyEvent | None, str | None]:
    """Attempt to build + validate a NotifyEvent from a patched dict."""
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
        return None, "missing event_id (post-patch)"
    errors = validate_event(event)
    if errors:
        return None, "; ".join(errors)
    return event, None


# ---------------------------------------------------------------------------
# Replay driver.
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ReplayResult:
    """Outcome of one ``replay`` invocation."""

    attempted: int
    replayed: int
    still_failed: int
    skipped_dedupe: int
    inbox_files: list[Path]
    remaining_records: list[DeadLetterRecord]
    failure_reasons: list[tuple[int, str]]  # (line_no, reason)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "replayed": self.replayed,
            "still_failed": self.still_failed,
            "skipped_dedupe": self.skipped_dedupe,
            "inbox_files": [str(p) for p in self.inbox_files],
            "remaining_count": len(self.remaining_records),
            "failure_reasons": [
                {"line_no": ln, "reason": r}
                for ln, r in self.failure_reasons
            ],
        }


def run_replay(
    records: list[DeadLetterRecord],
    inbox: Path,
    *,
    patches: PatchOptions,
    apply: bool,
) -> ReplayResult:
    """Attempt to replay each dead-letter record.

    ``apply=False`` (dry-run): no inbox files written, no dedupe set
    updated, no dead-letter file rewritten.  ``apply=True`` writes
    each successful event to the inbox, records its event_id in the
    dedupe set, and removes the record from the in-memory list so a
    follow-up ``write_dead_letter_file`` truncates resolved entries.
    """
    dedupe = load_dedupe_set(inbox) if apply else set()
    replayed = 0
    still_failed = 0
    skipped_dedupe = 0
    inbox_files: list[Path] = []
    remaining: list[DeadLetterRecord] = []
    failure_reasons: list[tuple[int, str]] = []

    for rec in records:
        obj = rec.inner_obj()
        if obj is None:
            remaining.append(rec)
            still_failed += 1
            failure_reasons.append(
                (rec.line_no, "raw payload is not a JSON object")
            )
            continue

        patched = apply_patches(obj, patches)
        event, err = try_construct_event(patched)
        if event is None:
            remaining.append(rec)
            still_failed += 1
            failure_reasons.append((rec.line_no, err or "unknown"))
            continue

        if apply:
            if event.event_id in dedupe:
                # Already materialised by a normal receiver run; drop
                # the dead-letter copy without re-writing the inbox.
                skipped_dedupe += 1
                continue
            out = write_inbox_file(inbox, event)
            inbox_files.append(out)
            append_dedupe(inbox, event.event_id)
            dedupe.add(event.event_id)
            replayed += 1
        else:
            # Dry-run: count as replayable but do not remove from
            # remaining (caller decides what to do).
            replayed += 1
            remaining.append(rec)

    return ReplayResult(
        attempted=len(records),
        replayed=replayed,
        still_failed=still_failed,
        skipped_dedupe=skipped_dedupe,
        inbox_files=inbox_files,
        remaining_records=remaining,
        failure_reasons=failure_reasons,
    )


# ---------------------------------------------------------------------------
# Prune driver.
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class PruneResult:
    """Outcome of one ``prune`` invocation."""

    inspected: int
    pruned: int
    kept: int
    remaining_records: list[DeadLetterRecord]

    def to_dict(self) -> dict[str, Any]:
        return {
            "inspected": self.inspected,
            "pruned": self.pruned,
            "kept": self.kept,
            "remaining_count": len(self.remaining_records),
        }


def run_prune(
    records: list[DeadLetterRecord],
    inbox: Path,
    *,
    patches: PatchOptions,
) -> PruneResult:
    """Drop dead-letter records whose event_id is in the dedupe set.

    Useful after a producer-side fix re-emits the corrected event;
    the dead-letter copy is now redundant.  This is purely an
    evacuation step and never materialises new inbox files.
    """
    dedupe = load_dedupe_set(inbox)
    pruned = 0
    kept = 0
    remaining: list[DeadLetterRecord] = []
    for rec in records:
        obj = rec.inner_obj()
        if obj is None:
            remaining.append(rec)
            kept += 1
            continue
        patched = apply_patches(obj, patches)
        event, _ = try_construct_event(patched)
        if event is None:
            remaining.append(rec)
            kept += 1
            continue
        if event.event_id in dedupe:
            pruned += 1
            continue
        remaining.append(rec)
        kept += 1
    return PruneResult(
        inspected=len(records),
        pruned=pruned,
        kept=kept,
        remaining_records=remaining,
    )


# ---------------------------------------------------------------------------
# CLI surface.
# ---------------------------------------------------------------------------


def _patch_opts_from_args(args: argparse.Namespace) -> PatchOptions:
    return PatchOptions(
        set_schema_version=bool(getattr(args, "set_schema_version", False)),
        fill_missing_fired_at_utc=bool(
            getattr(args, "fill_missing_fired_at_utc", False)
        ),
        normalise_severity=bool(getattr(args, "normalise_severity", False)),
        default_severity=getattr(args, "default_severity", None),
    )


def _resolve_dlq_path(inbox: Path, override: Path | None) -> Path:
    if override is not None:
        return override
    return inbox / DEAD_LETTER_FILENAME


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mira-notify-dlq",
        description=(
            "Inspect, replay, and prune the Mira-Notify dead-letter "
            "queue file written by mira-notify-receiver.py."
        ),
    )
    p.add_argument(
        "--inbox",
        type=Path,
        default=Path(receiver.DEFAULT_INBOX),
        help=(
            "Mira-Hand inbox dir whose dead-letter file is operated on "
            f"(default {receiver.DEFAULT_INBOX})."
        ),
    )
    p.add_argument(
        "--dlq-file",
        type=Path,
        default=None,
        help=(
            "Explicit dead-letter file path (default "
            f"<inbox>/{DEAD_LETTER_FILENAME})."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    insp = sub.add_parser(
        "inspect", help="Summarise the dead-letter queue."
    )
    insp.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )

    rep = sub.add_parser(
        "replay",
        help="Attempt to replay dead-lettered events into the inbox.",
    )
    rep.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Mutate the inbox + dead-letter file.  Without --apply "
            "the command is a dry-run (no writes)."
        ),
    )
    rep.add_argument(
        "--set-schema-version",
        action="store_true",
        help=f"Patch missing/old schema_version to {SCHEMA_VERSION!r}.",
    )
    rep.add_argument(
        "--fill-missing-fired-at-utc",
        action="store_true",
        help="Patch missing fired_at_utc with the current UTC time.",
    )
    rep.add_argument(
        "--normalise-severity",
        action="store_true",
        help=(
            "Lowercase + strip severity; use --default-severity for "
            "missing values."
        ),
    )
    rep.add_argument(
        "--default-severity",
        choices=list(VALID_SEVERITIES),
        default=None,
        help="Fallback severity used when severity is empty/missing.",
    )
    rep.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
        help="Report format on stdout.",
    )

    prune = sub.add_parser(
        "prune",
        help=(
            "Drop dead-letter records whose event_id is already "
            "in the inbox dedupe-set."
        ),
    )
    prune.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Mutate the dead-letter file.  Without --apply the "
            "command is a dry-run."
        ),
    )
    prune.add_argument(
        "--set-schema-version",
        action="store_true",
    )
    prune.add_argument(
        "--fill-missing-fired-at-utc",
        action="store_true",
    )
    prune.add_argument(
        "--normalise-severity",
        action="store_true",
    )
    prune.add_argument(
        "--default-severity",
        choices=list(VALID_SEVERITIES),
        default=None,
    )
    prune.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )

    return p


def render_replay_markdown(result: ReplayResult, apply: bool) -> str:
    lines: list[str] = []
    lines.append("# Mira-Notify DLQ Replay Report")
    lines.append("")
    lines.append(f"- mode: **{'apply' if apply else 'dry-run'}**")
    lines.append(f"- attempted: {result.attempted}")
    lines.append(f"- replayed: **{result.replayed}**")
    lines.append(f"- still failed: {result.still_failed}")
    lines.append(f"- skipped (already deduped): {result.skipped_dedupe}")
    lines.append(f"- new inbox files: {len(result.inbox_files)}")
    lines.append("")
    if result.inbox_files:
        lines.append("## Materialised inbox files")
        lines.append("")
        for f in result.inbox_files:
            lines.append(f"- `{f}`")
        lines.append("")
    if result.failure_reasons:
        lines.append("## Remaining failures")
        lines.append("")
        lines.append("| line_no | reason |")
        lines.append("|---|---|")
        for ln, reason in result.failure_reasons:
            lines.append(f"| {ln} | {reason} |")
        lines.append("")
    lines.append("---")
    lines.append("_Generated by `mira-notify-dlq.py` (Tag-51)._")
    return "\n".join(lines) + "\n"


def render_prune_markdown(result: PruneResult, apply: bool) -> str:
    lines: list[str] = []
    lines.append("# Mira-Notify DLQ Prune Report")
    lines.append("")
    lines.append(f"- mode: **{'apply' if apply else 'dry-run'}**")
    lines.append(f"- inspected: {result.inspected}")
    lines.append(f"- pruned: **{result.pruned}**")
    lines.append(f"- kept: {result.kept}")
    lines.append("")
    lines.append("---")
    lines.append("_Generated by `mira-notify-dlq.py` (Tag-51)._")
    return "\n".join(lines) + "\n"


def cmd_inspect(args: argparse.Namespace) -> int:
    dlq_path = _resolve_dlq_path(args.inbox, args.dlq_file)
    records = read_dead_letter_file(dlq_path)
    report = build_inspect_report(records)
    if args.format == "json":
        sys.stdout.write(json.dumps(report.to_dict(), sort_keys=True, indent=2) + "\n")
    else:
        sys.stdout.write(render_inspect_markdown(report))
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    dlq_path = _resolve_dlq_path(args.inbox, args.dlq_file)
    records = read_dead_letter_file(dlq_path)
    patches = _patch_opts_from_args(args)
    result = run_replay(
        records,
        args.inbox,
        patches=patches,
        apply=args.apply,
    )
    if args.apply:
        write_dead_letter_file(dlq_path, result.remaining_records)
    if args.format == "json":
        sys.stdout.write(
            json.dumps(result.to_dict(), sort_keys=True, indent=2) + "\n"
        )
    else:
        sys.stdout.write(render_replay_markdown(result, args.apply))
    # Exit non-zero iff any record still fails after replay.  This
    # makes the workflow visible in CI Job-Summary by red-flagging
    # an un-recoverable producer-side bug.
    return 1 if result.still_failed else 0


def cmd_prune(args: argparse.Namespace) -> int:
    dlq_path = _resolve_dlq_path(args.inbox, args.dlq_file)
    records = read_dead_letter_file(dlq_path)
    patches = _patch_opts_from_args(args)
    result = run_prune(records, args.inbox, patches=patches)
    if args.apply:
        write_dead_letter_file(dlq_path, result.remaining_records)
    if args.format == "json":
        sys.stdout.write(
            json.dumps(result.to_dict(), sort_keys=True, indent=2) + "\n"
        )
    else:
        sys.stdout.write(render_prune_markdown(result, args.apply))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "inspect":
        return cmd_inspect(args)
    if args.cmd == "replay":
        return cmd_replay(args)
    if args.cmd == "prune":
        return cmd_prune(args)
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
