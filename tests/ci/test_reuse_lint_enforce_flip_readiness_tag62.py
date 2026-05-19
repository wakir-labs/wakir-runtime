# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
# REUSE-IgnoreStart
"""Tests for the Tag-62 REUSE-Wrap enforce-flip-readiness mode.

Anchors
-------

* Helper (extended in Tag-62):
  ``tooling/ci/lint_reuse_ignore_wrap_pattern.py`` -- new
  ``--mode enforce-flip-readiness`` computes Coverage-Score +
  Verdict (READY / CAUTION / BLOCKED).
* Plan-Doc (new in Tag-62):
  ``docs/operations/reuse-wrap-enforce-flip-readiness-plan.md``.
* Predecessor test: ``tests/ci/test_reuse_wrap_pre_merge_lint_tag61.py``
  (PR #392, Tag-61 substance).

What this suite pins down
-------------------------

1. The plan-doc exists and has the six section anchors
   demanded by the Tag-62 brief.
2. The helper exposes the new mode, the new dataclass, and the
   new classify / compute / render functions.
3. The Coverage-Score is computed correctly across the three
   verdict bands (READY, CAUTION, BLOCKED).
4. Edge-cases: empty corpus, all-no-spdx corpus, all-clean
   corpus, all-missing-wrap corpus.
5. The CLI mode integrates: exit code is 0 regardless of
   verdict, and the verdict line is emitted on stdout.

Hermetic
--------

stdlib + pytest. No subprocess into the network. Fixture corpora
are constructed at runtime so this test file itself does not
become a REUSE-Wrap target.
"""

# REUSE-IgnoreEnd

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = REPO_ROOT / "tooling" / "ci" / "lint_reuse_ignore_wrap_pattern.py"
PLAN_DOC_PATH = (
    REPO_ROOT
    / "docs"
    / "operations"
    / "reuse-wrap-enforce-flip-readiness-plan.md"
)


def _load_helper():
    """Load the helper as a module (same pattern as Tag-61 tests)."""
    mod_name = "reuse_wrap_lint_helper_tag62"
    spec = importlib.util.spec_from_file_location(mod_name, HELPER_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def helper():
    return _load_helper()


# Runtime-constructed sentinel + SPDX tokens (Tag-61 trick: keeps
# this very file from being a REUSE-Wrap target).
_SPDX = "SPDX" "-License-Identifier"
_SPDX_COPY = "SPDX" "-FileCopyrightText"
_IGN_START = "# REUSE-Ignore" "Start"
_IGN_END = "# REUSE-Ignore" "End"


def _wrapped_fixture() -> str:
    return (
        f"# {_SPDX}: BUSL-1.1\n"
        f"{_IGN_START}\n"
        f'PAYLOAD = "{_SPDX}: Apache-2.0"\n'
        f"{_IGN_END}\n"
        "def test_x():\n"
        "    assert PAYLOAD\n"
    )


def _unwrapped_fixture() -> str:
    return (
        f"# {_SPDX}: BUSL-1.1\n"
        f'PAYLOAD = "{_SPDX}: Apache-2.0"\n'
        f'COPY = "{_SPDX_COPY}: 2026 Callandor GmbH"\n'
        "def test_x():\n"
        "    assert PAYLOAD and COPY\n"
    )


def _no_spdx_fixture() -> str:
    return (
        f"# {_SPDX}: BUSL-1.1\n"
        '"""Module without payload SPDX strings at all."""\n'
        "def test_noop():\n"
        "    assert True\n"
    )


# ---------------------------------------------------------------------------
# 1. Plan-doc exists
# ---------------------------------------------------------------------------

def test_plan_doc_exists():
    assert PLAN_DOC_PATH.is_file(), (
        f"Tag-62 plan-doc missing at {PLAN_DOC_PATH}"
    )


# ---------------------------------------------------------------------------
# 2. Plan-doc has the six required section anchors
# ---------------------------------------------------------------------------

def test_plan_doc_has_six_section_anchors():
    """The brief demanded six numbered sections; pin them all."""
    text = PLAN_DOC_PATH.read_text(encoding="utf-8")
    # Section headers are "## §N - <title>" or "## §N.M - <title>".
    # We assert presence of §1..§6 as top-level section markers.
    required = ("## §1", "## §2", "## §3", "## §4", "## §5", "## §6")
    missing = [s for s in required if s not in text]
    assert missing == [], f"Plan-doc missing sections: {missing}"


# ---------------------------------------------------------------------------
# 3. Plan-doc references Tag-59 OTS pattern in §3
# ---------------------------------------------------------------------------

def test_plan_doc_cross_references_tag59_ots_pattern():
    text = PLAN_DOC_PATH.read_text(encoding="utf-8")
    # The N-Run-Stability-Window section MUST cite Tag-59 by name
    # and the >=3-consecutive-green-main-Runs pattern.
    assert "Tag-59" in text
    assert "N-Run-Stability-Window" in text
    assert ">= 3" in text or ">=3" in text or "N=3" in text


# ---------------------------------------------------------------------------
# 4. Plan-doc cross-references Kai #389 (Branch-Protection-Wiring)
# ---------------------------------------------------------------------------

def test_plan_doc_cross_references_pr_389():
    text = PLAN_DOC_PATH.read_text(encoding="utf-8")
    assert "#389" in text, "Plan-doc must cross-ref Kai PR #389 (§4)."


# ---------------------------------------------------------------------------
# 5. Helper exposes the new mode in argparse choices
# ---------------------------------------------------------------------------

def test_helper_cli_accepts_enforce_flip_readiness_mode(helper):
    """The argparse mode-choices must include the new mode."""
    # Run with --help and confirm the new mode is listed.
    rc = helper.main(["--mode", "enforce-flip-readiness", "/nonexistent-path"])
    # Should exit 0 (empty corpus, no findings).
    assert rc == 0


# ---------------------------------------------------------------------------
# 6. Helper exposes ReadinessReport / classify / compute symbols
# ---------------------------------------------------------------------------

def test_helper_exposes_readiness_api(helper):
    assert hasattr(helper, "ReadinessReport")
    assert hasattr(helper, "compute_readiness")
    assert hasattr(helper, "render_readiness_report")
    assert hasattr(helper, "_classify_score")


# ---------------------------------------------------------------------------
# 7. Classify thresholds map correctly
# ---------------------------------------------------------------------------

def test_classify_score_thresholds(helper):
    assert helper._classify_score(100.0) == "ENFORCE-FLIP-READY"
    assert helper._classify_score(95.0) == "ENFORCE-FLIP-READY"
    assert helper._classify_score(94.999) == "ENFORCE-FLIP-CAUTION"
    assert helper._classify_score(80.0) == "ENFORCE-FLIP-CAUTION"
    assert helper._classify_score(79.999) == "ENFORCE-FLIP-BLOCKED"
    assert helper._classify_score(0.0) == "ENFORCE-FLIP-BLOCKED"


# ---------------------------------------------------------------------------
# 8. All-clean corpus -> READY, score 100
# ---------------------------------------------------------------------------

def test_all_clean_corpus_is_ready(tmp_path, helper):
    (tmp_path / "test_a.py").write_text(_wrapped_fixture(), encoding="utf-8")
    (tmp_path / "test_b.py").write_text(_wrapped_fixture(), encoding="utf-8")
    report = helper.compute_readiness([tmp_path])
    assert report.verdict == "ENFORCE-FLIP-READY"
    assert report.score == 100.0
    assert report.files_clean == 2
    assert report.files_missing_wrap == 0


# ---------------------------------------------------------------------------
# 9. All-missing-wrap corpus -> BLOCKED, score 0
# ---------------------------------------------------------------------------

def test_all_missing_corpus_is_blocked(tmp_path, helper):
    (tmp_path / "test_a.py").write_text(_unwrapped_fixture(), encoding="utf-8")
    (tmp_path / "test_b.py").write_text(_unwrapped_fixture(), encoding="utf-8")
    report = helper.compute_readiness([tmp_path])
    assert report.verdict == "ENFORCE-FLIP-BLOCKED"
    assert report.score == 0.0
    assert report.files_missing_wrap == 2
    assert report.files_clean == 0


# ---------------------------------------------------------------------------
# 10. Mixed corpus in CAUTION band (4 clean, 1 missing -> 80%)
# ---------------------------------------------------------------------------

def test_mixed_corpus_caution_band(tmp_path, helper):
    """4 clean + 1 missing -> score=80.0 -> CAUTION."""
    for i in range(4):
        (tmp_path / f"test_clean_{i}.py").write_text(
            _wrapped_fixture(), encoding="utf-8"
        )
    (tmp_path / "test_missing.py").write_text(
        _unwrapped_fixture(), encoding="utf-8"
    )
    report = helper.compute_readiness([tmp_path])
    assert report.score == 80.0
    assert report.verdict == "ENFORCE-FLIP-CAUTION"
    assert report.files_clean == 4
    assert report.files_missing_wrap == 1


# ---------------------------------------------------------------------------
# 11. Mixed corpus in READY band (19 clean, 1 missing -> 95%)
# ---------------------------------------------------------------------------

def test_mixed_corpus_ready_band(tmp_path, helper):
    for i in range(19):
        (tmp_path / f"test_clean_{i}.py").write_text(
            _wrapped_fixture(), encoding="utf-8"
        )
    (tmp_path / "test_missing.py").write_text(
        _unwrapped_fixture(), encoding="utf-8"
    )
    report = helper.compute_readiness([tmp_path])
    assert report.score == 95.0
    assert report.verdict == "ENFORCE-FLIP-READY"


# ---------------------------------------------------------------------------
# 12. No-SPDX files do not move the score
# ---------------------------------------------------------------------------

def test_no_spdx_files_not_in_denominator(tmp_path, helper):
    """Files without SPDX literals at all should not affect score."""
    (tmp_path / "test_clean.py").write_text(_wrapped_fixture(), encoding="utf-8")
    for i in range(10):
        (tmp_path / f"test_nospdx_{i}.py").write_text(
            _no_spdx_fixture(), encoding="utf-8"
        )
    report = helper.compute_readiness([tmp_path])
    # 1 clean + 0 missing + 10 no-spdx -> score = 100 (denominator=1).
    assert report.score == 100.0
    assert report.verdict == "ENFORCE-FLIP-READY"
    assert report.files_clean == 1
    assert report.files_missing_wrap == 0
    assert report.files_no_spdx == 10


# ---------------------------------------------------------------------------
# 13. Empty corpus -> READY (vacuously 100%)
# ---------------------------------------------------------------------------

def test_empty_corpus_is_vacuously_ready(tmp_path, helper):
    """No files at all means the denominator clamps to 1; score=100."""
    report = helper.compute_readiness([tmp_path])
    assert report.files_scanned == 0
    assert report.score == 100.0
    assert report.verdict == "ENFORCE-FLIP-READY"


# ---------------------------------------------------------------------------
# 14. CLI emits the verdict line on stdout
# ---------------------------------------------------------------------------

def test_cli_emits_verdict_line(tmp_path, helper, capsys):
    (tmp_path / "test_a.py").write_text(_wrapped_fixture(), encoding="utf-8")
    rc = helper.main(["--mode", "enforce-flip-readiness", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("ENFORCE-FLIP-READY") or "ENFORCE-FLIP-READY" in out.splitlines()[0]
    assert "score=" in out
    assert "files_clean" in out


# ---------------------------------------------------------------------------
# 15. CLI exits 0 even on BLOCKED verdict (verdict is the payload)
# ---------------------------------------------------------------------------

def test_cli_exits_zero_even_when_blocked(tmp_path, helper, capsys):
    """The readiness-mode is measurement, not gate. Always exit 0."""
    (tmp_path / "test_a.py").write_text(_unwrapped_fixture(), encoding="utf-8")
    rc = helper.main(["--mode", "enforce-flip-readiness", str(tmp_path)])
    assert rc == 0, "readiness-mode must always exit 0; gate is operator-hand"
    out = capsys.readouterr().out
    assert "ENFORCE-FLIP-BLOCKED" in out


# ---------------------------------------------------------------------------
# 16. Findings list contains at most 10 entries in rendered output
# ---------------------------------------------------------------------------

def test_render_caps_findings_at_ten(tmp_path, helper):
    """Render-output truncates the findings list at 10 to avoid log spam."""
    for i in range(15):
        (tmp_path / f"test_missing_{i}.py").write_text(
            _unwrapped_fixture(), encoding="utf-8"
        )
    report = helper.compute_readiness([tmp_path])
    # Each unwrapped fixture yields >= 2 findings, so >= 30 total.
    assert len(report.findings) >= 30
    rendered = helper.render_readiness_report(report)
    # Count finding-lines in the render (start with two-space indent and
    # a path-component containing ':').
    finding_lines = [
        ln for ln in rendered.splitlines()
        if ln.startswith("  test_missing_") or ln.startswith("  /")
    ]
    # Render also lists tmp_path-prefixed paths; we just upper-bound at 10.
    rendered_findings = [
        ln for ln in rendered.splitlines() if "test_missing_" in ln
    ]
    assert len(rendered_findings) <= 10


# ---------------------------------------------------------------------------
# 17. Plan-doc YAML frontmatter is well-formed
# ---------------------------------------------------------------------------

def test_plan_doc_frontmatter_well_formed():
    """Memory feedback_yaml_frontmatter_disziplin: multi-word values
    must be quoted, no markdown links in frontmatter, opens with ---,
    closes with ---."""
    text = PLAN_DOC_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == "---", "Frontmatter must open with ---"
    # Find the closing ---.
    closing_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line == "---":
            closing_idx = i
            break
    assert closing_idx is not None, "Frontmatter must close with ---"
    # No markdown-link syntax `[...](...)` inside frontmatter.
    fm_body = "\n".join(lines[1:closing_idx])
    assert "](" not in fm_body, (
        "Frontmatter must not contain markdown-link syntax "
        "(feedback_yaml_frontmatter_disziplin)."
    )


# ---------------------------------------------------------------------------
# 18. Verdict thresholds match the plan-doc §2.2 table
# ---------------------------------------------------------------------------

def test_verdict_thresholds_match_plan_doc(helper):
    """Pin: helper thresholds (95 / 80) must match plan-doc §2.2."""
    text = PLAN_DOC_PATH.read_text(encoding="utf-8")
    # Plan-doc §2.2 must show 95 and 80 as the band edges.
    assert ">= 95" in text or ">=95" in text
    assert ">= 80" in text or ">=80" in text
    # And the helper agrees.
    assert helper._classify_score(95.0) == "ENFORCE-FLIP-READY"
    assert helper._classify_score(80.0) == "ENFORCE-FLIP-CAUTION"
    assert helper._classify_score(79.99) == "ENFORCE-FLIP-BLOCKED"
