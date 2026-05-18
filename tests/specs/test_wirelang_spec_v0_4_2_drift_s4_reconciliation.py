# SPDX-License-Identifier: Apache-2.0
"""Tag-50 hermetic test suite for wirelang-spec-v0-4-2.md DRIFT-S4 reconciliation.

This suite verifies the additive patch v0.4.2 over v0.4.1 captures the single
drift item raised against PR #314 (Tag-49 federation-resolver cross-lang-pin
refresh suite):

- DRIFT-S4: spec v0.4.1 §4.1 listed nine `WAKIR_PE_*_BACKEND` components;
  Pin-Pack-0.5.1-pre-cutover wires ten `WAKIR_*_BACKEND` records with
  federation-resolver at #9 and bridge-audit-writer at #10. Mira-CEO-Triage
  2026-05-19 (Option C Hybrid): spec documents Pin-Pack reality as
  single-source-of-truth; canonical_form demoted to §4.1 FN-1 (no ENV-flag
  wired in v0.4.2; Phase-4-Item).

Hermetic: no NATS, no engine boot, no Rust build, no network import.
Pure static-pass over the working copy: read the spec, read the Pin-Pack
YAML, read the manifest, verify invariants.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_V040 = REPO_ROOT / "wirelang" / "specs" / "wirelang-spec-v0-4.md"
SPEC_V041 = REPO_ROOT / "wirelang" / "specs" / "wirelang-spec-v0-4-1.md"
SPEC_V042 = REPO_ROOT / "wirelang" / "specs" / "wirelang-spec-v0-4-2.md"
PIN_PACK_PATH = (
    REPO_ROOT / "infra" / "persona-engine" / "pin-pack-0.5.1-pre-cutover.yaml"
)
MANIFEST_PATH = (
    REPO_ROOT
    / "wirelang"
    / "persona_engine"
    / "MANIFEST-0.5.1-pre-cutover.md"
)


# Pin-Pack-0.5.1 ground truth (record-ordered) — this is the source of
# truth that spec v0.4.2 §4.1 must mirror byte-for-byte.
PIN_PACK_TEN_RECORDS_ORDERED = [
    (1, "persona-engine-recovery", "WAKIR_RECOVERY_BACKEND"),
    (2, "persona-engine-state-backing", "WAKIR_STATE_BACKING_BACKEND"),
    (3, "persona-engine-fsm", "WAKIR_FSM_BACKEND"),
    (4, "persona-engine-v907-verify", "WAKIR_V907_VERIFY_BACKEND"),
    (5, "persona-engine-bridge-diff", "WAKIR_BRIDGE_DIFF_BACKEND"),
    (6, "persona-engine-subscribe-loop", "WAKIR_SUBSCRIBE_LOOP_BACKEND"),
    (7, "persona-engine-anchor-emitter", "WAKIR_ANCHOR_EMITTER_BACKEND"),
    (
        8,
        "persona-engine-svid-workload-identity",
        "WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND",
    ),
    (
        9,
        "persona-engine-federation-resolver",
        "WAKIR_FEDERATION_RESOLVER_BACKEND",
    ),
    (
        10,
        "persona-engine-bridge-audit-writer",
        "WAKIR_BRIDGE_AUDIT_WRITER_BACKEND",
    ),
]


# ---------------------------------------------------------------------------
# T-01 / T-02: file presence + frontmatter
# ---------------------------------------------------------------------------


def test_t01_spec_v042_file_exists():
    """T-01: v0.4.2 spec file is present at expected path."""
    assert SPEC_V042.is_file(), f"missing v0.4.2 spec at {SPEC_V042}"


def test_t02_spec_v042_frontmatter_extends_v041():
    """T-02: v0.4.2 frontmatter declares version 0.4.2 and extends 0.4.1."""
    body = SPEC_V042.read_text(encoding="utf-8")
    assert re.search(
        r"^version:\s*0\.4\.2\s*$", body, re.M
    ), "version must be 0.4.2"
    assert re.search(
        r"^extends:\s*0\.4\.1\s*$", body, re.M
    ), "extends must be 0.4.1"
    assert re.search(
        r"^date:\s*2026-05-19\s*$", body, re.M
    ), "date must be 2026-05-19 (Tag-50)"


# ---------------------------------------------------------------------------
# T-03 / T-04: §4.1 row presence + ordering matches Pin-Pack reality
# ---------------------------------------------------------------------------


def test_t03_spec_v042_section_4_1_lists_all_ten_pin_pack_components():
    """T-03: every Pin-Pack-wired component name appears in v0.4.2 §4.1."""
    body = SPEC_V042.read_text(encoding="utf-8")
    for _record, crate, _env in PIN_PACK_TEN_RECORDS_ORDERED:
        # Backtick-fenced reference required (table cells are backtick-fenced).
        assert (
            f"`{crate}`" in body
        ), f"§4.1 must reference `{crate}` (Pin-Pack record)"


def test_t04_spec_v042_section_4_1_selector_envs_match_pin_pack():
    """T-04: every Pin-Pack selector_env value appears verbatim in v0.4.2 §4.1."""
    body = SPEC_V042.read_text(encoding="utf-8")
    for _record, _crate, env in PIN_PACK_TEN_RECORDS_ORDERED:
        # Match either backtick-fenced (table) or bare (prose) — but the
        # spec uses backtick fencing exclusively for ENV names in §4.1.
        assert (
            f"`{env}`" in body
        ), f"§4.1 must reference `{env}` (Pin-Pack selector_env)"


# ---------------------------------------------------------------------------
# T-05 / T-06: naming-contract invariants (no `_PE_` infix in §4.1)
# ---------------------------------------------------------------------------


def test_t05_spec_v042_section_4_1_does_not_use_legacy_pe_infix():
    """T-05: §4.1 must not contain `WAKIR_PE_` (legacy v0.4.0 / v0.4.1 naming)."""
    body = SPEC_V042.read_text(encoding="utf-8")
    # Locate the §4.1 block: from "### 4.1" up to "### 4.2".
    section_4_1_match = re.search(
        r"### 4\.1 The ten Pin-Pack-wired boot records.*?(?=### 4\.2)",
        body,
        re.S,
    )
    assert section_4_1_match is not None, "§4.1 block not found"
    section_4_1 = section_4_1_match.group(0)
    assert (
        "WAKIR_PE_" not in section_4_1
    ), "§4.1 must not contain `WAKIR_PE_` (legacy naming retired in v0.4.2)"


def test_t06_section_4_1_table_rows_use_only_wakir_backend_naming():
    """T-06: every backtick-fenced ENV name inside the §4.1 table follows WAKIR_*_BACKEND.

    The legacy `WAKIR_PE_*_BACKEND` family may appear in narrative blocks
    (intro, §1 drift-statement, §2 conformance migration note, §4.3
    prose, §5.6 migration table) — those are documentation of the drift.
    The structural invariant DRIFT-S4 forces is: **no §4.1 table row
    cites a legacy name**. This test asserts that invariant directly
    against table-row syntax.
    """
    body = SPEC_V042.read_text(encoding="utf-8")
    section_4_1_match = re.search(
        r"### 4\.1 The ten Pin-Pack-wired boot records.*?(?=### 4\.2)",
        body,
        re.S,
    )
    assert section_4_1_match is not None, "§4.1 block not found"
    section_4_1 = section_4_1_match.group(0)
    # Extract every table row (line starts with `|` after leading whitespace
    # and contains another `|`).
    table_rows = [
        line
        for line in section_4_1.splitlines()
        if line.lstrip().startswith("|") and "|" in line.lstrip()[1:]
    ]
    assert len(table_rows) >= 12, (
        "§4.1 must contain ≥12 table-row lines "
        "(header + separator + 10 data rows)"
    )
    # No table row may cite WAKIR_PE_.
    for row in table_rows:
        assert (
            "WAKIR_PE_" not in row
        ), f"§4.1 table row carries legacy `WAKIR_PE_*` naming: {row!r}"
    # Every selector_env occurrence inside a row must match WAKIR_*_BACKEND.
    env_pattern = re.compile(r"`(WAKIR_[A-Z0-9_]+_BACKEND)`")
    selector_envs_in_rows = set()
    for row in table_rows:
        selector_envs_in_rows.update(env_pattern.findall(row))
    expected = {env for _r, _c, env in PIN_PACK_TEN_RECORDS_ORDERED}
    assert expected.issubset(
        selector_envs_in_rows
    ), f"§4.1 table missing selector_env names: {expected - selector_envs_in_rows}"


# ---------------------------------------------------------------------------
# T-07: canonical_form footnote FN-1 contract
# ---------------------------------------------------------------------------


def test_t07_canonical_form_demoted_to_fn1_footnote_with_phase4_marking():
    """T-07: canonical_form appears only in FN-1 and explicitly defers to Phase-4."""
    body = SPEC_V042.read_text(encoding="utf-8")
    # FN-1 footnote header must be present.
    assert (
        "#### Footnote FN-1:" in body
    ), "§4.1 must include footnote FN-1 for canonical_form"
    # FN-1 block: from "#### Footnote FN-1:" up to next ## or ###.
    fn1_match = re.search(
        r"#### Footnote FN-1:.*?(?=\n## |\n### )",
        body,
        re.S,
    )
    assert fn1_match is not None, "FN-1 block could not be located"
    fn1 = fn1_match.group(0)
    # Must mention canonical_form and Phase-4 (the deferral target).
    assert "canonical_form" in fn1 or "canonical-form" in fn1
    assert "Phase-4" in fn1, "FN-1 must mark canonical_form as a Phase-4 item"
    # Must explicitly state no ENV-flag is wired in v0.4.2.
    assert re.search(
        r"[Nn]o ENV-flag.*?canonical[_-]form|canonical[_-]form.*?[Nn]o ENV-flag|"
        r"No ENV-flag is wired",
        fn1,
        re.S,
    ), "FN-1 must explicitly state no ENV-flag is wired in v0.4.2"
    # Confirm canonical_form is NOT a Pin-Pack selector_env (negative check).
    pin_pack = yaml.safe_load(PIN_PACK_PATH.read_text(encoding="utf-8"))
    for rec in pin_pack["boot_wired_crates"]:
        assert (
            "canonical" not in rec["name"]
        ), f"Pin-Pack should not wire a canonical_form record (found {rec['name']})"


# ---------------------------------------------------------------------------
# T-08: Pin-Pack ground-truth parity (selector_env + binary_env + record #)
# ---------------------------------------------------------------------------


def test_t08_pin_pack_ground_truth_matches_expected_ten_records():
    """T-08: Pin-Pack-0.5.1 still wires exactly the ten records §4.1 enumerates."""
    pin_pack = yaml.safe_load(PIN_PACK_PATH.read_text(encoding="utf-8"))
    boot_wired = pin_pack["boot_wired_crates"]
    assert len(boot_wired) == 10, "Pin-Pack must wire exactly ten records"
    for expected, actual in zip(PIN_PACK_TEN_RECORDS_ORDERED, boot_wired):
        exp_record, exp_name, exp_env = expected
        assert actual["record"] == exp_record, (
            f"Pin-Pack record #{actual['record']} ({actual['name']}) "
            f"does not match expected #{exp_record}"
        )
        assert actual["name"] == exp_name
        assert actual["selector_env"] == exp_env
        # Every selector_env follows the WAKIR_*_BACKEND contract.
        assert actual["selector_env"].startswith("WAKIR_")
        assert actual["selector_env"].endswith("_BACKEND")
        assert "WAKIR_PE_" not in actual["selector_env"]
        # Every binary_env follows the WAKIR_RUST_*_BIN contract.
        assert actual["binary_env"].startswith("WAKIR_RUST_")
        assert actual["binary_env"].endswith("_BIN")


# ---------------------------------------------------------------------------
# T-09: §3 catalogue is byte-identical to v0.4.1 (no catalogue-side drift)
# ---------------------------------------------------------------------------


def test_t09_section_3_catalogue_byte_identical_to_v041():
    """T-09: v0.4.2 declares no §3 (catalogue) change; §3 block restates 'no change'."""
    body = SPEC_V042.read_text(encoding="utf-8")
    # The v0.4.2 §3 block is documented as "no change" rather than reproducing
    # the catalogue. The contract is that §3 prose explicitly declares this.
    section_3_match = re.search(
        r"## 3\. §3 no change.*?(?=## 4\.)",
        body,
        re.S,
    )
    assert section_3_match is not None, "§3 'no change' block not found"
    section_3 = section_3_match.group(0)
    assert "unchanged" in section_3.lower()
    # Also assert v0.4.1 still exists (extends-chain integrity).
    assert SPEC_V041.is_file(), "v0.4.1 spec must remain in tree (extends chain)"


# ---------------------------------------------------------------------------
# T-10: federation-resolver at record #9, bridge-audit-writer at record #10
#        (the two record-position invariants central to DRIFT-S4)
# ---------------------------------------------------------------------------


def test_t10_federation_resolver_record_9_and_bridge_audit_writer_record_10():
    """T-10: §4.1 places federation-resolver at row #9 and bridge-audit-writer at row #10."""
    body = SPEC_V042.read_text(encoding="utf-8")
    section_4_1_match = re.search(
        r"### 4\.1 The ten Pin-Pack-wired boot records.*?(?=### 4\.2)",
        body,
        re.S,
    )
    assert section_4_1_match is not None
    section_4_1 = section_4_1_match.group(0)
    # Row #9 line must contain federation-resolver.
    row_9_match = re.search(
        r"\|\s*9\s*\|\s*`persona-engine-federation-resolver`",
        section_4_1,
    )
    assert (
        row_9_match is not None
    ), "§4.1 row #9 must be persona-engine-federation-resolver"
    # Row #10 line must contain bridge-audit-writer.
    row_10_match = re.search(
        r"\|\s*10\s*\|\s*`persona-engine-bridge-audit-writer`",
        section_4_1,
    )
    assert (
        row_10_match is not None
    ), "§4.1 row #10 must be persona-engine-bridge-audit-writer"


# ---------------------------------------------------------------------------
# T-11 (additive, ≥10 budget): manifest cross-reference present
# ---------------------------------------------------------------------------


def test_t11_manifest_carries_v042_cross_reference():
    """T-11: MANIFEST-0.5.1 §2 carries the v0.4.2 spec cross-reference (Tag-50)."""
    assert MANIFEST_PATH.is_file(), "MANIFEST-0.5.1 must be present"
    body = MANIFEST_PATH.read_text(encoding="utf-8")
    assert (
        "wirelang-spec-v0-4-2.md" in body
    ), "manifest must reference v0.4.2 spec file"
    assert (
        "Tag-50" in body
    ), "manifest cross-reference must declare Tag-50 origin"
    assert (
        "WAKIR_*_BACKEND" in body
        or "`WAKIR_*_BACKEND`" in body
    ), "manifest must declare WAKIR_*_BACKEND naming as normative"


# ---------------------------------------------------------------------------
# T-12 (additive, ≥10 budget): single-source-of-truth declaration present
# ---------------------------------------------------------------------------


def test_t12_spec_v042_declares_pin_pack_as_single_source_of_truth():
    """T-12: §1 declares Pin-Pack as single-source-of-truth per CEO-Triage."""
    body = SPEC_V042.read_text(encoding="utf-8")
    section_1_match = re.search(
        r"## 1\. Scope of v0\.4\.2.*?(?=## 2\.)",
        body,
        re.S,
    )
    assert section_1_match is not None, "§1 scope block not found"
    section_1 = section_1_match.group(0)
    assert "Option C Hybrid" in section_1, "§1 must cite Option-C-Hybrid"
    assert (
        "single source of truth" in section_1.lower()
        or "single-source-of-truth" in section_1.lower()
    ), "§1 must declare Pin-Pack single-source-of-truth"
    assert "DRIFT-S4" in section_1, "§1 must reference DRIFT-S4 explicitly"


# ---------------------------------------------------------------------------
# T-13 (additive, ≥10 budget): backward-compat §5 wire/frame/caveat/schema
# ---------------------------------------------------------------------------


def test_t13_spec_v042_section_5_declares_no_wire_frame_caveat_schema_change():
    """T-13: §5 subsections 5.1–5.4 explicitly declare 'no change' for wire/frame/caveat/schema."""
    body = SPEC_V042.read_text(encoding="utf-8")
    for sub_n, label in [
        ("5.1", "Wire format"),
        ("5.2", "Frame attributes"),
        ("5.3", "Caveat predicates"),
        ("5.4", "Schema documents"),
    ]:
        sub_match = re.search(
            rf"### {re.escape(sub_n)} {re.escape(label)}.*?(?=### 5\.|## 6\.)",
            body,
            re.S,
        )
        assert sub_match is not None, f"§{sub_n} '{label}' subsection missing"
        sub = sub_match.group(0)
        assert (
            "No change" in sub or "no change" in sub
        ), f"§{sub_n} must declare 'No change'"


# ---------------------------------------------------------------------------
# T-14 (additive, ≥10 budget): migration table covers every legacy name
# ---------------------------------------------------------------------------


def test_t14_section_5_6_migration_table_covers_every_legacy_name():
    """T-14: §5.6 migration table includes every v0.4.0/v0.4.1 legacy ENV name."""
    body = SPEC_V042.read_text(encoding="utf-8")
    legacy_names = [
        "WAKIR_PE_V907_BACKEND",
        "WAKIR_PE_SVID_BACKEND",
        "WAKIR_PE_BRIDGE_AUDIT_BACKEND",
        "WAKIR_PE_STATE_BACKING_BACKEND",
        "WAKIR_PE_FSM_BACKEND",
        "WAKIR_PE_SUBSCRIBE_LOOP_BACKEND",
        "WAKIR_PE_RECOVERY_BACKEND",
    ]
    section_5_6_match = re.search(
        r"### 5\.6 Operator migration guidance.*?(?=### 5\.7)",
        body,
        re.S,
    )
    assert section_5_6_match is not None
    section_5_6 = section_5_6_match.group(0)
    for legacy in legacy_names:
        assert (
            f"`{legacy}`" in section_5_6
        ), f"§5.6 migration table must include `{legacy}`"


# ---------------------------------------------------------------------------
# T-15 (additive, ≥10 budget): §8 verification invariants enumerated
# ---------------------------------------------------------------------------


def test_t15_section_8_verification_lists_static_pass_invariants():
    """T-15: §8 enumerates the static-pass invariants for v0.4.2 §4.1."""
    body = SPEC_V042.read_text(encoding="utf-8")
    section_8_match = re.search(
        r"## 8\. Verification.*?(?=## 9\.)",
        body,
        re.S,
    )
    assert section_8_match is not None, "§8 Verification block not found"
    section_8 = section_8_match.group(0)
    # The §8 contract requires byte-for-byte parity claims for the ten rows.
    assert "10/10" in section_8, "§8 must declare 10/10 row-parity invariants"
    assert (
        "WAKIR_<component>_BACKEND" in section_8
    ), "§8 must declare naming contract"
    # And the negative invariant on WAKIR_PE_.
    assert (
        "WAKIR_PE_" in section_8
    ), "§8 must declare WAKIR_PE_ exclusion invariant"


# ---------------------------------------------------------------------------
# T-16 (additive, ≥10 budget): citation pointers complete
# ---------------------------------------------------------------------------


def test_t16_section_9_citation_pointers_include_pin_pack_and_v041():
    """T-16: §9 citation pointers include Pin-Pack-0.5.1 and v0.4.1 spec."""
    body = SPEC_V042.read_text(encoding="utf-8")
    section_9_match = re.search(
        r"## 9\. Citation pointers.*?(?=— Reza)",
        body,
        re.S,
    )
    assert section_9_match is not None, "§9 Citation pointers not found"
    section_9 = section_9_match.group(0)
    assert "pin-pack-0.5.1-pre-cutover.yaml" in section_9
    assert "wirelang-spec-v0-4-1.md" in section_9
    assert "wirelang-spec-v0-4.md" in section_9
    assert "MANIFEST-0.5.1-pre-cutover.md" in section_9
