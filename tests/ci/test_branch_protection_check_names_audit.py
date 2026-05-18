# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic test for the Tag-35 branch-protection check-names audit.

The audit
``docs/audit/branch-protection-check-names-audit-2026-05-18.md``
documented (Section 2.3) that all currently-required-status-check
names in ``wakir-runtime`` match the actual job-display-names found
in ``.github/workflows/*.yml``. This test pins that match so a
future workflow edit that renames one of the protected job
display-names regresses HERE (hermetic) before it surfaces as a
forever-pending PR (which is exactly the PR #102 / PR #71 incident
class the audit was written against).

Sandbox boundary: parses YAML files on disk only. No GitHub API
calls, no branch-protection state queries — the required-name set
is encoded as a constant below and must be kept in sync with the
audit doc by hand. A separate AR-touch follow-up (Phase A in the
audit) will expand the required set; when that lands, this test's
``REQUIRED_NAMES`` constant must be updated in the same PR.

ADR-0068 Migration-Step-3 (Tag-39)
----------------------------------

ADR-0068 (approved 2026-05-18) replaces the multi-name required-set
with a single ``ci-aggregator`` Required-Status-Check. The cutover
script ``scripts/ci/adr-0068-migration-step-3-cutover.py`` performs
the actual branch-protection PATCH. Until that script has run
against ``main`` (operator-confirmed), this test continues to pin
the pre-cutover three-name set. After the cutover, the
``BRANCH_PROTECTION_MIGRATED`` flag below flips to ``True`` and
the test pins the single-name post-cutover set instead.

The flag flip is the canonical Mira-Hand-touch that confirms the
migration is live: the cutover script writes the PATCH, the operator
flips this flag in a follow-up PR, and from then on any drift in
either direction (e.g. someone re-adding a legacy name without
re-flipping the flag) is caught by this audit-test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")


#: Set to ``True`` only after
#: ``scripts/ci/adr-0068-migration-step-3-cutover.py --apply`` has
#: run successfully against ``wakir-labs/wakir-runtime/main`` and the
#: branch-protection ``required_status_checks.contexts`` list is
#: ``["ci-aggregator"]``. The flip itself is the operator-touch that
#: marks the migration as Done.
BRANCH_PROTECTION_MIGRATED: bool = False


#: Pre-cutover state. Per audit §2.2, originally captured at
#: 2026-05-18 09:15 CEST as a 3-name set. The audit-Phase-A
#: AR-touch expansion (Mira-Hand API-call 2026-05-18 morning
#: ahead of Tag-41) widened the protected set to six names —
#: the three original gates plus three Phase-2 / Welle-3 gates
#: that had reached production-quality but were not yet pinned.
#: Re-captured from
#: ``gh api repos/wakir-labs/wakir-runtime/branches/main/protection``
#: at 2026-05-18 19:48 CEST (Reza Tag-41 probe-dry-run).
#:
#: Order matches the live ``required_status_checks.contexts``
#: array on ``main`` and is preserved for round-trip backup /
#: rollback symmetry by the ADR-0068 Migration-Step-3 cutover
#: script.
REQUIRED_NAMES_RUNTIME_PRE_MIGRATION: tuple[str, ...] = (
    "License-Hygiene Gate (ADR-0061)",
    "wirelang suite with rfc8785 + jsonschema",
    "cross-repo drift (wakir-runtime ↔ wakir-protocol)",
    "production-vs-sandbox drift envelope",
    "wirelang suite without rfc8785 / jsonschema (shadow)",
    "Phase-2 Aggregator (All Gates + Cross-Gate Non-Interference)",
)


#: Post-cutover state per ADR-0068 Migration-Step-3.
REQUIRED_NAMES_RUNTIME_POST_MIGRATION: tuple[str, ...] = (
    "ci-aggregator",
)


REQUIRED_NAMES_RUNTIME: tuple[str, ...] = (
    REQUIRED_NAMES_RUNTIME_POST_MIGRATION
    if BRANCH_PROTECTION_MIGRATED
    else REQUIRED_NAMES_RUNTIME_PRE_MIGRATION
)


def _workflows_dir() -> Path:
    here = Path(__file__).resolve()
    repo_root = here.parents[2]
    return repo_root / ".github" / "workflows"


def _collect_job_display_names() -> set[str]:
    """Return the set of ``jobs.<id>.name`` strings across every
    workflow file in ``.github/workflows``.

    Matrix expansions (``${{ matrix.x }}``) are returned as the
    literal template string — sufficient for the current audit set
    because the 3 protected names are all matrix-free.
    """
    names: set[str] = set()
    for wf in _workflows_dir().glob("*.yml"):
        data = yaml.safe_load(wf.read_text())
        jobs = (data or {}).get("jobs") or {}
        for job_id, job_def in jobs.items():
            if not isinstance(job_def, dict):
                continue
            name = job_def.get("name")
            if isinstance(name, str):
                names.add(name)
    return names


@pytest.mark.parametrize("required_name", REQUIRED_NAMES_RUNTIME)
def test_required_status_check_name_matches_actual_job(required_name: str) -> None:
    """Every required-status-check name in wakir-runtime branch
    protection MUST exist as an actual ``jobs.<id>.name`` value in
    one of the workflow YAML files.

    Failure mode this catches: someone renames a protected job
    (e.g. ``License-Hygiene Gate (ADR-0061)`` -> ``License Gate``)
    in a workflow PR without touching branch-protection settings.
    The next PR after the merge would forever-pend on the renamed
    name. This test fails the workflow PR itself, before merge.
    """
    actual = _collect_job_display_names()
    assert required_name in actual, (
        f"Required-status-check name {required_name!r} is not present in "
        f"any .github/workflows/*.yml jobs.*.name field. Either the "
        f"workflow was renamed without updating branch protection, or the "
        f"REQUIRED_NAMES_RUNTIME constant in this test is stale relative "
        f"to the audit doc. Cross-grep with: "
        f"gh api repos/wakir-labs/wakir-runtime/branches/main/protection "
        f"--jq '.required_status_checks.contexts'"
    )


def test_required_names_constant_matches_audit_doc_count() -> None:
    """The ``REQUIRED_NAMES_RUNTIME`` constant has the expected
    cardinality for the current migration phase.

    Pre-migration (``BRANCH_PROTECTION_MIGRATED == False``):
    cardinality is 6, matching the audit doc Section 2.2 plus the
    Phase-A AR-touch expansion (Mira-Hand API-call 2026-05-18
    morning) that widened the protected set from the original
    three names to the six current names.

    Post-migration (``BRANCH_PROTECTION_MIGRATED == True``):
    cardinality is 1, matching ADR-0068 Migration-Step-3
    (``["ci-aggregator"]``).

    A change in cardinality (further Phase-A AR-touch expansion in
    the pre-migration window, or any drift in the post-migration
    window) MUST be reflected here and in the audit doc in the same
    PR. This test pins that disciplinary coupling.
    """
    expected = 1 if BRANCH_PROTECTION_MIGRATED else 6
    assert len(REQUIRED_NAMES_RUNTIME) == expected, (
        f"REQUIRED_NAMES_RUNTIME cardinality is "
        f"{len(REQUIRED_NAMES_RUNTIME)}, expected {expected} for "
        f"BRANCH_PROTECTION_MIGRATED={BRANCH_PROTECTION_MIGRATED}. "
        f"If you flipped BRANCH_PROTECTION_MIGRATED, also adjust the "
        f"pre/post-migration tuple definitions; if you expanded the "
        f"audit-Phase-A required set, update both this constant and "
        f"the audit doc Section 2.2 in the same PR."
    )


def test_migration_flag_pins_ci_aggregator_when_done() -> None:
    """When the migration is flagged Done, the required-set MUST
    contain exactly ``ci-aggregator``.

    This pins the post-cutover invariant per ADR-0068 Migration-
    Step-3: after the cutover script has run, the live
    branch-protection state and this test's constant agree on the
    single-name ``ci-aggregator``-only set.
    """
    if not BRANCH_PROTECTION_MIGRATED:
        pytest.skip(
            "BRANCH_PROTECTION_MIGRATED=False (pre-cutover); "
            "post-migration invariant is not yet active."
        )
    assert REQUIRED_NAMES_RUNTIME == ("ci-aggregator",), (
        "BRANCH_PROTECTION_MIGRATED is True, so REQUIRED_NAMES_RUNTIME "
        "must be exactly ('ci-aggregator',). If you need to add a "
        "second post-migration required name, that is a new ADR, not "
        "a constant edit."
    )
