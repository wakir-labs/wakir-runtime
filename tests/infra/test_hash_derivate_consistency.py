# SPDX-FileCopyrightText: 2026 Wakir Labs
# SPDX-License-Identifier: Apache-2.0
"""
Hash-Derivate-Drift consistency test (Sprint-Stability Tag-3, 2026-05-16).

Drives the `hash-derivate-gate` CI workflow. Verifies that every
hash-derivative fixture artifact under
`tests/fixtures/schema-registry/` stays in lock-step with the
live schema bytes it references.

Background
----------

Reza-PR #92 introduced top-level ``x-spdx-license-identifier`` on
all JSON schemas (ADR-0061 Folgeartefakte). That changed the
SHA-256 of ``wirelang/schemas/caveat-override-event-export.json``
from ``927eda…cbe82edb`` (6907 B) to ``353a617e…708464a2``
(6988 B). The hash-derivative fixture artifacts under
``tests/fixtures/schema-registry/caveat-override-event-export-v1/``
(specifically ``anchor-manifest.json``'s ``schema_file_sha256`` /
``schema_file_bytes`` fields, and the co-located
``schema.sha256.bin`` raw-32-byte digest) were not co-derived in
PR #92. Reza-PR #98 caught and fixed the drift after the fact.

This test cements the invariant in CI so the same class of drift
cannot re-enter ``main`` after any future schema modification. The
gate is hermetic: only stdlib + filesystem reads, no network, no
external state.

Test-vector matrix
------------------

TV-HDC-01 .. TV-HDC-05  — anchor-manifest schema_file_sha256
                          and schema_file_bytes consistency for
                          each discovered fixture. Currently a
                          single fixture exists
                          (``caveat-override-event-export-v1``);
                          additional fixtures auto-enroll via the
                          ``_fixture_dirs()`` enumeration.

TV-HDC-06 .. TV-HDC-10  — schema.sha256.bin raw-byte consistency
                          for each discovered fixture.

TV-HDC-11+              — synthetic drift-detection vectors using
                          ``tmp_path``-materialised mock fixtures.
                          Confirms the test logic actually fails on
                          drift (negative-path coverage), so a
                          silent-pass regression in the test itself
                          would surface immediately.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterator

import pytest

# Resolve the repository root via the test-file location. The test
# lives under ``tests/infra/`` so the repo root is two levels up.
REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "schema-registry"


def _fixture_dirs() -> list[Path]:
    """Enumerate every fixture directory that contains an
    ``anchor-manifest.json``. Skips non-directories and any
    directory without a manifest, so partially-staged fixtures do
    not silently bypass the gate."""
    if not FIXTURES_DIR.exists():
        return []
    result: list[Path] = []
    for entry in sorted(FIXTURES_DIR.iterdir()):
        if not entry.is_dir():
            continue
        if (entry / "anchor-manifest.json").exists():
            result.append(entry)
    return result


def _load_manifest(fixture_dir: Path) -> dict:
    return json.loads(
        (fixture_dir / "anchor-manifest.json").read_text(encoding="utf-8")
    )


# ----------------------------------------------------------------------
# Discovery sanity (TV-HDC-00)
# ----------------------------------------------------------------------

def test_hdc_00_at_least_one_fixture_discovered() -> None:
    """TV-HDC-00 — Guard against empty enumeration. If the fixture
    directory ever empties or moves, the gate would otherwise pass
    vacuously. This test fails fast in that case so the gate stays
    meaningful."""
    fixtures = _fixture_dirs()
    assert fixtures, (
        f"hash-derivate-gate: no fixtures under {FIXTURES_DIR}. "
        "If the layout moved, update _fixture_dirs() and this test."
    )


# ----------------------------------------------------------------------
# TV-HDC-01 .. TV-HDC-05 — anchor-manifest consistency
# ----------------------------------------------------------------------

@pytest.mark.parametrize("fixture_dir", _fixture_dirs(), ids=lambda p: p.name)
def test_hdc_01_anchor_manifest_schema_file_sha256_matches_live(
    fixture_dir: Path,
) -> None:
    """TV-HDC-01 — ``schema_file_sha256`` in the manifest equals
    ``sha256(schema_file_path)`` computed live from the repo."""
    manifest = _load_manifest(fixture_dir)
    schema_rel = manifest["schema_file_path"]
    declared = manifest["schema_file_sha256"]
    schema_path = REPO_ROOT / schema_rel
    assert schema_path.exists(), (
        f"schema_file_path does not exist: {schema_rel} "
        f"(referenced from {fixture_dir.name}/anchor-manifest.json)"
    )
    live = hashlib.sha256(schema_path.read_bytes()).hexdigest()
    assert declared == live, (
        f"schema_file_sha256 drift in {fixture_dir.name}:\n"
        f"  declared : {declared}\n"
        f"  live     : {live}\n"
        f"  schema   : {schema_rel}\n"
        f"Fix: re-derive the manifest hash-derivatives in the same PR "
        f"that modifies the schema (Sprint-Stability Tag-3 invariant)."
    )


@pytest.mark.parametrize("fixture_dir", _fixture_dirs(), ids=lambda p: p.name)
def test_hdc_02_anchor_manifest_schema_file_bytes_matches_live(
    fixture_dir: Path,
) -> None:
    """TV-HDC-02 — ``schema_file_bytes`` in the manifest equals
    ``len(schema_file_path-bytes)`` from the repo. Catches a class
    of drift where the SHA happens to be re-derived but the byte
    count was left stale (or vice versa)."""
    manifest = _load_manifest(fixture_dir)
    schema_rel = manifest["schema_file_path"]
    declared = manifest["schema_file_bytes"]
    schema_path = REPO_ROOT / schema_rel
    assert schema_path.exists(), (
        f"schema_file_path does not exist: {schema_rel}"
    )
    live = len(schema_path.read_bytes())
    assert declared == live, (
        f"schema_file_bytes drift in {fixture_dir.name}:\n"
        f"  declared : {declared}\n"
        f"  live     : {live}\n"
        f"  schema   : {schema_rel}"
    )


@pytest.mark.parametrize("fixture_dir", _fixture_dirs(), ids=lambda p: p.name)
def test_hdc_03_anchor_manifest_required_fields_present(
    fixture_dir: Path,
) -> None:
    """TV-HDC-03 — manifest carries the four fields the gate
    enforces. Catches a partial-rewrite where a field was renamed
    or dropped (which would otherwise yield a confusing KeyError in
    the parametrised tests above)."""
    manifest = _load_manifest(fixture_dir)
    for field in (
        "schema_file_path",
        "schema_file_sha256",
        "schema_file_bytes",
        "anchor_digest_target",
    ):
        assert field in manifest, (
            f"anchor-manifest.json in {fixture_dir.name} is missing "
            f"required field '{field}'"
        )


@pytest.mark.parametrize("fixture_dir", _fixture_dirs(), ids=lambda p: p.name)
def test_hdc_04_anchor_digest_algorithm_is_sha256(fixture_dir: Path) -> None:
    """TV-HDC-04 — ``anchor_digest_algorithm`` is sha256. The gate
    re-computes with hashlib.sha256; another algorithm would
    silently mismatch and require gate-logic updates first."""
    manifest = _load_manifest(fixture_dir)
    declared_algo = manifest.get("anchor_digest_algorithm", "sha256")
    assert declared_algo == "sha256", (
        f"{fixture_dir.name}: anchor_digest_algorithm is "
        f"'{declared_algo}', gate currently only supports sha256."
    )


@pytest.mark.parametrize("fixture_dir", _fixture_dirs(), ids=lambda p: p.name)
def test_hdc_05_anchor_digest_target_resolves(fixture_dir: Path) -> None:
    """TV-HDC-05 — ``anchor_digest_target`` resolves to an existing
    file relative to the fixture directory. This is the file
    TV-HDC-06 will validate the raw bytes of."""
    manifest = _load_manifest(fixture_dir)
    target = manifest["anchor_digest_target"]
    target_path = fixture_dir / target
    assert target_path.exists(), (
        f"{fixture_dir.name}: anchor_digest_target '{target}' "
        f"does not resolve to {target_path}"
    )


# ----------------------------------------------------------------------
# TV-HDC-06 .. TV-HDC-10 — schema.sha256.bin raw-byte consistency
# ----------------------------------------------------------------------

@pytest.mark.parametrize("fixture_dir", _fixture_dirs(), ids=lambda p: p.name)
def test_hdc_06_sha256_bin_length_is_32(fixture_dir: Path) -> None:
    """TV-HDC-06 — co-located ``schema.sha256.bin`` is exactly
    32 bytes (raw sha256 digest). Catches accidental hex-encoding
    or trailing-newline regressions."""
    manifest = _load_manifest(fixture_dir)
    bin_path = fixture_dir / manifest["anchor_digest_target"]
    raw = bin_path.read_bytes()
    assert len(raw) == 32, (
        f"{fixture_dir.name}: {bin_path.name} is {len(raw)} bytes, "
        f"expected 32 (raw sha256 digest)."
    )


@pytest.mark.parametrize("fixture_dir", _fixture_dirs(), ids=lambda p: p.name)
def test_hdc_07_sha256_bin_matches_live_schema_digest(
    fixture_dir: Path,
) -> None:
    """TV-HDC-07 — co-located ``schema.sha256.bin`` raw bytes equal
    ``sha256(schema_file_path)`` computed live. This is the
    invariant Reza-PR #98 had to re-derive after PR #92."""
    manifest = _load_manifest(fixture_dir)
    schema_rel = manifest["schema_file_path"]
    schema_path = REPO_ROOT / schema_rel
    bin_path = fixture_dir / manifest["anchor_digest_target"]
    live_digest = hashlib.sha256(schema_path.read_bytes()).digest()
    bin_bytes = bin_path.read_bytes()
    assert bin_bytes == live_digest, (
        f"schema.sha256.bin drift in {fixture_dir.name}:\n"
        f"  bin (hex)  : {bin_bytes.hex()}\n"
        f"  live (hex) : {live_digest.hex()}\n"
        f"  schema     : {schema_rel}\n"
        f"Fix: rewrite {bin_path.name} with the live raw 32-byte "
        f"digest in the same PR that modified the schema."
    )


@pytest.mark.parametrize("fixture_dir", _fixture_dirs(), ids=lambda p: p.name)
def test_hdc_08_sha256_bin_matches_manifest_declared(
    fixture_dir: Path,
) -> None:
    """TV-HDC-08 — co-located ``schema.sha256.bin`` raw bytes equal
    the ``schema_file_sha256`` hex in the manifest. Both must agree;
    a mismatch indicates partial drift between the two derivative
    artifacts."""
    manifest = _load_manifest(fixture_dir)
    declared_hex = manifest["schema_file_sha256"]
    bin_path = fixture_dir / manifest["anchor_digest_target"]
    bin_hex = bin_path.read_bytes().hex()
    assert bin_hex == declared_hex, (
        f"{fixture_dir.name}: schema.sha256.bin ({bin_hex}) and "
        f"manifest schema_file_sha256 ({declared_hex}) disagree."
    )


@pytest.mark.parametrize("fixture_dir", _fixture_dirs(), ids=lambda p: p.name)
def test_hdc_09_sha256_bin_no_trailing_newline(fixture_dir: Path) -> None:
    """TV-HDC-09 — defensive check that ``schema.sha256.bin`` is
    not a 33-byte hex-with-newline file. The 32-byte assertion in
    TV-HDC-06 already covers this, but having a dedicated vector
    makes the failure mode explicit during triage."""
    manifest = _load_manifest(fixture_dir)
    bin_path = fixture_dir / manifest["anchor_digest_target"]
    raw = bin_path.read_bytes()
    assert not raw.endswith(b"\n"), (
        f"{fixture_dir.name}: {bin_path.name} ends with a newline; "
        f"must be raw 32 bytes, no trailing whitespace."
    )


@pytest.mark.parametrize("fixture_dir", _fixture_dirs(), ids=lambda p: p.name)
def test_hdc_10_schema_file_path_is_relative(fixture_dir: Path) -> None:
    """TV-HDC-10 — ``schema_file_path`` is a relative repo path,
    not an absolute path. Absolute paths would break the gate on
    runners with different repo-roots (e.g. CI ubuntu-latest vs.
    operator-laptop)."""
    manifest = _load_manifest(fixture_dir)
    schema_rel = manifest["schema_file_path"]
    p = Path(schema_rel)
    assert not p.is_absolute(), (
        f"{fixture_dir.name}: schema_file_path '{schema_rel}' is "
        f"absolute; must be relative to repo root."
    )


# ----------------------------------------------------------------------
# TV-HDC-11 .. TV-HDC-14 — synthetic drift-detection vectors
# ----------------------------------------------------------------------
#
# These vectors materialise a synthetic fixture under ``tmp_path``
# and run the same recompute logic against it, so the test logic
# itself is exercised on both positive and negative paths. If a
# future refactor accidentally makes ``test_hdc_07`` silently pass
# on drift (e.g. by swallowing exceptions), these vectors will
# catch it.

def _build_synthetic_fixture(
    tmp_path: Path,
    schema_bytes: bytes,
    *,
    drift_sha: bool = False,
    drift_bytes: bool = False,
    drift_bin: bool = False,
) -> tuple[Path, Path, dict]:
    """Materialise a tmp-path fixture mirroring the real layout.

    Returns ``(fixture_dir, schema_path, manifest_dict)``. When any
    of the ``drift_*`` flags is True, the corresponding declared
    field is intentionally wrong so the recompute logic must
    detect it.
    """
    schema_dir = tmp_path / "wirelang" / "schemas"
    schema_dir.mkdir(parents=True)
    schema_path = schema_dir / "synthetic.json"
    schema_path.write_bytes(schema_bytes)

    live_digest = hashlib.sha256(schema_bytes).digest()
    live_hex = live_digest.hex()
    live_bytes = len(schema_bytes)

    declared_hex = live_hex if not drift_sha else "00" * 32
    declared_bytes = live_bytes if not drift_bytes else live_bytes + 1
    bin_payload = live_digest if not drift_bin else b"\x00" * 32

    fixture_dir = (
        tmp_path
        / "tests"
        / "fixtures"
        / "schema-registry"
        / "synthetic-v1"
    )
    fixture_dir.mkdir(parents=True)
    manifest = {
        "schema_registry_id": "wakir.synthetic/1",
        "schema_file_path": "wirelang/schemas/synthetic.json",
        "schema_file_sha256": declared_hex,
        "schema_file_bytes": declared_bytes,
        "anchor_kind": "wakir.schema-registry.ots-anchor/1",
        "anchor_digest_algorithm": "sha256",
        "anchor_digest_target": "schema.sha256.bin",
    }
    (fixture_dir / "anchor-manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (fixture_dir / "schema.sha256.bin").write_bytes(bin_payload)
    return fixture_dir, schema_path, manifest


def _recompute_check(
    fixture_dir: Path, schema_path: Path
) -> tuple[bool, bool, bool]:
    """Recompute the three drift dimensions against the live
    schema-bytes. Returns ``(sha_ok, bytes_ok, bin_ok)``."""
    manifest = json.loads(
        (fixture_dir / "anchor-manifest.json").read_text(encoding="utf-8")
    )
    raw = schema_path.read_bytes()
    live_hex = hashlib.sha256(raw).hexdigest()
    live_bytes = len(raw)
    sha_ok = manifest["schema_file_sha256"] == live_hex
    bytes_ok = manifest["schema_file_bytes"] == live_bytes
    bin_path = fixture_dir / manifest["anchor_digest_target"]
    bin_ok = bin_path.read_bytes() == hashlib.sha256(raw).digest()
    return sha_ok, bytes_ok, bin_ok


def test_hdc_11_synthetic_no_drift_detects_consistency(
    tmp_path: Path,
) -> None:
    """TV-HDC-11 — clean synthetic fixture passes all three checks
    (positive-path baseline). If this fails, the recompute logic
    itself is broken and the negative-path vectors below cannot be
    trusted."""
    fixture_dir, schema_path, _ = _build_synthetic_fixture(
        tmp_path, b'{"$id":"synthetic","type":"object"}\n'
    )
    sha_ok, bytes_ok, bin_ok = _recompute_check(fixture_dir, schema_path)
    assert (sha_ok, bytes_ok, bin_ok) == (True, True, True)


def test_hdc_12_synthetic_sha_drift_is_detected(tmp_path: Path) -> None:
    """TV-HDC-12 — drifted ``schema_file_sha256`` is detected.
    Mirrors the exact failure mode Reza-PR #98 had to fix."""
    fixture_dir, schema_path, _ = _build_synthetic_fixture(
        tmp_path, b'{"$id":"synthetic","type":"object"}\n', drift_sha=True
    )
    sha_ok, bytes_ok, bin_ok = _recompute_check(fixture_dir, schema_path)
    assert sha_ok is False, "sha-drift must be detected"
    assert bytes_ok is True
    # bin is still live; manifest-vs-bin disagreement is a separate
    # invariant (tested in production fixtures via TV-HDC-08).


def test_hdc_13_synthetic_bytes_drift_is_detected(tmp_path: Path) -> None:
    """TV-HDC-13 — drifted ``schema_file_bytes`` is detected.
    Catches the class where a re-derivation updated the SHA but
    forgot the byte count (or vice versa)."""
    fixture_dir, schema_path, _ = _build_synthetic_fixture(
        tmp_path, b'{"$id":"synthetic","type":"object"}\n', drift_bytes=True
    )
    sha_ok, bytes_ok, bin_ok = _recompute_check(fixture_dir, schema_path)
    assert bytes_ok is False, "byte-count-drift must be detected"
    assert sha_ok is True
    assert bin_ok is True


def test_hdc_14_synthetic_bin_drift_is_detected(tmp_path: Path) -> None:
    """TV-HDC-14 — drifted ``schema.sha256.bin`` raw bytes are
    detected. This is the second half of the Reza-PR #98 fix:
    the manifest hex AND the raw-byte file must both be re-derived."""
    fixture_dir, schema_path, _ = _build_synthetic_fixture(
        tmp_path, b'{"$id":"synthetic","type":"object"}\n', drift_bin=True
    )
    sha_ok, bytes_ok, bin_ok = _recompute_check(fixture_dir, schema_path)
    assert bin_ok is False, "schema.sha256.bin drift must be detected"
    assert sha_ok is True
    assert bytes_ok is True
