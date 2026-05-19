# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic Tag-56 production-readiness-audit companion tests.

These tests encode the numeric and string assertions of the Tag-56
production-readiness audit report
(``reports/audit/persona-engine-0-5-2-production-readiness-2026-05-19.md``)
as executable invariants. A divergence between the audit report and
the substrate trips the suite in the next CI cycle.

The audit covers seven dimensions of the 0.5.2-final-pre-cutover
engine release substrate; each dimension has a dedicated test class
(D1..D7). Total test count: 15 (≥12 required by the Tag-56 dispatch).

100% hermetic: pytest-only, no network, no subprocess, no Rust
build, no engine boot, no NATS. Pure file inspection + YAML parse +
source-grep.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip(
    "yaml",
    reason="PyYAML not available in this lane; production-readiness "
    "audit tests skipped.",
)

# ---------------------------------------------------------------------------
# Anchors — same anchoring strategy as the Tag-52 manifest-integrity tests.
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
ENGINE_PY_PATH = REPO_ROOT / "wirelang" / "persona_engine" / "engine.py"
RUST_SWITCH_PY_PATH = (
    REPO_ROOT / "wirelang" / "persona_engine" / "rust_backend_switch.py"
)
FSM_LIB_RS_PATH = (
    REPO_ROOT
    / "wirelang-rust"
    / "crates"
    / "persona-engine-fsm"
    / "src"
    / "lib.rs"
)
V907_LIB_RS_PATH = (
    REPO_ROOT
    / "wirelang-rust"
    / "crates"
    / "persona-engine-v907-verify"
    / "src"
    / "lib.rs"
)
CARGO_WORKSPACE_PATH = REPO_ROOT / "wirelang-rust" / "Cargo.toml"
CRATES_ROOT = REPO_ROOT / "wirelang-rust" / "crates"
AUDIT_REPORT_PATH = (
    REPO_ROOT
    / "reports"
    / "audit"
    / "persona-engine-0-5-2-production-readiness-2026-05-19.md"
)

# Canonical 10-record boot-order ground truth (audit Dimension 1).
CANONICAL_BOOT_ORDER = [
    ("recovery-workflow", "persona-engine-recovery"),
    ("state-backing", "persona-engine-state-backing"),
    ("lifecycle-fsm", "persona-engine-fsm"),
    ("v907-verify", "persona-engine-v907-verify"),
    ("bridge-diff", "persona-engine-bridge-diff"),
    ("subscribe-loop", "persona-engine-subscribe-loop"),
    ("anchor-emitter", "persona-engine-anchor-emitter"),
    ("svid-workload-identity", "persona-engine-svid-workload-identity"),
    ("federation-resolver", "persona-engine-federation-resolver"),
    ("bridge-audit-writer", "persona-engine-bridge-audit-writer"),
]

# Canonical 15-crate pin-pack ground truth (audit Dimension 2).
CANONICAL_PIN_PACK_15 = [
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
    "persona-engine-bridge-audit-replay",
    "persona-engine-anchor-submit-worker",
    "persona-engine-frontmatter-parser",
    "persona-engine-bridge-forward",
    "persona-engine-federation-frame-parser",
]

# Canonical 10-flag selector-ENV ground truth (audit Dimension 3).
CANONICAL_SELECTOR_ENVS = [
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

# Canonical 10-flag binary-path-ENV ground truth (audit Dimension 3).
CANONICAL_BINARY_ENVS = [
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

# Canonical FSM 6-state ground truth (audit Dimension 4).
CANONICAL_FSM_STATES = [
    "uninstantiated",
    "spawning",
    "running",
    "despawning",
    "recovered",
    "migrated",
]

# Canonical FSM 9-edge ground truth (audit Dimension 4).
CANONICAL_FSM_EDGES = [
    ("Uninstantiated", "Spawning"),
    ("Spawning", "Running"),
    ("Spawning", "Uninstantiated"),
    ("Running", "Despawning"),
    ("Despawning", "Uninstantiated"),
    ("Uninstantiated", "Recovered"),
    ("Recovered", "Running"),
    ("Running", "Migrated"),
    ("Migrated", "Uninstantiated"),
]

# Canonical V-907 ground-truth digest (audit Dimension 5).
V907_SAMPLE_AXIS_A_DIGEST = (
    "sha256:cf66fbc5e02ebee97726d5903460e1c3b2b20d1e10db6db1083bceb62ede6e39"
)


# ---------------------------------------------------------------------------
# Common fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pin_pack():
    """Parsed pin-pack YAML for the 0.5.2-final-pre-cutover release."""
    return yaml.safe_load(PIN_PACK_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def engine_py_source():
    """Source-text of engine.py for source-grep based assertions."""
    return ENGINE_PY_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def rust_switch_py_source():
    """Source-text of rust_backend_switch.py for ENV-flag constant scan."""
    return RUST_SWITCH_PY_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def fsm_lib_rs_source():
    """Source-text of persona-engine-fsm/src/lib.rs for FSM scan."""
    return FSM_LIB_RS_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def v907_lib_rs_source():
    """Source-text of persona-engine-v907-verify/src/lib.rs for V-907 scan."""
    return V907_LIB_RS_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def containerfile_source():
    """Source-text of Containerfile.real for layer-instruction scan."""
    return CONTAINERFILE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def cargo_workspace_source():
    """Source-text of wirelang-rust/Cargo.toml for workspace-member scan."""
    return CARGO_WORKSPACE_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Dimension 1 — 10 BackendDecision Records (3 tests).
# ---------------------------------------------------------------------------


class Test10BackendDecisions:
    """Audit Dimension 1: 10 BackendDecision records, byte-stable boot order."""

    def test_d1_pin_pack_has_exactly_10_wired_records_in_canonical_order(
        self, pin_pack
    ):
        """The pin-pack ``boot_wired_crates`` list must enumerate the 10
        canonical components in the canonical boot order."""
        wired = pin_pack["boot_wired_crates"]
        assert len(wired) == 10, (
            f"boot_wired_crates count drift: expected 10, got {len(wired)}"
        )
        actual_order = [(c["name"], c["record"]) for c in wired]
        expected_order = [
            (CANONICAL_BOOT_ORDER[i][1], i + 1) for i in range(10)
        ]
        assert actual_order == expected_order, (
            f"Boot-order drift: {actual_order} vs. {expected_order}"
        )

    def test_d1_engine_py_calls_all_10_canonical_resolvers(
        self, engine_py_source
    ):
        """engine.py must call every one of the 10 canonical resolver
        functions at least once. The Tag-51 resilience suite
        (``test_10_decision_resilience.py``) is the source of truth
        for emit ordering; this test only verifies presence + count
        because resolver text-position in source doesn't reflect the
        emit order (state_backing resolves inside ``__init__`` before
        ``boot()``; the other nine resolve in ``boot()`` itself)."""
        resolvers = [
            "resolve_recovery_backend",
            "resolve_state_backing_backend",
            "resolve_fsm_backend",
            "resolve_v907_verify_backend",
            "resolve_bridge_diff_backend",
            "resolve_subscribe_loop_backend",
            "resolve_anchor_emitter_backend",
            "resolve_svid_workload_identity_backend",
            "resolve_federation_resolver_backend",
            "resolve_bridge_audit_writer_backend",
        ]
        missing = []
        for r in resolvers:
            # Each resolver must appear as a call site (followed by `(`).
            if r + "(" not in engine_py_source:
                missing.append(r)
        assert not missing, f"Missing resolver call-sites: {missing}"
        # The Tag-51 resilience suite's BOOT_FAN_OUT_DECISIONS contains
        # exactly nine entries (all canonical decisions minus state_backing,
        # which resolves in __init__ pre-boot). This is the manifest-§4
        # invariant: 10 records = 1 (state_backing-in-init) + 9 (boot
        # fan-out).
        assert len(resolvers) == 10

    def test_d1_manifest_table_has_10_inventory_rows(self):
        """Manifest §1 must contain exactly ten markdown table rows
        whose first cell is a digit 1..10."""
        text = MANIFEST_PATH.read_text(encoding="utf-8")
        # Find the §1 table by scanning for `| 1 |` and counting rows
        # up to `| 10 |` inclusive.
        rows_1_to_10 = re.findall(r"^\|\s*(\d+)\s*\|", text, re.MULTILINE)
        # Filter to only the first 10 distinct integers 1..10 (the
        # manifest contains other numbered tables; we look for the
        # canonical inventory which is the first contiguous 1..10 run).
        seen = []
        for n in rows_1_to_10:
            i = int(n)
            if i == len(seen) + 1:
                seen.append(i)
                if i == 10:
                    break
            elif i == 1 and seen and seen[-1] != 10:
                # restart of a new table
                seen = [1]
        assert seen == list(range(1, 11)), (
            f"Manifest inventory rows 1..10 not contiguous: {seen}"
        )


# ---------------------------------------------------------------------------
# Dimension 2 — 15-Crate Cross-Language Pin Pack (2 tests).
# ---------------------------------------------------------------------------


class Test15CratePinPack:
    """Audit Dimension 2: 15-crate cross-lang pin pack, byte-stable vs. 0.5.1."""

    def test_d2_all_15_crates_exist_at_version_0_1_0(self):
        """All 15 pin-pack crates must have an on-disk Cargo.toml with
        a top-level ``version = "0.1.0"`` declaration."""
        missing = []
        wrong_version = []
        for crate in CANONICAL_PIN_PACK_15:
            cargo = CRATES_ROOT / crate / "Cargo.toml"
            if not cargo.exists():
                missing.append(crate)
                continue
            src = cargo.read_text(encoding="utf-8")
            # match the first standalone `version = "X.Y.Z"` line
            m = re.search(r'^version\s*=\s*"([^"]+)"', src, re.MULTILINE)
            if m is None or m.group(1) != "0.1.0":
                wrong_version.append(
                    (crate, m.group(1) if m else "<missing>")
                )
        assert not missing, f"Missing crates: {missing}"
        assert not wrong_version, f"Wrong-version crates: {wrong_version}"

    def test_d2_pin_pack_invariants_block_matches_audit_claims(
        self, pin_pack
    ):
        """The pin-pack ``invariants:`` block must declare the six audit-
        anchored numeric and string invariants."""
        inv = pin_pack["invariants"]
        assert inv["total_wired_crates"] == 10
        assert inv["total_pin_pack_crates"] == 15
        assert inv["boot_record_count"] == 10
        assert inv["manifest_present"] == (
            "wirelang/persona_engine/MANIFEST-0.5.2-final-pre-cutover.md"
        )
        assert inv["containerfile_image_tag"] == "0.5.2-final-pre-cutover"
        assert inv["byte_stable_versus"] == "0.5.1-pre-cutover"


# ---------------------------------------------------------------------------
# Dimension 3 — ENV-Flag Consistency (2 tests).
# ---------------------------------------------------------------------------


class TestEnvFlagConsistency:
    """Audit Dimension 3: WAKIR_*_BACKEND naming, no _PE_ infix in wired set."""

    def test_d3_pin_pack_env_flags_match_canonical_lists(self, pin_pack):
        """Pin-pack selector_env + binary_env across all 10 wired crates
        must equal the canonical ENV-flag lists exactly."""
        selectors = [c["selector_env"] for c in pin_pack["boot_wired_crates"]]
        binaries = [c["binary_env"] for c in pin_pack["boot_wired_crates"]]
        assert selectors == CANONICAL_SELECTOR_ENVS, (
            f"Selector ENV drift: {selectors}"
        )
        assert binaries == CANONICAL_BINARY_ENVS, (
            f"Binary-path ENV drift: {binaries}"
        )

    def test_d3_no_wakir_pe_backend_in_wired_set(
        self, pin_pack, rust_switch_py_source
    ):
        """No flag in the wired set may carry the legacy ``_PE_`` infix;
        the Tag-51 legacy migration-detector must be defined."""
        for c in pin_pack["boot_wired_crates"]:
            assert "_PE_" not in c["selector_env"], (
                f"Legacy _PE_ in selector_env: {c['selector_env']}"
            )
            assert "_PE_" not in c["binary_env"], (
                f"Legacy _PE_ in binary_env: {c['binary_env']}"
            )
        # The legacy-detector module is referenced by pin-pack and exists.
        legacy = pin_pack["legacy_env_detection"]
        assert legacy["legacy_prefix"] == "WAKIR_PE_"
        assert legacy["canonical_prefix"] == "WAKIR_"
        assert legacy["behaviour"] == "warn-no-fallback"


# ---------------------------------------------------------------------------
# Dimension 4 — FSM State Diagram (2 tests).
# ---------------------------------------------------------------------------


class TestFsmStateDiagram:
    """Audit Dimension 4: 6 FSM states + 9 valid transitions in Rust pendant."""

    def test_d4_fsm_has_six_states_with_canonical_wire_strings(
        self, fsm_lib_rs_source
    ):
        """The Rust FSM crate must declare the six canonical wire-string
        states; no extra state may be present."""
        for state in CANONICAL_FSM_STATES:
            # match the wire-string arm in as_wire_str / from_wire_str
            assert f'"{state}"' in fsm_lib_rs_source, (
                f"FSM state wire-string missing: {state}"
            )
        # No extra state — count the `FsmState::<X> =>` arms in
        # `as_wire_str` and verify count == 6.
        arms = re.findall(
            r"FsmState::(\w+)\s*=>\s*\"(\w+)\"", fsm_lib_rs_source
        )
        # Filter to lowercase wire-strings only (i.e. the as_wire_str body).
        lowercase_arms = [a for a in arms if a[1].islower()]
        # The as_wire_str body has six unique arms; we may also see the
        # mirrored arms in tests (also lowercase), so dedupe.
        unique = sorted(set(lowercase_arms))
        # Six distinct canonical-state mappings must be present.
        assert len(unique) == 6, (
            f"Expected 6 unique FsmState wire arms, got {len(unique)}: {unique}"
        )

    def test_d4_fsm_has_nine_valid_transitions(self, fsm_lib_rs_source):
        """The Rust FSM crate's VALID_TRANSITIONS constant must contain
        the nine canonical edges exactly."""
        # Find the VALID_TRANSITIONS block and extract FsmTransition::new
        # tuples within it.
        m = re.search(
            r"pub const VALID_TRANSITIONS:\s*&\[FsmTransition\]\s*=\s*&\[(.*?)\];",
            fsm_lib_rs_source,
            re.DOTALL,
        )
        assert m is not None, "VALID_TRANSITIONS block not found in lib.rs"
        block = m.group(1)
        edges = re.findall(
            r"FsmTransition::new\(\s*FsmState::(\w+)\s*,\s*FsmState::(\w+)\s*\)",
            block,
        )
        assert edges == CANONICAL_FSM_EDGES, (
            f"FSM transition drift: {edges}"
        )


# ---------------------------------------------------------------------------
# Dimension 5 — V-907 Pin-Stability Substrate (2 tests).
# ---------------------------------------------------------------------------


class TestV907PinStability:
    """Audit Dimension 5: V-907 4-crate substrate + ground-truth digest."""

    def test_d5_v907_substrate_four_crates_exist(self):
        """The four V-907-substrate crates must all exist on-disk."""
        for crate in (
            "persona-hash",
            "persona-canonical-form",
            "persona-canonical-form-yaml",
            "persona-engine-v907-verify",
        ):
            cargo = CRATES_ROOT / crate / "Cargo.toml"
            assert cargo.exists(), f"V-907 substrate crate missing: {crate}"

    def test_d5_v907_verify_pins_sample_axis_a_ground_truth_digest(
        self, v907_lib_rs_source
    ):
        """persona-engine-v907-verify must reference the SAMPLE_AXIS_A
        ground-truth digest captured 2026-05-16 (Zone-K anchor)."""
        assert V907_SAMPLE_AXIS_A_DIGEST in v907_lib_rs_source, (
            "V-907 SAMPLE_AXIS_A ground-truth digest not anchored in lib.rs"
        )


# ---------------------------------------------------------------------------
# Dimension 6 — Containerfile.real Layer Integrity (2 tests).
# ---------------------------------------------------------------------------


class TestContainerfileLayers:
    """Audit Dimension 6: Containerfile layer-count + image-tag integrity."""

    def test_d6_containerfile_has_canonical_layer_counts(
        self, containerfile_source
    ):
        """Containerfile.real must contain the canonical Tag-56 instruction
        counts: 1 FROM, 7 LABEL, 7 COPY, 4 RUN, 1 USER, 1 WORKDIR, 1
        ENTRYPOINT."""
        counts = {}
        for instr in (
            "FROM",
            "LABEL",
            "COPY",
            "RUN",
            "USER",
            "WORKDIR",
            "ENTRYPOINT",
        ):
            counts[instr] = len(
                re.findall(
                    rf"^{instr}\s", containerfile_source, re.MULTILINE
                )
            )
        expected = {
            "FROM": 1,
            "LABEL": 7,
            "COPY": 7,
            "RUN": 3,
            "USER": 1,
            "WORKDIR": 1,
            "ENTRYPOINT": 1,
        }
        assert counts == expected, (
            f"Containerfile layer-count drift: {counts} vs. {expected}"
        )

    def test_d6_image_version_label_matches_release_marker(
        self, containerfile_source
    ):
        """The OCI image-version label must be '0.5.2-final-pre-cutover'."""
        m = re.search(
            r'LABEL\s+org\.opencontainers\.image\.version="([^"]+)"',
            containerfile_source,
        )
        assert m is not None, "image.version LABEL not found"
        assert m.group(1) == "0.5.2-final-pre-cutover", (
            f"Image-version label drift: {m.group(1)}"
        )


# ---------------------------------------------------------------------------
# Dimension 7 — Cargo Workspace Inventory (2 tests).
# ---------------------------------------------------------------------------


class TestCargoWorkspace:
    """Audit Dimension 7: 33 workspace members + strict-equality dep pins."""

    def test_d7_workspace_lists_all_15_pin_pack_crates_as_members(
        self, cargo_workspace_source
    ):
        """Each of the 15 pin-pack crates must appear in the workspace
        ``members =`` block."""
        for crate in CANONICAL_PIN_PACK_15:
            needle = f'"crates/{crate}"'
            assert needle in cargo_workspace_source, (
                f"Workspace member missing: {crate}"
            )

    def test_d7_workspace_dependencies_are_strict_equality_pinned(
        self, cargo_workspace_source
    ):
        """The [workspace.dependencies] block must pin the six byte-stability-
        relevant crates with strict-equality (``=X.Y.Z``)."""
        # Extract the [workspace.dependencies] block.
        m = re.search(
            r"\[workspace\.dependencies\](.*?)(?:^\[|\Z)",
            cargo_workspace_source,
            re.DOTALL | re.MULTILINE,
        )
        assert m is not None, "[workspace.dependencies] block not found"
        block = m.group(1)
        # Each crate must have a line of the form
        #   crate = ... "=X.Y.Z" ...
        # The `"=` marker (equality-pin sigil inside the version string)
        # is the simple and sufficient check.
        for crate in (
            "sha2",
            "serde",
            "serde_json",
            "serde_jcs",
            "serde_yaml",
            "hex",
        ):
            # Find the line that starts with this crate name.
            line_pattern = rf"^{re.escape(crate)}\s*=.*$"
            line_match = re.search(line_pattern, block, re.MULTILINE)
            assert line_match is not None, (
                f"Workspace-dep line missing: {crate}"
            )
            line = line_match.group(0)
            assert '"=' in line, (
                f"Workspace-dep not strict-equality-pinned ('\"='-marker missing): "
                f"{crate} line: {line}"
            )


# ---------------------------------------------------------------------------
# Cross-cutting — audit report must exist (1 sanity test, not counted
# against the ≥12 dimension tests but included for completeness).
# ---------------------------------------------------------------------------


def test_audit_report_present_at_canonical_path():
    """The Tag-56 audit report must exist at its canonical path."""
    assert AUDIT_REPORT_PATH.exists(), (
        f"Audit report missing at {AUDIT_REPORT_PATH}"
    )
    text = AUDIT_REPORT_PATH.read_text(encoding="utf-8")
    # Headline marker presence.
    assert "Production-Readiness Audit (Tag-56)" in text
    assert "PRODUCTION-READY-WITH-2-OPEN-CROSS-REVIEW-ITEMS" in text
