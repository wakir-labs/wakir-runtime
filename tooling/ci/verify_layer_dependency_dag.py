#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cross-Layer Dependency-DAG verifier for the 6-Layer Acceptance-Pyramide.

Auftrag-Anker
-------------

Tag-58 Amara Auftrag (Mira, 2026-05-19, Continuous-Mode): the Tag-57
Pre-Cutover Acceptance Run-Order doc
(``docs/quality-gates/pre-cutover-acceptance-run-order.md`` §4.1)
declares ten directed dep-graph edges across the six Pyramide-layer
test-files. This helper verifies the declared DAG against the
actually-observable substrate-consumption topology of the six
Layer-test files.

Methodology
-----------

For each Layer-N test-file (the six canonical anchors per
``docs/quality-gates/marathon-acceptance-pyramide.md`` §2 and the
Tag-57 run-order-doc §2):

* **Stage A** - AST walk. Parse the test-file. Walk every
  ``ast.Constant`` node whose value is a ``str`` and collect
  references to the other five Layer-test-file basenames. These
  string-literals are the substrate-consumption signal: a Layer-N
  test-file that references ``test_phase_3_final_regression.py``
  signals that Layer-N consumes the Layer-1 substrate (via path
  introspection, importlib loading, or docstring citation - the
  three Layer-test patterns observed in the Tag-40..Tag-52 wave).

* **Stage B** - Cross-match. The collected basename references
  become an *observed* edge-set. The DAG spec (per §4.1) is the
  *declared* edge-set. The verifier emits a DAG-CONSISTENT verdict
  iff every declared edge is observed AND every observed edge is
  declared, OR iff observed-extras are explicitly whitelisted as
  ``soft-cite`` (docstring-only cross-citation that does not change
  the topology).

* **Stage C** - Verdict. Emit one of the following verdicts:
  - ``DAG-CONSISTENT``: declared = observed (modulo soft-cite
    whitelist) AND no allowlist entry was needed. Exit 0.
  - ``DAG-DRIFT-ALLOWED``: residual extras (observed-but-not-
    declared edges) are ALL covered by the Tag-61 drift-allowlist.
    Each allowed extra carries an edge + reason + follow-up-
    reference (e.g. an ADR/issue id). Exit 0. (Analogue of the
    ADR-Errata CI-pin-skip-pattern.)
  - ``DAG-DRIFT-BLOCKED``: residual extras or missing edges
    remain after allowlist consultation. Exit 2.
  - ``DAG-DRIFT``: legacy alias for ``DAG-DRIFT-BLOCKED`` for
    backwards-compat with Tag-58 consumers that branch on the
    short string. Same exit 2.
  - ``DAG-PARSE-ERROR``: a Layer-test-file failed to parse, the
    DAG-spec failed to load, the canonical Pyramide map is
    missing, or the allowlist file is malformed. Exit 1.

The verifier also enforces the DAG-acyclicity invariant (per §4.3):
the declared edges must form a DAG. If a cycle is detected, exit 2
with ``DAG-CYCLE``.

DAG-spec source-of-truth
------------------------

The canonical DAG-spec is embedded as ``LAYER_DEP_EDGES`` below,
derived verbatim from the Tag-57 run-order-doc §4.1 edge-inventory.
This is a code-level snapshot; the parallel doc-table is the human-
readable form. Drift between code-spec and doc-spec is caught by
the test-suite ``tests/ci/test_layer_dependency_dag_verify_tag58.py``.

The Layer -> test-file map is similarly embedded as ``LAYER_FILES``
to keep the verifier hermetic (no extra YAML/JSON file to load at
gate-time). Drift between the embedded map and the Pyramide doc is
also caught by the test-suite.

Hermetic
--------

Stdlib only: ``ast``, ``pathlib``, ``sys``, ``json``,
``argparse``, ``collections``. No subprocess, no network, no
third-party deps. Pure local-file-system read.

Exit codes
----------

* ``0`` - DAG-CONSISTENT.
* ``1`` - DAG-PARSE-ERROR (input invalid, files missing).
* ``2`` - DAG-DRIFT or DAG-CYCLE.

Usage
-----

    python tooling/ci/verify_layer_dependency_dag.py [--repo-root PATH]
                                                     [--json]
                                                     [--strict]
                                                     [--allowlist-path PATH]

* ``--repo-root PATH`` - root of the wakir-runtime checkout. Defaults
  to the current working directory.
* ``--json`` - emit the verdict envelope as JSON on stdout (for
  workflow step-summary consumption); human-readable diagnostics
  still go to stderr.
* ``--strict`` - treat soft-cite observed-extras as DRIFT. Default
  is permissive: docstring-only cross-citations are not topology
  changes and are allowed to be unmatched. Set when the DAG-spec
  is intended to be the *complete* edge-set including soft-cites
  (e.g. for ADR-locked spec).
* ``--allowlist-path PATH`` - Tag-61 drift-allowlist JSON file.
  When the residual extras-set (after soft-cite filtering) is
  fully covered by allowlist entries, the verdict downgrades from
  ``DAG-DRIFT-BLOCKED`` (exit 2) to ``DAG-DRIFT-ALLOWED`` (exit 0).
  Defaults to ``tooling/ci/layer-dag-drift-allowlist.json`` under
  the repo-root. Missing file is OK (treated as empty allowlist).
  Malformed file is a PARSE-ERROR.

Allowlist file format (Tag-61)
------------------------------

JSON object with shape::

    {
      "_schema": {
        "version": 1,
        "description": "Tag-61 layer-DAG-verify drift allowlist...",
        "owner": "Amara Osei (QA)"
      },
      "entries": [
        {
          "from_layer": 4,
          "to_layer": 2,
          "reason": "Why this cross-import is legitimate.",
          "follow_up": "ADR-XXXX or issue-link tracking permanent
                        spec update."
        },
        ...
      ]
    }

Each entry covers ONE directed edge. ``follow_up`` is mandatory
(no silent allowance): every drift-allowed edge MUST point at a
tracked follow-up so the allowlist does not accumulate stale
entries. Empty allowlist (initial Tag-61 state) is by design.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Mapping, Sequence, Set, Tuple


# ---------------------------------------------------------------
# Canonical Pyramide spec (verbatim from Tag-57 §2 + §4.1)
# ---------------------------------------------------------------

LAYER_FILES: Mapping[int, str] = {
    1: "tests/phase_3c/test_phase_3_final_regression.py",
    2: "tests/phase_3c/test_cutover_day_e2e_drill.py",
    3: "tests/phase_3c/test_marathon_schluss_acceptance_drill.py",
    4: "tests/phase_3c/test_marathon_anti_patterns.py",
    5: "tests/phase_3c/test_pre_mortem_failure_mode_coverage_audit.py",
    6: "tests/phase_3c/test_defence_in_depth_layer_6.py",
}


# Edge inventory (Tag-58 reconciliation of Tag-57 §4.1 against the
# actual substrate at main-tip 68ce0e4). Each tuple:
#   (from-layer, to-layer, edge-type, short-description)
#
# Direction semantics (§4): ``A -> B`` means B's contract assumes
# A's substrate exists. Concretely: B's test-file consumes A's
# substrate by (a) referencing A's filename via string-literal, or
# (b) consuming a data-record A produces at runtime, or (c) loading
# A's module via importlib.
#
# Three edge-classes
# ------------------
#
# * ``source-cited``: B's test-file contains a string-literal
#   reference to A's filename. Verified by AST-walk of B against
#   A's basename. The DAG-verifier asserts these against the
#   observed-edge-set at gate-time.
#
# * ``semantic-only``: B consumes a record-format / JSON-shape A
#   produces, but B's test-file does NOT cite A's filename
#   textually (typically because B predates A or because the
#   coupling is at the JSON-key level, not the test-file level).
#   These edges are documented in the spec but EXEMPTED from the
#   source-cited cross-match. The dep-graph still includes them
#   for cycle-detection and operator-summary.
#
# * ``dynamic-cross-check``: A runtime back-edge that is
#   intentionally cycle-permitting (the only such edge in the
#   spec is ``L6 -> L1``, the Doppel-Welle disjointness re-fire).
#   Exempted from acyclicity-check at the static-edge subset.
LAYER_DEP_EDGES: Tuple[Tuple[int, int, str, str], ...] = (
    # Source-cited edges (verified by AST cross-match)
    (1, 3, "predicate-consumer",
     "L3 fires the marker-emit-gate (AC-1..AC-5) defined by L1."),
    (2, 3, "data-producer",
     "L3 threads seven L2-records into four-Wochen-sequence."),
    (1, 4, "substrate-existence",
     "L4 asserts the marker-emit-gate rejects ten anti-patterns."),
    (2, 4, "fixture-reuse",
     "L4 re-uses L2 Cutover-Mittwoch fixtures (Tag-58 reconciliation)."),
    (3, 4, "positive-negative-companion",
     "L4 negative-companion to L3 positive marathon-aggregate."),
    (1, 5, "coverage-introspection",
     "L5 attests L1..L4 cover the 23 Pre-Mortem failure-modes."),
    (2, 5, "coverage-introspection",
     "L5 attests L1..L4 cover the 23 Pre-Mortem failure-modes."),
    (3, 5, "coverage-introspection",
     "L5 attests L1..L4 cover the 23 Pre-Mortem failure-modes."),
    (4, 5, "coverage-introspection",
     "L5 attests L1..L4 cover the 23 Pre-Mortem failure-modes."),
    (1, 6, "defence-composition",
     "L6 composes A1-defence-layers from L1..L4."),
    (3, 6, "defence-composition",
     "L6 composes A1-defence-layers from L1..L4."),
    (4, 6, "defence-composition",
     "L6 composes A1-defence-layers from L1..L4."),
    (5, 6, "substrate-existence-check",
     "L6 asserts L5 stays on tree (additive-not-replacement invariant)."),
    # Semantic-only edges (NOT source-cited; record-level coupling)
    (2, 1, "data-producer",
     "L2 produces per-Welle sign-off-record consumed by L1 aggregate. "
     "Semantic-only: L1 predates L2 textually; coupling is at the "
     "sign-off-JSON-key level, not the filename level."),
    (2, 6, "fixture-reuse",
     "L6 composes per-day fixtures from L2. Semantic-only: L6 "
     "references L2 via Tag-43 anchor in its docstring (Layer-2 "
     "INTERNAL naming), not via L2's canonical filename."),
    # Dynamic-cross-check edges (intentional back-edge)
    (6, 1, "dynamic-cross-check",
     "L6 defence-in-depth smoke-rerun cross-checks Doppel-Welle "
     "disjointness. Static-subset-acyclic, runtime feedback only."),
)


# Edge classes (for selective verification)
SOURCE_CITED_TYPES: FrozenSet[str] = frozenset({
    "predicate-consumer",
    "data-producer",
    "substrate-existence",
    "substrate-existence-check",
    "coverage-introspection",
    "defence-composition",
    "fixture-reuse",
    "positive-negative-companion",
})
SEMANTIC_ONLY_TYPES: FrozenSet[str] = frozenset({
    # 'data-producer' is shared with source-cited; per-edge
    # classification by edge-tuple, not by type alone. See
    # ``_semantic_only_edges()`` below for the per-edge filter.
})
DYNAMIC_CROSS_CHECK_TYPES: FrozenSet[str] = frozenset({
    "dynamic-cross-check",
})


# Per-edge override: edges that share a source-cited type-name but
# are classified as semantic-only by Tag-58 reconciliation. Listed
# as (from, to) tuples. Membership in this set OVERRIDES the type-
# based classification.
SEMANTIC_ONLY_EDGES: FrozenSet[Tuple[int, int]] = frozenset({
    (2, 1),  # L1 predates L2 textually
    (2, 6),  # L6 cites L2 via Tag-43 anchor not filename
})


# Soft-cite whitelist: observed-extras tolerated under non-strict
# mode. Each entry is (from-layer, to-layer) identifying a citation
# that is documentation-only and does NOT participate in the
# substrate-consumption topology. Currently empty: the §4.1 edge
# inventory + Tag-58 reconciliation subsume all observed cites at
# the Tag-52 snapshot.
SOFT_CITE_WHITELIST: FrozenSet[Tuple[int, int]] = frozenset({
    (1, 2),  # L2 docstring cites L1 (Tag-40 anchor) for context.
})


# ---------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------


@dataclass(frozen=True)
class LayerRef:
    """An observed string-literal reference inside a Layer-test-file
    pointing to another Layer-test-file."""

    from_layer: int
    to_layer: int
    line: int  # source line in the consumer file
    raw: str  # the matched string-literal


@dataclass(frozen=True)
class AllowlistEntry:
    """One Tag-61 drift-allowlist entry: a legitimate cross-layer
    import that is observed in the substrate but not declared in
    the DAG-spec, with a tracked follow-up reference."""

    from_layer: int
    to_layer: int
    reason: str
    follow_up: str


@dataclass
class VerifyResult:
    """Verdict envelope for one verifier run."""

    # Verdict values:
    #   "DAG-CONSISTENT" - declared == observed, no allowlist needed
    #   "DAG-DRIFT-ALLOWED" - residual extras all allowlist-covered (Tag-61)
    #   "DAG-DRIFT-BLOCKED" - residual extras or missing remain (Tag-61)
    #   "DAG-DRIFT" - legacy alias for BLOCKED (Tag-58 back-compat)
    #   "DAG-CYCLE" - static-subset cycle
    #   "DAG-PARSE-ERROR" - missing file, syntax error, or malformed allowlist
    verdict: str
    exit_code: int
    declared_edges: List[Tuple[int, int]]
    observed_edges: List[Tuple[int, int]]
    missing_edges: List[Tuple[int, int]]  # declared but not observed
    extra_edges: List[Tuple[int, int]]  # observed but not declared (residual)
    cycle: List[int] = field(default_factory=list)
    parse_errors: List[str] = field(default_factory=list)
    soft_cites_skipped: List[Tuple[int, int]] = field(default_factory=list)
    # Tag-61: extras that were observed-but-not-declared but were
    # covered by an allowlist entry (and therefore not blocking).
    allowlisted_extras: List[Tuple[int, int]] = field(default_factory=list)
    # Tag-61: entries from the allowlist that did not match any
    # observed extra (stale entries). NOT blocking by themselves
    # but surfaced as notes for operator-hygiene.
    stale_allowlist_entries: List[Tuple[int, int]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {
                "verdict": self.verdict,
                "exit_code": self.exit_code,
                "declared_edges": sorted(self.declared_edges),
                "observed_edges": sorted(self.observed_edges),
                "missing_edges": sorted(self.missing_edges),
                "extra_edges": sorted(self.extra_edges),
                "cycle": list(self.cycle),
                "parse_errors": list(self.parse_errors),
                "soft_cites_skipped": sorted(self.soft_cites_skipped),
                "allowlisted_extras": sorted(self.allowlisted_extras),
                "stale_allowlist_entries": sorted(self.stale_allowlist_entries),
                "notes": list(self.notes),
            },
            indent=2,
            sort_keys=False,
        )


# ---------------------------------------------------------------
# AST extraction
# ---------------------------------------------------------------


def _file_to_layer(repo_root: Path) -> Dict[str, int]:
    """Build a basename -> layer-id lookup table.

    The lookup keys are the bare filename (no directory) because
    Layer-test-files cross-reference each other variously as
    ``test_phase_3_final_regression.py`` (docstring) and
    ``tests/phase_3c/test_phase_3_final_regression.py`` (Path
    literal). Matching on the basename covers both.
    """
    return {Path(p).name: layer for layer, p in LAYER_FILES.items()}


def _walk_layer_refs(layer_id: int, file_path: Path) -> List[LayerRef]:
    """AST-walk one Layer-test-file and collect references to the
    other Layer-test-file basenames as ``LayerRef`` entries.

    A reference is any ``ast.Constant`` of type ``str`` containing
    the basename of one of the other five Layer-test-files as a
    substring. Self-references (the file referencing itself) are
    not edges and are skipped.

    The line attribute is the source line of the AST node (the
    enclosing string-literal). Multiple references to the same
    target on the same line count as one (deduplicated downstream
    by edge-aggregation).
    """
    targets = {
        name: lyr
        for name, lyr in _file_to_layer(file_path.parent.parent.parent).items()
        if lyr != layer_id
    }
    src = file_path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(file_path))
    out: List[LayerRef] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant):
            continue
        if not isinstance(node.value, str):
            continue
        s = node.value
        for name, to_layer in targets.items():
            if name in s:
                out.append(
                    LayerRef(
                        from_layer=layer_id,
                        to_layer=to_layer,
                        line=node.lineno,
                        raw=s if len(s) < 200 else s[:197] + "...",
                    )
                )
    return out


def _aggregate_observed_edges(
    refs: Sequence[LayerRef],
) -> Set[Tuple[int, int]]:
    """Collapse a stream of per-line ``LayerRef`` entries into a
    set of directed dep-graph edges in the **§4.1 direction**.

    Direction-convention reminder
    -----------------------------

    Per Tag-57 run-order-doc §4: ``Layer-A -> Layer-B`` means
    "Layer-B's contract assumes Layer-A's substrate exists" — i.e.
    Layer-B is the *consumer* and Layer-A is the *producer*.

    The raw AST signal is the reverse: a string-literal reference
    inside Layer-B's test-file pointing to Layer-A's filename is
    a "Layer-B consumes Layer-A" signal. ``LayerRef.from_layer``
    is the consumer (the file the AST was walked over), and
    ``LayerRef.to_layer`` is the producer (the referenced file).

    To make the observed-edge-set directly comparable to the
    declared-edge-set under the §4.1 direction, we flip the
    tuple here: ``(producer, consumer)``.
    """
    return {(r.to_layer, r.from_layer) for r in refs}


# ---------------------------------------------------------------
# DAG topology
# ---------------------------------------------------------------


def _detect_cycle(
    edges: Sequence[Tuple[int, int]]
) -> List[int]:
    """Return a vertex-cycle if one exists in the directed edge-set,
    else return [].

    Algorithm: Kahn-style topological sort. If a topological order
    exists that covers every vertex involved in any edge, the graph
    is acyclic. Otherwise, the residual SCC contains the cycle; we
    return the residual vertex list as the cycle-witness.

    For the 6-layer DAG (n=6, |E|<=20) this is overkill performance-
    wise but maximally clear correctness-wise.
    """
    nodes: Set[int] = set()
    in_deg: Dict[int, int] = defaultdict(int)
    adj: Dict[int, List[int]] = defaultdict(list)
    for a, b in edges:
        nodes.add(a)
        nodes.add(b)
        adj[a].append(b)
        in_deg[b] += 1
    queue = deque(n for n in nodes if in_deg[n] == 0)
    visited = 0
    while queue:
        n = queue.popleft()
        visited += 1
        for m in adj[n]:
            in_deg[m] -= 1
            if in_deg[m] == 0:
                queue.append(m)
    if visited == len(nodes):
        return []
    # cycle witness = residual nodes
    residual = sorted(n for n in nodes if in_deg[n] > 0)
    return residual


def _declared_edge_set() -> Set[Tuple[int, int]]:
    """All declared edges, regardless of class."""
    return {(a, b) for (a, b, _typ, _desc) in LAYER_DEP_EDGES}


def _source_cited_edge_set() -> Set[Tuple[int, int]]:
    """Subset of declared edges that MUST be observable via AST
    cross-match in the substrate. Excludes semantic-only and
    dynamic-cross-check edges."""
    out: Set[Tuple[int, int]] = set()
    for (a, b, typ, _desc) in LAYER_DEP_EDGES:
        if typ in DYNAMIC_CROSS_CHECK_TYPES:
            continue
        if (a, b) in SEMANTIC_ONLY_EDGES:
            continue
        if typ in SOURCE_CITED_TYPES:
            out.add((a, b))
    return out


def _semantic_only_edge_set() -> Set[Tuple[int, int]]:
    """Subset of declared edges that are record-level / anchor-
    name couplings, NOT source-cited. Excluded from AST cross-
    match but included in dep-graph for cycle-detection and
    operator-summary."""
    out: Set[Tuple[int, int]] = set()
    for (a, b, _typ, _desc) in LAYER_DEP_EDGES:
        if (a, b) in SEMANTIC_ONLY_EDGES:
            out.add((a, b))
    return out


def _dynamic_cross_check_edge_set() -> Set[Tuple[int, int]]:
    """Subset of declared edges classified as runtime back-edges.
    Excluded from acyclicity-check on the static subset."""
    return {
        (a, b)
        for (a, b, typ, _d) in LAYER_DEP_EDGES
        if typ in DYNAMIC_CROSS_CHECK_TYPES
    }


# ---------------------------------------------------------------
# Allowlist loader (Tag-61)
# ---------------------------------------------------------------


DEFAULT_ALLOWLIST_RELPATH: str = "tooling/ci/layer-dag-drift-allowlist.json"


def load_allowlist(
    allowlist_path: Path,
) -> Tuple[List[AllowlistEntry], List[str]]:
    """Load and validate the Tag-61 drift-allowlist file.

    Returns ``(entries, errors)``. If ``errors`` is non-empty the
    file was malformed and the caller should emit PARSE-ERROR.
    If the file does not exist, returns ``([], [])`` (empty
    allowlist is the documented default).

    Validation rules:
    * Top-level must be a JSON object with an ``entries`` array.
    * Each entry must have integer ``from_layer`` in 1..6,
      integer ``to_layer`` in 1..6, ``from != to``, non-empty
      string ``reason``, non-empty string ``follow_up``.
    * Duplicate (from, to) entries are an error (one reason +
      one follow-up per edge).
    """
    errors: List[str] = []
    if not allowlist_path.is_file():
        return ([], errors)
    try:
        text = allowlist_path.read_text(encoding="utf-8")
    except OSError as exc:
        return ([], [f"allowlist read failure: {exc}"])
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        return ([], [f"allowlist JSON parse failure: {exc}"])
    if not isinstance(doc, dict):
        return ([], ["allowlist top-level is not a JSON object"])
    raw_entries = doc.get("entries", [])
    if not isinstance(raw_entries, list):
        return ([], ["allowlist 'entries' is not a list"])
    out: List[AllowlistEntry] = []
    seen: Set[Tuple[int, int]] = set()
    valid_layers = set(LAYER_FILES.keys())
    for idx, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            errors.append(f"allowlist entry {idx}: not an object")
            continue
        fl = raw.get("from_layer")
        tl = raw.get("to_layer")
        reason = raw.get("reason")
        follow_up = raw.get("follow_up")
        if not isinstance(fl, int) or fl not in valid_layers:
            errors.append(
                f"allowlist entry {idx}: from_layer must be int in "
                f"{sorted(valid_layers)}, got {fl!r}"
            )
            continue
        if not isinstance(tl, int) or tl not in valid_layers:
            errors.append(
                f"allowlist entry {idx}: to_layer must be int in "
                f"{sorted(valid_layers)}, got {tl!r}"
            )
            continue
        if fl == tl:
            errors.append(
                f"allowlist entry {idx}: self-edge L{fl}->L{tl} "
                "is not a valid drift edge"
            )
            continue
        if not isinstance(reason, str) or not reason.strip():
            errors.append(
                f"allowlist entry {idx}: 'reason' must be a "
                "non-empty string"
            )
            continue
        if not isinstance(follow_up, str) or not follow_up.strip():
            errors.append(
                f"allowlist entry {idx}: 'follow_up' must be a "
                "non-empty string (ADR-id / issue-link required)"
            )
            continue
        key = (fl, tl)
        if key in seen:
            errors.append(
                f"allowlist entry {idx}: duplicate edge "
                f"L{fl}->L{tl}; only one entry per edge"
            )
            continue
        seen.add(key)
        out.append(
            AllowlistEntry(
                from_layer=fl,
                to_layer=tl,
                reason=reason.strip(),
                follow_up=follow_up.strip(),
            )
        )
    return (out, errors)


def _allowlist_edges(
    entries: Sequence[AllowlistEntry],
) -> Set[Tuple[int, int]]:
    return {(e.from_layer, e.to_layer) for e in entries}


# ---------------------------------------------------------------
# Main verifier
# ---------------------------------------------------------------


def verify(
    repo_root: Path,
    *,
    strict: bool = False,
    allowlist_path: Path | None = None,
) -> VerifyResult:
    """Run the DAG-verifier over the repo at ``repo_root``.

    Steps:
    1. Verify the six canonical Layer-files exist on disk.
    2. Verify the declared DAG is acyclic (sanity-check the spec).
    3. AST-walk each Layer-file, collect observed-edges.
    4. Cross-match observed vs declared. Apply allowlist (Tag-61).
       Emit verdict.

    Tag-61: ``allowlist_path`` defaults to
    ``{repo_root}/tooling/ci/layer-dag-drift-allowlist.json``.
    Missing file = empty allowlist (no allowed extras). Malformed
    file = DAG-PARSE-ERROR.
    """
    declared_all = _declared_edge_set()
    declared = _source_cited_edge_set()
    declared_list = sorted(declared_all)
    parse_errors: List[str] = []

    # Tag-61: load allowlist before file-existence checks so that a
    # malformed allowlist surfaces as PARSE-ERROR even if the layer-
    # files are also missing (both are spec-integrity failures).
    if allowlist_path is None:
        allowlist_path = repo_root / DEFAULT_ALLOWLIST_RELPATH
    allowlist_entries, allowlist_errors = load_allowlist(allowlist_path)
    if allowlist_errors:
        return VerifyResult(
            verdict="DAG-PARSE-ERROR",
            exit_code=1,
            declared_edges=declared_list,
            observed_edges=[],
            missing_edges=[],
            extra_edges=[],
            parse_errors=[f"allowlist {allowlist_path}: {e}"
                          for e in allowlist_errors],
        )
    allowlist_edges = _allowlist_edges(allowlist_entries)

    # Step 1: existence of all six canonical files
    paths: Dict[int, Path] = {}
    for layer_id, rel in sorted(LAYER_FILES.items()):
        p = repo_root / rel
        if not p.is_file():
            parse_errors.append(
                f"Layer-{layer_id} test-file not found at {p}"
            )
        else:
            paths[layer_id] = p
    if parse_errors:
        return VerifyResult(
            verdict="DAG-PARSE-ERROR",
            exit_code=1,
            declared_edges=declared_list,
            observed_edges=[],
            missing_edges=[],
            extra_edges=[],
            parse_errors=parse_errors,
        )

    # Step 2: acyclicity sanity on the declared spec
    cycle = _detect_cycle(sorted(declared_all))
    if cycle:
        # NOTE: the §4.1 spec contains the back-edge L6 -> L1 which
        # at first glance looks like a cycle when combined with
        # L1 -> L6. It IS a cycle in the strict graph-theoretic
        # sense. §4.3 explicitly classifies L6 -> L1 as a *dynamic
        # cross-check* at runtime, not a substrate-existence
        # dependency; the static dep-graph without it remains
        # acyclic. We model this by partitioning edges and only
        # requiring the static subset to be acyclic.
        dynamic = _dynamic_cross_check_edge_set()
        static_edges = [e for e in declared_all if e not in dynamic]
        static_cycle = _detect_cycle(static_edges)
        if static_cycle:
            return VerifyResult(
                verdict="DAG-CYCLE",
                exit_code=2,
                declared_edges=declared_list,
                observed_edges=[],
                missing_edges=[],
                extra_edges=[],
                cycle=static_cycle,
                notes=[
                    "Declared static-edge subset contains a cycle. "
                    "§4.3 invariant violated."
                ],
            )
        # else: cycle exists only on the full graph, which is the
        # documented L6->L1 dynamic cross-check. Acceptable.

    # Step 3: AST-walk each Layer-file
    all_refs: List[LayerRef] = []
    for layer_id, p in paths.items():
        try:
            refs = _walk_layer_refs(layer_id, p)
            all_refs.extend(refs)
        except SyntaxError as exc:
            parse_errors.append(
                f"Layer-{layer_id} ({p.name}) syntax-error: {exc}"
            )
    if parse_errors:
        return VerifyResult(
            verdict="DAG-PARSE-ERROR",
            exit_code=1,
            declared_edges=declared_list,
            observed_edges=[],
            missing_edges=[],
            extra_edges=[],
            parse_errors=parse_errors,
        )

    observed = _aggregate_observed_edges(all_refs)
    observed_list = sorted(observed)

    # Step 4: cross-match
    missing = sorted(declared - observed)
    extras = sorted(observed - declared)

    soft_cites: List[Tuple[int, int]] = []
    if not strict:
        # Move whitelisted soft-cites out of extras
        kept = []
        for e in extras:
            if e in SOFT_CITE_WHITELIST:
                soft_cites.append(e)
            else:
                kept.append(e)
        extras = kept

    # Tag-61: apply allowlist to residual extras. Allowlisted extras
    # are moved out of the blocking set; missing-edges are NEVER
    # allowlistable (the DAG-spec must accurately reflect what is
    # required, and missing means the declared invariant is not in
    # the substrate — that is a SPEC bug, not a drift to be excused).
    allowlisted_extras: List[Tuple[int, int]] = []
    residual_extras: List[Tuple[int, int]] = []
    for e in extras:
        if e in allowlist_edges:
            allowlisted_extras.append(e)
        else:
            residual_extras.append(e)

    # Stale-allowlist-detection: allowlist entries whose edge is
    # not actually observed any more (e.g. because the cross-import
    # was refactored away). Emitted as a note, not blocking.
    observed_set: Set[Tuple[int, int]] = set(observed)
    stale_allowlist = sorted(
        e for e in allowlist_edges if e not in observed_set
    )

    if not missing and not residual_extras and not allowlisted_extras:
        return VerifyResult(
            verdict="DAG-CONSISTENT",
            exit_code=0,
            declared_edges=declared_list,
            observed_edges=observed_list,
            missing_edges=[],
            extra_edges=[],
            soft_cites_skipped=sorted(soft_cites),
            allowlisted_extras=[],
            stale_allowlist_entries=stale_allowlist,
            notes=[
                f"6 layers, {len(declared_all)} declared edges total "
                f"({len(declared)} source-cited, "
                f"{len(_semantic_only_edge_set())} semantic-only, "
                f"{len(_dynamic_cross_check_edge_set())} dynamic-cross-check), "
                f"{len(observed)} observed source-edges, full match.",
            ],
        )

    notes: List[str] = []
    if missing:
        notes.append(
            f"{len(missing)} declared source-cited edge(s) NOT observed "
            f"in substrate: {missing}"
        )
    if allowlisted_extras:
        notes.append(
            f"{len(allowlisted_extras)} observed extra(s) covered by "
            f"Tag-61 drift-allowlist: {sorted(allowlisted_extras)}"
        )
    if residual_extras:
        notes.append(
            f"{len(residual_extras)} observed edge(s) NOT declared in "
            f"spec AND NOT allowlisted: {residual_extras}"
        )
    if stale_allowlist:
        notes.append(
            f"{len(stale_allowlist)} stale allowlist entry/entries "
            f"(edge not observed in substrate): {stale_allowlist}"
        )

    # Tag-61 verdict decision:
    # * missing edges OR residual non-allowlisted extras   -> BLOCKED
    # * only allowlisted extras (no missing, no residual)  -> ALLOWED
    if missing or residual_extras:
        return VerifyResult(
            verdict="DAG-DRIFT-BLOCKED",
            exit_code=2,
            declared_edges=declared_list,
            observed_edges=observed_list,
            missing_edges=missing,
            extra_edges=residual_extras,
            soft_cites_skipped=sorted(soft_cites),
            allowlisted_extras=sorted(allowlisted_extras),
            stale_allowlist_entries=stale_allowlist,
            notes=notes,
        )
    # allowlisted_extras non-empty, missing/residual empty
    return VerifyResult(
        verdict="DAG-DRIFT-ALLOWED",
        exit_code=0,
        declared_edges=declared_list,
        observed_edges=observed_list,
        missing_edges=[],
        extra_edges=[],
        soft_cites_skipped=sorted(soft_cites),
        allowlisted_extras=sorted(allowlisted_extras),
        stale_allowlist_entries=stale_allowlist,
        notes=notes,
    )


# ---------------------------------------------------------------
# CLI
# ---------------------------------------------------------------


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="verify_layer_dependency_dag",
        description=(
            "Verify the 6-Layer Acceptance-Pyramide cross-layer "
            "dependency DAG declared in pre-cutover-acceptance-run-"
            "order.md §4.1 against the actually-observable Layer-"
            "test-file substrate-consumption topology."
        ),
    )
    p.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repository root (default: current directory).",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit verdict envelope as JSON on stdout.",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="Treat soft-cite extras as DAG-DRIFT (no whitelist).",
    )
    p.add_argument(
        "--allowlist-path",
        type=Path,
        default=None,
        help=(
            "Tag-61 drift-allowlist JSON path. Defaults to "
            "{repo-root}/tooling/ci/layer-dag-drift-allowlist.json. "
            "Missing file = empty allowlist."
        ),
    )
    return p


def main(argv: Sequence[str]) -> int:
    args = _build_argparser().parse_args(argv[1:])
    repo_root = args.repo_root.resolve()
    if not repo_root.is_dir():
        print(
            f"::error::verify_layer_dependency_dag: --repo-root "
            f"{repo_root} is not a directory",
            file=sys.stderr,
        )
        return 1
    allowlist_path = args.allowlist_path
    if allowlist_path is not None:
        allowlist_path = allowlist_path.resolve()
    result = verify(
        repo_root,
        strict=args.strict,
        allowlist_path=allowlist_path,
    )
    if args.json:
        print(result.to_json())
    # Always emit a one-line summary on stderr for workflow logs.
    summary = (
        f"verify_layer_dependency_dag: verdict={result.verdict} "
        f"declared={len(result.declared_edges)} "
        f"observed={len(result.observed_edges)} "
        f"missing={len(result.missing_edges)} "
        f"extra={len(result.extra_edges)}"
    )
    print(summary, file=sys.stderr)
    for note in result.notes:
        print(f"  - {note}", file=sys.stderr)
    for err in result.parse_errors:
        print(f"  PARSE-ERROR: {err}", file=sys.stderr)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
