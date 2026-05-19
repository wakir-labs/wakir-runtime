# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic tests for the Tag-60 G1+G2 operator-recipe smoke validator.

Tag-60 Kai — sandbox-smoke-probe-validation for the Tag-56 PR #360
``docs/operations/cosign-g1-g2-operator-setup.md`` operator-recipe.
The validator is ``tooling/ci/validate_g1_g2_operator_recipe.py``.

Coverage targets (>=12 invariants):

  T-G1G2-SMOKE-01  helper imports cleanly + exposes top-level API
  T-G1G2-SMOKE-02  RECIPE-INTACT on the live guide file
  T-G1G2-SMOKE-03  Finding model round-trips through to_dict()
  T-G1G2-SMOKE-04  extract_code_blocks yields >=11 blocks on live guide
  T-G1G2-SMOKE-05  quote-aware semicolon-split keeps quoted ';' intact
  T-G1G2-SMOKE-06  unknown bash binary -> RECIPE-SYNTAX-DRIFT
  T-G1G2-SMOKE-07  unknown gh-shape -> RECIPE-SEMANTIC-DRIFT
  T-G1G2-SMOKE-08  malformed YAML fence -> RECIPE-SYNTAX-DRIFT
  T-G1G2-SMOKE-09  malformed JSON fence -> RECIPE-SYNTAX-DRIFT
  T-G1G2-SMOKE-10  missing placeholder token -> RECIPE-SEMANTIC-DRIFT
  T-G1G2-SMOKE-11  missing PENDING token -> RECIPE-SEMANTIC-DRIFT
  T-G1G2-SMOKE-12  workflow-existence cross-check finds both refs
  T-G1G2-SMOKE-13  aggregate_verdict precedence (semantic > syntax)
  T-G1G2-SMOKE-14  CLI main() exits 0 on live guide
  T-G1G2-SMOKE-15  CLI main() exits 1 on missing guide
  T-G1G2-SMOKE-16  workflow file exists + carries SPDX header
  T-G1G2-SMOKE-17  workflow declares all three triggers
  T-G1G2-SMOKE-18  workflow path-filter mentions guide + helper + tests
  T-G1G2-SMOKE-19  known-shape table covers both workflow refs

Total: 19 hermetic tests (target was >=12).

Sandbox boundary
----------------

Per ``feedback_sandbox_host_trennung.md`` + ADR-0051 these tests
NEVER call cosign / crane / gh / podman / network. They import the
validator module, exercise its pure-function API on the live guide
on disk and on synthetic in-memory inputs, and parse the workflow
YAML on disk. No subprocess invocations of external binaries.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")


REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = REPO_ROOT / "tooling" / "ci" / "validate_g1_g2_operator_recipe.py"
GUIDE_PATH = REPO_ROOT / "docs" / "operations" / "cosign-g1-g2-operator-setup.md"
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows"
    / "g1-g2-operator-recipe-smoke-validation.yml"
)


@pytest.fixture(scope="module")
def helper_mod():
    """Import the validator module by file path (hermetic)."""
    spec = importlib.util.spec_from_file_location(
        "validate_g1_g2_operator_recipe", HELPER_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["validate_g1_g2_operator_recipe"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guide_text() -> str:
    return GUIDE_PATH.read_text(encoding="utf-8")


# T-G1G2-SMOKE-01 ---------------------------------------------------------
def test_helper_imports_and_exposes_api(helper_mod):
    """The helper exports the documented top-level API surface."""
    assert hasattr(helper_mod, "validate_recipe")
    assert hasattr(helper_mod, "aggregate_verdict")
    assert hasattr(helper_mod, "extract_code_blocks")
    assert hasattr(helper_mod, "Finding")
    assert hasattr(helper_mod, "main")
    assert hasattr(helper_mod, "KNOWN_CLI_VOCAB")
    assert hasattr(helper_mod, "GH_KNOWN_SHAPES")
    assert hasattr(helper_mod, "WORKFLOW_REFS")


# T-G1G2-SMOKE-02 ---------------------------------------------------------
def test_live_guide_is_recipe_intact(helper_mod, guide_text):
    """The live Tag-56 guide must produce RECIPE-INTACT today."""
    result = helper_mod.validate_recipe(guide_text, REPO_ROOT)
    assert result["verdict"] == "RECIPE-INTACT", (
        "live guide regressed; findings = "
        f"{[f.render() for f in result['findings']]}"
    )
    assert result["code_block_count"] >= 10
    assert result["gh_call_count"] >= 3


# T-G1G2-SMOKE-03 ---------------------------------------------------------
def test_finding_to_dict_round_trip(helper_mod):
    """Finding.to_dict() emits the documented schema."""
    f = helper_mod.Finding(
        stage="stage-1",
        severity="error",
        subject="crane",
        message="unknown flag",
    )
    d = f.to_dict()
    assert d == {
        "stage": "stage-1",
        "severity": "error",
        "subject": "crane",
        "message": "unknown flag",
    }
    assert "crane" in f.render()
    assert "ERROR" in f.render()


# T-G1G2-SMOKE-04 ---------------------------------------------------------
def test_extract_code_blocks_counts_live(helper_mod, guide_text):
    """Live guide carries at least 11 fenced code-blocks."""
    blocks = helper_mod.extract_code_blocks(guide_text)
    assert len(blocks) >= 11, (
        f"expected >=11 fenced blocks, got {len(blocks)}"
    )
    # At least one bash block and at least one text block.
    langs = {b[0] for b in blocks}
    assert "bash" in langs
    assert "text" in langs


# T-G1G2-SMOKE-05 ---------------------------------------------------------
def test_quote_aware_semi_split_keeps_quoted_semi(helper_mod):
    """Quote-aware split must NOT break python3 -c 'a; b' on the ';'."""
    parts = helper_mod._quote_aware_semi_split(
        "python3 -c 'import json,sys; print(json.load(sys.stdin)[\"x\"])'"
    )
    assert len(parts) == 1, (
        "quote-aware split must keep quoted ';' intact"
    )
    # And it MUST split on a real outside-quote ';'.
    parts2 = helper_mod._quote_aware_semi_split("a=1; b=2")
    assert parts2 == ["a=1", "b=2"]


# T-G1G2-SMOKE-06 ---------------------------------------------------------
def test_unknown_bash_binary_is_syntax_drift(helper_mod, tmp_path):
    """A bash block with an unknown argv0 yields RECIPE-SYNTAX-DRIFT."""
    # Set up a synthetic repo-root that mirrors the live substrate so
    # the semantic-stage findings are zero.
    _synth = _make_synth_root(tmp_path, with_substrate=True)
    text = _make_synth_doc(
        bash="totallyfakecmd --do-thing\n"
        "grep -rn DIGEST_PENDING_KAI_CROSS_REVIEW policies/\n"
        "gh workflow run cosign-strict-mode-readiness-check -R wakir-labs/wakir-runtime\n"
        "gh workflow run cosign-keyless-oidc-drift-probe -R wakir-labs/wakir-runtime -f mode=fixture -f exit_non_zero_on_drift=true",
    )
    result = helper_mod.validate_recipe(text, _synth)
    assert result["verdict"] == "RECIPE-SYNTAX-DRIFT", (
        f"unexpected verdict {result['verdict']}; findings = "
        f"{[f.render() for f in result['findings']]}"
    )


# T-G1G2-SMOKE-07 ---------------------------------------------------------
def test_unknown_gh_shape_is_semantic_drift(helper_mod, tmp_path):
    """A bash block with an unknown gh-call shape -> SEMANTIC-DRIFT."""
    _synth = _make_synth_root(tmp_path, with_substrate=True)
    text = _make_synth_doc(
        bash="gh workflow run something-totally-unrelated -R wakir-labs/wakir-runtime",
    )
    result = helper_mod.validate_recipe(text, _synth)
    assert result["verdict"] == "RECIPE-SEMANTIC-DRIFT"
    msgs = [f.message for f in result["findings"]]
    assert any("unknown gh-call shape" in m for m in msgs)


# T-G1G2-SMOKE-08 ---------------------------------------------------------
def test_malformed_yaml_is_syntax_drift(helper_mod, tmp_path):
    """A yaml fence with invalid YAML -> RECIPE-SYNTAX-DRIFT."""
    _synth = _make_synth_root(tmp_path, with_substrate=True)
    bad_yaml = "key: value\n  bad: : :\nmore: [unterminated"
    text = (
        _make_synth_doc(bash="grep -rn DIGEST_PENDING_KAI_CROSS_REVIEW policies/")
        + f"\n\n```yaml\n{bad_yaml}\n```\n"
    )
    result = helper_mod.validate_recipe(text, _synth)
    assert result["verdict"] == "RECIPE-SYNTAX-DRIFT"
    msgs = [f.message for f in result["findings"]]
    assert any("yaml.safe_load failed" in m for m in msgs)


# T-G1G2-SMOKE-09 ---------------------------------------------------------
def test_malformed_json_is_syntax_drift(helper_mod, tmp_path):
    """A json fence with invalid JSON -> RECIPE-SYNTAX-DRIFT."""
    _synth = _make_synth_root(tmp_path, with_substrate=True)
    bad_json = "{ \"k\": "  # unterminated
    text = (
        _make_synth_doc(bash="grep -rn DIGEST_PENDING_KAI_CROSS_REVIEW policies/")
        + f"\n\n```json\n{bad_json}\n```\n"
    )
    result = helper_mod.validate_recipe(text, _synth)
    assert result["verdict"] == "RECIPE-SYNTAX-DRIFT"


# T-G1G2-SMOKE-10 ---------------------------------------------------------
def test_missing_placeholder_token_is_semantic_drift(helper_mod, tmp_path):
    """Guide must literally mention DIGEST_PENDING_KAI_CROSS_REVIEW."""
    _synth = _make_synth_root(tmp_path, with_substrate=True)
    text = (
        "# G1+G2 guide stub\n\n"
        "Stub body missing the placeholder. Mentions "
        "PENDING_OPERATOR_HAND_REFRESH only.\n\n"
        "```bash\ngrep -rn nothing policies/\n```\n"
    )
    result = helper_mod.validate_recipe(text, _synth)
    assert result["verdict"] == "RECIPE-SEMANTIC-DRIFT"
    msgs = [f.message for f in result["findings"]]
    assert any("DIGEST_PENDING_KAI_CROSS_REVIEW" in m for m in msgs)


# T-G1G2-SMOKE-11 ---------------------------------------------------------
def test_missing_pending_token_is_semantic_drift(helper_mod, tmp_path):
    """Guide must literally mention PENDING_OPERATOR_HAND_REFRESH."""
    _synth = _make_synth_root(tmp_path, with_substrate=True)
    text = (
        "# G1+G2 guide stub\n\n"
        "Stub body mentions DIGEST_PENDING_KAI_CROSS_REVIEW only.\n\n"
        "```bash\ngrep -rn DIGEST_PENDING_KAI_CROSS_REVIEW policies/\n```\n"
    )
    result = helper_mod.validate_recipe(text, _synth)
    assert result["verdict"] == "RECIPE-SEMANTIC-DRIFT"
    msgs = [f.message for f in result["findings"]]
    assert any("PENDING_OPERATOR_HAND_REFRESH" in m for m in msgs)


# T-G1G2-SMOKE-12 ---------------------------------------------------------
def test_workflow_existence_cross_check(helper_mod, tmp_path):
    """Both referenced workflows must exist on disk."""
    # Synth root WITHOUT workflows -> SEMANTIC-DRIFT.
    _synth = _make_synth_root(tmp_path, with_substrate=True, with_workflows=False)
    text = _make_synth_doc(
        bash="grep -rn DIGEST_PENDING_KAI_CROSS_REVIEW policies/\n"
        "gh workflow run cosign-strict-mode-readiness-check -R wakir-labs/wakir-runtime",
    )
    result = helper_mod.validate_recipe(text, _synth)
    assert result["verdict"] == "RECIPE-SEMANTIC-DRIFT"
    msgs = [f.message for f in result["findings"]]
    assert any("workflows/" in m for m in msgs)
    # Live repo has both workflows -> they ARE referenced.
    refs = helper_mod.WORKFLOW_REFS
    assert "cosign-strict-mode-readiness-check" in refs
    assert "cosign-keyless-oidc-drift-probe" in refs
    for ref in refs:
        assert (REPO_ROOT / ".github" / "workflows" / f"{ref}.yml").exists()


# T-G1G2-SMOKE-13 ---------------------------------------------------------
def test_aggregate_verdict_precedence(helper_mod):
    """SEMANTIC drift outranks SYNTAX drift in the aggregate."""
    F = helper_mod.Finding
    assert helper_mod.aggregate_verdict([]) == "RECIPE-INTACT"
    assert (
        helper_mod.aggregate_verdict([F("stage-1", "error", "x", "y")])
        == "RECIPE-SYNTAX-DRIFT"
    )
    assert (
        helper_mod.aggregate_verdict([F("stage-3", "error", "x", "y")])
        == "RECIPE-SEMANTIC-DRIFT"
    )
    # Mixed: semantic wins.
    assert (
        helper_mod.aggregate_verdict(
            [
                F("stage-1", "error", "x", "y"),
                F("stage-3b", "error", "x", "y"),
            ]
        )
        == "RECIPE-SEMANTIC-DRIFT"
    )


# T-G1G2-SMOKE-14 ---------------------------------------------------------
def test_cli_main_exits_zero_on_live(helper_mod):
    """CLI main() against the live repo-root exits 0."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        rc = helper_mod.main(
            [
                "--doc",
                "docs/operations/cosign-g1-g2-operator-setup.md",
                "--repo-root",
                str(REPO_ROOT),
            ]
        )
    assert rc == 0, f"stdout={stdout.getvalue()} stderr={stderr.getvalue()}"
    assert "RECIPE-INTACT" in stdout.getvalue()


# T-G1G2-SMOKE-15 ---------------------------------------------------------
def test_cli_main_exits_one_on_missing_guide(helper_mod, tmp_path):
    """CLI main() against a missing guide path exits 1."""
    stderr = io.StringIO()
    stdout = io.StringIO()
    with redirect_stderr(stderr), redirect_stdout(stdout):
        rc = helper_mod.main(
            [
                "--doc",
                "docs/operations/does-not-exist.md",
                "--repo-root",
                str(tmp_path),
            ]
        )
    assert rc == 1
    assert "[FATAL]" in stderr.getvalue() or "[FATAL]" in stdout.getvalue()


# T-G1G2-SMOKE-16 ---------------------------------------------------------
def test_workflow_file_carries_spdx_header():
    """The workflow YAML carries the SPDX-License-Identifier."""
    assert WORKFLOW_PATH.exists(), f"missing workflow: {WORKFLOW_PATH}"
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "SPDX-License-Identifier: Apache-2.0" in text


# T-G1G2-SMOKE-17 ---------------------------------------------------------
def test_workflow_declares_all_three_triggers():
    """Workflow declares push + pull_request + workflow_dispatch."""
    wf = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    # YAML maps "on:" to True (the boolean) because PyYAML interprets
    # the bare "on" key. Accept either form.
    on = wf.get("on", wf.get(True))
    assert on is not None, f"workflow missing 'on:' key: {list(wf)}"
    assert "push" in on
    assert "pull_request" in on
    assert "workflow_dispatch" in on


# T-G1G2-SMOKE-18 ---------------------------------------------------------
def test_workflow_path_filter_mentions_guide_helper_tests():
    """Path-filter covers guide + helper + tests + workflow itself."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "docs/operations/cosign-g1-g2-operator-setup.md" in text
    assert "tooling/ci/validate_g1_g2_operator_recipe.py" in text
    assert "tests/ci/test_g1_g2_operator_recipe_validation.py" in text
    assert ".github/workflows/g1-g2-operator-recipe-smoke-validation.yml" in text


# T-G1G2-SMOKE-19 ---------------------------------------------------------
def test_known_shape_table_covers_both_workflow_refs(helper_mod):
    """Each WORKFLOW_REFS entry has at least one matching GH_KNOWN_SHAPES row."""
    shapes_text = "\n".join(s for _, s in helper_mod.GH_KNOWN_SHAPES)
    for ref in helper_mod.WORKFLOW_REFS:
        assert ref in shapes_text, (
            f"WORKFLOW_REFS entry '{ref}' has no matching shape row"
        )


# ---------------------------------------------------------------------------
# Synthetic-substrate helpers (hermetic — no network, no real bins).
# ---------------------------------------------------------------------------


def _make_synth_root(
    tmp_path: Path,
    with_substrate: bool,
    with_workflows: bool = True,
) -> Path:
    """Build a minimal in-tmp repo-root for negative-test scenarios."""
    root = tmp_path / "synth-repo"
    (root / "policies").mkdir(parents=True, exist_ok=True)
    (root / "state" / "cosign-drift").mkdir(parents=True, exist_ok=True)
    (root / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    if with_substrate:
        (root / "policies" / "cosign-policy-phase-3b.yaml").write_text(
            "stub: true\n", encoding="utf-8"
        )
        (root / "state" / "cosign-drift" / "pinned-trust-root.json").write_text(
            "{}\n", encoding="utf-8"
        )
    if with_workflows:
        for wf in (
            "cosign-strict-mode-readiness-check",
            "cosign-keyless-oidc-drift-probe",
        ):
            (root / ".github" / "workflows" / f"{wf}.yml").write_text(
                f"name: {wf}\non: workflow_dispatch\n", encoding="utf-8"
            )
    return root


def _make_synth_doc(bash: str) -> str:
    """Wrap a bash snippet into a minimal guide-shaped markdown."""
    return (
        "# Synthetic G1+G2 guide for negative tests\n\n"
        "References placeholder token DIGEST_PENDING_KAI_CROSS_REVIEW "
        "and pending token PENDING_OPERATOR_HAND_REFRESH so the "
        "substrate-token check passes by default.\n\n"
        f"```bash\n{bash}\n```\n"
    )
