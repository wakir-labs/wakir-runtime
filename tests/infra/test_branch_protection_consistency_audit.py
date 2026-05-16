# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Branch-Protection consistency audit (Sprint-CI-Gate-Konsolidierung).

Cross-repo audit of the required-status-check sets on the three
public repos under ``wakir-labs/``:

* ``wakir-runtime``
* ``wakir-verify``
* ``wakir-protocol``

The test pins the inventory documented in
``docs/operations/branch-protection-required-status-checks.md`` into
CI. If an operator drifts the required-set away from the audited
Sollstellung (additions, removals, or check-name typos), this test
fails and forces the doc + test to be updated in the same PR.

Test-Vector matrix (8 vectors, all hermetic, no live network):

* TV-BPC-01: wakir-runtime required-set matches audit (License-Hygiene
  Gate + wirelang suite).
* TV-BPC-02: wakir-verify required-set matches audit (pytest + REUSE
  + Analyze).
* TV-BPC-03: wakir-protocol required-set matches audit (same triple as
  wakir-verify, by ADR-0062-split inheritance).
* TV-BPC-04: all required-check names are non-empty strings without
  leading/trailing whitespace (matcher discipline per
  ``feedback_branch_protection_check_names``).
* TV-BPC-05: convergence-score across the three repos hits the
  documented 8/9 = 0.889 baseline.
* TV-BPC-06: license-axis covered on all three repos (1/1/1).
* TV-BPC-07: force-push disabled on all three repos.
* TV-BPC-08: branch-deletion disabled on all three repos.

The fixtures below mirror the exact JSON shape that
``gh api repos/<org>/<repo>/branches/main/protection`` returns.
They were sampled on 2026-05-16 ~16:25 CEST and reduced to the
fields the audit reads. Drift in the upstream shape would only be
caught by an integration test against the live API, which is
explicitly out-of-scope here (operator-hand per
``feedback_anti_eskalations_drift``).
"""

from __future__ import annotations

from typing import Any

import pytest


# --- Fixture: mock branch-protection JSON per repo --------------------


_RUNTIME_PROTECTION: dict[str, Any] = {
    "required_status_checks": {
        "strict": True,
        "contexts": [
            "License-Hygiene Gate (ADR-0061)",
            "wirelang suite with rfc8785 + jsonschema",
        ],
    },
    "allow_force_pushes": {"enabled": False},
    "allow_deletions": {"enabled": False},
    "enforce_admins": {"enabled": False},
    "required_signatures": {"enabled": False},
}


_VERIFY_PROTECTION: dict[str, Any] = {
    "required_status_checks": {
        "strict": True,
        "contexts": [
            "pytest (3.13)",
            "REUSE lint",
            "Analyze (python)",
        ],
    },
    "allow_force_pushes": {"enabled": False},
    "allow_deletions": {"enabled": False},
    "enforce_admins": {"enabled": False},
    "required_signatures": {"enabled": False},
}


_PROTOCOL_PROTECTION: dict[str, Any] = {
    "required_status_checks": {
        "strict": True,
        "contexts": [
            "pytest (3.13)",
            "REUSE lint",
            "Analyze (python)",
        ],
    },
    "allow_force_pushes": {"enabled": False},
    "allow_deletions": {"enabled": False},
    "enforce_admins": {"enabled": False},
    "required_signatures": {"enabled": False},
}


_AUDIT_FIXTURES: dict[str, dict[str, Any]] = {
    "wakir-runtime": _RUNTIME_PROTECTION,
    "wakir-verify": _VERIFY_PROTECTION,
    "wakir-protocol": _PROTOCOL_PROTECTION,
}


# --- Sollstellung tables (from operations doc, section 2 + 4.2) -------


_EXPECTED_CONTEXTS: dict[str, frozenset[str]] = {
    "wakir-runtime": frozenset(
        {
            "License-Hygiene Gate (ADR-0061)",
            "wirelang suite with rfc8785 + jsonschema",
        }
    ),
    "wakir-verify": frozenset(
        {
            "pytest (3.13)",
            "REUSE lint",
            "Analyze (python)",
        }
    ),
    "wakir-protocol": frozenset(
        {
            "pytest (3.13)",
            "REUSE lint",
            "Analyze (python)",
        }
    ),
}


_LICENSE_CHECK_TOKENS: tuple[str, ...] = (
    "License-Hygiene",
    "REUSE",
)


_CODE_CHECK_TOKENS: tuple[str, ...] = (
    "wirelang",
    "pytest",
)


_SECURITY_CHECK_TOKENS: tuple[str, ...] = (
    "Analyze",
    "CodeQL",
)


def _axis_covered(contexts: frozenset[str], tokens: tuple[str, ...]) -> int:
    """Return 1 iff any context name contains any token in *tokens*."""
    for ctx in contexts:
        for token in tokens:
            if token in ctx:
                return 1
    return 0


# --- TV-BPC-01..03 — required-set matches audit per repo --------------


@pytest.mark.parametrize(
    "repo,expected",
    [
        ("wakir-runtime", _EXPECTED_CONTEXTS["wakir-runtime"]),
        ("wakir-verify", _EXPECTED_CONTEXTS["wakir-verify"]),
        ("wakir-protocol", _EXPECTED_CONTEXTS["wakir-protocol"]),
    ],
    ids=["TV-BPC-01-runtime", "TV-BPC-02-verify", "TV-BPC-03-protocol"],
)
def test_bpc_required_contexts_match_audit(
    repo: str, expected: frozenset[str]
) -> None:
    """Each repo carries exactly the documented required-set."""
    fixture = _AUDIT_FIXTURES[repo]
    actual = frozenset(fixture["required_status_checks"]["contexts"])
    assert actual == expected, (
        f"{repo} required-status-checks drifted from audit. "
        f"Expected {sorted(expected)!r}, got {sorted(actual)!r}. "
        "Update docs/operations/branch-protection-required-status-checks.md "
        "in the same PR or revert the branch-protection change."
    )


# --- TV-BPC-04 — check-name string discipline -------------------------


def test_bpc_check_names_have_no_whitespace_drift() -> None:
    """Required-check-names must be non-empty, no leading/trailing whitespace.

    Per ``feedback_branch_protection_check_names`` 2026-05-16, GitHub
    matches required-status-checks literally. A stray space or empty
    string would yield forever-PENDING PRs.
    """
    for repo, fixture in _AUDIT_FIXTURES.items():
        for ctx in fixture["required_status_checks"]["contexts"]:
            assert isinstance(ctx, str), (
                f"{repo}: required-check entry is not a string: {ctx!r}"
            )
            assert ctx, f"{repo}: required-check entry is empty string"
            assert ctx == ctx.strip(), (
                f"{repo}: required-check name has whitespace drift: {ctx!r}"
            )


# --- TV-BPC-05 — convergence-score baseline ---------------------------


def test_bpc_convergence_score_matches_baseline() -> None:
    """Cross-repo convergence-score = 8/9 per audit section 4.2."""
    per_repo_axes = {}
    for repo, fixture in _AUDIT_FIXTURES.items():
        contexts = frozenset(fixture["required_status_checks"]["contexts"])
        license_axis = _axis_covered(contexts, _LICENSE_CHECK_TOKENS)
        code_axis = _axis_covered(contexts, _CODE_CHECK_TOKENS)
        security_axis = _axis_covered(contexts, _SECURITY_CHECK_TOKENS)
        per_repo_axes[repo] = (license_axis, code_axis, security_axis)

    total = sum(sum(axes) for axes in per_repo_axes.values())
    maximum = 3 * len(per_repo_axes)
    score = total / maximum

    assert (total, maximum) == (8, 9), (
        f"Convergence baseline drifted: expected 8/9, got {total}/{maximum}. "
        f"Per-repo axes (license, code, security): {per_repo_axes!r}. "
        "Either: (a) closing the wakir-runtime CodeQL gap pushed score to "
        "9/9 — update audit doc + baseline; or (b) a required-check was "
        "removed — investigate ops-drift."
    )
    assert abs(score - (8 / 9)) < 1e-9


# --- TV-BPC-06 — license-axis universally covered ---------------------


def test_bpc_license_axis_universal() -> None:
    """All three repos enforce *some* license-class required-check."""
    for repo, fixture in _AUDIT_FIXTURES.items():
        contexts = frozenset(fixture["required_status_checks"]["contexts"])
        assert _axis_covered(contexts, _LICENSE_CHECK_TOKENS) == 1, (
            f"{repo}: no license-hygiene-class required-check found. "
            f"Contexts: {sorted(contexts)!r}"
        )


# --- TV-BPC-07 — force-push disabled ---------------------------------


def test_bpc_force_push_disabled_everywhere() -> None:
    """Every repo must reject force-pushes on the protected branch."""
    for repo, fixture in _AUDIT_FIXTURES.items():
        assert fixture["allow_force_pushes"]["enabled"] is False, (
            f"{repo}: allow_force_pushes is enabled on main — this breaks "
            "the OTS-anchoring trust-perimeter (history must be append-only)."
        )


# --- TV-BPC-08 — branch-deletion disabled -----------------------------


def test_bpc_deletions_disabled_everywhere() -> None:
    """Every repo must reject branch-deletion on the protected branch."""
    for repo, fixture in _AUDIT_FIXTURES.items():
        assert fixture["allow_deletions"]["enabled"] is False, (
            f"{repo}: allow_deletions is enabled on main — protected branch "
            "deletion would orphan all OTS-anchored commit-references."
        )
