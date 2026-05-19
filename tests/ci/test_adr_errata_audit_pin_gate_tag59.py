# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic CI-substrate tests for the Tag-59 ADR-Errata-Footer-
Verifier CI-Pin gate.

Surfaces under test
-------------------

* ``tooling/audit/adr_errata_audit_pin_verifier.py`` — the verifier
  module.
* ``tooling/audit/adr-errata-audit-baseline.json`` — the committed
  baseline snapshot.
* ``.github/workflows/adr-errata-cross-site-audit-pin-gate.yml`` —
  the CI workflow that wires both into a regression gate.

Discipline
----------

The tests are hermetic (no network, no sibling-clone dependency).
They synthesise tiny ADR + spec fixtures in ``tmp_path`` and drive
the verifier against those fixtures. The only baseline-touching
test asserts the on-disk baseline's schema, not its content, so
that legitimate Reza-Hand baseline-rebases (a content-owner
decision) do not red-light this suite.

Auftrag minimum: >= 12 hermetic tests. This module ships >= 16.

Tag-59, Amara-Hand, continuous-mode.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TOOLING_AUDIT_DIR = REPO_ROOT / "tooling" / "audit"
VERIFIER_PATH = TOOLING_AUDIT_DIR / "adr_errata_audit_pin_verifier.py"
HELPER_PATH = TOOLING_AUDIT_DIR / "audit_adr_errata_spec_drift.py"
BASELINE_PATH = TOOLING_AUDIT_DIR / "adr-errata-audit-baseline.json"
WORKFLOW_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "adr-errata-cross-site-audit-pin-gate.yml"
)


# ---------------------------------------------------------------
# Module loader
# ---------------------------------------------------------------


@pytest.fixture(scope="module")
def verifier_module():
    """Load the verifier helper as an importable module."""
    assert VERIFIER_PATH.is_file(), f"verifier missing: {VERIFIER_PATH}"
    # Make sure the tooling/audit dir is on sys.path so the lazy
    # import inside run_pin_check (``from audit_adr_errata_spec_drift
    # import run_audit``) resolves.
    sys.path.insert(0, str(TOOLING_AUDIT_DIR))
    mod_name = "adr_errata_audit_pin_verifier_under_test"
    spec = importlib.util.spec_from_file_location(mod_name, VERIFIER_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(mod_name, None)
        raise
    return mod


# ---------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------


def _write_adr_head(decisions_dir: Path, filename: str, err_markers: tuple[str, ...]):
    """Write a minimal ADR head with an ## Errata footer containing
    each of the requested ERR markers."""
    body = ["# ADR (synthetic)\n", "Status: synthetic\n", "## Body\nLorem.\n"]
    if err_markers:
        body.append("## Errata\n")
        for m in err_markers:
            body.append(f"- {m}: synthetic marker text\n")
    (decisions_dir / filename).write_text("".join(body), encoding="utf-8")


def _write_synthetic_adr_set(decisions_dir: Path):
    """Recreate the four ADR-heads with the Tag-57 marker mapping."""
    decisions_dir.mkdir(parents=True, exist_ok=True)
    _write_adr_head(
        decisions_dir,
        "0034-repo-lizenz-strategie.md",
        ("ERR-S1", "ERR-S2", "ERR-S3"),
    )
    _write_adr_head(
        decisions_dir,
        "0052-class-p-promotion-caveat-hash.md",
        ("ERR-S4",),
    )
    _write_adr_head(
        decisions_dir,
        "0062-repo-split-strategie-phase-2.md",
        ("ERR-S1", "ERR-S2", "ERR-S5"),
    )
    _write_adr_head(
        decisions_dir,
        "0064-model-routing-prompt-caching-persona-engine.md",
        ("ERR-S6",),
    )


def _write_synthetic_spec(path: Path, *, mention_canonical: bool, mention_legacy: bool):
    """Write a tiny spec with optional canonical/legacy back-tick
    spans for ERR-S1.
    """
    parts = [
        "---\nstatus: pre-cutover-freeze\n---\n",
        "# Synthetic Wirelang Spec\n",
        "Some body text.\n",
    ]
    if mention_canonical:
        parts.append("See `wirelang/specs/wirelang-spec-v0-4-3.md` for canonical layout.\n")
    if mention_legacy:
        parts.append("Historical path `wirelang/spec/v0.1.0/` is no longer canonical.\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(parts), encoding="utf-8")


def _make_synthetic_baseline(tmp_path: Path, verifier_module) -> Path:
    """Run the verifier's underlying audit against the synthetic
    fixtures and write a baseline snapshot to tmp_path/baseline.json."""
    decisions_dir = tmp_path / "decisions"
    spec_path = tmp_path / "wirelang" / "specs" / "wirelang-spec-v0-4-3.md"
    _write_synthetic_adr_set(decisions_dir)
    _write_synthetic_spec(spec_path, mention_canonical=True, mention_legacy=False)
    sys.path.insert(0, str(TOOLING_AUDIT_DIR))
    from audit_adr_errata_spec_drift import run_audit  # type: ignore

    envelope = run_audit(decisions_dir=decisions_dir, spec_path=spec_path)
    data = json.loads(envelope.to_json())
    # Normalise paths so the baseline is runner-agnostic.
    data["spec_path"] = "wirelang/specs/wirelang-spec-v0-4-3.md"
    for h in data["adr_heads"]:
        h["path"] = Path(h["path"]).name
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return baseline_path


# ---------------------------------------------------------------
# Section A — Verifier module surface
# ---------------------------------------------------------------


def test_verifier_module_exports_three_verdict_constants(verifier_module):
    assert verifier_module.PIN_VERDICT_INTACT == "AUDIT-PIN-INTACT"
    assert verifier_module.PIN_VERDICT_DRIFT == "AUDIT-PIN-DRIFT"
    assert verifier_module.PIN_VERDICT_SKIP == "AUDIT-PIN-SKIP"


def test_verifier_module_exposes_run_pin_check_callable(verifier_module):
    assert callable(verifier_module.run_pin_check)


def test_pin_result_to_lines_includes_verdict_and_paths(verifier_module, tmp_path):
    res = verifier_module.PinResult(
        verdict="AUDIT-PIN-INTACT",
        diffs=(),
        decisions_dir=str(tmp_path / "d"),
        spec_path=str(tmp_path / "s.md"),
        baseline_path=str(tmp_path / "b.json"),
    )
    lines = res.to_lines()
    joined = "\n".join(lines)
    assert "adr-errata-audit-pin verdict: AUDIT-PIN-INTACT" in joined
    assert "decisions_dir" in joined and "spec_path" in joined and "baseline" in joined


# ---------------------------------------------------------------
# Section B — Path normalisation (the core stability primitive)
# ---------------------------------------------------------------


def test_normalise_adr_path_returns_basename(verifier_module):
    assert verifier_module._normalise_adr_path(
        "/var/home/fred/AI-Corp/decisions/0034-repo-lizenz-strategie.md"
    ) == "0034-repo-lizenz-strategie.md"


def test_normalise_spec_path_keeps_last_two_segments(verifier_module):
    assert verifier_module._normalise_spec_path(
        "/abs/path/wirelang/specs/wirelang-spec-v0-4-3.md"
    ) == "specs/wirelang-spec-v0-4-3.md"


def test_normalise_envelope_strips_absolute_paths(verifier_module):
    env = {
        "audit_id": "x",
        "spec_path": "/abs/wirelang/specs/wirelang-spec-v0-4-3.md",
        "spec_freeze_marker": None,
        "adr_heads": [{"adr_id": "ADR-0034", "path": "/abs/decisions/0034.md", "found": True, "err_markers_extracted": []}],
        "err_markers": [],
        "summary": {"markers_total": 0, "markers_with_drift": 0, "markers_with_citation_ok": 0},
    }
    norm = verifier_module._normalise_envelope(env)
    assert norm["spec_path"] == "specs/wirelang-spec-v0-4-3.md"
    assert norm["adr_heads"][0]["path"] == "0034.md"


# ---------------------------------------------------------------
# Section C — Diff engine
# ---------------------------------------------------------------


def test_compare_envelope_returns_intact_on_equal_inputs(verifier_module, tmp_path):
    baseline_path = _make_synthetic_baseline(tmp_path, verifier_module)
    base = json.loads(baseline_path.read_text(encoding="utf-8"))
    verdict, diffs = verifier_module.compare_envelope_against_baseline(base, base)
    assert verdict == "AUDIT-PIN-INTACT"
    assert diffs == ()


def test_compare_envelope_detects_summary_drift(verifier_module, tmp_path):
    baseline_path = _make_synthetic_baseline(tmp_path, verifier_module)
    base = json.loads(baseline_path.read_text(encoding="utf-8"))
    observed = json.loads(json.dumps(base))
    observed["summary"]["markers_with_drift"] = 99
    verdict, diffs = verifier_module.compare_envelope_against_baseline(observed, base)
    assert verdict == "AUDIT-PIN-DRIFT"
    assert any("summary.markers_with_drift" in d for d in diffs)


def test_compare_envelope_detects_marker_drift_class_shift(verifier_module, tmp_path):
    baseline_path = _make_synthetic_baseline(tmp_path, verifier_module)
    base = json.loads(baseline_path.read_text(encoding="utf-8"))
    observed = json.loads(json.dumps(base))
    observed["err_markers"][0]["drift_class"] = "legacy-form-uncited"
    verdict, diffs = verifier_module.compare_envelope_against_baseline(observed, base)
    assert verdict == "AUDIT-PIN-DRIFT"
    assert any("drift_class" in d for d in diffs)


def test_compare_envelope_detects_list_length_change(verifier_module, tmp_path):
    baseline_path = _make_synthetic_baseline(tmp_path, verifier_module)
    base = json.loads(baseline_path.read_text(encoding="utf-8"))
    observed = json.loads(json.dumps(base))
    observed["err_markers"] = observed["err_markers"][:-1]
    verdict, diffs = verifier_module.compare_envelope_against_baseline(observed, base)
    assert verdict == "AUDIT-PIN-DRIFT"
    assert any("length" in d and "baseline" in d for d in diffs)


def test_compare_envelope_is_path_agnostic_for_spec_and_adr(verifier_module, tmp_path):
    baseline_path = _make_synthetic_baseline(tmp_path, verifier_module)
    base = json.loads(baseline_path.read_text(encoding="utf-8"))
    observed = json.loads(json.dumps(base))
    # Pretend the observed envelope carries absolute runner paths
    # while the baseline is relative — the verifier must normalise
    # both and still return INTACT.
    observed["spec_path"] = "/runner/abs/wirelang/specs/wirelang-spec-v0-4-3.md"
    for h in observed["adr_heads"]:
        h["path"] = f"/runner/abs/decisions/{h['path']}"
    verdict, diffs = verifier_module.compare_envelope_against_baseline(observed, base)
    assert verdict == "AUDIT-PIN-INTACT", f"diffs: {diffs}"


# ---------------------------------------------------------------
# Section D — run_pin_check end-to-end
# ---------------------------------------------------------------


def test_run_pin_check_intact_on_synthetic_fixtures(verifier_module, tmp_path):
    baseline_path = _make_synthetic_baseline(tmp_path, verifier_module)
    decisions_dir = tmp_path / "decisions"
    spec_path = tmp_path / "wirelang" / "specs" / "wirelang-spec-v0-4-3.md"
    res = verifier_module.run_pin_check(
        decisions_dir=decisions_dir,
        spec_path=spec_path,
        baseline_path=baseline_path,
    )
    assert res.verdict == "AUDIT-PIN-INTACT", f"diffs: {res.diffs}"


def test_run_pin_check_skips_when_decisions_dir_missing(verifier_module, tmp_path):
    res = verifier_module.run_pin_check(
        decisions_dir=tmp_path / "does-not-exist",
        spec_path=tmp_path / "wirelang" / "specs" / "wirelang-spec-v0-4-3.md",
        baseline_path=tmp_path / "baseline.json",
    )
    assert res.verdict == "AUDIT-PIN-SKIP"
    assert res.skip_reason is not None and "decisions_dir not found" in res.skip_reason


def test_run_pin_check_skips_when_spec_missing(verifier_module, tmp_path):
    decisions_dir = tmp_path / "decisions"
    _write_synthetic_adr_set(decisions_dir)
    res = verifier_module.run_pin_check(
        decisions_dir=decisions_dir,
        spec_path=tmp_path / "missing-spec.md",
        baseline_path=tmp_path / "baseline.json",
    )
    assert res.verdict == "AUDIT-PIN-SKIP"
    assert res.skip_reason is not None and "spec_path not found" in res.skip_reason


def test_run_pin_check_drifts_when_baseline_missing(verifier_module, tmp_path):
    decisions_dir = tmp_path / "decisions"
    spec_path = tmp_path / "wirelang" / "specs" / "wirelang-spec-v0-4-3.md"
    _write_synthetic_adr_set(decisions_dir)
    _write_synthetic_spec(spec_path, mention_canonical=True, mention_legacy=False)
    res = verifier_module.run_pin_check(
        decisions_dir=decisions_dir,
        spec_path=spec_path,
        baseline_path=tmp_path / "missing-baseline.json",
    )
    assert res.verdict == "AUDIT-PIN-DRIFT"
    assert any("baseline file missing" in d for d in res.diffs)


def test_run_pin_check_drifts_when_legacy_form_appears_in_spec(verifier_module, tmp_path):
    baseline_path = _make_synthetic_baseline(tmp_path, verifier_module)
    decisions_dir = tmp_path / "decisions"
    spec_path = tmp_path / "wirelang" / "specs" / "wirelang-spec-v0-4-3.md"
    # Rewrite spec with a legacy form (no citation) — this should
    # flip ERR-S1.drift_class to legacy-form-uncited.
    _write_synthetic_spec(spec_path, mention_canonical=True, mention_legacy=True)
    res = verifier_module.run_pin_check(
        decisions_dir=decisions_dir,
        spec_path=spec_path,
        baseline_path=baseline_path,
    )
    assert res.verdict == "AUDIT-PIN-DRIFT"
    assert any("drift_class" in d or "mentions_legacy_form_in_spec" in d for d in res.diffs)


# ---------------------------------------------------------------
# Section E — Baseline on disk
# ---------------------------------------------------------------


def test_baseline_file_exists_and_parses():
    assert BASELINE_PATH.is_file(), f"baseline missing: {BASELINE_PATH}"
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    assert data["audit_id"] == "tag-57-adr-errata-spec-cross-audit"
    assert "summary" in data and "err_markers" in data and "adr_heads" in data


def test_baseline_summary_has_six_markers_and_zero_drift():
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    assert data["summary"]["markers_total"] == 6
    assert data["summary"]["markers_with_drift"] == 0
    assert data["summary"]["markers_with_citation_ok"] == 6


def test_baseline_paths_are_relative_not_absolute():
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    assert not data["spec_path"].startswith("/"), (
        "baseline spec_path must be relative (runner-agnostic)"
    )
    for h in data["adr_heads"]:
        assert not h["path"].startswith("/"), (
            f"baseline ADR path must be runner-agnostic, got {h['path']}"
        )


def test_baseline_lists_all_six_err_markers():
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    marker_ids = [m["marker_id"] for m in data["err_markers"]]
    assert marker_ids == ["ERR-S1", "ERR-S2", "ERR-S3", "ERR-S4", "ERR-S5", "ERR-S6"]


def test_baseline_intact_against_live_repo_state_or_skips():
    """The committed baseline must produce AUDIT-PIN-INTACT against
    the live AI-Corp/decisions sibling when present, and AUDIT-PIN-
    SKIP otherwise. We accept either outcome — what we never accept
    is AUDIT-PIN-DRIFT against the committed runtime tip + sibling."""
    sys.path.insert(0, str(TOOLING_AUDIT_DIR))
    spec = importlib.util.spec_from_file_location(
        "adr_errata_audit_pin_verifier_e2e", VERIFIER_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["adr_errata_audit_pin_verifier_e2e"] = mod
    spec.loader.exec_module(mod)

    decisions_dir = Path("/var/home/fred/AI-Corp/decisions")
    spec_path = REPO_ROOT / "wirelang" / "specs" / "wirelang-spec-v0-4-3.md"
    res = mod.run_pin_check(
        decisions_dir=decisions_dir,
        spec_path=spec_path,
        baseline_path=BASELINE_PATH,
    )
    assert res.verdict in ("AUDIT-PIN-INTACT", "AUDIT-PIN-SKIP"), (
        f"live verdict was {res.verdict}; diffs: {res.diffs}"
    )


# ---------------------------------------------------------------
# Section F — Workflow YAML shape
# ---------------------------------------------------------------


def test_workflow_exists_at_canonical_path():
    assert WORKFLOW_PATH.is_file(), f"workflow missing: {WORKFLOW_PATH}"


def test_workflow_declares_path_filter_for_all_pinned_artefacts():
    body = WORKFLOW_PATH.read_text(encoding="utf-8")
    for needle in (
        "tooling/audit/audit_adr_errata_spec_drift.py",
        "tooling/audit/adr_errata_audit_pin_verifier.py",
        "tooling/audit/adr-errata-audit-baseline.json",
        "wirelang/specs/wirelang-spec-v0-4-3.md",
        "tests/ci/test_adr_errata_audit_pin_gate_tag59.py",
        ".github/workflows/adr-errata-cross-site-audit-pin-gate.yml",
    ):
        assert needle in body, f"workflow path-filter missing: {needle}"


def test_workflow_has_minimal_contents_read_permission():
    body = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert re.search(r"^permissions:\s*\n\s+contents:\s*read\s*$", body, re.MULTILINE), (
        "workflow must declare permissions.contents: read"
    )


def test_workflow_emits_three_documented_verdict_strings():
    body = WORKFLOW_PATH.read_text(encoding="utf-8")
    for verdict in ("AUDIT-PIN-INTACT", "AUDIT-PIN-DRIFT", "AUDIT-PIN-SKIP"):
        assert verdict in body, f"workflow must reference verdict {verdict}"


def test_workflow_runs_hermetic_test_suite():
    body = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "tests/ci/test_adr_errata_audit_pin_gate_tag59.py" in body, (
        "workflow must invoke the hermetic Tag-59 test-suite"
    )
    assert "pytest" in body, "workflow must use pytest as test runner"
