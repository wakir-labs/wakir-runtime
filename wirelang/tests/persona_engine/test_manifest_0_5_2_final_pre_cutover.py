# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic Tag-52 manifest-integrity tests for the 0.5.2-final-pre-cutover engine.

These tests pin the byte-shape of the Tag-52 Pre-KW-24-Final
consolidation marker for the Persona-Engine. The 0.5.2-final-pre-cutover
release is a strict superset of 0.5.1-pre-cutover (Tag-48 PR #313)
with no new BackendDecision record, no flag rename, no flag-default
flip, and no crate-version bump. The bump is a manifest-and-metadata-
only consolidation marker that absorbs:

* Tag-48 PR #313 — bridge-audit-writer wire-in.
* Tag-50 PR #320 — v0.4.2 DRIFT-S4 reconciliation (Pin-Pack as SoT).
* Tag-51 PR #327 — 10-Decision-Engine-Resilience suite (36 tests).
* Tag-51 PR #329 — legacy WAKIR_PE_*_BACKEND migration-detector.

The three Tag-52 artefacts under test:

* ``wirelang/persona_engine/MANIFEST-0.5.2-final-pre-cutover.md`` —
  the human/machine manifest with §1 inventory, §2 ENV-flag schema,
  §3 15-crate pin pack table, §4 boot diagram, §5 backward-compat
  statement, §6 cutover checklist, §7 sources-absorbed table.
* ``infra/persona-engine/pin-pack-0.5.2-final-pre-cutover.yaml`` —
  the machine-readable counterpart.
* ``infra/persona-engine/Containerfile.real`` — the version bump
  to ``0.5.2-final-pre-cutover``.

Why this matters
----------------
The Phase-3a/3b Doppelbetrieb parity gate hashes a fingerprint of
the joint state — manifest + pin pack + Containerfile tag — and
any silent drift between the three sources would break the cutover.
The 0.5.2-final marker is the Pre-KW-24 anchor; the cutover-gate
hashes this manifest's fingerprint as the final pre-cutover commit.

100% hermetic: no network, no subprocess, no Rust binary. Pure
file inspection + YAML parse.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip(
    "yaml",
    reason="PyYAML not available in this lane; pin-pack tests skipped.",
)

# ---------------------------------------------------------------------------
# Paths anchored from the repo root (this file lives at
# wirelang/tests/persona_engine/, so repo_root = parents[3]).
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = (
    REPO_ROOT
    / "wirelang"
    / "persona_engine"
    / "MANIFEST-0.5.2-final-pre-cutover.md"
)
PIN_PACK_PATH = (
    REPO_ROOT
    / "infra"
    / "persona-engine"
    / "pin-pack-0.5.2-final-pre-cutover.yaml"
)
CONTAINERFILE_PATH = (
    REPO_ROOT / "infra" / "persona-engine" / "Containerfile.real"
)
CRATES_ROOT = REPO_ROOT / "wirelang-rust" / "crates"

# Historical anchors that must still exist on-disk (Tag-48 + Tag-45).
HISTORICAL_MANIFEST_051 = (
    REPO_ROOT
    / "wirelang"
    / "persona_engine"
    / "MANIFEST-0.5.1-pre-cutover.md"
)
HISTORICAL_PIN_PACK_051 = (
    REPO_ROOT
    / "infra"
    / "persona-engine"
    / "pin-pack-0.5.1-pre-cutover.yaml"
)

EXPECTED_IMAGE_TAG = "0.5.2-final-pre-cutover"
PREDECESSOR_IMAGE_TAG = "0.5.1-pre-cutover"

# The 10 boot-wired components in their canonical boot order
# (byte-stable vs. 0.5.1-pre-cutover).
EXPECTED_BOOT_ORDER = [
    "persona-engine-recovery",
    "persona-engine-state-backing",
    "persona-engine-fsm",
    "persona-engine-v907-verify",
    "persona-engine-bridge-diff",
    "persona-engine-subscribe-loop",
    "persona-engine-anchor-emitter",
    "persona-engine-svid-workload-identity",
    "persona-engine-federation-resolver",
    "persona-engine-bridge-audit-writer",
]

# The 10 selector-ENV flags in the same boot order.
EXPECTED_SELECTOR_ENVS = [
    "WAKIR_RECOVERY_BACKEND",
    "WAKIR_STATE_BACKING_BACKEND",
    "WAKIR_FSM_BACKEND",
    "WAKIR_V907_VERIFY_BACKEND",
    "WAKIR_BRIDGE_DIFF_BACKEND",
    "WAKIR_SUBSCRIBE_LOOP_BACKEND",
    "WAKIR_ANCHOR_EMITTER_BACKEND",
    "WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND",
    "WAKIR_FEDERATION_RESOLVER_BACKEND",
    "WAKIR_BRIDGE_AUDIT_WRITER_BACKEND",
]

EXPECTED_BINARY_ENVS = [
    "WAKIR_RUST_RECOVERY_BIN",
    "WAKIR_RUST_STATE_BACKING_BIN",
    "WAKIR_RUST_FSM_BIN",
    "WAKIR_RUST_V907_VERIFY_BIN",
    "WAKIR_RUST_BRIDGE_DIFF_BIN",
    "WAKIR_RUST_SUBSCRIBE_LOOP_BIN",
    "WAKIR_RUST_ANCHOR_EMITTER_BIN",
    "WAKIR_RUST_SVID_WORKLOAD_IDENTITY_BIN",
    "WAKIR_RUST_FEDERATION_RESOLVER_BIN",
    "WAKIR_RUST_BRIDGE_AUDIT_WRITER_BIN",
]

# The 5 additional substrates that ship parity-pinned but are not
# wired into the boot fan-out (Phase-3a oracles).
EXPECTED_UNWIRED_CRATES = [
    "persona-engine-bridge-audit-replay",
    "persona-engine-anchor-submit-worker",
    "persona-engine-frontmatter-parser",
    "persona-engine-bridge-forward",
    "persona-engine-federation-frame-parser",
]

EXPECTED_PIN_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# Module-scope cached loaders so each test pays the parse cost once.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def manifest_text() -> str:
    return MANIFEST_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pin_pack() -> dict:
    return yaml.safe_load(PIN_PACK_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def containerfile_text() -> str:
    return CONTAINERFILE_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. File-presence guard (3 new files + 2 historical anchors).
# ---------------------------------------------------------------------------


def test_01_manifest_file_exists() -> None:
    assert MANIFEST_PATH.is_file(), (
        f"Tag-52 manifest missing at {MANIFEST_PATH}; Pre-KW-24 "
        "cutover gate cannot hash an absent source."
    )


def test_02_pin_pack_file_exists() -> None:
    assert PIN_PACK_PATH.is_file(), (
        f"Tag-52 pin pack missing at {PIN_PACK_PATH}; "
        "cross-substrate-parity-gate workflow has no input."
    )


def test_03_containerfile_real_exists() -> None:
    assert CONTAINERFILE_PATH.is_file(), (
        f"Containerfile.real missing at {CONTAINERFILE_PATH}; "
        "image rotation impossible."
    )


def test_04_historical_anchors_still_present() -> None:
    """0.5.2-final does not delete the 0.5.1-pre-cutover artefacts;
    they stay on-disk as the Doppelbetrieb regression-comparison
    baseline."""
    assert HISTORICAL_MANIFEST_051.is_file(), (
        "Tag-48 0.5.1-pre-cutover manifest must remain on-disk as "
        "the regression-comparison baseline for the Doppelbetrieb gate."
    )
    assert HISTORICAL_PIN_PACK_051.is_file(), (
        "Tag-48 0.5.1-pre-cutover pin-pack must remain on-disk as "
        "the regression-comparison baseline for the Doppelbetrieb gate."
    )


# ---------------------------------------------------------------------------
# 2. Manifest content invariants.
# ---------------------------------------------------------------------------


def test_05_manifest_declares_image_tag(manifest_text: str) -> None:
    assert EXPECTED_IMAGE_TAG in manifest_text, (
        f"Manifest must self-identify with image tag "
        f"'{EXPECTED_IMAGE_TAG}' to align with Containerfile."
    )


def test_06_manifest_lists_all_ten_boot_crates(manifest_text: str) -> None:
    missing = [c for c in EXPECTED_BOOT_ORDER if c not in manifest_text]
    assert not missing, (
        f"Manifest §1 must reference all 10 boot-wired crates; "
        f"missing: {missing}"
    )


def test_07_manifest_lists_all_selector_envs(manifest_text: str) -> None:
    missing = [e for e in EXPECTED_SELECTOR_ENVS if e not in manifest_text]
    assert not missing, (
        f"Manifest §2.1 must reference all 10 WAKIR_*_BACKEND "
        f"selector ENVs; missing: {missing}"
    )


def test_08_manifest_lists_all_binary_envs(manifest_text: str) -> None:
    missing = [e for e in EXPECTED_BINARY_ENVS if e not in manifest_text]
    assert not missing, (
        f"Manifest §2.2 must reference all 10 WAKIR_RUST_*_BIN "
        f"path-override ENVs; missing: {missing}"
    )


def test_09_manifest_documents_timeout_knob(manifest_text: str) -> None:
    assert "WAKIR_RUST_BACKEND_TIMEOUT_S" in manifest_text, (
        "Manifest §2.3 must document the cross-backend timeout knob; "
        "operators need a single dial for slow CI lanes."
    )


def test_10_manifest_boot_order_is_canonical(manifest_text: str) -> None:
    """The 10 crates must appear in the manifest in the canonical
    boot order (record #1 → record #10). Reordering would invalidate
    the Doppelbetrieb boot-fingerprint."""
    positions = {
        crate: manifest_text.find(crate) for crate in EXPECTED_BOOT_ORDER
    }
    assert all(pos != -1 for pos in positions.values()), (
        "All boot-wired crates must be present in the manifest."
    )
    ordered = sorted(EXPECTED_BOOT_ORDER, key=lambda c: positions[c])
    assert ordered == EXPECTED_BOOT_ORDER, (
        f"Boot-order in manifest must be canonical (1->10); "
        f"got file-order: {ordered}"
    )


def test_11_manifest_documents_predecessor(manifest_text: str) -> None:
    """The Tag-52 manifest must explicitly declare 0.5.1-pre-cutover
    as its predecessor and itself as a strict superset."""
    assert PREDECESSOR_IMAGE_TAG in manifest_text, (
        "Manifest must reference 0.5.1-pre-cutover predecessor for "
        "the byte-stability claim trail."
    )
    assert "strict superset" in manifest_text.lower(), (
        "Manifest must declare strict-superset relationship "
        "vs. 0.5.1-pre-cutover."
    )


def test_12_manifest_documents_tag48_50_51_absorption(
    manifest_text: str,
) -> None:
    """The Tag-52 manifest §7 must cite the four absorbed sources by
    Tag + PR number for traceability."""
    expected_refs = [
        "Tag-48",
        "Tag-50",
        "Tag-51",
        "DRIFT-S4",
        "10-Decision-Engine-Resilience",
    ]
    missing = [r for r in expected_refs if r not in manifest_text]
    assert not missing, (
        f"Manifest §7 must absorb Tag-48 + Tag-50 + Tag-51 + DRIFT-S4 "
        f"+ Resilience by reference; missing refs: {missing}"
    )


def test_13_manifest_documents_legacy_env_detection(
    manifest_text: str,
) -> None:
    """The Tag-52 manifest §2.5 must reference the Tag-51 Reza
    legacy-ENV-migration-detector hook (PR #329)."""
    assert "WAKIR_PE_" in manifest_text, (
        "Manifest §2.5 must reference the legacy WAKIR_PE_*_BACKEND "
        "naming so the migration-detector hook is traceable."
    )
    assert "legacy_env_migration_detector" in manifest_text or "legacy" in manifest_text.lower(), (
        "Manifest must reference the legacy-ENV detector hook."
    )


# ---------------------------------------------------------------------------
# 3. Pin-pack content invariants.
# ---------------------------------------------------------------------------


def test_14_pin_pack_manifest_version_matches(pin_pack: dict) -> None:
    assert pin_pack["manifest_version"] == EXPECTED_IMAGE_TAG, (
        f"Pin pack manifest_version must equal '{EXPECTED_IMAGE_TAG}'; "
        f"got {pin_pack['manifest_version']!r}"
    )


def test_15_pin_pack_supersedes_field(pin_pack: dict) -> None:
    """The Tag-52 pin-pack must explicitly declare 0.5.1-pre-cutover
    as its predecessor via the `supersedes` field."""
    assert pin_pack.get("supersedes") == PREDECESSOR_IMAGE_TAG, (
        f"Pin pack must declare supersedes='{PREDECESSOR_IMAGE_TAG}'; "
        f"got {pin_pack.get('supersedes')!r}"
    )


def test_16_pin_pack_consolidation_marker(pin_pack: dict) -> None:
    """The Tag-52 pin-pack must self-identify as the Pre-KW-24-Final
    consolidation marker."""
    assert pin_pack.get("consolidation_marker") == "pre-kw-24-final", (
        "Pin pack must declare consolidation_marker='pre-kw-24-final'."
    )


def test_17_pin_pack_strict_superset_field(pin_pack: dict) -> None:
    """The Tag-52 pin-pack must declare the strict-superset
    relationship for cutover-gate machine-readability."""
    assert pin_pack.get("strict_superset_of") == PREDECESSOR_IMAGE_TAG, (
        f"Pin pack must declare strict_superset_of="
        f"'{PREDECESSOR_IMAGE_TAG}'; got {pin_pack.get('strict_superset_of')!r}"
    )


def test_18_pin_pack_wired_crate_count(pin_pack: dict) -> None:
    wired = pin_pack["boot_wired_crates"]
    assert len(wired) == 10, (
        f"Pin pack must list exactly 10 boot-wired crates "
        f"(byte-stable vs. 0.5.1); got {len(wired)}"
    )


def test_19_pin_pack_wired_crate_order(pin_pack: dict) -> None:
    wired_names = [c["name"] for c in pin_pack["boot_wired_crates"]]
    assert wired_names == EXPECTED_BOOT_ORDER, (
        f"Pin pack boot_wired_crates order must match the canonical "
        f"boot order; got {wired_names}"
    )


def test_20_pin_pack_records_are_one_through_ten(pin_pack: dict) -> None:
    records = [c["record"] for c in pin_pack["boot_wired_crates"]]
    assert records == list(range(1, 11)), (
        f"Pin pack boot_wired_crates must declare records 1..10 in "
        f"order; got {records}"
    )


def test_21_pin_pack_all_versions_pinned_to_expected(pin_pack: dict) -> None:
    bad = [
        (c["name"], c["version"])
        for c in pin_pack["boot_wired_crates"]
        + pin_pack["boot_unwired_crates"]
        if c["version"] != EXPECTED_PIN_VERSION
    ]
    assert not bad, (
        f"Every crate in the pin pack must be pinned to "
        f"{EXPECTED_PIN_VERSION}; deviations: {bad}"
    )


def test_22_pin_pack_total_is_fifteen(pin_pack: dict) -> None:
    wired = pin_pack["boot_wired_crates"]
    unwired = pin_pack["boot_unwired_crates"]
    assert len(wired) + len(unwired) == 15, (
        f"Pin pack must total 15 Phase-3a crates "
        f"(10 wired + 5 unwired); got {len(wired) + len(unwired)}"
    )


def test_23_pin_pack_unwired_crates_match_expected(pin_pack: dict) -> None:
    unwired_names = {c["name"] for c in pin_pack["boot_unwired_crates"]}
    expected = set(EXPECTED_UNWIRED_CRATES)
    assert unwired_names == expected, (
        f"Pin pack unwired-crate set must equal the expected oracle "
        f"set; diff: {unwired_names ^ expected}"
    )


def test_24_pin_pack_selector_envs_consistent(pin_pack: dict) -> None:
    """Pin pack selector_env fields must match the canonical
    WAKIR_*_BACKEND naming used by rust_backend_switch.py."""
    for crate in pin_pack["boot_wired_crates"]:
        sel = crate["selector_env"]
        assert sel.startswith("WAKIR_") and sel.endswith("_BACKEND"), (
            f"Crate {crate['name']} selector_env {sel!r} must follow "
            "WAKIR_*_BACKEND convention."
        )
        # Tag-50 DRIFT-S4 invariant: no _PE_ infix.
        assert "WAKIR_PE_" not in sel, (
            f"Crate {crate['name']} selector_env {sel!r} must NOT use "
            "the legacy WAKIR_PE_*_BACKEND prefix (Tag-50 DRIFT-S4)."
        )


def test_25_pin_pack_resilience_contract_pinned(pin_pack: dict) -> None:
    """The Tag-52 pin-pack must reference the Tag-51 resilience
    contract by file path + test count."""
    rc = pin_pack.get("resilience_contract")
    assert rc, "Pin pack must declare resilience_contract block."
    assert "test_tag51_10_decision_engine_resilience" in rc.get(
        "pinned_test_module", ""
    ), "Resilience contract must pin Tag-51 PR #327 test module."
    assert rc.get("pinned_test_count") == 36, (
        "Resilience contract must pin the 36-test count from Tag-51 PR #327."
    )


def test_26_pin_pack_spec_sot_pinned(pin_pack: dict) -> None:
    """The Tag-52 pin-pack must reference the Tag-50 spec-v0.4.2 §4.1
    source-of-truth invariant."""
    sot = pin_pack.get("spec_source_of_truth")
    assert sot, "Pin pack must declare spec_source_of_truth block."
    assert sot.get("drift_id") == "DRIFT-S4", (
        "spec_source_of_truth must reference DRIFT-S4 (Tag-50)."
    )
    assert sot.get("section") == "4.1", (
        "spec_source_of_truth must reference spec §4.1."
    )
    assert "v0-4-2" in sot.get("spec_file", "") or "v0.4.2" in sot.get(
        "spec_file", ""
    ), "spec_source_of_truth must reference spec v0.4.2."


def test_27_pin_pack_legacy_env_detection_block(pin_pack: dict) -> None:
    """The Tag-52 pin-pack must reference the Tag-51 Reza legacy-ENV
    detection hook (PR #329)."""
    led = pin_pack.get("legacy_env_detection")
    assert led, "Pin pack must declare legacy_env_detection block."
    assert led.get("legacy_prefix") == "WAKIR_PE_", (
        "legacy_env_detection must pin the legacy WAKIR_PE_ prefix."
    )
    assert led.get("canonical_prefix") == "WAKIR_", (
        "legacy_env_detection must pin the canonical WAKIR_ prefix."
    )
    assert led.get("behaviour") == "warn-no-fallback", (
        "legacy_env_detection must declare warn-no-fallback posture."
    )


def test_28_pin_pack_invariants_block_matches_reality(pin_pack: dict) -> None:
    inv = pin_pack["invariants"]
    assert inv["total_wired_crates"] == 10
    assert inv["total_pin_pack_crates"] == 15
    assert inv["boot_record_count"] == 10
    assert inv["containerfile_image_tag"] == EXPECTED_IMAGE_TAG
    assert inv["manifest_present"].endswith(
        "MANIFEST-0.5.2-final-pre-cutover.md",
    )
    assert inv.get("byte_stable_versus") == PREDECESSOR_IMAGE_TAG, (
        "Pin pack invariants must declare byte-stability anchor."
    )


# ---------------------------------------------------------------------------
# 4. Containerfile.real version bump.
# ---------------------------------------------------------------------------


def test_29_containerfile_image_version_bumped(
    containerfile_text: str,
) -> None:
    pattern = re.compile(
        r'LABEL\s+org\.opencontainers\.image\.version="([^"]+)"'
    )
    match = pattern.search(containerfile_text)
    assert match, "Containerfile.real must declare image.version label."
    assert match.group(1) == EXPECTED_IMAGE_TAG, (
        f"Containerfile.real image.version must be "
        f"'{EXPECTED_IMAGE_TAG}'; got {match.group(1)!r}"
    )


def test_30_containerfile_references_manifest(
    containerfile_text: str,
) -> None:
    assert "MANIFEST-0.5.2-final-pre-cutover.md" in containerfile_text, (
        "Containerfile.real must reference the Tag-52 manifest in "
        "its header comment / description for operator traceability."
    )


def test_31_containerfile_references_pin_pack(
    containerfile_text: str,
) -> None:
    assert "pin-pack-0.5.2-final-pre-cutover.yaml" in containerfile_text, (
        "Containerfile.real must reference the Tag-52 pin pack in "
        "its header comment / description for operator traceability."
    )


# ---------------------------------------------------------------------------
# 5. Cross-source consistency — the three artifacts must agree.
# ---------------------------------------------------------------------------


def test_32_pin_pack_crate_versions_match_cargo_toml(pin_pack: dict) -> None:
    """Every crate version pinned in the YAML must equal the version
    declared in the crate's Cargo.toml. Drift here would mean the
    pin pack lies — a worst-case parity-gate failure mode."""
    version_re = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)
    failures: list[tuple[str, str, str]] = []
    for crate in (
        pin_pack["boot_wired_crates"] + pin_pack["boot_unwired_crates"]
    ):
        cargo = CRATES_ROOT / crate["name"] / "Cargo.toml"
        assert cargo.is_file(), (
            f"Pin pack references crate {crate['name']!r} but its "
            f"Cargo.toml does not exist at {cargo}."
        )
        m = version_re.search(cargo.read_text(encoding="utf-8"))
        assert m, f"Cargo.toml for {crate['name']} has no version field."
        on_disk = m.group(1)
        if on_disk != crate["version"]:
            failures.append((crate["name"], crate["version"], on_disk))
    assert not failures, (
        "Pin-pack <-> Cargo.toml version drift detected: "
        f"{failures}"
    )


def test_33_manifest_and_pin_pack_share_image_tag(
    manifest_text: str, pin_pack: dict, containerfile_text: str,
) -> None:
    """All three sources must agree on the image tag string."""
    assert EXPECTED_IMAGE_TAG in manifest_text
    assert pin_pack["manifest_version"] == EXPECTED_IMAGE_TAG
    assert pin_pack["invariants"]["containerfile_image_tag"] == EXPECTED_IMAGE_TAG
    pattern = re.compile(
        r'LABEL\s+org\.opencontainers\.image\.version="([^"]+)"'
    )
    match = pattern.search(containerfile_text)
    assert match and match.group(1) == EXPECTED_IMAGE_TAG, (
        "Containerfile image.version must match manifest + pin pack."
    )


def test_34_pin_pack_boot_wired_consistent_with_051(
    pin_pack: dict,
) -> None:
    """Strict-superset invariant: the 0.5.2-final pin-pack boot_wired
    crate-set + ordering must be byte-identical to the 0.5.1-pre-cutover
    pin-pack. Any deviation would falsify the strict-superset claim
    and break the Doppelbetrieb boot-fingerprint hash."""
    historical_yaml = yaml.safe_load(
        HISTORICAL_PIN_PACK_051.read_text(encoding="utf-8")
    )
    historical_wired = [
        (c["name"], c["record"], c["version"], c["selector_env"])
        for c in historical_yaml["boot_wired_crates"]
    ]
    current_wired = [
        (c["name"], c["record"], c["version"], c["selector_env"])
        for c in pin_pack["boot_wired_crates"]
    ]
    assert current_wired == historical_wired, (
        "Tag-52 boot_wired_crates must be byte-identical to Tag-48 "
        f"0.5.1-pre-cutover; diff detected:\n"
        f"current : {current_wired}\n"
        f"historical: {historical_wired}"
    )


def test_35_pin_pack_unwired_consistent_with_051(pin_pack: dict) -> None:
    """Strict-superset invariant for the unwired half of the pin set."""
    historical_yaml = yaml.safe_load(
        HISTORICAL_PIN_PACK_051.read_text(encoding="utf-8")
    )
    historical_unwired = {
        c["name"]: c["version"]
        for c in historical_yaml["boot_unwired_crates"]
    }
    current_unwired = {
        c["name"]: c["version"]
        for c in pin_pack["boot_unwired_crates"]
    }
    assert current_unwired == historical_unwired, (
        "Tag-52 boot_unwired_crates must be byte-identical to Tag-48; "
        f"diff: current={current_unwired}, historical={historical_unwired}"
    )


def test_36_containerfile_documents_tag52_consolidation(
    containerfile_text: str,
) -> None:
    """The Containerfile.real header must announce the Tag-52
    Pre-KW-24-Final consolidation marker for operator traceability."""
    assert "Tag-52" in containerfile_text, (
        "Containerfile.real header must reference Tag-52 for the "
        "consolidation-marker audit trail."
    )
    assert "Pre-KW-24" in containerfile_text or "KW-24" in containerfile_text or "kw 24" in containerfile_text.lower() or "kw-24" in containerfile_text.lower(), (
        "Containerfile.real header must reference the KW-24 cutover "
        "window for operator traceability."
    )
