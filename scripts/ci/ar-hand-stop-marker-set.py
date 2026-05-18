#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""AR-Hand-Stop-Marker Operator-CLI — Tag-47 Tomás.

Context
-------

Tag-46 PR #299 pinte den Marker-File-Schema-Vertrag und das
B2-Cascade-Coupling. Tag-47 Substanz-Counterpart liefert (a) den
Listener-Workflow (`.github/workflows/ar-hand-stop-marker-
listener.yml`), und (b) diese CLI, mit der die Operator-Hand
(Mira oder AR delegiert) den Marker einsetzt, **bevor** sie ihn
nach `wakir-runtime/main` pusht.

Die CLI ist bewusst rein-lokal: sie schreibt nur die Marker-Datei
ins lokale Repo. Push, Commit-Message, GPG-Signatur und der
Listener-Trigger sind operator-hand-Schritte; die CLI druckt
einen "next-steps"-Hinweis ans Ende der Ausgabe, der die
Push-Sequenz wiedergibt.

Pflicht-Eingaben
----------------

  * ``--welle N``           Welle-Nummer 1..7 (Cheat-Sheet §I).
  * ``--trigger TOKEN``     einer der 10 Trigger-Tokens aus
                            Cheat-Sheet §I (`Cross-Modul-Drift`,
                            `Self-Reference-Trap-Fire`, ...).
  * ``--operator NAME``     Operator-Identitaet (default ``mira``).

Optionen
--------

  * ``--repo PATH``         Repo-Root, default: cwd-search.
  * ``--state-dir PATH``    Marker-Ordner relativ zum Repo-Root,
                            default ``state/``.
  * ``--ts ISO8601``        UTC-Zeitstempel, default ``now()`` in
                            UTC.
  * ``--force``             ueberschreibt eine existierende
                            Marker-Datei (default: refuse).
  * ``--dry-run``           gibt nur den geplanten Filename +
                            Payload aus, schreibt nichts.

Exit-Codes
----------

  *  0 — Marker geschrieben (oder dry-run-OK).
  *  2 — Validation-Fehler (welle oob, trigger unbekannt,
         schon vorhanden).
  *  3 — IO-Fehler (state-dir nicht beschreibbar).

Audit-Trail
-----------

Die CLI gibt zusaetzlich eine vorbereitete
``activity-log.md``-Append-Zeile aus, die der Operator
unveraendert in die `activity-log.md` der `AI-Corp`-Sandbox
appendieren soll (audit-trail-completeness, B1-Coverage-Test
§5 ``TestMarkerPersistenceAndAuditTrail``).

Sandbox-Boundary
----------------

Stdlib-only. Kein Netzwerk, kein gh CLI, kein git invoke. Die
CLI komponiert ausschliesslich lokale Datei-State; alles
darueber hinaus ist Operator-Hand.

Anchors
-------

  * Cheat-Sheet §I (Trigger 1..10, Marker-Pattern, Sign-Off-
    Pattern, `docs/phase-3c/cutover-operator-cheat-sheet.md`).
  * Tag-46 B1 Coverage-Test (PR #299,
    `tests/ci/test_ar_hand_stop_marker_trigger_b1.py`).
  * Listener-Workflow (`.github/workflows/ar-hand-stop-marker-
    listener.yml`).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Source-of-truth constants (anchored to Cheat-Sheet §I).
# ---------------------------------------------------------------------------


# Cheat-Sheet §I §"Marker-Setzen": filename pattern
#   `state/ar-hand-stop-welle-N-YYYYMMDD.json`
MARKER_FILENAME_PATTERN = "ar-hand-stop-welle-{welle}-{yyyymmdd}.json"
MARKER_FILENAME_RE = re.compile(
    r"^ar-hand-stop-welle-([1-7])-(\d{8})\.json$"
)

# Cheat-Sheet §I sign-off pattern (referenced for diagnostics, not
# written by this CLI).
SIGN_OFF_FILENAME_PATTERN = "ar-hand-stop-sign-off-welle-{welle}.json"

# Cheat-Sheet §I 10 operator-trigger bedingungen. The vocabulary is
# pinned as substring-tokens so minor copyedits to the cheat-sheet
# do not break the CLI; the operator MUST supply one of these
# tokens verbatim.
TRIGGER_TOKENS: tuple[str, ...] = (
    "Cross-Modul-Drift",
    "Self-Reference-Trap-Fire",
    "OTS-Anchor-Emission-Stop",
    "POST_HASH != PRE_HASH",
    "FSM-Phantom-Transition",
    "NATS-Consumer-Lag",
    "Recovery-Drill",
    "Henrik-Audit-Trail-Luecke",
    "Quadlet-Restart-Failure",
    "Mira-SSH-Authority-Loss",
)

# Welle range (Phase-3c cutover has 7 Wellen, ADR-0066).
WELLE_MIN = 1
WELLE_MAX = 7


# ---------------------------------------------------------------------------
# Public helpers (also used by the test-suite).
# ---------------------------------------------------------------------------


def build_marker_filename(welle: int, when: datetime) -> str:
    """Compose the marker filename per Cheat-Sheet §I.

    >>> build_marker_filename(3, datetime(2026, 5, 19, tzinfo=timezone.utc))
    'ar-hand-stop-welle-3-20260519.json'
    """

    if not (WELLE_MIN <= welle <= WELLE_MAX):
        raise ValueError(
            f"welle out of range: {welle} (expected {WELLE_MIN}..{WELLE_MAX})"
        )
    if when.tzinfo is None:
        raise ValueError("'when' must be timezone-aware (UTC)")
    yyyymmdd = when.astimezone(timezone.utc).strftime("%Y%m%d")
    return MARKER_FILENAME_PATTERN.format(welle=welle, yyyymmdd=yyyymmdd)


def build_marker_payload(
    *,
    welle: int,
    trigger: str,
    operator: str,
    when: datetime,
) -> dict[str, object]:
    """Compose the marker JSON-payload per Cheat-Sheet §I."""

    if not (WELLE_MIN <= welle <= WELLE_MAX):
        raise ValueError(
            f"welle out of range: {welle} (expected {WELLE_MIN}..{WELLE_MAX})"
        )
    if not _trigger_is_recognised(trigger):
        raise ValueError(
            "trigger token not recognised; expected one of: "
            + ", ".join(TRIGGER_TOKENS)
        )
    if not operator:
        raise ValueError("operator must be a non-empty string")
    if when.tzinfo is None:
        raise ValueError("'when' must be timezone-aware (UTC)")
    ts = when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "welle": welle,
        "trigger": trigger,
        "ts": ts,
        "operator": operator,
    }


def build_activity_log_line(
    *,
    welle: int,
    trigger: str,
    operator: str,
    marker_filename: str,
    when: datetime,
) -> str:
    """Compose the activity-log.md append-line.

    The line is single-line, RFC3339-ts-prefixed, and includes
    the marker filename verbatim + the trigger-bedingung verbatim
    (B1-Coverage-Test §5 audit-trail completeness invariant).
    """

    ts = when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        f"- {ts} — AR-Hand-Stop-Marker gesetzt: "
        f"welle={welle}, trigger={trigger!r}, operator={operator}, "
        f"marker={marker_filename}. "
        f"Cutover-Sequenz haltet bis "
        f"{SIGN_OFF_FILENAME_PATTERN.format(welle=welle)} Sign-Off."
    )


def write_marker(
    *,
    state_dir: pathlib.Path,
    filename: str,
    payload: dict[str, object],
    force: bool,
) -> pathlib.Path:
    """Write the marker JSON to ``state_dir/filename``.

    Raises:
      FileExistsError: when the marker exists and ``force`` is False.
      OSError: when the state-dir cannot be created or written.
    """

    state_dir.mkdir(parents=True, exist_ok=True)
    target = state_dir / filename
    if target.exists() and not force:
        raise FileExistsError(
            f"marker already exists at {target}; pass --force to overwrite"
        )
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    target.write_text(body, encoding="utf-8")
    return target


def parse_marker_filename(filename: str) -> tuple[int, str]:
    """Return ``(welle, yyyymmdd)`` parsed from a marker filename.

    Raises ValueError on a malformed filename.
    """

    match = MARKER_FILENAME_RE.match(pathlib.Path(filename).name)
    if not match:
        raise ValueError(
            f"filename does not match marker pattern: {filename!r}"
        )
    welle = int(match.group(1))
    yyyymmdd = match.group(2)
    return welle, yyyymmdd


# ---------------------------------------------------------------------------
# CLI plumbing.
# ---------------------------------------------------------------------------


def _trigger_is_recognised(trigger: str) -> bool:
    """Returns True iff ``trigger`` contains one of the §I tokens.

    Substring-containment is intentional: the cheat-sheet wording is
    the source of truth, so a slightly expanded line like
    ``"NATS-Consumer-Lag P95 > 500ms"`` is accepted as long as one
    token appears verbatim.
    """

    return any(token in trigger for token in TRIGGER_TOKENS)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="ar-hand-stop-marker-set",
        description="Compose and write an AR-Hand-Stop-Marker file "
        "for the Phase-3c cutover sequence "
        "(Cheat-Sheet §I).",
    )
    p.add_argument(
        "--welle",
        type=int,
        required=True,
        help="Welle number (1..7) per ADR-0066 §Welle-Sequenz.",
    )
    p.add_argument(
        "--trigger",
        type=str,
        required=True,
        help=(
            "Operator-trigger string; MUST contain one of the 10 "
            "Cheat-Sheet §I tokens verbatim. Run with --list-triggers "
            "to print the recognised tokens."
        ),
    )
    p.add_argument(
        "--operator",
        type=str,
        default="mira",
        help="Operator identity, default 'mira'.",
    )
    p.add_argument(
        "--repo",
        type=pathlib.Path,
        default=pathlib.Path.cwd(),
        help="Repo root, default cwd. The marker lands at "
        "<repo>/<state-dir>/<marker-filename>.",
    )
    p.add_argument(
        "--state-dir",
        type=str,
        default="state",
        help="State directory relative to repo root, default 'state'.",
    )
    p.add_argument(
        "--ts",
        type=str,
        default="",
        help=(
            "UTC timestamp in ISO-8601 format (e.g. "
            "2026-05-19T12:34:56Z); default now()."
        ),
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing marker (refused by default).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Compose the filename and payload but do not write "
            "anything. Prints the JSON-payload to stdout."
        ),
    )
    p.add_argument(
        "--list-triggers",
        action="store_true",
        help="Print recognised Cheat-Sheet §I trigger tokens and exit.",
    )
    return p.parse_args(argv)


def _parse_ts(raw: str) -> datetime:
    if not raw:
        return datetime.now(tz=timezone.utc)
    # Accept "...Z" (Python <3.11 does not parse the trailing Z).
    normalised = raw.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalised)
    if parsed.tzinfo is None:
        raise ValueError(
            f"timestamp must include a timezone offset: {raw!r}"
        )
    return parsed.astimezone(timezone.utc)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.list_triggers:
        for token in TRIGGER_TOKENS:
            print(token)
        return 0

    try:
        when = _parse_ts(args.ts)
    except ValueError as exc:
        print(f"ERROR: --ts: {exc}", file=sys.stderr)
        return 2

    try:
        filename = build_marker_filename(args.welle, when)
        payload = build_marker_payload(
            welle=args.welle,
            trigger=args.trigger,
            operator=args.operator,
            when=when,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    state_dir: pathlib.Path = args.repo / args.state_dir

    if args.dry_run:
        print("DRY-RUN — no files written")
        print(f"marker-file: {state_dir / filename}")
        print("payload:")
        print(json.dumps(payload, indent=2, sort_keys=True))
        print()
        print(
            "activity-log append-line "
            "(operator-hand appends to AI-Corp/activity-log.md):"
        )
        print(
            build_activity_log_line(
                welle=args.welle,
                trigger=args.trigger,
                operator=args.operator,
                marker_filename=filename,
                when=when,
            )
        )
        return 0

    try:
        target = write_marker(
            state_dir=state_dir,
            filename=filename,
            payload=payload,
            force=args.force,
        )
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ERROR: state-dir IO failed: {exc}", file=sys.stderr)
        return 3

    print(f"marker written: {target}")
    print(
        "next-steps (operator-hand):\n"
        f"  1. cd {args.repo}\n"
        f"  2. git add {state_dir / filename}\n"
        f'  3. git commit -m "ops(ar-hand-stop): set welle-{args.welle} '
        f'marker for {args.trigger!r}"\n'
        "  4. git push origin main  "
        "# triggers ar-hand-stop-marker-listener.yml\n"
        "  5. append activity-log.md (line below)\n"
    )
    print(
        build_activity_log_line(
            welle=args.welle,
            trigger=args.trigger,
            operator=args.operator,
            marker_filename=filename,
            when=when,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
