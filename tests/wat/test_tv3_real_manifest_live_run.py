# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""TV-3 real-manifest live-run validation.

Sprint-3 Tag-3 substance: the single hour-receipt produced by the
TV-3 close-out run on 2026-05-07 is committed under
``tests/fixtures/wat-tv3-real/`` and is exercised here as a second
real-world-anchored reference cohort alongside the TV-2 multi-hour
cohort.

What this module checks
-----------------------

For the single TV-3 hour-receipt (2026-05-26T17, run-genesis):

1. ``verify_real_manifest_file(use_schema_file=True,
   check_ots_anchor=True)`` returns a fully-green
   :class:`RealManifestResult`.
2. The manifest is accepted by the formal v1 JSON-Schema file under
   direct ``jsonschema``-driver validation.
3. ``root.bin`` is exactly 32 bytes equal to ``bytes.fromhex
   (manifest['merkle_root'])``.
4. ``prev_hour_root`` is null (TV-3 is single-hour run-genesis).

Negative-path (against mutated copies of the T17 fixture):

5. Tampered ``merkle_root`` -> ``integrity_ok`` False.
6. Tampered ``version`` -> ``fields_ok`` False (schema-side reject).
7. Tampered ``event_count`` (drift vs len(events)) -> integrity reject.

Receipt-persistence edge-cases (against on-disk side-file shapes):

8. ``root.bin`` smaller than 32 bytes -> ots-anchor reject.
9. ``root.bin.ots`` byte-truncated -> ots-anchor reject.
10. ``root.bin`` whose first byte differs from ``merkle_root`` ->
    ots-anchor reject (the side-file does not stamp the claimed root).

Driver-script smoke:

11. ``scripts/external_verifier_validation.py --real-tv3`` exits 0.

Why TV-3 in addition to TV-2
----------------------------

TV-2 (Tag-2) gave us a four-hour multi-hop chain. TV-3 (Tag-3)
gives us a single-hour run-genesis: the schema-file plumbing is
exercised against a *second* real Bitcoin-anchored production
manifest with a different shape (single hop, different submit-run
ID, different OTS proof file). The pair is what proves the
verifier path is not coincidentally tuned to the TV-2 four-hour
specifics.

The receipt-persistence edge-case cluster (8-10) is hardening
substance for Tag-3 specifically: not just "does the verifier
accept the production manifest" (already proven Tag-2) but "does
the verifier reject realistic on-disk corruptions of the
side-files" (root.bin truncation, ots-side-file truncation,
side-file lying about the root).
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

#: Repository-relative path to the TV-3 real-manifest fixture cohort
#: (committed to the repo as Sprint-3 Tag-3 close-out source).
TV3_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "wat-tv3-real"

#: The single hour-slot that comprises the TV-3 close-out run.
TV3_HOUR_SLOTS: tuple[str, ...] = ("2026-05-26T17",)


def _hour_dir(slot: str) -> Path:
    return TV3_FIXTURE_ROOT / slot


def _manifest_path(slot: str) -> Path:
    return _hour_dir(slot) / "manifest.json"


def _load_manifest(slot: str) -> dict:
    with _manifest_path(slot).open("r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Sanity: fixture cohort is on-disk
# ---------------------------------------------------------------------------


def test_tv3_fixture_cohort_present():
    """The single hour-receipt directory carries the three side-files."""
    assert TV3_FIXTURE_ROOT.is_dir(), (
        f"TV-3 fixture root missing: {TV3_FIXTURE_ROOT}"
    )
    for slot in TV3_HOUR_SLOTS:
        d = _hour_dir(slot)
        assert d.is_dir(), f"hour-slot dir missing: {d}"
        for sidecar in ("manifest.json", "root.bin", "root.bin.ots"):
            p = d / sidecar
            assert p.is_file(), f"sidecar missing: {p}"
        assert (d / "root.bin").stat().st_size == 32, (
            f"root.bin must be 32 bytes for {slot}"
        )


# ---------------------------------------------------------------------------
# Per-hour live-run via verify_real_manifest_file
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slot", TV3_HOUR_SLOTS)
def test_tv3_hour_verify_real_manifest_file_green(slot):
    """The TV-3 hour passes the full real-manifest verifier path."""
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


@pytest.mark.parametrize("slot", TV3_HOUR_SLOTS)
def test_tv3_hour_root_bin_matches_merkle_root(slot):
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


@pytest.mark.parametrize("slot", TV3_HOUR_SLOTS)
def test_tv3_hour_accepted_by_v1_schema_file(slot):
    """The formal v1 JSON-Schema accepts the TV-3 hour-manifest."""
    pytest.importorskip("jsonschema")
    import jsonschema  # type: ignore[import-not-found]

    with DEFAULT_REAL_SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)
    manifest = _load_manifest(slot)
    jsonschema.validate(instance=manifest, schema=schema)


# ---------------------------------------------------------------------------
# TV-3 is single-hour run-genesis
# ---------------------------------------------------------------------------


def test_tv3_is_single_hour_run_genesis():
    """TV-3 has one hour-slot and prev_hour_root is null."""
    assert len(TV3_HOUR_SLOTS) == 1
    manifest = _load_manifest(TV3_HOUR_SLOTS[0])
    assert manifest["prev_hour_root"] is None, (
        "TV-3 single-hour run-genesis must have prev_hour_root null"
    )


# ---------------------------------------------------------------------------
# Negative-path: mutated copies of T17 must reject
# ---------------------------------------------------------------------------


def _copy_t17_and_mutate(tmp_path: Path, mutate_fn) -> Path:
    """Copy T17 fixture into tmp_path, mutate manifest, return new path."""
    src = _hour_dir(TV3_HOUR_SLOTS[0])
    dst = tmp_path / TV3_HOUR_SLOTS[0]
    shutil.copytree(src, dst)
    manifest_path = dst / "manifest.json"
    with manifest_path.open("r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    mutate_fn(manifest)
    with manifest_path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    return manifest_path


def test_tv3_t17_tampered_merkle_root_rejected(tmp_path):
    """Flipping a hex digit in merkle_root breaks integrity rebuild."""
    def mutate(m):
        original = m["merkle_root"]
        flipped = original[:-1] + ("0" if original[-1] != "0" else "1")
        m["merkle_root"] = flipped

    manifest_path = _copy_t17_and_mutate(tmp_path, mutate)
    result = verify_real_manifest_file(
        manifest_path, check_ots_anchor=False, use_schema_file=True
    )
    assert not result.ok, "tampered merkle_root must not pass"
    assert not result.integrity_ok, (
        "tampered merkle_root must fail integrity rebuild check"
    )


def test_tv3_t17_tampered_version_rejected_by_schema(tmp_path):
    """Replacing version with an unknown string fails schema-file enum."""
    def mutate(m):
        m["version"] = "wakir-wat-manifest/v99"

    manifest_path = _copy_t17_and_mutate(tmp_path, mutate)
    result = verify_real_manifest_file(
        manifest_path, check_ots_anchor=False, use_schema_file=True
    )
    assert not result.ok, "unknown version must not pass"
    assert not result.fields_ok, (
        "unknown version must fail schema-side validation (fields_ok)"
    )


def test_tv3_t17_tampered_event_count_rejected(tmp_path):
    """event_count drifting from len(events) breaks fields/integrity check.

    The schema-side declares event_count as an integer; the code-side
    ``verify_real_manifest_file`` enforces the cross-check that
    event_count == len(events). A drift here is a realistic
    aggregator-bug shape.
    """
    def mutate(m):
        m["event_count"] = m["event_count"] + 1  # claim one more event than present

    manifest_path = _copy_t17_and_mutate(tmp_path, mutate)
    result = verify_real_manifest_file(
        manifest_path, check_ots_anchor=False, use_schema_file=True
    )
    assert not result.ok, "drifted event_count must not pass"


# ---------------------------------------------------------------------------
# Receipt-persistence edge-cases: corrupted on-disk side-files
# ---------------------------------------------------------------------------


def _copy_cohort(tmp_path: Path) -> Path:
    """Copy the entire TV-3 fixture into tmp_path, return the hour-dir."""
    src = _hour_dir(TV3_HOUR_SLOTS[0])
    dst = tmp_path / TV3_HOUR_SLOTS[0]
    shutil.copytree(src, dst)
    return dst


def test_tv3_t17_root_bin_truncated_rejected_by_ots_anchor(tmp_path):
    """A root.bin smaller than 32 bytes is not a valid Merkle root.

    Production aggregators emit exactly 32 bytes; a short root.bin is
    a corruption signal and ``check_ots_anchor=True`` must reject it.
    """
    dst_dir = _copy_cohort(tmp_path)
    short = dst_dir / "root.bin"
    short.write_bytes(b"\x00" * 16)  # half-size
    result = verify_real_manifest_file(
        dst_dir / "manifest.json",
        check_ots_anchor=True,
        use_schema_file=True,
    )
    assert not result.ok, "truncated root.bin must not pass"
    assert not result.ots_anchor.ok, (
        "truncated root.bin must fail ots-anchor side-file check"
    )


def test_tv3_t17_ots_side_file_truncated_rejected(tmp_path):
    """A truncated root.bin.ots is not a well-formed OTS proof.

    The ots-anchor side-file check looks for the OpenTimestamps magic
    header; a single-byte file cannot carry it.
    """
    dst_dir = _copy_cohort(tmp_path)
    ots_file = dst_dir / "root.bin.ots"
    ots_file.write_bytes(b"\x00")  # one-byte truncation
    result = verify_real_manifest_file(
        dst_dir / "manifest.json",
        check_ots_anchor=True,
        use_schema_file=True,
    )
    assert not result.ok, "truncated ots side-file must not pass"
    assert not result.ots_anchor.ok, (
        "truncated ots side-file must fail ots-anchor side-file check"
    )


def test_tv3_t17_root_bin_does_not_match_merkle_root_rejected(tmp_path):
    """A root.bin whose bytes differ from merkle_root is a side-file lie.

    The aggregator could produce a manifest that *claims* root X while
    the OTS-stamped root.bin holds root Y; the verifier must catch
    this. The integrity-side rebuilds the tree and matches against
    merkle_root (manifest claim); the ots-anchor side compares
    root.bin against merkle_root (side-file claim). When root.bin
    lies, the ots-anchor side detects the mismatch.
    """
    dst_dir = _copy_cohort(tmp_path)
    root_bin = dst_dir / "root.bin"
    original = root_bin.read_bytes()
    # Flip a single byte; still 32 bytes, still binary, but now does
    # not equal bytes.fromhex(merkle_root).
    flipped_byte = (original[0] ^ 0x01).to_bytes(1, "big")
    root_bin.write_bytes(flipped_byte + original[1:])
    result = verify_real_manifest_file(
        dst_dir / "manifest.json",
        check_ots_anchor=True,
        use_schema_file=True,
    )
    assert not result.ok, "root.bin lying about merkle_root must not pass"
    assert not result.ots_anchor.ok, (
        "root.bin not equal merkle_root must fail ots-anchor side-file check"
    )


# ---------------------------------------------------------------------------
# Driver-script smoke (real-tv3 mode)
# ---------------------------------------------------------------------------


def test_tv3_driver_real_tv3_mode_runs_clean():
    """``scripts/external_verifier_validation.py --real-tv3`` exits 0."""
    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parents[2]
    cmd = [
        sys.executable,
        str(repo_root / "scripts" / "external_verifier_validation.py"),
        "--real-tv3",
        "--quiet",
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, (
        f"driver --real-tv3 exit {completed.returncode}\n"
        f"stdout: {completed.stdout}\nstderr: {completed.stderr}"
    )
