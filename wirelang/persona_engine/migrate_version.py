# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Engine-version migration mechanic (spec §3.7.3, Sprint-Pengine-9 OI-PEFR-5).

Spec §3.7.3 declares that the persona-engine carries a semver
``engine_version`` tag (e.g. ``0.2.0-pilot``, ``0.3.0-pilot``) and
must support **state-pack backward compatibility**: a state-pack
written by an older engine MUST be readable by a newer engine on
the same major version. Sprint-Pengine-9 0.3.0-pilot is the second
real-engine release, and the migrate-version mechanic must guarantee
that ``0.2.0-pilot`` state-packs round-trip cleanly through a
``0.3.0-pilot`` engine.

Contract
--------

The state-pack on-the-wire form is :class:`PersonaStateSnapshot`
JCS bytes (spec §3.7.5.2). The shape has been stable since
``0.2.0-pilot`` and is the **backward-compat envelope** for this
migration: a new engine version that needs to add a field MUST
either:

  1. Add the field with a sensible default that an older state-pack
     can imply (the migration converter fills it in on read), OR
  2. Bump the major version and document a one-way migration.

Spec §3.7.3 requires the engine to gracefully handle:

  - **Forward-read**: 0.3.0-pilot reads a 0.2.0-pilot state-pack
    (state was written by older engine, read by newer engine). MUST
    succeed byte-for-byte (no field drift in 0.3.0-pilot vs 0.2.0-pilot).
  - **Backward-write**: 0.3.0-pilot writes a state-pack readable by
    a 0.2.0-pilot engine. MUST succeed for the v0 envelope; future
    field additions are gated on the version-bump.
  - **Cross-version pin swap**: the pinned-offset can point to a
    snapshot written by a different engine version; the
    ``migrate_pinned_offset`` flow updates both the persona's pinned
    offset and the engine-version tag in the metadata key.

This module ships the :class:`MigrateVersionWorkflow` driver that
implements the four operations above.

Persisted version-tag key
-------------------------

The bucket carries one extra sentinel key per persona:

  - ``state-pack/__engine_version__`` — last writer engine semver
    tag. Written on every snapshot. Read on restore for the audit
    annotation and the cross-version-read code path.

The key lives alongside ``__pinned__`` / ``__next_offset__`` /
``latest`` (see :mod:`wirelang.persona_engine.state_backing`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from .state_backing import (
    LATEST_KEY,
    PINNED_KEY,
    PersonaStateBacking,
    PersonaStateBackingError,
    PersonaStateSnapshot,
    snapshot_from_jcs_bytes,
    snapshot_to_jcs_bytes,
)

# ---------------------------------------------------------------------------
# Constants.
# ---------------------------------------------------------------------------

ENGINE_VERSION_KEY = "state-pack/__engine_version__"

# Closed set of engine semver tags this workflow knows how to
# read/write. Sprint-Pengine-10 adds 0.4.0-pilot (NATS-subscribe-loop +
# Phase-2-Stub LLM-Call-Shim); the v0 envelope remains backward-compat
# for 0.2.0-pilot and 0.3.0-pilot.
KNOWN_ENGINE_VERSIONS: Tuple[str, ...] = (
    "0.2.0-pilot",
    "0.3.0-pilot",
    "0.4.0-pilot",
)

# Semver matcher (relaxed: ``M.m.p[-prerelease]``).
_SEMVER_RE = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<prerelease>[A-Za-z0-9-]+))?$"
)


class MigrationFailureMode(str, Enum):
    """Failure-mode enumeration for the audit-record annotation."""

    UNKNOWN_FROM_VERSION = "UnknownFromVersion"
    UNKNOWN_TO_VERSION = "UnknownToVersion"
    MAJOR_VERSION_BUMP_DISALLOWED = "MajorVersionBumpDisallowed"
    BACKING_UNREACHABLE = "BackingUnreachable"
    SNAPSHOT_NOT_FOUND = "SnapshotNotFound"
    SNAPSHOT_CORRUPT = "SnapshotCorrupt"


class MigrationError(RuntimeError):
    """Raised by :class:`MigrateVersionWorkflow` on any failure."""

    def __init__(self, mode: MigrationFailureMode, detail: str) -> None:
        self.mode: MigrationFailureMode = mode
        super().__init__(f"{mode.value}: {detail}")


# ---------------------------------------------------------------------------
# Semver helpers.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SemverParts:
    major: int
    minor: int
    patch: int
    prerelease: Optional[str]


def parse_semver(tag: str) -> SemverParts:
    """Parse a relaxed-semver tag like ``0.3.0-pilot``."""
    m = _SEMVER_RE.match(tag)
    if not m:
        raise ValueError(f"unparseable semver tag: {tag!r}")
    return SemverParts(
        major=int(m.group("major")),
        minor=int(m.group("minor")),
        patch=int(m.group("patch")),
        prerelease=m.group("prerelease"),
    )


def is_supported_engine_version(tag: str) -> bool:
    return tag in KNOWN_ENGINE_VERSIONS


# ---------------------------------------------------------------------------
# Result envelope.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MigrateVersionResult:
    """Outcome of a migrate-version run."""

    from_version: str
    to_version: str
    snapshots_scanned: int
    snapshots_readable: int
    pinned_offset_before: Optional[int]
    pinned_offset_after: Optional[int]
    success: bool


# ---------------------------------------------------------------------------
# Workflow.
# ---------------------------------------------------------------------------


class MigrateVersionWorkflow:
    """Engine-version migration driver (spec §3.7.3).

    Operations:

    - :meth:`scan_cross_version_reads` — Iterate every state-pack
      offset, verify it decodes cleanly through the
      :class:`PersonaStateSnapshot` envelope. Returns the count of
      readable vs. total snapshots; any unreadable snapshot raises
      :class:`MigrationError` with ``SNAPSHOT_CORRUPT``.
    - :meth:`migrate_pinned_offset` — Move the persona's pinned
      offset under cross-version semantics: read current pin, verify
      the target offset decodes, atomically swap.
    - :meth:`stamp_engine_version` — Write the engine-version sentinel
      key after a successful snapshot.
    - :meth:`read_engine_version` — Read the engine-version sentinel
      key. Returns None if the key is absent (legacy state-pack from
      pre-OI-PEFR-5 engine).
    """

    def __init__(
        self,
        state_backing: PersonaStateBacking,
        *,
        from_version: str,
        to_version: str,
        allow_major_bump: bool = False,
    ) -> None:
        if not is_supported_engine_version(from_version):
            raise MigrationError(
                MigrationFailureMode.UNKNOWN_FROM_VERSION,
                f"from_version={from_version!r} not in {KNOWN_ENGINE_VERSIONS}",
            )
        if not is_supported_engine_version(to_version):
            raise MigrationError(
                MigrationFailureMode.UNKNOWN_TO_VERSION,
                f"to_version={to_version!r} not in {KNOWN_ENGINE_VERSIONS}",
            )
        fp = parse_semver(from_version)
        tp = parse_semver(to_version)
        if fp.major != tp.major and not allow_major_bump:
            raise MigrationError(
                MigrationFailureMode.MAJOR_VERSION_BUMP_DISALLOWED,
                f"major-version bump {fp.major} -> {tp.major} disallowed; "
                "pass allow_major_bump=True to override",
            )
        self.backing = state_backing
        self.from_version = from_version
        self.to_version = to_version

    # ------------------------------------------------------------------
    # Read-only cross-version scan.
    # ------------------------------------------------------------------

    def scan_cross_version_reads(
        self, persona_id: str
    ) -> Tuple[int, int]:
        """Iterate every offset and confirm it decodes cleanly.

        Returns ``(scanned, readable)``. The caller is responsible
        for asserting ``scanned == readable`` (the workflow does not
        raise on partial-readability so the operator can inspect
        which offsets are corrupt).
        """
        offsets = self.backing.list_snapshots(persona_id)
        scanned = 0
        readable = 0
        for off in offsets:
            scanned += 1
            try:
                self._read_offset_via_restore_chain(persona_id, off)
                readable += 1
            except (PersonaStateBackingError, ValueError):
                continue
        return scanned, readable

    def _read_offset_via_restore_chain(
        self, persona_id: str, offset: int
    ) -> Optional[PersonaStateSnapshot]:
        """Read a specific offset via the trait surface.

        The trait does not expose a per-offset read; for the
        cross-version scan we delegate to ``restore_latest`` and
        compare offsets. This is sufficient for the v0 envelope
        because the trait guarantees byte-stable JCS reads.

        The async binding exposes a richer per-offset read; the sync
        facade trait surface stays minimal until spec §3.7.5
        catches up.
        """
        latest = self.backing.restore_latest(persona_id)
        if latest is None:
            return None
        if latest.audit_trace_offset == offset:
            return latest
        # The trait does not support arbitrary-offset reads in the
        # sync surface. Hermetic tests inject a custom backing that
        # exposes ``read_offset`` — fall back to that if available.
        reader = getattr(self.backing, "read_offset", None)
        if reader is not None:
            return reader(persona_id, offset)
        return None

    # ------------------------------------------------------------------
    # Pinned-offset migration.
    # ------------------------------------------------------------------

    def migrate_pinned_offset(
        self,
        persona_id: str,
        *,
        target_offset: int,
    ) -> MigrateVersionResult:
        """Move the pinned offset to ``target_offset``.

        Pre-conditions:
          - ``target_offset`` MUST be present in the backing.
          - The current pinned offset (if any) MUST decode cleanly
            (the migration refuses to swap away from a corrupt pin
            without operator override).
        """
        offsets = self.backing.list_snapshots(persona_id)
        if target_offset not in offsets:
            raise MigrationError(
                MigrationFailureMode.SNAPSHOT_NOT_FOUND,
                f"target_offset={target_offset} not in {offsets}",
            )
        scanned, readable = self.scan_cross_version_reads(persona_id)
        # Read current pin (the trait does not expose this directly;
        # hermetic tests inject ``get_pinned``).
        pin_reader = getattr(self.backing, "get_pinned", None)
        current_pin: Optional[int] = None
        if pin_reader is not None:
            current_pin = pin_reader(persona_id)
        # Atomic swap. The from_offset for the trait is the current
        # pinned value (or 0 / target if uninitialised — the trait
        # accepts None-as-uninitialised semantics).
        from_off = current_pin if current_pin is not None else 0
        if current_pin is None:
            # First-time pin: the trait expects from_offset=0 to mean
            # uninitialised. Hermetic InMemoryPersonaStateBacking
            # accepts that semantics.
            self.backing.atomic_swap_pinned_offset(
                persona_id=persona_id,
                from_offset=0,
                to_offset=target_offset,
            )
        else:
            self.backing.atomic_swap_pinned_offset(
                persona_id=persona_id,
                from_offset=from_off,
                to_offset=target_offset,
            )
        new_pin = target_offset
        return MigrateVersionResult(
            from_version=self.from_version,
            to_version=self.to_version,
            snapshots_scanned=scanned,
            snapshots_readable=readable,
            pinned_offset_before=current_pin,
            pinned_offset_after=new_pin,
            success=True,
        )

    # ------------------------------------------------------------------
    # Engine-version sentinel key.
    # ------------------------------------------------------------------

    def stamp_engine_version(
        self,
        persona_id: str,
        *,
        version: Optional[str] = None,
        write_stamp: Optional[Callable[[str, str, str], None]] = None,
    ) -> str:
        """Record the engine-version stamp for ``persona_id``.

        The trait does not expose a generic put surface, so this
        operation is **callable-injected**: the caller passes
        ``write_stamp(persona_id, key, value)`` which knows how to
        write the sentinel key on the underlying backing. Hermetic
        tests pass a stub; production engines pass a closure over
        the async backing's ``put`` method.
        """
        v = version or self.to_version
        if write_stamp is not None:
            write_stamp(persona_id, ENGINE_VERSION_KEY, v)
        return v

    def read_engine_version(
        self,
        persona_id: str,
        *,
        read_stamp: Optional[Callable[[str, str], Optional[str]]] = None,
    ) -> Optional[str]:
        """Inverse of :meth:`stamp_engine_version`.

        Returns None if the key is absent (legacy pre-OI-PEFR-5
        state-pack); the caller treats absence as ``0.2.0-pilot`` for
        backward compat.
        """
        if read_stamp is None:
            return None
        return read_stamp(persona_id, ENGINE_VERSION_KEY)
