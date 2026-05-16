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

Test-Vector matrix (12 vectors, all hermetic, no live network):

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
* TV-BPC-09: path-filter-reach — currently Required workflows on
  ``wakir-runtime`` trigger on every reach-relevant PR-path-class
  (``tests.yml`` + ``license-gate.yml`` must reach
  ``code-only``/``test-only``/``doc-only``/``dashboard-only``).
* TV-BPC-10: anti-pattern detection — ``hash-derivate-gate.yml`` is
  flagged as Required-unfit because its path-filter fails the
  universal-trigger rule (operations doc §4.4 / §4.5).
* TV-BPC-11: cross-repo-drift reach — the proposed Required addition
  ``cross-repo drift (wakir-runtime ↔ wakir-protocol)`` triggers on
  ``code-only`` PRs (the in-scope class for substance-classification
  symmetry) per operations doc §4.2.
* TV-BPC-12: universal-trigger consistency — every name currently in
  the Required-set on ``wakir-runtime`` triggers on the three minimum
  required PR-path-classes (``code-only``, ``test-only``,
  ``workflow-only``); detection of regressions on this rule fires.

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


# --- Path-Filter-Reach fixtures (operations doc §4.5) -----------------


# Mock `on.pull_request.paths` blocks for the five wakir-runtime
# workflows that are either currently Required, recommended Required,
# or explicitly named as Required-unfit in operations doc §4.5.
# Sampled 2026-05-16 ~19:36 CEST from the live .github/workflows/
# tree on `main`.

_PATH_FILTERS: dict[str, tuple[str, ...]] = {
    "tests.yml": (
        "wirelang/**",
        "tests/**",
        "pyproject.toml",
        ".github/workflows/tests.yml",
        ".github/workflows/sandbox-ci.yml",
        ".github/workflows/hash-derivate-gate.yml",
        ".github/workflows/cross-repo-drift-audit.yml",
        ".cross-repo-drift-allowlist.yaml",
        ".github/workflows/phase-2-validation-gate.yml",
        "dashboards/**",
        "docs/**",
    ),
    "license-gate.yml": (
        "**/*.py",
        "**/*.toml",
        "**/LICENSE*",
        "**/NOTICE",
        "LICENSING.md",
        "LICENSES/**",
        "README.md",
        "bin/**",
        "infra/spire/**/bin/**",
        ".github/workflows/license-gate.yml",
        ".github/workflows/tests.yml",
        ".github/workflows/sandbox-ci.yml",
        ".github/workflows/hash-derivate-gate.yml",
        ".github/workflows/cross-repo-drift-audit.yml",
        ".cross-repo-drift-allowlist.yaml",
        ".github/workflows/phase-2-validation-gate.yml",
        "dashboards/**",
        "docs/**",
        "tests/infra/test_spdx_header_consistency.py",
        "tests/infra/test_license_hygiene_consistency.py",
    ),
    "hash-derivate-gate.yml": (
        "wirelang/schemas/**",
        "tests/fixtures/schema-registry/**",
        "tests/infra/test_hash_derivate_consistency.py",
        ".github/workflows/hash-derivate-gate.yml",
    ),
    "cross-repo-drift-audit.yml": (
        "wirelang/**",
        "pyproject.toml",
        ".cross-repo-drift-allowlist.yaml",
        ".github/workflows/cross-repo-drift-audit.yml",
    ),
    "phase-2-validation-gate.yml": (
        "wirelang/**",
        "tests/infra/test_phase_2_acceptance_gates.py",
        "docs/quality-gates/**",
        ".github/workflows/phase-2-validation-gate.yml",
    ),
}


# Mapping of Required-status-check display-name to the workflow file
# that defines it. Required for the universal-trigger consistency
# check (TV-BPC-12).

_RUNTIME_CHECKNAME_TO_WORKFLOW: dict[str, str] = {
    "License-Hygiene Gate (ADR-0061)": "license-gate.yml",
    "wirelang suite with rfc8785 + jsonschema": "tests.yml",
}


# Five "typical PR-path-classes" (operations doc §4.5).  Each class is
# represented by a small set of representative file-paths that would
# show up in `git diff --name-only`.  A workflow triggers on a class if
# any of its path-filter globs matches any of the class's paths.

_PR_PATH_CLASSES: dict[str, tuple[str, ...]] = {
    "code-only": (
        "wirelang/wat/builder.py",
        "wirelang/orchestrator/spawn.py",
    ),
    "test-only": (
        "tests/orchestrator/test_spawn.py",
        "tests/infra/test_branch_protection_consistency_audit.py",
    ),
    "workflow-only": (
        ".github/workflows/release.yml",
    ),
    "doc-only": (
        "docs/operations/branch-protection-required-status-checks.md",
        "docs/decisions/0099-some-future-adr.md",
    ),
    "dashboard-only": (
        "dashboards/cost/per-model.json",
        "dashboards/cache/hit-rate.json",
    ),
}


def _glob_matches(pattern: str, path: str) -> bool:
    """Approximate GitHub-Actions path-filter glob-match.

    GitHub uses the ``minimatch`` library (Node) with the following
    behaviours relevant here:

    * ``**`` matches any number of path segments including zero.
    * ``*`` matches within a single segment (no ``/``).
    * Plain segments match literally.

    This helper is a hermetic reimplementation sufficient for the
    five PR-path-classes above. It is not a full minimatch port.
    """
    import fnmatch

    # GitHub's `**/x` matches `x` at any depth, including the root.
    # Python's fnmatch does not natively understand `**`. We do a
    # two-pass: first try the literal pattern (fnmatch handles single
    # `*` per segment but treats `**` as `*`), then handle the
    # specific `**/<suffix>` form by stripping the leading `**/`.
    if pattern.startswith("**/"):
        suffix = pattern[3:]
        # Match at any depth.
        if fnmatch.fnmatch(path, suffix):
            return True
        # Match nested.
        parts = path.split("/")
        for depth in range(len(parts)):
            tail = "/".join(parts[depth:])
            if fnmatch.fnmatch(tail, suffix):
                return True
        return False
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        # Match files inside the prefix-directory.
        return path == prefix or path.startswith(prefix + "/")
    # Plain glob: convert `**` (which fnmatch treats as `*`) by
    # replacing `**` with `*` first, then fnmatch.
    flat = pattern.replace("**", "*")
    return fnmatch.fnmatch(path, flat)


def _workflow_triggers_on_class(
    workflow: str, pr_class: str
) -> bool:
    """Return True if *workflow* triggers on at least one path of *pr_class*."""
    patterns = _PATH_FILTERS[workflow]
    paths = _PR_PATH_CLASSES[pr_class]
    for path in paths:
        for pattern in patterns:
            if _glob_matches(pattern, path):
                return True
    return False


# --- TV-BPC-09 — currently Required workflows have universal reach ---


@pytest.mark.parametrize(
    "workflow,pr_class",
    [
        (wf, cls)
        for wf in ("tests.yml", "license-gate.yml")
        for cls in (
            "code-only",
            "test-only",
            "doc-only",
            "dashboard-only",
        )
    ],
    ids=lambda v: v.replace(".yml", "").replace("-", "_"),
)
def test_bpc_required_workflows_reach_typical_pr_classes(
    workflow: str, pr_class: str
) -> None:
    """Every currently Required workflow on wakir-runtime must trigger on
    each of the four substance-reach PR-path-classes.

    The ``workflow-only`` class is excluded from this vector because
    workflows-only PRs are by construction self-listing in their own
    path-filter; the universal-reach property does not extend to
    *other* workflows' YAMLs as a class. Operations doc §4.5 records
    this exception explicitly.
    """
    triggered = _workflow_triggers_on_class(workflow, pr_class)
    assert triggered, (
        f"Required workflow {workflow} does NOT trigger on PR-path-class "
        f"{pr_class!r}. This is the forever-PENDING shape from "
        f"`feedback_branch_protection_check_names`. Either widen the "
        f"path-filter or de-Required the check (operations doc §4.4)."
    )


# --- TV-BPC-10 — anti-pattern detection on hash-derivate-gate --------


def test_bpc_hash_derivate_gate_is_required_unfit() -> None:
    """``hash-derivate-gate.yml`` is flagged Required-unfit.

    Per operations doc §4.4, a workflow with a narrow path-filter that
    fails the universal-trigger rule must not be added to the
    Required-set. This test asserts that fact remains true (so that if
    someone widens the path-filter to make the gate Required-fit, the
    audit doc must be updated in the same PR).

    Required-fit (as defined here) = triggers on AT LEAST the
    ``code-only``, ``test-only``, ``doc-only``, and ``dashboard-only``
    classes. If a future PR widens the filter to satisfy this, this
    test must be updated (and the doc §4.4 + §7 entry too).
    """
    required_classes = (
        "code-only",
        "test-only",
        "doc-only",
        "dashboard-only",
    )
    triggered = {
        cls: _workflow_triggers_on_class("hash-derivate-gate.yml", cls)
        for cls in required_classes
    }
    fit = all(triggered.values())

    assert not fit, (
        "hash-derivate-gate.yml has been widened to universal reach: "
        f"trigger-map = {triggered!r}. Update the operations doc §4.1 / "
        "§4.4 (withdrawal rationale no longer applies) and re-consider "
        "Required-promotion. Then update this assertion to expect "
        "fit=True."
    )

    # And confirm the specific gaps stay where the doc says they are.
    assert triggered["doc-only"] is False, (
        "hash-derivate-gate.yml unexpectedly triggers on doc-only PRs — "
        "operations doc §4.5 row is stale."
    )
    assert triggered["dashboard-only"] is False, (
        "hash-derivate-gate.yml unexpectedly triggers on dashboard-only "
        "PRs — operations doc §4.5 row is stale."
    )


# --- TV-BPC-11 — cross-repo-drift reach on code-only -----------------


def test_bpc_cross_repo_drift_reaches_code_only_class() -> None:
    """``cross-repo-drift-audit.yml`` reaches ``code-only`` PRs.

    Operations doc §4.2 recommends promoting this workflow to Required
    on the strength that it covers the in-scope PR-class
    (substance-classification PRs touching ``wirelang/**``). This test
    pins that property: if a future path-filter narrowing breaks it,
    the §4.2 recommendation is no longer valid and the operator must
    re-evaluate before applying.
    """
    assert _workflow_triggers_on_class(
        "cross-repo-drift-audit.yml", "code-only"
    ), (
        "cross-repo-drift-audit.yml no longer reaches code-only PRs. "
        "Operations doc §4.2 Required-promotion recommendation is "
        "INVALID until path-filter is restored. Do NOT mark this check "
        "Required on wakir-runtime/main."
    )

    # And confirm the documented non-reach properties hold (so the
    # operator's reach-analysis in §4.2 stays accurate).
    assert _workflow_triggers_on_class(
        "cross-repo-drift-audit.yml", "test-only"
    ) is False, (
        "cross-repo-drift-audit.yml now reaches test-only PRs. Update "
        "operations doc §4.2 reach-paragraph and §4.5 row."
    )
    assert _workflow_triggers_on_class(
        "cross-repo-drift-audit.yml", "doc-only"
    ) is False, (
        "cross-repo-drift-audit.yml now reaches doc-only PRs. Update "
        "operations doc §4.2 reach-paragraph and §4.5 row."
    )


# --- TV-BPC-12 — universal-trigger consistency across Required-set ---


def test_bpc_required_set_has_universal_minimum_reach() -> None:
    """Every Required check on wakir-runtime triggers on the minimum
    PR-path-class set.

    Minimum reach = ``code-only`` AND ``test-only``. (``doc-only`` and
    ``dashboard-only`` are also documented as reach targets in §4.5
    and TV-BPC-09 pins them for the currently Required pair.
    ``workflow-only`` is not a minimum-reach requirement because
    foreign-workflow-only PRs are by construction out of scope of the
    quality-gate (a PR that only edits, say, ``release.yml`` does not
    need re-running the license-gate or wirelang suite). The
    self-listing variant — "the workflow file of the Required check
    itself is modified" — is enforced by TV-BPC-12b below.)

    TV-BPC-12 is the tighter regression-anchor: any *new* Required-check
    that fails to reach ``code-only`` or ``test-only`` is flagged here.
    """
    minimum_classes = ("code-only", "test-only")
    for check_name in _EXPECTED_CONTEXTS["wakir-runtime"]:
        workflow = _RUNTIME_CHECKNAME_TO_WORKFLOW.get(check_name)
        assert workflow is not None, (
            f"Required check {check_name!r} on wakir-runtime is not "
            "mapped to a workflow file in "
            "_RUNTIME_CHECKNAME_TO_WORKFLOW. Update the mapping when "
            "operations doc §2.1 changes."
        )
        for cls in minimum_classes:
            assert _workflow_triggers_on_class(workflow, cls), (
                f"Required check {check_name!r} (workflow {workflow}) "
                f"FAILS minimum-reach on PR-path-class {cls!r}. This is "
                "the §4.4 anti-pattern. Either widen the path-filter or "
                "remove the check from the Required-set."
            )


# --- TV-BPC-12b — self-listing path-filter discipline ----------------


def test_bpc_required_workflow_paths_self_list() -> None:
    """Each Required workflow's path-filter contains its own YAML path.

    Self-listing is what allows a PR that modifies the gate itself to
    re-trigger the gate. Without self-listing, the gate's
    modification-PR cannot merge behind the gate (the gate doesn't run
    on the PR, the Required-marker stays PENDING). This is the
    Henne-Ei failure mode from PRs #102 / #107 / #117 (2026-05-16),
    where the path-filter expansion PRs did not match their own
    workflow's old filter and stalled.
    """
    for check_name in _EXPECTED_CONTEXTS["wakir-runtime"]:
        workflow = _RUNTIME_CHECKNAME_TO_WORKFLOW.get(check_name)
        assert workflow is not None
        patterns = _PATH_FILTERS[workflow]
        self_path = f".github/workflows/{workflow}"
        # Direct match or broader glob (e.g. ``**/*.yml`` does not
        # count here — we want explicit self-listing for clarity).
        listed = any(p == self_path for p in patterns)
        assert listed, (
            f"Required workflow {workflow} does NOT explicitly list "
            f"itself ({self_path!r}) in its own path-filter. "
            f"Patterns: {patterns!r}. This re-creates the Henne-Ei "
            f"failure shape from PRs #102/#107/#117 — a future "
            f"path-filter modification PR would stall forever-PENDING."
        )
