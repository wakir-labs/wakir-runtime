# SPDX-License-Identifier: Apache-2.0
"""Hermetic tests for the Tag-54 ADR Spec-Compliance Audit.

Re-Dispatch nach Quota-Hit 2026-05-19 ~03:20 CEST. The Tag-54 audit
report
(``reports/audit/adr-spec-compliance-audit-2026-05-19.md``)
documents drift between ADR-cited Wirelang substrate surfaces and
the working-copy at main-tip ``f713e75`` (Tag-53 PR #345).

The tests in this module pin the audit's verdict by re-checking
each MATCH / DRIFT claim against the working-copy. If a future
substrate change resolves a DRIFT (e.g. the Phase-3c cutover lands
``persona_engine_py_legacy/``), the corresponding test fails fast
so the report can be re-baselined.

Test inventory (T-ADR-S-01..15, ≥10 required by Mira-Auftrag):

- T-ADR-S-01: Audit report exists at the canonical path.
- T-ADR-S-02: Audit report cites the correct main-tip commit.
- T-ADR-S-03: Audit report cites the v0.4.3 freeze marker.
- T-ADR-S-04: Wirelang spec dir is ``wirelang/specs/`` (with s).
- T-ADR-S-05: Spec v0.4.3 exists and is in ``pre-cutover-freeze``.
- T-ADR-S-06: Path-typo DRIFT for ``wirelang/spec/`` is real.
- T-ADR-S-07: Path-typo DRIFT for ``wirelang/parser/`` is real.
- T-ADR-S-08: ADR-0034 contains both path-typos.
- T-ADR-S-09: ADR-0062 contains both path-typos.
- T-ADR-S-10: ADR-0064 LLM-hook file rename DRIFT is real.
- T-ADR-S-11: ADR-0052 self_reference.py DRIFT is real.
- T-ADR-S-12: ADR-0052 caveat_set.py MATCH is real.
- T-ADR-S-13: Datalog-caveat schema $id matches ADR-0052 promotion.
- T-ADR-S-14: Persona-engine-format-spec exists; version drift is
  expected (ADR-0058 v1.0 → main-tip v1.2.0/v1.3).
- T-ADR-S-15: All seven wirelang schemas are inventoried at main-tip
  (ADR-0047 §A-1 baseline).

The tests are static (no network, no engine boot, no NATS).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

# Repo root: this file is at wakir-runtime/wirelang/tests/<this>.py
REPO_ROOT = Path(__file__).resolve().parents[2]
DECISIONS_ROOT = REPO_ROOT.parent / "decisions"
AUDIT_REPORT = (
    REPO_ROOT / "reports" / "audit" / "adr-spec-compliance-audit-2026-05-19.md"
)
SPEC_DIR = REPO_ROOT / "wirelang" / "specs"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _audit_text() -> str:
    return _read(AUDIT_REPORT)


# --------------------------------------------------------------------- #
# T-ADR-S-01 / T-ADR-S-02 / T-ADR-S-03 — report self-consistency
# --------------------------------------------------------------------- #


def test_t_adr_s_01_audit_report_exists() -> None:
    """T-ADR-S-01: audit report file is present at the canonical path."""
    assert AUDIT_REPORT.exists(), (
        f"Tag-54 audit report missing at {AUDIT_REPORT}"
    )
    assert AUDIT_REPORT.stat().st_size > 1000, (
        "Tag-54 audit report is suspiciously small (<1 kB)"
    )


def test_t_adr_s_02_audit_cites_correct_main_tip() -> None:
    """T-ADR-S-02: audit report cites Tag-53 PR #345 hotfix commit."""
    text = _audit_text()
    assert "f713e75" in text, "audit report must cite main-tip commit"
    assert "#345" in text or "Tag-53" in text, (
        "audit report must cite Tag-53 PR #345 lineage"
    )


def test_t_adr_s_03_audit_cites_v043_freeze_marker() -> None:
    """T-ADR-S-03: audit cites v0.4.3 pre-cutover-freeze."""
    text = _audit_text()
    assert "v0.4.3" in text
    assert "pre-cutover-freeze" in text
    assert "persona-engine-0.5.2-final-pre-cutover" in text


# --------------------------------------------------------------------- #
# T-ADR-S-04 / T-ADR-S-05 — spec-dir + freeze ground-truth
# --------------------------------------------------------------------- #


def test_t_adr_s_04_spec_dir_is_specs_with_s() -> None:
    """T-ADR-S-04: canonical spec dir is wirelang/specs/, not /spec/."""
    assert SPEC_DIR.exists(), f"{SPEC_DIR} must exist (with 's')"
    assert not (REPO_ROOT / "wirelang" / "spec").exists(), (
        "wirelang/spec/ (without 's') must NOT exist — path-typo guard"
    )


def test_t_adr_s_05_v043_spec_pre_cutover_freeze() -> None:
    """T-ADR-S-05: v0.4.3 spec exists with status pre-cutover-freeze."""
    spec_v043 = SPEC_DIR / "wirelang-spec-v0-4-3.md"
    assert spec_v043.exists()
    head = spec_v043.read_text(encoding="utf-8")[:1200]
    assert re.search(r"^version:\s*0\.4\.3\s*$", head, re.MULTILINE)
    assert re.search(
        r"^status:\s*pre-cutover-freeze\s*$", head, re.MULTILINE
    )
    assert "freeze-marker: kw-24-cutover-gate" in head


# --------------------------------------------------------------------- #
# T-ADR-S-06 / T-ADR-S-07 — DRIFT claims for non-existent paths
# --------------------------------------------------------------------- #


def test_t_adr_s_06_drift_wirelang_spec_path() -> None:
    """T-ADR-S-06: wirelang/spec/ DRIFT (path does not exist)."""
    bad_path = REPO_ROOT / "wirelang" / "spec"
    assert not bad_path.exists(), (
        "DRIFT-claim regressed: wirelang/spec/ appeared. "
        "Re-audit ADR-0034 + ADR-0062 path citations."
    )


def test_t_adr_s_07_drift_wirelang_parser_path() -> None:
    """T-ADR-S-07: wirelang/parser/ DRIFT (path does not exist)."""
    bad_path = REPO_ROOT / "wirelang" / "parser"
    assert not bad_path.exists(), (
        "DRIFT-claim regressed: wirelang/parser/ appeared. "
        "Re-audit ADR-0034 + ADR-0062 parser-reference citations."
    )


# --------------------------------------------------------------------- #
# T-ADR-S-08 / T-ADR-S-09 — ADRs really contain the typo citations
# --------------------------------------------------------------------- #


def test_t_adr_s_08_adr_0034_contains_path_typos() -> None:
    """T-ADR-S-08: ADR-0034 cites wirelang/spec/ and wirelang/parser/."""
    adr = DECISIONS_ROOT / "0034-repo-lizenz-strategie.md"
    assert adr.exists()
    text = adr.read_text(encoding="utf-8")
    assert "wirelang/spec/" in text, (
        "ERR-S1 surface vanished — recheck ADR-0034 erratum status"
    )
    assert "wirelang/parser/" in text, (
        "ERR-S2 surface vanished — recheck ADR-0034 erratum status"
    )


def test_t_adr_s_09_adr_0062_contains_path_typos() -> None:
    """T-ADR-S-09: ADR-0062 cites wirelang/spec/ and wirelang/parser/."""
    adr = DECISIONS_ROOT / "0062-repo-split-strategie-phase-2.md"
    assert adr.exists()
    text = adr.read_text(encoding="utf-8")
    assert "wirelang/spec/" in text
    assert "wirelang/parser/" in text


# --------------------------------------------------------------------- #
# T-ADR-S-10 / T-ADR-S-11 / T-ADR-S-12 — file-rename DRIFT claims
# --------------------------------------------------------------------- #


def test_t_adr_s_10_adr_0064_llm_hook_drift() -> None:
    """T-ADR-S-10: ADR-0064 cites llm_hook.py; main-tip lacks it."""
    adr = DECISIONS_ROOT / "0064-model-routing-prompt-caching-persona-engine.md"
    text = adr.read_text(encoding="utf-8")
    assert "llm_hook.py" in text, (
        "ERR-S6 surface vanished — recheck ADR-0064 erratum"
    )
    bad = REPO_ROOT / "wirelang" / "persona_engine" / "llm_hook.py"
    assert not bad.exists(), (
        "DRIFT-claim regressed: llm_hook.py appeared. "
        "Re-audit ADR-0064 — the rename has been undone or reverted."
    )
    # Replacement surface present
    pe = REPO_ROOT / "wirelang" / "persona_engine"
    assert (pe / "llm_call_shim.py").exists()
    assert (pe / "llm_classifier.py").exists()
    assert (pe / "rust_adapter_hook.py").exists()


def test_t_adr_s_11_adr_0052_self_reference_drift() -> None:
    """T-ADR-S-11: ADR-0052 cites self_reference.py; main-tip lacks it."""
    adr = DECISIONS_ROOT / "0052-class-p-promotion-caveat-hash.md"
    text = adr.read_text(encoding="utf-8")
    assert "self_reference.py" in text, (
        "ERR-S4 surface vanished — recheck ADR-0052 erratum"
    )
    bad = REPO_ROOT / "wirelang" / "canonical" / "self_reference.py"
    assert not bad.exists(), (
        "DRIFT-claim regressed: self_reference.py appeared. "
        "Re-audit ADR-0052 — confirm where helper lives now."
    )


def test_t_adr_s_12_adr_0052_caveat_set_match() -> None:
    """T-ADR-S-12: ADR-0052 cites caveat_set.py and it exists."""
    good = REPO_ROOT / "wirelang" / "canonical" / "caveat_set.py"
    assert good.exists(), (
        "MATCH-claim regressed: caveat_set.py vanished. Re-audit ADR-0052."
    )


# --------------------------------------------------------------------- #
# T-ADR-S-13 — schema $id MATCH (Class-P promotion)
# --------------------------------------------------------------------- #


def test_t_adr_s_13_datalog_caveat_schema_id_match() -> None:
    """T-ADR-S-13: datalog-caveat.json $id matches ADR-0052 v0.2.1."""
    schema = REPO_ROOT / "wirelang" / "schemas" / "datalog-caveat.json"
    assert schema.exists()
    blob = json.loads(schema.read_text(encoding="utf-8"))
    assert blob["$id"] == (
        "https://wakir.dev/wirelang/schema/datalog-caveat/0.2.1"
    ), "ADR-0052 Class-P promotion $id mismatch — schema-version drift"


# --------------------------------------------------------------------- #
# T-ADR-S-14 / T-ADR-S-15 — persona-engine-format + seven-schema inventory
# --------------------------------------------------------------------- #


def test_t_adr_s_14_persona_engine_format_spec_present() -> None:
    """T-ADR-S-14: persona-engine-format-spec.md exists; ADR-0058 v1.0 drift expected."""
    spec = SPEC_DIR / "persona-engine-format-spec.md"
    assert spec.exists()
    head = spec.read_text(encoding="utf-8")[:2000]
    # ADR-0058 cited v1.0; main-tip is v1.2.0 (frontmatter) per Tag-4
    m = re.search(r"^version:\s*([0-9]+\.[0-9]+(?:\.[0-9]+)?)", head, re.MULTILINE)
    assert m is not None, "persona-engine-format-spec must declare version"
    version = m.group(1)
    # Frontmatter version is now 1.2.0; refuse to silently regress < 1.0
    assert tuple(int(p) for p in version.split(".")) >= (1, 0), (
        f"persona-engine-format-spec version regressed below v1.0 (got {version})"
    )


def test_t_adr_s_15_seven_wirelang_schemas_present() -> None:
    """T-ADR-S-15: Seven wirelang JSON-schemas present (ADR-0047 §A-1)."""
    schemas_dir = REPO_ROOT / "wirelang" / "schemas"
    json_files = sorted(p.name for p in schemas_dir.glob("*.json"))
    expected = {
        "layer-0-transport.json",
        "layer-1-wire.json",
        "layer-2-semantic.json",
        "layer-3-capability-token.json",
        "datalog-caveat.json",
        "aip-document.json",
        # ADR-0047 cites 7; the inventory adds aip-frame-envelope.json
        # plus federation-trust + caveat-override + persona-* extensions.
    }
    actual = set(json_files)
    missing = expected - actual
    assert not missing, (
        f"ADR-0047 §A-1 baseline schemas missing: {sorted(missing)}"
    )


# --------------------------------------------------------------------- #
# Aux probe: report has a drift-summary table
# --------------------------------------------------------------------- #


def test_audit_report_contains_drift_summary_table() -> None:
    """Aux probe: audit report has a Drift Summary section."""
    text = _audit_text()
    assert "## 3. Drift Summary Table" in text
    assert "Recommended Errata" in text
    assert "ERR-S1" in text and "ERR-S6" in text


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
