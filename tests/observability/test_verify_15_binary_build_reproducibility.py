#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for
``scripts/observability/verify-15-binary-build-reproducibility.py``.

Tag-51 Kai -- 15-Binary Build-Reproducibility Audit.

Coverage targets the pure-function core. The tests in this file
cover:

  * 3 Cargo.lock parser invariants     (TV-PL-01..TV-PL-03)
  * 4 transitive-closure invariants    (TV-TC-01..TV-TC-04)
  * 3 fingerprint determinism          (TV-FP-01..TV-FP-03)
  * 2 compare-passes verdict           (TV-CP-01..TV-CP-02)
  * 3 render-envelope/prom/md          (TV-RD-01..TV-RD-03)
  * 2 mira-notify shape                (TV-MN-01..TV-MN-02)
  * 1 CLI smoke (run_audit end-to-end) (TV-CLI-01)

Total: 18 hermetic invariants -- comfortably above the >=12 target.

Sandbox boundary
----------------

These tests NEVER invoke cargo / cosign / podman / network. They
synthesise tiny inline Cargo.lock fixtures and assert the expected
fingerprint shape, JSON envelope shape, and drift detection.

Author: Kai Hoffmann (Dev-Engineering-3)
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Loader: import the hyphenated module path.
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
_MOD_PATH = (
    _REPO_ROOT
    / "scripts"
    / "observability"
    / "verify-15-binary-build-reproducibility.py"
)

_spec = importlib.util.spec_from_file_location(
    "verify_15_binary_build_reproducibility", str(_MOD_PATH)
)
assert _spec is not None
assert _spec.loader is not None
vbr = importlib.util.module_from_spec(_spec)
sys.modules["verify_15_binary_build_reproducibility"] = vbr
_spec.loader.exec_module(vbr)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Synthetic Cargo.lock fixture.
#
# Covers every welle-pinned variant of the canonical inventory plus
# their transitive deps. The shape is intentionally small so the
# expected fingerprints can be reasoned about by hand.
# ---------------------------------------------------------------------------

_SYNTHETIC_LOCK = b"""\
version = 4

[[package]]
name = "cfg-if"
version = "1.0.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "baf1de4339761588bc0619e3cbc0120ee582ebb74b53b4efbf79117bd2da40fd"

[[package]]
name = "hex"
version = "0.4.3"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "7f24254aa9a54b5c858eaee2f5bccdb46aaf0e486a595ed5fd8f86ba55232a70"

[[package]]
name = "serde_json"
version = "1.0.120"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "4e2eaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

[[package]]
name = "persona-engine-recovery"
version = "0.1.0"
dependencies = [
 "hex",
 "serde_json",
]

[[package]]
name = "persona-engine-state-backing"
version = "0.1.0"
dependencies = [
 "hex",
]

[[package]]
name = "persona-engine-fsm"
version = "0.1.0"
dependencies = [
 "cfg-if",
 "serde_json",
]

[[package]]
name = "persona-engine-v907-verify"
version = "0.1.0"
dependencies = [
 "serde_json",
]

[[package]]
name = "persona-engine-bridge-diff"
version = "0.1.0"
dependencies = [
 "serde_json",
]

[[package]]
name = "persona-engine-subscribe-loop"
version = "0.1.0"
dependencies = [
 "cfg-if",
]

[[package]]
name = "persona-engine-anchor-emitter"
version = "0.1.0"
dependencies = []

[[package]]
name = "persona-engine-svid-workload-identity"
version = "0.1.0"
dependencies = [
 "hex",
]

[[package]]
name = "persona-engine-bridge-audit-writer"
version = "0.1.0"
dependencies = [
 "serde_json",
]

[[package]]
name = "persona-engine-bridge-audit-replay"
version = "0.1.0"
dependencies = [
 "serde_json",
]

[[package]]
name = "persona-engine-migrate-version"
version = "0.1.0"
dependencies = []
"""


# ---------------------------------------------------------------------------
# TV-PL-* : Cargo.lock parser invariants.
# ---------------------------------------------------------------------------


def test_TV_PL_01_parse_cargo_lock_returns_full_package_set() -> None:
    """All declared packages survive the parse round-trip."""
    pkgs = vbr.parse_cargo_lock(_SYNTHETIC_LOCK)
    names = {p.name for p in pkgs}
    # 3 transitive deps + 11 workspace crates.
    assert "cfg-if" in names
    assert "hex" in names
    assert "serde_json" in names
    assert "persona-engine-recovery" in names
    assert "persona-engine-migrate-version" in names


def test_TV_PL_02_dependency_edges_are_name_only() -> None:
    """Dependency strings are stripped to bare name."""
    pkgs = vbr.parse_cargo_lock(_SYNTHETIC_LOCK)
    recovery = next(p for p in pkgs if p.name == "persona-engine-recovery")
    assert recovery.dependencies == ("hex", "serde_json")


def test_TV_PL_03_missing_package_array_raises() -> None:
    """A Cargo.lock without [[package]] raises ValueError."""
    with pytest.raises(ValueError):
        vbr.parse_cargo_lock(b"version = 4\n")


# ---------------------------------------------------------------------------
# TV-TC-* : transitive-closure invariants.
# ---------------------------------------------------------------------------


def test_TV_TC_01_closure_includes_root_and_all_deps() -> None:
    """The closure contains the root crate and every transitive dep."""
    pkgs = vbr.parse_cargo_lock(_SYNTHETIC_LOCK)
    idx = vbr.build_package_index(pkgs)
    closure = vbr.transitive_closure("persona-engine-recovery", idx)
    names = {p.name for p in closure}
    assert names == {
        "persona-engine-recovery", "hex", "serde_json",
    }


def test_TV_TC_02_closure_is_lex_sorted() -> None:
    """The closure tuple is sorted lexicographically by (name, version)."""
    pkgs = vbr.parse_cargo_lock(_SYNTHETIC_LOCK)
    idx = vbr.build_package_index(pkgs)
    closure = vbr.transitive_closure("persona-engine-fsm", idx)
    names = [p.name for p in closure]
    assert names == sorted(names)


def test_TV_TC_03_unknown_root_raises_keyerror() -> None:
    """A root_name not in pkg_index raises KeyError."""
    pkgs = vbr.parse_cargo_lock(_SYNTHETIC_LOCK)
    idx = vbr.build_package_index(pkgs)
    with pytest.raises(KeyError):
        vbr.transitive_closure("does-not-exist", idx)


def test_TV_TC_04_closure_handles_multi_version_dep() -> None:
    """Multiple versions of the same crate are all included.

    Mirrors the Tag-48 generator's invariant: when Cargo.lock
    contains two versions of the same crate (e.g. block-buffer
    0.10 + 0.9), both versions show up in the closure if both
    are reachable from the root.
    """
    multi_lock = b"""\
version = 4

[[package]]
name = "block-buffer"
version = "0.10.4"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

[[package]]
name = "block-buffer"
version = "0.9.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

[[package]]
name = "persona-engine-recovery"
version = "0.1.0"
dependencies = [
 "block-buffer",
]
"""
    pkgs = vbr.parse_cargo_lock(multi_lock)
    idx = vbr.build_package_index(pkgs)
    closure = vbr.transitive_closure("persona-engine-recovery", idx)
    versions = sorted(
        p.version for p in closure if p.name == "block-buffer"
    )
    assert versions == ["0.10.4", "0.9.0"]


# ---------------------------------------------------------------------------
# TV-FP-* : fingerprint determinism invariants.
# ---------------------------------------------------------------------------


def test_TV_FP_01_two_passes_byte_equal() -> None:
    """Two derive_pass invocations on the same input are byte-equal."""
    p1 = vbr.derive_pass(_SYNTHETIC_LOCK)
    p2 = vbr.derive_pass(_SYNTHETIC_LOCK)
    assert p1.cargo_lock_sha256 == p2.cargo_lock_sha256
    for fp1, fp2 in zip(p1.per_binary, p2.per_binary):
        assert fp1.fingerprint_sha256 == fp2.fingerprint_sha256


def test_TV_FP_02_distinct_binaries_have_distinct_fingerprints() -> None:
    """Sibling welle-variants get distinct fingerprints by binary_name.

    ``state-backing`` and ``state-backing-welle4`` share the same root
    crate but the fingerprint binds binary_name into the hash, so
    their fingerprints must differ.
    """
    p1 = vbr.derive_pass(_SYNTHETIC_LOCK)
    by_name = {fp.binary_name: fp for fp in p1.per_binary}
    a = by_name["state-backing"]
    b = by_name["state-backing-welle4"]
    assert a.root_crate == b.root_crate
    assert a.fingerprint_sha256 != b.fingerprint_sha256


def test_TV_FP_03_inventory_covers_all_15_binaries() -> None:
    """The pass result covers exactly the 15 canonical binaries."""
    p1 = vbr.derive_pass(_SYNTHETIC_LOCK)
    names = [fp.binary_name for fp in p1.per_binary]
    assert names == list(vbr.TAG45_BINARY_INVENTORY)
    assert len(names) == 15


# ---------------------------------------------------------------------------
# TV-CP-* : compare_passes verdict invariants.
# ---------------------------------------------------------------------------


def test_TV_CP_01_green_when_two_passes_match() -> None:
    """GREEN verdict when both passes are byte-equal."""
    p1 = vbr.derive_pass(_SYNTHETIC_LOCK)
    p2 = vbr.derive_pass(_SYNTHETIC_LOCK)
    verdict = vbr.compare_passes(p1, p2)
    assert verdict.overall_green is True
    assert verdict.drift_count == 0
    assert verdict.deterministic_count == 15


def test_TV_CP_02_red_when_fingerprint_diverges() -> None:
    """RED verdict + drift_count >= 1 when a fingerprint differs."""
    p1 = vbr.derive_pass(_SYNTHETIC_LOCK)
    # Hand-craft a divergent pass by mutating one binary's
    # fingerprint string.
    mutated = list(p1.per_binary)
    target = mutated[0]
    mutated[0] = vbr.BinaryFingerprint(
        binary_name=target.binary_name,
        root_crate=target.root_crate,
        transitive_count=target.transitive_count,
        fingerprint_sha256="0" * 64,
    )
    p2 = vbr.PassResult(
        cargo_lock_sha256=p1.cargo_lock_sha256,
        per_binary=tuple(mutated),
    )
    verdict = vbr.compare_passes(p1, p2)
    assert verdict.overall_green is False
    assert verdict.drift_count == 1
    assert verdict.deterministic_count == 14
    assert verdict.per_binary[0].deterministic is False


# ---------------------------------------------------------------------------
# TV-RD-* : renderer invariants.
# ---------------------------------------------------------------------------


def test_TV_RD_01_envelope_json_is_canonical() -> None:
    """JSON envelope is sorted-keys + parseable."""
    p1 = vbr.derive_pass(_SYNTHETIC_LOCK)
    p2 = vbr.derive_pass(_SYNTHETIC_LOCK)
    verdict = vbr.compare_passes(p1, p2)
    body_a = vbr.render_envelope_json(verdict, 0.0)
    body_b = vbr.render_envelope_json(verdict, 0.0)
    assert body_a == body_b
    parsed = json.loads(body_a)
    assert parsed["$schema"] == vbr.ENVELOPE_SCHEMA
    assert parsed["overall_green"] is True
    assert len(parsed["per_binary"]) == 15


def test_TV_RD_02_prometheus_textfile_has_per_binary_gauge() -> None:
    """Prom textfile contains the gauge for every binary."""
    p1 = vbr.derive_pass(_SYNTHETIC_LOCK)
    p2 = vbr.derive_pass(_SYNTHETIC_LOCK)
    verdict = vbr.compare_passes(p1, p2)
    text = vbr.render_prom_textfile(verdict)
    assert (
        "wakir_build_reproducibility_deterministic"
        in text
    )
    assert "wakir_build_reproducibility_drift_count 0" in text
    for name in vbr.TAG45_BINARY_INVENTORY:
        assert f'binary="{name}"' in text


def test_TV_RD_03_markdown_summary_renders_table_rows() -> None:
    """Markdown contains a row per binary plus overall-green anchor."""
    p1 = vbr.derive_pass(_SYNTHETIC_LOCK)
    p2 = vbr.derive_pass(_SYNTHETIC_LOCK)
    verdict = vbr.compare_passes(p1, p2)
    md = vbr.render_markdown(verdict)
    assert "## 15-Binary Build-Reproducibility Audit" in md
    assert "Overall**: `GREEN`" in md
    for name in vbr.TAG45_BINARY_INVENTORY:
        assert f"`{name}`" in md


# ---------------------------------------------------------------------------
# TV-MN-* : Mira-Notify payload invariants.
# ---------------------------------------------------------------------------


def test_TV_MN_01_green_emits_empty_notify_payload() -> None:
    """GREEN audit produces an empty Mira-Notify payload."""
    p1 = vbr.derive_pass(_SYNTHETIC_LOCK)
    p2 = vbr.derive_pass(_SYNTHETIC_LOCK)
    verdict = vbr.compare_passes(p1, p2)
    notify = vbr.render_mira_notify(verdict, 0.0)
    assert notify == ""


def test_TV_MN_02_red_emits_drift_event_with_binary_list() -> None:
    """RED audit produces a Mira-Notify event listing every drift binary."""
    p1 = vbr.derive_pass(_SYNTHETIC_LOCK)
    mutated = list(p1.per_binary)
    # Mutate two binaries so we can assert the list is complete.
    for i in (2, 5):
        target = mutated[i]
        mutated[i] = vbr.BinaryFingerprint(
            binary_name=target.binary_name,
            root_crate=target.root_crate,
            transitive_count=target.transitive_count,
            fingerprint_sha256="f" * 64,
        )
    p2 = vbr.PassResult(
        cargo_lock_sha256=p1.cargo_lock_sha256,
        per_binary=tuple(mutated),
    )
    verdict = vbr.compare_passes(p1, p2)
    notify = vbr.render_mira_notify(verdict, 0.0)
    assert notify != ""
    parsed = json.loads(notify)
    assert parsed["severity"] == "RED"
    assert parsed["event_type"] == "build-reproducibility-drift"
    assert parsed["drift_count"] == 2
    assert set(parsed["drift_binaries"]) == {
        vbr.TAG45_BINARY_INVENTORY[2],
        vbr.TAG45_BINARY_INVENTORY[5],
    }


# ---------------------------------------------------------------------------
# TV-CLI-01 : CLI smoke test (end-to-end via main()).
# ---------------------------------------------------------------------------


def test_TV_CLI_01_main_writes_outputs_and_returns_zero(
    tmp_path: Path,
) -> None:
    """main() round-trips a real Cargo.lock fixture to all outputs.

    The audit-timestamp defaults to 0.0 (no SOURCE_DATE_EPOCH set)
    so the JSON envelope is byte-stable across two invocations of
    main() on the same input.
    """
    lock_path = tmp_path / "Cargo.lock"
    lock_path.write_bytes(_SYNTHETIC_LOCK)
    out_json = tmp_path / "verdict.json"
    out_prom = tmp_path / "metrics.prom"
    out_md = tmp_path / "summary.md"
    out_notify = tmp_path / "mira-notify.json"

    # Force-clear SOURCE_DATE_EPOCH for determinism.
    old_sde = os.environ.pop("SOURCE_DATE_EPOCH", None)
    try:
        rc1 = vbr.main([
            "--cargo-lock", str(lock_path),
            "--out-json", str(out_json),
            "--out-textfile", str(out_prom),
            "--out-markdown", str(out_md),
            "--out-mira-notify", str(out_notify),
        ])
        assert rc1 == 0
        body1 = out_json.read_text()
        # Run a second time -- envelope must be byte-equal.
        rc2 = vbr.main([
            "--cargo-lock", str(lock_path),
            "--out-json", str(out_json),
            "--out-textfile", str(out_prom),
            "--out-markdown", str(out_md),
            "--out-mira-notify", str(out_notify),
        ])
        assert rc2 == 0
        body2 = out_json.read_text()
        assert body1 == body2
        # GREEN verdict -> notify file is zero bytes.
        assert out_notify.read_text() == ""
        # Prom textfile + Markdown were written.
        assert out_prom.exists()
        assert out_md.exists()
    finally:
        if old_sde is not None:
            os.environ["SOURCE_DATE_EPOCH"] = old_sde
