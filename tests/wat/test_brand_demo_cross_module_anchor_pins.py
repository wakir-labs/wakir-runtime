# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Brand-Demo-Verifier Cross-Module byte-coordinated anchor pins.

Sprint-4 Tag-4 — Option A (Brand-Demo-Verifier-Cross-Module-Test).

This module pins the byte-level Cross-Module contracts that a
hypothetical Brand-Demo-Snapshot emitter (as specified by
``docs/wat-brand-asset-snapshot-spec.md``) must rely on across the
three layers it spans:

1. **WAT-Identity-Layer** — ``wat.verify.manifest_v2`` verifier
   (both ``verify_real_manifest_file`` and ``verify_manifest_v2_file``).
2. **Manifest-v1+v2-Schema-File-Surface** —
   ``wirelang/schemas/wakir-wat-manifest-v1.json`` (real wire-form)
   and ``wirelang/schemas/wat-manifest-v2.json`` (spec-form).
3. **Real-OTS-Receipts** — the TV-3 T17 fixture under
   ``tests/fixtures/wat-tv3-real/2026-05-26T17/`` carries a real
   ``root.bin`` (32 raw bytes) plus ``root.bin.ots`` (real OTS
   receipt; OpenTimestamps magic-header pinned).

Existing tests cover each layer in isolation
(``test_tv3_real_manifest_live_run.py`` for verifier+real manifest,
``test_manifest_v2_schema_smoke.py`` for v2 schema, etc). This module
adds Cross-Module **byte-coordination** — i.e. assertions that the
*same* bytes flow correctly between layers, and that the *divergence*
between v1 wire-form and v2 spec-form is preserved (schema-rejection
on cross-feed is intentional, not a bug).

Brand-Demo-Snapshot context:
``docs/wat-brand-asset-snapshot-spec.md`` §3.5 specifies the JSON
snapshot fields ``hour_slot``, ``merkle_root``, ``prev_hour_root``,
``event_count``, plus per-calendar Bitcoin attestations. Those
fields must be byte-pluckable from the manifest, byte-identical to
the on-disk side-files (``root.bin``), and byte-consistent with the
v1 schema-file pattern constraints. The Cross-Module tests below
pin exactly that.

All tests are hermetic: tmp-path-only when mutation is needed,
direct fixture reads otherwise. No network, no subprocess, no OTS
CLI dependency, no Bitcoin RPC.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from wat.verify.manifest_v2 import (
    DEFAULT_REAL_SCHEMA_PATH,
    DEFAULT_SCHEMA_PATH,
    verify_manifest_v2_file,
    verify_real_manifest_file,
)

# ---------------------------------------------------------------------------
# Fixture roots — repo-anchored so the tests work both in-tree and in
# a dedicated worktree (ADR-0049 Pre-Box-Worktree-Pattern).
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TV3_T17_DIR = _REPO_ROOT / "tests" / "fixtures" / "wat-tv3-real" / "2026-05-26T17"
_V2_SAMPLE_MULTI_CAP = (
    _REPO_ROOT
    / "tests"
    / "fixtures"
    / "wat-manifest-v2"
    / "sample-multi-cap-hour.json"
)

# Brand-Snapshot anchor fields per docs/wat-brand-asset-snapshot-spec.md
# §3.5. The set is pinned here so a future snapshot-emit implementation
# can import and consume it; for now we assert the fields are
# byte-pluckable from the TV-3 real-manifest fixture.
_BRAND_SNAPSHOT_ANCHOR_FIELDS = (
    "hour_slot",
    "merkle_root",
    "prev_hour_root",
    "event_count",
)

# v1 schema-file pattern constants — pinned here so a regression in the
# schema-file's regex is caught by this test module (not just by the
# verifier's runtime jsonschema-validation, which only fires on schema
# violations rather than on schema-pattern drift).
_HOUR_SLOT_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}$")
_HEX64_PATTERN = re.compile(r"^[0-9a-f]{64}$")

# OpenTimestamps magic header (16 bytes). Per
# wat/verify/manifest_v2.py:_OTS_MAGIC_HEADER and pinned in the
# OpenTimestamps reference spec.
_OTS_MAGIC_HEADER = b"\x00OpenTimestamps\x00"


# ---------------------------------------------------------------------------
# Test 1 — TV-3 merkle_root byte-identity across manifest.json + root.bin
# ---------------------------------------------------------------------------


def test_tv3_merkle_root_byte_identity_across_manifest_and_root_bin() -> None:
    """The merkle_root hex string in manifest.json equals the raw bytes
    in root.bin when hex-encoded.

    Cross-Module contract: a Brand-Snapshot emitter that reads
    ``manifest.merkle_root`` and the verifier that reads ``root.bin``
    must agree byte-for-byte. If this breaks, the chain of trust
    between the manifest and the OTS-stamped raw bytes silently
    diverges.
    """
    manifest = json.loads((_TV3_T17_DIR / "manifest.json").read_text())
    root_bin = (_TV3_T17_DIR / "root.bin").read_bytes()

    assert "merkle_root" in manifest, "TV-3 fixture missing merkle_root"
    assert len(root_bin) == 32, (
        f"TV-3 root.bin must be exactly 32 bytes; got {len(root_bin)}"
    )
    assert manifest["merkle_root"] == root_bin.hex(), (
        "Cross-Module drift: manifest.merkle_root != hex(root.bin). "
        f"manifest={manifest['merkle_root']!r}, root.bin.hex()={root_bin.hex()!r}"
    )
    # And the regex-pattern constraint from the v1 schema must hold.
    assert _HEX64_PATTERN.match(manifest["merkle_root"]), (
        "merkle_root must match v1-schema hex64 pattern"
    )


# ---------------------------------------------------------------------------
# Test 2 — TV-3 real-manifest passes via use_schema_file (v1 schema-file)
# ---------------------------------------------------------------------------


def test_tv3_real_manifest_passes_v1_schema_via_use_schema_file() -> None:
    """``verify_real_manifest_file(..., use_schema_file=True)`` against
    TV-3 T17 must pass end-to-end: v1 JSON-Schema validation, in-code
    field-validation, Merkle rebuild, AND OTS-anchor side-file check.

    Cross-Module contract: the v1 schema-file is the *external*
    verifier-implementer contract; if a Brand-Snapshot consumer ever
    re-implements the verifier in Go / Rust / Node, this schema-file
    is what they validate against. Drift between the schema-file and
    the in-code field-validator must be caught immediately by running
    both paths in lockstep, which is exactly what ``use_schema_file``
    enables.
    """
    pytest.importorskip(
        "jsonschema",
        reason="jsonschema package required for the use_schema_file path",
    )

    result = verify_real_manifest_file(
        _TV3_T17_DIR / "manifest.json",
        check_ots_anchor=True,
        use_schema_file=True,
    )

    assert result.ok, (
        f"TV-3 real-manifest must pass full verifier pipeline; "
        f"got fields_ok={result.fields_ok}, integrity_ok={result.integrity_ok}, "
        f"ots.ok={result.ots_anchor.ok}, reason={result.failure_reason!r}"
    )
    assert result.fields_ok is True
    assert result.integrity_ok is True
    assert result.ots_anchor.ok is True
    assert result.version == "wakir-wat-manifest/v1"


# ---------------------------------------------------------------------------
# Test 3 — TV-3 wire-form fails v2-spec schema (intentional divergence)
# ---------------------------------------------------------------------------


def test_tv3_real_manifest_fails_v2_schema_due_to_wire_form_divergence() -> None:
    """Feeding the TV-3 wire-form v1 manifest through the v2-spec
    verifier (``verify_manifest_v2_file``, which validates against
    ``wat-manifest-v2.json``) must FAIL.

    Cross-Module contract: the v1 wire-form and the v2 spec-form are
    intentionally separate schemas (the v1 schema-file header
    explicitly calls this out: "leaves as objects vs hex strings"
    cannot be unified without lossy coercion). A future Brand-Snapshot
    emitter that mis-routes v1 manifests through the v2 verifier
    would silently produce wrong attestations; this test pins the
    rejection.

    Specifically, the v2 schema's ``additionalProperties: false`` at
    the root rejects v1's ``prev_hour_root`` extension; the v1 wire-
    form's ``version`` enum (``wakir-wat-manifest/v1``) also doesn't
    match the v2 schema's ``wat-manifest/{1.0,2.0}`` enum. Either
    rejection is sufficient — we assert that the verdict is failure
    AND the failure_reason names the schema-rejection layer.
    """
    pytest.importorskip(
        "jsonschema",
        reason="jsonschema package required to surface schema violations",
    )

    result = verify_manifest_v2_file(_TV3_T17_DIR / "manifest.json")

    assert result.schema_ok is False, (
        "v1 wire-form must NOT validate against v2 spec-schema"
    )
    assert result.failure_reason.startswith("schema:"), (
        "rejection must be at the schema layer, "
        f"got {result.failure_reason!r}"
    )


# ---------------------------------------------------------------------------
# Test 4 — v2 sample-multi-cap-hour passes v2 schema + integrity
# ---------------------------------------------------------------------------


def test_v2_sample_multi_cap_hour_passes_v2_schema_and_integrity() -> None:
    """The committed ``sample-multi-cap-hour.json`` v2-fixture passes
    full v2-spec verifier pipeline including the strict multi-cap-root
    Merkle recompute (OQ-1 ratified 2026-05-07).

    Cross-Module contract: the v2-spec-shaped fixture is the
    forward-compat contract for the future v2 producer
    (``wat/aggregator.py`` v2 branch). Brand-Snapshot consumers that
    plan for v1.1 schema-bump (``multi_cap_events_count`` in summary,
    per ``docs/wat-brand-asset-snapshot-spec.md`` §6.4) must rely on
    the v2-verifier's multi-cap-root recompute being byte-stable.
    This test pins ``multi_cap_root_status == "verified"`` as the
    success marker that a future snapshot-emitter can consume.
    """
    pytest.importorskip(
        "jsonschema",
        reason="jsonschema package required for v2-schema validation",
    )

    result = verify_manifest_v2_file(_V2_SAMPLE_MULTI_CAP)

    assert result.ok, (
        f"v2 sample-multi-cap-hour must pass full verifier pipeline; "
        f"got schema_ok={result.schema_ok}, integrity_ok={result.integrity_ok}, "
        f"mcr={result.multi_cap_root_status!r}, "
        f"reason={result.failure_reason!r}"
    )
    assert result.schema_ok is True
    assert result.integrity_ok is True
    assert result.version == "wat-manifest/2.0"
    assert result.multi_cap_root_status == "verified", (
        "multi_cap_root_status must be 'verified' (strict mode); "
        f"got {result.multi_cap_root_status!r}"
    )


# ---------------------------------------------------------------------------
# Test 5 — Brand-Snapshot anchor fields Cross-Module byte-consistency
# ---------------------------------------------------------------------------


def test_brand_snapshot_anchor_fields_cross_module_byte_consistency() -> None:
    """The four Brand-Snapshot anchor fields specified in
    ``docs/wat-brand-asset-snapshot-spec.md`` §3.5 are byte-pluckable
    from the TV-3 real manifest, satisfy the v1 schema-file pattern
    constraints, and are byte-consistent with the on-disk
    ``root.bin``.

    Cross-Module contract: this is the single concrete test that a
    hypothetical Brand-Snapshot-emit pipeline (``scripts/wat-brand-
    snapshot-emit.sh`` or ``wat/cmd/brand_snapshot.py``, per spec §4)
    consumes the same bytes that the verifier sees and the schema
    constrains. If any of these three layers drift, this test fires
    BEFORE a Brand-Demo-Snapshot can be emitted with mismatched
    bytes.
    """
    manifest = json.loads((_TV3_T17_DIR / "manifest.json").read_text())
    root_bin = (_TV3_T17_DIR / "root.bin").read_bytes()

    # All four anchor fields must be present (prev_hour_root may be
    # JSON null for cold-start hours; that is valid per spec §3.5).
    for field in _BRAND_SNAPSHOT_ANCHOR_FIELDS:
        assert field in manifest, (
            f"Brand-Snapshot anchor field {field!r} missing from "
            f"TV-3 manifest (spec §3.5 requires all four)"
        )

    # hour_slot must match the v1 schema pattern.
    assert _HOUR_SLOT_PATTERN.match(manifest["hour_slot"]), (
        f"hour_slot {manifest['hour_slot']!r} violates v1-schema "
        f"YYYY-MM-DDTHH pattern"
    )

    # merkle_root must match the v1 schema hex64 pattern AND be
    # byte-identical to root.bin.
    assert _HEX64_PATTERN.match(manifest["merkle_root"]), (
        f"merkle_root {manifest['merkle_root']!r} violates v1-schema "
        f"hex64 pattern"
    )
    assert bytes.fromhex(manifest["merkle_root"]) == root_bin, (
        "Cross-Module drift: bytes.fromhex(manifest.merkle_root) != "
        "root.bin contents"
    )

    # prev_hour_root: either null (cold-start, valid per spec §3.5)
    # or hex64. TV-3 T17 is the bootstrap hour, so null is expected;
    # we pin BOTH branches valid.
    prev = manifest["prev_hour_root"]
    assert prev is None or (
        isinstance(prev, str) and _HEX64_PATTERN.match(prev)
    ), (
        f"prev_hour_root {prev!r} must be null or v1-schema hex64; "
        f"spec §3.5 requires frontend to handle both"
    )

    # event_count must be non-negative integer (v1 schema:
    # type=integer, minimum=0) and equal len(events) / len(leaves).
    assert isinstance(manifest["event_count"], int)
    assert manifest["event_count"] >= 0
    assert manifest["event_count"] == len(manifest["events"]) == len(manifest["leaves"]), (
        f"event_count {manifest['event_count']} must equal "
        f"len(events)={len(manifest['events'])} and "
        f"len(leaves)={len(manifest['leaves'])}"
    )

    # The v1 schema-file MUST exist at DEFAULT_REAL_SCHEMA_PATH so a
    # Brand-Snapshot consumer in another language can re-validate.
    assert DEFAULT_REAL_SCHEMA_PATH.exists(), (
        "v1 schema-file missing — Brand-Snapshot external-verifier "
        "contract broken"
    )
    # And the v2 schema-file MUST exist for v1.1-forward-compat
    # planning (spec §6.4).
    assert DEFAULT_SCHEMA_PATH.exists(), (
        "v2 schema-file missing — Brand-Snapshot v1.1 forward-compat "
        "contract broken"
    )


# ---------------------------------------------------------------------------
# Test 6 — full verifier pipeline + real OTS receipt side-files byte-pinned
# ---------------------------------------------------------------------------


def test_tv3_full_verifier_pipeline_real_ots_receipt_side_files_byte_pinned(
    tmp_path: Path,
) -> None:
    """Run the full verifier pipeline (schema-file + in-code fields +
    integrity rebuild + OTS-anchor side-files) against a hermetic copy
    of TV-3 T17 and byte-pin every OtsAnchorCheck discriminator.

    Cross-Module contract: this is the end-to-end pin that a
    Brand-Snapshot-emit pipeline (spec §4) running on a per-hour
    archive directory will rely on. We copy the fixture into tmp_path
    first so any future modification of the live fixture doesn't
    accidentally pass through a verifier-side mutation (defensive),
    and we assert on the OTS receipt's magic-header bytes directly to
    pin the cross-layer contract between the on-disk file and the
    verifier's ``ots_magic_ok`` flag.
    """
    pytest.importorskip(
        "jsonschema",
        reason="jsonschema package required for the use_schema_file path",
    )

    # Copy TV-3 T17 fixture into hermetic tmp_path.
    hour_dir = tmp_path / "2026-05-26T17"
    hour_dir.mkdir()
    for fname in ("manifest.json", "root.bin", "root.bin.ots"):
        shutil.copy2(_TV3_T17_DIR / fname, hour_dir / fname)

    # Independent byte-level pin of the OTS magic header BEFORE the
    # verifier ever touches the file. This is the Cross-Module ground-
    # truth: if the magic-header bytes shift, the verifier's
    # ots_magic_ok flag must shift in lockstep.
    ots_bytes = (hour_dir / "root.bin.ots").read_bytes()
    assert len(ots_bytes) >= len(_OTS_MAGIC_HEADER), (
        "TV-3 OTS receipt too short to contain magic header"
    )
    assert ots_bytes[: len(_OTS_MAGIC_HEADER)] == _OTS_MAGIC_HEADER, (
        "TV-3 OTS receipt magic-header bytes drifted from "
        "OpenTimestamps reference"
    )

    # And the root.bin bytes equal the manifest merkle_root, exactly.
    manifest = json.loads((hour_dir / "manifest.json").read_text())
    root_bin = (hour_dir / "root.bin").read_bytes()
    assert root_bin.hex() == manifest["merkle_root"]

    # Now run the full verifier pipeline and assert every relevant
    # OtsAnchorCheck discriminator field.
    result = verify_real_manifest_file(
        hour_dir / "manifest.json",
        check_ots_anchor=True,
        use_schema_file=True,
    )

    assert result.ok, (
        f"Full verifier pipeline must pass on hermetic TV-3 copy; "
        f"reason={result.failure_reason!r}"
    )
    assert result.fields_ok is True
    assert result.integrity_ok is True

    ots = result.ots_anchor
    assert ots.checked is True
    assert ots.root_bin_present is True
    assert ots.root_bin_matches_manifest is True
    assert ots.ots_present is True
    assert ots.ots_magic_ok is True
    assert ots.failure_reason == ""
    assert ots.ok is True
