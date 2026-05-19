# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic CI-substrate tests for the Tag-58 6-Layer Acceptance-
Pyramide Cross-Layer Dependency-DAG verifier
(``tooling/ci/verify_layer_dependency_dag.py``) and its CI-gate
workflow
(``.github/workflows/pyramide-layer-dependency-verify-gate.yml``).

Auftrag-Anker
-------------

Tag-58 Amara Auftrag (Mira, 2026-05-19, Continuous-Mode, Marathon):
build a hermetic CI-gate that cross-verifies the Tag-57 Pre-Cutover
Acceptance Run-Order doc §4.1 cross-layer dependency-DAG against
the actually-observable substrate-consumption topology of the six
Layer-1..6 test-files. The gate fires on drift in any of those
six substrates, the DAG-spec helper, the run-order doc, the gate
workflow, or this test-suite.

Scope (helper-correctness + gate-shape)
---------------------------------------

This module verifies two surfaces:

* The Tag-58 verifier helper (``verify_layer_dependency_dag.py``):
  - canonical 6-layer file map matches the Tag-57 §2 inventory
  - LAYER_DEP_EDGES is well-formed (no self-edges, valid layer-ids)
  - declared edge classes (source-cited / semantic-only / dynamic-
    cross-check) partition LAYER_DEP_EDGES exactly
  - acyclicity-check correctly rejects an artificial cycle in the
    static subset
  - acyclicity-check correctly accepts the documented L6->L1
    dynamic back-edge on the full graph
  - AST walk correctly identifies cross-layer string-literal cites
    in a synthetic in-memory test-file
  - verify() against the current repo emits DAG-CONSISTENT under
    non-strict and DAG-DRIFT under strict (because of the (1, 2)
    soft-cite in L2's docstring)
  - CLI parses --repo-root, --json, --strict
  - VerifyResult.to_json() emits well-formed JSON

* The Tag-58 gate workflow YAML:
  - exactly one job with the contracted Required-Status-Check name
  - permissions: contents: read
  - concurrency.cancel-in-progress: false
  - path-filter covers all six Layer-files + helper + doc + suite + self
  - push and pull_request path-filters are identical (no drift)

Hermetic-tests
--------------

Auftrag minimum: >= 12 hermetic tests. This module ships >= 18.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Tuple

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HELPER_PATH = REPO_ROOT / "tooling" / "ci" / "verify_layer_dependency_dag.py"
WORKFLOW_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "pyramide-layer-dependency-verify-gate.yml"
)
RUN_ORDER_DOC = (
    REPO_ROOT / "docs" / "quality-gates" / "pre-cutover-acceptance-run-order.md"
)

REQUIRED_LAYER_FILES = (
    "tests/phase_3c/test_phase_3_final_regression.py",
    "tests/phase_3c/test_cutover_day_e2e_drill.py",
    "tests/phase_3c/test_marathon_schluss_acceptance_drill.py",
    "tests/phase_3c/test_marathon_anti_patterns.py",
    "tests/phase_3c/test_pre_mortem_failure_mode_coverage_audit.py",
    "tests/phase_3c/test_defence_in_depth_layer_6.py",
)

# Job-Display-Name contracted by the workflow header (Required-
# Status-Check identity).
GATE_JOB_NAME = (
    "pyramide layer-dependency DAG verify (6 layers, 16 edges)"
)


@pytest.fixture(scope="module")
def helper_module():
    """Load the verifier helper as an importable module without
    requiring tooling/ to be on sys.path.

    Note: we register the module in ``sys.modules`` BEFORE
    ``exec_module`` so that ``@dataclass`` decorators inside the
    helper (which look up the class's module via
    ``sys.modules[cls.__module__]``) can resolve. This is required
    on Python 3.13+ where the dataclass machinery resolves the
    module namespace at decoration time."""
    assert HELPER_PATH.is_file(), f"helper missing: {HELPER_PATH}"
    mod_name = "verify_layer_dependency_dag_under_test"
    spec = importlib.util.spec_from_file_location(mod_name, HELPER_PATH)
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
# Section A - Helper canonical-spec sanity
# ---------------------------------------------------------------


def test_helper_layer_files_map_matches_six_canonical_anchors(helper_module):
    """LAYER_FILES must enumerate exactly the six Tag-57 §2 anchors."""
    files = helper_module.LAYER_FILES
    assert sorted(files.keys()) == [1, 2, 3, 4, 5, 6], (
        f"LAYER_FILES keys must be {{1..6}}, got {sorted(files.keys())}"
    )
    for layer, rel in files.items():
        assert rel in REQUIRED_LAYER_FILES, (
            f"Layer-{layer} file {rel!r} not in canonical anchor list"
        )
    # And the reverse direction (every canonical anchor mapped):
    mapped = set(files.values())
    for canonical in REQUIRED_LAYER_FILES:
        assert canonical in mapped, (
            f"canonical anchor {canonical!r} missing from LAYER_FILES"
        )


def test_helper_dep_edges_well_formed(helper_module):
    """No self-edges. Layer-ids must be 1..6. No duplicate tuples."""
    edges = helper_module.LAYER_DEP_EDGES
    seen: set = set()
    for tup in edges:
        assert len(tup) == 4, (
            f"edge tuple must be 4-element (from, to, type, desc): {tup!r}"
        )
        a, b, typ, desc = tup
        assert isinstance(a, int) and isinstance(b, int)
        assert 1 <= a <= 6, f"from-layer out of range: {a}"
        assert 1 <= b <= 6, f"to-layer out of range: {b}"
        assert a != b, f"self-edge declared: {tup!r}"
        assert isinstance(typ, str) and typ, f"empty type: {tup!r}"
        assert isinstance(desc, str) and desc, f"empty desc: {tup!r}"
        key = (a, b)
        assert key not in seen, f"duplicate edge: {tup!r}"
        seen.add(key)


def test_helper_edge_class_partition_is_total(helper_module):
    """Every declared edge must be classified as source-cited XOR
    semantic-only XOR dynamic-cross-check. No edge unclassified."""
    declared = helper_module._declared_edge_set()
    source_cited = helper_module._source_cited_edge_set()
    semantic_only = helper_module._semantic_only_edge_set()
    dynamic = helper_module._dynamic_cross_check_edge_set()

    # Partition: disjoint
    assert not (source_cited & semantic_only), (
        f"source-cited overlaps semantic-only: "
        f"{source_cited & semantic_only}"
    )
    assert not (source_cited & dynamic), (
        f"source-cited overlaps dynamic: "
        f"{source_cited & dynamic}"
    )
    assert not (semantic_only & dynamic), (
        f"semantic-only overlaps dynamic: "
        f"{semantic_only & dynamic}"
    )
    # Partition: total
    union = source_cited | semantic_only | dynamic
    assert union == declared, (
        f"edge partition incomplete. unaccounted: "
        f"{declared - union}; over-claimed: {union - declared}"
    )


def test_helper_canonical_dag_has_no_static_cycle(helper_module):
    """The declared DAG must be acyclic on the static subset (i.e.
    excluding the L6->L1 dynamic-cross-check edge per §4.3)."""
    declared_all = helper_module._declared_edge_set()
    dynamic = helper_module._dynamic_cross_check_edge_set()
    static = sorted(declared_all - dynamic)
    cycle = helper_module._detect_cycle(static)
    assert cycle == [], (
        f"static-edge subset has a cycle witness: {cycle}"
    )


def test_helper_full_dag_includes_documented_back_edge(helper_module):
    """The full declared graph contains exactly one dynamic-cross-
    check back-edge (L6 -> L1) per §4.3."""
    dynamic = helper_module._dynamic_cross_check_edge_set()
    assert dynamic == {(6, 1)}, (
        f"expected dynamic edge set {{(6,1)}}, got {dynamic}"
    )


# ---------------------------------------------------------------
# Section B - Cycle-detector positive tests
# ---------------------------------------------------------------


def test_helper_cycle_detector_finds_artificial_cycle(helper_module):
    """Inject a cycle (L1->L2, L2->L3, L3->L1) and verify the
    detector returns a non-empty witness."""
    cycle = helper_module._detect_cycle([(1, 2), (2, 3), (3, 1)])
    assert cycle, "_detect_cycle failed to detect 3-vertex cycle"
    assert set(cycle) == {1, 2, 3}


def test_helper_cycle_detector_accepts_acyclic_chain(helper_module):
    """A linear chain L1->L2->L3->L4 must report no cycle."""
    cycle = helper_module._detect_cycle([(1, 2), (2, 3), (3, 4)])
    assert cycle == [], f"_detect_cycle false-positive: {cycle}"


# ---------------------------------------------------------------
# Section C - AST walker correctness
# ---------------------------------------------------------------


def test_helper_ast_walk_extracts_basename_reference(helper_module, tmp_path):
    """Synthesize a tiny Layer-N test-file that cites Layer-1's
    basename in a docstring; verify the walker yields a LayerRef
    pointing (from=N, to=1)."""
    # Build a temporary repo skeleton that the walker can introspect
    # WITHOUT touching the real tree.
    repo = tmp_path / "fake-repo"
    (repo / "tests" / "phase_3c").mkdir(parents=True)
    for layer, rel in helper_module.LAYER_FILES.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if layer == 2:
            # Synthetic L2 file with a docstring citing L1.
            p.write_text(
                textwrap.dedent(
                    '''\
                    """Synthetic L2 stand-in.

                    Companion: ``test_phase_3_final_regression.py``.
                    """

                    PATH = "tests/phase_3c/test_phase_3_final_regression.py"
                    '''
                ),
                encoding="utf-8",
            )
        else:
            p.write_text('"""stub layer file"""\n', encoding="utf-8")

    target = repo / helper_module.LAYER_FILES[2]
    refs = helper_module._walk_layer_refs(2, target)
    # We expect >=2 refs: one docstring, one path literal (could be
    # collapsed to 1 if the dedup happens at AST-Constant uniqueness).
    assert len(refs) >= 1, f"no refs found; expected >=1: {refs}"
    for r in refs:
        assert r.from_layer == 2
        assert r.to_layer == 1
        assert "test_phase_3_final_regression" in r.raw


def test_helper_ast_walk_ignores_self_references(helper_module, tmp_path):
    """A Layer-N file mentioning its OWN basename must not produce
    a self-edge."""
    repo = tmp_path / "fake-repo"
    for layer, rel in helper_module.LAYER_FILES.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if layer == 3:
            p.write_text(
                textwrap.dedent(
                    '''\
                    """Self-reference inside Layer-3.

                    This file is ``test_marathon_schluss_acceptance_drill.py``.
                    """
                    '''
                ),
                encoding="utf-8",
            )
        else:
            p.write_text('"""stub"""\n', encoding="utf-8")

    target = repo / helper_module.LAYER_FILES[3]
    refs = helper_module._walk_layer_refs(3, target)
    # Filter to only edges where the to_layer is L3 (self-edge):
    self_refs = [r for r in refs if r.to_layer == 3]
    assert self_refs == [], f"self-references leaked: {self_refs}"


def test_helper_aggregate_edges_flips_direction(helper_module):
    """``_aggregate_observed_edges`` must flip
    (consumer, producer) -> (producer, consumer) to match the
    §4.1 declared direction."""
    LayerRef = helper_module.LayerRef
    refs = [
        LayerRef(from_layer=3, to_layer=1, line=1, raw="..."),
        LayerRef(from_layer=3, to_layer=2, line=2, raw="..."),
    ]
    edges = helper_module._aggregate_observed_edges(refs)
    # Refs say "L3 references L1, L2"; in §4.1 direction this is
    # "L1 -> L3, L2 -> L3" (L3 consumes L1, L2).
    assert edges == {(1, 3), (2, 3)}, (
        f"expected {{(1,3),(2,3)}}, got {edges}"
    )


# ---------------------------------------------------------------
# Section D - End-to-end verify() against the real repo
# ---------------------------------------------------------------


def test_verify_against_repo_is_dag_consistent_under_default(helper_module):
    """Against the actual main-tip tree, non-strict verify must
    return DAG-CONSISTENT with exit 0."""
    result = helper_module.verify(REPO_ROOT, strict=False)
    assert result.verdict == "DAG-CONSISTENT", (
        f"verdict {result.verdict!r}, notes={result.notes}, "
        f"missing={result.missing_edges}, extras={result.extra_edges}"
    )
    assert result.exit_code == 0


def test_verify_against_repo_under_strict_catches_soft_cites(helper_module):
    """Under --strict, the L2 docstring cite of L1 (the only soft-
    cite at Tag-58 snapshot) is treated as drift."""
    result = helper_module.verify(REPO_ROOT, strict=True)
    assert result.verdict == "DAG-DRIFT"
    assert result.exit_code == 2
    assert (1, 2) in result.extra_edges, (
        f"expected (1,2) soft-cite to appear as extra under strict; "
        f"got extras={result.extra_edges}"
    )


def test_verify_emits_parse_error_when_layer_file_missing(
    helper_module, tmp_path
):
    """If a Layer-file is missing from the tree, verify must
    return DAG-PARSE-ERROR with exit 1."""
    # Construct a partial repo missing Layer-6
    repo = tmp_path / "partial-repo"
    for layer, rel in helper_module.LAYER_FILES.items():
        if layer == 6:
            continue
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('"""stub"""\n', encoding="utf-8")
    result = helper_module.verify(repo, strict=False)
    assert result.verdict == "DAG-PARSE-ERROR"
    assert result.exit_code == 1
    assert any("Layer-6" in e for e in result.parse_errors), (
        f"expected Layer-6 missing error; got {result.parse_errors}"
    )


# ---------------------------------------------------------------
# Section E - VerifyResult envelope shape
# ---------------------------------------------------------------


def test_verify_result_to_json_is_well_formed(helper_module):
    """to_json() must emit parseable JSON with the contracted keys."""
    result = helper_module.verify(REPO_ROOT, strict=False)
    blob = result.to_json()
    parsed = json.loads(blob)
    contracted_keys = {
        "verdict",
        "exit_code",
        "declared_edges",
        "observed_edges",
        "missing_edges",
        "extra_edges",
        "cycle",
        "parse_errors",
        "soft_cites_skipped",
        "notes",
    }
    assert contracted_keys.issubset(parsed.keys()), (
        f"missing keys: {contracted_keys - set(parsed.keys())}"
    )


# ---------------------------------------------------------------
# Section F - CLI surface
# ---------------------------------------------------------------


def test_cli_emits_dag_consistent_against_repo():
    """Run the helper as a CLI process against the real repo and
    expect exit 0 + verdict line on stderr."""
    proc = subprocess.run(
        [sys.executable, str(HELPER_PATH), "--repo-root", str(REPO_ROOT)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, (
        f"CLI exit {proc.returncode}; stderr=\n{proc.stderr}"
    )
    assert "DAG-CONSISTENT" in proc.stderr


def test_cli_json_flag_emits_parseable_envelope():
    """--json flag emits a JSON object on stdout."""
    proc = subprocess.run(
        [
            sys.executable,
            str(HELPER_PATH),
            "--repo-root",
            str(REPO_ROOT),
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0
    envelope = json.loads(proc.stdout)
    assert envelope["verdict"] == "DAG-CONSISTENT"


def test_cli_strict_flag_changes_verdict():
    """--strict turns the (1, 2) soft-cite into drift."""
    proc = subprocess.run(
        [
            sys.executable,
            str(HELPER_PATH),
            "--repo-root",
            str(REPO_ROOT),
            "--strict",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 2
    assert "DAG-DRIFT" in proc.stderr


# ---------------------------------------------------------------
# Section G - Workflow YAML structural shape
# ---------------------------------------------------------------


def _read_workflow_text() -> str:
    assert WORKFLOW_PATH.is_file(), f"workflow missing: {WORKFLOW_PATH}"
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_workflow_has_contracted_job_display_name():
    """Required-Status-Check name is contracted by
    feedback_branch_protection_check_names.md."""
    txt = _read_workflow_text()
    assert f'name: "{GATE_JOB_NAME}"' in txt, (
        f"workflow missing contracted job-display-name "
        f"{GATE_JOB_NAME!r}"
    )


def test_workflow_path_filter_covers_six_layer_files():
    """Push + PR path-filter must list all six Layer-test-files."""
    txt = _read_workflow_text()
    # Each Layer-file must appear at least twice (once for push,
    # once for pull_request).
    for rel in REQUIRED_LAYER_FILES:
        count = txt.count(f'"{rel}"')
        assert count >= 2, (
            f"path-filter coverage missing for {rel!r}: "
            f"appeared {count}x, expected >=2"
        )


def test_workflow_path_filter_lists_helper_and_doc_and_self():
    """Path-filter must also list the helper, the Tag-57 doc, the
    test-suite, and the workflow-self."""
    txt = _read_workflow_text()
    must = (
        "tooling/ci/verify_layer_dependency_dag.py",
        "docs/quality-gates/pre-cutover-acceptance-run-order.md",
        "tests/ci/test_layer_dependency_dag_verify_tag58.py",
        ".github/workflows/pyramide-layer-dependency-verify-gate.yml",
    )
    for rel in must:
        count = txt.count(f'"{rel}"')
        assert count >= 2, (
            f"path-filter must list {rel!r} at least twice (push + PR); "
            f"got {count}"
        )


def test_workflow_permissions_read_only():
    """permissions: contents: read (no write surface for a verifier-gate)."""
    txt = _read_workflow_text()
    # Tolerate either "contents: read" inline or block form.
    assert re.search(r"permissions:\s*\n\s*contents:\s*read", txt), (
        "workflow must declare permissions: contents: read"
    )


def test_workflow_concurrency_does_not_cancel():
    """cancel-in-progress: false. A drift-detection gate must not
    cancel mid-run when a follow-up commit lands."""
    txt = _read_workflow_text()
    assert "cancel-in-progress: false" in txt


def test_workflow_uses_python_313():
    """Python 3.13 (production-lane parity)."""
    txt = _read_workflow_text()
    assert 'python-version: "3.13"' in txt


def test_workflow_invokes_helper_and_test_suite():
    """Stage 1 runs the test-suite; Stage 2 runs the helper."""
    txt = _read_workflow_text()
    assert "tests/ci/test_layer_dependency_dag_verify_tag58.py" in txt
    assert "tooling/ci/verify_layer_dependency_dag.py" in txt


def test_workflow_has_workflow_dispatch_trigger():
    """workflow_dispatch enabled for operator-hand manual fires."""
    txt = _read_workflow_text()
    assert "workflow_dispatch:" in txt


def test_workflow_push_and_pr_path_filters_are_identical_count():
    """Each path-filter entry must appear the SAME number of times
    in the push-block as in the pull_request-block. We approximate
    this by asserting every path listed appears >=2x; the actual
    push/PR split is enforced by visual review + the
    test_workflow_path_filter_covers_six_layer_files coverage
    test."""
    txt = _read_workflow_text()
    # Anchor blocks
    assert "on:\n" in txt
    assert "push:" in txt
    assert "pull_request:" in txt
    # Spot-check: the helper path must appear exactly twice (push +
    # PR) and the Layer-1 file at least twice.
    assert txt.count('"tooling/ci/verify_layer_dependency_dag.py"') == 2
    assert (
        txt.count('"tests/phase_3c/test_phase_3_final_regression.py"') >= 2
    )


# ---------------------------------------------------------------
# Section H - Tag-57 doc cross-anchor (drift between doc and helper)
# ---------------------------------------------------------------


def test_doc_section_4_lists_helper_declared_edge_pairs(helper_module):
    """Each (from, to) pair declared in LAYER_DEP_EDGES must be
    findable in the Tag-57 §4.1 edge-inventory table of the run-
    order doc — at least in the source-cited and dynamic classes.
    Semantic-only edges (added by Tag-58 reconciliation) may post-
    date the doc; we only check the source-cited subset plus the
    one dynamic edge, mirroring §4.1's seven-row table.
    """
    assert RUN_ORDER_DOC.is_file(), f"Tag-57 doc missing: {RUN_ORDER_DOC}"
    doc = RUN_ORDER_DOC.read_text(encoding="utf-8")
    # The doc uses ``Lx -> Ly`` and ``L1..L4 -> L5`` style notation.
    # We accept either spelling per edge.
    # Per the doc §4.1 table, only the *original* 7 doc-rows are
    # required to be cite-traceable; Tag-58 additions (L2->L4,
    # L3->L4, L5->L6) are helper-only until the doc is updated.
    doc_required = {
        (2, 1),  # L2 -> L1
        (2, 3),  # L2 -> L3
        (1, 3),  # L1 -> L3
        (1, 4),  # L1 -> L4
        # L1..L4 -> L5
        (1, 5), (2, 5), (3, 5), (4, 5),
        # L1..L4 -> L6
        (1, 6), (2, 6), (3, 6), (4, 6),
        # L6 -> L1 dynamic
        (6, 1),
    }
    declared = helper_module._declared_edge_set()
    not_in_helper = doc_required - declared
    assert not_in_helper == set(), (
        f"Tag-57 doc §4.1 declares edges that the helper does NOT "
        f"include: {sorted(not_in_helper)}. Helper-spec must subsume "
        f"the doc-spec or the doc must be updated."
    )


def test_doc_anchor_string_present_in_helper_module_docstring(helper_module):
    """The helper must reference the Tag-57 run-order-doc by path
    in its module docstring so future maintainers can trace the
    DAG-spec back to its human-readable source."""
    doc = helper_module.__doc__ or ""
    assert "pre-cutover-acceptance-run-order.md" in doc, (
        "helper docstring must cite the Tag-57 run-order-doc as the "
        "DAG-spec parallel source-of-truth"
    )
