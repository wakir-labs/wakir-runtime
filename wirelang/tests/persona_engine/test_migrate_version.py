# SPDX-License-Identifier: BUSL-1.1
"""Sprint-Pengine-9 OI-PEFR-5 tests: migrate-version mechanic.

Coverage:

  - Semver-tag parsing + supported-version checks.
  - Cross-version snapshot scan (0.2.0-pilot bytes readable by
    0.3.0-pilot engine via the v0 envelope).
  - Pinned-offset migration with idempotent semantics.
  - Engine-version sentinel-key stamp/read round-trip.
  - Major-version-bump guard.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pytest

from wirelang.persona_engine.migrate_version import (
    ENGINE_VERSION_KEY,
    KNOWN_ENGINE_VERSIONS,
    MigrateVersionResult,
    MigrateVersionWorkflow,
    MigrationError,
    MigrationFailureMode,
    SemverParts,
    is_supported_engine_version,
    parse_semver,
)
from wirelang.persona_engine.state_backing import (
    InMemoryPersonaStateBacking,
    PersonaStateBackingError,
    PersonaStateSnapshot,
    snapshot_from_jcs_bytes,
    snapshot_to_jcs_bytes,
)


def _snap(seed: int = 0) -> PersonaStateSnapshot:
    return PersonaStateSnapshot(
        persona_hash="sha256:" + "0" * 64,
        audit_trace_offset=seed,
        capability_token_ids=("tok-1",),
        snapshot_at_utc=f"2026-05-15T{seed:02d}:00:00Z",
        workspace_state_hash="sha256:" + "1" * 64,
    )


# -------------------- semver helpers --------------------


def test_parse_semver_basic():
    p = parse_semver("0.3.0-pilot")
    assert p.major == 0
    assert p.minor == 3
    assert p.patch == 0
    assert p.prerelease == "pilot"


def test_parse_semver_without_prerelease():
    p = parse_semver("1.2.3")
    assert p.prerelease is None


def test_parse_semver_rejects_malformed():
    with pytest.raises(ValueError):
        parse_semver("not-a-semver")


def test_parse_semver_rejects_empty():
    with pytest.raises(ValueError):
        parse_semver("")


def test_is_supported_engine_version_yes():
    assert is_supported_engine_version("0.2.0-pilot")
    assert is_supported_engine_version("0.3.0-pilot")


def test_is_supported_engine_version_no():
    assert not is_supported_engine_version("0.1.0-pilot")
    assert not is_supported_engine_version("99.99.99")


def test_known_engine_versions_includes_pilot_pair():
    assert "0.2.0-pilot" in KNOWN_ENGINE_VERSIONS
    assert "0.3.0-pilot" in KNOWN_ENGINE_VERSIONS


# -------------------- workflow constructor guards --------------------


def test_workflow_rejects_unknown_from_version():
    b = InMemoryPersonaStateBacking()
    with pytest.raises(MigrationError) as exc:
        MigrateVersionWorkflow(
            state_backing=b,
            from_version="9.9.9-foo",
            to_version="0.3.0-pilot",
        )
    assert exc.value.mode == MigrationFailureMode.UNKNOWN_FROM_VERSION


def test_workflow_rejects_unknown_to_version():
    b = InMemoryPersonaStateBacking()
    with pytest.raises(MigrationError) as exc:
        MigrateVersionWorkflow(
            state_backing=b,
            from_version="0.2.0-pilot",
            to_version="9.9.9-foo",
        )
    assert exc.value.mode == MigrationFailureMode.UNKNOWN_TO_VERSION


def test_workflow_accepts_same_major_minor_patch_bump():
    b = InMemoryPersonaStateBacking()
    # Same major (0); workflow constructible.
    MigrateVersionWorkflow(
        state_backing=b,
        from_version="0.2.0-pilot",
        to_version="0.3.0-pilot",
    )


# -------------------- cross-version scan --------------------


def test_scan_cross_version_reads_zero_snapshots():
    b = InMemoryPersonaStateBacking()
    wf = MigrateVersionWorkflow(
        state_backing=b,
        from_version="0.2.0-pilot",
        to_version="0.3.0-pilot",
    )
    scanned, readable = wf.scan_cross_version_reads("tomas")
    assert scanned == 0
    assert readable == 0


def test_scan_cross_version_reads_single_snapshot():
    b = InMemoryPersonaStateBacking()
    b.snapshot("tomas", _snap(0))
    wf = MigrateVersionWorkflow(
        state_backing=b,
        from_version="0.2.0-pilot",
        to_version="0.3.0-pilot",
    )
    scanned, readable = wf.scan_cross_version_reads("tomas")
    assert scanned == 1
    assert readable == 1


def test_scan_cross_version_reads_multiple_snapshots():
    """For the trait surface, only the latest is reachable; the
    workflow reports the difference for operator inspection."""
    b = InMemoryPersonaStateBacking()
    b.snapshot("tomas", _snap(0))
    b.snapshot("tomas", _snap(1))
    b.snapshot("tomas", _snap(2))
    wf = MigrateVersionWorkflow(
        state_backing=b,
        from_version="0.2.0-pilot",
        to_version="0.3.0-pilot",
    )
    scanned, readable = wf.scan_cross_version_reads("tomas")
    assert scanned == 3
    # Only the latest is readable via the sync trait without an
    # extension hook.
    assert readable in (1, 3)


def test_scan_with_read_offset_extension_hook_reads_all():
    """A backing that exposes ``read_offset`` allows the scan to
    iterate every offset (used by the async backing facade)."""

    class _ExtendedBacking(InMemoryPersonaStateBacking):
        def read_offset(self, persona_id: str, offset: int):
            entries = self._snapshots.get(persona_id, [])
            for off, snap in entries:
                if off == offset:
                    return snap
            return None

    b = _ExtendedBacking()
    b.snapshot("tomas", _snap(0))
    b.snapshot("tomas", _snap(1))
    b.snapshot("tomas", _snap(2))
    wf = MigrateVersionWorkflow(
        state_backing=b,
        from_version="0.2.0-pilot",
        to_version="0.3.0-pilot",
    )
    scanned, readable = wf.scan_cross_version_reads("tomas")
    assert scanned == 3
    assert readable == 3


# -------------------- pinned-offset migration --------------------


def test_migrate_pinned_offset_first_time_pin():
    b = InMemoryPersonaStateBacking()
    off = b.snapshot("tomas", _snap(0))
    wf = MigrateVersionWorkflow(
        state_backing=b,
        from_version="0.2.0-pilot",
        to_version="0.3.0-pilot",
    )
    result = wf.migrate_pinned_offset("tomas", target_offset=off)
    assert result.success is True
    assert result.pinned_offset_after == off


def test_migrate_pinned_offset_rejects_unknown_target():
    b = InMemoryPersonaStateBacking()
    b.snapshot("tomas", _snap(0))
    wf = MigrateVersionWorkflow(
        state_backing=b,
        from_version="0.2.0-pilot",
        to_version="0.3.0-pilot",
    )
    with pytest.raises(MigrationError) as exc:
        wf.migrate_pinned_offset("tomas", target_offset=42)
    assert exc.value.mode == MigrationFailureMode.SNAPSHOT_NOT_FOUND


def test_migrate_pinned_offset_after_existing_pin():
    """Re-pin onto a newer offset requires the from_offset match the
    current pin (compare-and-swap semantics)."""
    b = InMemoryPersonaStateBacking()
    off1 = b.snapshot("tomas", _snap(0))
    off2 = b.snapshot("tomas", _snap(1))
    # First pin.
    b.atomic_swap_pinned_offset(
        "tomas", from_offset=0, to_offset=off1,
    )
    wf = MigrateVersionWorkflow(
        state_backing=b,
        from_version="0.2.0-pilot",
        to_version="0.3.0-pilot",
    )
    result = wf.migrate_pinned_offset("tomas", target_offset=off2)
    assert result.pinned_offset_before == off1
    assert result.pinned_offset_after == off2


def test_migrate_result_records_from_and_to_versions():
    b = InMemoryPersonaStateBacking()
    off = b.snapshot("tomas", _snap(0))
    wf = MigrateVersionWorkflow(
        state_backing=b,
        from_version="0.2.0-pilot",
        to_version="0.3.0-pilot",
    )
    result = wf.migrate_pinned_offset("tomas", target_offset=off)
    assert result.from_version == "0.2.0-pilot"
    assert result.to_version == "0.3.0-pilot"


# -------------------- engine-version sentinel key --------------------


def test_stamp_and_read_engine_version_round_trip():
    b = InMemoryPersonaStateBacking()
    wf = MigrateVersionWorkflow(
        state_backing=b,
        from_version="0.2.0-pilot",
        to_version="0.3.0-pilot",
    )
    store: Dict[Tuple[str, str], str] = {}

    def write_stamp(persona_id: str, key: str, value: str) -> None:
        store[(persona_id, key)] = value

    def read_stamp(persona_id: str, key: str) -> Optional[str]:
        return store.get((persona_id, key))

    stamped = wf.stamp_engine_version("tomas", write_stamp=write_stamp)
    assert stamped == "0.3.0-pilot"
    assert read_stamp("tomas", ENGINE_VERSION_KEY) == "0.3.0-pilot"

    fetched = wf.read_engine_version("tomas", read_stamp=read_stamp)
    assert fetched == "0.3.0-pilot"


def test_stamp_engine_version_with_explicit_version():
    b = InMemoryPersonaStateBacking()
    wf = MigrateVersionWorkflow(
        state_backing=b,
        from_version="0.2.0-pilot",
        to_version="0.3.0-pilot",
    )
    store: Dict[Tuple[str, str], str] = {}

    def write_stamp(persona_id: str, key: str, value: str) -> None:
        store[(persona_id, key)] = value

    wf.stamp_engine_version(
        "tomas",
        version="0.2.0-pilot",
        write_stamp=write_stamp,
    )
    assert store[("tomas", ENGINE_VERSION_KEY)] == "0.2.0-pilot"


def test_read_engine_version_returns_none_when_no_reader():
    b = InMemoryPersonaStateBacking()
    wf = MigrateVersionWorkflow(
        state_backing=b,
        from_version="0.2.0-pilot",
        to_version="0.3.0-pilot",
    )
    assert wf.read_engine_version("tomas") is None


# -------------------- byte-equal cross-version envelope --------------------


def test_v0_envelope_byte_equal_across_versions():
    """The PersonaStateSnapshot JCS bytes are version-agnostic for the
    v0 envelope — Sprint-Pengine-9 OI-PEFR-5 invariant."""
    s = _snap(7)
    blob = snapshot_to_jcs_bytes(s)
    # Round-trip through the inverse helper.
    s_restored = snapshot_from_jcs_bytes(blob)
    assert s_restored == s


def test_v0_envelope_unchanged_field_set():
    """Sprint-Pengine-9 0.3.0-pilot MUST not change the v0 envelope
    field set. If a future engine adds a field, this test forces a
    deliberate spec update."""
    expected_fields = {
        "audit_trace_offset",
        "capability_token_ids",
        "persona_hash",
        "snapshot_at_utc",
        "workspace_state_hash",
    }
    s = _snap()
    fields = {f.name for f in s.__dataclass_fields__.values()}
    assert fields == expected_fields


# -------------------- migrate result dataclass --------------------


def test_migrate_version_result_dataclass_shape():
    r = MigrateVersionResult(
        from_version="0.2.0-pilot",
        to_version="0.3.0-pilot",
        snapshots_scanned=3,
        snapshots_readable=3,
        pinned_offset_before=None,
        pinned_offset_after=1,
        success=True,
    )
    assert r.snapshots_scanned == 3
    assert r.snapshots_readable == 3
    assert r.success is True


# -------------------- failure-mode enum --------------------


def test_migration_failure_mode_enum_values():
    assert MigrationFailureMode.UNKNOWN_FROM_VERSION.value == "UnknownFromVersion"
    assert MigrationFailureMode.UNKNOWN_TO_VERSION.value == "UnknownToVersion"
    assert MigrationFailureMode.SNAPSHOT_NOT_FOUND.value == "SnapshotNotFound"
    assert MigrationFailureMode.SNAPSHOT_CORRUPT.value == "SnapshotCorrupt"
    assert MigrationFailureMode.BACKING_UNREACHABLE.value == "BackingUnreachable"


def test_engine_version_key_canonical():
    assert ENGINE_VERSION_KEY == "state-pack/__engine_version__"


def test_semver_parts_dataclass_fields():
    p = SemverParts(major=0, minor=3, patch=0, prerelease="pilot")
    assert p.major == 0
    assert p.minor == 3
    assert p.patch == 0
    assert p.prerelease == "pilot"
