#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""CI Aggregator — single Required-Status-Check for wakir-runtime.

ADR-0068 (approved 2026-05-18) substance implementation.

Architectural rationale
-----------------------

The wakir-runtime CI stack has ~30 GitHub-Actions workflows, of which
six are currently Required-Status-Checks on the `main` branch
protection. Each Required-Check has its own ``paths:`` filter. When a
PR's changed-files set does not intersect a Required-Check's path
filter, GitHub registers the check as **never reported**, which the
Branch-Protection rule treats as ``PENDING forever``. This is the
"Forever-Pending" pattern that bit Tag-34/35/36 hard (PR #228, #232,
#236, four Mira-Hand workaround PRs in two days).

ADR-0068 §"Empfehlung" approves a single aggregator workflow as the
sole Required-Status-Check. The aggregator:

  1. Fires on **every** PR/Push (no path-filter of its own).
  2. Reads a declarative "Sub-Workflow Inventory" (see ``SUB_WORKFLOWS``
     below) and the PR's changed-files set.
  3. For each sub-workflow, decides whether the path-filter is expected
     to trigger.
  4. If expected: polls the GitHub Actions API for the corresponding
     workflow run on the same commit SHA, waits for completion,
     collects the verdict.
  5. If not expected: marks the sub-workflow as ``SKIP_OK``.
  6. Final verdict: all "expected" sub-workflows ``SUCCESS`` AND zero
     ``FAILURE``/``CANCELLED``/``TIMED_OUT`` => aggregator ``SUCCESS``.
  7. Emits a per-PR markdown summary table to ``$GITHUB_STEP_SUMMARY``.

Boring tech
-----------

stdlib only (urllib + json + subprocess). No third-party action, no
``requests`` dependency. Pattern is a direct re-use of CPython's
``lint-and-test`` aggregator and Rust's ``bors r+`` try-job model. Both
patterns survived years of churn at higher PR volumes than wakir-runtime
will ever see — this is the boring-tech bet.

Sandbox boundary
----------------

When invoked outside GitHub-Actions (``GITHUB_TOKEN`` unset, ``CI``
unset, or ``WAKIR_CI_AGGREGATOR_DRY_RUN=1``), the script runs in
"decision-table-only" mode — it computes the expected-vs-skip-ok
verdict from a fixture changed-files set and prints the table without
hitting the GitHub API. This is the hermetic-test mode used by
``tests/ci/test_ci_aggregator_workflow.py``.

The decision-logic (``decide_expected_set``, ``aggregate_verdicts``)
is pure-function and fully unit-testable. The I/O wrappers
(``fetch_pr_changed_files``, ``poll_workflow_runs``) are isolated at
the bottom of the file behind the ``# --- I/O boundary ---`` marker.

Author: Tomás Reinhart (Dev-Engineering)
Anchor: ADR-0068 §"Beschluss" + §"Folgeartefakte"
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Sub-workflow inventory
# ---------------------------------------------------------------------------
#
# Each entry declares one sub-workflow that the aggregator depends on.
#
#   workflow_file: the workflow file name under .github/workflows/.
#       Used to look up runs via ``GET /repos/{owner}/{repo}/actions/
#       workflows/{file}/runs?head_sha={sha}``.
#   check_name: the per-job ``name:`` field as it appears on the PR
#       check-run-tab. Used to disambiguate when a workflow declares
#       multiple jobs (e.g. ``tests.yml`` has three jobs: production,
#       shadow, drift-envelope).
#   path_globs: the set of fnmatch-globs that should trigger this
#       sub-workflow. Mirrors the ``on.push.paths`` /
#       ``on.pull_request.paths`` list of the workflow YAML. When the
#       PR changed-files set intersects this, the sub-workflow is
#       "expected". Otherwise "skip-ok".
#   required: whether this sub-workflow is a Required-Status-Check
#       seed (the six contexts currently in Branch-Protection). The
#       aggregator only **emits** one Required-Status; this flag
#       documents lineage so the post-migration cleanup
#       (Mira-Hand-Folge §4 in the auftrag) is auditable.
#
# Inventory is ordered to match the Mira-Hand-Folge migration order
# (license-hygiene first, Phase-2 aggregator last).
#
# Note: ``tests.yml`` contributes three Required-Status names —
# ``wirelang suite with rfc8785 + jsonschema`` (production),
# ``wirelang suite without rfc8785 / jsonschema (shadow)`` (shadow), and
# ``production-vs-sandbox drift envelope`` (drift). All three share the
# same workflow file, so we emit three inventory rows pointing at the
# same workflow with different ``check_name``.

@dataclass(frozen=True)
class SubWorkflow:
    """Declarative spec for one sub-workflow."""

    workflow_file: str
    check_name: str
    path_globs: Tuple[str, ...]
    required: bool = False

    def path_filter_triggers(self, changed_files: Iterable[str]) -> bool:
        """Return True iff at least one changed file matches at least
        one of the workflow's path globs.

        Pure function; safe to unit-test without any GitHub API access.
        Mirrors GitHub-Actions ``paths:``-filter semantics (fnmatch
        with ``**`` as recursive-wildcard treated as ``*``).
        """
        for f in changed_files:
            for glob in self.path_globs:
                # GitHub-Actions uses minimatch-style ``**``. We
                # normalise to fnmatch with three explicit special
                # cases: bare-** prefix (``**/*.py`` => any depth),
                # directory-** suffix (``wirelang/**`` => recursive),
                # and single-* segment.
                # 1. Exact-pattern fnmatch (covers ``*.py`` and
                #    similar non-recursive globs).
                if fnmatch.fnmatch(f, glob):
                    return True
                # 2. Bare-``**``-replacement-to-``*`` (covers
                #    ``foo/**/bar`` style mid-path matches).
                pat = glob.replace("**", "*")
                if fnmatch.fnmatch(f, pat):
                    return True
                # 3. ``**/<rest>`` should match at any depth, **including
                #    depth zero**. fnmatch alone misses the depth-zero
                #    case (it requires the ``*`` segment to bind to
                #    something).
                if glob.startswith("**/"):
                    tail = glob[3:]
                    if fnmatch.fnmatch(f, tail):
                        return True
                # 4. Directory-prefix shortcut: ``wirelang/**`` should
                #    match ``wirelang/foo/bar.py`` (and also
                #    ``wirelang/foo.py``).
                if glob.endswith("/**") and f.startswith(glob[:-3] + "/"):
                    return True
                # 5. Single-* directory glob: ``foo/*`` matches
                #    ``foo/bar`` but not ``foo/bar/baz``.
                if glob.endswith("/*") and "/" in f:
                    head = glob[:-2]
                    rest = f[len(head) + 1 :] if f.startswith(head + "/") else None
                    if rest is not None and "/" not in rest:
                        return True
        return False


# ---------------------------------------------------------------------------
# The canonical sub-workflow inventory.
#
# Keep this list aligned with `.github/workflows/*.yml` ``paths:``
# filters. The hermetic test
# ``tests/ci/test_ci_aggregator_workflow.py::test_inventory_matches_workflow_paths``
# enforces a sanity-bound (each inventory row's path_globs must be a
# non-strict subset of the actual workflow's ``paths:`` declaration).
# ---------------------------------------------------------------------------

SUB_WORKFLOWS: Tuple[SubWorkflow, ...] = (
    # 1. License-Hygiene Gate (ADR-0061) -- license-gate.yml
    SubWorkflow(
        workflow_file="license-gate.yml",
        check_name="License-Hygiene Gate (ADR-0061)",
        path_globs=(
            "**/*.py",
            "**/*.toml",
            "**/LICENSE*",
            "**/NOTICE",
            "LICENSING.md",
            "LICENSES/**",
            "README.md",
            "bin/**",
            "infra/spire/**/bin/**",
            ".github/workflows/**",
            ".cross-repo-drift-allowlist.yaml",
            "dashboards/**",
            "docs/**",
            "wirelang-rust/**",
            "tests/infra/test_spdx_header_consistency.py",
            "tests/infra/test_license_hygiene_consistency.py",
            "tests/infra/test_licensing_md_state.py",
            "REUSE.toml",
        ),
        required=True,
    ),
    # 2. wirelang suite production lane -- tests.yml :: production-suite
    SubWorkflow(
        workflow_file="tests.yml",
        check_name="wirelang suite with rfc8785 + jsonschema",
        path_globs=(
            "wirelang/**",
            "tests/**",
            "pyproject.toml",
            ".github/workflows/**",
            ".cross-repo-drift-allowlist.yaml",
            "dashboards/**",
            "docs/**",
            "wirelang-rust/**",
            ".pre-commit-config.yaml",
            "scripts/pre-commit-*.py",
        ),
        required=True,
    ),
    # 3. wirelang suite shadow lane -- tests.yml :: shadow-suite
    SubWorkflow(
        workflow_file="tests.yml",
        check_name="wirelang suite without rfc8785 / jsonschema (shadow)",
        path_globs=(
            "wirelang/**",
            "tests/**",
            "pyproject.toml",
            ".github/workflows/**",
            ".cross-repo-drift-allowlist.yaml",
            "dashboards/**",
            "docs/**",
            "wirelang-rust/**",
            ".pre-commit-config.yaml",
            "scripts/pre-commit-*.py",
        ),
        required=True,
    ),
    # 4. drift-envelope -- tests.yml :: drift-envelope
    SubWorkflow(
        workflow_file="tests.yml",
        check_name="production-vs-sandbox drift envelope",
        path_globs=(
            "wirelang/**",
            "tests/**",
            "pyproject.toml",
            ".github/workflows/**",
            ".cross-repo-drift-allowlist.yaml",
            "dashboards/**",
            "docs/**",
            "wirelang-rust/**",
            ".pre-commit-config.yaml",
            "scripts/pre-commit-*.py",
        ),
        required=True,
    ),
    # 5. cross-repo drift -- cross-repo-drift-audit.yml
    SubWorkflow(
        workflow_file="cross-repo-drift-audit.yml",
        check_name="cross-repo drift (wakir-runtime ↔ wakir-protocol)",
        path_globs=(
            "wirelang/**",
            "wirelang-rust/**",
            "pyproject.toml",
            "tests/**",
            "scripts/**",
            "dashboards/**",
            "docs/**",
            ".cross-repo-drift-allowlist.yaml",
            ".github/workflows/cross-repo-drift-audit.yml",
        ),
        required=True,
    ),
    # 6. Phase-2 aggregator -- phase-2-validation-gate.yml
    SubWorkflow(
        workflow_file="phase-2-validation-gate.yml",
        check_name="Phase-2 Aggregator (All Gates + Cross-Gate Non-Interference)",
        path_globs=(
            "wirelang/**",
            "tests/infra/test_phase_2_acceptance_gates.py",
            "docs/quality-gates/**",
            ".github/workflows/phase-2-validation-gate.yml",
        ),
        required=True,
    ),
)


# ---------------------------------------------------------------------------
# Decision logic (pure functions, hermetic-test target)
# ---------------------------------------------------------------------------


@dataclass
class SubWorkflowVerdict:
    """Per-sub-workflow verdict carried through the aggregator pipeline."""

    spec: SubWorkflow
    expected: bool
    status: str = "skip-ok"  # one of: skip-ok, success, failure,
    #                           cancelled, timed_out, pending, missing
    run_id: Optional[int] = None
    run_url: Optional[str] = None

    @property
    def is_blocking(self) -> bool:
        """Return True iff this verdict should block the aggregator."""
        if not self.expected:
            return False
        return self.status not in ("success", "skip-ok")


def decide_expected_set(
    changed_files: Sequence[str],
    inventory: Sequence[SubWorkflow] = SUB_WORKFLOWS,
) -> List[SubWorkflowVerdict]:
    """Compute the per-sub-workflow expected/skip-ok decision.

    Pure function: no I/O, no GitHub API calls. This is the function
    that ``tests/ci/test_ci_aggregator_workflow.py`` covers end-to-end.

    Args:
        changed_files: list of repo-relative paths changed by the PR.
            Empty list (e.g. push-to-main with no diff) is treated as
            "no path-filter triggers", so all sub-workflows are
            ``skip-ok``.
        inventory: the sub-workflow inventory. Defaults to the canonical
            module-level ``SUB_WORKFLOWS``. Tests override this with
            fixture-inventories.

    Returns:
        One ``SubWorkflowVerdict`` per inventory entry, with
        ``expected`` populated and ``status`` set to ``skip-ok`` or
        ``pending`` (the I/O layer later upgrades ``pending`` to a
        terminal status).
    """
    verdicts: List[SubWorkflowVerdict] = []
    for spec in inventory:
        expected = spec.path_filter_triggers(changed_files)
        status = "pending" if expected else "skip-ok"
        verdicts.append(SubWorkflowVerdict(spec=spec, expected=expected, status=status))
    return verdicts


def aggregate_verdicts(verdicts: Sequence[SubWorkflowVerdict]) -> str:
    """Reduce per-sub-workflow verdicts to a single aggregator status.

    Returns one of ``success``, ``failure``, ``pending``.

      - ``failure`` if any expected sub-workflow has a blocking status
        (failure, cancelled, timed_out, missing).
      - ``pending`` if no failure but at least one expected verdict
        still ``pending``.
      - ``success`` otherwise (all expected = success, rest = skip-ok).
    """
    has_pending = False
    for v in verdicts:
        if not v.expected:
            continue
        if v.status in ("failure", "cancelled", "timed_out", "missing"):
            return "failure"
        if v.status == "pending":
            has_pending = True
    return "pending" if has_pending else "success"


def render_summary_table(verdicts: Sequence[SubWorkflowVerdict]) -> str:
    """Render a markdown summary table for ``$GITHUB_STEP_SUMMARY``.

    Pure function. Includes a footer line with the aggregator verdict
    and a stable link to the ADR-0068 decision record.
    """
    lines: List[str] = []
    lines.append("# CI Aggregator — Verdict Summary")
    lines.append("")
    lines.append("| Sub-Workflow | Check Name | Expected | Status | Run |")
    lines.append("|---|---|---|---|---|")
    for v in verdicts:
        exp_marker = "yes" if v.expected else "skip"
        if v.run_url:
            run_cell = f"[link]({v.run_url})"
        elif v.run_id is not None:
            run_cell = str(v.run_id)
        else:
            run_cell = "-"
        # Escape pipe in check_name (defensive; none of the current
        # six contain pipes, but future Welle-validations might).
        cn = v.spec.check_name.replace("|", "\\|")
        wf = v.spec.workflow_file
        lines.append(f"| `{wf}` | {cn} | {exp_marker} | `{v.status}` | {run_cell} |")
    lines.append("")
    verdict = aggregate_verdicts(verdicts)
    lines.append(f"**Aggregator Verdict:** `{verdict}`")
    lines.append("")
    lines.append("Anchor: ADR-0068 §Beschluss (2026-05-18).")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Backoff schedule (pure function, hermetic-test target)
# ---------------------------------------------------------------------------


def backoff_schedule(
    *,
    base_seconds: float = 5.0,
    cap_seconds: float = 60.0,
    max_attempts: int = 60,
) -> List[float]:
    """Return an exponential-with-cap backoff schedule.

    Default schedule: 5s, 10s, 20s, 40s, 60s, 60s, ... up to 60 attempts.
    Total wait at default settings: roughly 60min — the GitHub-Actions
    default job timeout. The aggregator's own job-level timeout
    ultimately stops the loop; the schedule is the per-poll cadence.
    """
    out: List[float] = []
    cur = base_seconds
    for _ in range(max_attempts):
        out.append(min(cur, cap_seconds))
        cur = cur * 2 if cur < cap_seconds else cap_seconds
    return out


# ---------------------------------------------------------------------------
# I/O boundary
# ---------------------------------------------------------------------------
# Everything below this marker calls the GitHub API and is **not** unit-
# tested in the hermetic suite. Integration coverage comes from the
# Aggregator's own self-run on the migration PR (the workflow at
# ``.github/workflows/ci-aggregator.yml`` invokes this script and the
# PR-merge is itself the green-light signal).
# ---------------------------------------------------------------------------


def _gh_api(
    path: str,
    *,
    token: str,
    method: str = "GET",
    query: Optional[dict] = None,
    timeout_seconds: float = 30.0,
) -> dict:
    """Minimal GitHub-API client over urllib.

    Returns the parsed JSON response. Raises ``urllib.error.HTTPError``
    for non-2xx responses; callers handle 404 / 422 explicitly.
    """
    url = f"https://api.github.com{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "wakir-ci-aggregator/1.0 (ADR-0068)")
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_pr_changed_files(
    *,
    owner: str,
    repo: str,
    pr_number: int,
    token: str,
) -> List[str]:
    """Return the list of file paths changed in the PR.

    Handles GitHub's 100-files-per-page pagination via ``page`` query
    parameter. Defensive against PRs with >3000 files (rare; the loop
    caps at 30 pages = 3000 files and warns on stderr).
    """
    out: List[str] = []
    for page in range(1, 31):
        payload = _gh_api(
            f"/repos/{owner}/{repo}/pulls/{pr_number}/files",
            token=token,
            query={"per_page": 100, "page": page},
        )
        if not payload:
            break
        for entry in payload:
            out.append(entry["filename"])
        if len(payload) < 100:
            break
    else:
        print(
            f"WARNING: PR #{pr_number} has >3000 files; aggregator "
            f"capped read at 3000.",
            file=sys.stderr,
        )
    return out


def fetch_push_changed_files(
    *,
    owner: str,
    repo: str,
    before_sha: str,
    head_sha: str,
    token: str,
) -> List[str]:
    """Return the list of file paths changed by a push event.

    Uses the ``compare/{base}...{head}`` endpoint. Truncation behaviour
    matches the PR-pagination path: cap at 3000 files, warn on stderr.
    """
    out: List[str] = []
    for page in range(1, 31):
        payload = _gh_api(
            f"/repos/{owner}/{repo}/compare/{before_sha}...{head_sha}",
            token=token,
            query={"per_page": 100, "page": page},
        )
        files = payload.get("files") or []
        for entry in files:
            out.append(entry["filename"])
        if len(files) < 100:
            break
    return out


def poll_workflow_run(
    *,
    owner: str,
    repo: str,
    workflow_file: str,
    head_sha: str,
    check_name: str,
    token: str,
    backoff: Sequence[float],
) -> Tuple[str, Optional[int], Optional[str]]:
    """Poll the GitHub-Actions API for one sub-workflow's verdict.

    Returns (status, run_id, run_url) where status is one of:
      - ``success``, ``failure``, ``cancelled``, ``timed_out``
      - ``missing`` if the workflow never produced a run for this SHA
        within the backoff schedule (treated as blocking by the
        aggregator — the sub-workflow was expected to fire but did not).

    Strategy: per attempt, list runs for the workflow at the head SHA,
    then pick the most-recent. If still ``in_progress`` or ``queued``,
    sleep for the next backoff interval and retry. If completed, fetch
    the per-job list, find the job with display-name == check_name, and
    report its conclusion.
    """
    last_run_id: Optional[int] = None
    last_run_url: Optional[str] = None
    for delay in backoff:
        try:
            runs_payload = _gh_api(
                f"/repos/{owner}/{repo}/actions/workflows/"
                f"{urllib.parse.quote(workflow_file)}/runs",
                token=token,
                query={"head_sha": head_sha, "per_page": 5},
            )
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # Workflow file removed from main; treat as missing.
                return ("missing", None, None)
            raise
        runs = runs_payload.get("workflow_runs") or []
        if not runs:
            time.sleep(delay)
            continue
        run = runs[0]  # most recent
        last_run_id = run["id"]
        last_run_url = run.get("html_url")
        status = run.get("status")  # queued / in_progress / completed
        conclusion = run.get("conclusion")  # success / failure / ...
        if status != "completed":
            time.sleep(delay)
            continue
        # Run is completed; resolve per-job verdict for check_name.
        jobs_payload = _gh_api(
            f"/repos/{owner}/{repo}/actions/runs/{last_run_id}/jobs",
            token=token,
            query={"per_page": 100},
        )
        jobs = jobs_payload.get("jobs") or []
        for job in jobs:
            if job.get("name") == check_name:
                job_conclusion = job.get("conclusion") or "missing"
                return (job_conclusion, last_run_id, last_run_url)
        # Run completed but no matching job-name. Fall back to run-level
        # conclusion as the aggregator verdict — better than ``missing``.
        return (conclusion or "missing", last_run_id, last_run_url)
    # Backoff schedule exhausted without seeing a completed run for the
    # SHA. Surface as ``missing`` so the aggregator blocks.
    return ("missing", last_run_id, last_run_url)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ci_aggregator",
        description="CI Aggregator (ADR-0068) — single Required-Status-Check.",
    )
    parser.add_argument(
        "--mode",
        choices=("decide-only", "live"),
        default="live",
        help=(
            "``decide-only``: pure decide_expected_set + render_summary "
            "from a fixture changed-files list (used by tests). "
            "``live``: fetch PR changed-files and poll workflow runs."
        ),
    )
    parser.add_argument(
        "--changed-files",
        type=str,
        default=None,
        help="Path to a newline-separated list of changed files (decide-only mode).",
    )
    parser.add_argument(
        "--head-sha",
        type=str,
        default=None,
        help="head SHA to poll workflow runs against (live mode).",
    )
    parser.add_argument(
        "--pr-number",
        type=int,
        default=None,
        help="PR number for changed-files fetch (live mode).",
    )
    parser.add_argument(
        "--before-sha",
        type=str,
        default=None,
        help="base SHA for push-event changed-files fetch (live mode, push).",
    )
    parser.add_argument(
        "--owner",
        type=str,
        default=os.environ.get("GITHUB_REPOSITORY_OWNER", ""),
    )
    parser.add_argument(
        "--repo",
        type=str,
        default=(os.environ.get("GITHUB_REPOSITORY") or "/").split("/")[-1],
    )
    parser.add_argument(
        "--summary-path",
        type=str,
        default=os.environ.get("GITHUB_STEP_SUMMARY", ""),
    )
    args = parser.parse_args(argv)

    if args.mode == "decide-only":
        files: List[str] = []
        if args.changed_files:
            files = Path(args.changed_files).read_text(encoding="utf-8").splitlines()
        files = [f.strip() for f in files if f.strip()]
        verdicts = decide_expected_set(files)
        summary = render_summary_table(verdicts)
        sys.stdout.write(summary)
        if args.summary_path:
            Path(args.summary_path).write_text(summary, encoding="utf-8")
        verdict = aggregate_verdicts(verdicts)
        # In decide-only mode, ``pending`` is a hermetic-test signal,
        # not a CI failure. Exit 0 for success/pending, 1 for failure.
        return 0 if verdict in ("success", "pending") else 1

    # --- Live mode ---
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("ERROR: GITHUB_TOKEN not set; cannot run in live mode.", file=sys.stderr)
        return 2
    if not args.head_sha:
        print("ERROR: --head-sha required in live mode.", file=sys.stderr)
        return 2
    if not args.owner or not args.repo:
        print("ERROR: --owner and --repo required in live mode.", file=sys.stderr)
        return 2

    if args.pr_number:
        changed = fetch_pr_changed_files(
            owner=args.owner,
            repo=args.repo,
            pr_number=args.pr_number,
            token=token,
        )
    elif args.before_sha:
        changed = fetch_push_changed_files(
            owner=args.owner,
            repo=args.repo,
            before_sha=args.before_sha,
            head_sha=args.head_sha,
            token=token,
        )
    else:
        # Push-to-main without a before-SHA (initial push) or
        # workflow_dispatch. Conservative default: treat as
        # "everything changed" so every sub-workflow is expected.
        changed = [
            "wirelang/__sentinel__.py",
            "tests/__sentinel__.py",
            "docs/__sentinel__.md",
            ".github/workflows/__sentinel__.yml",
        ]

    print(f"Aggregator changed-files set ({len(changed)}):", file=sys.stderr)
    for f in changed[:50]:
        print(f"  {f}", file=sys.stderr)
    if len(changed) > 50:
        print(f"  ... and {len(changed) - 50} more", file=sys.stderr)

    verdicts = decide_expected_set(changed)
    backoff = backoff_schedule()
    for v in verdicts:
        if not v.expected:
            continue
        status, run_id, run_url = poll_workflow_run(
            owner=args.owner,
            repo=args.repo,
            workflow_file=v.spec.workflow_file,
            head_sha=args.head_sha,
            check_name=v.spec.check_name,
            token=token,
            backoff=backoff,
        )
        v.status = status
        v.run_id = run_id
        v.run_url = run_url

    summary = render_summary_table(verdicts)
    sys.stdout.write(summary)
    if args.summary_path:
        with open(args.summary_path, "a", encoding="utf-8") as f:
            f.write(summary)

    verdict = aggregate_verdicts(verdicts)
    print(f"Aggregator verdict: {verdict}", file=sys.stderr)
    return 0 if verdict == "success" else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
