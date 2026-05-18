# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic Tag-45 manifest-integrity tests for the 0.5.0-pre-cutover engine.

These tests pin the byte-shape of the Tag-45 Persona-Engine
consolidation:

* `wirelang/persona_engine/MANIFEST-0.5.0-pre-cutover.md` — the
  human/machine manifest with the 9-component inventory, the
  ENV-flag schema, the 15-crate pin pack, and the boot diagram.
* `infra/persona-engine/pin-pack-0.5.0-pre-cutover.yaml` — the
  machine-readable counterpart.
* `infra/persona-engine/Containerfile.real` — the version bump to
  ``0.5.0-pre-cutover``.

Why this matters
----------------
The Phase-3a/3b Doppelbetrieb parity gate hashes a fingerprint of
the joint state — manifest + pin pack + Containerfile tag — and any
silent drift between the three sources would break the cutover.
The 15 hermetic tests below assert that the three sources agree on
every load-bearing field.

100% hermetic: no network, no subprocess, no Rust binary. Pure file
inspection + YAML parse.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

try:  # pragma: no cover — defensive import; yaml is in the runtime extra
    import yaml
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "PyYAML must be installed in the test environment; "
        "the 0.5.0-pre-cutover pin pack is a YAML file.",
    ) from exc

# ---------------------------------------------------------------------------
# Paths anchored from the repo root (this file lives at
# wirelang/tests/persona_engine/, so repo_root = parents[3]).
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = (
    REPO_ROOT
    / "wirelang"
    / "persona_engine"
    / "MANIFEST-0.5.0-pre-cutover.md"
)
PIN_PACK_PATH = (
    REPO_ROOT
    / "infra"
    / "persona-engine"
    / "pin-pack-0.5.0-pre-cutover.yaml"
)
CONTAINERFILE_PATH = (
    REPO_ROOT / "infra" / "persona-engine" / "Containerfile.real"
)
CRATES_ROOT = REPO_ROOT / "wirelang-rust" / "crates"

EXPECTED_IMAGE_TAG = "0.5.0-pre-cutover"

# The 9 boot-wired components in their canonical boot order.
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
]

# The 9 selector-ENV flags in the same boot order.
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
]

# The 6 additional substrates that ship parity-pinned but are not
# wired into the boot fan-out (Phase-3a oracles).
EXPECTED_UNWIRED_CRATES = [
    "persona-engine-bridge-audit-writer",
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
# 1. File-presence guard (3 files must exist).
# ---------------------------------------------------------------------------


def test_01_manifest_file_exists() -> None:
    assert MANIFEST_PATH.is_file(), (
        f"Tag-45 manifest missing at {MANIFEST_PATH}; cutover gate "
        "cannot hash an absent source."
    )


def test_02_pin_pack_file_exists() -> None:
    assert PIN_PACK_PATH.is_file(), (
        f"Tag-45 pin pack missing at {PIN_PACK_PATH}; "
        "cross-substrate-parity-gate workflow has no input."
    )


def test_03_containerfile_real_exists() -> None:
    assert CONTAINERFILE_PATH.is_file(), (
        f"Containerfile.real missing at {CONTAINERFILE_PATH}; "
        "image rotation impossible."
    )


# ---------------------------------------------------------------------------
# 2. Manifest content invariants.
# ---------------------------------------------------------------------------


def test_04_manifest_declares_image_tag(manifest_text: str) -> None:
    assert EXPECTED_IMAGE_TAG in manifest_text, (
        f"Manifest must self-identify with image tag "
        f"'{EXPECTED_IMAGE_TAG}' to align with Containerfile."
    )


def test_05_manifest_lists_all_nine_boot_crates(manifest_text: str) -> None:
    missing = [c for c in EXPECTED_BOOT_ORDER if c not in manifest_text]
    assert not missing, (
        f"Manifest §1 must reference all 9 boot-wired crates; "
        f"missing: {missing}"
    )


def test_06_manifest_lists_all_selector_envs(manifest_text: str) -> None:
    missing = [e for e in EXPECTED_SELECTOR_ENVS if e not in manifest_text]
    assert not missing, (
        f"Manifest §2.1 must reference all 9 WAKIR_*_BACKEND "
        f"selector ENVs; missing: {missing}"
    )


def test_07_manifest_lists_all_binary_envs(manifest_text: str) -> None:
    missing = [e for e in EXPECTED_BINARY_ENVS if e not in manifest_text]
    assert not missing, (
        f"Manifest §2.2 must reference all 9 WAKIR_RUST_*_BIN "
        f"path-override ENVs; missing: {missing}"
    )


def test_08_manifest_documents_timeout_knob(manifest_text: str) -> None:
    assert "WAKIR_RUST_BACKEND_TIMEOUT_S" in manifest_text, (
        "Manifest §2.3 must document the cross-backend timeout knob; "
        "operators need a single dial for slow CI lanes."
    )


def test_09_manifest_boot_order_is_canonical(manifest_text: str) -> None:
    """The 9 crates must appear in the manifest in the canonical
    boot order (record #1 → record #9). Reordering would invalidate
    the Doppelbetrieb boot-fingerprint."""

    positions = {
        crate: manifest_text.find(crate) for crate in EXPECTED_BOOT_ORDER
    }
    assert all(pos != -1 for pos in positions.values()), (
        "All boot-wired crates must be present in the manifest."
    )
    ordered = sorted(EXPECTED_BOOT_ORDER, key=lambda c: positions[c])
    assert ordered == EXPECTED_BOOT_ORDER, (
        f"Boot-order in manifest must be canonical (1→9); "
        f"got file-order: {ordered}"
    )


# ---------------------------------------------------------------------------
# 3. Pin-pack content invariants.
# ---------------------------------------------------------------------------


def test_10_pin_pack_manifest_version_matches(pin_pack: dict) -> None:
    assert pin_pack["manifest_version"] == EXPECTED_IMAGE_TAG, (
        f"Pin pack manifest_version must equal '{EXPECTED_IMAGE_TAG}'; "
        f"got {pin_pack['manifest_version']!r}"
    )


def test_11_pin_pack_wired_crate_count(pin_pack: dict) -> None:
    wired = pin_pack["boot_wired_crates"]
    assert len(wired) == 9, (
        f"Pin pack must list exactly 9 boot-wired crates; "
        f"got {len(wired)}"
    )


def test_12_pin_pack_wired_crate_order(pin_pack: dict) -> None:
    wired_names = [c["name"] for c in pin_pack["boot_wired_crates"]]
    assert wired_names == EXPECTED_BOOT_ORDER, (
        f"Pin pack boot_wired_crates order must match the canonical "
        f"boot order; got {wired_names}"
    )


def test_13_pin_pack_records_are_one_through_nine(pin_pack: dict) -> None:
    records = [c["record"] for c in pin_pack["boot_wired_crates"]]
    assert records == list(range(1, 10)), (
        f"Pin pack boot_wired_crates must declare records 1..9 in "
        f"order; got {records}"
    )


def test_14_pin_pack_all_versions_pinned_to_expected(pin_pack: dict) -> None:
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


def test_15_pin_pack_total_is_fifteen(pin_pack: dict) -> None:
    wired = pin_pack["boot_wired_crates"]
    unwired = pin_pack["boot_unwired_crates"]
    assert len(wired) + len(unwired) == 15, (
        f"Pin pack must total 15 Phase-3a crates "
        f"(9 wired + 6 unwired); got {len(wired) + len(unwired)}"
    )


def test_16_pin_pack_unwired_crates_match_expected(pin_pack: dict) -> None:
    unwired_names = {c["name"] for c in pin_pack["boot_unwired_crates"]}
    expected = set(EXPECTED_UNWIRED_CRATES)
    assert unwired_names == expected, (
        f"Pin pack unwired-crate set must equal the expected oracle "
        f"set; diff: {unwired_names ^ expected}"
    )


def test_17_pin_pack_selector_envs_consistent(pin_pack: dict) -> None:
    """Pin pack selector_env fields must match the canonical
    WAKIR_*_BACKEND naming used by rust_backend_switch.py."""
    for crate in pin_pack["boot_wired_crates"]:
        sel = crate["selector_env"]
        assert sel.startswith("WAKIR_") and sel.endswith("_BACKEND"), (
            f"Crate {crate['name']} selector_env {sel!r} must follow "
            "WAKIR_*_BACKEND convention."
        )


def test_18_pin_pack_invariants_block_matches_reality(pin_pack: dict) -> None:
    inv = pin_pack["invariants"]
    assert inv["total_wired_crates"] == 9
    assert inv["total_pin_pack_crates"] == 15
    assert inv["boot_record_count"] == 9
    assert inv["containerfile_image_tag"] == EXPECTED_IMAGE_TAG
    assert inv["manifest_present"].endswith(
        "MANIFEST-0.5.0-pre-cutover.md",
    )


# ---------------------------------------------------------------------------
# 4. Containerfile.real version bump.
# ---------------------------------------------------------------------------


def test_19_containerfile_image_version_bumped(
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


def test_20_containerfile_references_manifest(
    containerfile_text: str,
) -> None:
    assert "MANIFEST-0.5.0-pre-cutover.md" in containerfile_text, (
        "Containerfile.real must reference the Tag-45 manifest in "
        "its header comment for operator traceability."
    )


def test_21_containerfile_references_pin_pack(
    containerfile_text: str,
) -> None:
    assert "pin-pack-0.5.0-pre-cutover.yaml" in containerfile_text, (
        "Containerfile.real must reference the Tag-45 pin pack in "
        "its header comment for operator traceability."
    )


# ---------------------------------------------------------------------------
# 5. Cross-source consistency — the three artifacts must agree.
# ---------------------------------------------------------------------------


def test_22_pin_pack_crate_versions_match_cargo_toml(pin_pack: dict) -> None:
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
        "Pin-pack ↔ Cargo.toml version drift detected: "
        f"{failures}"
    )


def test_23_manifest_and_pin_pack_share_image_tag(
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
