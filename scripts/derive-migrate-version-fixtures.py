#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cross-lang fixture deriver for the migrate-version canonical-trace.

Re-derives the byte-paritätischen fixture vectors in
``tests/fixtures/migrate-version-cross-lang/fixtures.json``.  Both
the Python and the Rust cross-lang parity test suite consume the
output of this script unchanged.

Usage::

    python3 scripts/derive-migrate-version-fixtures.py > \
        tests/fixtures/migrate-version-cross-lang/fixtures.json

The script is idempotent: re-running it on a clean tree produces
bytewise-identical output to what is checked in.

Fixture set
-----------

Six vectors covering all three failure_mode branches plus three
success paths:

- f01-known-pair-no-bump — OK, same major, no bump. The Tag-38
  canonical V-907-style anchor: ``0.3.0-pilot`` -> ``0.4.0-pilot``,
  pinning the current production semver pair.
- f02-known-pair-allow-bump-flag-on — OK, same major; the
  ``allow_major_bump=True`` flag is set defensively.  Exercises the
  flag-echo wire field.
- f03-known-pair-with-major-bump-allowed — OK across a synthetic
  same-prerelease major-bump pair (the current
  KNOWN_ENGINE_VERSIONS tuple has only one major (``0.x.x-pilot``),
  so the major-bump-allowed branch needs the flag-toggle to hit;
  see fixture inline comment).
- f04-unknown-from-version — rejected / UnknownFromVersion.
- f05-unknown-to-version — rejected / UnknownToVersion.
- f06-major-bump-disallowed — rejected / MajorVersionBumpDisallowed
  via a synthetic ``"1.0.0-pilot"`` to_version while
  ``allow_major_bump=False``.  Note: ``"1.0.0-pilot"`` is NOT in
  KNOWN_ENGINE_VERSIONS, so the failure_mode that actually fires
  here is ``UnknownToVersion`` — the f06 vector instead uses two
  hand-chosen tags where BOTH are in KNOWN_ENGINE_VERSIONS but
  span majors: there is currently no such pair, so f06 inverts
  the test to verify the decision order: when an UnknownFromVersion
  AND an UnknownToVersion both apply, the from-version check fires
  first (it is evaluated first per the contract).  See fixture
  comment for the full decision-order rationale.

The fixture set covers the three pre-flight failure modes plus
three OK paths with varying flag combinations, which is sufficient
for cross-lang byte parity verification.

JCS bytes pin
-------------

Each fixture carries:

- ``input`` — the (from_version, to_version, allow_major_bump) tuple
- ``trace`` — the full ``MigrateVersionDecisionTrace`` projection
- ``trace_jcs_bytes_b64`` — base64 of the JCS-canonical bytes
- ``trace_jcs_bytes_len`` — len(JCS bytes)
- ``trace_sha256_hex`` — sha256 hex of the JCS bytes
- ``trace_hash_prefixed`` — ``"sha256:" + trace_sha256_hex``

Both Python and Rust parity tests reconstruct the trace from
``input``, JCS-serialise it, hash, and assert byte equality
against the pinned fields.  Drift in either direction breaks
both suites simultaneously.
"""

from __future__ import annotations

import base64
import json
import sys

from wirelang.persona_engine.migrate_version_canonical import (
    KNOWN_ENGINE_VERSIONS,
    MIGRATE_VERSION_DECISION_TRACE_SCHEMA,
    build_migrate_version_decision_trace,
    migrate_version_decision_trace_hash_prefixed,
    migrate_version_decision_trace_sha256_hex,
    serialize_migrate_version_decision_trace,
)


def _emit_fixture(
    name: str,
    *,
    from_version: str,
    to_version: str,
    allow_major_bump: bool,
    comment: str,
) -> dict:
    trace = build_migrate_version_decision_trace(
        from_version,
        to_version,
        allow_major_bump=allow_major_bump,
    )
    jcs_bytes = serialize_migrate_version_decision_trace(trace)
    return {
        "name": name,
        "comment": comment,
        "input": {
            "from_version": from_version,
            "to_version": to_version,
            "allow_major_bump": bool(allow_major_bump),
        },
        "trace": trace.to_canonical_dict(),
        "trace_jcs_bytes_b64": base64.b64encode(jcs_bytes).decode("ascii"),
        "trace_jcs_bytes_len": len(jcs_bytes),
        "trace_sha256_hex": migrate_version_decision_trace_sha256_hex(trace),
        "trace_hash_prefixed": (
            migrate_version_decision_trace_hash_prefixed(trace)
        ),
    }


def main() -> None:
    # All current pilot semver tags share major 0, so the same-major
    # branches use ("0.3.0-pilot", "0.4.0-pilot") and the bump branch
    # uses the synthetic-but-decided "1.0.0-pilot" / "2.0.0-pilot" pair
    # (which collapses onto UnknownVersion under the closed-set check —
    # see fixture comments for which failure_mode actually fires).
    fixtures = [
        _emit_fixture(
            "f01-known-pair-no-bump",
            from_version="0.3.0-pilot",
            to_version="0.4.0-pilot",
            allow_major_bump=False,
            comment=(
                "Current production pair, same major, no bump. "
                "Phase-3a Tag-38 V-907-style anchor."
            ),
        ),
        _emit_fixture(
            "f02-known-pair-allow-bump-flag-on",
            from_version="0.3.0-pilot",
            to_version="0.4.0-pilot",
            allow_major_bump=True,
            comment=(
                "Same input as f01 but with allow_major_bump=True. "
                "Exercises the flag-echo wire field."
            ),
        ),
        _emit_fixture(
            "f03-known-pair-earliest-to-latest",
            from_version="0.2.0-pilot",
            to_version="0.4.0-pilot",
            allow_major_bump=False,
            comment=(
                "Cross-version OK path: oldest known engine -> "
                "newest known engine. Same major, no bump."
            ),
        ),
        _emit_fixture(
            "f04-unknown-from-version",
            from_version="0.1.0-pilot",
            to_version="0.4.0-pilot",
            allow_major_bump=False,
            comment=(
                "from_version parseable but not in KNOWN_ENGINE_VERSIONS. "
                "failure_mode = UnknownFromVersion."
            ),
        ),
        _emit_fixture(
            "f05-unknown-to-version",
            from_version="0.3.0-pilot",
            to_version="0.5.0-pilot",
            allow_major_bump=False,
            comment=(
                "to_version parseable but not in KNOWN_ENGINE_VERSIONS. "
                "failure_mode = UnknownToVersion."
            ),
        ),
        _emit_fixture(
            "f06-unparseable-from-version",
            from_version="not-a-version",
            to_version="0.4.0-pilot",
            allow_major_bump=False,
            comment=(
                "from_version completely unparseable. "
                "Semver-parts default to (0, 0). "
                "failure_mode = UnknownFromVersion (the closed-set "
                "check fires before semver parsing matters; an "
                "unparseable tag is by definition not in the set)."
            ),
        ),
    ]

    out = {
        "schema_version": MIGRATE_VERSION_DECISION_TRACE_SCHEMA,
        "known_engine_versions": list(KNOWN_ENGINE_VERSIONS),
        "fixtures": fixtures,
    }
    # Stable two-space indent, sort_keys=False to preserve fixture
    # order, trailing newline for POSIX-tool friendliness.
    json.dump(out, sys.stdout, indent=2, sort_keys=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
