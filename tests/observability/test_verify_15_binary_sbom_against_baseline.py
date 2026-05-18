#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for
``scripts/observability/verify-15-binary-sbom-against-baseline.py``.

Tag-49 Kai -- 15-Binary SBOM-vs-Baseline verifier.

Coverage targets the pure-function core (no live cargo / network).
The tests in this file cover:

  * 4 component-extraction + helper invariants (TV-EX-01..TV-EX-04)
  * 5 drift-computation invariants (TV-DR-01..TV-DR-05)
  * 3 per-binary verdict invariants (TV-PB-01..TV-PB-03)
  * 3 aggregate verdict invariants (TV-AG-01..TV-AG-03)
  * 2 rendering invariants (TV-RD-01..TV-RD-02)
  * 1 end-to-end CLI invariant (TV-CLI-01)

Total: 18 hermetic invariants -- comfortably above the >=12 target.

Sandbox boundary
----------------

Per ``feedback_sandbox_host_trennung.md`` + ADR-0051 these tests
NEVER call cargo / cosign / podman / network. They construct
synthetic per-binary SBOM dicts inline and assert the verifier's
drift classification, per-binary verdict, and aggregate verdict.

Author: Kai Hoffmann (Dev-Engineering-3)
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Loader: import the verifier module from its hyphenated path.
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
_VERIFIER_PATH = (
    _REPO_ROOT
    / "scripts"
    / "observability"
    / "verify-15-binary-sbom-against-baseline.py"
)

_spec = importlib.util.spec_from_file_location(
    "verify_15_binary_sbom_against_baseline", str(_VERIFIER_PATH)
)
assert _spec is not None
assert _spec.loader is not None
ver = importlib.util.module_from_spec(_spec)
sys.modules["verify_15_binary_sbom_against_baseline"] = ver
_spec.loader.exec_module(ver)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Synthetic SBOM fixture helpers
# ---------------------------------------------------------------------------


def _sbom(
    *,
    components: list[dict] | None = None,
    cargo_lock_sha256: str | None = "fixturelock0000000000000000000000000000000000000000000000000000",
) -> dict:
    """Build a minimal CycloneDX-1.5 SBOM dict for testing."""
    metadata: dict = {"properties": []}
    if cargo_lock_sha256 is not None:
        metadata["properties"].append(
            {"name": "wakir:cargo-lock-sha256", "value": cargo_lock_sha256}
        )
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "metadata": metadata,
        "components": components or [],
        "dependencies": [],
    }


def _comp(
    name: str,
    version: str,
    checksum: str | None = None,
) -> dict:
    out: dict = {
        "bom-ref": f"{name}@{version}",
        "name": name,
        "version": version,
    }
    if checksum is not None:
        out["hashes"] = [{"alg": "SHA-256", "content": checksum}]
    return out


# ===========================================================================
# Component-extraction + helper invariants (TV-EX-01..TV-EX-04)
# ===========================================================================


def test_TV_EX_01_extract_components_returns_sorted_triples():
    """TV-EX-01: components are returned sorted by (name, version)."""
    sbom = _sbom(
        components=[
            _comp("zlib", "1.0.0"),
            _comp("alpha", "0.2.0"),
            _comp("alpha", "0.1.0"),
        ]
    )
    triples = ver.extract_components_from_cyclonedx(sbom)
    names_versions = [(t.name, t.version) for t in triples]
    assert names_versions == [
        ("alpha", "0.1.0"),
        ("alpha", "0.2.0"),
        ("zlib", "1.0.0"),
    ]


def test_TV_EX_02_extract_components_picks_sha256_checksum():
    """TV-EX-02: SHA-256 ``hashes[]`` entry maps to ComponentTriple.checksum."""
    sbom = _sbom(
        components=[_comp("hex", "0.4.3", checksum="deadbeef" * 8)]
    )
    triples = ver.extract_components_from_cyclonedx(sbom)
    assert len(triples) == 1
    assert triples[0].checksum == "deadbeef" * 8


def test_TV_EX_03_extract_components_missing_array_raises():
    """TV-EX-03: an SBOM without ``components`` raises ValueError."""
    bad = {"bomFormat": "CycloneDX", "specVersion": "1.5"}
    with pytest.raises(ValueError):
        ver.extract_components_from_cyclonedx(bad)


def test_TV_EX_04_extract_cargo_lock_sha256_reads_property():
    """TV-EX-04: ``wakir:cargo-lock-sha256`` metadata property is read."""
    sbom = _sbom(cargo_lock_sha256="abc123")
    assert ver.extract_cargo_lock_sha256_from_cyclonedx(sbom) == "abc123"
    sbom_no_meta = _sbom(cargo_lock_sha256=None)
    assert ver.extract_cargo_lock_sha256_from_cyclonedx(sbom_no_meta) is None


# ===========================================================================
# Drift-computation invariants (TV-DR-01..TV-DR-05)
# ===========================================================================


def test_TV_DR_01_no_drift_returns_empty_tuple():
    """TV-DR-01: identical baseline + current -> zero drift entries."""
    base = ver.extract_components_from_cyclonedx(
        _sbom(components=[_comp("a", "1.0.0", "11" * 32)])
    )
    cur = ver.extract_components_from_cyclonedx(
        _sbom(components=[_comp("a", "1.0.0", "11" * 32)])
    )
    assert ver.compute_drift_entries(base, cur) == tuple()


def test_TV_DR_02_component_added_class():
    """TV-DR-02: new component in current produces ``component-added``."""
    base = ver.extract_components_from_cyclonedx(
        _sbom(components=[_comp("a", "1.0.0")])
    )
    cur = ver.extract_components_from_cyclonedx(
        _sbom(
            components=[_comp("a", "1.0.0"), _comp("new-crate", "0.1.0")]
        )
    )
    entries = ver.compute_drift_entries(base, cur)
    assert len(entries) == 1
    assert entries[0].drift_class == ver.DRIFT_COMPONENT_ADDED
    assert entries[0].component_name == "new-crate"
    assert entries[0].baseline_version is None
    assert entries[0].current_version == "0.1.0"


def test_TV_DR_03_component_removed_class():
    """TV-DR-03: missing component in current produces ``component-removed``."""
    base = ver.extract_components_from_cyclonedx(
        _sbom(
            components=[_comp("a", "1.0.0"), _comp("removed", "0.5.0")]
        )
    )
    cur = ver.extract_components_from_cyclonedx(
        _sbom(components=[_comp("a", "1.0.0")])
    )
    entries = ver.compute_drift_entries(base, cur)
    assert len(entries) == 1
    assert entries[0].drift_class == ver.DRIFT_COMPONENT_REMOVED
    assert entries[0].component_name == "removed"
    assert entries[0].baseline_version == "0.5.0"
    assert entries[0].current_version is None


def test_TV_DR_04_version_changed_class():
    """TV-DR-04: same name different version produces ``version-changed``."""
    base = ver.extract_components_from_cyclonedx(
        _sbom(components=[_comp("a", "1.0.0", "aa" * 32)])
    )
    cur = ver.extract_components_from_cyclonedx(
        _sbom(components=[_comp("a", "1.1.0", "bb" * 32)])
    )
    entries = ver.compute_drift_entries(base, cur)
    assert len(entries) == 1
    assert entries[0].drift_class == ver.DRIFT_VERSION_CHANGED
    assert entries[0].baseline_version == "1.0.0"
    assert entries[0].current_version == "1.1.0"


def test_TV_DR_05_checksum_changed_class_sorted_first():
    """TV-DR-05: same (name, version) different checksum -> ``checksum-changed``.

    Also asserts severity ordering: checksum-changed precedes
    version-changed precedes component-removed precedes component-added.
    """
    base = ver.extract_components_from_cyclonedx(
        _sbom(
            components=[
                _comp("checksum-drift", "1.0.0", "aa" * 32),
                _comp("removed", "1.0.0"),
                _comp("version-drift", "1.0.0"),
            ]
        )
    )
    cur = ver.extract_components_from_cyclonedx(
        _sbom(
            components=[
                _comp("added", "0.1.0"),
                _comp("checksum-drift", "1.0.0", "bb" * 32),
                _comp("version-drift", "1.1.0"),
            ]
        )
    )
    entries = ver.compute_drift_entries(base, cur)
    assert len(entries) == 4
    # Severity order: checksum-changed first, version-changed,
    # component-removed, component-added.
    assert entries[0].drift_class == ver.DRIFT_CHECKSUM_CHANGED
    assert entries[1].drift_class == ver.DRIFT_VERSION_CHANGED
    assert entries[2].drift_class == ver.DRIFT_COMPONENT_REMOVED
    assert entries[3].drift_class == ver.DRIFT_COMPONENT_ADDED


# ===========================================================================
# Per-binary verdict invariants (TV-PB-01..TV-PB-03)
# ===========================================================================


def test_TV_PB_01_per_binary_ok_when_identical():
    """TV-PB-01: identical baseline + current -> ``OK``."""
    sbom = _sbom(components=[_comp("a", "1.0.0", "aa" * 32)])
    pb = ver.verify_one_binary("recovery", sbom, sbom)
    assert pb.verdict == ver.BIN_OK
    assert pb.drift_count == 0
    assert pb.component_count_baseline == 1
    assert pb.component_count_current == 1


def test_TV_PB_02_per_binary_drift_red_on_checksum_change():
    """TV-PB-02: any checksum-changed -> per-binary ``DRIFT-RED``."""
    base = _sbom(components=[_comp("a", "1.0.0", "aa" * 32)])
    cur = _sbom(components=[_comp("a", "1.0.0", "bb" * 32)])
    pb = ver.verify_one_binary("recovery", cur, base)
    assert pb.verdict == ver.BIN_DRIFT_RED
    assert pb.drift_count == 1


def test_TV_PB_03_per_binary_missing_baseline_verdict():
    """TV-PB-03: missing baseline -> ``MISSING-BASELINE``.

    The current component-count is still extracted so the
    operator sees substrate health.
    """
    cur = _sbom(components=[_comp("a", "1.0.0")])
    pb = ver.verify_one_binary("recovery", cur, None)
    assert pb.verdict == ver.BIN_MISSING_BASELINE
    assert pb.component_count_baseline == 0
    assert pb.component_count_current == 1
    assert pb.drift_count == 0


# ===========================================================================
# Aggregate verdict invariants (TV-AG-01..TV-AG-03)
# ===========================================================================


def _make_per_binary(
    *,
    name: str,
    verdict: str,
    drift_count: int = 0,
    current_lock: str = "lock-sha",
) -> ver.PerBinaryVerdict:
    return ver.PerBinaryVerdict(
        binary_name=name,
        verdict=verdict,
        drift_count=drift_count,
        drift_entries=tuple(),
        baseline_cargo_lock_sha256="lock-sha",
        current_cargo_lock_sha256=current_lock,
        component_count_baseline=10,
        component_count_current=10,
    )


def test_TV_AG_01_aggregate_green_when_all_ok():
    """TV-AG-01: every binary OK -> aggregate GREEN."""
    pbs = tuple(
        _make_per_binary(name=f"b{i}", verdict=ver.BIN_OK) for i in range(15)
    )
    assert ver.compute_aggregate_verdict(pbs, "lock-sha") == ver.VERDICT_GREEN


def test_TV_AG_02_aggregate_yellow_when_any_yellow():
    """TV-AG-02: one binary YELLOW (no RED/MISSING) -> aggregate YELLOW."""
    pbs = list(
        _make_per_binary(name=f"b{i}", verdict=ver.BIN_OK) for i in range(14)
    )
    pbs.append(
        _make_per_binary(
            name="b14", verdict=ver.BIN_DRIFT_YELLOW, drift_count=2
        )
    )
    assert (
        ver.compute_aggregate_verdict(tuple(pbs), "lock-sha")
        == ver.VERDICT_YELLOW
    )


def test_TV_AG_03_aggregate_red_on_missing_or_red_or_lock_drift():
    """TV-AG-03: RED, MISSING-BASELINE, or per-binary lock-sha mismatch -> RED.

    Three sub-cases packaged into one invariant because they share
    the same RED-promotion rule.
    """
    # Sub-case 1: a single DRIFT-RED triggers RED.
    pbs_red = [
        _make_per_binary(name=f"b{i}", verdict=ver.BIN_OK) for i in range(14)
    ]
    pbs_red.append(
        _make_per_binary(name="b14", verdict=ver.BIN_DRIFT_RED, drift_count=1)
    )
    assert (
        ver.compute_aggregate_verdict(tuple(pbs_red), "lock-sha")
        == ver.VERDICT_RED
    )

    # Sub-case 2: a single MISSING-BASELINE triggers RED.
    pbs_missing = [
        _make_per_binary(name=f"b{i}", verdict=ver.BIN_OK) for i in range(14)
    ]
    pbs_missing.append(
        _make_per_binary(name="b14", verdict=ver.BIN_MISSING_BASELINE)
    )
    assert (
        ver.compute_aggregate_verdict(tuple(pbs_missing), "lock-sha")
        == ver.VERDICT_RED
    )

    # Sub-case 3: lock-sha mismatch on any binary triggers RED even
    # if every binary is otherwise OK.
    pbs_lock = [
        _make_per_binary(name=f"b{i}", verdict=ver.BIN_OK) for i in range(14)
    ]
    pbs_lock.append(
        _make_per_binary(
            name="b14", verdict=ver.BIN_OK, current_lock="OTHER-lock"
        )
    )
    assert (
        ver.compute_aggregate_verdict(tuple(pbs_lock), "lock-sha")
        == ver.VERDICT_RED
    )


# ===========================================================================
# Rendering invariants (TV-RD-01..TV-RD-02)
# ===========================================================================


def _make_aggregate(verdict: str) -> ver.AggregateVerdict:
    pbs = tuple(
        _make_per_binary(name=f"b{i}", verdict=ver.BIN_OK) for i in range(15)
    )
    return ver.AggregateVerdict(
        verdict=verdict,
        generator_ts=0.0,
        current_cargo_lock_sha256="lock-sha",
        per_binary=pbs,
        binaries_total=15,
        binaries_ok=15,
        binaries_yellow=0,
        binaries_red=0,
        binaries_missing=0,
    )


def test_TV_RD_01_textfile_emits_one_hot_aggregate_verdict():
    """TV-RD-01: aggregate verdict is rendered as one-hot Prometheus gauge."""
    agg = _make_aggregate(ver.VERDICT_GREEN)
    body = ver.render_textfile_metrics(agg)
    assert (
        'wakir_sbom_verification_aggregate_verdict{verdict="GREEN"} 1'
        in body
    )
    assert (
        'wakir_sbom_verification_aggregate_verdict{verdict="YELLOW"} 0'
        in body
    )
    assert (
        'wakir_sbom_verification_aggregate_verdict{verdict="RED"} 0'
        in body
    )


def test_TV_RD_02_markdown_contains_verdict_and_per_binary_table():
    """TV-RD-02: Markdown summary contains aggregate verdict + per-binary rows."""
    agg = _make_aggregate(ver.VERDICT_YELLOW)
    body = ver.render_markdown_summary(agg)
    assert "**Aggregate verdict:** `YELLOW`" in body
    assert "| Binary | Verdict | Drift count | Components |" in body
    # 15 per-binary rows present.
    for i in range(15):
        assert f"| `b{i}` |" in body


# ===========================================================================
# End-to-end CLI invariant (TV-CLI-01)
# ===========================================================================


def test_TV_CLI_01_cli_drives_full_pipeline_against_synthetic_dirs(tmp_path):
    """TV-CLI-01: full main() pipeline run with synthetic SBOM dirs.

    Exercises:
      * file-loading from disk,
      * verify_all_binaries,
      * aggregate verdict computation,
      * envelope JSON serialisation,
      * textfile + markdown rendering,
      * stdout digest line.

    Uses the real Tag-48 generator's TAG45_BINARY_INVENTORY by
    looking the constant up via the verifier's loader path. The
    test writes synthetic per-binary SBOMs covering every name in
    the inventory.
    """
    # Load the inventory the same way the verifier does.
    gen_path = (
        _REPO_ROOT
        / "scripts"
        / "observability"
        / "generate-15-binary-sbom.py"
    )
    gen = ver._load_generator_module(gen_path)
    inventory = gen.TAG45_BINARY_INVENTORY
    assert len(inventory) == 15

    sbom_dir = tmp_path / "sbom"
    baseline_dir = tmp_path / "baseline"
    sbom_dir.mkdir()
    baseline_dir.mkdir()

    # Write identical baseline + current for fourteen binaries (OK)
    # and a checksum-drift for one binary (DRIFT-RED -> aggregate RED).
    drift_binary = inventory[0]
    for name in inventory:
        base_components = [_comp("foo", "1.0.0", "aa" * 32)]
        if name == drift_binary:
            cur_components = [_comp("foo", "1.0.0", "bb" * 32)]
        else:
            cur_components = base_components
        base = _sbom(
            components=base_components,
            cargo_lock_sha256="lock-sha-baseline",
        )
        cur = _sbom(
            components=cur_components,
            cargo_lock_sha256="lock-sha-baseline",
        )
        (baseline_dir / f"{name}.json").write_text(json.dumps(base))
        (sbom_dir / f"{name}.cdx.json").write_text(json.dumps(cur))

    out_json = tmp_path / "envelope.json"
    out_textfile = tmp_path / "textfile.prom"
    out_markdown = tmp_path / "summary.md"

    rc = ver.main(
        [
            "--sbom-dir",
            str(sbom_dir),
            "--baseline-dir",
            str(baseline_dir),
            "--out-json",
            str(out_json),
            "--out-textfile",
            str(out_textfile),
            "--out-markdown",
            str(out_markdown),
            "--generator-ts",
            "0.0",
        ]
    )
    assert rc == 0

    envelope = json.loads(out_json.read_text())
    assert envelope["verdict"] == ver.VERDICT_RED  # checksum-drift -> RED
    assert envelope["binaries_total"] == 15
    assert envelope["binaries_red"] == 1
    assert envelope["binaries_ok"] == 14

    # First per-binary in the per_binary array is the drift binary
    # (the verifier preserves inventory order).
    pb0 = envelope["per_binary"][0]
    assert pb0["binary_name"] == drift_binary
    assert pb0["verdict"] == ver.BIN_DRIFT_RED
    assert pb0["drift_count"] == 1
    assert pb0["drift_entries"][0]["drift_class"] == (
        ver.DRIFT_CHECKSUM_CHANGED
    )

    # Textfile + markdown got written and contain the verdict.
    assert (
        'wakir_sbom_verification_aggregate_verdict{verdict="RED"} 1'
        in out_textfile.read_text()
    )
    assert "**Aggregate verdict:** `RED`" in out_markdown.read_text()


def test_TV_CLI_02_exit_non_zero_on_drift_flag_returns_1(tmp_path):
    """TV-CLI-02 (bonus): ``--exit-non-zero-on-drift`` exits 1 on non-GREEN.

    Bonus invariant beyond the >=12 target -- documents the workflow
    contract for the CI block-or-allow decision.
    """
    gen_path = (
        _REPO_ROOT
        / "scripts"
        / "observability"
        / "generate-15-binary-sbom.py"
    )
    gen = ver._load_generator_module(gen_path)
    inventory = gen.TAG45_BINARY_INVENTORY

    sbom_dir = tmp_path / "sbom"
    baseline_dir = tmp_path / "baseline"
    sbom_dir.mkdir()
    baseline_dir.mkdir()
    # Write current SBOMs but only ONE baseline -> aggregate RED
    # (14 MISSING-BASELINE entries).
    base = _sbom(
        components=[_comp("foo", "1.0.0")], cargo_lock_sha256="lock-sha"
    )
    cur = _sbom(
        components=[_comp("foo", "1.0.0")], cargo_lock_sha256="lock-sha"
    )
    for name in inventory:
        (sbom_dir / f"{name}.cdx.json").write_text(json.dumps(cur))
    (baseline_dir / f"{inventory[0]}.json").write_text(json.dumps(base))

    rc = ver.main(
        [
            "--sbom-dir",
            str(sbom_dir),
            "--baseline-dir",
            str(baseline_dir),
            "--exit-non-zero-on-drift",
            "--generator-ts",
            "0.0",
        ]
    )
    assert rc == 1


def test_TV_BL_01_baseline_state_dir_contains_15_files():
    """TV-BL-01: ``state/sbom-baseline/`` has fifteen baseline JSON files.

    Substrate invariant -- the Tag-49 baseline-freeze is captured.
    Without this guard a future deletion of one of the fifteen
    baselines silently regresses the substrate to MISSING-BASELINE.
    """
    baseline_dir = _REPO_ROOT / "state" / "sbom-baseline"
    files = sorted(p.name for p in baseline_dir.glob("*.json"))
    assert len(files) == 15
    # Each file is well-formed JSON with a ``components`` array.
    for f in files:
        sbom = json.loads((baseline_dir / f).read_text())
        assert "components" in sbom
        assert isinstance(sbom["components"], list)


def test_TV_BL_02_baseline_inventory_matches_tag45():
    """TV-BL-02: baseline filenames cover the Tag-45 15-binary inventory.

    Substrate invariant -- the baseline directory's filenames must
    match the inventory the verifier iterates. A mismatch surfaces
    as MISSING-BASELINE which is RED.
    """
    gen_path = (
        _REPO_ROOT
        / "scripts"
        / "observability"
        / "generate-15-binary-sbom.py"
    )
    gen = ver._load_generator_module(gen_path)
    inventory = set(gen.TAG45_BINARY_INVENTORY)
    baseline_dir = _REPO_ROOT / "state" / "sbom-baseline"
    file_names = {p.stem for p in baseline_dir.glob("*.json")}
    assert inventory == file_names
