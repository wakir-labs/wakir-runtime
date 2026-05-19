# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-67 shared audit-trail-marker-constants tests (Tomás).

Pins the substance contract of
``tooling/ci/shared/audit_trail_marker_constants.py``:

* the canonical four marker source classes (operator / ar / cron /
  replay),
* the regex primitives (slug, RFC3339, dispatched_at, UUID,
  audit-marker-tag),
* the audit-trail schema field tuples used by both Tag-66 verifier
  helpers,
* the Cutover-Day verdict tokens + Watch-Day audit-trail verdict
  tokens,
* the audit-trail-note canonical substrings,
* the pure-function helpers (parse, build),
* the **additive-refactor invariant**: both Tag-66 verifier helpers
  re-export the shared values verbatim under the names that the
  Tag-66 test suites depend on.

Hermetic: pytest + stdlib + python 3.11. No subprocess, no network,
no podman.

Author: Tomás Reinhart (Dev-Engineering)
Anchor: Tag-67 Shared-Constants-Module-Extraction (Noa Tag-66
        Folge-Item §3, Marathon-Continuous-Mode).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


from tooling.ci.shared import audit_trail_marker_constants as shared  # noqa: E402
from tooling.ci import verify_ar_hand_override_audit_trail as tomas_verifier  # noqa: E402
from tooling.ci import verify_watch_day_operator_trigger_audit_trail as noa_verifier  # noqa: E402


# ---------------------------------------------------------------------------
# T01 - shared module is importable and exposes the canonical __all__.
# ---------------------------------------------------------------------------
def test_t01_shared_module_exposes_canonical_all():
    """The public surface (``__all__``) MUST enumerate the names that
    downstream verifiers and tests rely on. Drift in this set
    forces a coordinated update across all consumers."""
    expected = {
        # Event constants
        "CANONICAL_EVENT",
        "CANONICAL_WORKFLOW",
        "CANONICAL_REF",
        # Marker source classes
        "MarkerSourceClass",
        "MARKER_SOURCE_CLASSES",
        "MARKER_SOURCE_CLASSES_BY_SOURCE",
        "MARKER_SOURCE_CLASSES_BY_NAME",
        "MARKER_SOURCE_TOKENS",
        # Regex primitives
        "SLUG_PATTERN",
        "RFC3339_TIMESTAMP_PATTERN",
        "DISPATCHED_AT_PATTERN",
        "UUID_PATTERN",
        "AUDIT_MARKER_TAG_PATTERN",
        # Schema field tuples
        "AR_OVERRIDE_ENVELOPE_REQUIRED_KEYS",
        "AR_OVERRIDE_MARKER_REQUIRED_FIELDS",
        "WATCH_DAY_ENVELOPE_REQUIRED_KEYS",
        "WATCH_DAY_BASE_KEYS_TAG62",
        "WATCH_DAY_AUDIT_ONLY_KEYS",
        # AR-Hand marker constants
        "AR_OVERRIDE_MARKER_KIND",
        "AR_OVERRIDE_MARKER_SCHEMA_VERSION",
        "AR_OVERRIDE_REASON_MIN_LEN",
        "AR_OVERRIDE_REASON_MAX_LEN",
        # Cutover-Day verdict tokens
        "VERDICT_CUTOVER_DAY_READY",
        "VERDICT_CUTOVER_DAY_CAUTION",
        "VERDICT_CUTOVER_DAY_BLOCK",
        "CUTOVER_DAY_VERDICTS",
        "AR_OVERRIDE_TARGET_VERDICT",
        "AR_OVERRIDE_POST_VERDICT",
        # Watch-Day verdict tokens
        "WATCH_DAY_VERDICT_INTACT",
        "WATCH_DAY_VERDICT_DRIFT",
        "WATCH_DAY_VERDICT_DEFECT",
        "WATCH_DAY_AUDIT_TRAIL_VERDICTS",
        "STAGE_STATUS_GREEN",
        "STAGE_STATUS_YELLOW",
        "STAGE_STATUS_RED",
        "VALID_STAGE_STATUSES",
        # Audit-trail-note tokens
        "NOTE_OVERRIDE_APPLIED_PREFIX",
        "NOTE_STALE_MARKER_GUARD_TOKENS",
        "NOTE_NO_MARKER_TOKEN",
        # Helpers
        "parse_audit_marker_tag_source",
        "build_audit_marker_tag",
        # Module metadata
        "SHARED_CONSTANTS_SCHEMA_VERSION",
    }
    assert set(shared.__all__) == expected, (
        f"__all__ drift: missing={expected - set(shared.__all__)}, "
        f"extra={set(shared.__all__) - expected}"
    )
    # Every name in __all__ must actually exist on the module.
    for name in shared.__all__:
        assert hasattr(shared, name), f"__all__ lists missing name: {name!r}"


# ---------------------------------------------------------------------------
# T02 - marker source classes are exactly the four canonical entries.
# ---------------------------------------------------------------------------
def test_t02_marker_source_classes_are_canonical_four():
    """The catalog enumerates exactly operator / ar / cron / replay
    with their expected GitHub event types. Any addition to the
    catalog is a breaking ADR-0070 schema change."""
    sources = [m.source for m in shared.MARKER_SOURCE_CLASSES]
    assert sources == ["operator", "ar", "cron", "replay"]
    assert shared.MARKER_SOURCE_TOKENS == frozenset(
        {"operator", "ar", "cron", "replay"}
    )
    # Event-type contract.
    by_source = shared.MARKER_SOURCE_CLASSES_BY_SOURCE
    assert by_source["operator"].expected_event == "workflow_dispatch"
    assert by_source["ar"].expected_event == "workflow_dispatch"
    assert by_source["cron"].expected_event == "schedule"
    assert by_source["replay"].expected_event == "workflow_dispatch"
    # By-name lookup mirrors by-source.
    assert (
        shared.MARKER_SOURCE_CLASSES_BY_NAME["operator-hand-dispatch"]
        is by_source["operator"]
    )
    assert (
        shared.MARKER_SOURCE_CLASSES_BY_NAME["ar-hand-override"]
        is by_source["ar"]
    )


# ---------------------------------------------------------------------------
# T03 - MarkerSourceClass is frozen (immutable) and hashable.
# ---------------------------------------------------------------------------
def test_t03_marker_source_class_is_frozen():
    """Frozen dataclass guards against accidental mutation in
    consumer hot-loops. The dataclass instances must also be
    hashable so they can be used in sets / dict keys."""
    op = shared.MARKER_SOURCE_CLASSES_BY_SOURCE["operator"]
    with pytest.raises(Exception):  # FrozenInstanceError (dataclasses)
        op.source = "tampered"  # type: ignore[misc]
    # Hashability.
    s = {op, shared.MARKER_SOURCE_CLASSES_BY_SOURCE["ar"]}
    assert len(s) == 2


# ---------------------------------------------------------------------------
# T04 - audit-marker-tag pattern matches canonical examples + rejects
#       drift cases.
# ---------------------------------------------------------------------------
def test_t04_audit_marker_tag_pattern_canonical_cases():
    """Pattern: ``watch-day-<source>-<YYYYMMDD>-<short-hash>``."""
    pat = shared.AUDIT_MARKER_TAG_PATTERN
    # Canonical pass cases for each source.
    for src in ("operator", "ar", "cron", "replay"):
        tag = f"watch-day-{src}-20260609-3bc7794"
        m = pat.match(tag)
        assert m is not None, f"should match: {tag!r}"
        assert m.group(1) == src
        assert m.group(2) == "20260609"
        assert m.group(3) == "3bc7794"
    # Short-hash bounds: 7..12 hex.
    assert pat.match("watch-day-operator-20260609-3bc7794a") is not None
    assert pat.match("watch-day-operator-20260609-3bc7794abcde") is not None
    # Fail cases.
    fail_cases = [
        "watch-day-unknown-20260609-3bc7794",  # unknown source
        "watch-day-operator-2026060-3bc7794",  # date too short
        "watch-day-operator-20260609-3bc",  # hash too short
        "watch-day-operator-20260609-G3bc7794",  # non-hex char
        "WATCH-day-operator-20260609-3bc7794",  # case-sensitive prefix
        "phase-3-operator-20260609-3bc7794",  # wrong prefix
    ]
    for tag in fail_cases:
        assert pat.match(tag) is None, f"should not match: {tag!r}"


# ---------------------------------------------------------------------------
# T05 - regex primitives (slug, RFC3339, dispatched_at, UUID) are
#       independently sound.
# ---------------------------------------------------------------------------
def test_t05_regex_primitives_independent_checks():
    # Slug.
    assert shared.SLUG_PATTERN.match("mira-hand-operator")
    assert shared.SLUG_PATTERN.match("risk-id-7")
    assert not shared.SLUG_PATTERN.match("MIRA-Hand")  # uppercase
    assert not shared.SLUG_PATTERN.match("-leading-hyphen")
    assert not shared.SLUG_PATTERN.match("a")  # too short (1 char)

    # RFC3339 strict (offset required).
    assert shared.RFC3339_TIMESTAMP_PATTERN.match("2026-06-09T05:00:00Z")
    assert shared.RFC3339_TIMESTAMP_PATTERN.match(
        "2026-06-09T05:00:00.123+02:00"
    )
    assert not shared.RFC3339_TIMESTAMP_PATTERN.match(
        "2026-06-09T05:00:00"  # no offset
    )

    # dispatched_at tolerant (offset optional).
    assert shared.DISPATCHED_AT_PATTERN.match("2026-06-09T05:00:00Z")
    assert shared.DISPATCHED_AT_PATTERN.match("2026-06-09T05:00:00")
    assert not shared.DISPATCHED_AT_PATTERN.match("2026-06-09 05:00:00")

    # UUID (case-insensitive).
    assert shared.UUID_PATTERN.match(
        "12345678-1234-1234-1234-123456789abc"
    )
    assert shared.UUID_PATTERN.match(
        "12345678-1234-1234-1234-123456789ABC"
    )
    assert not shared.UUID_PATTERN.match("not-a-uuid")


# ---------------------------------------------------------------------------
# T06 - audit-trail schema field tuples are immutable + non-empty.
# ---------------------------------------------------------------------------
def test_t06_schema_field_tuples_shape():
    # All schema tuples must be tuples (not lists), non-empty,
    # and contain only non-empty strings.
    field_tuples = (
        shared.AR_OVERRIDE_ENVELOPE_REQUIRED_KEYS,
        shared.AR_OVERRIDE_MARKER_REQUIRED_FIELDS,
        shared.WATCH_DAY_ENVELOPE_REQUIRED_KEYS,
        shared.WATCH_DAY_BASE_KEYS_TAG62,
        shared.WATCH_DAY_AUDIT_ONLY_KEYS,
    )
    for t in field_tuples:
        assert isinstance(t, tuple), f"not a tuple: {t!r}"
        assert len(t) > 0
        for k in t:
            assert isinstance(k, str) and k, f"bad key: {k!r}"
    # Watch-Day audit-only-keys + base-keys partition the full
    # required-keys set without overlap.
    base = set(shared.WATCH_DAY_BASE_KEYS_TAG62)
    audit = set(shared.WATCH_DAY_AUDIT_ONLY_KEYS)
    full = set(shared.WATCH_DAY_ENVELOPE_REQUIRED_KEYS)
    assert base.isdisjoint(audit), "base and audit-only must not overlap"
    assert base | audit == full, "base + audit-only must equal full"


# ---------------------------------------------------------------------------
# T07 - verdict tokens + stage-status sets are consistent.
# ---------------------------------------------------------------------------
def test_t07_verdict_token_sets_consistent():
    # Cutover-Day verdict triplet.
    assert shared.VERDICT_CUTOVER_DAY_READY == "CUTOVER-DAY-MORGEN-READY"
    assert (
        shared.VERDICT_CUTOVER_DAY_CAUTION == "CUTOVER-DAY-MORGEN-CAUTION"
    )
    assert shared.VERDICT_CUTOVER_DAY_BLOCK == "CUTOVER-DAY-MORGEN-BLOCK"
    assert shared.CUTOVER_DAY_VERDICTS == frozenset(
        {
            shared.VERDICT_CUTOVER_DAY_READY,
            shared.VERDICT_CUTOVER_DAY_CAUTION,
            shared.VERDICT_CUTOVER_DAY_BLOCK,
        }
    )
    # Override transition: BLOCK -> CAUTION, never BLOCK -> READY.
    assert (
        shared.AR_OVERRIDE_TARGET_VERDICT
        == shared.VERDICT_CUTOVER_DAY_BLOCK
    )
    assert (
        shared.AR_OVERRIDE_POST_VERDICT
        == shared.VERDICT_CUTOVER_DAY_CAUTION
    )

    # Watch-Day audit-trail verdict triplet.
    assert shared.WATCH_DAY_VERDICT_INTACT == "AUDIT-TRAIL-INTACT"
    assert shared.WATCH_DAY_VERDICT_DRIFT == "AUDIT-TRAIL-DRIFT"
    assert shared.WATCH_DAY_VERDICT_DEFECT == "AUDIT-TRAIL-DEFECT"
    assert shared.WATCH_DAY_AUDIT_TRAIL_VERDICTS == frozenset(
        {
            shared.WATCH_DAY_VERDICT_INTACT,
            shared.WATCH_DAY_VERDICT_DRIFT,
            shared.WATCH_DAY_VERDICT_DEFECT,
        }
    )
    # Stage-status set.
    assert shared.VALID_STAGE_STATUSES == frozenset(
        {
            shared.STAGE_STATUS_GREEN,
            shared.STAGE_STATUS_YELLOW,
            shared.STAGE_STATUS_RED,
        }
    )


# ---------------------------------------------------------------------------
# T08 - audit-trail-note canonical substrings are non-empty strings.
# ---------------------------------------------------------------------------
def test_t08_audit_trail_note_constants():
    assert (
        shared.NOTE_OVERRIDE_APPLIED_PREFIX == "AR-Hand override applied"
    )
    assert shared.NOTE_NO_MARKER_TOKEN == "no override marker"
    assert isinstance(shared.NOTE_STALE_MARKER_GUARD_TOKENS, tuple)
    assert "marker recorded" in shared.NOTE_STALE_MARKER_GUARD_TOKENS
    assert "verdict unchanged" in shared.NOTE_STALE_MARKER_GUARD_TOKENS


# ---------------------------------------------------------------------------
# T09 - parse_audit_marker_tag_source returns source or None.
# ---------------------------------------------------------------------------
def test_t09_parse_audit_marker_tag_source():
    f = shared.parse_audit_marker_tag_source
    assert f("watch-day-operator-20260609-3bc7794") == "operator"
    assert f("watch-day-ar-20260609-deadbeef") == "ar"
    assert f("watch-day-cron-20260609-cafebabe") == "cron"
    assert f("watch-day-replay-20260609-f00dface") == "replay"
    # Non-matches.
    assert f("watch-day-unknown-20260609-3bc7794") is None
    assert f("not-a-tag") is None
    assert f("") is None
    # Non-string inputs return None (no exception).
    assert f(None) is None  # type: ignore[arg-type]
    assert f(123) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# T10 - build_audit_marker_tag round-trips with parse_*.
# ---------------------------------------------------------------------------
def test_t10_build_audit_marker_tag_round_trip():
    for src in ("operator", "ar", "cron", "replay"):
        tag = shared.build_audit_marker_tag(src, "20260609", "3bc7794")
        assert tag == f"watch-day-{src}-20260609-3bc7794"
        assert shared.AUDIT_MARKER_TAG_PATTERN.match(tag)
        assert shared.parse_audit_marker_tag_source(tag) == src


# ---------------------------------------------------------------------------
# T11 - build_audit_marker_tag rejects invalid inputs with ValueError.
# ---------------------------------------------------------------------------
def test_t11_build_audit_marker_tag_validation():
    # Unknown source.
    with pytest.raises(ValueError, match="unknown marker source"):
        shared.build_audit_marker_tag("unknown", "20260609", "3bc7794")
    # Bad date.
    with pytest.raises(ValueError, match="date_yyyymmdd"):
        shared.build_audit_marker_tag("operator", "2026-06-09", "3bc7794")
    with pytest.raises(ValueError, match="date_yyyymmdd"):
        shared.build_audit_marker_tag("operator", "abcdefgh", "3bc7794")
    # Bad hash.
    with pytest.raises(ValueError, match="short_hash"):
        shared.build_audit_marker_tag("operator", "20260609", "3bc")
    with pytest.raises(ValueError, match="short_hash"):
        shared.build_audit_marker_tag(
            "operator", "20260609", "TOOLONG12345678"
        )
    with pytest.raises(ValueError, match="short_hash"):
        shared.build_audit_marker_tag(
            "operator", "20260609", "G0fbabe7"  # non-hex
        )


# ---------------------------------------------------------------------------
# T12 - Tomás verifier re-exports shared constants verbatim.
# ---------------------------------------------------------------------------
def test_t12_tomas_verifier_aliases_shared_constants():
    """Additive-refactor invariant: every constant that Tomás's
    Tag-66 verifier exposes at module level MUST be the exact
    object from the shared module (object identity for the regex
    + frozensets + tuples; equality for strings/ints)."""
    assert tomas_verifier.VERDICT_READY == shared.VERDICT_CUTOVER_DAY_READY
    assert (
        tomas_verifier.VERDICT_CAUTION == shared.VERDICT_CUTOVER_DAY_CAUTION
    )
    assert tomas_verifier.VERDICT_BLOCK == shared.VERDICT_CUTOVER_DAY_BLOCK
    assert tomas_verifier.ALLOWED_VERDICTS is shared.CUTOVER_DAY_VERDICTS

    assert (
        tomas_verifier.ENVELOPE_REQUIRED_KEYS
        is shared.AR_OVERRIDE_ENVELOPE_REQUIRED_KEYS
    )
    assert tomas_verifier.MARKER_KIND == shared.AR_OVERRIDE_MARKER_KIND
    assert (
        tomas_verifier.MARKER_SCHEMA_VERSION
        == shared.AR_OVERRIDE_MARKER_SCHEMA_VERSION
    )
    assert (
        tomas_verifier.MARKER_REQUIRED_FIELDS
        is shared.AR_OVERRIDE_MARKER_REQUIRED_FIELDS
    )
    assert (
        tomas_verifier.MARKER_OVERRIDE_TARGET
        == shared.AR_OVERRIDE_TARGET_VERDICT
    )
    assert (
        tomas_verifier.MARKER_POST_OVERRIDE == shared.AR_OVERRIDE_POST_VERDICT
    )
    assert tomas_verifier._SLUG_RE is shared.SLUG_PATTERN
    assert tomas_verifier._TS_RE is shared.RFC3339_TIMESTAMP_PATTERN
    assert tomas_verifier.REASON_MIN_LEN == shared.AR_OVERRIDE_REASON_MIN_LEN
    assert tomas_verifier.REASON_MAX_LEN == shared.AR_OVERRIDE_REASON_MAX_LEN
    assert (
        tomas_verifier.NOTE_APPLIED_PREFIX
        == shared.NOTE_OVERRIDE_APPLIED_PREFIX
    )
    assert (
        tomas_verifier.NOTE_GUARD_TOKENS
        is shared.NOTE_STALE_MARKER_GUARD_TOKENS
    )
    assert tomas_verifier.NOTE_NO_MARKER_TOKEN == shared.NOTE_NO_MARKER_TOKEN


# ---------------------------------------------------------------------------
# T13 - Noa verifier re-exports shared constants verbatim.
# ---------------------------------------------------------------------------
def test_t13_noa_verifier_aliases_shared_constants():
    """Same invariant for Noa's Tag-66 verifier."""
    assert noa_verifier.VERDICT_INTACT == shared.WATCH_DAY_VERDICT_INTACT
    assert noa_verifier.VERDICT_DRIFT == shared.WATCH_DAY_VERDICT_DRIFT
    assert noa_verifier.VERDICT_DEFECT == shared.WATCH_DAY_VERDICT_DEFECT
    assert noa_verifier.STAGE_GREEN == shared.STAGE_STATUS_GREEN
    assert noa_verifier.STAGE_YELLOW == shared.STAGE_STATUS_YELLOW
    assert noa_verifier.STAGE_RED == shared.STAGE_STATUS_RED
    assert noa_verifier.VALID_STAGE_STATUSES is shared.VALID_STAGE_STATUSES

    assert noa_verifier.CANONICAL_EVENT == shared.CANONICAL_EVENT
    assert noa_verifier.CANONICAL_WORKFLOW == shared.CANONICAL_WORKFLOW
    assert noa_verifier.CANONICAL_REF == shared.CANONICAL_REF

    assert (
        noa_verifier.AUDIT_MARKER_REQUIRED_KEYS
        is shared.WATCH_DAY_ENVELOPE_REQUIRED_KEYS
    )
    assert noa_verifier.TAG62_BASE_KEYS is shared.WATCH_DAY_BASE_KEYS_TAG62
    assert noa_verifier.AUDIT_ONLY_KEYS is shared.WATCH_DAY_AUDIT_ONLY_KEYS

    assert (
        noa_verifier.AUDIT_MARKER_TAG_PATTERN
        is shared.AUDIT_MARKER_TAG_PATTERN
    )
    assert (
        noa_verifier.DISPATCHED_AT_PATTERN is shared.DISPATCHED_AT_PATTERN
    )
    assert noa_verifier.UUID_PATTERN is shared.UUID_PATTERN

    # MarkerClass is now an alias of MarkerSourceClass.
    assert noa_verifier.MarkerClass is shared.MarkerSourceClass
    assert (
        noa_verifier.AUDIT_MARKER_CATALOG is shared.MARKER_SOURCE_CLASSES
    )
    assert (
        noa_verifier.CATALOG_BY_SOURCE
        is shared.MARKER_SOURCE_CLASSES_BY_SOURCE
    )


# ---------------------------------------------------------------------------
# T14 - both verifiers + shared module share THE SAME pattern objects
#       (single-source-of-truth invariant).
# ---------------------------------------------------------------------------
def test_t14_cross_verifier_pattern_identity():
    """Both verifiers must reference the SAME compiled regex objects
    so that any future amendment to the canonical patterns lands
    once in the shared module and propagates everywhere. Object
    identity (``is``) is the discriminator -- two re.compile()
    calls produce equal-but-distinct objects."""
    # AUDIT_MARKER_TAG_PATTERN: only Noa exposes this name.
    assert (
        noa_verifier.AUDIT_MARKER_TAG_PATTERN
        is shared.AUDIT_MARKER_TAG_PATTERN
    )
    # SLUG_PATTERN: only Tomás exposes (as _SLUG_RE).
    assert tomas_verifier._SLUG_RE is shared.SLUG_PATTERN
    # RFC3339_TIMESTAMP_PATTERN: only Tomás exposes (as _TS_RE).
    assert tomas_verifier._TS_RE is shared.RFC3339_TIMESTAMP_PATTERN
    # UUID_PATTERN: only Noa exposes.
    assert noa_verifier.UUID_PATTERN is shared.UUID_PATTERN
    # DISPATCHED_AT_PATTERN: only Noa exposes.
    assert (
        noa_verifier.DISPATCHED_AT_PATTERN is shared.DISPATCHED_AT_PATTERN
    )


# ---------------------------------------------------------------------------
# T15 - schema-version metadata is a positive integer.
# ---------------------------------------------------------------------------
def test_t15_schema_version_metadata():
    assert isinstance(shared.SHARED_CONSTANTS_SCHEMA_VERSION, int)
    assert shared.SHARED_CONSTANTS_SCHEMA_VERSION >= 1
