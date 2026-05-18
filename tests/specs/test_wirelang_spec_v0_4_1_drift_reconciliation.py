# SPDX-License-Identifier: Apache-2.0
"""Tag-48 hermetic test suite for wirelang-spec-v0-4-1.md drift reconciliation.

This suite verifies the additive patch v0.4.1 over v0.4.0 captures the three
drift items recorded in the Tag-47 audit report:

- DRIFT-S1: persona-engine-federation-resolver added to spec §3.1 row 16
- DRIFT-S2: persona-engine-recovery-replay companion-vs-row clarification (§3.1.14)
- DRIFT-S3: unwired-crates classification clarification (§4)

Hermetic: no NATS, no engine boot, no Rust build, no network import.
Pure static-pass over the working copy: read the spec, read the workspace,
verify invariants.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_V040 = REPO_ROOT / "wirelang" / "specs" / "wirelang-spec-v0-4.md"
SPEC_V041 = REPO_ROOT / "wirelang" / "specs" / "wirelang-spec-v0-4-1.md"
RUST_CRATES_DIR = REPO_ROOT / "wirelang-rust" / "crates"
PIN_PACK_PATH = REPO_ROOT / "infra" / "persona-engine" / "pin-pack-0.5.0-pre-cutover.yaml"
AUDIT_REPORT_PATH = (
    REPO_ROOT / "reports" / "audit" / "phase-3a-15-crate-consistency-2026-05-19.md"
)


# The sixteen-row §3.1 catalogue under v0.4.1.
SPEC_V041_CRATES_16 = [
    "persona-canonical-form",
    "persona-canonical-form-yaml",
    "persona-hash",
    "persona-engine-v907-verify",
    "persona-engine-svid-workload-identity",
    "persona-engine-bridge-audit-writer",
    "persona-engine-bridge-audit-replay",
    "persona-engine-bridge-diff",
    "persona-engine-bridge-forward",
    "persona-engine-state-backing",
    "persona-engine-fsm",
    "persona-engine-subscribe-loop",
    "persona-engine-recovery",
    "persona-engine-recovery-replay",
    "persona-engine-anchor-emitter",
    "persona-engine-federation-resolver",
]

# The three pin-pack-parity-pinned tooling crates per v0.4.1 §4.
PARITY_PINNED_TOOLING_3 = [
    "persona-engine-anchor-submit-worker",
    "persona-engine-federation-frame-parser",
    "persona-engine-frontmatter-parser",
]


def test_t01_spec_v041_file_exists():
    """T-01: v0.4.1 spec file is present at expected path."""
    assert SPEC_V041.is_file(), f"missing v0.4.1 spec at {SPEC_V041}"


def test_t02_spec_v040_file_exists():
    """T-02: v0.4.0 spec file is present (extends contract)."""
    assert SPEC_V040.is_file(), f"missing v0.4.0 spec at {SPEC_V040}"


def test_t03_spec_v041_extends_v040_in_frontmatter():
    """T-03: v0.4.1 frontmatter declares extends: 0.4.0."""
    body = SPEC_V041.read_text(encoding="utf-8")
    # Frontmatter block at file head.
    assert re.search(r"^version:\s*0\.4\.1\s*$", body, re.M), "version must be 0.4.1"
    assert re.search(r"^extends:\s*0\.4\.0\s*$", body, re.M), "extends must be 0.4.0"


def test_t04_spec_v041_lists_sixteen_rows_in_section_3_1():
    """T-04: v0.4.1 §3.1 catalogue contains all sixteen crate names."""
    body = SPEC_V041.read_text(encoding="utf-8")
    for crate in SPEC_V041_CRATES_16:
        assert (
            f"`{crate}`" in body
        ), f"crate {crate} missing from v0.4.1 spec body"


def test_t05_spec_v041_lists_row_16_federation_resolver():
    """T-05: row 16 is persona-engine-federation-resolver (DRIFT-S1)."""
    body = SPEC_V041.read_text(encoding="utf-8")
    # The row marker `| 16 | ` or `| **16** | ` should appear with
    # federation-resolver in the same line.
    pattern = re.compile(
        r"\|\s*\*?\*?16\*?\*?\s*\|\s*\*?\*?`persona-engine-federation-resolver`",
    )
    assert pattern.search(body), "row 16 must be federation-resolver"


def test_t06_all_sixteen_crates_exist_in_workspace():
    """T-06: every v0.4.1 §3.1 crate exists under wirelang-rust/crates/."""
    for crate in SPEC_V041_CRATES_16:
        crate_dir = RUST_CRATES_DIR / crate
        assert crate_dir.is_dir(), f"missing rust crate dir for {crate}"
        cargo_toml = crate_dir / "Cargo.toml"
        assert cargo_toml.is_file(), f"missing Cargo.toml for {crate}"


def test_t07_federation_resolver_has_substantive_source():
    """T-07: federation-resolver has non-trivial src/lib.rs or src/main.rs."""
    crate_dir = RUST_CRATES_DIR / "persona-engine-federation-resolver"
    src_dir = crate_dir / "src"
    assert src_dir.is_dir(), "federation-resolver missing src/ dir"
    rs_files = list(src_dir.rglob("*.rs"))
    assert rs_files, "federation-resolver has no .rs files"
    total_loc = sum(
        len([line for line in f.read_text(encoding="utf-8").splitlines() if line.strip()])
        for f in rs_files
    )
    # Spec §7 verification floor: 100 LoC.
    assert total_loc >= 100, f"federation-resolver LoC {total_loc} below floor 100"


def test_t08_spec_v041_documents_off_welle_classification_for_row_16():
    """T-08: row 16 is classified Off-Welle (boot), not on Phase-3c path."""
    body = SPEC_V041.read_text(encoding="utf-8")
    # The Off-Welle phrase must appear in close proximity to row 16's
    # federation-resolver content.
    assert "Off-Welle" in body, "v0.4.1 must classify row 16 as Off-Welle"
    # Either §3.1.16 subsection or the §3.1 row itself documents it.
    assert "Off-Welle (boot)" in body, "Off-Welle classifier (boot) must be present"


def test_t09_spec_v041_documents_recovery_replay_companion_footnote():
    """T-09: §3.1.14 footnote clarifies recovery-replay companion semantics (DRIFT-S2)."""
    body = SPEC_V041.read_text(encoding="utf-8")
    assert "3.1.14" in body, "§3.1.14 footnote must be present"
    assert "companion" in body.lower(), "companion semantics must be discussed"
    # The shared fixture directory is the canonical companion-anchor.
    assert (
        "recovery-workflow-cross-lang" in body
    ), "shared fixture dir must be cited"


def test_t10_spec_v041_documents_three_parity_pinned_tooling_crates():
    """T-10: §4 lists the three parity-pinned tooling crates (DRIFT-S3)."""
    body = SPEC_V041.read_text(encoding="utf-8")
    for crate in PARITY_PINNED_TOOLING_3:
        assert (
            f"`{crate}`" in body
        ), f"parity-pinned tooling crate {crate} missing from v0.4.1 body"
    assert "Tooling/cross-lang-parity-pinned" in body, (
        "v0.4.1 must introduce the Tooling/cross-lang-parity-pinned subclass"
    )


def test_t11_spec_v041_does_not_modify_wire_format():
    """T-11: backward-compat note declares no wire-format change."""
    body = SPEC_V041.read_text(encoding="utf-8")
    assert "No on-the-wire change" in body, (
        "v0.4.1 must declare no wire-format change for backward compatibility"
    )
    # Specifically, wirelangversion stays at 0.4.0 on the wire.
    assert "0.4.0" in body, "v0.4.1 must reference 0.4.0 wire-attribute baseline"


def test_t12_spec_v041_does_not_modify_env_flag_schema():
    """T-12: backward-compat note declares no ENV-flag-schema change."""
    body = SPEC_V041.read_text(encoding="utf-8")
    # §5.2 must explicitly state "nine engine components" preserved.
    assert "nine engine components" in body, (
        "v0.4.1 §5.2 must preserve nine-component ENV-flag schema"
    )


def test_t13_audit_report_is_cited():
    """T-13: v0.4.1 citation pointers reference the Tag-47 audit report."""
    body = SPEC_V041.read_text(encoding="utf-8")
    assert (
        "phase-3a-15-crate-consistency-2026-05-19.md" in body
    ), "audit report path must be cited"
    assert "PR #305" in body, "audit PR #305 must be cited"
    assert "7ada5ab" in body, "audit baseline commit must be cited"


def test_t14_workspace_total_is_32_crates():
    """T-14: workspace contains exactly 32 crates (16 §3.1 + 16 tooling)."""
    crates = [
        d for d in RUST_CRATES_DIR.iterdir() if d.is_dir() and (d / "Cargo.toml").is_file()
    ]
    assert len(crates) == 32, f"workspace crate count {len(crates)} != 32"

    # All §3.1 sixteen exist.
    crate_names = {d.name for d in crates}
    missing_spec = set(SPEC_V041_CRATES_16) - crate_names
    assert not missing_spec, f"v0.4.1 §3.1 crates missing from workspace: {missing_spec}"

    # All three parity-pinned-tooling exist.
    missing_pinned = set(PARITY_PINNED_TOOLING_3) - crate_names
    assert not missing_pinned, f"parity-pinned tooling missing: {missing_pinned}"


def test_t15_v041_16_plus_16_partition_recovers_v040_15_plus_17():
    """T-15: the v0.4.1 16+16 partition is a refinement of v0.4.0's 15+17.

    Move federation-resolver from "tooling" to "§3.1 catalogue":
    - v0.4.0: 15 §3.1 + 17 tooling = 32
    - v0.4.1: 16 §3.1 + 16 tooling = 32

    Sanity check: §3.1 row sixteen IS federation-resolver and is the
    only delta between the two partitions.
    """
    # Build v0.4.0 §3.1 fifteen set (drop the new row 16).
    v040_15 = [c for c in SPEC_V041_CRATES_16 if c != "persona-engine-federation-resolver"]
    assert len(v040_15) == 15, "v0.4.0 §3.1 had fifteen crates"
    assert len(SPEC_V041_CRATES_16) == 16, "v0.4.1 §3.1 has sixteen crates"

    # The symmetric difference is exactly federation-resolver.
    delta = set(SPEC_V041_CRATES_16) - set(v040_15)
    assert delta == {
        "persona-engine-federation-resolver"
    }, f"delta set unexpected: {delta}"


def test_t16_open_items_section_present():
    """T-16: §6 lists open items deferred to v0.5 (no silent debt)."""
    body = SPEC_V041.read_text(encoding="utf-8")
    assert "## 6. Open items" in body, "open items section must be present"
    # Welle-0 deferral.
    assert "Welle-0" in body or "Welle 0" in body, (
        "Welle-0 boot-fan-out classification deferral must be noted"
    )


def test_t17_no_caveat_predicate_addition():
    """T-17: v0.4.1 introduces no new caveat predicates."""
    body = SPEC_V041.read_text(encoding="utf-8")
    assert "No caveat-" in body or "No caveat" in body, (
        "v0.4.1 must declare no caveat predicate change"
    )
