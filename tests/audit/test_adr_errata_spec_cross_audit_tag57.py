# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Hermetic Tag-57 tests for the ADR-head-errata x Wirelang-spec
cross-site mirror-drift audit (``tooling/audit/audit_adr_errata_
spec_drift.py``).

Test inventory (>= 12 hermetic, all stdlib):

  T01  helper module imports without side-effects
  T02  ERR_MARKERS contract: 6 markers, ids ERR-S1..ERR-S6
  T03  ERR_MARKERS contract: ADR coverage matches Tag-56 footer set
       (S1..S3 -> 0034, S4 -> 0052, S5 -> 0062, S6 -> 0064)
  T04  extract_errata_section yields the right slice on a synthetic
       ADR fixture and stops at the next ``## ``
  T05  extract_err_marker_ids finds all six markers on a synthetic
       fixture containing them
  T06  extract_backtick_spans recovers literal back-tick spans only
       (single-back-tick form, not fenced code blocks)
  T07  run_audit on a hermetic fixture: spec mentions only canonical
       forms -> all six markers report ``drift_class="no-drift"``
  T08  run_audit: spec mentions a legacy form *with* citation hint
       -> that marker reports ``drift_class="legacy-form-cited"``
  T09  run_audit: spec mentions a legacy form *without* citation hint
       -> that marker reports ``drift_class="legacy-form-uncited"``
       and the summary increments ``markers_with_drift``
  T10  run_audit: missing ADR head file -> AdrHeadStatus.found=False,
       err_markers_extracted=() and the audit still completes
  T11  Drift-envelope JSON shape is stable: top-level keys,
       nested keys for adr_heads/err_markers/summary present in
       exact contract order
  T12  Drift-envelope JSON round-trips through json.loads without
       error and the summary tally is internally consistent
       (markers_total == markers_with_drift + markers_with_citation_ok)
  T13  Cross-site anchor: when run against the *real* Tag-56 ADR
       heads in ``AI-Corp/decisions/`` (skip-if-absent), all four
       heads are found and every expected ERR marker is extracted
  T14  Cross-site anchor: when run against the *real* Wirelang spec
       at ``wirelang/specs/wirelang-spec-v0-4-3.md`` (skip-if-absent),
       the spec freeze marker resolves to ``"pre-cutover-freeze"``
       and no uncited-drift surfaces

All fixtures (except the optional real-world anchor tests T13/T14)
are synthesised in ``tmp_path``. No network, no real clone, no git.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest


# --------------------------------------------------------------- #
# Helper import (path-driven so tests work both from repo root    #
# and from a pytest invocation in tests/audit/)                   #
# --------------------------------------------------------------- #


_HELPER_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "tooling"
    / "audit"
    / "audit_adr_errata_spec_drift.py"
)


def _load_helper():
    spec = importlib.util.spec_from_file_location(
        "audit_adr_errata_spec_drift_tag57", _HELPER_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------- #
# Synthetic ADR-head fixtures                                      #
# --------------------------------------------------------------- #


def _synthetic_adr_0034(with_errata: bool = True) -> str:
    body = [
        "# ADR-0034 — Repo-Lizenz-Strategie",
        "",
        "## Kontext",
        "",
        "Some body text.",
        "",
        "## Folgeartefakte",
        "",
        "- Bla bla.",
        "",
    ]
    if with_errata:
        body += [
            "## Errata",
            "",
            "**Errata 1 — ERR-S1 / ERR-S2 / ERR-S3.**",
            "",
            "ERR-S1: `wirelang/specs/` canonical.",
            "ERR-S2: `wirelang/builder/` + `wirelang/canonical/` + `wirelang/identity/`.",
            "ERR-S3: `decisions/0023a-inter-agent-protokoll-layer-architektur.md`.",
            "",
        ]
    return "\n".join(body)


def _synthetic_adr_0052() -> str:
    return "\n".join(
        [
            "# ADR-0052",
            "",
            "## Kontext",
            "",
            "## Errata",
            "",
            "**Errata 1 — ERR-S4 Self-Reference-Predicate.**",
            "Canonical: `wirelang/canonical/caveat_set.py`.",
            "",
            "## Folgeartefakte",
            "",
        ]
    )


def _synthetic_adr_0062() -> str:
    return "\n".join(
        [
            "# ADR-0062",
            "",
            "## Kontext",
            "",
            "## Errata",
            "",
            "**Errata 1 — ERR-S5 Source-Origin-List Pfad-Korrekturen.**",
            "Canonical: `wakir-runtime/wirelang/specs/`.",
            "",
            "## Folgeartefakte",
            "",
        ]
    )


def _synthetic_adr_0064() -> str:
    return "\n".join(
        [
            "# ADR-0064",
            "",
            "## Kontext",
            "",
            "## Errata",
            "",
            "**Errata 1 — ERR-S6 LLM-Hook.**",
            "Canonical: `wirelang/persona_engine/llm_call_shim.py`.",
            "",
        ]
    )


def _write_synthetic_decisions(tmp_path: pathlib.Path) -> pathlib.Path:
    decisions_dir = tmp_path / "decisions"
    decisions_dir.mkdir()
    (decisions_dir / "0034-repo-lizenz-strategie.md").write_text(
        _synthetic_adr_0034(), encoding="utf-8"
    )
    (decisions_dir / "0052-class-p-promotion-caveat-hash.md").write_text(
        _synthetic_adr_0052(), encoding="utf-8"
    )
    (decisions_dir / "0062-repo-split-strategie-phase-2.md").write_text(
        _synthetic_adr_0062(), encoding="utf-8"
    )
    (
        decisions_dir
        / "0064-model-routing-prompt-caching-persona-engine.md"
    ).write_text(_synthetic_adr_0064(), encoding="utf-8")
    return decisions_dir


def _synthetic_spec(
    *,
    mention_canonical: bool = True,
    mention_legacy: bool = False,
    legacy_cited: bool = False,
) -> str:
    parts = [
        "# Wirelang Spec v0.4.3 — pre-cutover-freeze",
        "",
        "## 1. Scope",
        "",
        "This spec freezes the v0.4 substrate at the pre-cutover-freeze",
        "marker.",
        "",
    ]
    if mention_canonical:
        parts += [
            "## 2. Anchors",
            "",
            "Canonical paths: `wirelang/specs/`, `wirelang/builder/`,",
            "`wirelang/canonical/`, `wirelang/identity/`,",
            "`wirelang/canonical/caveat_set.py`, ",
            "`wakir-runtime/wirelang/specs/`,",
            "`wirelang/persona_engine/llm_call_shim.py`,",
            "`decisions/0023a-inter-agent-protokoll-layer-architektur.md`.",
            "",
        ]
    if mention_legacy:
        if legacy_cited:
            parts += [
                "## 3. Historical names",
                "",
                "Some legacy adopter docs cite `wirelang/parser/`; see",
                "ADR-0034 Errata 1 (ERR-S2) for the canonical-form",
                "replacement subtrees.",
                "",
            ]
        else:
            parts += [
                "## 3. Random reference",
                "",
                "The reference parser surface is `wirelang/parser/`.",
                "",
            ]
    return "\n".join(parts)


# --------------------------------------------------------------- #
# Tests                                                            #
# --------------------------------------------------------------- #


def test_t01_helper_imports_without_side_effects():
    mod = _load_helper()
    assert mod.AUDIT_ID == "tag-57-adr-errata-spec-cross-audit"


def test_t02_err_markers_contract_six_ids():
    mod = _load_helper()
    ids = [m.marker_id for m in mod.ERR_MARKERS]
    assert ids == ["ERR-S1", "ERR-S2", "ERR-S3", "ERR-S4", "ERR-S5", "ERR-S6"]
    assert len(set(ids)) == 6


def test_t03_err_markers_contract_adr_coverage():
    mod = _load_helper()
    by_marker = {m.marker_id: m.adr_id for m in mod.ERR_MARKERS}
    assert by_marker["ERR-S1"] == "ADR-0034"
    assert by_marker["ERR-S2"] == "ADR-0034"
    assert by_marker["ERR-S3"] == "ADR-0034"
    assert by_marker["ERR-S4"] == "ADR-0052"
    assert by_marker["ERR-S5"] == "ADR-0062"
    assert by_marker["ERR-S6"] == "ADR-0064"


def test_t04_extract_errata_section_slice(tmp_path):
    mod = _load_helper()
    adr = _synthetic_adr_0034()
    section = mod.extract_errata_section(adr)
    assert section.startswith("## Errata")
    # The section must NOT bleed into the next top-level heading.
    assert "## Kontext" not in section
    assert "## Folgeartefakte" not in section
    assert "ERR-S1" in section


def test_t05_extract_err_marker_ids_finds_all_six():
    mod = _load_helper()
    text = (
        "## Errata\nERR-S1, ERR-S2, ERR-S3 here. "
        "ERR-S4 next. ERR-S5. ERR-S6. ERR-S99 should NOT count."
    )
    ids = mod.extract_err_marker_ids(text)
    assert ids == ("ERR-S1", "ERR-S2", "ERR-S3", "ERR-S4", "ERR-S5", "ERR-S6")


def test_t06_extract_backtick_spans_literal_only():
    mod = _load_helper()
    spans = mod.extract_backtick_spans(
        "Plain `wirelang/specs/` and `caveat_set.py` and not-a-span text."
    )
    assert "wirelang/specs/" in spans
    assert "caveat_set.py" in spans
    # Fenced blocks are not single-back-tick spans; we don't extract
    # their content as identifiers here. Verify by absence.
    spans_fenced = mod.extract_backtick_spans(
        "```\nwirelang/parser/\n```\n"
    )
    assert "wirelang/parser/" not in spans_fenced


def test_t07_run_audit_only_canonical_yields_no_drift(tmp_path):
    mod = _load_helper()
    decisions = _write_synthetic_decisions(tmp_path)
    spec_path = tmp_path / "spec.md"
    spec_path.write_text(_synthetic_spec(mention_legacy=False), encoding="utf-8")

    envelope = mod.run_audit(decisions_dir=decisions, spec_path=spec_path)
    assert envelope.summary.markers_total == 6
    assert envelope.summary.markers_with_drift == 0
    assert envelope.summary.markers_with_citation_ok == 6
    for r in envelope.err_markers:
        assert r.drift_class == "no-drift", (r.marker_id, r.drift_class)


def test_t08_run_audit_legacy_with_citation_is_acceptable(tmp_path):
    mod = _load_helper()
    decisions = _write_synthetic_decisions(tmp_path)
    spec_path = tmp_path / "spec.md"
    spec_path.write_text(
        _synthetic_spec(mention_legacy=True, legacy_cited=True),
        encoding="utf-8",
    )

    envelope = mod.run_audit(decisions_dir=decisions, spec_path=spec_path)
    # ERR-S2 is the marker whose legacy form (`wirelang/parser/`) the
    # citation-fixture references.
    by_marker = {r.marker_id: r for r in envelope.err_markers}
    assert by_marker["ERR-S2"].mentions_legacy_form_in_spec >= 1
    assert by_marker["ERR-S2"].legacy_form_citation_pointer is True
    assert by_marker["ERR-S2"].drift_class == "legacy-form-cited"
    # legacy-form-cited counts as citation_ok in the summary.
    assert envelope.summary.markers_with_drift == 0
    assert envelope.summary.markers_with_citation_ok == 6


def test_t09_run_audit_legacy_uncited_surfaces_drift(tmp_path):
    mod = _load_helper()
    decisions = _write_synthetic_decisions(tmp_path)
    spec_path = tmp_path / "spec.md"
    spec_path.write_text(
        _synthetic_spec(mention_legacy=True, legacy_cited=False),
        encoding="utf-8",
    )

    envelope = mod.run_audit(decisions_dir=decisions, spec_path=spec_path)
    by_marker = {r.marker_id: r for r in envelope.err_markers}
    assert by_marker["ERR-S2"].mentions_legacy_form_in_spec >= 1
    assert by_marker["ERR-S2"].legacy_form_citation_pointer is False
    assert by_marker["ERR-S2"].drift_class == "legacy-form-uncited"
    assert envelope.summary.markers_with_drift == 1
    assert envelope.summary.markers_with_citation_ok == 5


def test_t10_run_audit_handles_missing_adr_head(tmp_path):
    mod = _load_helper()
    decisions = tmp_path / "decisions"
    decisions.mkdir()
    # Only ADR-0034 is present.
    (decisions / "0034-repo-lizenz-strategie.md").write_text(
        _synthetic_adr_0034(), encoding="utf-8"
    )
    spec_path = tmp_path / "spec.md"
    spec_path.write_text(_synthetic_spec(), encoding="utf-8")

    envelope = mod.run_audit(decisions_dir=decisions, spec_path=spec_path)
    by_adr = {h.adr_id: h for h in envelope.adr_heads}
    assert by_adr["ADR-0034"].found is True
    assert "ERR-S1" in by_adr["ADR-0034"].err_markers_extracted
    assert by_adr["ADR-0052"].found is False
    assert by_adr["ADR-0052"].err_markers_extracted == ()
    assert by_adr["ADR-0062"].found is False
    assert by_adr["ADR-0064"].found is False
    # Even with missing heads the marker contract still emits 6 reports.
    assert len(envelope.err_markers) == 6


def test_t11_drift_envelope_json_shape_is_stable(tmp_path):
    mod = _load_helper()
    decisions = _write_synthetic_decisions(tmp_path)
    spec_path = tmp_path / "spec.md"
    spec_path.write_text(_synthetic_spec(), encoding="utf-8")

    envelope = mod.run_audit(decisions_dir=decisions, spec_path=spec_path)
    payload = json.loads(envelope.to_json())

    # Top-level contract.
    # Tag-63 extension: the envelope MAY carry an additional "draft_shape"
    # key (None on a non-draft document). The Tag-57 pin is preserved by
    # asserting the six original keys appear in order at the head of the
    # payload; any later keys are accepted as compatible extensions.
    assert list(payload.keys())[:6] == [
        "audit_id",
        "spec_path",
        "spec_freeze_marker",
        "adr_heads",
        "err_markers",
        "summary",
    ]
    assert set(payload.keys()) - {"draft_shape"} == {
        "audit_id",
        "spec_path",
        "spec_freeze_marker",
        "adr_heads",
        "err_markers",
        "summary",
    }
    assert payload["audit_id"] == "tag-57-adr-errata-spec-cross-audit"
    # adr_heads inner shape.
    assert payload["adr_heads"] and all(
        set(h.keys()) == {"adr_id", "path", "found", "err_markers_extracted"}
        for h in payload["adr_heads"]
    )
    # err_markers inner shape.
    expected_marker_keys = {
        "marker_id",
        "adr_id",
        "canonical_forms",
        "legacy_forms",
        "mentions_canonical_form_in_spec",
        "mentions_legacy_form_in_spec",
        "legacy_form_citation_pointer",
        "drift_class",
    }
    assert payload["err_markers"] and all(
        set(r.keys()) == expected_marker_keys for r in payload["err_markers"]
    )
    # summary inner shape.
    assert set(payload["summary"].keys()) == {
        "markers_total",
        "markers_with_drift",
        "markers_with_citation_ok",
    }


def test_t12_summary_tally_is_internally_consistent(tmp_path):
    mod = _load_helper()
    decisions = _write_synthetic_decisions(tmp_path)
    spec_path = tmp_path / "spec.md"
    spec_path.write_text(
        _synthetic_spec(mention_legacy=True, legacy_cited=False),
        encoding="utf-8",
    )
    envelope = mod.run_audit(decisions_dir=decisions, spec_path=spec_path)
    s = envelope.summary
    assert s.markers_total == 6
    assert s.markers_with_drift + s.markers_with_citation_ok == s.markers_total


# --------------------------------------------------------------- #
# Optional cross-site anchor tests (skip-if-absent)                #
# --------------------------------------------------------------- #


_REAL_DECISIONS_DIR = pathlib.Path("/var/home/fred/AI-Corp/decisions")
_REAL_SPEC_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "wirelang"
    / "specs"
    / "wirelang-spec-v0-4-3.md"
)


@pytest.mark.skipif(
    not _REAL_DECISIONS_DIR.exists(),
    reason="AI-Corp/decisions/ not visible from this checkout (CI sandbox).",
)
def test_t13_real_adr_heads_yield_full_marker_set():
    mod = _load_helper()
    envelope = mod.run_audit(
        decisions_dir=_REAL_DECISIONS_DIR,
        spec_path=_REAL_SPEC_PATH if _REAL_SPEC_PATH.exists() else pathlib.Path("/dev/null"),
    )
    by_adr = {h.adr_id: h for h in envelope.adr_heads}
    assert by_adr["ADR-0034"].found is True
    assert by_adr["ADR-0052"].found is True
    assert by_adr["ADR-0062"].found is True
    assert by_adr["ADR-0064"].found is True
    # ERR-S1..S3 in ADR-0034, S4 in 0052, S5 in 0062, S6 in 0064.
    assert "ERR-S1" in by_adr["ADR-0034"].err_markers_extracted
    assert "ERR-S2" in by_adr["ADR-0034"].err_markers_extracted
    assert "ERR-S3" in by_adr["ADR-0034"].err_markers_extracted
    assert "ERR-S4" in by_adr["ADR-0052"].err_markers_extracted
    assert "ERR-S5" in by_adr["ADR-0062"].err_markers_extracted
    assert "ERR-S6" in by_adr["ADR-0064"].err_markers_extracted


@pytest.mark.skipif(
    not (_REAL_DECISIONS_DIR.exists() and _REAL_SPEC_PATH.exists()),
    reason="Real-world fixtures missing (decisions dir or spec).",
)
def test_t14_real_spec_freeze_marker_resolves_and_no_uncited_drift():
    mod = _load_helper()
    envelope = mod.run_audit(
        decisions_dir=_REAL_DECISIONS_DIR,
        spec_path=_REAL_SPEC_PATH,
    )
    assert envelope.spec_freeze_marker == "pre-cutover-freeze"
    # We allow "legacy-form-cited" as green; we only fail on uncited.
    uncited = [
        r.marker_id
        for r in envelope.err_markers
        if r.drift_class == "legacy-form-uncited"
    ]
    assert uncited == [], (
        "Wirelang spec v0.4.3 mentions legacy forms without an "
        "Errata-citation pointer: " + ", ".join(uncited)
    )
