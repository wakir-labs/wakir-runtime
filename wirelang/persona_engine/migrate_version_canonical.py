# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Engine-version migration canonical-trace helpers (Phase-3a Modul 15).

This module is the **Python sibling** of the Rust crate
``persona-engine-migrate-version`` (Tag-38 Phase-3a-Foundation
closing module). Where the BUSL-1.1 surface in
:mod:`wirelang.persona_engine.migrate_version` provides the live
state-pack workflow (:class:`MigrateVersionWorkflow`,
:class:`MigrateVersionResult`), this Apache-2.0 sibling provides a
pure-function canonical-trace projection of the **pre-flight
migration decision** — the deterministic part of the workflow that
validates the version pair and the major-bump policy before any
state-backing I/O happens.

Why a sibling module?
---------------------

The live workflow is stateful: it talks to a
:class:`PersonaStateBacking`, lists snapshots, reads / writes the
pinned offset, stamps the engine-version sentinel key. None of that
is byte-paritätisch across Python and Rust without a network of
mocked backings.

The **pre-flight decision** — "is this (from_version, to_version,
allow_major_bump) tuple acceptable, and if not why?" — IS
byte-paritätisch and is the cross-engine determinism anchor called
out by the Selin roadmap §1.3 ("state-pack envelope must be
byte-stable across engines").

The trace surface captures exactly that: parse both semver tags,
check known-version membership, evaluate the major-bump rule,
produce a structured ``MigrateVersionDecisionTrace``.

Schema
------

The canonical-trace carries exactly eleven top-level fields
(alphabetically sorted in the canonical form):

- ``accepted_status`` — One of ``"ok"``, ``"rejected"``.
- ``allow_major_bump`` — Boolean policy bit echoed for trace
  reproducibility. ``True`` iff the caller passed
  ``allow_major_bump=True``.
- ``failure_mode`` — Wire-string of :class:`MigrationFailureMode`
  on ``rejected``; empty string ``""`` on ``ok``. Values:
  ``"UnknownFromVersion"``, ``"UnknownToVersion"``,
  ``"MajorVersionBumpDisallowed"``. (The four backing-side modes —
  ``BackingUnreachable`` / ``SnapshotNotFound`` / ``SnapshotCorrupt``
  / ``MajorVersionBumpDisallowed`` post-check — are NOT reachable
  pre-flight and therefore not pinned on this surface.)
- ``from_major`` — ``int``. Semver-parsed major component of
  ``from_version``. Zero on parse-failure (i.e. when
  ``failure_mode == "UnknownFromVersion"`` because of a
  ``KNOWN_ENGINE_VERSIONS`` miss). Always present.
- ``from_minor`` — ``int``. Semver-parsed minor component. Zero on
  parse-failure. Always present.
- ``from_version`` — The input string echoed verbatim. Empty
  string if the caller passed an empty input (the parse failure
  collapses onto ``UnknownFromVersion``).
- ``major_bump_required`` — Boolean. ``True`` iff
  ``from_major != to_major`` after both parses succeed. ``False``
  on any parse-fail (the wire field is schema-symmetric — always
  present, never omitted).
- ``schema`` — Constant schema id
  ``"wakir.persona-engine.migrate-version-canonical/1"``.
- ``to_major`` — ``int``. Semver-parsed major component of
  ``to_version``. Zero on parse-failure.
- ``to_minor`` — ``int``. Semver-parsed minor component. Zero on
  parse-failure.
- ``to_version`` — The input string echoed verbatim.

Serialisation
-------------

The canonical bytes are produced by ``rfc8785.dumps`` (RFC 8785
JCS). The outer trace hash is
``"sha256:" + hex(SHA-256(canonical_bytes))``.

Same serialisation discipline as every other Phase-3a cross-lang
canonical-trace module — JCS-canonical bytes, SHA-256, hex,
prefixed with ``"sha256:"``. Rust pendant uses ``serde_jcs::to_vec``
+ ``sha2::Sha256``.

Cross-lang anchor
-----------------

The fixture file
``tests/fixtures/migrate-version-cross-lang/fixtures.json`` is the
byte-level cross-lang pin: both
``wirelang/tests/persona_engine/test_migrate_version_cross_lang_parity.py``
(Python) and
``wirelang-rust/crates/persona-engine-migrate-version/tests/cross_lang_fixture_test.rs``
(Rust) consume the same vectors. Any drift on either side fails
both suites.

Schema-parity table (Python <-> Rust)
--------------------------------------

::

    Python helper                                          <-> Rust pendant
    -----------------------------------------------------------------------
    build_migrate_version_decision_trace(...)              <-> build_migrate_version_decision_trace
    serialize_migrate_version_decision_trace(trace)        <-> serialize_trace
    migrate_version_decision_trace_sha256_hex(trace)       <-> trace_sha256_hex
    migrate_version_decision_trace_hash_prefixed(trace)    <-> trace_hash_prefixed
    MigrateVersionDecisionTrace (dataclass)                <-> MigrateVersionDecisionTrace
    MIGRATE_VERSION_DECISION_TRACE_SCHEMA / HASH_PREFIX /
      SHA256_HEX_LEN                                       <-> same constants

ADR anchors
-----------

- ADR-0063 §Folgeartefakte Phase-3a — closes the 15-module
  Phase-3a-Foundation sweep (state-pack-envelope cross-engine
  determinism anchor per roadmap §1.3).
- ADR-0065 — Phase-3c cutover; engine-version migration is a
  pre-condition for any Rust-engine that needs to read state-packs
  written by the Python-engine.
- ADR-0066 — Phase-3c-Beschleunigung; this module unblocks the
  Welle-7 final cutover by giving operators a deterministic
  pre-flight check for engine-version upgrades.

V-907 pin pack anchor
---------------------

The ``f01-known-pair-no-bump`` fixture pins the historical
SAMPLE V-907 anchor pin context: the ``from_version`` /
``to_version`` pair are the two engine semver tags in current
production circulation
(``"0.3.0-pilot"`` -> ``"0.4.0-pilot"``), and the trace's
``major_bump_required`` is ``False`` (matching the byte-stable
v0-envelope contract documented in :mod:`migrate_version`).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Final

# ---------------------------------------------------------------------------
# Optional-dependency resolver (same posture as v907_verify_canonical).
# ---------------------------------------------------------------------------

try:  # pragma: no cover - production path always has rfc8785
    import rfc8785 as _rfc8785_lib

    _HAS_RFC8785 = True
except ImportError:  # pragma: no cover - shadow-lane fallback path
    _rfc8785_lib = None  # type: ignore[assignment]
    _HAS_RFC8785 = False


#: JCS-canonical schema id for the migrate-version decision trace.
#: Cross-lang anchor — must match the Rust constant of the same name.
MIGRATE_VERSION_DECISION_TRACE_SCHEMA: Final[str] = (
    "wakir.persona-engine.migrate-version-canonical/1"
)

#: Outer-hash prefix.  Cross-lang anchor.
HASH_PREFIX: Final[str] = "sha256:"

#: Length of a SHA-256 hex digest (32 bytes = 64 hex chars).
SHA256_HEX_LEN: Final[int] = 64

#: Accepted-status wire-string values.  Frozen across Rust/Python.
STATUS_OK: Final[str] = "ok"
STATUS_REJECTED: Final[str] = "rejected"

ACCEPTED_STATUS_VALUES: Final[tuple[str, ...]] = (
    STATUS_OK,
    STATUS_REJECTED,
)

#: Failure-mode wire-string values reachable from the pre-flight
#: decision surface.  Frozen across Rust/Python.  The four backing-side
#: modes (BackingUnreachable / SnapshotNotFound / SnapshotCorrupt /
#: post-flight MajorVersionBumpDisallowed) are NOT reachable here and
#: therefore not pinned.
FAILURE_MODE_UNKNOWN_FROM_VERSION: Final[str] = "UnknownFromVersion"
FAILURE_MODE_UNKNOWN_TO_VERSION: Final[str] = "UnknownToVersion"
FAILURE_MODE_MAJOR_VERSION_BUMP_DISALLOWED: Final[str] = (
    "MajorVersionBumpDisallowed"
)

FAILURE_MODE_VALUES: Final[tuple[str, ...]] = (
    "",
    FAILURE_MODE_UNKNOWN_FROM_VERSION,
    FAILURE_MODE_UNKNOWN_TO_VERSION,
    FAILURE_MODE_MAJOR_VERSION_BUMP_DISALLOWED,
)

#: Closed set of engine semver tags this canonical-trace knows about.
#: Mirrors :data:`wirelang.persona_engine.migrate_version.KNOWN_ENGINE_VERSIONS`
#: byte-for-byte; the Rust crate carries the same tuple.  Any addition
#: requires a coordinated three-place edit (Python live module + Python
#: canonical sibling + Rust crate) and a fixture re-derivation.
KNOWN_ENGINE_VERSIONS: Final[tuple[str, ...]] = (
    "0.2.0-pilot",
    "0.3.0-pilot",
    "0.4.0-pilot",
)

# Semver matcher (relaxed: ``M.m.p[-prerelease]``).  Pattern matches
# the live module's ``_SEMVER_RE`` byte-for-byte; the Rust crate uses
# the same pattern via the ``regex`` crate.
_SEMVER_RE = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<prerelease>[A-Za-z0-9-]+))?$"
)


# ---------------------------------------------------------------------------
# Trace dataclass.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MigrateVersionDecisionTrace:
    """Canonical-trace projection of a migrate-version pre-flight decision.

    Fields are ordered to match the alphabetical JCS sort the wire form
    uses; the dataclass itself is otherwise an opaque record.
    """

    accepted_status: str
    allow_major_bump: bool
    failure_mode: str
    from_major: int
    from_minor: int
    from_version: str
    major_bump_required: bool
    to_major: int
    to_minor: int
    to_version: str

    def to_canonical_dict(self) -> dict[str, Any]:
        """Project this trace onto a JSON-compatible dict, ready for JCS.

        Keys are inserted in alphabetical order to document the wire
        contract; JCS will re-sort them lexicographically anyway, so
        the insertion order has no effect on the resulting bytes.
        """
        return {
            "accepted_status": self.accepted_status,
            "allow_major_bump": bool(self.allow_major_bump),
            "failure_mode": self.failure_mode,
            "from_major": int(self.from_major),
            "from_minor": int(self.from_minor),
            "from_version": self.from_version,
            "major_bump_required": bool(self.major_bump_required),
            "schema": MIGRATE_VERSION_DECISION_TRACE_SCHEMA,
            "to_major": int(self.to_major),
            "to_minor": int(self.to_minor),
            "to_version": self.to_version,
        }


# ---------------------------------------------------------------------------
# Trace-build helpers.
# ---------------------------------------------------------------------------


def _parse_semver_strict(tag: str) -> tuple[int, int, bool]:
    """Parse a semver tag, return ``(major, minor, ok)``.

    ``ok`` is ``False`` if the tag does not match the relaxed-semver
    grammar; ``major`` / ``minor`` then default to ``0``.  This is the
    pre-flight surface — the caller decides what to do on failure.
    """
    m = _SEMVER_RE.match(tag)
    if not m:
        return 0, 0, False
    return int(m.group("major")), int(m.group("minor")), True


def build_migrate_version_decision_trace(
    from_version: str,
    to_version: str,
    *,
    allow_major_bump: bool = False,
) -> MigrateVersionDecisionTrace:
    """Build a canonical migrate-version pre-flight decision trace.

    The function is **infallible** at the trace-build layer: every
    decision outcome (success, unknown-from, unknown-to,
    major-bump-disallowed) is captured as a structured trace with the
    appropriate ``accepted_status`` and ``failure_mode`` populated.

    Decision order
    --------------

    1. ``from_version`` not in :data:`KNOWN_ENGINE_VERSIONS` ->
       ``rejected`` / ``UnknownFromVersion``.  Semver parts default
       to (0, 0) if the tag is unparseable; otherwise the parsed
       major / minor are echoed for diagnostics.
    2. ``to_version`` not in :data:`KNOWN_ENGINE_VERSIONS` ->
       ``rejected`` / ``UnknownToVersion``.  Same parts-echo policy.
    3. ``from_major != to_major`` AND not ``allow_major_bump`` ->
       ``rejected`` / ``MajorVersionBumpDisallowed``.
    4. Otherwise -> ``ok``.

    The order of evaluation is part of the cross-lang contract.
    Re-ordering between (1) and (2) would change the failure_mode
    on a (unknown, unknown) pair and is forbidden.

    ``major_bump_required`` echoes ``from_major != to_major`` whenever
    both versions parse cleanly, regardless of the
    ``allow_major_bump`` flag.  This is operator-readable signal: a
    successful ``ok`` trace with ``major_bump_required=True`` means
    the caller explicitly opted into a major-version bump.
    """
    from_major, from_minor, from_parsed = _parse_semver_strict(from_version)
    to_major, to_minor, to_parsed = _parse_semver_strict(to_version)

    from_known = from_version in KNOWN_ENGINE_VERSIONS
    to_known = to_version in KNOWN_ENGINE_VERSIONS

    # major_bump_required is meaningful only when BOTH parse cleanly.
    # When either tag is unparseable the field is ``False`` (the
    # schema-symmetric default).
    if from_parsed and to_parsed:
        major_bump_required = from_major != to_major
    else:
        major_bump_required = False

    if not from_known:
        return MigrateVersionDecisionTrace(
            accepted_status=STATUS_REJECTED,
            allow_major_bump=bool(allow_major_bump),
            failure_mode=FAILURE_MODE_UNKNOWN_FROM_VERSION,
            from_major=from_major,
            from_minor=from_minor,
            from_version=from_version,
            major_bump_required=major_bump_required,
            to_major=to_major,
            to_minor=to_minor,
            to_version=to_version,
        )

    if not to_known:
        return MigrateVersionDecisionTrace(
            accepted_status=STATUS_REJECTED,
            allow_major_bump=bool(allow_major_bump),
            failure_mode=FAILURE_MODE_UNKNOWN_TO_VERSION,
            from_major=from_major,
            from_minor=from_minor,
            from_version=from_version,
            major_bump_required=major_bump_required,
            to_major=to_major,
            to_minor=to_minor,
            to_version=to_version,
        )

    if major_bump_required and not allow_major_bump:
        return MigrateVersionDecisionTrace(
            accepted_status=STATUS_REJECTED,
            allow_major_bump=bool(allow_major_bump),
            failure_mode=FAILURE_MODE_MAJOR_VERSION_BUMP_DISALLOWED,
            from_major=from_major,
            from_minor=from_minor,
            from_version=from_version,
            major_bump_required=True,
            to_major=to_major,
            to_minor=to_minor,
            to_version=to_version,
        )

    return MigrateVersionDecisionTrace(
        accepted_status=STATUS_OK,
        allow_major_bump=bool(allow_major_bump),
        failure_mode="",
        from_major=from_major,
        from_minor=from_minor,
        from_version=from_version,
        major_bump_required=major_bump_required,
        to_major=to_major,
        to_minor=to_minor,
        to_version=to_version,
    )


# ---------------------------------------------------------------------------
# Trace serialisation + hashing.
# ---------------------------------------------------------------------------


def serialize_migrate_version_decision_trace(
    trace: MigrateVersionDecisionTrace,
) -> bytes:
    """Serialise a trace to its JCS-canonical UTF-8 bytes.

    Raises:
        PersonaCanonicalFormDependencyMissingError: if ``rfc8785`` is
            not installed in this environment.  (Re-raised as the
            shared dependency-missing error class so callers can
            surface install hints uniformly across the sibling-set.)
    """
    if not _HAS_RFC8785:
        from wirelang.persona.persona_canonical_form import (
            PersonaCanonicalFormDependencyMissingError,
        )

        raise PersonaCanonicalFormDependencyMissingError("rfc8785")
    return _rfc8785_lib.dumps(trace.to_canonical_dict())


def migrate_version_decision_trace_sha256_hex(
    trace: MigrateVersionDecisionTrace,
) -> str:
    """SHA-256 hex of the JCS bytes of ``trace``."""
    return hashlib.sha256(
        serialize_migrate_version_decision_trace(trace)
    ).hexdigest()


def migrate_version_decision_trace_hash_prefixed(
    trace: MigrateVersionDecisionTrace,
) -> str:
    """Prefixed outer hash: ``"sha256:" + sha256_hex``."""
    return HASH_PREFIX + migrate_version_decision_trace_sha256_hex(trace)


# ---------------------------------------------------------------------------
# Re-exports for downstream importers that want one-stop access.
# ---------------------------------------------------------------------------

__all__ = [
    "ACCEPTED_STATUS_VALUES",
    "FAILURE_MODE_MAJOR_VERSION_BUMP_DISALLOWED",
    "FAILURE_MODE_UNKNOWN_FROM_VERSION",
    "FAILURE_MODE_UNKNOWN_TO_VERSION",
    "FAILURE_MODE_VALUES",
    "HASH_PREFIX",
    "KNOWN_ENGINE_VERSIONS",
    "MIGRATE_VERSION_DECISION_TRACE_SCHEMA",
    "MigrateVersionDecisionTrace",
    "SHA256_HEX_LEN",
    "STATUS_OK",
    "STATUS_REJECTED",
    "build_migrate_version_decision_trace",
    "migrate_version_decision_trace_hash_prefixed",
    "migrate_version_decision_trace_sha256_hex",
    "serialize_migrate_version_decision_trace",
]
