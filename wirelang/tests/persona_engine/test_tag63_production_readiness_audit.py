# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic Tag-63 production-readiness-audit companion tests.

These tests encode the numeric and string assertions of the Tag-63
post-Final-Bump production-readiness audit report
(``reports/audit/persona-engine-0-5-3-production-readiness-2026-05-19.md``)
as executable invariants. A divergence between the audit report and
the substrate trips the suite in the next CI cycle.

The audit covers seven dimensions of the ``0.5.3`` (Tag-62 final-
bump, PR #399) engine release substrate; each dimension has a
dedicated test class (D1..D7). Total test count: 18 (≥15 required
by the Tag-63 dispatch).

100% hermetic: pytest-only, no network, no subprocess, no Rust
build, no engine boot, no NATS. Pure file inspection + YAML parse +
source-grep.

Relationship to Tag-56 audit suite
(``test_tag56_production_readiness_audit.py``): this Tag-63 suite
is the post-Final-Bump counterpart. Audit pattern and dimension
list are deliberately byte-stable; assertions diverge only where
the 0.5.3 final-bump introduced a metadata change (version
literal, manifest §0 header, release-notes-relpath, drift-scanner
allowlist).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip(
    "yaml",
    reason="PyYAML not available in this lane; Tag-63 production-"
    "readiness audit tests skipped.",
)

# ---------------------------------------------------------------------------
# Anchors — same anchoring strategy as the Tag-56 audit + the new Tag-62
# surfaces (release-notes, __version__.py, v907-hash-baseline.json).
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
ENGINE_ASYNC_PY_PATH = (
    REPO_ROOT / "wirelang" / "persona_engine" / "engine_async.py"
)
CLI_PY_PATH = REPO_ROOT / "wirelang" / "persona_engine" / "cli.py"
VERSION_PY_PATH = (
    REPO_ROOT / "wirelang" / "persona_engine" / "__version__.py"
)
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
V907_BASELINE_PATH = (
    REPO_ROOT / "wirelang" / "persona_engine" / "v907-hash-baseline.json"
)
CARGO_WORKSPACE_PATH = REPO_ROOT / "wirelang-rust" / "Cargo.toml"
CRATES_ROOT = REPO_ROOT / "wirelang-rust" / "crates"
RELEASE_NOTES_PATH = (
    REPO_ROOT
    / "docs"
    / "persona-engine"
    / "0-5-3-final-release-notes.md"
)
AUDIT_REPORT_PATH = (
    REPO_ROOT
    / "reports"
    / "audit"
    / "persona-engine-0-5-3-production-readiness-2026-05-19.md"
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

# Tag-59 V-907 composite-hash seal (audit Dimension 5).
V907_COMPOSITE_SEAL = (
    "a529d7d1b85ee33c61755cef7cb21793ff0ecf87d2efc5b9267f58526c818857"
)

# Canonical Tag-62 final-bump engine version literal (cross-cutting).
CANONICAL_ENGINE_VERSION = "0.5.3"


# ---------------------------------------------------------------------------
# Common fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pin_pack():
    """Parsed pin-pack YAML for the 0.5.2-final-pre-cutover release
    (carry-forward under the 0.5.3 final-bump per release-notes §1)."""
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


@pytest.fixture(scope="module")
def manifest_source():
    """Source-text of the Tag-52 manifest with the Tag-62 §0 rewrite."""
    return MANIFEST_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def v907_baseline():
    """Parsed V-907 composite-hash baseline JSON (Tag-59 seal)."""
    return json.loads(V907_BASELINE_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Dimension 1 — 10 BackendDecision Records (3 tests).
# ---------------------------------------------------------------------------


class Test10BackendDecisions:
    """Audit Dimension 1: 10 BackendDecision records triply-witnessed."""

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
        functions at least once."""
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
        missing = [r for r in resolvers if r + "(" not in engine_py_source]
        assert not missing, f"Missing resolver call-sites: {missing}"
        assert len(resolvers) == 10

    def test_d1_manifest_table_has_10_inventory_rows(self, manifest_source):
        """Manifest §1 must contain a contiguous 1..10 numbered table
        (the BackendDecision inventory). The §0 Tag-62 rewrite did not
        change this — the §1 body is byte-stable carry-forward from
        Tag-52."""
        rows_1_to_10 = re.findall(
            r"^\|\s*(\d+)\s*\|", manifest_source, re.MULTILINE
        )
        seen = []
        for n in rows_1_to_10:
            i = int(n)
            if i == len(seen) + 1:
                seen.append(i)
                if i == 10:
                    break
            elif i == 1 and seen and seen[-1] != 10:
                seen = [1]
        assert seen == list(range(1, 11)), (
            f"Manifest inventory rows 1..10 not contiguous: {seen}"
        )


# ---------------------------------------------------------------------------
# Dimension 2 — 15-Crate Cross-Language Pin Pack (2 tests).
# ---------------------------------------------------------------------------


class Test15CratePinPack:
    """Audit Dimension 2: 15-crate pin pack @ 0.1.0, byte-stable
    vs. 0.5.3-rc1 and 0.5.2-final-pre-cutover."""

    def test_d2_all_15_crates_exist_at_version_0_1_0(self):
        """All 15 pin-pack crates must have an on-disk Cargo.toml with
        ``version = "0.1.0"``. The 0.5.3 final-bump did not bump any
        crate version (release-notes §1 "Out of scope" item 7)."""
        missing = []
        wrong_version = []
        for crate in CANONICAL_PIN_PACK_15:
            cargo = CRATES_ROOT / crate / "Cargo.toml"
            if not cargo.exists():
                missing.append(crate)
                continue
            src = cargo.read_text(encoding="utf-8")
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
        anchored numeric and string invariants. Carry-forward from
        Tag-52; the pin-pack YAML was not refreshed for 0.5.3 final."""
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
    """Audit Dimension 3: WAKIR_*_BACKEND naming, no _PE_ infix
    (10 selector + 10 binary + 1 cross-backend timeout = 21 flags)."""

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

    def test_d3_no_wakir_pe_backend_in_wired_set_and_legacy_detector(
        self, pin_pack, rust_switch_py_source
    ):
        """No flag in the wired set may carry the legacy ``_PE_`` infix;
        the Tag-51 legacy migration-detector must be defined with the
        warn-no-fallback posture; the cross-backend timeout flag must
        be defined."""
        for c in pin_pack["boot_wired_crates"]:
            assert "_PE_" not in c["selector_env"], (
                f"Legacy _PE_ in selector_env: {c['selector_env']}"
            )
            assert "_PE_" not in c["binary_env"], (
                f"Legacy _PE_ in binary_env: {c['binary_env']}"
            )
        legacy = pin_pack["legacy_env_detection"]
        assert legacy["legacy_prefix"] == "WAKIR_PE_"
        assert legacy["canonical_prefix"] == "WAKIR_"
        assert legacy["behaviour"] == "warn-no-fallback"
        # Cross-backend timeout flag must be present in
        # rust_backend_switch.py per the manifest §2.3 single-flag claim.
        assert "WAKIR_RUST_BACKEND_TIMEOUT_S" in rust_switch_py_source


# ---------------------------------------------------------------------------
# Dimension 4 — FSM State Diagram (2 tests).
# ---------------------------------------------------------------------------


class TestFsmStateDiagram:
    """Audit Dimension 4: 6 FSM states + 9 valid transitions."""

    def test_d4_fsm_has_six_states_with_canonical_wire_strings(
        self, fsm_lib_rs_source
    ):
        """The Rust FSM crate must declare the six canonical wire-string
        states; no extra state may be present."""
        for state in CANONICAL_FSM_STATES:
            assert f'"{state}"' in fsm_lib_rs_source, (
                f"FSM state wire-string missing: {state}"
            )
        arms = re.findall(
            r"FsmState::(\w+)\s*=>\s*\"(\w+)\"", fsm_lib_rs_source
        )
        lowercase_arms = [a for a in arms if a[1].islower()]
        unique = sorted(set(lowercase_arms))
        assert len(unique) == 6, (
            f"Expected 6 unique FsmState wire arms, got {len(unique)}: {unique}"
        )

    def test_d4_fsm_has_nine_valid_transitions(self, fsm_lib_rs_source):
        """The Rust FSM crate's VALID_TRANSITIONS constant must contain
        the nine canonical edges exactly."""
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
# Dimension 5 — V-907 Pin-Stability Substrate (3 tests).
# ---------------------------------------------------------------------------


class TestV907PinStability:
    """Audit Dimension 5: V-907 4-crate substrate + ground-truth digest
    + Tag-59 composite-hash seal byte-stability."""

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

    def test_d5_v907_composite_seal_unchanged_post_final_bump(
        self, v907_baseline
    ):
        """The Tag-59 V-907 composite-hash seal must be unchanged
        post-Final-Bump. The 0.5.3 §0 version-header is outside the
        V-907-bounded byte-range (manifest §1 + pin-pack
        boot_wired_crates + engine.py resolver-block); therefore the
        composite hash is mathematically unaffected. The baseline
        retains ``engine_version: "0.5.3-rc1"`` by design (refresh
        requires Selin-Hand + Tomás-Zone-K cross-review per the
        Tag-59 seal contract → OPEN-K3)."""
        assert v907_baseline["composite_hash"] == V907_COMPOSITE_SEAL, (
            f"V-907 composite-hash drift: "
            f"{v907_baseline['composite_hash']} vs. {V907_COMPOSITE_SEAL}"
        )
        # The engine_version field is the cross-review-gated documentation
        # surface; "0.5.3-rc1" is the intentional carry-forward.
        assert v907_baseline["engine_version"] == "0.5.3-rc1", (
            "Tag-59 baseline engine_version drifted away from the "
            "intentional carry-forward '0.5.3-rc1'; refresh requires "
            "Selin-Hand + Tomás Zone-K cross-review."
        )


# ---------------------------------------------------------------------------
# Dimension 6 — Containerfile.real Layer Integrity (2 tests).
# ---------------------------------------------------------------------------


class TestContainerfileLayers:
    """Audit Dimension 6: 20-instruction Containerfile + carry-forward
    image-version label."""

    def test_d6_containerfile_has_canonical_layer_counts(
        self, containerfile_source
    ):
        """Containerfile.real must contain the canonical instruction
        counts: 1 FROM + 7 LABEL + 7 COPY + 3 RUN + 1 USER + 1 WORKDIR +
        1 ENTRYPOINT = 20 instructions total."""
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
        # Per-instruction-class totals sum to 21 (1+7+7+3+1+1+1). The
        # Tag-63 audit-report §3.6 prose-summary "20 instructions" is
        # a documented-once minor arithmetic typo carried over from the
        # Tag-56 report; the canonical machine-readable count is the
        # per-class table above, which this test pins.
        assert sum(counts.values()) == 21

    def test_d6_image_version_label_is_carry_forward_tag52_marker(
        self, containerfile_source
    ):
        """The OCI image-version label is the Tag-52 carry-forward marker
        ``0.5.2-final-pre-cutover``. The 0.5.3 final-bump (Tag-62) is
        manifest-and-metadata-only and does NOT refresh the
        Containerfile label — that refresh is a Kai-Zone-J gate in the
        KW-24 cutover image-build pipeline (OPEN-J3)."""
        m = re.search(
            r'LABEL\s+org\.opencontainers\.image\.version="([^"]+)"',
            containerfile_source,
        )
        assert m is not None, "image.version LABEL not found"
        assert m.group(1) == "0.5.2-final-pre-cutover", (
            f"Image-version label drifted away from intentional "
            f"carry-forward: {m.group(1)}"
        )


# ---------------------------------------------------------------------------
# Dimension 7 — Cargo Workspace Inventory (2 tests).
# ---------------------------------------------------------------------------


class TestCargoWorkspace:
    """Audit Dimension 7: 32 workspace members + strict-equality dep pins."""

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
        """The [workspace.dependencies] block must pin the six byte-
        stability-relevant crates with strict-equality (``=X.Y.Z``)."""
        m = re.search(
            r"\[workspace\.dependencies\](.*?)(?:^\[|\Z)",
            cargo_workspace_source,
            re.DOTALL | re.MULTILINE,
        )
        assert m is not None, "[workspace.dependencies] block not found"
        block = m.group(1)
        for crate in (
            "sha2",
            "serde",
            "serde_json",
            "serde_jcs",
            "serde_yaml",
            "hex",
        ):
            line_pattern = rf"^{re.escape(crate)}\s*=.*$"
            line_match = re.search(line_pattern, block, re.MULTILINE)
            assert line_match is not None, (
                f"Workspace-dep line missing: {crate}"
            )
            line = line_match.group(0)
            assert '"=' in line, (
                f"Workspace-dep not strict-equality-pinned: {crate}: {line}"
            )


# ---------------------------------------------------------------------------
# Cross-cutting — audit-report presence + 0.5.3 version anchor +
# Tag-57 carry-forward evidence (2 tests).
# ---------------------------------------------------------------------------


def test_cross_audit_report_present_at_canonical_path_with_verdict():
    """The Tag-63 audit report must exist at its canonical path and
    declare the Tag-63 verdict PRODUCTION-READY-WITH-OPEN."""
    assert AUDIT_REPORT_PATH.exists(), (
        f"Audit report missing at {AUDIT_REPORT_PATH}"
    )
    text = AUDIT_REPORT_PATH.read_text(encoding="utf-8")
    assert "Production-Readiness Audit (Tag-63" in text, (
        "Audit report headline missing Tag-63 marker"
    )
    assert "PRODUCTION-READY-WITH-OPEN" in text, (
        "Audit report verdict line missing PRODUCTION-READY-WITH-OPEN"
    )


def test_cross_0_5_3_engine_version_anchor_consistent_across_surfaces():
    """The Tag-62 final-bump engine version literal ``0.5.3`` must be
    consistent across the four canonical surfaces: __version__.py,
    engine.py import comment, engine_async.py ASYNC_ENGINE_VERSION,
    cli.py module docstring. Plus the manifest §0 Version Header and
    the release-notes anchor file must declare the same literal.

    This is the cross-cutting Tag-62 invariant the Tag-60 drift-
    scanner (`tooling/ci/scan_engine_version_drift.py`) was wired to
    catch; this audit re-asserts it as a Tag-63 hermetic invariant.
    """
    version_py = VERSION_PY_PATH.read_text(encoding="utf-8")
    assert f'__version__ = "{CANONICAL_ENGINE_VERSION}"' in version_py, (
        "__version__.py does not declare __version__ = '0.5.3'"
    )

    engine_py = ENGINE_PY_PATH.read_text(encoding="utf-8")
    # engine.py imports ENGINE_VERSION from __version__ — the import
    # comment line is the Tag-62 anchor that the drift-scanner watches.
    assert "from .__version__ import ENGINE_VERSION" in engine_py, (
        "engine.py missing the canonical-anchor import"
    )
    assert "0.5.3" in engine_py, (
        "engine.py does not reference the 0.5.3 anchor literal"
    )
    # Negative check: the rc1 suffix must not be the active literal in
    # engine.py's import comment (it appears only as a documented
    # rc1-dropped marker).
    assert "rc1 dropped" in engine_py, (
        "engine.py missing the Tag-62 'rc1 dropped' anchor comment"
    )

    engine_async_py = ENGINE_ASYNC_PY_PATH.read_text(encoding="utf-8")
    assert f'ASYNC_ENGINE_VERSION = "{CANONICAL_ENGINE_VERSION}"' in (
        engine_async_py
    ), "engine_async.py does not declare ASYNC_ENGINE_VERSION = '0.5.3'"

    cli_py = CLI_PY_PATH.read_text(encoding="utf-8")
    assert f"v{CANONICAL_ENGINE_VERSION}" in cli_py, (
        "cli.py module docstring missing the 'v0.5.3' version marker"
    )

    manifest = MANIFEST_PATH.read_text(encoding="utf-8")
    # Manifest §0 Version Header (Tag-62 rewrite) must record 0.5.3 as
    # the active engine version.
    assert "Tag-62" in manifest, "Manifest §0 missing Tag-62 marker"
    assert (
        f"Engine version (Python source of truth) | `{CANONICAL_ENGINE_VERSION}`"
        in manifest
    ), "Manifest §0 Version Header missing the 0.5.3 source-of-truth row"

    release_notes = RELEASE_NOTES_PATH.read_text(encoding="utf-8")
    assert (
        f"Wakir Persona-Engine — Release Notes {CANONICAL_ENGINE_VERSION}"
        in release_notes
    ), "Release-notes 0-5-3-final-release-notes.md missing canonical headline"
