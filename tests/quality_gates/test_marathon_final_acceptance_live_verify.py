# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Live-Verification audit for ``docs/quality-gates/phase-3-marathon-
final-acceptance.md`` (Tag-55).

Auftrag-Anker
-------------

* Tag-55 Amara Auftrag (Mira, 2026-05-19, Continuous-Mode, AR-persistent):
  follow-up to Tag-54 PR #346 (the consolidated Final-Acceptance doc).
* Tag-54 introduced a hermetic *doc-side* audit
  (``test_phase_3_marathon_final_acceptance_doc.py``) that asserts the
  doc's TEXT contains the right surface citations.
* Tag-55 closes the second half of the verification surface: every
  claim the Tag-54 doc makes about on-tree substrate must verify
  against the current main-tip substrate, NOT just against the doc's
  own text. Drift between the doc and the substrate it describes is
  Tag-55's failure mode.

Scope (live-verify vs. doc-side audit)
--------------------------------------

The Tag-54 audit answers "does the doc cite the surface markers?".
The Tag-55 audit answers "do the surfaces the doc cites actually
exist on tree, in the cardinality the doc claims?". Specifically:

1. Surface-1 — every AC-N (AC-1..AC-5) referenced in the doc has a
   matching ``name: AC-N verify ...`` job in
   ``.github/workflows/phase-3-complete-marker.yml`` (the marker-
   workflow Tomas Tag-40 substrate).
2. Surface-2 — every Pyramide-layer test-file cited in the doc:
   * exists on tree;
   * is collected by pytest;
   * carries AT LEAST the doc-claimed test-count (drift-tolerant
     floor — per Tag-54 doc section 12 maintenance-contract, routine
     test-count drift is OK, but the floor MUST hold so the doc never
     overclaims);
   * does not drift more than a sane delta above the doc claim
     (sanity ceiling: doc-claim + 30 tests). A 30-test delta is the
     soft drift-watermark before the doc should be refreshed.
3. Surface-3 — every AP-N (AP-1..AP-10) cited in the doc resolves
   to an ``### AP-N`` heading in
   ``docs/quality-gates/phase-3-marathon-anti-patterns.md``.
4. Surface-4 — every Pre-Mortem class (Class-A..D) and the four-
   state taxonomy (COVERED / PARTIAL / GAP-ACCEPTED / GAP-OPEN)
   resolves to a heading in
   ``docs/quality-gates/pre-mortem-failure-mode-coverage.md``.
5. Surface-5 — every SLI-MARATHON-N (1..7) cited in the doc
   resolves to an ``### 2.N`` SLI heading in
   ``docs/observability/sli-slo-phase-3-marathon.md``.
6. Surface-Pre — every S-N (S1..S7) cited in the doc resolves to
   a ``${{ needs.s<N>-* }}`` reference in
   ``.github/workflows/pre-cutover-final-sanity-gate.yml``.
7. Cadence (ADR-0066) — the four KW cutover/sign-off dates
   (KW-24..KW-27, 2026-06-10 .. 2026-07-03) cited in the doc must
   appear in chronological order and as documented.
8. Companion-doc anchor consistency — every companion-doc file the
   doc cites must exist AND must carry its own canonical H1.

This audit is stdlib-only (re, pathlib, dataclasses, subprocess for
pytest-collection); no third-party deps beyond pytest itself; no
network IO; hermetic.

Hermetic-tests
--------------

Auftrag minimum: >= 15 hermetic tests. This module ships >= 20
(parametrised over surfaces).
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Tuple

import pytest

# ---------------------------------------------------------------------------
# Repo-root anchor.
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        if (ancestor / ".git").exists() or (ancestor / "pyproject.toml").exists():
            return ancestor
    raise RuntimeError(
        f"could not locate repo-root from {here!r} (no .git/ or "
        f"pyproject.toml ancestor)"
    )


REPO_ROOT = _repo_root()
DOC_PATH = (
    REPO_ROOT
    / "docs"
    / "quality-gates"
    / "phase-3-marathon-final-acceptance.md"
)


def _read_doc() -> str:
    assert DOC_PATH.exists(), (
        f"doc {DOC_PATH!r} missing — Tag-54 substrate not landed; "
        f"Tag-55 live-verify has nothing to verify against."
    )
    return DOC_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Surface-2 — Pyramide layer claims (Tag-53 doc-snapshot test-counts).
#
# Per Tag-54 doc §3:
#   Layer-1 (Tag-40): test_phase_3_final_regression.py             | 28
#   Layer-2 (Tag-41): test_cutover_day_e2e_drill.py                | 45
#   Layer-3 (Tag-43): test_marathon_schluss_acceptance_drill.py    | 27
#   Layer-4 (Tag-44): test_marathon_anti_patterns.py               | 20
#   Layer-5 (Tag-45): test_pre_mortem_failure_mode_coverage_audit  | 25
#   Layer-6 (Tag-52): test_defence_in_depth_layer_6.py             | 22
#
# Live-verify policy (drift-tolerant, floor-pinned):
#   * actual >= doc_claim (no overclaim).
#   * actual <= doc_claim + DRIFT_CEILING_DELTA (soft watermark).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PyramideLayer:
    layer_id: int
    tag_anchor: str
    test_file_rel: str
    doc_claimed_count: int


DRIFT_CEILING_DELTA = 30  # tests above doc-claim before doc-refresh expected

PYRAMIDE_LAYERS: Tuple[PyramideLayer, ...] = (
    PyramideLayer(1, "Tag-40", "tests/phase_3c/test_phase_3_final_regression.py", 28),
    PyramideLayer(2, "Tag-41", "tests/phase_3c/test_cutover_day_e2e_drill.py", 45),
    PyramideLayer(3, "Tag-43", "tests/phase_3c/test_marathon_schluss_acceptance_drill.py", 27),
    PyramideLayer(4, "Tag-44", "tests/phase_3c/test_marathon_anti_patterns.py", 20),
    PyramideLayer(5, "Tag-45", "tests/phase_3c/test_pre_mortem_failure_mode_coverage_audit.py", 25),
    PyramideLayer(6, "Tag-52", "tests/phase_3c/test_defence_in_depth_layer_6.py", 22),
)


def _pytest_collect_count(rel_path: str) -> int:
    """Return the number of tests pytest collects from ``rel_path``.

    Uses ``--collect-only -q`` and parses the trailing summary line
    (``"<count> tests collected"``).
    """
    target = REPO_ROOT / rel_path
    assert target.exists(), f"cannot collect from missing path {target!r}"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", str(target)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    # pytest --collect-only -q emits either
    #   "<count> tests collected in <t>s"
    # or, for older versions, a `module: <count>` summary line per file.
    text = result.stdout + "\n" + result.stderr
    m = re.search(r"^(\d+)\s+tests?\s+collected", text, re.MULTILINE)
    if m:
        return int(m.group(1))
    # Fallback: per-file summary line.
    m2 = re.search(rf"^{re.escape(rel_path)}:\s*(\d+)\s*$", text, re.MULTILINE)
    if m2:
        return int(m2.group(1))
    raise AssertionError(
        f"could not parse pytest --collect-only output for {rel_path!r}:\n"
        f"---stdout---\n{result.stdout}\n---stderr---\n{result.stderr}\n"
    )


# ---------------------------------------------------------------------------
# Surface-1 — AC-N marker-workflow job-name pins.
# ---------------------------------------------------------------------------


MARKER_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "phase-3-complete-marker.yml"
AC_IDS: Tuple[str, ...] = ("AC-1", "AC-2", "AC-3", "AC-4", "AC-5")


# ---------------------------------------------------------------------------
# Surface-3 — AP-N anti-pattern doc heading anchors.
# ---------------------------------------------------------------------------


ANTI_PATTERNS_DOC = (
    REPO_ROOT / "docs" / "quality-gates" / "phase-3-marathon-anti-patterns.md"
)
AP_IDS: Tuple[str, ...] = tuple(f"AP-{i}" for i in range(1, 11))  # AP-1..AP-10


# ---------------------------------------------------------------------------
# Surface-4 — Pre-Mortem class headings + four-state taxonomy.
# ---------------------------------------------------------------------------


PRE_MORTEM_DOC = (
    REPO_ROOT / "docs" / "quality-gates" / "pre-mortem-failure-mode-coverage.md"
)
PRE_MORTEM_CLASSES: Tuple[str, ...] = ("Class-A", "Class-B", "Class-C", "Class-D")
PRE_MORTEM_STATES: Tuple[str, ...] = (
    "COVERED",
    "PARTIAL",
    "GAP-ACCEPTED",
    "GAP-OPEN",
)


# ---------------------------------------------------------------------------
# Surface-5 — SLI-MARATHON-N section anchors.
# ---------------------------------------------------------------------------


SLI_DOC = REPO_ROOT / "docs" / "observability" / "sli-slo-phase-3-marathon.md"
SLI_IDS: Tuple[str, ...] = tuple(f"SLI-MARATHON-{i}" for i in range(1, 8))  # 1..7


# ---------------------------------------------------------------------------
# Surface-Pre — Pre-Cutover-Final-Sanity-Gate S-substrate anchors.
# ---------------------------------------------------------------------------


SANITY_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "pre-cutover-final-sanity-gate.yml"
)
S_IDS: Tuple[str, ...] = tuple(f"S{i}" for i in range(1, 8))  # S1..S7


# ---------------------------------------------------------------------------
# Cadence — ADR-0066 KW-24..KW-27 dates.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CadenceKW:
    kw_id: str
    cutover_mittwoch_iso: str  # date-only
    sign_off_freitag_iso: str  # date-only


CADENCE_KW: Tuple[CadenceKW, ...] = (
    CadenceKW("KW-24", "2026-06-10", "2026-06-12"),
    CadenceKW("KW-25", "2026-06-17", "2026-06-19"),
    CadenceKW("KW-26", "2026-06-24", "2026-06-26"),
    CadenceKW("KW-27", "2026-07-01", "2026-07-03"),
)


# ---------------------------------------------------------------------------
# Companion-doc canonical-H1 expectations.
# ---------------------------------------------------------------------------


COMPANION_H1: Mapping[str, str] = {
    "docs/quality-gates/marathon-acceptance-pyramide.md":
        "# Quality-Gate — Phase-3-Marathon-Acceptance-Pyramide (6-Layer)",
    "docs/quality-gates/phase-3-marathon-anti-patterns.md":
        "# Quality-Gate — Phase-3-Marathon-Anti-Pattern",
    "docs/quality-gates/pre-mortem-failure-mode-coverage.md":
        "# Quality-Gate — Phase-3-Marathon Pre-Mortem Failure-Mode Test-Coverage Matrix",
    "docs/quality-gates/phase-3-marathon-schluss-acceptance.md":
        "# Quality-Gate — Phase-3-Marathon-Schluss",
    "docs/ci/pre-cutover-final-sanity-gate-runbook.md":
        "# Pre-Cutover-Final-Sanity-Gate",
    "docs/observability/sli-slo-phase-3-marathon.md":
        "# SLI / SLO Catalogue — Phase-3 Marathon",
}


def _first_markdown_h1(text: str) -> str:
    """Return the first ``# `` H1 line in ``text``, skipping leading HTML
    comments / SPDX headers (some docs lead with ``<!-- ... -->`` blocks)."""
    in_comment = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("<!--"):
            in_comment = True
            if "-->" in stripped:
                in_comment = False
            continue
        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue
        if stripped.startswith("# "):
            return stripped
    raise AssertionError("no H1 found in markdown text")


# ===========================================================================
# §1 — Doc-presence pre-condition.
# ===========================================================================


def test_tag_54_doc_present_precondition() -> None:
    """The Tag-54 consolidated final-acceptance doc MUST be on tree.
    Without it, Tag-55 live-verify is a no-op."""
    assert DOC_PATH.exists(), (
        f"doc {DOC_PATH!r} missing — Tag-54 PR #346 was supposed to land "
        f"the consolidated final-acceptance doc; Tag-55 cannot live-verify "
        f"against a missing artefact."
    )


# ===========================================================================
# §2 — Surface-2 Pyramide-Layer live-substrate verification.
# ===========================================================================


@pytest.mark.parametrize(
    "layer",
    PYRAMIDE_LAYERS,
    ids=[f"L{layer.layer_id}-{layer.tag_anchor}" for layer in PYRAMIDE_LAYERS],
)
def test_pyramide_layer_test_file_exists_on_tree(layer: PyramideLayer) -> None:
    """Each Pyramide-layer test-file cited in the Tag-54 doc MUST exist."""
    p = REPO_ROOT / layer.test_file_rel
    assert p.exists(), (
        f"Pyramide-Layer-{layer.layer_id} ({layer.tag_anchor}) test-file "
        f"{layer.test_file_rel!r} missing on tree — Tag-54 doc cites it "
        f"but main-tip does not have it. File-presence-cascade broken."
    )


@pytest.mark.parametrize(
    "layer",
    PYRAMIDE_LAYERS,
    ids=[f"L{layer.layer_id}-{layer.tag_anchor}" for layer in PYRAMIDE_LAYERS],
)
def test_pyramide_layer_doc_claim_is_floor(layer: PyramideLayer) -> None:
    """Doc-claim is a FLOOR: actual collected-count >= doc-claim.

    The doc must never *overclaim* test substrate. Drift downward
    (actual < doc-claim) means the doc names tests that don't exist
    or counts incorrectly. The Tag-54 doc §12 maintenance-contract
    permits routine drift upward (more tests than claimed), so the
    floor is what Tag-55 pins."""
    actual = _pytest_collect_count(layer.test_file_rel)
    assert actual >= layer.doc_claimed_count, (
        f"Pyramide-Layer-{layer.layer_id} ({layer.tag_anchor}) overclaim: "
        f"doc says {layer.doc_claimed_count} tests, actual collected is "
        f"{actual}. The doc must never claim more substrate than exists."
    )


@pytest.mark.parametrize(
    "layer",
    PYRAMIDE_LAYERS,
    ids=[f"L{layer.layer_id}-{layer.tag_anchor}" for layer in PYRAMIDE_LAYERS],
)
def test_pyramide_layer_drift_within_ceiling(layer: PyramideLayer) -> None:
    """Drift-ceiling sanity check: actual <= doc-claim + DRIFT_CEILING_DELTA.

    Per Tag-54 doc §12 maintenance-contract, routine per-layer drift
    does NOT require a doc-refresh. But large drift (>30 tests above
    claim) signals the doc is stale enough that a refresh is overdue."""
    actual = _pytest_collect_count(layer.test_file_rel)
    ceiling = layer.doc_claimed_count + DRIFT_CEILING_DELTA
    assert actual <= ceiling, (
        f"Pyramide-Layer-{layer.layer_id} ({layer.tag_anchor}) drift "
        f"exceeds ceiling: doc claims {layer.doc_claimed_count}, actual "
        f"is {actual}, soft-watermark ceiling is {ceiling}. Tag-54 doc "
        f"§3 Pyramide-table is overdue for a refresh."
    )


def test_pyramide_sum_within_drift_envelope() -> None:
    """Cross-layer aggregate: the sum of actual test-counts MUST be
    >= the doc's claimed sum (Tag-53 snapshot: 167) and within the
    six-layer drift envelope (6 * DRIFT_CEILING_DELTA = 180 above)."""
    doc_sum = sum(layer.doc_claimed_count for layer in PYRAMIDE_LAYERS)
    assert doc_sum == 167, (
        f"sanity: PYRAMIDE_LAYERS doc-claim sum is {doc_sum}, expected "
        f"167 per Tag-53 snapshot (Tag-54 doc §3 'Sum (Tag-53 snapshot)')."
    )
    actual_sum = sum(
        _pytest_collect_count(layer.test_file_rel) for layer in PYRAMIDE_LAYERS
    )
    assert actual_sum >= doc_sum, (
        f"Cross-layer actual sum {actual_sum} < doc-claim sum {doc_sum} — "
        f"net under-substrate, the doc is overclaiming."
    )
    envelope_ceiling = doc_sum + len(PYRAMIDE_LAYERS) * DRIFT_CEILING_DELTA
    assert actual_sum <= envelope_ceiling, (
        f"Cross-layer actual sum {actual_sum} exceeds aggregate drift "
        f"envelope {envelope_ceiling} — doc-refresh of the Tag-53 snapshot "
        f"is overdue."
    )


# ===========================================================================
# §3 — Surface-1 AC-N marker-workflow job-name verification.
# ===========================================================================


def test_marker_workflow_exists_on_tree() -> None:
    """The Tag-40 marker-workflow file MUST exist; the doc cites it."""
    assert MARKER_WORKFLOW.exists(), (
        f"marker-workflow {MARKER_WORKFLOW!r} missing on tree — Tag-54 "
        f"doc cites this Tomas Tag-40 substrate; Surface-1 anchor broken."
    )


@pytest.mark.parametrize("ac_id", AC_IDS)
def test_marker_workflow_carries_ac_verify_job(ac_id: str) -> None:
    """Each AC-N (1..5) cited in the doc MUST resolve to a ``name: AC-N
    verify ...`` job entry in the marker-workflow YAML."""
    text = MARKER_WORKFLOW.read_text(encoding="utf-8")
    # The Tomas Tag-40 convention is `name: AC-N verify ...`.
    pat = re.compile(rf"^\s*name:\s*{re.escape(ac_id)}\s+verify\b", re.MULTILINE)
    assert pat.search(text), (
        f"marker-workflow does not contain a 'name: {ac_id} verify ...' "
        f"job entry; Surface-1 marker-emit-predicate {ac_id} is unanchored."
    )


# ===========================================================================
# §4 — Surface-3 AP-N anti-pattern heading verification.
# ===========================================================================


def test_anti_patterns_doc_exists_on_tree() -> None:
    """The Tag-44 anti-patterns doc MUST exist; doc cites it."""
    assert ANTI_PATTERNS_DOC.exists(), (
        f"anti-patterns doc {ANTI_PATTERNS_DOC!r} missing — Tag-54 doc "
        f"cites this Tag-44 substrate; Surface-3 anchor broken."
    )


@pytest.mark.parametrize("ap_id", AP_IDS)
def test_anti_patterns_doc_has_ap_heading(ap_id: str) -> None:
    """Each AP-N (1..10) cited in the Tag-54 doc MUST resolve to an
    ``### AP-N`` heading in the anti-patterns doc."""
    text = ANTI_PATTERNS_DOC.read_text(encoding="utf-8")
    pat = re.compile(rf"^###\s+{re.escape(ap_id)}\b", re.MULTILINE)
    assert pat.search(text), (
        f"anti-patterns doc does not have an '### {ap_id}' heading — "
        f"Tag-54 Surface-3 cites {ap_id} without anchor in the canonical "
        f"Tag-44 doc."
    )


# ===========================================================================
# §5 — Surface-4 Pre-Mortem class + state taxonomy verification.
# ===========================================================================


def test_pre_mortem_doc_exists_on_tree() -> None:
    """The Tag-45/46/50 Pre-Mortem coverage doc MUST exist."""
    assert PRE_MORTEM_DOC.exists(), (
        f"pre-mortem coverage doc {PRE_MORTEM_DOC!r} missing — Surface-4 "
        f"anchor broken."
    )


@pytest.mark.parametrize("pmc_class", PRE_MORTEM_CLASSES)
def test_pre_mortem_doc_has_class_heading(pmc_class: str) -> None:
    """Each Pre-Mortem class (A..D) cited in the Tag-54 doc MUST resolve
    to a ``### Class-X`` heading in the canonical coverage doc."""
    text = PRE_MORTEM_DOC.read_text(encoding="utf-8")
    pat = re.compile(rf"^###\s+{re.escape(pmc_class)}\b", re.MULTILINE)
    assert pat.search(text), (
        f"pre-mortem doc does not have an '### {pmc_class}' heading — "
        f"Surface-4 class-axis {pmc_class} unanchored."
    )


@pytest.mark.parametrize("state", PRE_MORTEM_STATES)
def test_pre_mortem_doc_uses_state_taxonomy(state: str) -> None:
    """Each of the four Pre-Mortem coverage states must be cited in the
    canonical coverage doc (it is the source-of-truth for the
    classification)."""
    text = PRE_MORTEM_DOC.read_text(encoding="utf-8")
    assert state in text, (
        f"pre-mortem doc does not cite state {state!r} — Tag-54 Surface-4 "
        f"taxonomy cell is unanchored in the canonical source-of-truth."
    )


# ===========================================================================
# §6 — Surface-5 SLI-MARATHON-N heading verification.
# ===========================================================================


def test_sli_doc_exists_on_tree() -> None:
    """The Noa Tag-52 SLI/SLO doc MUST exist."""
    assert SLI_DOC.exists(), (
        f"SLI/SLO doc {SLI_DOC!r} missing — Surface-5 anchor broken."
    )


@pytest.mark.parametrize("sli_id", SLI_IDS)
def test_sli_doc_has_sli_section(sli_id: str) -> None:
    """Each SLI-MARATHON-N (1..7) cited in the Tag-54 doc MUST resolve
    to a heading in the canonical Noa Tag-52 SLI/SLO doc. The doc
    uses ``### 2.N <name> (`SLI-MARATHON-N`)`` headings; we look for
    the literal SLI-MARATHON-N inside any ### 2 heading line."""
    text = SLI_DOC.read_text(encoding="utf-8")
    # Match any ### line that mentions the SLI-id.
    pat = re.compile(rf"^###\s+.*{re.escape(sli_id)}.*$", re.MULTILINE)
    assert pat.search(text), (
        f"SLI doc does not have a heading for {sli_id} — Surface-5 SLO "
        f"catalogue entry unanchored."
    )


# ===========================================================================
# §7 — Surface-Pre S-substrate sanity-workflow verification.
# ===========================================================================


def test_sanity_workflow_exists_on_tree() -> None:
    """The Tomas Tag-53 pre-cutover-final-sanity-gate workflow MUST exist."""
    assert SANITY_WORKFLOW.exists(), (
        f"sanity-gate workflow {SANITY_WORKFLOW!r} missing — Surface-Pre "
        f"anchor broken."
    )


@pytest.mark.parametrize("s_id", S_IDS)
def test_sanity_workflow_carries_s_substrate(s_id: str) -> None:
    """Each S-N (1..7) cited in the Tag-54 doc MUST resolve to a
    ``needs.s<N>-*`` reference in the sanity-gate workflow (the Tomas
    Tag-53 substrate-output convention)."""
    text = SANITY_WORKFLOW.read_text(encoding="utf-8")
    # `needs.s1-engine-manifest.outputs.s1_status` style (lowercase
    # `s<n>-...`). We look for `needs.s<n>-` to anchor.
    n = s_id[1:]  # "S1" -> "1"
    pat = re.compile(rf"needs\.s{re.escape(n)}-", re.MULTILINE)
    assert pat.search(text), (
        f"sanity-gate workflow does not reference 'needs.s{n}-...' — "
        f"Surface-Pre substrate {s_id} is unanchored in the canonical "
        f"Tomas Tag-53 workflow."
    )


# ===========================================================================
# §8 — Cadence (ADR-0066 KW-24..KW-27 dates) verification.
# ===========================================================================


@pytest.mark.parametrize(
    "cadence",
    CADENCE_KW,
    ids=[kw.kw_id for kw in CADENCE_KW],
)
def test_doc_cites_cadence_dates(cadence: CadenceKW) -> None:
    """For each KW cadence-slot, the doc MUST cite both the cutover-
    Mittwoch date and the sign-off-Freitag date in their canonical
    ISO-date form."""
    text = _read_doc()
    assert cadence.cutover_mittwoch_iso in text, (
        f"{cadence.kw_id} cutover-Mittwoch date "
        f"{cadence.cutover_mittwoch_iso!r} missing from doc — ADR-0066 "
        f"cadence anchor broken."
    )
    assert cadence.sign_off_freitag_iso in text, (
        f"{cadence.kw_id} sign-off-Freitag date "
        f"{cadence.sign_off_freitag_iso!r} missing from doc — ADR-0066 "
        f"cadence anchor broken."
    )


def test_doc_cadence_is_chronological() -> None:
    """The four KW cadence-slots MUST appear in chronological order in
    the doc (KW-24 before KW-25 before KW-26 before KW-27). A doc
    that lists KW-27 before KW-24 violates the marathon-sequence
    narrative."""
    text = _read_doc()
    positions = []
    for cadence in CADENCE_KW:
        # Use the cutover-Mittwoch date (which is unique per row in the
        # §9 cadence table) as the per-row position-marker.
        idx = text.find(cadence.cutover_mittwoch_iso)
        assert idx >= 0, (
            f"{cadence.kw_id} cutover-Mittwoch date not found for "
            f"chronological-order check."
        )
        positions.append((cadence.kw_id, idx))
    sorted_by_position = sorted(positions, key=lambda p: p[1])
    expected_order = [p[0] for p in positions]  # KW-24..KW-27 as declared
    actual_order = [p[0] for p in sorted_by_position]
    assert actual_order == expected_order, (
        f"cadence chronological order broken: doc lists KWs in order "
        f"{actual_order}, expected {expected_order}."
    )


# ===========================================================================
# §9 — Companion-doc H1 consistency.
# ===========================================================================


@pytest.mark.parametrize("rel_path", sorted(COMPANION_H1.keys()))
def test_companion_doc_present_and_h1_consistent(rel_path: str) -> None:
    """For each companion-doc the Tag-54 doc cites, the companion MUST
    exist AND its H1 line MUST start with the canonical prefix. A
    renamed companion-doc would silently break the consolidated doc's
    cross-references; this audit pins H1 stability."""
    p = REPO_ROOT / rel_path
    assert p.exists(), (
        f"companion doc {rel_path!r} missing — Tag-54 doc cross-reference "
        f"is dangling."
    )
    h1 = _first_markdown_h1(p.read_text(encoding="utf-8"))
    expected_prefix = COMPANION_H1[rel_path]
    assert h1.startswith(expected_prefix), (
        f"companion {rel_path!r} H1 changed: got {h1!r}, "
        f"expected prefix {expected_prefix!r} — Tag-54 doc cross-reference "
        f"may now be ambiguous."
    )


# ===========================================================================
# §10 — Final-acceptance doc self-consistency.
# ===========================================================================


def test_doc_layer_table_counts_match_canonical() -> None:
    """The Tag-54 doc §3 Pyramide-table layer-count cells (`| <N> |`)
    MUST match the canonical ``PYRAMIDE_LAYERS`` constant in this
    module. Drift here means the Tag-54 doc and this Tag-55 audit
    disagree about what the doc claims, which would mask future
    substrate-drift."""
    text = _read_doc()
    # The §3 table has lines like:
    #   | 1 | State-Machine | Tag-40 | `tests/phase_3c/test_phase_3_final_regression.py` | 28 | ... |
    for layer in PYRAMIDE_LAYERS:
        # Match the layer's row by its full rel-path in backticks +
        # a |-separated count cell carrying the doc-claim.
        pat = re.compile(
            rf"`{re.escape(layer.test_file_rel)}`\s*\|\s*"
            rf"{layer.doc_claimed_count}\s*\|",
            re.MULTILINE,
        )
        assert pat.search(text), (
            f"doc §3 Pyramide-table row for Layer-{layer.layer_id} "
            f"({layer.test_file_rel}) does not carry the expected doc-claim "
            f"count {layer.doc_claimed_count}; canonical PYRAMIDE_LAYERS "
            f"constant disagrees with on-tree doc."
        )


def test_doc_total_claimed_sum_167() -> None:
    """The doc §3 cites 'Sum (Tag-53 snapshot): 167'. Tag-55 pins this
    as a stable claim until the Tag-54 doc is refreshed."""
    text = _read_doc()
    # Match either "Sum (Tag-53 snapshot): 167" or "Sum (Tag-53
    # snapshot):** 167" (markdown bold).
    pat = re.compile(r"Sum\s*\(Tag-53\s+snapshot\)[^\d]*167", re.MULTILINE)
    assert pat.search(text), (
        "doc does not carry the canonical 'Sum (Tag-53 snapshot): 167' "
        "anchor — Pyramide aggregate claim is missing or has drifted "
        "off its anchor."
    )
