# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic Tag-47 audit: Phase-3a 15-crate consistency.

Re-runs the substrate checks documented in
``reports/audit/phase-3a-15-crate-consistency-2026-05-19.md`` against
the working tree.

Hermetic discipline:

- No NATS, no engine boot, no Rust build, no network.
- No import of ``wirelang.*`` runtime modules.
- Pure stdlib + pytest tree-walk over the working copy.

Twelve test functions cover the twelve assertion targets enumerated
in the audit report §9.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest


# ---------------------------------------------------------------------
# Substrate constants (mirror report §3, §5).
# ---------------------------------------------------------------------

# Spec v0.4 §3.1 — the fifteen Phase-3a-foundation crates.
SPEC_15: tuple[str, ...] = (
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
)


# Spec §3.3 Foundation crates — no Python sibling expected.
FOUNDATION_NO_PY: frozenset[str] = frozenset({"persona-canonical-form-yaml"})


# Crate -> Python sibling path (relative to repo root). Foundation
# crates are absent. The "persona-engine-recovery-replay" entry
# points at the recovery-workflow canonical sibling per the spec
# §3.1 row #14 companion designation.
PY_SIBLING: dict[str, str] = {
    "persona-canonical-form": "wirelang/persona/persona_canonical_form.py",
    "persona-hash": "wirelang/persona/persona_hash.py",
    "persona-engine-v907-verify": "wirelang/persona_engine/v907_verify_canonical.py",
    "persona-engine-svid-workload-identity": "wirelang/persona_engine/svid_workload_identity.py",
    "persona-engine-bridge-audit-writer": "wirelang/persona_engine/bridge_audit_writer.py",
    "persona-engine-bridge-audit-replay": "wirelang/persona_engine/bridge_audit_replay.py",
    "persona-engine-bridge-diff": "wirelang/persona_engine/bridge_audit_diff_engine.py",
    "persona-engine-bridge-forward": "wirelang/cli/bridge_forward.py",
    "persona-engine-state-backing": "wirelang/persona_engine/state_backing.py",
    "persona-engine-fsm": "wirelang/persona_engine/lifecycle_state_machine.py",
    "persona-engine-subscribe-loop": "wirelang/persona_engine/nats_subscribe_loop.py",
    "persona-engine-recovery": "wirelang/persona_engine/recovery_workflow.py",
    "persona-engine-recovery-replay": "wirelang/persona_engine/recovery_workflow_canonical.py",
    "persona-engine-anchor-emitter": "wirelang/persona_engine/anchor_emitter.py",
}


# Crate -> cross-lang fixture directory (relative to repo root).
# Foundation crates absent. Companion crates share the leader's
# directory (recovery-replay shares recovery's).
FIXTURE_DIR: dict[str, str] = {
    "persona-canonical-form": "tests/fixtures/jcs-leaf-vectors",
    "persona-hash": "tests/fixtures/v907-verify-cross-lang",
    "persona-engine-v907-verify": "tests/fixtures/v907-verify-cross-lang",
    "persona-engine-svid-workload-identity": "tests/fixtures/svid-workload-cross-lang",
    "persona-engine-bridge-audit-writer": "tests/fixtures/bridge-audit-writer-cross-lang",
    "persona-engine-bridge-audit-replay": "tests/fixtures/bridge-audit-replay-cross-lang",
    "persona-engine-bridge-diff": "tests/fixtures/bridge-audit-diff-engine-cross-lang",
    "persona-engine-bridge-forward": "tests/fixtures/bridge-forward-cross-lang",
    "persona-engine-state-backing": "tests/fixtures/state-backing-cross-lang",
    "persona-engine-fsm": "tests/fixtures/lifecycle-state-machine-cross-lang",
    "persona-engine-subscribe-loop": "tests/fixtures/subscribe-loop-cross-lang",
    "persona-engine-recovery": "tests/fixtures/recovery-workflow-cross-lang",
    "persona-engine-recovery-replay": "tests/fixtures/recovery-workflow-cross-lang",
    "persona-engine-anchor-emitter": "tests/fixtures/anchor-emitter-cross-lang",
}


# Crate -> cross-lang parity test path. Companions share leader.
PARITY_TEST: dict[str, str] = {
    "persona-canonical-form": "wirelang/tests/test_persona_canonical_form_jcs.py",
    "persona-hash": "wirelang/tests/test_persona_hash.py",
    "persona-engine-v907-verify": (
        "wirelang/tests/persona_engine/test_v907_verify_cross_lang_parity.py"
    ),
    "persona-engine-svid-workload-identity": (
        "tests/identity/test_svid_workload_identity_cross_lang_parity.py"
    ),
    "persona-engine-bridge-audit-writer": (
        "tests/persona_engine/test_bridge_audit_writer_cross_lang_parity.py"
    ),
    "persona-engine-bridge-audit-replay": (
        "wirelang/tests/persona_engine/test_bridge_audit_replay_cross_lang_parity.py"
    ),
    "persona-engine-bridge-diff": (
        "wirelang/tests/persona_engine/test_bridge_audit_diff_engine_cross_lang_parity.py"
    ),
    "persona-engine-bridge-forward": (
        "tests/cli/test_bridge_forward_cross_lang_parity.py"
    ),
    "persona-engine-state-backing": (
        "wirelang/tests/persona_engine/test_state_backing_cross_lang_parity.py"
    ),
    "persona-engine-fsm": (
        "wirelang/tests/persona_engine/test_lifecycle_state_machine_cross_lang_parity.py"
    ),
    "persona-engine-subscribe-loop": (
        "wirelang/tests/persona_engine/test_subscribe_loop_cross_lang_parity.py"
    ),
    "persona-engine-recovery": (
        "wirelang/tests/persona_engine/test_recovery_workflow_cross_lang_parity.py"
    ),
    "persona-engine-recovery-replay": (
        # Companion: shares recovery's parity test.
        "wirelang/tests/persona_engine/test_recovery_workflow_cross_lang_parity.py"
    ),
    "persona-engine-anchor-emitter": (
        "tests/wat/test_anchor_emitter_cross_lang_parity.py"
    ),
}


# Expected pin-pack ↔ spec §3.1 symmetric difference (report §4).
SPEC_ONLY: frozenset[str] = frozenset(
    {
        "persona-canonical-form",
        "persona-canonical-form-yaml",
        "persona-hash",
        "persona-engine-recovery-replay",
    }
)
PIN_PACK_ONLY: frozenset[str] = frozenset(
    {
        "persona-engine-anchor-submit-worker",
        "persona-engine-federation-frame-parser",
        "persona-engine-federation-resolver",
        "persona-engine-frontmatter-parser",
    }
)


# Audit baseline (report §2 banner).
BASELINE_COMMIT: str = "7ada5ab"


REPORT_PATH: str = "reports/audit/phase-3a-15-crate-consistency-2026-05-19.md"


# ---------------------------------------------------------------------
# Helpers (hermetic — no network, no engine import).
# ---------------------------------------------------------------------


def _repo_root() -> Path:
    """Locate the runtime repo root from this test's file path.

    The test lives at ``tests/audit/test_phase_3a_15_crate_consistency.py``;
    the repo root is two parents up.
    """
    return Path(__file__).resolve().parents[2]


def _pin_pack_text() -> str:
    return (
        _repo_root()
        / "infra"
        / "persona-engine"
        / "pin-pack-0.5.0-pre-cutover.yaml"
    ).read_text(encoding="utf-8")


def _pin_pack_crate_names() -> list[str]:
    """Stdlib-only mini-YAML parse: pick out ``- name: <id>`` rows."""
    rows: list[str] = []
    for line in _pin_pack_text().splitlines():
        m = re.match(r"\s*-\s+name:\s+([A-Za-z0-9_-]+)\s*$", line)
        if m:
            rows.append(m.group(1))
    return rows


def _pin_pack_invariant(key: str) -> str:
    """Return the value of ``invariants.<key>`` as a raw string."""
    in_invariants = False
    for line in _pin_pack_text().splitlines():
        if line.startswith("invariants:"):
            in_invariants = True
            continue
        if in_invariants:
            m = re.match(r"\s+" + re.escape(key) + r":\s+(.+)$", line)
            if m:
                return m.group(1).strip().strip('"')
    raise KeyError(f"invariants.{key} not found in pin-pack")


def _manifest_table_rows() -> list[tuple[str, str]]:
    """Parse the manifest §1 table; return (component, crate) pairs.

    The table is a markdown pipe table; the third column is the Python
    authority and the fourth column is the Rust crate. We pick rows
    that begin with ``| <digit> |``.
    """
    text = (
        _repo_root()
        / "wirelang"
        / "persona_engine"
        / "MANIFEST-0.5.0-pre-cutover.md"
    ).read_text(encoding="utf-8")
    rows: list[tuple[str, str]] = []
    pat = re.compile(
        r"^\|\s*(\d+)\s*\|\s*([A-Za-z0-9_-]+)\s*\|"
        r"\s*`?([\w\.]+)`?\s*\|\s*`?([A-Za-z0-9_-]+)`?\s*\|"
    )
    for line in text.splitlines():
        m = pat.match(line.strip())
        if m:
            _idx, component, _py_auth, crate = m.groups()
            rows.append((component, crate))
    return rows


# ---------------------------------------------------------------------
# Hermetic test cases — twelve assertion targets per report §9.
# ---------------------------------------------------------------------


@pytest.mark.parametrize("crate", SPEC_15)
def test_t01_spec_crate_has_cargo_toml(crate: str) -> None:
    """T-01: each spec §3.1 crate has a `Cargo.toml`."""
    root = _repo_root()
    cargo = root / "wirelang-rust" / "crates" / crate / "Cargo.toml"
    assert cargo.is_file(), f"missing Cargo.toml for {crate}"


@pytest.mark.parametrize("crate", SPEC_15)
def test_t02_python_sibling_present(crate: str) -> None:
    """T-02: non-Foundation crates have the expected Python sibling."""
    if crate in FOUNDATION_NO_PY:
        pytest.skip(f"{crate} is Foundation (§3.3); no Py sibling expected")
    sibling_rel = PY_SIBLING[crate]
    p = _repo_root() / sibling_rel
    assert p.is_file(), f"missing Python sibling {sibling_rel} for {crate}"


@pytest.mark.parametrize("crate", SPEC_15)
def test_t03_fixture_dir_present(crate: str) -> None:
    """T-03: non-Foundation crates have the expected fixture dir."""
    if crate in FOUNDATION_NO_PY:
        pytest.skip(f"{crate} is Foundation (§3.3); no fixture dir expected")
    fix_rel = FIXTURE_DIR[crate]
    p = _repo_root() / fix_rel
    assert p.is_dir(), f"missing fixture dir {fix_rel} for {crate}"


@pytest.mark.parametrize("crate", SPEC_15)
def test_t04_parity_test_present(crate: str) -> None:
    """T-04: each crate has a cross-lang parity test (non-Foundation)."""
    if crate in FOUNDATION_NO_PY:
        pytest.skip(f"{crate} is Foundation (§3.3); no parity test expected")
    parity_rel = PARITY_TEST[crate]
    p = _repo_root() / parity_rel
    assert p.is_file(), f"missing parity test {parity_rel} for {crate}"


def test_t05_pin_pack_total_fifteen() -> None:
    """T-05: pin-pack YAML enumerates exactly 15 crates."""
    names = _pin_pack_crate_names()
    assert len(names) == 15, (
        f"pin-pack crate count = {len(names)}; expected 15"
    )


def test_t06_pin_pack_invariant_total_fifteen() -> None:
    """T-06: pin-pack invariants.total_pin_pack_crates == 15."""
    v = _pin_pack_invariant("total_pin_pack_crates")
    assert v == "15", (
        f"pin-pack invariants.total_pin_pack_crates = {v!r}; expected '15'"
    )


def test_t07_symmetric_difference_matches_report() -> None:
    """T-07: regression-pin the spec ↔ pin-pack symmetric difference.

    The four-on-four pattern documented in audit report §4 must be
    stable; any change to either side requires a report update.
    """
    pin = set(_pin_pack_crate_names())
    spec = set(SPEC_15)
    spec_only = spec - pin
    pin_only = pin - spec
    assert spec_only == set(SPEC_ONLY), (
        f"spec-only set drifted: got {sorted(spec_only)} "
        f"expected {sorted(SPEC_ONLY)}"
    )
    assert pin_only == set(PIN_PACK_ONLY), (
        f"pin-pack-only set drifted: got {sorted(pin_only)} "
        f"expected {sorted(PIN_PACK_ONLY)}"
    )


def test_t08_workspace_crate_count_32() -> None:
    """T-08: 32 crates in the workspace = 15 spec + 17 tooling."""
    crates_dir = _repo_root() / "wirelang-rust" / "crates"
    actual = sorted(p.name for p in crates_dir.iterdir() if p.is_dir())
    assert len(actual) == 32, (
        f"workspace has {len(actual)} crates, expected 32. "
        f"crates: {actual}"
    )
    spec_present = [c for c in SPEC_15 if c in actual]
    assert len(spec_present) == 15, (
        f"only {len(spec_present)} spec crates present in workspace; "
        f"missing: {set(SPEC_15) - set(actual)}"
    )


@pytest.mark.parametrize("crate", SPEC_15)
def test_t09_crate_has_source(crate: str) -> None:
    """T-09: no spec §3.1 crate is a zero-source skeleton."""
    src_dir = _repo_root() / "wirelang-rust" / "crates" / crate / "src"
    rs_files = sorted(src_dir.glob("**/*.rs"))
    assert rs_files, f"{crate}/src has no .rs files"


@pytest.mark.parametrize("crate", SPEC_15)
def test_t10_crate_lib_or_main_non_empty(crate: str) -> None:
    """T-10: each crate's `lib.rs` or `main.rs` has > 50 bytes."""
    src_dir = _repo_root() / "wirelang-rust" / "crates" / crate / "src"
    lib = src_dir / "lib.rs"
    main = src_dir / "main.rs"
    target: Path
    if lib.is_file():
        target = lib
    elif main.is_file():
        target = main
    else:
        # Fall back to the first .rs file in src/.
        first = next(iter(sorted(src_dir.glob("**/*.rs"))), None)
        assert first is not None, f"{crate}: no entry .rs in src/"
        target = first
    size = target.stat().st_size
    assert size > 50, (
        f"{crate}/src/{target.name} is essentially empty: {size} bytes"
    )


def test_t11_manifest_nine_boot_records_matches_pin_pack_wired() -> None:
    """T-11: manifest §1 has 9 records and matches pin-pack `boot_wired_crates`.

    The manifest's first 9 markdown table rows enumerate the 9
    BackendDecision records emitted at cold-start. The pin-pack's
    `boot_wired_crates` section enumerates 9 crates with `record: N`.
    The crate-name set must coincide.
    """
    rows = _manifest_table_rows()
    assert len(rows) == 9, (
        f"manifest table has {len(rows)} rows; expected 9"
    )
    manifest_crates = {crate for _component, crate in rows}

    # Extract pin-pack wired crates: rows under `boot_wired_crates:`
    # up to (but not including) the `boot_unwired_crates:` header.
    text = _pin_pack_text()
    wired_block_start = text.index("boot_wired_crates:")
    unwired_block_start = text.index("boot_unwired_crates:")
    wired_block = text[wired_block_start:unwired_block_start]
    wired_pin_pack = {
        m.group(1)
        for m in re.finditer(
            r"^\s+-\s+name:\s+([A-Za-z0-9_-]+)\s*$",
            wired_block,
            re.MULTILINE,
        )
    }
    assert len(wired_pin_pack) == 9, (
        f"pin-pack wired set has {len(wired_pin_pack)} entries; "
        f"expected 9. got={sorted(wired_pin_pack)}"
    )
    assert manifest_crates == wired_pin_pack, (
        "manifest 9 boot-records ≠ pin-pack 9 wired crates. "
        f"manifest={sorted(manifest_crates)} "
        f"pin-pack-wired={sorted(wired_pin_pack)}"
    )


def test_t12_audit_report_exists_and_cites_baseline() -> None:
    """T-12: this audit's own report exists and cites baseline 7ada5ab."""
    p = _repo_root() / REPORT_PATH
    assert p.is_file(), f"missing audit report at {REPORT_PATH}"
    body = p.read_text(encoding="utf-8")
    assert BASELINE_COMMIT in body, (
        f"audit report does not cite baseline commit {BASELINE_COMMIT}"
    )
    # Also assert the report references the spec under audit.
    assert "wirelang-spec-v0-4.md" in body, (
        "audit report does not name the spec under audit"
    )
    # And the pin-pack substrate.
    assert "pin-pack-0.5.0-pre-cutover.yaml" in body, (
        "audit report does not name the pin-pack substrate"
    )
