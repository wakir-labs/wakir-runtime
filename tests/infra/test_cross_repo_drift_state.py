# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the Cross-Repo-Drift Runbook (Day-31 living-doc).

Follow-up to PR #105 / PR #111 / PR #126 per ADR-0062 Cut-2/Cut-3 and
the External-Audit-Folge 2026-05-17 §3.4 demand:

    "Cross-repo drift kontrollieren — runtime ↔ protocol schema drift,
     runtime ↔ verify manifest/proof drift, test vectors shared across
     repos."

PR #105 covered the *workflow logic*. PR #111 covered the *workflow-
logic hermetic tests*. PR #126 covered the *Enforce-Flip readiness
contract*. This file (Tag-31) covers the **living-document contract**:

* The runbook ``docs/operations/cross-repo-drift-runbook.md`` exists
  and structurally matches the four-zone surface inventory
  (Zone-A schemas, Zone-B fixtures, Zone-C verify-shape, Zone-D
  prose).
* The Zone-A drift-map table in the runbook matches the workflow's
  ``pairs=( ... )`` array (no drift between *doc* and *workflow*).
* The Zone-B fixture-set inventory in the runbook matches the set
  of fixture directories that actually exist on the runtime side
  with parallel directories on the protocol side (we do not clone
  protocol here — we only verify the runbook does not claim a
  fixture set the runtime does not ship).
* The Zone-C shape-equivalence pair list in the runbook references
  files that exist on the runtime side (the verify-side files are
  documented but cannot be checked here without a clone).
* The allowlist file's audit-log discipline (every entry-set
  refresh leaves a dated audit-log line in the file header) is
  enforced.
* The runbook's trajectory log §6 is append-only — older entries
  may not be edited (we approximate this by checking the
  oldest-known-row anchor text is present unchanged).

We deliberately re-parse the runbook's markdown content here and pin
its structural shape into CI, so a change to the operator-source-of-
truth file must be coordinated with a change to these tests. Same
contract direction as PR #111 and PR #126.

What this file does NOT do:

* Clone wakir-protocol / wakir-verify. The drift *measurement* lives
  in the runbook §3 as point-in-time data; CI does not re-measure
  on every PR (re-measurement is per-welle, per §4).
* Run the actual ``cross-repo-drift-audit.yml`` workflow. PR #111
  already covers the workflow-logic invariants hermetically.
* Promote the Zone-B / Zone-C lanes to required-status-check.
  Zone-A required-status-check is gated by Enforce-Flip per
  PR #126; Zone-B / Zone-C lanes are doc-only on Tag-31 by design.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNBOOK_PATH = (
    REPO_ROOT / "docs" / "operations" / "cross-repo-drift-runbook.md"
)
ENFORCE_READINESS_PATH = (
    REPO_ROOT / "docs" / "operations" / "cross-repo-drift-enforce-flip-readiness.md"
)
MIRROR_PAIR_STATUS_PATH = (
    REPO_ROOT / "docs" / "operations" / "cross-repo-drift-mirror-pair-status.md"
)
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "cross-repo-drift-audit.yml"
ALLOWLIST_PATH = REPO_ROOT / ".cross-repo-drift-allowlist.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read(path: Path) -> str:
    assert path.is_file(), f"required file is missing: {path}"
    return path.read_text(encoding="utf-8")


_PAIR_RE = re.compile(
    r'"(?P<rt>[^"]+)\|(?P<pt>[^"]+)"'
)


def _workflow_pairs() -> list[tuple[str, str]]:
    """Extract the literal pairs=( ... ) array from the workflow YAML.

    Mirrors the helper used by PR #111. Re-implemented here so the
    runbook-vs-workflow consistency test does not transitively depend
    on PR #111's private helpers.
    """
    src = _read(WORKFLOW_PATH)
    # The array spans multiple lines; find its open/close and extract
    # quoted "runtime|protocol" entries between them.
    open_idx = src.find("pairs=(")
    assert open_idx != -1, "workflow has no pairs=( ... ) array"
    close_idx = src.find(")", open_idx)
    assert close_idx != -1, "workflow pairs=( ... ) array is unclosed"
    block = src[open_idx:close_idx]
    pairs = [(m.group("rt"), m.group("pt")) for m in _PAIR_RE.finditer(block)]
    assert len(pairs) >= 5, "workflow must declare at least 5 mirror-pairs"
    return pairs


def _runbook_zone_a_runtime_paths() -> list[str]:
    """Return the runtime-path column values from the runbook §3.1 table.

    The runbook §3.1 table has the literal column header
    ``| Runtime path | Protocol path |`` followed by ten data rows
    with backticked paths.
    """
    src = _read(RUNBOOK_PATH)
    # Find the §3.1 table by anchoring on its heading.
    anchor = "### 3.1 Zone-A drift-map"
    start = src.find(anchor)
    assert start != -1, "runbook has no §3.1 Zone-A drift-map heading"
    end = src.find("\n### ", start + len(anchor))
    if end == -1:
        end = len(src)
    section = src[start:end]
    # Match the runtime-path column (first backticked cell after the row's #).
    row_re = re.compile(
        r"^\|\s*\d+\s*\|\s*`([^`]+)`\s*\|",
        re.MULTILINE,
    )
    return [m.group(1) for m in row_re.finditer(section)]


def _runbook_zone_b_fixture_sets() -> list[str]:
    """Return the fixture-set names from the runbook §3.2 table."""
    src = _read(RUNBOOK_PATH)
    anchor = "### 3.2 Zone-B drift-map"
    start = src.find(anchor)
    assert start != -1, "runbook has no §3.2 Zone-B drift-map heading"
    end = src.find("\n### ", start + len(anchor))
    if end == -1:
        end = len(src)
    section = src[start:end]
    # The fixture-set column is the first backticked cell or the first
    # text cell in each row. We match cells whose first segment is a
    # short identifier or backticked name.
    row_re = re.compile(
        r"^\|\s*(`?[A-Za-z0-9_\-/\\.]+`?[^|]*?)\s*\|",
        re.MULTILINE,
    )
    names = []
    for m in row_re.finditer(section):
        cell = m.group(1).strip().strip("`").strip()
        # Skip the header row(s).
        if cell.lower() in {"fixture set", "---"}:
            continue
        # The first cell may carry trailing prose; strip after first
        # whitespace boundary that introduces a path-prefix mention.
        # We only want the bare set name.
        name = cell.split()[0].strip("`").strip()
        if name in {"|", "", "---"}:
            continue
        names.append(name)
    return names


# ---------------------------------------------------------------------------
# TV-RBK-01..02 — runbook exists with all four zones present
# ---------------------------------------------------------------------------


class TestRunbookStructure:
    def test_tv_rbk_01_runbook_file_exists(self):
        """The runbook file must exist at the canonical path."""
        assert RUNBOOK_PATH.is_file(), (
            f"runbook is missing — expected at {RUNBOOK_PATH.relative_to(REPO_ROOT)}"
        )

    def test_tv_rbk_02_runbook_declares_four_zones(self):
        """The runbook must declare all four contract zones (A/B/C/D).

        Each zone is the operator-facing surface for a distinct drift
        edge per the external-audit §3.4 demand (schemas, fixtures,
        verify, prose). Dropping a zone silently re-narrows the audit
        surface — which is exactly the regression we want CI to catch.
        """
        src = _read(RUNBOOK_PATH)
        for zone_anchor in (
            "### 2.1 Zone-A",
            "### 2.2 Zone-B",
            "### 2.3 Zone-C",
            "### 2.4 Zone-D",
        ):
            assert zone_anchor in src, (
                f"runbook missing zone section: {zone_anchor!r}"
            )


# ---------------------------------------------------------------------------
# TV-RBK-03 — Zone-A drift-map inventory matches the workflow's pairs=()
# ---------------------------------------------------------------------------


class TestZoneAInventoryConsistency:
    def test_tv_rbk_03_runbook_zone_a_rows_match_workflow_pairs(self):
        """The runbook's §3.1 ten data rows must match the workflow array.

        This is the *anti-drift-of-the-drift-doc* contract: a future
        contributor who extends the workflow's pairs=( ... ) array
        without updating the runbook §3.1 table must trip this test.
        Same direction the runbook says it expects in §2.1.
        """
        workflow_pairs = _workflow_pairs()
        runbook_runtime_paths = _runbook_zone_a_runtime_paths()

        # Same length: every workflow pair must have a runbook row.
        assert len(runbook_runtime_paths) == len(workflow_pairs), (
            f"runbook §3.1 row count ({len(runbook_runtime_paths)}) does not "
            f"match workflow pair count ({len(workflow_pairs)})"
        )

        # Same set of runtime-side paths (order may differ; we accept
        # any reasonable ordering as long as the set matches).
        workflow_runtime_set = {rt for rt, _pt in workflow_pairs}
        runbook_set = set(runbook_runtime_paths)
        assert runbook_set == workflow_runtime_set, (
            "runbook §3.1 runtime paths diverge from workflow pairs.\n"
            f"  in runbook not workflow: {runbook_set - workflow_runtime_set}\n"
            f"  in workflow not runbook: {workflow_runtime_set - runbook_set}"
        )


# ---------------------------------------------------------------------------
# TV-RBK-04 — Zone-B fixture-set inventory matches runtime-side reality
# ---------------------------------------------------------------------------


class TestZoneBFixtureInventory:
    def test_tv_rbk_04_zone_b_fixture_sets_exist_on_runtime_side(self):
        """Each Zone-B fixture-set the runbook names must exist on the
        runtime side under one of the documented path prefixes
        (``tests/fixtures/`` or ``wirelang/tests/fixtures/``).

        This catches the "runbook claims we ship fixture X but actually
        we don't" regression silently. We deliberately do not clone
        wakir-protocol here — verifying the protocol side is the per-
        welle measurement methodology in §4.2 of the runbook.
        """
        runbook_sets = _runbook_zone_b_fixture_sets()
        assert len(runbook_sets) >= 8, (
            "runbook §3.2 must enumerate at least 8 fixture sets "
            f"(got {len(runbook_sets)}: {runbook_sets})"
        )

        runtime_prefixes = (
            REPO_ROOT / "tests" / "fixtures",
            REPO_ROOT / "wirelang" / "tests" / "fixtures",
        )
        for fixture_set in runbook_sets:
            # The fixture-set cell may include a path-fragment (e.g.
            # ``schema-registry/caveat-override-event-export-v1``).
            # Walk path-segments left-to-right against the prefixes.
            found = any(
                (prefix / fixture_set).is_dir() for prefix in runtime_prefixes
            )
            if not found:
                # Try the leading-segment fallback (the runbook may
                # name a sub-set under a parent directory).
                head = fixture_set.split("/", 1)[0]
                found = any(
                    (prefix / head).is_dir() for prefix in runtime_prefixes
                )
            assert found, (
                f"runbook §3.2 names fixture set {fixture_set!r} but no "
                f"matching directory exists on the runtime side under "
                f"any of {[str(p.relative_to(REPO_ROOT)) for p in runtime_prefixes]}"
            )


# ---------------------------------------------------------------------------
# TV-RBK-05 — Zone-C shape-equivalence pair list points at real runtime files
# ---------------------------------------------------------------------------


class TestZoneCShapeEquivalence:
    def test_tv_rbk_05_zone_c_runtime_paths_exist(self):
        """Each Zone-C shape-equivalence pair in runbook §3.3 must
        reference a runtime-side file that actually exists.

        We only check the runtime side here (the verify side is in
        the wakir-verify repo and cannot be probed without a clone).
        This still catches the "runbook claims we mirror file X on
        the verify side but file X does not exist on the runtime
        side either" regression.
        """
        src = _read(RUNBOOK_PATH)
        anchor = "### 3.3 Zone-C drift-map"
        start = src.find(anchor)
        assert start != -1, "runbook has no §3.3 Zone-C drift-map heading"
        end = src.find("\n### ", start + len(anchor))
        if end == -1:
            end = len(src)
        section = src[start:end]

        # Match table rows with a numbered first column.
        row_re = re.compile(
            r"^\|\s*\d+\s*\|\s*`([^`]+)`\s*\|",
            re.MULTILINE,
        )
        runtime_paths = [m.group(1) for m in row_re.finditer(section)]
        assert len(runtime_paths) >= 3, (
            "runbook §3.3 must enumerate at least 3 shape-equivalence "
            f"pairs (got {len(runtime_paths)})"
        )
        for rt_path in runtime_paths:
            abs_path = REPO_ROOT / rt_path
            assert abs_path.is_file(), (
                f"runbook §3.3 references runtime file {rt_path!r} which "
                f"does not exist at {abs_path}"
            )


# ---------------------------------------------------------------------------
# TV-RBK-06 — Allowlist file carries the audit-log discipline header
# ---------------------------------------------------------------------------


class TestAllowlistAuditLog:
    def test_tv_rbk_06_allowlist_carries_dated_audit_log_entries(self):
        """The allowlist file must carry a dated audit-log header.

        Every Welle that touches the allowlist (add / remove / re-
        affirm) appends an entry like::

            # YYYY-MM-DD (Operator, Welle-ref): <one-liner>

        in the ``Allowlist audit log`` header section. CI here pins
        the structure into a tripwire: a future contributor who edits
        the allowlist without leaving an audit-log entry must trip
        this test.
        """
        src = _read(ALLOWLIST_PATH)
        assert "Allowlist audit log" in src, (
            "allowlist file is missing the ``Allowlist audit log`` "
            "header section — every welle that touches the file must "
            "append a dated entry under this header."
        )

        # At least two dated entries (Day-1 + Day-31 minimum, per the
        # current state). The date format is YYYY-MM-DD inside a
        # comment line.
        date_re = re.compile(r"#\s*(\d{4}-\d{2}-\d{2})\s*\(")
        dates = date_re.findall(src)
        assert len(dates) >= 2, (
            "allowlist audit log must carry at least 2 dated entries "
            f"(got {len(dates)}: {dates})"
        )

        # All dates must be parseable YYYY-MM-DD format.
        for d in dates:
            year, month, day = d.split("-")
            assert 2025 <= int(year) <= 2030, f"audit-log year out of range: {d}"
            assert 1 <= int(month) <= 12, f"audit-log month out of range: {d}"
            assert 1 <= int(day) <= 31, f"audit-log day out of range: {d}"

        # The current allowlist is still empty (allow: []). Verify
        # the empty-list discipline holds — the Enforce-Flip-Readiness
        # doc §4 Step-2 is the first scheduled refresh window that
        # may admit entries.
        assert re.search(r"^allow:\s*\[\]\s*$", src, re.MULTILINE), (
            "allowlist is no longer empty (allow: []). If this is "
            "intentional, update the test to admit the new entries "
            "and add an ADR / sprint reference to the audit-log."
        )


# ---------------------------------------------------------------------------
# TV-RBK-07 — Trajectory log §6 is append-only (Day-1 anchor is unmodified)
# ---------------------------------------------------------------------------


class TestTrajectoryLogAppendOnly:
    def test_tv_rbk_07_trajectory_day_1_anchor_preserved(self):
        """The runbook §6 trajectory log is append-only.

        We approximate this contract by anchoring on a hard-coded text
        fingerprint of the Day-1 entry. A future contributor who
        rewrites Day-1 must update this test simultaneously, which is
        the audit-trail equivalent of "you may not rewrite history
        without leaving a fingerprint".
        """
        src = _read(RUNBOOK_PATH)
        # Day-1 fingerprint: the exact tally + source reference.
        day_1_fingerprint = "Zone-A: `ok=4, drift=6, missing=0`."
        assert day_1_fingerprint in src, (
            "runbook §6 Day-1 trajectory entry has been mutated. "
            "The trajectory log is append-only — older entries are "
            "audit-trail anchors. If this change is intentional, "
            "update the test fingerprint to the new value AND record "
            "the rewrite reason in the PR description."
        )
        # And the corresponding §6 section heading.
        assert "### 6.1 Day-1" in src, (
            "runbook §6.1 Day-1 section heading is missing — the "
            "trajectory log structure was renamed without test update."
        )


# ---------------------------------------------------------------------------
# TV-RBK-08 — Cross-doc reference graph is intact
# ---------------------------------------------------------------------------


class TestCrossDocReferences:
    def test_tv_rbk_08_runbook_cross_doc_references_resolve(self):
        """The runbook §7 cross-references must point at files that
        actually exist in the repo. This catches the "we renamed a
        sister doc without updating the runbook back-link" regression.
        """
        src = _read(RUNBOOK_PATH)
        anchor = "## 7. Cross-references"
        start = src.find(anchor)
        assert start != -1, "runbook has no §7 cross-references section"
        section = src[start:]

        # Match Markdown link targets that are repo-relative paths.
        # Pattern: [text](./relative-path) or [text](path).
        link_re = re.compile(r"\]\(\./([^)\s]+)\)")
        targets = link_re.findall(section)
        # We expect at least three internal cross-references (sister
        # ops docs).
        assert len(targets) >= 3, (
            "runbook §7 must cross-reference at least 3 sister docs "
            f"(got {len(targets)}: {targets})"
        )

        for rel in targets:
            # Cross-references are relative to the doc directory.
            doc_dir = RUNBOOK_PATH.parent
            target = (doc_dir / rel).resolve()
            assert target.is_file(), (
                f"runbook §7 references {rel!r} which does not exist "
                f"at {target}"
            )

    def test_tv_rbk_09_companion_docs_back_reference_runbook(self):
        """Sister ops docs (Enforce-Flip-Readiness, Mirror-Pair-Status)
        existed before the runbook. We do NOT yet require them to
        back-reference the runbook — that is a follow-up sprint to
        avoid a circular-PR-dependency on Tag-31. The test here pins
        the *minimum* state: both sister docs are intact and the
        runbook can be navigated to them.
        """
        assert ENFORCE_READINESS_PATH.is_file(), (
            "Enforce-Flip-Readiness doc is missing — sister doc the "
            "runbook companions."
        )
        assert MIRROR_PAIR_STATUS_PATH.is_file(), (
            "Mirror-Pair-Status doc is missing — sister doc the "
            "runbook companions for Zone-D."
        )


# ---------------------------------------------------------------------------
# TV-RBK-10 — Workflow's empty-allowlist contract matches the file state
# ---------------------------------------------------------------------------


class TestWorkflowAllowlistAlignment:
    def test_tv_rbk_10_workflow_documents_empty_allowlist_posture(self):
        """The workflow file's comment block documents that the initial
        allowlist is empty by design. This must remain true on Tag-31
        because §5 of the runbook codifies the empty-list audit verdict.

        If a future contributor populates the allowlist before the
        Enforce-Flip cleanup sequence advances (Enforce-Flip-Readiness
        §4 Step-2), they must update both the workflow comment AND
        the runbook §5 simultaneously.
        """
        workflow_src = _read(WORKFLOW_PATH)
        allowlist_src = _read(ALLOWLIST_PATH)

        # The workflow declares the empty-by-design posture.
        assert "initial file is **empty**" in workflow_src, (
            "workflow comment no longer documents the empty-by-design "
            "allowlist posture — coordinate with runbook §5 update."
        )

        # The allowlist file is in fact empty.
        assert re.search(r"^allow:\s*\[\]\s*$", allowlist_src, re.MULTILINE), (
            "allowlist file is no longer empty — runbook §5 must be "
            "refreshed to reflect the new audit-log entries."
        )


# ---------------------------------------------------------------------------
# TV-RBK-11 — External-audit demand traceability
# ---------------------------------------------------------------------------


class TestExternalAuditTraceability:
    def test_tv_rbk_11_runbook_traces_to_external_audit_demand(self):
        """The runbook §1 must cite the external-audit-2026-05-17 §3.4
        demand verbatim. This is the audit-trail anchor that ties the
        runbook artefact to the auditor-facing requirement that
        spawned it. A future PR that drops the citation must trip
        this test (and the operator must add an ADR if the demand
        evolved).
        """
        src = _read(RUNBOOK_PATH)
        # The verbatim citation may appear as a Markdown blockquote
        # with hard-wrapped lines; we normalise the source by
        # collapsing whitespace and ``> `` blockquote-line-prefixes
        # before substring-matching the demand text.
        normalised = re.sub(r"\n>\s*", " ", src)
        normalised = re.sub(r"\s+", " ", normalised)
        verbatim = (
            "Cross-repo drift kontrollieren — runtime ↔ protocol "
            "schema drift, runtime ↔ verify manifest/proof drift, "
            "test vectors shared across repos."
        )
        assert verbatim in normalised, (
            "runbook §1 has dropped the verbatim external-audit-"
            "2026-05-17 §3.4 citation. This is the audit-trail "
            "anchor — restore it or add an ADR-reference if the "
            "demand has evolved."
        )


# ---------------------------------------------------------------------------
# TV-RBK-12 — Day-31 measurement section is present (today's snapshot)
# ---------------------------------------------------------------------------


class TestDay31Snapshot:
    def test_tv_rbk_12_day_31_snapshot_present_with_tally(self):
        """The runbook §6.2 Day-31 entry must record TODAY's drift tally
        for both Zone-A and Zone-B. This is the load-bearing measurement
        the external-audit demand requires; dropping it silently
        defeats the welle.
        """
        src = _read(RUNBOOK_PATH)
        assert "### 6.2 Day-31" in src, (
            "runbook §6.2 Day-31 trajectory entry is missing — the "
            "Welle that authored this runbook must record the day's "
            "measurement before merging."
        )
        # Must record both Zone-A and Zone-B tallies.
        assert re.search(
            r"Zone-A:\s*`ok=4,\s*DRIFT=6,\s*missing=0`",
            src,
        ), (
            "Day-31 Zone-A tally not in the expected form. Update "
            "the runbook to record `ok=4, DRIFT=6, missing=0` (or "
            "update this test if the actual TODAY's measurement "
            "differs and was re-measured after the runbook draft)."
        )
        assert "Zone-B:" in src, "Day-31 Zone-B tally missing in §6.2"
        # Cross-Review sign-off is recorded as pending (Tag-31 outbox).
        assert "Cross-Review-Zone-3" in src, (
            "Day-31 entry must reference Cross-Review-Zone-3 sign-off "
            "status (pending on Tag-31 by design)."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
