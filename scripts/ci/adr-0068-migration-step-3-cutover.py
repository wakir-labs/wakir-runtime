#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""ADR-0068 Migration-Step-3 Cutover-Script.

Context
-------

ADR-0068 (approved 2026-05-18) replaces the multi-name
Required-Status-Checks list on ``wakir-runtime/main`` with a single
``ci-aggregator`` Required-Status-Check. Tomas Tag-37 PR #244
delivered the aggregator workflow itself; Noa Tag-38 PR #251
delivered the failure-rate-tracker observability layer that the
present script reads. This script performs the final cutover:
patch the GitHub branch-protection ``required_status_checks.contexts``
list to ``["ci-aggregator"]``.

The cutover is gated by a three-gate read:

  * Gate 1 - Drift Gate: Noa's tracker must report
    ``summary.drift_event_count == 0`` over the most recent N
    (default 50) aggregator runs. A non-zero drift means the
    aggregator verdict diverged from the legacy-name union at least
    once - cutover is unsafe.

  * Gate 2 - Time Gate: At least 7 days must have elapsed since
    ADR-0068 approval (2026-05-18). The 7-day window matches the
    ADR-stated observation window for the aggregator.

  * Gate 3 - Operator Gate: The operator (Mira-Hand) must
    authorize via the ``MIRA_HAND_AUTHORIZED=1`` environment
    variable or the ``--mira-hand-authorized`` CLI flag. This is
    the explicit human-decision boundary; the script will not
    cutover without it even if Gates 1 and 2 pass.

Modes
-----

The script offers three operating modes:

  * ``--dry-run`` (default when invoked without ``--apply``):
    Report gate readings and the proposed patch payload; do not
    call ``gh api PATCH``.

  * ``--apply``: Perform the cutover. Requires all three gates
    green. Writes a timestamped pre-cutover backup of the current
    required-status-checks list to
    ``backup/branch-protection-pre-migration-{ts}.json`` before
    the PATCH.

  * ``--rollback <backup-file>``: Restore the
    ``required_status_checks.contexts`` list from a backup file
    previously written by ``--apply``. Useful if the post-cutover
    monitoring shows aggregator regressions and the legacy names
    must be re-instated.

Sandbox boundary
----------------

When invoked without ``GITHUB_TOKEN`` and with
``WAKIR_MIGRATION_STEP_3_DRY_RUN=1`` set (or ``--dry-run``), the
script does not call the GitHub API. ``--fixture-tracker-json``
and ``--fixture-current-protection`` redirect the two API reads to
on-disk JSON fixtures. This mirrors the
``ci_aggregator.py`` / ``aggregator-failure-rate-tracker.py``
decide-only-vs-live split and is the mode used by the hermetic
test suite (``tests/ci/test_adr_0068_migration_step_3.py``).

Pure-function-vs-IO split
-------------------------

Everything above the ``# --- I/O boundary ---`` marker is
pure-function, hermetic-test target. The I/O wrappers
(``read_tracker_json``, ``fetch_current_protection``,
``apply_patch``, ``write_backup``) are isolated at the bottom.

Anchors
-------

  * ADR-0068 (approved 2026-05-18)
  * Noa tracker schema:
    ``scripts/observability/aggregator-failure-rate-tracker.py``
    (PR #251, ``6d0bb73``)
  * Current branch-protection baseline:
    ``tests/ci/test_branch_protection_check_names_audit.py::REQUIRED_NAMES_RUNTIME``
  * Tomas aggregator workflow:
    ``.github/workflows/ci-aggregator.yml`` (PR #244)
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
from typing import Any, Mapping, Optional, Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: ADR-0068 was approved on this date (UTC). Gate 2 measures
#: ``today - ADR_APPROVAL_DATE`` against ``MIN_OBSERVATION_DAYS``.
ADR_0068_APPROVAL_DATE = dt.date(2026, 5, 18)

#: Minimum days that must elapse between ADR approval and cutover.
#: ADR-0068 stipulates a ~1-week observation window.
MIN_OBSERVATION_DAYS = 7

#: Minimum number of recent aggregator runs that must show zero
#: drift events for Gate 1 to pass. Default 50; can be overridden
#: by ``--min-clean-runs``.
DEFAULT_MIN_CLEAN_RUNS = 50

#: Repository slug for the gh api call.
DEFAULT_REPO = "wakir-labs/wakir-runtime"

#: Final cutover state: aggregator is the only Required-Status-Check.
TARGET_REQUIRED_CONTEXTS: tuple[str, ...] = ("ci-aggregator",)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class GateReading:
    """Outcome of one gate evaluation.

    Attributes
    ----------
    name:
        Short label, e.g. ``"drift"``, ``"time"``, ``"operator"``.
    passed:
        ``True`` iff the gate condition is satisfied.
    detail:
        Human-readable explanation, e.g. ``"drift_event_count=0,
        sample_count=52 >= min 50"``.
    """

    name: str
    passed: bool
    detail: str


@dataclasses.dataclass(frozen=True)
class CutoverPlan:
    """The proposed cutover action.

    Attributes
    ----------
    repo:
        ``owner/name`` slug.
    pre_contexts:
        Required-Status-Check names currently configured (read
        from branch-protection API or fixture).
    post_contexts:
        Required-Status-Check names after the cutover.
    backup_path:
        Where the pre-cutover backup will be written.
    """

    repo: str
    pre_contexts: tuple[str, ...]
    post_contexts: tuple[str, ...]
    backup_path: pathlib.Path


@dataclasses.dataclass(frozen=True)
class GateReport:
    """The aggregate gate-readings + go/no-go decision."""

    gates: tuple[GateReading, ...]

    @property
    def all_passed(self) -> bool:
        return all(g.passed for g in self.gates)

    def as_dict(self) -> dict:
        return {
            "all_passed": self.all_passed,
            "gates": [
                {"name": g.name, "passed": g.passed, "detail": g.detail}
                for g in self.gates
            ],
        }


# ---------------------------------------------------------------------------
# Pure-function gates
# ---------------------------------------------------------------------------


def gate_drift(
    tracker_payload: Mapping[str, Any],
    *,
    min_clean_runs: int = DEFAULT_MIN_CLEAN_RUNS,
) -> GateReading:
    """Gate 1: drift-event count over recent aggregator runs.

    Reads Noa's tracker JSON
    (``scripts/observability/aggregator-failure-rate-tracker.py``)
    and asserts:

      * ``summary.drift_event_count == 0``, AND
      * the sample count for ``ci-aggregator`` in the largest
        configured window is ``>= min_clean_runs``.

    The second condition matters because zero drift over 3 runs
    is not the same as zero drift over 50 runs.

    Parameters
    ----------
    tracker_payload:
        Parsed JSON payload from
        ``aggregator-failure-rate-tracker.py``. The schema is
        documented in that script's ``render_json_rollup`` docstring.
    min_clean_runs:
        Minimum sample count required in the largest rollup window.

    Returns
    -------
    GateReading
        ``passed=True`` iff both subconditions are satisfied.
    """
    summary = tracker_payload.get("summary") or {}
    drift_count = summary.get("drift_event_count")
    if drift_count is None:
        return GateReading(
            name="drift",
            passed=False,
            detail=(
                "tracker payload missing 'summary.drift_event_count'; "
                "cannot evaluate Gate 1"
            ),
        )
    if not isinstance(drift_count, int):
        return GateReading(
            name="drift",
            passed=False,
            detail=(
                f"tracker 'summary.drift_event_count' is "
                f"{type(drift_count).__name__}, expected int"
            ),
        )
    if drift_count != 0:
        return GateReading(
            name="drift",
            passed=False,
            detail=(
                f"drift_event_count={drift_count} > 0; aggregator "
                f"verdict diverged from legacy-name union at least once. "
                f"Cutover unsafe. Extend observation window."
            ),
        )

    # Largest window sample-count for ci-aggregator itself.
    sample_count = _largest_window_sample_count(
        tracker_payload, check_name="ci-aggregator"
    )
    if sample_count is None:
        return GateReading(
            name="drift",
            passed=False,
            detail=(
                "tracker payload has no rollup for check_name='ci-aggregator'; "
                "cannot confirm sample size for Gate 1"
            ),
        )
    if sample_count < min_clean_runs:
        return GateReading(
            name="drift",
            passed=False,
            detail=(
                f"drift_event_count=0 but sample_count={sample_count} "
                f"< min {min_clean_runs}; not enough runs observed yet"
            ),
        )
    return GateReading(
        name="drift",
        passed=True,
        detail=(
            f"drift_event_count=0 over {sample_count} runs "
            f"(>= min {min_clean_runs})"
        ),
    )


def _largest_window_sample_count(
    tracker_payload: Mapping[str, Any], *, check_name: str
) -> Optional[int]:
    """Return the sample-count of the largest configured window for
    ``check_name`` in the tracker payload, or ``None`` if the check
    name is not present.

    Pure function. Exposed at module-level for direct test access.
    """
    rollups = tracker_payload.get("rollups") or []
    for r in rollups:
        if not isinstance(r, Mapping):
            continue
        if r.get("check_name") != check_name:
            continue
        windows = r.get("windows") or {}
        if not isinstance(windows, Mapping) or not windows:
            return None
        # Window keys are stringified ints ("50", "100", "500").
        try:
            largest_key = max(windows.keys(), key=lambda k: int(k))
        except (ValueError, TypeError):
            return None
        win = windows.get(largest_key) or {}
        sc = win.get("sample_count")
        return int(sc) if isinstance(sc, int) else None
    return None


def gate_time(
    now: dt.date,
    *,
    approval_date: dt.date = ADR_0068_APPROVAL_DATE,
    min_days: int = MIN_OBSERVATION_DAYS,
) -> GateReading:
    """Gate 2: observation-window time gate.

    The cutover must wait at least ``min_days`` (default 7) after
    ADR-0068 approval.

    Parameters
    ----------
    now:
        Today's date (UTC).
    approval_date:
        ADR-0068 approval date.
    min_days:
        Minimum days that must elapse.

    Returns
    -------
    GateReading
        ``passed=True`` iff ``(now - approval_date).days >= min_days``.
    """
    delta_days = (now - approval_date).days
    if delta_days < min_days:
        return GateReading(
            name="time",
            passed=False,
            detail=(
                f"{delta_days} day(s) since ADR-0068 approval "
                f"({approval_date.isoformat()}); min {min_days} required"
            ),
        )
    return GateReading(
        name="time",
        passed=True,
        detail=(
            f"{delta_days} day(s) since ADR-0068 approval "
            f"({approval_date.isoformat()}); >= min {min_days}"
        ),
    )


def gate_operator(
    *,
    env_flag: Optional[str],
    cli_flag: bool,
) -> GateReading:
    """Gate 3: explicit operator authorization.

    Authorization is granted by EITHER:

      * environment variable ``MIRA_HAND_AUTHORIZED=1``, OR
      * the CLI flag ``--mira-hand-authorized``.

    Parameters
    ----------
    env_flag:
        Value of the ``MIRA_HAND_AUTHORIZED`` env var, or ``None``
        if unset.
    cli_flag:
        Whether ``--mira-hand-authorized`` was passed.

    Returns
    -------
    GateReading
        ``passed=True`` iff at least one authorization channel is
        active.
    """
    env_authorized = env_flag == "1"
    if env_authorized or cli_flag:
        ch = []
        if env_authorized:
            ch.append("env(MIRA_HAND_AUTHORIZED=1)")
        if cli_flag:
            ch.append("cli(--mira-hand-authorized)")
        return GateReading(
            name="operator",
            passed=True,
            detail=f"authorized via {', '.join(ch)}",
        )
    return GateReading(
        name="operator",
        passed=False,
        detail=(
            "no operator authorization (set MIRA_HAND_AUTHORIZED=1 or "
            "pass --mira-hand-authorized)"
        ),
    )


def evaluate_all_gates(
    tracker_payload: Mapping[str, Any],
    *,
    now: dt.date,
    env_flag: Optional[str],
    cli_flag: bool,
    min_clean_runs: int = DEFAULT_MIN_CLEAN_RUNS,
    approval_date: dt.date = ADR_0068_APPROVAL_DATE,
    min_days: int = MIN_OBSERVATION_DAYS,
) -> GateReport:
    """Run all three gates and return their aggregate report.

    Pure function: no I/O, all inputs explicit. The top-level
    ``main`` is responsible for sourcing the tracker payload from
    file/network and passing it in.
    """
    return GateReport(
        gates=(
            gate_drift(tracker_payload, min_clean_runs=min_clean_runs),
            gate_time(now, approval_date=approval_date, min_days=min_days),
            gate_operator(env_flag=env_flag, cli_flag=cli_flag),
        )
    )


# ---------------------------------------------------------------------------
# Plan / patch / backup (pure)
# ---------------------------------------------------------------------------


def build_cutover_plan(
    *,
    repo: str,
    pre_contexts: Sequence[str],
    backup_dir: pathlib.Path,
    timestamp_unixtime: float,
    post_contexts: Sequence[str] = TARGET_REQUIRED_CONTEXTS,
) -> CutoverPlan:
    """Construct a CutoverPlan with a timestamped backup path.

    Backup-filename convention:
    ``branch-protection-pre-migration-{YYYYMMDDTHHMMSSZ}.json``.

    Pure function: does not touch the filesystem.
    """
    ts = dt.datetime.fromtimestamp(
        timestamp_unixtime, tz=dt.timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"branch-protection-pre-migration-{ts}.json"
    return CutoverPlan(
        repo=repo,
        pre_contexts=tuple(pre_contexts),
        post_contexts=tuple(post_contexts),
        backup_path=backup_path,
    )


def build_patch_payload(post_contexts: Sequence[str]) -> dict:
    """Build the ``gh api PATCH`` body for ``required_status_checks``.

    The GitHub branch-protection API accepts a partial PATCH body
    that updates only the ``required_status_checks`` sub-object.
    We send the ``contexts`` list and preserve ``strict=True``
    (the prior baseline; if the baseline drifts the operator must
    investigate manually).

    Pure function.
    """
    return {
        "required_status_checks": {
            "strict": True,
            "contexts": list(post_contexts),
        }
    }


def build_backup_document(
    *,
    repo: str,
    pre_protection: Mapping[str, Any],
    timestamp_unixtime: float,
) -> dict:
    """Build the JSON document that ``--apply`` will write to disk
    before issuing the PATCH.

    The document is sufficient to fully re-construct the prior
    ``required_status_checks.contexts`` list via ``--rollback``.

    Pure function.
    """
    rsc = pre_protection.get("required_status_checks") or {}
    contexts = list(rsc.get("contexts") or [])
    strict = bool(rsc.get("strict", True))
    return {
        "schema_version": 1,
        "anchor": "ADR-0068 Migration-Step-3",
        "timestamp_unixtime": timestamp_unixtime,
        "timestamp_iso": dt.datetime.fromtimestamp(
            timestamp_unixtime, tz=dt.timezone.utc
        ).isoformat(),
        "repo": repo,
        "required_status_checks": {
            "strict": strict,
            "contexts": contexts,
        },
    }


def build_rollback_payload(backup_document: Mapping[str, Any]) -> dict:
    """Reverse of ``build_patch_payload``: read a backup document
    and produce the PATCH body that re-instates the prior state.

    Pure function. Validates that the document has schema_version 1
    and a non-empty contexts list.
    """
    sv = backup_document.get("schema_version")
    if sv != 1:
        raise ValueError(
            f"backup document schema_version={sv!r}, expected 1"
        )
    rsc = backup_document.get("required_status_checks") or {}
    contexts = rsc.get("contexts")
    if not isinstance(contexts, list) or not contexts:
        raise ValueError(
            "backup document has no required_status_checks.contexts "
            "or it is empty; refusing to rollback to empty state"
        )
    strict = bool(rsc.get("strict", True))
    return {
        "required_status_checks": {
            "strict": strict,
            "contexts": list(contexts),
        }
    }


def format_gate_report(report: GateReport) -> str:
    """Render a GateReport for stdout / log consumption.

    Pure function.
    """
    lines = ["ADR-0068 Migration-Step-3 Gate Report"]
    lines.append("=" * len(lines[0]))
    for g in report.gates:
        mark = "OK  " if g.passed else "FAIL"
        lines.append(f"  [{mark}] gate-{g.name}: {g.detail}")
    lines.append("")
    if report.all_passed:
        lines.append("Verdict: ALL GATES PASSED -- cutover may proceed.")
    else:
        lines.append(
            "Verdict: AT LEAST ONE GATE FAILED -- cutover refused."
        )
    return "\n".join(lines) + "\n"


def format_plan(plan: CutoverPlan) -> str:
    """Render a CutoverPlan for dry-run / pre-apply output.

    Pure function.
    """
    lines = [
        f"Cutover plan for {plan.repo}:",
        f"  Pre-cutover  contexts ({len(plan.pre_contexts)}):",
    ]
    for c in plan.pre_contexts:
        lines.append(f"    - {c}")
    lines.append(
        f"  Post-cutover contexts ({len(plan.post_contexts)}):"
    )
    for c in plan.post_contexts:
        lines.append(f"    + {c}")
    lines.append(f"  Backup file: {plan.backup_path}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# I/O boundary
# ---------------------------------------------------------------------------


def read_tracker_json(path: pathlib.Path) -> dict:
    """Read Noa's tracker JSON from disk.

    I/O wrapper. Hermetic tests inject a fixture path; live mode
    points to the path produced by Noa's tracker run (typically
    ``/var/lib/prometheus/.../aggregator-failure-rate.json`` or
    a CI artifact).
    """
    return json.loads(path.read_text())


def fetch_current_protection(
    repo: str, *, gh_path: str = "gh"
) -> dict:
    """Read the current branch-protection JSON for ``{repo}/main``.

    Live mode: shells out to ``gh api repos/{repo}/branches/main/
    protection`` and parses the JSON. Requires ``GITHUB_TOKEN`` in
    the environment (or ``gh auth login`` state) with admin scope
    on the repo.

    I/O wrapper. Not invoked under ``--fixture-current-protection``.
    """
    cmd = [
        gh_path,
        "api",
        f"repos/{repo}/branches/main/protection",
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"gh CLI not found at {gh_path!r}; install GitHub CLI or "
            f"pass --fixture-current-protection for offline mode"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"gh api failed (exit {exc.returncode}): "
            f"{exc.stderr.decode('utf-8', errors='replace').strip()}"
        ) from exc
    return json.loads(out)


def fetch_current_protection_from_fixture(
    fixture_path: pathlib.Path,
) -> dict:
    """Hermetic-test path: read the fake protection JSON from disk."""
    return json.loads(fixture_path.read_text())


def write_backup(
    backup_path: pathlib.Path, document: Mapping[str, Any]
) -> None:
    """Persist the pre-cutover backup atomically.

    Writes to ``{backup_path}.tmp`` then renames; the rename is
    atomic on POSIX filesystems. Creates the parent directory if
    absent.
    """
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = backup_path.with_suffix(backup_path.suffix + ".tmp")
    tmp.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    tmp.replace(backup_path)


def apply_patch(
    repo: str,
    patch_payload: Mapping[str, Any],
    *,
    gh_path: str = "gh",
) -> dict:
    """Send the PATCH to GitHub.

    Uses ``gh api --method PATCH ... --input -`` and streams the
    JSON body via stdin. Returns the parsed response on success;
    raises ``RuntimeError`` on any non-zero exit code.

    I/O wrapper. Not invoked under ``--dry-run``.
    """
    cmd = [
        gh_path,
        "api",
        "--method",
        "PATCH",
        f"repos/{repo}/branches/main/protection/required_status_checks",
        "--input",
        "-",
    ]
    body = json.dumps(patch_payload["required_status_checks"])
    try:
        proc = subprocess.run(
            cmd,
            input=body.encode("utf-8"),
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"gh CLI not found at {gh_path!r}"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"gh api PATCH failed (exit {exc.returncode}): "
            f"{exc.stderr.decode('utf-8', errors='replace').strip()}"
        ) from exc
    if not proc.stdout:
        return {}
    return json.loads(proc.stdout)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="adr-0068-migration-step-3-cutover.py",
        description=(
            "ADR-0068 Migration-Step-3 cutover script: replace the "
            "multi-name Required-Status-Checks list on wakir-runtime/"
            "main with a single 'ci-aggregator' Required-Status-Check. "
            "Gated by a three-read (drift / time / operator)."
        ),
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Default mode. Read gates, print plan, do not call "
            "gh api PATCH."
        ),
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Perform the cutover. Requires all three gates green. "
            "Writes a timestamped backup before the PATCH."
        ),
    )
    mode.add_argument(
        "--rollback",
        type=pathlib.Path,
        metavar="BACKUP_FILE",
        help=(
            "Restore required-status-checks from a backup file "
            "previously written by --apply."
        ),
    )
    p.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        help=f"Repository slug (default {DEFAULT_REPO})",
    )
    p.add_argument(
        "--tracker-json",
        type=pathlib.Path,
        default=None,
        help=(
            "Path to Noa's aggregator-failure-rate-tracker JSON "
            "output. Required for --dry-run / --apply (not for "
            "--rollback)."
        ),
    )
    p.add_argument(
        "--fixture-current-protection",
        type=pathlib.Path,
        default=None,
        help=(
            "Hermetic-test mode: read current branch-protection "
            "JSON from this file instead of calling gh api."
        ),
    )
    p.add_argument(
        "--backup-dir",
        type=pathlib.Path,
        default=pathlib.Path("backup"),
        help=(
            "Directory where pre-cutover backups are written "
            "(default ./backup)."
        ),
    )
    p.add_argument(
        "--min-clean-runs",
        type=int,
        default=DEFAULT_MIN_CLEAN_RUNS,
        help=(
            f"Gate 1 minimum sample count "
            f"(default {DEFAULT_MIN_CLEAN_RUNS})"
        ),
    )
    p.add_argument(
        "--min-days",
        type=int,
        default=MIN_OBSERVATION_DAYS,
        help=(
            f"Gate 2 minimum days since ADR approval "
            f"(default {MIN_OBSERVATION_DAYS})"
        ),
    )
    p.add_argument(
        "--mira-hand-authorized",
        action="store_true",
        help=(
            "Gate 3 CLI authorization channel. Equivalent to setting "
            "MIRA_HAND_AUTHORIZED=1 in the env."
        ),
    )
    p.add_argument(
        "--now",
        type=str,
        default=None,
        help=(
            "Override today's date as ISO 'YYYY-MM-DD' for testing. "
            "Default: today's UTC date."
        ),
    )
    p.add_argument(
        "--gh-path",
        default="gh",
        help="Path to gh CLI executable (default 'gh')",
    )
    return p


def _parse_now(s: Optional[str]) -> dt.date:
    if s is None:
        return dt.datetime.now(tz=dt.timezone.utc).date()
    return dt.date.fromisoformat(s)


def _run_dry_or_apply(
    args: argparse.Namespace, *, apply: bool, stdout
) -> int:
    """Run the dry-run path or the apply path. Returns exit code."""
    if args.tracker_json is None:
        print(
            "error: --tracker-json is required for "
            "--dry-run / --apply",
            file=sys.stderr,
        )
        return 2

    tracker = read_tracker_json(args.tracker_json)
    now = _parse_now(args.now)
    env_flag = os.environ.get("MIRA_HAND_AUTHORIZED")
    report = evaluate_all_gates(
        tracker,
        now=now,
        env_flag=env_flag,
        cli_flag=args.mira_hand_authorized,
        min_clean_runs=args.min_clean_runs,
        min_days=args.min_days,
    )
    stdout.write(format_gate_report(report))

    if args.fixture_current_protection is not None:
        pre = fetch_current_protection_from_fixture(
            args.fixture_current_protection
        )
    else:
        pre = fetch_current_protection(
            args.repo, gh_path=args.gh_path
        )
    pre_contexts = tuple(
        (pre.get("required_status_checks") or {}).get("contexts") or []
    )

    plan = build_cutover_plan(
        repo=args.repo,
        pre_contexts=pre_contexts,
        backup_dir=args.backup_dir,
        timestamp_unixtime=time.time(),
    )
    stdout.write(format_plan(plan))

    if not apply:
        stdout.write("Dry-run complete; no changes made.\n")
        return 0 if report.all_passed else 1

    if not report.all_passed:
        stdout.write(
            "Refusing to --apply: at least one gate failed.\n"
        )
        return 1

    # Backup first.
    backup_doc = build_backup_document(
        repo=args.repo,
        pre_protection=pre,
        timestamp_unixtime=time.time(),
    )
    write_backup(plan.backup_path, backup_doc)
    stdout.write(f"Backup written: {plan.backup_path}\n")

    # Patch.
    patch_payload = build_patch_payload(plan.post_contexts)
    apply_patch(args.repo, patch_payload, gh_path=args.gh_path)
    stdout.write(
        f"PATCH applied: {args.repo}/main required_status_checks."
        f"contexts = {list(plan.post_contexts)}\n"
    )
    return 0


def _run_rollback(
    args: argparse.Namespace, *, stdout
) -> int:
    """Run the rollback path. Returns exit code."""
    backup_path: pathlib.Path = args.rollback
    if not backup_path.exists():
        print(
            f"error: backup file not found: {backup_path}",
            file=sys.stderr,
        )
        return 2
    try:
        backup_doc = json.loads(backup_path.read_text())
    except json.JSONDecodeError as exc:
        print(
            f"error: backup file is not valid JSON: {exc}",
            file=sys.stderr,
        )
        return 2

    try:
        payload = build_rollback_payload(backup_doc)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    contexts = payload["required_status_checks"]["contexts"]
    stdout.write(
        f"Rollback plan for {args.repo}:\n"
        f"  Restore required_status_checks.contexts "
        f"({len(contexts)}):\n"
    )
    for c in contexts:
        stdout.write(f"    + {c}\n")

    # Rollback is an operator-initiated emergency action and does
    # NOT require the three-gate read. It DOES require explicit
    # operator authorization to avoid accidental restoration.
    env_flag = os.environ.get("MIRA_HAND_AUTHORIZED")
    if env_flag != "1" and not args.mira_hand_authorized:
        stdout.write(
            "Refusing to rollback: operator authorization required "
            "(set MIRA_HAND_AUTHORIZED=1 or pass "
            "--mira-hand-authorized).\n"
        )
        return 1

    apply_patch(args.repo, payload, gh_path=args.gh_path)
    stdout.write(
        f"PATCH applied (rollback): {args.repo}/main "
        f"required_status_checks.contexts restored.\n"
    )
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point. Returns process exit code."""
    parser = _build_argparser()
    args = parser.parse_args(argv)
    stdout = sys.stdout

    # Default-mode resolution: if neither --apply nor --rollback,
    # treat as --dry-run.
    if args.rollback is not None:
        return _run_rollback(args, stdout=stdout)
    if args.apply:
        return _run_dry_or_apply(args, apply=True, stdout=stdout)
    return _run_dry_or_apply(args, apply=False, stdout=stdout)


if __name__ == "__main__":
    sys.exit(main())
