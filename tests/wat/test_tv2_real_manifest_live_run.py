# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""TV-2 real-manifest live-run validation.

Sprint-3 Tag-2 substance: the four hour-receipts produced by the
TV-2 multi-hour audit-trail run on 2026-05-06 are committed under
``tests/fixtures/wat-tv2-real/`` and are exercised here as the
real-world-anchored reference cohort for the v1 schema-file +
``verify_real_manifest_file`` pipeline.

What this module checks
-----------------------

Per real on-disk hour-receipt (4 of them, 2026-05-27T00..T03):

1. ``verify_real_manifest_file(use_schema_file=True,
   check_ots_anchor=True)`` returns a fully-green
   :class:`RealManifestResult` (``fields_ok`` + ``integrity_ok`` +
   ``ots_anchor.ok`` all True; ``failure_reason`` empty).

2. The manifest is accepted by the formal v1 JSON-Schema file
   under direct ``jsonschema``-driver validation.

3. ``root.bin`` is exactly 32 bytes equal to ``bytes.fromhex
   (manifest['merkle_root'])`` — i.e. the file the OpenTimestamps
   anchor signs is the same bytes as the manifest's merkle_root
   field.

Cross-hour:

4. ``prev_hour_root`` chain is contiguous (T01.prev_hour_root ==
   T00.merkle_root etc.). T00 has ``prev_hour_root: null`` (run
   genesis); T01..T03 each chain back.

Negative-path (against mutated copies of the T00 fixture):

5. Tampered ``merkle_root`` → ``integrity_ok`` False.
6. Tampered ``version`` → ``fields_ok`` False (schema-side reject).

Why this is hard substance for Phase-1b→1c
------------------------------------------

The schema-file plus ``use_schema_file=True`` plumbing has had
synthetic-vector coverage since Sprint-2 Tag-6 (smoke tests) and
Sprint-3 Tag-1 (cross-tool-parity with ajv). What is missing
until Tag-2 is the assertion that the same plumbing accepts real
on-disk manifests produced by the *production aggregator* against
*real Bitcoin-anchored* root.bin.ots side-files. This is the
acceptance evidence Phase-1b→1c needs: the verifier pipeline is
exercised against the artefact the Brand-Demo TV-2 card publishes,
not against a hand-authored synthetic.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from wat.verify.manifest_v2 import (
    DEFAULT_REAL_SCHEMA_PATH,
    verify_real_manifest_file,
)

# ---------------------------------------------------------------------------
# Fixture roots
# ---------------------------------------------------------------------------

#: Repository-relative path to the TV-2 real-manifest fixture cohort
#: (committed to the repo as Sprint-3 Tag-2 Brand-Demo-anchor source).
TV2_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "wat-tv2-real"

#: The four hour-slots that comprise the TV-2 run, in chronological
#: order. Each carries manifest.json + root.bin + root.bin.ots.
TV2_HOUR_SLOTS: tuple[str, ...] = (
    "2026-05-27T00",
    "2026-05-27T01",
    "2026-05-27T02",
    "2026-05-27T03",
)


def _hour_dir(slot: str) -> Path:
    return TV2_FIXTURE_ROOT / slot


def _manifest_path(slot: str) -> Path:
    return _hour_dir(slot) / "manifest.json"


def _load_manifest(slot: str) -> dict:
    with _manifest_path(slot).open("r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Sanity: fixture cohort is on-disk
# ---------------------------------------------------------------------------


def test_tv2_fixture_cohort_present():
    """All four hour-receipt directories carry the three side-files."""
    assert TV2_FIXTURE_ROOT.is_dir(), (
        f"TV-2 fixture root missing: {TV2_FIXTURE_ROOT}"
    )
    for slot in TV2_HOUR_SLOTS:
        d = _hour_dir(slot)
        assert d.is_dir(), f"hour-slot dir missing: {d}"
        for sidecar in ("manifest.json", "root.bin", "root.bin.ots"):
            p = d / sidecar
            assert p.is_file(), f"sidecar missing: {p}"
        # root.bin is exactly 32 bytes.
        assert (d / "root.bin").stat().st_size == 32, (
            f"root.bin must be 32 bytes for {slot}"
        )


# ---------------------------------------------------------------------------
# Per-hour live-run via verify_real_manifest_file
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slot", TV2_HOUR_SLOTS)
def test_tv2_hour_verify_real_manifest_file_green(slot):
    """Each TV-2 hour passes the full real-manifest verifier path.

    With ``use_schema_file=True`` the schema-file is run; with
    ``check_ots_anchor=True`` the side-files (root.bin +
    root.bin.ots) are smoke-checked. All three result fields
    (fields_ok, integrity_ok, ots_anchor.ok) must be True for a
    Bitcoin-anchored production hour-receipt. ``failure_reason``
    must be empty.
    """
    result = verify_real_manifest_file(
        _manifest_path(slot),
        check_ots_anchor=True,
        use_schema_file=True,
    )
    assert result.ok, (
        f"{slot} not ok: fields={result.fields_ok} "
        f"integrity={result.integrity_ok} "
        f"ots={result.ots_anchor.ok} reason={result.failure_reason!r}"
    )
    assert result.fields_ok, f"{slot} fields_ok False"
    assert result.integrity_ok, f"{slot} integrity_ok False"
    assert result.ots_anchor.ok, f"{slot} ots_anchor.ok False"
    assert result.failure_reason == "", (
        f"{slot} failure_reason non-empty: {result.failure_reason!r}"
    )
    assert result.version == "wakir-wat-manifest/v1"


# ---------------------------------------------------------------------------
# root.bin matches merkle_root
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slot", TV2_HOUR_SLOTS)
def test_tv2_hour_root_bin_matches_merkle_root(slot):
    """root.bin (the OTS-stamped 32 bytes) equals bytes.fromhex(merkle_root)."""
    manifest = _load_manifest(slot)
    expected = bytes.fromhex(manifest["merkle_root"])
    assert len(expected) == 32
    actual = (_hour_dir(slot) / "root.bin").read_bytes()
    assert actual == expected, (
        f"{slot}: root.bin does not match merkle_root field"
    )


# ---------------------------------------------------------------------------
# Schema-file direct validation (via jsonschema-side validator)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slot", TV2_HOUR_SLOTS)
def test_tv2_hour_accepted_by_v1_schema_file(slot):
    """The formal v1 JSON-Schema accepts each TV-2 hour-manifest."""
    pytest.importorskip("jsonschema")
    import jsonschema  # type: ignore[import-not-found]

    with DEFAULT_REAL_SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)
    manifest = _load_manifest(slot)
    # Default (Draft-2020-12) validator; raises ValidationError on reject.
    jsonschema.validate(instance=manifest, schema=schema)


# ---------------------------------------------------------------------------
# Cross-hour prev_hour_root chain
# ---------------------------------------------------------------------------


def test_tv2_prev_hour_root_chain_contiguous():
    """T00 is genesis (null); T01..T03 chain back to T(N-1).merkle_root."""
    manifests = {slot: _load_manifest(slot) for slot in TV2_HOUR_SLOTS}

    # T00 is run-genesis: prev_hour_root must be null.
    assert manifests["2026-05-27T00"]["prev_hour_root"] is None, (
        "TV-2 T00 should be run-genesis (prev_hour_root null)"
    )

    # T01..T03 chain back to T(N-1).merkle_root.
    for prev_slot, this_slot in zip(TV2_HOUR_SLOTS, TV2_HOUR_SLOTS[1:]):
        prev_root = manifests[prev_slot]["merkle_root"]
        this_prev = manifests[this_slot]["prev_hour_root"]
        assert this_prev == prev_root, (
            f"chain break: {this_slot}.prev_hour_root = {this_prev!r} "
            f"but {prev_slot}.merkle_root = {prev_root!r}"
        )


# ---------------------------------------------------------------------------
# Negative-path: mutated copies of T00 must reject
# ---------------------------------------------------------------------------


def _copy_t00_and_mutate(tmp_path: Path, mutate_fn):
    """Copy T00 fixture into tmp_path, mutate manifest in-place, return path."""
    src = _hour_dir("2026-05-27T00")
    dst = tmp_path / "2026-05-27T00"
    shutil.copytree(src, dst)
    manifest_path = dst / "manifest.json"
    with manifest_path.open("r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    mutate_fn(manifest)
    with manifest_path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    return manifest_path


def test_tv2_t00_tampered_merkle_root_rejected(tmp_path):
    """Flipping a hex digit in merkle_root breaks integrity.

    The integrity check rebuilds the Merkle tree from leaves[];
    tampering merkle_root makes the rebuilt root mismatch.
    """
    def mutate(m):
        # Flip the last hex digit (still a valid 64-hex string, but
        # no longer matches the rebuilt tree).
        original = m["merkle_root"]
        flipped = original[:-1] + ("0" if original[-1] != "0" else "1")
        m["merkle_root"] = flipped

    manifest_path = _copy_t00_and_mutate(tmp_path, mutate)
    # OTS anchor side-files still exist next to the mutated manifest;
    # the field-rebuild check is what catches this. Disable OTS
    # check to keep the failure reason deterministic.
    result = verify_real_manifest_file(
        manifest_path, check_ots_anchor=False, use_schema_file=True
    )
    assert not result.ok, "tampered merkle_root must not pass"
    # Either fields_ok or integrity_ok must be False; in this
    # tampering the schema still passes (still 64-hex), but the
    # rebuild-vs-claim integrity check fails.
    assert not result.integrity_ok, (
        "tampered merkle_root must fail integrity rebuild check"
    )


def test_tv2_t00_tampered_version_rejected_by_schema(tmp_path):
    """Replacing version with an unknown string fails schema-file enum."""
    def mutate(m):
        m["version"] = "wakir-wat-manifest/v99"

    manifest_path = _copy_t00_and_mutate(tmp_path, mutate)
    result = verify_real_manifest_file(
        manifest_path, check_ots_anchor=False, use_schema_file=True
    )
    assert not result.ok, "unknown version must not pass"
    assert not result.fields_ok, (
        "unknown version must fail schema-side validation (fields_ok)"
    )


# ---------------------------------------------------------------------------
# Driver-script smoke (real-tv2 mode)
# ---------------------------------------------------------------------------


def test_tv2_driver_real_tv2_mode_runs_clean():
    """``scripts/external_verifier_validation.py --real-tv2`` exits 0.

    The driver iterates the TV-2 fixture cohort and re-runs the same
    pipeline this test module asserts; this is the CLI surface the
    Tag-2 outbox quotes.
    """
    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parents[2]
    cmd = [
        sys.executable,
        str(repo_root / "scripts" / "external_verifier_validation.py"),
        "--real-tv2",
        "--quiet",
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, (
        f"driver --real-tv2 exit {completed.returncode}\n"
        f"stdout: {completed.stdout}\nstderr: {completed.stderr}"
    )
