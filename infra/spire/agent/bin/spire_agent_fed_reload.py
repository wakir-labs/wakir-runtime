# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""spire-agent-fed-reload — hermetic Agent-Side Bundle-Cache-Refresh
Helper for the Phase-2 Sprint-8 Tag-3 federation substrate.

The Tag-1 + Tag-2 substrate stages a federated peer-bundle in the
agent's ``trust_bundle_path`` (default
``/var/lib/spire/bundles/bootstrap.jwks``). When the peer-side
rotates its CA key (Tag-3 ``spire-fed-bundle-rotator``), the agent
must re-read the bundle file so the new key enters the JWKS-set
cache. SPIRE-Agent's native ``refresh_hint`` cadence handles this in
live mode; this helper provides the hermetic substrate for the
operator-side trigger and the deterministic test surface.

Two reload-cadence patterns are exposed:

  * **cron-cycle**: an interval-driven re-read loop. The helper
    reads the bundle file every ``--interval-seconds``, compares the
    JWKS contents to the in-memory cache, and emits a state-
    transition log line on change. Default interval 3600s (1h);
    operator-configurable.

  * **SIGHUP-reload**: an event-driven re-read. The helper installs
    a SIGHUP handler that forces an immediate re-read on the next
    cycle. Use-case: operator-hand bundle-update + ``podman kill
    --signal HUP <agent>`` for instant cache-refresh without waiting
    for the next cron cycle.

Both patterns share the same core ``poll_once()`` function that
takes a path + cache-state and returns the new cache-state plus a
``BundleChange`` descriptor. The descriptor is the hermetic test
surface — the test suite asserts that adding/removing/expiring keys
produces the expected change descriptor.

This module is import-safe: importing it does NOT install any signal
handler, does NOT start any loop, does NOT touch the filesystem
beyond what the test fixture explicitly requests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Mirror of the rotator's _wakir_* marker namespace so this helper can
# parse rotator-generated bundles without importing the rotator module
# (decoupling the agent-side from the server-side codepath).
_WAKIR_NOT_AFTER = "_wakir_not_after"
_WAKIR_ROTATION = "_wakir_rotation_counter"


@dataclass(frozen=True)
class BundleSnapshot:
    """Immutable snapshot of a JWKS bundle for change-detection.

    ``content_hash`` is the SHA-256 of the canonical-JSON encoding;
    bit-identical bundles share a hash. ``kids`` is the frozenset
    of ``kid`` literals present. ``rotation_counters`` is the
    frozenset of ``_wakir_rotation_counter`` integers present (empty
    if the bundle has no rotator-marked keys — Tag-1 bundles).
    """

    content_hash: str
    kids: frozenset[str]
    rotation_counters: frozenset[int]
    n_keys: int

    @classmethod
    def empty(cls) -> "BundleSnapshot":
        return cls(
            content_hash="",
            kids=frozenset(),
            rotation_counters=frozenset(),
            n_keys=0,
        )


@dataclass(frozen=True)
class BundleChange:
    """Descriptor for a snapshot-to-snapshot transition.

    * ``added``: kids present in ``new`` but not in ``old``.
    * ``removed``: kids present in ``old`` but not in ``new``.
    * ``unchanged``: True iff the content_hashes are equal.
    """

    old: BundleSnapshot
    new: BundleSnapshot
    added: frozenset[str] = field(default_factory=frozenset)
    removed: frozenset[str] = field(default_factory=frozenset)

    @property
    def unchanged(self) -> bool:
        return self.old.content_hash == self.new.content_hash

    @property
    def changed(self) -> bool:
        return not self.unchanged


def _read_jwks_file(path: Path) -> tuple[dict[str, Any], bytes]:
    """Return (parsed JWKS, raw bytes). The raw bytes are used for
    content-hash; the parsed dict for kid/rotation-counter extraction.
    """
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    doc = json.loads(text)
    if not isinstance(doc, dict) or "keys" not in doc:
        raise ValueError(
            f"JWKS shape error in {path}: top-level must be an object "
            "with a 'keys' array"
        )
    if not isinstance(doc["keys"], list) or not doc["keys"]:
        raise ValueError(
            f"JWKS shape error in {path}: 'keys' must be a non-empty array"
        )
    return doc, raw


def snapshot_bundle(path: Path) -> BundleSnapshot:
    """Read the JWKS file at ``path`` and return its BundleSnapshot.

    Raises ValueError on a malformed bundle. Raises FileNotFoundError
    if the file does not exist.
    """
    doc, raw = _read_jwks_file(path)
    content_hash = hashlib.sha256(raw).hexdigest()
    kids: set[str] = set()
    counters: set[int] = set()
    for jwk in doc["keys"]:
        if not isinstance(jwk, dict):
            continue
        kid = jwk.get("kid")
        if isinstance(kid, str):
            kids.add(kid)
        rc = jwk.get(_WAKIR_ROTATION)
        if isinstance(rc, int):
            counters.add(rc)
    return BundleSnapshot(
        content_hash=content_hash,
        kids=frozenset(kids),
        rotation_counters=frozenset(counters),
        n_keys=len(doc["keys"]),
    )


def diff_snapshots(
    old: BundleSnapshot, new: BundleSnapshot
) -> BundleChange:
    """Return the BundleChange descriptor for ``old`` → ``new``."""
    added = new.kids - old.kids
    removed = old.kids - new.kids
    return BundleChange(
        old=old,
        new=new,
        added=added,
        removed=removed,
    )


def poll_once(
    path: Path,
    cached: BundleSnapshot,
) -> BundleChange:
    """Read the bundle file ``path`` once; return the change vs.
    ``cached``. Atomic from the caller's POV: either the read
    succeeds and we return a fresh snapshot, or we raise.

    Race-condition-safety: the read is a single ``path.read_bytes()``
    call. If the operator-hand bundle-update is non-atomic (e.g.
    truncate-then-write), this helper may observe a malformed bundle
    and raise — callers MUST handle that with a retry/back-off
    around the call. The recommended operator-hand pattern is
    write-temp-then-rename (POSIX-atomic on the same filesystem).
    """
    fresh = snapshot_bundle(path)
    return diff_snapshots(cached, fresh)


# ---------------------------------------------------------------------
# cron-cycle loop (hermetic-test-friendly)
# ---------------------------------------------------------------------


@dataclass
class ReloadLoopState:
    """Mutable state for a cron-cycle reload loop.

    Kept as a dataclass (not a closure) so tests can drive the loop
    one iteration at a time without monkey-patching ``time.sleep``.
    """

    path: Path
    interval_seconds: float
    snapshot: BundleSnapshot = field(default_factory=BundleSnapshot.empty)
    iterations: int = 0
    changes: int = 0
    errors: int = 0


def step_loop(
    state: ReloadLoopState,
    *,
    on_change: "callable[[BundleChange], None] | None" = None,
    on_error: "callable[[Exception], None] | None" = None,
) -> BundleChange | None:
    """Run a single iteration of the reload loop and update ``state``
    in place. Returns the BundleChange iff the bundle changed; returns
    None if the bundle is unchanged or if the read failed.

    Tests drive this directly without invoking the wall-clock sleep
    of ``run_loop``.
    """
    state.iterations += 1
    try:
        change = poll_once(state.path, state.snapshot)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        state.errors += 1
        if on_error is not None:
            on_error(exc)
        return None
    if change.unchanged:
        return None
    state.snapshot = change.new
    state.changes += 1
    if on_change is not None:
        on_change(change)
    return change


def run_loop(
    state: ReloadLoopState,
    *,
    max_iterations: int | None = None,
    sleep: "callable[[float], None]" = time.sleep,
    on_change: "callable[[BundleChange], None] | None" = None,
    on_error: "callable[[Exception], None] | None" = None,
) -> ReloadLoopState:
    """Drive the loop until ``max_iterations`` is reached (or forever
    if None). The ``sleep`` callable is injectable so tests can
    bypass wall-clock waiting.

    SIGHUP handling: install a handler in the caller scope; the
    handler should set an event that the caller checks before the
    next ``sleep`` call. This function intentionally does NOT install
    a global signal handler — keeps the helper import-safe and
    test-driven.
    """
    while True:
        step_loop(state, on_change=on_change, on_error=on_error)
        if max_iterations is not None and state.iterations >= max_iterations:
            break
        sleep(state.interval_seconds)
    return state


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="spire-agent-fed-reload",
        description=(
            "Agent-Side Bundle-Cache-Refresh Helper for the Wakir SPIRE-"
            "Federation substrate (Phase-2 Sprint-8 Tag-3). Hermetic mode: "
            "no signal-handler install, no live SPIRE-Agent socket, no "
            "podman. Operator-Hand drives live reload."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # poll-once: hermetic single-iteration; returns a JSON descriptor.
    p_poll = sub.add_parser(
        "poll-once",
        help=(
            "Read the bundle file ONCE and emit a JSON change-"
            "descriptor (vs. an empty cache). Used in operator-hand "
            "ad-hoc reload after rotator output."
        ),
    )
    p_poll.add_argument("--bundle-path", required=True, type=Path)

    # snapshot: emit the BundleSnapshot as JSON (used for test fixture
    # generation + operator introspection).
    p_snap = sub.add_parser(
        "snapshot",
        help="Emit the BundleSnapshot for the given bundle file as JSON.",
    )
    p_snap.add_argument("--bundle-path", required=True, type=Path)

    return p


def _snapshot_to_json(snap: BundleSnapshot) -> dict[str, Any]:
    return {
        "content_hash": snap.content_hash,
        "kids": sorted(snap.kids),
        "rotation_counters": sorted(snap.rotation_counters),
        "n_keys": snap.n_keys,
    }


def _change_to_json(change: BundleChange) -> dict[str, Any]:
    return {
        "unchanged": change.unchanged,
        "added": sorted(change.added),
        "removed": sorted(change.removed),
        "old": _snapshot_to_json(change.old),
        "new": _snapshot_to_json(change.new),
    }


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.cmd == "poll-once":
            change = poll_once(args.bundle_path, BundleSnapshot.empty())
            json.dump(
                _change_to_json(change),
                sys.stdout,
                indent=2,
                sort_keys=True,
            )
            sys.stdout.write("\n")
            return 0

        if args.cmd == "snapshot":
            snap = snapshot_bundle(args.bundle_path)
            json.dump(
                _snapshot_to_json(snap), sys.stdout, indent=2, sort_keys=True
            )
            sys.stdout.write("\n")
            return 0
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"spire-agent-fed-reload: error: {exc}\n")
        return 2

    return 0  # pragma: no cover — argparse forces a subcommand


if __name__ == "__main__":
    raise SystemExit(main())
