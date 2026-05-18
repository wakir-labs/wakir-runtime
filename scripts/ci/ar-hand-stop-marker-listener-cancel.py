#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""AR-Hand-Stop-Marker Listener — Cancel-Step.

For each workflow filename in the three target lists, query the
GitHub Actions API for in-flight runs (``status in {queued,
in_progress, waiting}``) and cancel them via ``gh api`` POST to
``/repos/<owner>/<repo>/actions/runs/<run-id>/cancel``.

GitHub-Auth
-----------

``gh`` reads ``GH_TOKEN`` from the environment (the workflow sets
this to ``${{ secrets.GITHUB_TOKEN }}``). The token has
``actions: write`` per the workflow's permissions block, which is
the minimum scope needed for ``POST /actions/runs/*/cancel``.

Idempotency
-----------

If a run is already in a terminal state when we try to cancel it,
``gh api`` exits non-zero. The script treats 409 (conflict —
already terminal) as success and logs all other failures
without aborting the cascade.

Test-mode
---------

When invoked with ``--gh-binary /path/to/echo``, the script logs
the gh-invocations instead of running them. This is the hook
used by the hermetic test-suite.

Sandbox-Boundary
----------------

Stdlib + subprocess. The gh-binary is the only external surface;
the test-suite substitutes it with a stub.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys


# ---------------------------------------------------------------------------
# gh wrappers.
# ---------------------------------------------------------------------------


def gh_list_in_flight_runs(
    *,
    workflow_filename: str,
    gh_repo: str,
    gh_binary: str,
) -> list[dict[str, object]]:
    """Return the list of (id, status, name) for in-flight runs."""

    runs: list[dict[str, object]] = []
    for status in ("queued", "in_progress", "waiting"):
        endpoint = (
            f"/repos/{gh_repo}/actions/workflows/"
            f"{workflow_filename}/runs?status={status}&per_page=100"
        )
        cmd = [gh_binary, "api", endpoint]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                env=os.environ,
            )
        except subprocess.CalledProcessError as exc:
            print(
                f"WARN: gh list-runs failed for "
                f"{workflow_filename!r} status={status}: "
                f"rc={exc.returncode} stderr={exc.stderr.strip()}",
                file=sys.stderr,
            )
            continue
        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            print(
                f"WARN: gh list-runs returned non-JSON for "
                f"{workflow_filename!r} status={status}: {exc}",
                file=sys.stderr,
            )
            continue
        for run in payload.get("workflow_runs", []) or []:
            runs.append(
                {
                    "id": run.get("id"),
                    "status": run.get("status"),
                    "name": run.get("name") or workflow_filename,
                    "workflow_filename": workflow_filename,
                }
            )
    return runs


def gh_cancel_run(
    *,
    run_id: int,
    gh_repo: str,
    gh_binary: str,
) -> bool:
    """POST to /actions/runs/<id>/cancel. Returns True on success."""

    cmd = [
        gh_binary,
        "api",
        "-X",
        "POST",
        f"/repos/{gh_repo}/actions/runs/{run_id}/cancel",
    ]
    try:
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            env=os.environ,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        if "409" in stderr or "already" in stderr.lower():
            print(
                f"INFO: run {run_id} already terminal; "
                f"treating as success",
                file=sys.stderr,
            )
            return True
        print(
            f"WARN: gh cancel failed for run-id {run_id}: "
            f"rc={exc.returncode} stderr={stderr}",
            file=sys.stderr,
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Driver.
# ---------------------------------------------------------------------------


def cancel_target_list(
    *,
    targets: list[str],
    gh_repo: str,
    gh_binary: str,
    label: str,
) -> tuple[int, int]:
    """Returns (runs_seen, runs_cancelled) across the target list."""

    seen = 0
    cancelled = 0
    for workflow_filename in targets:
        runs = gh_list_in_flight_runs(
            workflow_filename=workflow_filename,
            gh_repo=gh_repo,
            gh_binary=gh_binary,
        )
        for run in runs:
            seen += 1
            run_id = run.get("id")
            if not isinstance(run_id, int):
                continue
            ok = gh_cancel_run(
                run_id=run_id,
                gh_repo=gh_repo,
                gh_binary=gh_binary,
            )
            if ok:
                cancelled += 1
                print(
                    f"CANCELLED [{label}] workflow={workflow_filename} "
                    f"run-id={run_id} status={run.get('status')}"
                )
    return seen, cancelled


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="ar-hand-stop-marker-listener-cancel")
    p.add_argument("--welle-targets", required=True)
    p.add_argument("--cascade-targets", required=True)
    p.add_argument("--marathon-targets", required=True)
    p.add_argument("--gh-repo", required=True)
    p.add_argument(
        "--gh-binary",
        default="",
        help="Override gh-binary path (test-hook).",
    )
    return p.parse_args(argv)


def _decode_targets(raw: str) -> list[str]:
    try:
        return list(json.loads(raw))
    except json.JSONDecodeError as exc:
        raise ValueError(f"target list must be JSON: {raw!r} ({exc})")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    gh_binary = args.gh_binary or shutil.which("gh") or "gh"
    welle_targets = _decode_targets(args.welle_targets)
    cascade_targets = _decode_targets(args.cascade_targets)
    marathon_targets = _decode_targets(args.marathon_targets)

    total_seen, total_cancelled = 0, 0
    for label, targets in (
        ("welle", welle_targets),
        ("cascade", cascade_targets),
        ("marathon", marathon_targets),
    ):
        seen, cancelled = cancel_target_list(
            targets=targets,
            gh_repo=args.gh_repo,
            gh_binary=gh_binary,
            label=label,
        )
        total_seen += seen
        total_cancelled += cancelled
        print(f"summary [{label}] runs-seen={seen} cancelled={cancelled}")

    print(
        f"TOTAL runs-seen={total_seen} cancelled={total_cancelled} "
        f"failed={total_seen - total_cancelled}"
    )
    # Always exit-0; the verdict-step records the failed-count.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
