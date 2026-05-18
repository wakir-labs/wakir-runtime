#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""marathon-aggregat-tracker - Tag-40 Phase-3 marathon aggregate tracker.

Background
----------

The Phase-3c cutover sequence (ADR-0065 + ADR-0066) flips the
persona-engine default backend from Python to Rust across seven
production-default switches ("Wellen") in KW 24..27:

    Welle 1  v907_verify              KW 24  doppel with Welle-2
    Welle 2  svid_workload_identity   KW 24  doppel with Welle-1
    Welle 3  bridge_audit_writer      KW 25  solo
    Welle 4  state_backing            KW 26  doppel with Welle-5
    Welle 5  lifecycle_state_machine  KW 26  doppel with Welle-4
    Welle 6  subscribe_loop           KW 27  doppel with Welle-7
    Welle 7  recovery_workflow        KW 27  doppel with Welle-6 (Phase-3 final)

Each Welle traverses a discrete lifecycle from pre-flight checks
through cutover-execution to post-cutover soak and operator sign-off
(or rollback). The other Phase-3c substrates only model a 5-state
coarse view (`pre_cutover`, `in_cutover`, `post_cutover`,
`rollback_active`, `welle_complete` - see
``scripts/phase-3c-welle-status-emitter.py``). That coarse view is
enough for the Grafana panel but it does NOT distinguish between

  * "pre-flight RUNNING" vs "pre-flight GREEN" (the difference between
    "we are validating" and "we may proceed to cutover");
  * "cutover RUNNING" vs "cutover GREEN" (the difference between
    "we are in the irreversible window" and "the switch has flipped");
  * "soak RUNNING" vs "soak GREEN" (the difference between "we are
    watching for regressions" and "soak window completed clean");
  * "sign-off PENDING" vs "signed-off" (the difference between
    "engineering says green, awaiting operator-hand approval" and
    "operator-hand approval recorded").

The Tag-40 marathon-aggregat-tracker implements that finer 9-state
welle-lifecycle and persists it across operator-hand sessions so the
KW 24..27 cutover-marathon has a single source of truth for "where is
each Welle right now?" plus a cross-Welle aggregate-view ("how far
through the marathon are we?").

State-Machine per Welle (ADR-0066 Cutover-Lifecycle)
----------------------------------------------------

Forward path::

    pending
        |
        v
    pre-flight-running
        |
        v
    pre-flight-green
        |
        v
    cutover-running    -------+
        |                     |
        v                     |
    cutover-green             |
        |                     |
        v                     |
    soak-running              |
        |                     |
        v                     |
    soak-green                |
        |                     |
        v                     |
    sign-off-pending          |
        |                     |
        v                     |
    signed-off                |
                              |
    Rollback path (from any   |
    forward state past        |
    pre-flight-green):        |
                              |
    rollback-running  <-------+
        |
        v
    rolled-back

Invariants
~~~~~~~~~~

  I1.  Every Welle starts in ``pending``.
  I2.  Forward transitions follow the exact sequence above. Skipping a
       state is rejected with a ``StateTransitionError``.
  I3.  Rollback is only legal from ``cutover-running`` onwards (you
       cannot roll back something you have not started cutting over).
       Rollback from ``pre-flight-running`` or ``pre-flight-green``
       must use the ``pending`` reset path instead (operator-hand:
       set state back to ``pending`` explicitly).
  I4.  Terminal states are ``signed-off`` and ``rolled-back``.
       No outbound transitions are accepted from terminal states; an
       operator-hand reset to ``pending`` is the only escape and is
       refused unless ``--force`` is supplied (CLI flag).
  I5.  Every state change records a UTC timestamp. The full history
       is preserved (append-only), the latest state is also exposed
       at the top level for cheap reads.
  I6.  When all seven Welles reach ``signed-off``, the tracker emits
       a single ``phase_3_complete`` event (idempotent: re-running
       the trigger after emission is a no-op, the event-file stays
       at the original timestamp).

Persistent state
----------------

The state file lives by default at::

    state/phase-3-marathon-state.json

(``state/`` is created on first write.) The file is canonical JSON,
sorted keys, 2-space indent, trailing newline - deterministic so
``git diff`` is meaningful. Schema::

    {
      "schema_version": 1,
      "created_utc": "2026-05-18T12:34:56Z",
      "updated_utc": "2026-05-18T12:34:56Z",
      "phase_3_complete": false,
      "phase_3_complete_utc": null,
      "welles": {
        "1": {
          "welle": 1,
          "domain": "v907_verify",
          "kw": "KW 24",
          "pair": "welle-2",
          "state": "pending",
          "first_seen_utc": "...",
          "last_updated_utc": "...",
          "history": [
            {"state": "pending", "utc": "...", "note": null}
          ]
        },
        ...
      }
    }

CLI
---

::

    # Show the cross-Welle marathon-aggregate (ASCII table).
    python scripts/phase-3c/marathon-aggregat-tracker.py --show-marathon

    # Show a single Welle's detailed lifecycle history.
    python scripts/phase-3c/marathon-aggregat-tracker.py --show-welle 3

    # Show only the aggregate counters (JSON), no per-Welle rows.
    python scripts/phase-3c/marathon-aggregat-tracker.py --show-aggregat

    # Update a Welle's state (operator-hand transition).
    python scripts/phase-3c/marathon-aggregat-tracker.py \\
        --update-welle 1 --state pre-flight-running

    # Same with an audit-note (recorded into history[].note).
    python scripts/phase-3c/marathon-aggregat-tracker.py \\
        --update-welle 1 --state pre-flight-green --note "PR #190 merged"

Exit codes
----------

  * 0  - command succeeded (show / update / aggregate).
  * 1  - illegal state transition or invalid state name.
  * 2  - state-file schema mismatch or unparseable.
  * 3  - unknown welle number (must be 1..7) or invalid CLI usage.

Posture
-------

This tracker is **operator-hand-driven**: it never reaches out to CI,
to GitHub, to podman, or to a live VM. It is the discipline-substrate
the Mira-Hand uses to record "where in the marathon are we" - the
actual evidence for each transition (pre-flight smoke green, cutover
PR merged, soak window observed) is gathered by sibling substrates
(``scripts/phase-3c/welle-{N}-cutover-smoke.{py,sh}``,
``.github/workflows/phase-3c-welle-{N}-validation.yml``, the Tag-30
``phase-3c-welle-status-emitter``, and the Henrik audit-trail).

Stdlib only. No third-party dependencies. Python 3.13+.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import enum
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants - Welle definitions (must stay in sync with
# scripts/phase-3c-welle-status-emitter.py WELLE_DOMAIN_MAP).
# ---------------------------------------------------------------------------


#: The fixed Welle 1..7 metadata. Source-of-truth: ADR-0065 + ADR-0066.
WELLE_DEFINITIONS: Dict[int, Dict[str, str]] = {
    1: {"domain": "v907_verify", "kw": "KW 24", "pair": "welle-2"},
    2: {"domain": "svid_workload_identity", "kw": "KW 24", "pair": "welle-1"},
    3: {"domain": "bridge_audit_writer", "kw": "KW 25", "pair": "solo"},
    4: {"domain": "state_backing", "kw": "KW 26", "pair": "welle-5"},
    5: {"domain": "lifecycle_state_machine", "kw": "KW 26", "pair": "welle-4"},
    6: {"domain": "subscribe_loop", "kw": "KW 27", "pair": "welle-7"},
    7: {"domain": "recovery_workflow", "kw": "KW 27", "pair": "welle-6"},
}


SCHEMA_VERSION = 1
DEFAULT_STATE_PATH = "state/phase-3-marathon-state.json"
EVENT_PHASE_3_COMPLETE = "phase_3_complete"
DEFAULT_EVENT_DIR = "state/events"


# ---------------------------------------------------------------------------
# Lifecycle state enum + transition graph
# ---------------------------------------------------------------------------


class WelleLifecycleState(str, enum.Enum):
    """Per-Welle fine-grained lifecycle state. String-enum for JSON."""

    PENDING = "pending"
    PRE_FLIGHT_RUNNING = "pre-flight-running"
    PRE_FLIGHT_GREEN = "pre-flight-green"
    CUTOVER_RUNNING = "cutover-running"
    CUTOVER_GREEN = "cutover-green"
    SOAK_RUNNING = "soak-running"
    SOAK_GREEN = "soak-green"
    SIGN_OFF_PENDING = "sign-off-pending"
    SIGNED_OFF = "signed-off"
    ROLLBACK_RUNNING = "rollback-running"
    ROLLED_BACK = "rolled-back"


ALL_STATES: Tuple[WelleLifecycleState, ...] = tuple(WelleLifecycleState)

#: Forward-path linear sequence (Invariant I2).
FORWARD_SEQUENCE: Tuple[WelleLifecycleState, ...] = (
    WelleLifecycleState.PENDING,
    WelleLifecycleState.PRE_FLIGHT_RUNNING,
    WelleLifecycleState.PRE_FLIGHT_GREEN,
    WelleLifecycleState.CUTOVER_RUNNING,
    WelleLifecycleState.CUTOVER_GREEN,
    WelleLifecycleState.SOAK_RUNNING,
    WelleLifecycleState.SOAK_GREEN,
    WelleLifecycleState.SIGN_OFF_PENDING,
    WelleLifecycleState.SIGNED_OFF,
)

#: Rollback is only legal once cutover has started (Invariant I3).
ROLLBACK_ENTRY_STATES = frozenset(
    {
        WelleLifecycleState.CUTOVER_RUNNING,
        WelleLifecycleState.CUTOVER_GREEN,
        WelleLifecycleState.SOAK_RUNNING,
        WelleLifecycleState.SOAK_GREEN,
        WelleLifecycleState.SIGN_OFF_PENDING,
    }
)

#: Terminal states (Invariant I4).
TERMINAL_STATES = frozenset(
    {WelleLifecycleState.SIGNED_OFF, WelleLifecycleState.ROLLED_BACK}
)


def _build_legal_transitions() -> Dict[
    WelleLifecycleState, frozenset
]:
    """Compute the legal-transition map from the forward sequence + rollback rules."""

    legal: Dict[WelleLifecycleState, set] = {s: set() for s in ALL_STATES}
    # Forward path.
    for i in range(len(FORWARD_SEQUENCE) - 1):
        legal[FORWARD_SEQUENCE[i]].add(FORWARD_SEQUENCE[i + 1])
    # Rollback entry (I3).
    for s in ROLLBACK_ENTRY_STATES:
        legal[s].add(WelleLifecycleState.ROLLBACK_RUNNING)
    # Rollback completion.
    legal[WelleLifecycleState.ROLLBACK_RUNNING].add(
        WelleLifecycleState.ROLLED_BACK
    )
    # Terminal states have no outbound transitions (I4).
    return {k: frozenset(v) for k, v in legal.items()}


LEGAL_TRANSITIONS: Dict[WelleLifecycleState, frozenset] = (
    _build_legal_transitions()
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class StateTransitionError(Exception):
    """Raised when an illegal lifecycle transition is requested."""


class StateFileError(Exception):
    """Raised when the persisted state file is unparseable or schema-bad."""


class UnknownWelleError(Exception):
    """Raised for welle numbers outside 1..7."""


# ---------------------------------------------------------------------------
# Time helpers (UTC, ISO-8601 with Z suffix, second-precision)
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    """Return current UTC time as ``YYYY-MM-DDTHH:MM:SSZ`` (no microseconds)."""

    return _dt.datetime.now(tz=_dt.timezone.utc).replace(
        microsecond=0
    ).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class WelleEntry:
    """Per-Welle state + history."""

    welle: int
    domain: str
    kw: str
    pair: str
    state: WelleLifecycleState
    first_seen_utc: str
    last_updated_utc: str
    history: List[Dict[str, Optional[str]]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "welle": self.welle,
            "domain": self.domain,
            "kw": self.kw,
            "pair": self.pair,
            "state": self.state.value,
            "first_seen_utc": self.first_seen_utc,
            "last_updated_utc": self.last_updated_utc,
            "history": list(self.history),
        }


@dataclass
class MarathonState:
    """Top-level persisted document."""

    schema_version: int
    created_utc: str
    updated_utc: str
    phase_3_complete: bool
    phase_3_complete_utc: Optional[str]
    welles: Dict[int, WelleEntry]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "created_utc": self.created_utc,
            "updated_utc": self.updated_utc,
            "phase_3_complete": self.phase_3_complete,
            "phase_3_complete_utc": self.phase_3_complete_utc,
            "welles": {
                str(k): self.welles[k].to_dict()
                for k in sorted(self.welles.keys())
            },
        }


# ---------------------------------------------------------------------------
# State construction + persistence
# ---------------------------------------------------------------------------


def build_initial_state(now: Optional[str] = None) -> MarathonState:
    """Build a fresh ``MarathonState`` with all seven Welles in ``pending``."""

    ts = now or _utcnow_iso()
    welles: Dict[int, WelleEntry] = {}
    for num, meta in WELLE_DEFINITIONS.items():
        welles[num] = WelleEntry(
            welle=num,
            domain=meta["domain"],
            kw=meta["kw"],
            pair=meta["pair"],
            state=WelleLifecycleState.PENDING,
            first_seen_utc=ts,
            last_updated_utc=ts,
            history=[
                {
                    "state": WelleLifecycleState.PENDING.value,
                    "utc": ts,
                    "note": None,
                }
            ],
        )
    return MarathonState(
        schema_version=SCHEMA_VERSION,
        created_utc=ts,
        updated_utc=ts,
        phase_3_complete=False,
        phase_3_complete_utc=None,
        welles=welles,
    )


def _parse_state_value(value: Any, welle_num: int) -> WelleLifecycleState:
    if not isinstance(value, str):
        raise StateFileError(
            f"welle={welle_num}: state must be a string, got {type(value).__name__}"
        )
    try:
        return WelleLifecycleState(value)
    except ValueError:
        raise StateFileError(
            f"welle={welle_num}: unknown lifecycle state {value!r}"
        )


def load_state(path: Path) -> MarathonState:
    """Load persisted state from disk. Raises ``StateFileError`` on schema-bad input."""

    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StateFileError(f"state file {path} is not valid JSON: {exc}")
    if not isinstance(doc, dict):
        raise StateFileError(
            f"state file {path}: top-level must be an object"
        )
    sv = doc.get("schema_version")
    if sv != SCHEMA_VERSION:
        raise StateFileError(
            f"state file {path}: schema_version={sv!r} unsupported "
            f"(expected {SCHEMA_VERSION})"
        )
    welles_raw = doc.get("welles")
    if not isinstance(welles_raw, dict):
        raise StateFileError(
            f"state file {path}: 'welles' must be an object"
        )
    welles: Dict[int, WelleEntry] = {}
    for key, w in welles_raw.items():
        try:
            num = int(key)
        except (TypeError, ValueError):
            raise StateFileError(
                f"state file {path}: welle key {key!r} is not an int"
            )
        if num not in WELLE_DEFINITIONS:
            raise StateFileError(
                f"state file {path}: welle={num} not in 1..7"
            )
        if not isinstance(w, dict):
            raise StateFileError(
                f"state file {path}: welle={num} entry must be an object"
            )
        state = _parse_state_value(w.get("state"), num)
        history = w.get("history", [])
        if not isinstance(history, list):
            raise StateFileError(
                f"state file {path}: welle={num} history must be a list"
            )
        welles[num] = WelleEntry(
            welle=num,
            domain=str(w.get("domain", WELLE_DEFINITIONS[num]["domain"])),
            kw=str(w.get("kw", WELLE_DEFINITIONS[num]["kw"])),
            pair=str(w.get("pair", WELLE_DEFINITIONS[num]["pair"])),
            state=state,
            first_seen_utc=str(w.get("first_seen_utc", "")),
            last_updated_utc=str(w.get("last_updated_utc", "")),
            history=list(history),
        )
    # Ensure all seven Welles are present.
    for num in WELLE_DEFINITIONS:
        if num not in welles:
            raise StateFileError(
                f"state file {path}: welle={num} missing"
            )
    return MarathonState(
        schema_version=sv,
        created_utc=str(doc.get("created_utc", "")),
        updated_utc=str(doc.get("updated_utc", "")),
        phase_3_complete=bool(doc.get("phase_3_complete", False)),
        phase_3_complete_utc=doc.get("phase_3_complete_utc"),
        welles=welles,
    )


def save_state(state: MarathonState, path: Path) -> None:
    """Persist ``state`` to ``path`` deterministically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(state.to_dict(), indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")


def load_or_init(path: Path, now: Optional[str] = None) -> MarathonState:
    """Load state from ``path``; if missing, build a fresh initial state."""

    try:
        return load_state(path)
    except FileNotFoundError:
        return build_initial_state(now=now)


# ---------------------------------------------------------------------------
# Transition logic
# ---------------------------------------------------------------------------


def validate_transition(
    src: WelleLifecycleState, dst: WelleLifecycleState
) -> None:
    """Raise ``StateTransitionError`` if the transition is illegal."""

    if src == dst:
        raise StateTransitionError(
            f"transition rejected: src == dst ({src.value!r})"
        )
    if src in TERMINAL_STATES:
        raise StateTransitionError(
            f"transition rejected: {src.value!r} is terminal"
        )
    if dst not in LEGAL_TRANSITIONS.get(src, frozenset()):
        raise StateTransitionError(
            f"transition rejected: {src.value!r} -> {dst.value!r} is not legal"
        )


def update_welle(
    state: MarathonState,
    welle_num: int,
    new_state: WelleLifecycleState,
    note: Optional[str] = None,
    now: Optional[str] = None,
) -> MarathonState:
    """Apply a state transition. Mutates ``state`` in place and returns it."""

    if welle_num not in WELLE_DEFINITIONS:
        raise UnknownWelleError(
            f"welle={welle_num} unknown (must be 1..7)"
        )
    entry = state.welles[welle_num]
    validate_transition(entry.state, new_state)
    ts = now or _utcnow_iso()
    entry.state = new_state
    entry.last_updated_utc = ts
    entry.history.append(
        {"state": new_state.value, "utc": ts, "note": note}
    )
    state.updated_utc = ts
    # Phase-3-COMPLETE-Trigger-Logic (Invariant I6).
    if not state.phase_3_complete and all(
        state.welles[n].state == WelleLifecycleState.SIGNED_OFF
        for n in WELLE_DEFINITIONS
    ):
        state.phase_3_complete = True
        state.phase_3_complete_utc = ts
    return state


def emit_phase_3_complete_event(
    state: MarathonState,
    event_dir: Path,
    now: Optional[str] = None,
) -> Optional[Path]:
    """If ``state.phase_3_complete`` and the event-file is not yet present,
    create the event-file. Idempotent: returns the existing path if the
    event was already emitted, ``None`` if the marathon is not yet complete.
    """

    if not state.phase_3_complete:
        return None
    event_dir.mkdir(parents=True, exist_ok=True)
    path = event_dir / f"{EVENT_PHASE_3_COMPLETE}.json"
    if path.exists():
        return path
    ts = state.phase_3_complete_utc or now or _utcnow_iso()
    payload = {
        "event": EVENT_PHASE_3_COMPLETE,
        "utc": ts,
        "schema_version": SCHEMA_VERSION,
        "welles": {
            str(n): state.welles[n].state.value
            for n in sorted(WELLE_DEFINITIONS)
        },
    }
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Aggregate computations
# ---------------------------------------------------------------------------


@dataclass
class AggregateView:
    """Cross-Welle marathon-aggregate summary."""

    total_welles: int
    pending_count: int
    in_flight_count: int
    signed_off_count: int
    rolled_back_count: int
    progress_pct: float
    phase_3_complete: bool
    phase_3_complete_utc: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_welles": self.total_welles,
            "pending_count": self.pending_count,
            "in_flight_count": self.in_flight_count,
            "signed_off_count": self.signed_off_count,
            "rolled_back_count": self.rolled_back_count,
            "progress_pct": self.progress_pct,
            "phase_3_complete": self.phase_3_complete,
            "phase_3_complete_utc": self.phase_3_complete_utc,
        }


def compute_aggregate(state: MarathonState) -> AggregateView:
    """Compute the cross-Welle aggregate counters from ``state``."""

    total = len(WELLE_DEFINITIONS)
    pending = 0
    in_flight = 0
    signed_off = 0
    rolled_back = 0
    for n in WELLE_DEFINITIONS:
        s = state.welles[n].state
        if s == WelleLifecycleState.PENDING:
            pending += 1
        elif s == WelleLifecycleState.SIGNED_OFF:
            signed_off += 1
        elif s == WelleLifecycleState.ROLLED_BACK:
            rolled_back += 1
        else:
            in_flight += 1
    progress = 100.0 * signed_off / total if total else 0.0
    return AggregateView(
        total_welles=total,
        pending_count=pending,
        in_flight_count=in_flight,
        signed_off_count=signed_off,
        rolled_back_count=rolled_back,
        progress_pct=round(progress, 2),
        phase_3_complete=state.phase_3_complete,
        phase_3_complete_utc=state.phase_3_complete_utc,
    )


# ---------------------------------------------------------------------------
# Pre/Cutover/Post phase mapping (for the marathon ASCII view)
# ---------------------------------------------------------------------------


#: Maps a fine-grained lifecycle state to the (pre, cutover, post)
#: tri-column phase status for the marathon-aggregate table.
#: Values are "-" (not started), "RUN" (running), "OK" (green / done),
#: "ROLL" (rolled-back affects this column), or "PEND" (sign-off pending,
#: post-column only).
PHASE_COLUMNS: Dict[
    WelleLifecycleState, Tuple[str, str, str]
] = {
    WelleLifecycleState.PENDING: ("-", "-", "-"),
    WelleLifecycleState.PRE_FLIGHT_RUNNING: ("RUN", "-", "-"),
    WelleLifecycleState.PRE_FLIGHT_GREEN: ("OK", "-", "-"),
    WelleLifecycleState.CUTOVER_RUNNING: ("OK", "RUN", "-"),
    WelleLifecycleState.CUTOVER_GREEN: ("OK", "OK", "-"),
    WelleLifecycleState.SOAK_RUNNING: ("OK", "OK", "RUN"),
    WelleLifecycleState.SOAK_GREEN: ("OK", "OK", "OK"),
    WelleLifecycleState.SIGN_OFF_PENDING: ("OK", "OK", "PEND"),
    WelleLifecycleState.SIGNED_OFF: ("OK", "OK", "OK"),
    WelleLifecycleState.ROLLBACK_RUNNING: ("OK", "ROLL", "-"),
    WelleLifecycleState.ROLLED_BACK: ("OK", "ROLL", "-"),
}


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------


def _coupling_indicator(state: MarathonState, num: int) -> str:
    """Return a cross-Welle coupling indicator for Welle ``num``.

    Doppel-Wellen share a KW window; if one partner has progressed past
    ``pre-flight-green`` but the other is still ``pending``, that is a
    drift signal worth surfacing in the table.
    """

    meta = WELLE_DEFINITIONS[num]
    pair = meta["pair"]
    if pair == "solo":
        return "solo"
    try:
        partner = int(pair.split("-", 1)[1])
    except (ValueError, IndexError):
        return "?"
    me_idx = FORWARD_SEQUENCE.index(state.welles[num].state) if (
        state.welles[num].state in FORWARD_SEQUENCE
    ) else -1
    partner_state = state.welles[partner].state
    partner_idx = (
        FORWARD_SEQUENCE.index(partner_state)
        if partner_state in FORWARD_SEQUENCE
        else -1
    )
    if state.welles[num].state in (
        WelleLifecycleState.ROLLBACK_RUNNING,
        WelleLifecycleState.ROLLED_BACK,
    ) or partner_state in (
        WelleLifecycleState.ROLLBACK_RUNNING,
        WelleLifecycleState.ROLLED_BACK,
    ):
        return f"<-w{partner}:ROLL"
    drift = abs(me_idx - partner_idx)
    if drift == 0:
        return f"<-w{partner}:sync"
    if drift <= 2:
        return f"<-w{partner}:near"
    return f"<-w{partner}:DRIFT"


def render_marathon_table(state: MarathonState) -> str:
    """Render the ASCII marathon table (Welle 1..7 with Pre/Cutover/Post)."""

    header = (
        "Welle | Domain                  | KW    | Pre | Cut  | Post | "
        "State              | Coupling      | Last-Update"
    )
    sep = "-" * len(header)
    lines: List[str] = [header, sep]
    for num in sorted(WELLE_DEFINITIONS):
        entry = state.welles[num]
        pre, cut, post = PHASE_COLUMNS[entry.state]
        lines.append(
            "{w:>5} | {dom:<23} | {kw:<5} | {pre:<3} | {cut:<4} | "
            "{post:<4} | {st:<18} | {cp:<13} | {ts}".format(
                w=num,
                dom=entry.domain[:23],
                kw=entry.kw,
                pre=pre,
                cut=cut,
                post=post,
                st=entry.state.value,
                cp=_coupling_indicator(state, num),
                ts=entry.last_updated_utc or "-",
            )
        )
    agg = compute_aggregate(state)
    lines.append(sep)
    lines.append(
        "Marathon: signed-off={so}/{tot} ({pct}%), in-flight={inf}, "
        "rolled-back={rb}, pending={pen}".format(
            so=agg.signed_off_count,
            tot=agg.total_welles,
            pct=agg.progress_pct,
            inf=agg.in_flight_count,
            rb=agg.rolled_back_count,
            pen=agg.pending_count,
        )
    )
    if state.phase_3_complete:
        lines.append(
            f"PHASE_3_COMPLETE emitted at {state.phase_3_complete_utc}"
        )
    return "\n".join(lines)


def render_welle_detail(state: MarathonState, num: int) -> str:
    """Render a single-Welle detail dump (state + full history)."""

    if num not in WELLE_DEFINITIONS:
        raise UnknownWelleError(f"welle={num} unknown (must be 1..7)")
    entry = state.welles[num]
    lines: List[str] = [
        f"Welle {num} - {entry.domain} ({entry.kw}, pair={entry.pair})",
        f"  state           : {entry.state.value}",
        f"  first-seen-utc  : {entry.first_seen_utc}",
        f"  last-updated-utc: {entry.last_updated_utc}",
        f"  history ({len(entry.history)} entries):",
    ]
    for h in entry.history:
        note = h.get("note")
        note_str = f" ({note})" if note else ""
        lines.append(f"    - {h.get('utc')}: {h.get('state')}{note_str}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="marathon-aggregat-tracker",
        description=(
            "Phase-3 marathon-aggregat-tracker: persists per-Welle "
            "lifecycle state across operator-hand sessions and renders "
            "the cross-Welle aggregate-view."
        ),
    )
    p.add_argument(
        "--state-path",
        default=None,
        help=(
            "Path to the persistent state JSON. Default: "
            f"./{DEFAULT_STATE_PATH} (resolved relative to --repo-root)."
        ),
    )
    p.add_argument(
        "--repo-root",
        default=None,
        help="Override the repo root. Default: current working directory.",
    )
    p.add_argument(
        "--event-dir",
        default=None,
        help=(
            "Directory for emitted phase_3_complete event-files. "
            f"Default: ./{DEFAULT_EVENT_DIR}."
        ),
    )

    grp = p.add_mutually_exclusive_group()
    grp.add_argument(
        "--show-marathon",
        action="store_true",
        help="Render the cross-Welle ASCII marathon table.",
    )
    grp.add_argument(
        "--show-welle",
        type=int,
        metavar="N",
        help="Render Welle N's detailed state + history.",
    )
    grp.add_argument(
        "--show-aggregat",
        action="store_true",
        help="Print only the aggregate counters as JSON.",
    )
    grp.add_argument(
        "--update-welle",
        type=int,
        metavar="N",
        help="Update Welle N's lifecycle state (requires --state).",
    )

    p.add_argument(
        "--state",
        default=None,
        help=(
            "New lifecycle state for --update-welle. Must be one of: "
            + ", ".join(s.value for s in ALL_STATES)
        ),
    )
    p.add_argument(
        "--note",
        default=None,
        help="Optional audit-note recorded into history[].note.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of ASCII tables.",
    )
    return p


def _resolve_paths(args: argparse.Namespace) -> Tuple[Path, Path]:
    repo_root = Path(args.repo_root) if args.repo_root else Path.cwd()
    state_path = (
        Path(args.state_path)
        if args.state_path
        else repo_root / DEFAULT_STATE_PATH
    )
    event_dir = (
        Path(args.event_dir)
        if args.event_dir
        else repo_root / DEFAULT_EVENT_DIR
    )
    return state_path, event_dir


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    state_path, event_dir = _resolve_paths(args)

    # If no action flag given, default to --show-marathon.
    if not any(
        [
            args.show_marathon,
            args.show_welle is not None,
            args.show_aggregat,
            args.update_welle is not None,
        ]
    ):
        args.show_marathon = True

    try:
        state = load_or_init(state_path)
    except StateFileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.update_welle is not None:
        if args.state is None:
            print(
                "error: --update-welle requires --state",
                file=sys.stderr,
            )
            return 3
        try:
            new_state = WelleLifecycleState(args.state)
        except ValueError:
            print(
                f"error: unknown state {args.state!r}; valid: "
                + ", ".join(s.value for s in ALL_STATES),
                file=sys.stderr,
            )
            return 1
        try:
            update_welle(
                state, args.update_welle, new_state, note=args.note
            )
        except UnknownWelleError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 3
        except StateTransitionError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        save_state(state, state_path)
        emit_phase_3_complete_event(state, event_dir)
        entry = state.welles[args.update_welle]
        if args.json:
            print(json.dumps(entry.to_dict(), indent=2, sort_keys=True))
        else:
            print(
                f"welle={args.update_welle} state={entry.state.value} "
                f"updated_utc={entry.last_updated_utc}"
            )
        return 0

    if args.show_welle is not None:
        try:
            text = render_welle_detail(state, args.show_welle)
        except UnknownWelleError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 3
        if args.json:
            print(
                json.dumps(
                    state.welles[args.show_welle].to_dict(),
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(text)
        return 0

    if args.show_aggregat:
        agg = compute_aggregate(state)
        print(json.dumps(agg.to_dict(), indent=2, sort_keys=True))
        return 0

    # Default: --show-marathon.
    if args.json:
        agg = compute_aggregate(state)
        payload = {
            "aggregate": agg.to_dict(),
            "welles": {
                str(n): state.welles[n].to_dict()
                for n in sorted(WELLE_DEFINITIONS)
            },
            "updated_utc": state.updated_utc,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_marathon_table(state))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
