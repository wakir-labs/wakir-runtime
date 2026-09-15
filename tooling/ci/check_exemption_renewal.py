#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Moving a review date is a renewal, and a renewal has an author.

The other half of ADR-0075 §3
-----------------------------

``tooling/ci/exemption_expiry.py`` compares every exemption date against
the calendar. That alone leaves one way out, and it is the comfortable
one: on the morning the lane goes red, edit the date. One character, no
reason, no author, and the exemption is back for another six weeks. The
ADR anticipates exactly that and answers it:

    Renewal is allowed and requires ``renewed_on`` and
    ``renewal_reason`` — which replaces silent lapse with a visible
    decision that has an author.

A hermetic test cannot enforce that, because it cannot see what the date
used to be. This check can: on a pull request it reads the base commit's
version of the file and compares the two. A ``review_by`` that moved
without ``renewed_on`` moving with it is refused.

It is intentionally narrow. It does not judge whether the renewal is
*wise* — that is what review is for. It only refuses the version of the
act that leaves no trace.

Usage::

    python tooling/ci/check_exemption_renewal.py --base-ref <sha>

Outside a pull request (no base ref) the check reports "nothing to
compare" and exits 0.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSIGNMENT_REL = "tests/lanes/lane_assignment.json"
MIN_RENEWAL_REASON = 60


def _git(args: list[str], repo_root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


def read_base_version(base_ref: str, repo_root: Path = REPO_ROOT) -> dict | None:
    """The base commit's assignment document, or ``None`` if unreachable.

    Unreachable is not the same as unchanged, and the difference matters:
    a shallow clone that cannot see the base commit must say so rather
    than report "no renewal happened".
    """
    show = _git(["show", f"{base_ref}:{ASSIGNMENT_REL}"], repo_root)
    if show.returncode != 0:
        fetch = _git(
            ["fetch", "--no-tags", "--depth=1", "origin", base_ref], repo_root
        )
        if fetch.returncode != 0:
            return None
        show = _git(["show", f"{base_ref}:{ASSIGNMENT_REL}"], repo_root)
        if show.returncode != 0:
            return None
    return json.loads(show.stdout)


def renewal_problems(base: dict, head: dict) -> list[str]:
    """Groups whose review date moved without a dated, reasoned renewal."""
    base_groups = base.get("exemption_groups", {})
    head_groups = head.get("exemption_groups", {})
    problems: list[str] = []

    for name, head_group in sorted(head_groups.items()):
        base_group = base_groups.get(name)
        if base_group is None:
            continue  # a new group sets its first date; nothing was renewed
        before = base_group.get("review_by")
        after = head_group.get("review_by")
        if before == after:
            continue

        renewed_before = base_group.get("renewed_on")
        renewed_after = head_group.get("renewed_on")
        reason = str(head_group.get("renewal_reason", "")).strip()

        if not renewed_after or renewed_after == renewed_before:
            problems.append(
                f"{name}: review_by moved {before} -> {after} without "
                "setting `renewed_on` to the date of this decision. "
                "ADR-0075 §3: renewal is allowed, silent extension is not."
            )
            continue
        if len(reason) < MIN_RENEWAL_REASON:
            problems.append(
                f"{name}: review_by moved {before} -> {after} and "
                f"`renewal_reason` is {len(reason)} characters. Write why "
                "the exemption is still true — the reason is the part that "
                "makes this a decision rather than a date edit."
            )
            continue
        if reason == str(base_group.get("renewal_reason", "")).strip():
            problems.append(
                f"{name}: review_by moved {before} -> {after} but "
                "`renewal_reason` is the text from the previous renewal. "
                "A new decision needs its own reason."
            )
    return problems


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-ref",
        default="",
        help="commit to compare against (the pull request's base SHA)",
    )
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument(
        "--require-base",
        action="store_true",
        help=(
            "fail when the base version cannot be read instead of passing. "
            "Use this in a lane that is supposed to always have a base — a "
            "check that silently becomes a no-op is the thing being fixed."
        ),
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    if not args.base_ref:
        print("no base ref given (not a pull request) — nothing to compare")
        return 0

    base = read_base_version(args.base_ref, repo_root)
    if base is None:
        message = (
            f"could not read {ASSIGNMENT_REL} at {args.base_ref}; the renewal "
            "check did not run"
        )
        if args.require_base:
            print(message, file=sys.stderr)
            return 1
        print(message)
        return 0

    head = json.loads((repo_root / ASSIGNMENT_REL).read_text(encoding="utf-8"))
    problems = renewal_problems(base, head)
    if problems:
        print(
            "exemption review dates changed without a recorded renewal:",
            file=sys.stderr,
        )
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    print(f"exemption renewal check ok against {args.base_ref}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
