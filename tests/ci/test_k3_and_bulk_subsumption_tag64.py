# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
# REUSE-IgnoreStart
"""Tests for the Tag-64 OPEN-K3 Carry-Forward + Bulk-Activation Subsumption Check-#8 Coordination.

Anchors
-------

* OPEN-K3 carry-forward doc (new in Tag-64):
  ``docs/operations/open-k3-v907-baseline-metadata-carry-forward.md``.
* Bulk-Activation Subsumption Coordination doc (new in Tag-64):
  ``docs/operations/bulk-activation-subsumption-check-8-coordination.md``.
* V-907 baseline substrate (unchanged in Tag-64):
  ``wirelang/persona_engine/v907-hash-baseline.json``.
* Drift-allowlist (unchanged in Tag-64):
  ``tooling/ci/engine-version-drift-allowlist.json``.
* Predecessor audit:
  ``reports/audit/persona-engine-0-5-3-production-readiness-2026-05-19.md``
  §3.5 + §Open-Item-Tracker (Selin PR #405).
* Predecessor Enforce-Flip plan-doc (Tomás PR #404):
  ``docs/operations/reuse-wrap-enforce-flip-readiness-plan.md``.
* Predecessor Bulk-Activation Pre-Walk Recipe (Kai PR #396):
  ``docs/operations/bulk-activation-pre-walk-recipe.md``.
* Predecessor Walking-Skeleton Test (Kai PR #401):
  ``.github/workflows/bulk-activation-walking-skeleton-test.yml``.

What this suite pins down
-------------------------

K3 group (V-907 baseline carry-forward):
1. The K3 doc exists and has the five canonical section anchors.
2. The K3 doc records the seal-contract two-hand invariant
   (Selin-Hand + Tomas-Zone-K cross-review).
3. The V-907 baseline JSON still carries the literal
   ``"engine_version": "0.5.3-rc1"`` (the carry-forward
   substrate that the K3 doc records).
4. The drift-allowlist contains the v907-baseline-pin entry
   for the file (the K3 doc references the allowlist as the
   tooling guard surface).
5. The K3 doc lists the three triggers for a future refresh
   (substrate-change, KW-24 cutover-T0, explicit cross-review).
6. The K3 doc lists the Tag-58 PR #372 + Tag-59 PR #381
   + Tag-62 PR #399 + Tag-63 PR #405 anchor PRs.

Subsumption group (Check #8 coordination):
7. The subsumption doc exists and has the five canonical
   section anchors.
8. The subsumption doc records the 7-Pool composition as the
   union of Tag-59 §1 + Tag-61-addendum §1.
9. The subsumption doc records the "separate single-context
   PUT, after Stability-Window-Confirmed" default posture.
10. The subsumption doc records the ownership matrix entries
    for Tomás and Kai with no veto on each other's domain.
11. The subsumption doc lists the seven-step activation order.
12. The subsumption doc records the three reasons not to fold
    Check #8 into the initial bulk-walk.
13. The subsumption doc records the Option-B fixture-refresh
    recipe as a future operator-hand action, not as a Tag-64
    PR action.
14. The subsumption doc cross-anchors PR #389 + #392 + #394
    + #396 + #401 + #404.

Cross-cutting:
15. Both docs declare a sandbox-boundary section and do not
    mutate any of the six listed substrate surfaces.
16. The K3 doc and subsumption doc together resolve both open
    Tag-63 lieferbericht items (Selin-Audit §D5 OPEN-K3 +
    Tomás-Tag-63 §3 subsumption open-question).

Hermetic
--------

All tests parse files from the repository and assert structural
invariants. No network. No subprocess. No mutation of any
substrate file. The tests are safe to run in any sandbox or
runner.

# REUSE-IgnoreEnd
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
K3_DOC = REPO_ROOT / "docs" / "operations" / "open-k3-v907-baseline-metadata-carry-forward.md"
SUB_DOC = REPO_ROOT / "docs" / "operations" / "bulk-activation-subsumption-check-8-coordination.md"
V907_BASELINE = REPO_ROOT / "wirelang" / "persona_engine" / "v907-hash-baseline.json"
DRIFT_ALLOWLIST = REPO_ROOT / "tooling" / "ci" / "engine-version-drift-allowlist.json"
SELIN_AUDIT = (
    REPO_ROOT
    / "reports"
    / "audit"
    / "persona-engine-0-5-3-production-readiness-2026-05-19.md"
)
ENFORCE_FLIP_PLAN = (
    REPO_ROOT / "docs" / "operations" / "reuse-wrap-enforce-flip-readiness-plan.md"
)
BULK_PRE_WALK = (
    REPO_ROOT / "docs" / "operations" / "bulk-activation-pre-walk-recipe.md"
)


# ---------- helpers ----------


def _read(p: Path) -> str:
    assert p.exists(), f"required file missing: {p}"
    return p.read_text(encoding="utf-8")


# ---------- K3 group ----------


def test_01_k3_doc_exists_with_five_section_anchors():
    """K3 doc exists and has §1-§5 + §1.1/1.2/1.3/2.1/2.2/2.3/3.1/3.2/3.3/5.1/5.2/5.3/5.4/5.5."""
    text = _read(K3_DOC)
    expected = [
        "## §1 - Subject and posture",
        "### §1.1 - Substrate",
        "### §1.2 - Posture",
        "### §1.3 - Verdict",
        "## §2 - Why not cleanup",
        "### §2.1 - Reason 1",
        "### §2.2 - Reason 2",
        "### §2.3 - Reason 3",
        "## §3 - Refresh trigger conditions",
        "### §3.1 - Trigger A",
        "### §3.2 - Trigger B",
        "### §3.3 - Trigger C",
        "## §4 - Tooling guard",
        "## §5 - Cross-Anchors",
        "### §5.1 - Tag-58",
        "### §5.2 - Tag-59",
        "### §5.3 - Tag-62",
        "### §5.4 - Tag-63",
        "### §5.5 - Zone-K",
    ]
    for anchor in expected:
        assert anchor in text, f"K3 doc missing anchor: {anchor}"


def test_02_k3_doc_records_two_hand_invariant():
    """K3 doc names the Selin-Hand + Tomas-Zone-K invariant."""
    text = _read(K3_DOC)
    # The doc must explicitly state the seal contract.
    assert "Selin-Hand" in text
    assert "Tomás-Zone-K" in text or "Tomas-Zone-K" in text
    assert "seal contract" in text
    # And it must explicitly call this the "two-hand invariant"
    # (the phrase pinned by §2.1).
    assert "two-hand invariant" in text or "two-hand-on-the-baseline" in text


def test_03_v907_baseline_carries_rc1_literal():
    """The substrate the K3 doc records: baseline JSON still carries 0.5.3-rc1."""
    payload = json.loads(_read(V907_BASELINE))
    assert payload["engine_version"] == "0.5.3-rc1", (
        "Tag-64 K3 carry-forward record assumes baseline still on 0.5.3-rc1"
    )
    assert "Selin-Hand" in payload["note"]
    assert "Tomas Zone-K cross-review" in payload["note"]


def test_04_drift_allowlist_has_v907_baseline_pin_entry():
    """Drift-allowlist has the v907-baseline-pin entry the K3 doc references."""
    payload = json.loads(_read(DRIFT_ALLOWLIST))
    entries = payload["entries"]
    matches = [
        e
        for e in entries
        if e["path"] == "wirelang/persona_engine/v907-hash-baseline.json"
        and "v907-baseline-pin" in e.get("categories", [])
    ]
    assert matches, (
        "v907-baseline-pin allowlist entry must exist; K3 doc §4 references it"
    )


def test_05_k3_doc_lists_three_refresh_triggers():
    """K3 doc §3 lists Trigger A (substrate-change), B (KW-24 cutover), C (explicit cross-review)."""
    text = _read(K3_DOC)
    assert "Trigger A: substrate change" in text
    assert "Trigger B: KW-24 cutover" in text
    assert "Trigger C: explicit cross-review" in text
    # And §3.1 must declare the dual-hand approval requirement.
    assert "two-hand invariant" in text
    # And §3.2 must call the cutover-day refresh "optional".
    assert "cutover-day refresh is optional" in text


def test_06_k3_doc_anchors_predecessor_prs():
    """K3 doc §5 cross-anchors Tag-58 #372, Tag-59 #381, Tag-62 #399, Tag-63 #405."""
    text = _read(K3_DOC)
    for pr in ("#372", "#381", "#399", "#405"):
        assert pr in text, f"K3 doc must cross-anchor PR {pr}"
    # The K3 doc also references its own seal contract dimension
    # in the Selin audit (§3.5 of the audit report).
    assert "§3.5" in text


# ---------- Subsumption group ----------


def test_07_subsumption_doc_exists_with_five_section_anchors():
    """Subsumption doc has the five mandated sections."""
    text = _read(SUB_DOC)
    expected = [
        "## §1 - Scope",
        "## §2 - Coordination Protocol",
        "## §3 - Activation Order Update",
        "## §4 - Pool-Sync Pattern",
        "## §5 - Sandbox Boundary",
    ]
    for anchor in expected:
        assert anchor in text, f"Subsumption doc missing top-level section: {anchor}"


def test_08_subsumption_doc_records_7_pool_composition():
    """§1.3 lists 7 display-names spanning Tag-59 §1 + Tag-61-addendum §1."""
    text = _read(SUB_DOC)
    # Tag-59 §1 #1-#5
    for dn in (
        "wakir-runtime tests",
        "wakir-runtime spec-format",
        "wakir-runtime brand-pin-guard",
        "wakir-runtime adr-pin-guard",
        "wakir-runtime adr-cross-link-guard",
    ):
        assert dn in text, f"Subsumption doc §1.3 missing Tag-59 §1 display-name: {dn}"
    # Tag-61 §1 #6-#7
    for dn in (
        "wakir-runtime audit-log-corruption-replay",
        "wakir-runtime nats-jetstream-schema",
    ):
        assert dn in text, (
            f"Subsumption doc §1.3 missing Tag-61-addendum §1 display-name: {dn}"
        )


def test_09_subsumption_doc_records_default_posture():
    """§1.2 + §3.1 record the default 'separate single-context PUT after Stability-Window-Confirmed'."""
    text = _read(SUB_DOC)
    # Default verdict from §1.2
    assert (
        "separate single-context PUT" in text
        or "single-context PUT, after Stability-Window-Confirmed" in text
    )
    # §3.1 step ordering
    assert "STABILITY-WINDOW-CONFIRMED" in text
    assert "PLAN-CONSISTENT" in text
    assert "WALKING-SKELETON-INTACT" in text


def test_10_subsumption_doc_records_ownership_matrix():
    """§2.1 names Tomás and Kai with no cross-domain veto."""
    text = _read(SUB_DOC)
    assert "Ownership matrix" in text
    # Tomás owns REUSE-Wrap pre-merge lint workflow
    assert "reuse-wrap-pre-merge-lint.yml" in text
    # Kai owns bulk-activate scripts
    assert "_bulk_activate_required_checks.py" in text
    # Walking-skeleton fixtures Kai-hand
    assert "branch-protection-walking-skeleton" in text
    # The doc must mention Mira-mediation as the conflict path
    assert "Mira" in text


def test_11_subsumption_doc_lists_seven_step_activation_order():
    """§3.1 has the 7-step ordering."""
    text = _read(SUB_DOC)
    for step in (
        "Step 1:",
        "Step 2:",
        "Step 3:",
        "Step 4:",
        "Step 5:",
        "Step 6:",
        "Step 7:",
    ):
        assert step in text, f"Subsumption doc §3.1 missing {step}"
    # Step 5 must offer Option-A + Option-B
    assert "Option-A" in text and "Option-B" in text


def test_12_subsumption_doc_records_three_reasons_not_to_fold():
    """§3.2 lists three reasons not to fold Check #8 into the initial bulk-walk."""
    text = _read(SUB_DOC)
    # §3.2 has (i) (ii) (iii)
    for tag in ("(i)", "(ii)", "(iii)"):
        assert tag in text, f"Subsumption doc §3.2 missing reason {tag}"
    # And it must explicitly mention "full-replace PUT, not an append"
    # as one of the structural reasons.
    assert "full-replace" in text
    # And it must mention Tomás's §7.2 preconditions.
    assert "§7.2" in text


def test_13_subsumption_doc_records_option_b_fixture_refresh():
    """§3.4 details the Option-B fixture refresh as future operator-hand."""
    text = _read(SUB_DOC)
    assert "§3.4" in text
    assert "expected-post-snapshot.json" in text
    # The fixture refresh must be marked as future, not as a Tag-64 action.
    assert "future operator-hand" in text or "future operator-hand PR" in text


def test_14_subsumption_doc_cross_anchors_six_prs():
    """Subsumption doc cross-anchors PR #389 + #392 + #394 + #396 + #401 + #404."""
    text = _read(SUB_DOC)
    for pr in ("#389", "#392", "#394", "#396", "#401", "#404"):
        assert pr in text, f"Subsumption doc must cross-anchor PR {pr}"


# ---------- Cross-cutting ----------


def test_15_both_docs_declare_sandbox_boundary():
    """Both Tag-64 docs explicitly declare a sandbox boundary section."""
    k3 = _read(K3_DOC)
    sub = _read(SUB_DOC)
    for text, name in ((k3, "K3"), (sub, "Subsumption")):
        # Each doc has a §-titled Sandbox Boundary section.
        assert (
            "Sandbox boundary" in text or "Sandbox Boundary" in text
        ), f"{name} doc missing Sandbox boundary section"
        # And each doc references the Mira rule.
        assert "feedback_sandbox_host_trennung" in text or "Mira-Sandbox" in text, (
            f"{name} doc missing Mira-Sandbox cross-ref"
        )


def test_16_both_docs_resolve_two_open_tag63_items():
    """Both docs together resolve Selin-Audit §D5 (OPEN-K3) + Tomás-Tag-63 §3 (subsumption)."""
    # Cross-check that the predecessor surfaces actually mark these
    # as open in the first place (sanity: we're not closing
    # phantom items).
    selin = _read(SELIN_AUDIT)
    assert "OPEN-K3" in selin
    assert "intentional-by-design" in selin

    plan = _read(ENFORCE_FLIP_PLAN)
    # Tag-63 §10.A is the open question that this Tag-64 PR closes.
    assert "§10" in plan
    # And the Tag-63 plan must reference Kai #396 + the §7.3 flip command
    # — the substrates the subsumption doc coordinates between.
    assert "#396" in plan
    assert "§7.3" in plan

    # And the Kai #396 pre-walk doc must reference the 7-Pool target.
    bulk = _read(BULK_PRE_WALK)
    assert "7-Pool" in bulk or "7 contexts" in bulk

    # Both Tag-64 docs together close these:
    k3 = _read(K3_DOC)
    sub = _read(SUB_DOC)
    # K3 doc closes OPEN-K3 by recording the carry-forward.
    assert "OPEN-K3" in k3
    assert "carry-forward" in k3.lower()
    # Subsumption doc closes the §10.A open-question by recording
    # the default Option-A posture + the conditional Option-B path.
    assert "subsumption" in sub.lower()
    assert "Option-A" in sub and "Option-B" in sub


# ---------- Extra structural pins ----------


def test_17_k3_doc_yaml_frontmatter_valid():
    """K3 doc has a quoted, multi-word frontmatter (Mira YAML-frontmatter discipline)."""
    text = _read(K3_DOC)
    assert text.startswith("---\n"), "K3 doc must start with YAML frontmatter"
    # Multi-word values must be quoted (Memory feedback_yaml_frontmatter_disziplin).
    fm_end = text.find("\n---\n", 4)
    assert fm_end > 0
    fm = text[4:fm_end]
    # The owner field must be quoted single-token.
    assert re.search(r'^owner:\s*"tomas"\s*$', fm, re.MULTILINE)
    # title field multi-word must be quoted.
    assert re.search(r'^title:\s*"[^"]+"\s*$', fm, re.MULTILINE)
    # And no markdown links in frontmatter.
    assert "](" not in fm, "K3 frontmatter must not contain markdown links"


def test_18_subsumption_doc_yaml_frontmatter_valid():
    """Subsumption doc frontmatter follows the same discipline."""
    text = _read(SUB_DOC)
    assert text.startswith("---\n")
    fm_end = text.find("\n---\n", 4)
    assert fm_end > 0
    fm = text[4:fm_end]
    assert re.search(r'^owner:\s*"tomas\+kai"\s*$', fm, re.MULTILINE)
    assert re.search(r'^title:\s*"[^"]+"\s*$', fm, re.MULTILINE)
    assert "](" not in fm, "Subsumption frontmatter must not contain markdown links"
    # related_zones must list both Zone-K (Tomás) and Zone-J/CI (Kai).
    assert "Zone-K" in fm and ("Zone-J" in fm or "CI" in fm)


def test_19_k3_doc_explicitly_cites_release_notes_anchor():
    """K3 doc §2.3 cites the release-notes §1 line 3-4 + the v907-hash-baseline note + the audit §3.5."""
    text = _read(K3_DOC)
    assert "v907-hash-baseline.json:10" in text
    assert "0-5-3-final-release-notes.md" in text
    assert "§3.5" in text


def test_20_subsumption_doc_records_pool_sync_invariant():
    """§4.1 + §4.2 + §4.3 record the layered append-only pattern."""
    text = _read(SUB_DOC)
    assert "pool-sync invariant" in text
    assert "append-only" in text
    assert "Walking-Skeleton" in text  # the enforcement workflow
    # The layered pattern's three layers must be named.
    assert "Layer 1" in text and "Layer 2" in text and "Layer 3" in text


def test_21_no_substrate_mutations_in_tag_64_pr():
    """Tag-64 must not touch the substrate files (read-only assertion)."""
    # The substrate files exist and we can read them; the test
    # serves as a *self-witness* that this Tag-64 PR did not alter
    # the byte-content of the substrate.
    # The substantive assertion is at the PR-diff level
    # (operator visual inspection), but we pin the structural
    # invariants here: the V-907 baseline still has the rc1
    # literal AND the drift-allowlist still has the entry AND
    # the Tag-61 REUSE-Wrap workflow still exists AND the
    # Tag-63 walking-skeleton workflow still exists AND the
    # Tag-62 bulk-activation script still exists.
    payload = json.loads(_read(V907_BASELINE))
    assert payload["engine_version"] == "0.5.3-rc1"
    allow = json.loads(_read(DRIFT_ALLOWLIST))
    assert any(
        e["path"] == "wirelang/persona_engine/v907-hash-baseline.json"
        for e in allow["entries"]
    )
    # Tag-61 REUSE-Wrap workflow.
    wf = REPO_ROOT / ".github" / "workflows" / "reuse-wrap-pre-merge-lint.yml"
    assert wf.exists(), "Tag-61 REUSE-Wrap workflow must still exist"
    # Tag-63 walking-skeleton workflow.
    ws = (
        REPO_ROOT
        / ".github"
        / "workflows"
        / "bulk-activation-walking-skeleton-test.yml"
    )
    assert ws.exists(), "Tag-63 walking-skeleton workflow must still exist"
    # Tag-62 bulk-activation script.
    script = REPO_ROOT / "tooling" / "ops" / "_bulk_activate_required_checks.py"
    assert script.exists(), "Tag-62 bulk-activation planner must still exist"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
