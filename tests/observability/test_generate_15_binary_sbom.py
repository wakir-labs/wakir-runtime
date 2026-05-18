#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for
``scripts/observability/generate-15-binary-sbom.py``.

Tag-48 Kai — 15-Binary SBOM generator.

Coverage targets the pure-function core (no live cargo / network).
The tests in this file cover:

  * 3 Cargo.lock parser invariants (TV-PL-01..TV-PL-03)
  * 4 transitive-closure invariants (TV-TC-01..TV-TC-04)
  * 3 CycloneDX-1.5 rendering invariants (TV-CDX-01..TV-CDX-03)
  * 2 SPDX-2.3 rendering invariants (TV-SPDX-01..TV-SPDX-02)
  * 2 bundle-shape invariants (TV-BU-01..TV-BU-02)
  * 2 Prometheus-textfile + Markdown invariants (TV-RD-01..TV-RD-02)
  * 1 determinism invariant (TV-DT-01)
  * 1 substrate-anchor invariant (TV-AN-01)

Total: 18 hermetic invariants — comfortably above the >=12 target.

Sandbox boundary
----------------

Per ``feedback_sandbox_host_trennung.md`` + ADR-0051 these tests
NEVER call cargo / cosign / podman / network. They construct
synthetic Cargo.lock-shaped fixtures inline and assert the
expected SBOM shape, PURL encoding, and dependency graph.

Author: Kai Hoffmann (Dev-Engineering-3)
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Loader: import the generator module from its hyphenated path.
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
_GEN_PATH = (
    _REPO_ROOT
    / "scripts"
    / "observability"
    / "generate-15-binary-sbom.py"
)

_spec = importlib.util.spec_from_file_location(
    "generate_15_binary_sbom", str(_GEN_PATH)
)
assert _spec is not None
assert _spec.loader is not None
gen = importlib.util.module_from_spec(_spec)
sys.modules["generate_15_binary_sbom"] = gen
_spec.loader.exec_module(gen)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Synthetic Cargo.lock fixture (small, deterministic).
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
name = "persona-engine-fsm"
version = "0.1.0"
dependencies = [
 "cfg-if",
 "serde_json",
]

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
 "serde_json",
]

[[package]]
name = "persona-engine-anchor-emitter"
version = "0.1.0"
dependencies = [
 "serde_json",
]

[[package]]
name = "persona-engine-svid-workload-identity"
version = "0.1.0"
dependencies = [
 "serde_json",
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
dependencies = [
 "serde_json",
]

[[package]]
name = "serde_json"
version = "1.0.140"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "20068b6e96dc6c9bd23e01df8827e6c7e1f2fddd43c21810382803c136b99373"
dependencies = [
 "cfg-if",
]
"""


@pytest.fixture
def synthetic_packages():
    """Return the parsed CratePackage tuple for the synthetic lock."""
    return gen.parse_cargo_lock(_SYNTHETIC_LOCK)


# ---------------------------------------------------------------------------
# Cargo.lock parser invariants
# ---------------------------------------------------------------------------


def test_TV_PL_01_parser_reads_all_packages(synthetic_packages):
    """TV-PL-01: parser returns one CratePackage per [[package]] block.

    The synthetic fixture has 14 entries (2 crates.io deps + 12
    workspace crates). The parser must return exactly 14.
    """
    assert len(synthetic_packages) == 14


def test_TV_PL_02_parser_strips_dep_version_qualifiers(synthetic_packages):
    """TV-PL-02: dependency strings are reduced to bare package names."""
    by_name = {p.name: p for p in synthetic_packages}
    fsm = by_name["persona-engine-fsm"]
    assert "cfg-if" in fsm.dependencies
    assert "serde_json" in fsm.dependencies
    # No version qualifier survived the parser.
    for dep in fsm.dependencies:
        assert " " not in dep
        assert "(" not in dep


def test_TV_PL_03_parser_rejects_lockfile_without_packages():
    """TV-PL-03: parser errors loudly on malformed Cargo.lock."""
    with pytest.raises(ValueError, match="missing"):
        gen.parse_cargo_lock(b'version = 4\n')


# ---------------------------------------------------------------------------
# Transitive-closure invariants
# ---------------------------------------------------------------------------


def test_TV_TC_01_closure_includes_root_crate(synthetic_packages):
    """TV-TC-01: the transitive closure includes the root itself."""
    closure = gen.resolve_transitive_closure(
        "persona-engine-recovery", synthetic_packages
    )
    names = {p.name for p in closure}
    assert "persona-engine-recovery" in names


def test_TV_TC_02_closure_resolves_transitive_deps(synthetic_packages):
    """TV-TC-02: serde_json -> cfg-if edge is followed for fsm crate."""
    closure = gen.resolve_transitive_closure(
        "persona-engine-fsm", synthetic_packages
    )
    names = {p.name for p in closure}
    assert "serde_json" in names
    # cfg-if is reachable both directly (fsm depends on it) and
    # transitively (via serde_json). Either way, it must appear.
    assert "cfg-if" in names


def test_TV_TC_03_closure_deterministic_order(synthetic_packages):
    """TV-TC-03: same input -> identical closure order across runs."""
    closure_a = gen.resolve_transitive_closure(
        "persona-engine-fsm", synthetic_packages
    )
    closure_b = gen.resolve_transitive_closure(
        "persona-engine-fsm", synthetic_packages
    )
    assert tuple((p.name, p.version) for p in closure_a) == tuple(
        (p.name, p.version) for p in closure_b
    )


def test_TV_TC_04_closure_unknown_root_raises(synthetic_packages):
    """TV-TC-04: resolver errors loudly on unknown root crate."""
    with pytest.raises(ValueError, match="not found"):
        gen.resolve_transitive_closure(
            "does-not-exist", synthetic_packages
        )


# ---------------------------------------------------------------------------
# CycloneDX-1.5 rendering invariants
# ---------------------------------------------------------------------------


def test_TV_CDX_01_cyclonedx_top_level_fields(synthetic_packages):
    """TV-CDX-01: CycloneDX top-level fields match spec v1.5."""
    sbom = gen.build_binary_sbom(
        "fsm", "persona-engine-fsm", synthetic_packages
    )
    doc = gen.render_cyclonedx_sbom(sbom, 1_700_000_000.0, "deadbeef")
    assert doc["bomFormat"] == "CycloneDX"
    assert doc["specVersion"] == "1.5"
    assert doc["version"] == 1
    assert doc["serialNumber"].startswith("urn:uuid:")
    assert "metadata" in doc
    assert "components" in doc
    assert "dependencies" in doc


def test_TV_CDX_02_cyclonedx_component_purls(synthetic_packages):
    """TV-CDX-02: every CycloneDX component has a valid PURL.

    Crates.io components: ``pkg:cargo/<name>@<version>``.
    Workspace-local components: same prefix but with
    ``?source=workspace`` qualifier.
    """
    sbom = gen.build_binary_sbom(
        "fsm", "persona-engine-fsm", synthetic_packages
    )
    doc = gen.render_cyclonedx_sbom(sbom, 1_700_000_000.0, "deadbeef")
    components = doc["components"]
    for comp in components:
        purl = comp["purl"]
        assert purl.startswith("pkg:cargo/"), purl
        # crates.io entries carry a sha256 hash slot.
        if "?source=workspace" not in purl:
            assert "hashes" in comp


def test_TV_CDX_03_cyclonedx_dependency_graph_is_closed(synthetic_packages):
    """TV-CDX-03: every dependsOn ref appears as a component bom-ref."""
    sbom = gen.build_binary_sbom(
        "fsm", "persona-engine-fsm", synthetic_packages
    )
    doc = gen.render_cyclonedx_sbom(sbom, 1_700_000_000.0, "deadbeef")
    component_refs = {c["bom-ref"] for c in doc["components"]}
    for dep in doc["dependencies"]:
        for ref in dep["dependsOn"]:
            assert ref in component_refs, (
                f"dependsOn ref {ref!r} missing from components"
            )


# ---------------------------------------------------------------------------
# SPDX-2.3 rendering invariants
# ---------------------------------------------------------------------------


def test_TV_SPDX_01_spdx_top_level_fields(synthetic_packages):
    """TV-SPDX-01: SPDX top-level fields match spec v2.3."""
    sbom = gen.build_binary_sbom(
        "fsm", "persona-engine-fsm", synthetic_packages
    )
    doc = gen.render_spdx_sbom(sbom, 1_700_000_000.0, "deadbeef")
    assert doc["spdxVersion"] == "SPDX-2.3"
    assert doc["dataLicense"] == "CC0-1.0"
    assert doc["SPDXID"] == "SPDXRef-DOCUMENT"
    assert "packages" in doc
    assert "relationships" in doc
    assert "documentDescribes" in doc
    # Every package SPDXID must be SPDX-conformant.
    for pkg in doc["packages"]:
        spdx_id = pkg["SPDXID"]
        assert spdx_id.startswith("SPDXRef-Package-")
        # No underscores per SPDX-ID-charset.
        assert "_" not in spdx_id


def test_TV_SPDX_02_spdx_describes_root(synthetic_packages):
    """TV-SPDX-02: the SPDX document DESCRIBES the root crate."""
    sbom = gen.build_binary_sbom(
        "recovery", "persona-engine-recovery", synthetic_packages
    )
    doc = gen.render_spdx_sbom(sbom, 1_700_000_000.0, "deadbeef")
    # documentDescribes must contain at least one SPDXRef for the
    # root crate.
    described = doc["documentDescribes"]
    assert any("persona-engine-recovery" in d for d in described)


# ---------------------------------------------------------------------------
# Bundle-shape invariants
# ---------------------------------------------------------------------------


def test_TV_BU_01_bundle_has_fifteen_binaries(synthetic_packages):
    """TV-BU-01: bundle contains one SBOM per Tag-45 binary name."""
    bundle = gen.build_full_bundle(
        packages=synthetic_packages,
        cargo_lock_sha256="deadbeef",
        generator_ts=1_700_000_000.0,
        sbom_format="cyclonedx-1.5",
    )
    assert len(bundle.per_binary) == 15
    # The order matches the canonical inventory.
    names = tuple(sbom.binary_name for sbom in bundle.per_binary)
    assert names == gen.TAG45_BINARY_INVENTORY


def test_TV_BU_02_bundle_resolves_each_binary_to_a_root_crate(
    synthetic_packages,
):
    """TV-BU-02: every binary resolves to a workspace crate root."""
    bundle = gen.build_full_bundle(
        packages=synthetic_packages,
        cargo_lock_sha256="deadbeef",
        generator_ts=1_700_000_000.0,
        sbom_format="cyclonedx-1.5",
    )
    workspace_names = {p.name for p in synthetic_packages}
    for sbom in bundle.per_binary:
        assert sbom.root_crate in workspace_names, sbom.root_crate
        assert len(sbom.transitive_packages) >= 1


# ---------------------------------------------------------------------------
# Prometheus-textfile + Markdown rendering invariants
# ---------------------------------------------------------------------------


def test_TV_RD_01_textfile_has_one_gauge_per_binary(synthetic_packages):
    """TV-RD-01: textfile output has 15 rows of per-binary gauge."""
    bundle = gen.build_full_bundle(
        packages=synthetic_packages,
        cargo_lock_sha256="deadbeef",
        generator_ts=1_700_000_000.0,
        sbom_format="cyclonedx-1.5",
    )
    text = gen.render_textfile_metrics(bundle)
    rows = [
        line for line in text.splitlines()
        if line.startswith("wakir_sbom_binary_transitive_packages{")
    ]
    assert len(rows) == 15
    # Run-timestamp gauge present once.
    assert "wakir_sbom_generator_run_timestamp_seconds " in text


def test_TV_RD_02_markdown_summary_lists_all_binaries(synthetic_packages):
    """TV-RD-02: markdown summary has a row per binary."""
    bundle = gen.build_full_bundle(
        packages=synthetic_packages,
        cargo_lock_sha256="deadbeef",
        generator_ts=1_700_000_000.0,
        sbom_format="cyclonedx-1.5",
    )
    md = gen.render_markdown_summary(bundle)
    for binary in gen.TAG45_BINARY_INVENTORY:
        assert f"`{binary}`" in md, binary


# ---------------------------------------------------------------------------
# Determinism invariant
# ---------------------------------------------------------------------------


def test_TV_DT_01_same_input_same_output(synthetic_packages):
    """TV-DT-01: same Cargo.lock + same ts -> byte-identical SBOM."""
    bundle_a = gen.build_full_bundle(
        packages=synthetic_packages,
        cargo_lock_sha256="deadbeef",
        generator_ts=1_700_000_000.0,
        sbom_format="cyclonedx-1.5",
    )
    bundle_b = gen.build_full_bundle(
        packages=synthetic_packages,
        cargo_lock_sha256="deadbeef",
        generator_ts=1_700_000_000.0,
        sbom_format="cyclonedx-1.5",
    )
    doc_a = gen.render_cyclonedx_sbom(
        bundle_a.per_binary[0], 1_700_000_000.0, "deadbeef"
    )
    doc_b = gen.render_cyclonedx_sbom(
        bundle_b.per_binary[0], 1_700_000_000.0, "deadbeef"
    )
    assert json.dumps(doc_a, sort_keys=True) == json.dumps(
        doc_b, sort_keys=True
    )


# ---------------------------------------------------------------------------
# Substrate-anchor invariant
# ---------------------------------------------------------------------------


def test_TV_AN_01_inventory_matches_cosign_policy():
    """TV-AN-01: TAG45_BINARY_INVENTORY matches cosign-policy YAML.

    Reads ``policies/cosign-policy-phase-3b.yaml`` from disk and
    extracts the ``- name:`` entries. Asserts byte-identical match
    against the generator's inventory constant — if the policy ever
    drifts, this test fires and the generator must be updated in
    lock-step (per Tag-45 cross-substrate parity contract).
    """
    policy_path = _REPO_ROOT / "policies" / "cosign-policy-phase-3b.yaml"
    text = policy_path.read_text(encoding="utf-8")
    # Naive parse to avoid pulling in pyyaml at test-time.
    names = []
    in_binaries = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "binaries:":
            in_binaries = True
            continue
        if in_binaries and stripped.startswith("- name:"):
            name = stripped.split(":", 1)[1].strip()
            names.append(name)
    assert tuple(names) == gen.TAG45_BINARY_INVENTORY, (
        f"cosign-policy inventory drift; "
        f"policy={names!r}, generator={gen.TAG45_BINARY_INVENTORY!r}"
    )
