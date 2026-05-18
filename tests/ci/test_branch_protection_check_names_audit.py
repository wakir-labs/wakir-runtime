# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic test for the Tag-35 branch-protection check-names audit.

The audit
``docs/audit/branch-protection-check-names-audit-2026-05-18.md``
documented (Section 2.3) that all 3 currently-required-status-check
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
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")


# Per audit §2.2, captured from
# ``gh api repos/wakir-labs/wakir-runtime/branches/main/protection``
# at 2026-05-18 09:15 CEST.
REQUIRED_NAMES_RUNTIME: tuple[str, ...] = (
    "License-Hygiene Gate (ADR-0061)",
    "wirelang suite with rfc8785 + jsonschema",
    "cross-repo drift (wakir-runtime ↔ wakir-protocol)",
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
    """The ``REQUIRED_NAMES_RUNTIME`` constant has exactly the
    same cardinality as Section 2.2 of the audit doc.

    A change in cardinality (Phase-A AR-touch expansion) MUST be
    reflected here and in the audit doc in the same PR. This test
    pins that disciplinary coupling.
    """
    assert len(REQUIRED_NAMES_RUNTIME) == 3, (
        "REQUIRED_NAMES_RUNTIME cardinality drifted from the audit doc "
        "Section 2.2 (which lists 3 required-status-check names as of "
        "2026-05-18). If you are expanding the required set per audit "
        "Phase-A, update both the audit doc Section 2.2 AND this "
        "constant in the same PR, and bump this assertion."
    )
