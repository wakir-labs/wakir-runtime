# SPDX-License-Identifier: Apache-2.0
"""Hermetic tests for the Tag-55 ADR-Errata addendum (ERR-S1..S6).

The Tag-54 ADR Spec-Compliance Audit (PR #349, Reza) flagged six
path-typo / file-rename drifts in corp-internal ADRs (0034, 0052,
0062, 0064). Tag-55 records the corrected canonical citations in
``docs/decisions/adr-errata-tag-55-path-typo-fixes.md``.

This module pins the errata claims against the runtime working-copy.
Each test verifies one statement in the errata document so that if
the substrate ever moves again the corresponding test fails fast.

Test inventory (T-ERR-01..11, ≥10 required by Mira-Auftrag):

- T-ERR-01: Errata addendum file exists at the canonical path.
- T-ERR-02: Errata addendum lists all six ERR-IDs (S1..S6).
- T-ERR-03: ERR-S1 corrected path ``wirelang/specs/`` exists.
- T-ERR-04: ERR-S2 corrected paths (``builder/`` + ``canonical/`` +
  ``identity/``) all exist.
- T-ERR-05: ERR-S2 ``wirelang/parser/`` does NOT exist (drift-pin).
- T-ERR-06: ERR-S3 cited filename ``0023a-wirelang-tech-spec.md``
  does NOT exist; correction is documented.
- T-ERR-07: ERR-S4 ``self_reference.py`` does NOT exist; the
  ``caveat_hash`` self-reference predicate lives in
  ``wirelang/canonical/caveat_set.py``.
- T-ERR-08: ERR-S6 ``llm_hook.py`` does NOT exist; both cited
  symbols live in ``wirelang/persona_engine/llm_call_shim.py``.
- T-ERR-09: ERR-S6 ``EchoReflectionLlmHook`` symbol present in
  ``llm_call_shim.py`` __all__ export list.
- T-ERR-10: ERR-S6 ``anthropic_messages_hook_phase_3_stub`` symbol
  present in ``llm_call_shim.py`` __all__ export list.
- T-ERR-11: Errata addendum cross-references the Tag-54 audit
  report by canonical path.

The tests are static (no network, no engine boot, no NATS).
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ERRATA_DOC = (
    REPO_ROOT
    / "docs"
    / "decisions"
    / "adr-errata-tag-55-path-typo-fixes.md"
)
AUDIT_REPORT_REL = (
    "reports/audit/adr-spec-compliance-audit-2026-05-19.md"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _errata_text() -> str:
    return _read(ERRATA_DOC)


# --------------------------------------------------------------------- #
# T-ERR-01..02 — errata document self-consistency
# --------------------------------------------------------------------- #


def test_t_err_01_errata_doc_exists() -> None:
    """T-ERR-01: errata addendum file is present at canonical path."""
    assert ERRATA_DOC.exists(), (
        f"Tag-55 errata addendum missing at {ERRATA_DOC}"
    )
    assert ERRATA_DOC.stat().st_size > 1500, (
        "Tag-55 errata addendum is suspiciously small (<1.5 kB)"
    )


def test_t_err_02_all_six_err_ids_listed() -> None:
    """T-ERR-02: errata addendum names all six ERR-IDs (S1..S6)."""
    text = _errata_text()
    for err_id in ("ERR-S1", "ERR-S2", "ERR-S3", "ERR-S4", "ERR-S5", "ERR-S6"):
        assert err_id in text, (
            f"errata addendum missing required ID {err_id}"
        )


# --------------------------------------------------------------------- #
# T-ERR-03..05 — ERR-S1 + ERR-S2 path corrections
# --------------------------------------------------------------------- #


def test_t_err_03_specs_dir_with_s_exists() -> None:
    """T-ERR-03: corrected path ``wirelang/specs/`` exists (with s)."""
    specs_dir = REPO_ROOT / "wirelang" / "specs"
    assert specs_dir.exists() and specs_dir.is_dir(), (
        "wirelang/specs/ must exist (ERR-S1 corrected path)"
    )
    # At least one v0.4.x spec file must be present.
    spec_files = list(specs_dir.glob("wirelang-spec-v0-4*.md"))
    assert spec_files, (
        "wirelang/specs/wirelang-spec-v0-4*.md must exist "
        "(ERR-S1 corrected citation target)"
    )


def test_t_err_04_parser_replacement_paths_all_exist() -> None:
    """T-ERR-04: ERR-S2 corrected substrate (builder/canonical/identity)."""
    for sub in ("builder", "canonical", "identity"):
        path = REPO_ROOT / "wirelang" / sub
        assert path.exists() and path.is_dir(), (
            f"wirelang/{sub}/ must exist (ERR-S2 corrected target)"
        )
        # Each must contain at least one Python module.
        py_files = list(path.glob("*.py"))
        assert py_files, (
            f"wirelang/{sub}/ must contain Python modules (got 0)"
        )


def test_t_err_05_parser_dir_does_not_exist() -> None:
    """T-ERR-05: drift-pin — ``wirelang/parser/`` must remain absent."""
    parser_dir = REPO_ROOT / "wirelang" / "parser"
    assert not parser_dir.exists(), (
        "wirelang/parser/ reappeared — Tag-54 audit DRIFT claim "
        "regressed; ADR-0034 / ADR-0062 ERR-S2 needs re-evaluation"
    )


# --------------------------------------------------------------------- #
# T-ERR-06 — ERR-S3 filename correction
# --------------------------------------------------------------------- #


def test_t_err_06_err_s3_documented() -> None:
    """T-ERR-06: ERR-S3 (0023a- filename) is documented and corrected."""
    text = _errata_text()
    # The cited (non-existent) filename appears in the errata table.
    assert "0023a-wirelang-tech-spec.md" in text, (
        "ERR-S3 must cite the non-existent original filename for traceability"
    )
    # The actual filename appears as the correction.
    assert "0023a-inter-agent-protokoll-layer-architektur.md" in text, (
        "ERR-S3 correction must cite the actual filename "
        "(0023a-inter-agent-protokoll-layer-architektur.md)"
    )


# --------------------------------------------------------------------- #
# T-ERR-07 — ERR-S4 caveat_hash self-reference folded
# --------------------------------------------------------------------- #


def test_t_err_07_self_reference_folded_into_caveat_set() -> None:
    """T-ERR-07: self_reference.py absent; caveat_set.py owns predicate."""
    self_ref = REPO_ROOT / "wirelang" / "canonical" / "self_reference.py"
    caveat_set = REPO_ROOT / "wirelang" / "canonical" / "caveat_set.py"
    assert not self_ref.exists(), (
        "wirelang/canonical/self_reference.py reappeared — ERR-S4 "
        "drift-pin regressed; audit needs re-baselining"
    )
    assert caveat_set.exists(), (
        "wirelang/canonical/caveat_set.py must exist (ERR-S4 fold target)"
    )
    body = _read(caveat_set)
    # The Class-P self-reference predicate must be documented in
    # the module (either as docstring text or as a code path).
    assert "self-reference" in body, (
        "caveat_set.py must mention the self-reference predicate "
        "(ERR-S4 fold claim)"
    )


# --------------------------------------------------------------------- #
# T-ERR-08..10 — ERR-S6 LLM-hook file + symbol corrections
# --------------------------------------------------------------------- #


def test_t_err_08_llm_hook_filename_does_not_exist() -> None:
    """T-ERR-08: cited ``llm_hook.py`` does NOT exist (drift-pin)."""
    llm_hook = REPO_ROOT / "wirelang" / "persona_engine" / "llm_hook.py"
    assert not llm_hook.exists(), (
        "wirelang/persona_engine/llm_hook.py reappeared — ERR-S6 "
        "drift-pin regressed; ADR-0064 erratum needs re-baselining"
    )
    # Canonical replacement file exists.
    llm_shim = (
        REPO_ROOT / "wirelang" / "persona_engine" / "llm_call_shim.py"
    )
    assert llm_shim.exists(), (
        "wirelang/persona_engine/llm_call_shim.py must exist "
        "(ERR-S6 canonical replacement)"
    )


def test_t_err_09_echo_reflection_llm_hook_exported() -> None:
    """T-ERR-09: ``EchoReflectionLlmHook`` survives in __all__."""
    llm_shim = (
        REPO_ROOT / "wirelang" / "persona_engine" / "llm_call_shim.py"
    )
    body = _read(llm_shim)
    assert "class EchoReflectionLlmHook" in body, (
        "EchoReflectionLlmHook class definition must be present in "
        "llm_call_shim.py (ERR-S6 symbol survival)"
    )
    # Symbol exported (find in __all__ block).
    assert '"EchoReflectionLlmHook"' in body, (
        "EchoReflectionLlmHook must appear in __all__ export list"
    )


def test_t_err_10_anthropic_phase_3_stub_exported() -> None:
    """T-ERR-10: ``anthropic_messages_hook_phase_3_stub`` survives."""
    llm_shim = (
        REPO_ROOT / "wirelang" / "persona_engine" / "llm_call_shim.py"
    )
    body = _read(llm_shim)
    assert "def anthropic_messages_hook_phase_3_stub" in body, (
        "anthropic_messages_hook_phase_3_stub factory must be present "
        "in llm_call_shim.py (ERR-S6 symbol survival)"
    )
    assert '"anthropic_messages_hook_phase_3_stub"' in body, (
        "anthropic_messages_hook_phase_3_stub must appear in __all__"
    )


# --------------------------------------------------------------------- #
# T-ERR-11 — cross-reference to Tag-54 audit report
# --------------------------------------------------------------------- #


def test_t_err_11_errata_cross_refs_audit_report() -> None:
    """T-ERR-11: errata addendum cites the Tag-54 audit report path."""
    text = _errata_text()
    assert AUDIT_REPORT_REL in text, (
        "errata addendum must cross-reference the Tag-54 audit report "
        f"at {AUDIT_REPORT_REL}"
    )
    # PR #349 is the audit-report PR.
    assert "PR #349" in text or "#349" in text, (
        "errata addendum must cite the upstream PR (#349) for traceability"
    )
