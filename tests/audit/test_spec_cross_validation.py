# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Hermetic Tag-78 tests for the Wirelang-Spec v0.4.3 vs v0.4.4-draft
cross-validation helper
``tooling/audit/cross_validate_v0_4_3_vs_v0_4_4.py``.
=========================================================================

Three-axis coverage:

  Axis I   -- Live-spec smoke tests against the in-repo
              v0.4.3 + v0.4.4-draft files. These confirm that the
              helper passes on the actual cutover-gate substrate.

  Axis II  -- Hermetic mutilation tests using temporary fixture
              specs that violate one cross-validation invariant
              at a time. These confirm that each family of the
              helper has actual detection power (not just
              accidentally-passing regexes).

  Axis III -- Direct unit tests against the helper's internal
              functions (parse_frontmatter, collect_section_anchors,
              find_section_6_bounds, check_family_a..d) using
              minimal inline fixtures.

Test inventory (>=15 hermetic, stdlib + pytest):

  T01 -- Helper module is importable.
  T02 -- Live-spec helper exit-0 (smoke).
  T03 -- Live-spec helper stdout banner names all four families.
  T04 -- Family A: Pin-Pack row removal in v0.4.4-draft fixture
         triggers helper failure.
  T05 -- Family A: Pin-Pack source-of-truth pointer missing in
         v0.4.3 fixture triggers helper failure.
  T06 -- Family B: section reorder in v0.4.4-draft fixture
         (swap §7 and §8) triggers helper failure.
  T07 -- Family C: RES-D1 anchor leaked into v0.4.3 fixture
         triggers helper failure.
  T08 -- Family C: RES-D3 missing from v0.4.4-draft fixture
         triggers helper failure.
  T09 -- Family C: §6 missing from v0.4.4-draft fixture
         triggers helper failure.
  T10 -- Family C: draft-isolation invariant phrase removed
         triggers helper failure.
  T11 -- Family D: v0.4.4-draft status collides with v0.4.3
         status triggers helper failure.
  T12 -- Family D: v0.4.4-draft extends mismatches v0.4.3 version
         triggers helper failure.
  T13 -- Family D: v0.4.4-draft freeze-marker non-null triggers
         helper failure.
  T14 -- Unit: parse_frontmatter handles SPDX-comment + ---
         block correctly.
  T15 -- Unit: collect_section_anchors returns anchors in source
         order.
  T16 -- Unit: find_section_6_bounds returns (-1, -1) when §6
         absent.
  T17 -- Helper --quiet flag suppresses stdout banner on green.
  T18 -- Helper exits non-zero with stderr message when v0.4.3
         path does not exist.
  T19 -- Helper accepts custom --v043 / --v044 paths.
  T20 -- Live spec: v0.4.3 contains zero RES-Dn anchors
         (direct corpus invariant — load-bearing for Family C).
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = (
    REPO_ROOT / "tooling" / "audit" / "cross_validate_v0_4_3_vs_v0_4_4.py"
)
SPEC_V043 = REPO_ROOT / "wirelang" / "specs" / "wirelang-spec-v0-4-3.md"
SPEC_V044 = REPO_ROOT / "wirelang" / "specs" / "wirelang-spec-v0-4-4-draft.md"


def _load_helper_module():
    spec = importlib.util.spec_from_file_location(
        "cross_validate_v0_4_3_vs_v0_4_4", HELPER_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_helper(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HELPER_PATH), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )


# --- Axis I: Live-spec smoke ------------------------------------------------


def test_T01_helper_importable():
    """T01: The helper module is importable (parse + load smoke)."""
    mod = _load_helper_module()
    assert hasattr(mod, "cross_validate")
    assert hasattr(mod, "check_family_a")
    assert hasattr(mod, "check_family_b")
    assert hasattr(mod, "check_family_c")
    assert hasattr(mod, "check_family_d")


def test_T02_live_specs_pass():
    """T02: Live in-repo specs pass cross-validation (exit 0)."""
    if not SPEC_V043.exists() or not SPEC_V044.exists():
        pytest.skip("live specs missing — skip live smoke test")
    cp = _run_helper()
    assert cp.returncode == 0, (
        f"live smoke FAILED. stdout={cp.stdout!r} stderr={cp.stderr!r}"
    )


def test_T03_live_specs_banner_lists_four_families():
    """T03: On green, stdout names all four families A/B/C/D."""
    if not SPEC_V043.exists() or not SPEC_V044.exists():
        pytest.skip("live specs missing")
    cp = _run_helper()
    assert cp.returncode == 0
    assert "Family A" in cp.stdout
    assert "Family B" in cp.stdout
    assert "Family C" in cp.stdout
    assert "Family D" in cp.stdout


# --- Axis II: Hermetic mutilation fixtures --------------------------------


# REUSE-IgnoreStart
# The fixture builders below embed SPDX-License-Identifier strings
# as TEST SUBSTANCE (frontmatter-bearing markdown templates). The
# strings are assertions, not declarations for this file. Per the
# REUSE.toml false-positive carve-out pattern (see
# tests/wat/test_hash_consistency.py and
# tests/infra/test_spdx_header_consistency.py), we wrap the literals
# in REUSE-Ignore brackets so the lint scanner does not parse them
# as this file's license header.


def _make_v043_fixture(tmp_path: Path) -> Path:
    """Write a minimal-but-valid v0.4.3 fixture file."""
    body = (
        "<!-- SPDX" + "-License-Identifier: CC-BY-4.0 -->\n"
        "\n"
        "---\n"
        "spec: wirelang\n"
        "version: 0.4.3\n"
        "status: pre-cutover-freeze\n"
        "extends: 0.4.2\n"
        "freeze-marker: kw-24-cutover-gate\n"
        "freeze-anchor: persona-engine-0.5.2-final-pre-cutover\n"
        "---\n"
        "\n"
        "# Wirelang Specification v0.4.3\n"
        "\n"
        "## 1. Scope\n"
        "\n"
        "## 2. Conformance keywords\n"
        "\n"
        "## 3. §3 no change\n"
        "\n"
        "## 4. §4 no change\n"
        "\n"
        "### 4.1 Carry-forward inventory\n"
        "\n"
        "| Pin-Pack record # | Component | Selector ENV |\n"
        "|---|---|---|\n"
        "| 1 | `persona-engine-recovery` | `WAKIR_RECOVERY_BACKEND` |\n"
        "| 2 | `persona-engine-state-backing` | `WAKIR_STATE_BACKING_BACKEND` |\n"
        "| 3 | `persona-engine-fsm` | `WAKIR_FSM_BACKEND` |\n"
        "| 4 | `persona-engine-v907-verify` | `WAKIR_V907_VERIFY_BACKEND` |\n"
        "| 5 | `persona-engine-bridge-diff` | `WAKIR_BRIDGE_DIFF_BACKEND` |\n"
        "| 6 | `persona-engine-subscribe-loop` | `WAKIR_SUBSCRIBE_LOOP_BACKEND` |\n"
        "| 7 | `persona-engine-anchor-emitter` | `WAKIR_ANCHOR_EMITTER_BACKEND` |\n"
        "| 8 | `persona-engine-svid-workload-identity` | `WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND` |\n"
        "| 9 | `persona-engine-federation-resolver` | `WAKIR_FEDERATION_RESOLVER_BACKEND` |\n"
        "| 10 | `persona-engine-bridge-audit-writer` | `WAKIR_BRIDGE_AUDIT_WRITER_BACKEND` |\n"
        "\n"
        "Pin-Pack source-of-truth at "
        "`infra/persona-engine/pin-pack-0.5.1-pre-cutover.yaml`.\n"
        "\n"
        "## 5. §5 no change\n"
        "## 6. Freeze-marker semantics\n"
        "## 7. Backward compatibility\n"
        "## 8. Audit conformance\n"
        "## 9. Citation pointers\n"
    )
    p = tmp_path / "v0.4.3.md"
    p.write_text(body, encoding="utf-8")
    return p


def _make_v044_fixture(tmp_path: Path) -> Path:
    """Write a minimal-but-valid v0.4.4-draft fixture file."""
    body = (
        "<!-- SPDX" + "-License-Identifier: CC-BY-4.0 -->\n"
        "\n"
        "---\n"
        "spec: wirelang\n"
        "version: 0.4.4-draft\n"
        "status: post-cutover-reserve-draft\n"
        "parent: wirelang-spec-v0-4-3\n"
        "extends: 0.4.3\n"
        "freeze-marker: null\n"
        "freeze-anchor: null\n"
        "---\n"
        "\n"
        "# Wirelang Specification v0.4.4-draft\n"
        "\n"
        "Verifiers MUST reject any frame carrying "
        "`wirelangversion: 0.4.4-draft`.\n"
        "Producers MUST NOT emit a frame carrying "
        "`wirelangversion: 0.4.4-draft`.\n"
        "Operators MUST NOT switch a Pin-Pack record to a draft backend.\n"
        "\n"
        "## 1. Scope\n"
        "RES-D1 RES-D2 RES-D3 RES-D4 RES-D5 (scope table mentions)\n"
        "\n"
        "## 2. Conformance keywords\n"
        "\n"
        "## 3. §3 carry-forward\n"
        "\n"
        "## 4. §4 carry-forward\n"
        "\n"
        "### 4.1 Carry-forward of the ten Pin-Pack-0.5.1 boot records\n"
        "\n"
        "| Pin-Pack record # | Component | Selector ENV |\n"
        "|---|---|---|\n"
        "| 1 | `persona-engine-recovery` | `WAKIR_RECOVERY_BACKEND` |\n"
        "| 2 | `persona-engine-state-backing` | `WAKIR_STATE_BACKING_BACKEND` |\n"
        "| 3 | `persona-engine-fsm` | `WAKIR_FSM_BACKEND` |\n"
        "| 4 | `persona-engine-v907-verify` | `WAKIR_V907_VERIFY_BACKEND` |\n"
        "| 5 | `persona-engine-bridge-diff` | `WAKIR_BRIDGE_DIFF_BACKEND` |\n"
        "| 6 | `persona-engine-subscribe-loop` | `WAKIR_SUBSCRIBE_LOOP_BACKEND` |\n"
        "| 7 | `persona-engine-anchor-emitter` | `WAKIR_ANCHOR_EMITTER_BACKEND` |\n"
        "| 8 | `persona-engine-svid-workload-identity` | `WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND` |\n"
        "| 9 | `persona-engine-federation-resolver` | `WAKIR_FEDERATION_RESOLVER_BACKEND` |\n"
        "| 10 | `persona-engine-bridge-audit-writer` | `WAKIR_BRIDGE_AUDIT_WRITER_BACKEND` |\n"
        "\n"
        "Pin-Pack source-of-truth at "
        "`infra/persona-engine/pin-pack-0.5.1-pre-cutover.yaml`.\n"
        "\n"
        "## 5. §5 carry-forward\n"
        "## 6. Reserve substrate\n"
        "### 6.1 RES-D1: identity-substrate-evolution\n"
        "### 6.2 RES-D2: capability-token-refinements\n"
        "### 6.3 RES-D3: bridge-audit-cleanup\n"
        "### 6.4 RES-D4: schema-registry-v2-prep\n"
        "### 6.5 RES-D5: recovery-drill-leaf-projection-v2\n"
        "## 7. Backward compatibility\n"
        "## 8. Audit conformance\n"
        "## 9. Citation pointers\n"
    )
    p = tmp_path / "v0.4.4-draft.md"
    p.write_text(body, encoding="utf-8")
    return p


def test_T04_family_a_pin_pack_row_removed_fails(tmp_path):
    """T04: Removing a Pin-Pack row in v0.4.4-draft fixture fails."""
    v043 = _make_v043_fixture(tmp_path)
    v044 = _make_v044_fixture(tmp_path)
    body = v044.read_text(encoding="utf-8")
    # Remove the row #5 (bridge-diff).
    body_mut = body.replace(
        "| 5 | `persona-engine-bridge-diff` | `WAKIR_BRIDGE_DIFF_BACKEND` |\n",
        "",
        1,
    )
    v044.write_text(body_mut, encoding="utf-8")
    cp = _run_helper("--v043", str(v043), "--v044", str(v044))
    assert cp.returncode == 1
    assert "A." in cp.stderr
    assert "persona-engine-bridge-diff" in cp.stderr


def test_T05_family_a_pinpack_pointer_missing_fails(tmp_path):
    """T05: Pin-Pack source-of-truth pointer missing from v0.4.3 fails."""
    v043 = _make_v043_fixture(tmp_path)
    v044 = _make_v044_fixture(tmp_path)
    body = v043.read_text(encoding="utf-8")
    body_mut = body.replace(
        "infra/persona-engine/pin-pack-0.5.1-pre-cutover.yaml",
        "infra/persona-engine/some-other-file.yaml",
        1,
    )
    v043.write_text(body_mut, encoding="utf-8")
    cp = _run_helper("--v043", str(v043), "--v044", str(v044))
    assert cp.returncode == 1
    assert "A.11" in cp.stderr


def test_T06_family_b_section_reorder_fails(tmp_path):
    """T06: Swapping §7 and §8 headings in v0.4.4-draft fails Family B."""
    v043 = _make_v043_fixture(tmp_path)
    v044 = _make_v044_fixture(tmp_path)
    body = v044.read_text(encoding="utf-8")
    body_mut = body.replace(
        "## 7. Backward compatibility\n## 8. Audit conformance\n",
        "## 8. Audit conformance\n## 7. Backward compatibility\n",
        1,
    )
    v044.write_text(body_mut, encoding="utf-8")
    cp = _run_helper("--v043", str(v043), "--v044", str(v044))
    assert cp.returncode == 1
    assert "B.1" in cp.stderr


def test_T07_family_c_res_d_leak_into_v043_fails(tmp_path):
    """T07: RES-D1 leaking into v0.4.3 triggers Family C failure."""
    v043 = _make_v043_fixture(tmp_path)
    v044 = _make_v044_fixture(tmp_path)
    body = v043.read_text(encoding="utf-8")
    body_mut = body.replace(
        "## 6. Freeze-marker semantics\n",
        "## 6. Freeze-marker semantics\n\nRES-D1 leaked here.\n",
        1,
    )
    v043.write_text(body_mut, encoding="utf-8")
    cp = _run_helper("--v043", str(v043), "--v044", str(v044))
    assert cp.returncode == 1
    assert "C.1" in cp.stderr


def test_T08_family_c_res_d3_missing_in_draft_fails(tmp_path):
    """T08: RES-D3 missing from v0.4.4-draft triggers Family C failure."""
    v043 = _make_v043_fixture(tmp_path)
    v044 = _make_v044_fixture(tmp_path)
    body = v044.read_text(encoding="utf-8")
    body_mut = body.replace("RES-D3", "RES-DX-removed")
    v044.write_text(body_mut, encoding="utf-8")
    cp = _run_helper("--v043", str(v043), "--v044", str(v044))
    assert cp.returncode == 1
    assert "C.2" in cp.stderr
    assert "RES-D3" in cp.stderr


def test_T09_family_c_section_6_missing_fails(tmp_path):
    """T09: §6 absent from v0.4.4-draft triggers Family C + B failure."""
    v043 = _make_v043_fixture(tmp_path)
    v044 = _make_v044_fixture(tmp_path)
    body = v044.read_text(encoding="utf-8")
    # Replace all RES-D-bearing §6 sub-section headings with §99 (out of canon).
    body_mut = body.replace("## 6. Reserve substrate\n", "")
    body_mut = body_mut.replace("### 6.1 ", "### 99.1 ")
    body_mut = body_mut.replace("### 6.2 ", "### 99.2 ")
    body_mut = body_mut.replace("### 6.3 ", "### 99.3 ")
    body_mut = body_mut.replace("### 6.4 ", "### 99.4 ")
    body_mut = body_mut.replace("### 6.5 ", "### 99.5 ")
    v044.write_text(body_mut, encoding="utf-8")
    cp = _run_helper("--v043", str(v043), "--v044", str(v044))
    assert cp.returncode == 1
    # Either C.3 (section absent) or B.1 (canonical order broken) MUST fire.
    assert ("C.3" in cp.stderr) or ("B.1" in cp.stderr)


def test_T10_family_c_isolation_invariant_phrase_missing_fails(tmp_path):
    """T10: Removing the draft-isolation phrase triggers C.4."""
    v043 = _make_v043_fixture(tmp_path)
    v044 = _make_v044_fixture(tmp_path)
    body = v044.read_text(encoding="utf-8")
    body_mut = body.replace(
        "Operators MUST NOT switch a Pin-Pack record to a draft backend.",
        "Operators may consider switching at their leisure.",
    )
    v044.write_text(body_mut, encoding="utf-8")
    cp = _run_helper("--v043", str(v043), "--v044", str(v044))
    assert cp.returncode == 1
    assert "C.4" in cp.stderr


def test_T11_family_d_status_collision_fails(tmp_path):
    """T11: v0.4.4-draft status colliding with v0.4.3 triggers D.3."""
    v043 = _make_v043_fixture(tmp_path)
    v044 = _make_v044_fixture(tmp_path)
    body = v044.read_text(encoding="utf-8")
    body_mut = body.replace(
        "status: post-cutover-reserve-draft",
        "status: pre-cutover-freeze",
    )
    v044.write_text(body_mut, encoding="utf-8")
    cp = _run_helper("--v043", str(v043), "--v044", str(v044))
    assert cp.returncode == 1
    assert "D.3" in cp.stderr or "D.2" in cp.stderr


def test_T12_family_d_extends_mismatch_fails(tmp_path):
    """T12: v0.4.4-draft extends != v0.4.3 version triggers D.4 / D.2."""
    v043 = _make_v043_fixture(tmp_path)
    v044 = _make_v044_fixture(tmp_path)
    body = v044.read_text(encoding="utf-8")
    body_mut = body.replace("extends: 0.4.3", "extends: 0.4.7")
    v044.write_text(body_mut, encoding="utf-8")
    cp = _run_helper("--v043", str(v043), "--v044", str(v044))
    assert cp.returncode == 1
    assert ("D.4" in cp.stderr) or ("D.2" in cp.stderr)


def test_T13_family_d_draft_freeze_marker_nonnull_fails(tmp_path):
    """T13: v0.4.4-draft with non-null freeze-marker triggers D.5."""
    v043 = _make_v043_fixture(tmp_path)
    v044 = _make_v044_fixture(tmp_path)
    body = v044.read_text(encoding="utf-8")
    body_mut = body.replace(
        "freeze-marker: null",
        "freeze-marker: kw-24-cutover-gate",
    )
    v044.write_text(body_mut, encoding="utf-8")
    cp = _run_helper("--v043", str(v043), "--v044", str(v044))
    assert cp.returncode == 1
    assert "D.5" in cp.stderr


# --- Axis III: Unit tests against helper internals -------------------------


def test_T14_parse_frontmatter_skips_spdx_comment(tmp_path):
    """T14: parse_frontmatter handles the SPDX HTML comment prefix."""
    mod = _load_helper_module()
    sample = (
        "<!-- SPDX" + "-License-Identifier: CC-BY-4.0 -->\n\n"
        "---\n"
        "spec: wirelang\n"
        "version: 0.4.3\n"
        "status: pre-cutover-freeze\n"
        "freeze-marker: kw-24-cutover-gate\n"
        "---\n\nbody\n"
    )
    fm = mod.parse_frontmatter(sample)
    assert fm["version"] == "0.4.3"
    assert fm["status"] == "pre-cutover-freeze"
    assert fm["freeze-marker"] == "kw-24-cutover-gate"


def test_T15_collect_section_anchors_preserves_source_order():
    """T15: collect_section_anchors returns anchors in document order."""
    mod = _load_helper_module()
    text = (
        "# Title\n\n"
        "## 1. Scope\n## 2. Conformance\n"
        "## 4. Skipped on purpose\n## 3. Out of order\n"
    )
    anchors = mod.collect_section_anchors(text)
    assert anchors == ["1.", "2.", "4.", "3."]


def test_T16_find_section_6_bounds_handles_missing_section():
    """T16: find_section_6_bounds returns (-1, -1) when §6 absent."""
    mod = _load_helper_module()
    text = "## 1. A\n## 2. B\n## 7. C\n"
    start, end = mod.find_section_6_bounds(text)
    assert start == -1
    assert end == -1


def test_T17_quiet_flag_suppresses_banner():
    """T17: --quiet suppresses the green-banner stdout on success."""
    if not SPEC_V043.exists() or not SPEC_V044.exists():
        pytest.skip("live specs missing")
    cp = _run_helper("--quiet")
    assert cp.returncode == 0
    assert cp.stdout.strip() == ""


def test_T18_missing_path_exits_nonzero(tmp_path):
    """T18: Helper exits non-zero with stderr message for missing path."""
    cp = _run_helper(
        "--v043",
        str(tmp_path / "does-not-exist-v043.md"),
        "--v044",
        str(tmp_path / "does-not-exist-v044.md"),
    )
    assert cp.returncode == 1
    assert "not found" in cp.stderr


def test_T19_helper_accepts_custom_paths(tmp_path):
    """T19: Helper accepts --v043 / --v044 custom path overrides."""
    v043 = _make_v043_fixture(tmp_path)
    v044 = _make_v044_fixture(tmp_path)
    cp = _run_helper("--v043", str(v043), "--v044", str(v044))
    assert cp.returncode == 0, f"stderr={cp.stderr!r}"


def test_T20_live_v043_contains_zero_res_d_anchors():
    """T20: Live v0.4.3 contains NONE of the RES-Dn anchors
    (load-bearing Family-C corpus invariant — verified at the
    source, independent of helper internals).
    """
    if not SPEC_V043.exists():
        pytest.skip("live v0.4.3 spec missing")
    body = SPEC_V043.read_text(encoding="utf-8")
    for anchor in ("RES-D1", "RES-D2", "RES-D3", "RES-D4", "RES-D5"):
        assert anchor not in body, (
            f"v0.4.3 contamination — anchor '{anchor}' "
            "found in pre-cutover-freeze spec"
        )


# REUSE-IgnoreEnd
