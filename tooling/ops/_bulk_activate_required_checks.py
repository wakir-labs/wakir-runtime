#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Tag-62 Bulk-Activation Pre-Walk Recipe — Planner Helper.

Hermetic, stdlib-only. Parses the Tag-59 + Tag-61 Branch-Protection
Required-Check Wiring Docs to extract the 7-Pool target list (Tag-62-
lineage), or — when --tag64-doc is supplied — parses additionally the
Tag-64 Companion doc to extract the 8-Pool target list (Tag-64 E2E-
verdict added). Without --tag64-doc the planner falls back to the
7-Pool behaviour, preserving Kai's Tag-62 walking-skeleton path
byte-identically.

It then emits one of three output forms:

  * default            human-readable plan (used by --dry-run)
  * --json             machine-readable plan envelope
  * --put-payload      raw required_status_checks JSON block for
                       gh api -X PUT (used by the shell wrapper's
                       --enforce path)
  * --mock-api-mode    Tag-63 Walking-Skeleton mode: reads a JSON
                       pre-snapshot fixture from --mock-pre-snapshot,
                       computes a post-snapshot by full-replace
                       semantics (PUT semantics of the GitHub
                       branch-protection API), and emits the
                       post-snapshot to --mock-post-snapshot.
                       Touches NO network. Sandbox-boundary safe.
  * --post-activate-verify
                       Tag-65 Post-Activate-Verify mode: reads a JSON
                       post-activate snapshot fixture from
                       --post-activate-snapshot (i.e. the hypothetical
                       branch-protection state AFTER the bulk
                       activation has run), and verifies — without
                       network — that all expected Required-Status-
                       Checks for the configured pool (7 or 8) are
                       registered verbatim and that `strict=true`
                       holds. Emits a verify-report (human or JSON
                       per --json) and a non-zero exit on any
                       discrepancy. Used by the Tag-65 walking-
                       skeleton Stage-5 post-activate verifier.

The planner does NOT touch GitHub. It is pure parse + render. The
shell wrapper around it (`bulk_activate_required_checks.sh`) is
responsible for sandbox-boundary detection + gh-CLI invocation.

Exit codes
==========

  0   plan parsed cleanly, 7-Pool target set assembled
      (or, in --mock-api-mode: mock post-snapshot written cleanly,
       or, in --post-activate-verify: snapshot verified clean)
  1   plan inconsistent: doc parse error, count mismatch, duplicate
      display-name, or empty display-name
      (or, in --post-activate-verify: missing/extra/unstrict context)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Tuple


# Expected pool size. Tag-59 contributes 5 checks; Tag-61 adds 2;
# Tag-64 adds 1 additional check (E2E verdict). The Tag-64 doc is
# OPTIONAL — without --tag64-doc the planner falls back to the
# Tag-62-lineage 7-Pool behaviour, preserving Kai's Tag-62 walking-
# skeleton path. With --tag64-doc the planner emits the 8-Pool.
EXPECTED_TAG59_COUNT = 5
EXPECTED_TAG61_COUNT = 2
EXPECTED_TAG64_COUNT = 1
EXPECTED_POOL_TOTAL_7 = EXPECTED_TAG59_COUNT + EXPECTED_TAG61_COUNT
EXPECTED_POOL_TOTAL_8 = EXPECTED_POOL_TOTAL_7 + EXPECTED_TAG64_COUNT
# Back-compat alias: existing call sites referencing EXPECTED_POOL_TOTAL
# (e.g. Tag-63 walking-skeleton tests) keep working unchanged.
EXPECTED_POOL_TOTAL = EXPECTED_POOL_TOTAL_7

# Regex for table rows of shape:
#   | # | `display-name` | `.github/workflows/file.yml` | ... |
# captures (row-number, display-name, workflow-file).
_ROW_RE = re.compile(
    r"^\|\s*(?P<idx>\d+)\s*\|\s*`(?P<name>[^`]+)`\s*\|"
    r"\s*`(?P<wf>\.github/workflows/[^`]+)`\s*\|",
    re.MULTILINE,
)

# Regex for the Tag-61 §1 Gesamt-Pool-Bilanz table row shape:
#   | <pool-slot> | `display-name` | <activation-status> | <tag-quelle> |
_POOL_BILANZ_RE = re.compile(
    r"^\|\s*(?P<slot>\d+)\s*\|\s*`(?P<name>[^`]+)`\s*\|"
    r"\s*(?P<status>[A-Z][A-Z0-9-]+(?:-[A-Z0-9-]+)*)\s*\|"
    r"\s*(?P<src>Tag-\d+|\*\*Tag-\d+\*\*)\s*\|",
    re.MULTILINE,
)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SystemExit(f"missing doc: {path} ({exc})") from exc


def parse_tag59_doc(text: str) -> List[Tuple[int, str, str]]:
    """Return [(idx, display-name, workflow-file), ...] for Tag-59 §1.

    Tag-59 §1 has exactly 5 rows (rows 1..5).
    """
    rows = []
    for match in _ROW_RE.finditer(text):
        idx = int(match.group("idx"))
        if idx > EXPECTED_TAG59_COUNT:
            # Tag-59 doc only carries rows 1..5 in §1; defensive
            # break in case the doc later grows.
            continue
        rows.append((idx, match.group("name"), match.group("wf")))
        if len(rows) == EXPECTED_TAG59_COUNT:
            break
    return rows


def parse_tag61_addendum(text: str) -> List[Tuple[int, str, str]]:
    """Return [(idx, display-name, workflow-file), ...] for Tag-61 §1.

    Tag-61 §1 Addendum-Tabelle has exactly 2 rows (rows 6..7).
    """
    rows = []
    for match in _ROW_RE.finditer(text):
        idx = int(match.group("idx"))
        if idx < EXPECTED_TAG59_COUNT + 1 or idx > EXPECTED_POOL_TOTAL_7:
            continue
        rows.append((idx, match.group("name"), match.group("wf")))
        if len(rows) == EXPECTED_TAG61_COUNT:
            break
    return rows


def parse_tag64_companion(text: str) -> List[Tuple[int, str, str]]:
    """Return [(idx, display-name, workflow-file), ...] for Tag-64 §1.

    Tag-64 §1 Companion-Tabelle has exactly 1 row (row 8). The Tag-64
    parser is additive: if the doc is absent, callers fall back to
    the Tag-62-lineage 7-Pool. Idempotency-disciplined per
    `feedback_high_tempo_spawn_collision`.
    """
    rows = []
    for match in _ROW_RE.finditer(text):
        idx = int(match.group("idx"))
        if idx < EXPECTED_POOL_TOTAL_7 + 1 or idx > EXPECTED_POOL_TOTAL_8:
            continue
        rows.append((idx, match.group("name"), match.group("wf")))
        if len(rows) == EXPECTED_TAG64_COUNT:
            break
    return rows


def parse_pool_bilanz(text: str) -> List[Tuple[int, str, str, str]]:
    """Return [(slot, name, status, src), ...] for Tag-61 §1 bilanz table."""
    rows = []
    for match in _POOL_BILANZ_RE.finditer(text):
        slot = int(match.group("slot"))
        rows.append(
            (slot, match.group("name"), match.group("status"), match.group("src"))
        )
    return rows


def assemble_pool(tag59_doc: Path, tag61_doc: Path, tag64_doc: Path = None):
    """Assemble the Required-Status-Check pool.

    Without ``tag64_doc``: 7-Pool (Tag-62-lineage; Kai walking-skeleton
    compatibility). With ``tag64_doc``: 8-Pool (Tag-64 Companion).
    """
    tag59_text = _read_text(tag59_doc)
    tag61_text = _read_text(tag61_doc)

    tag59_rows = parse_tag59_doc(tag59_text)
    tag61_rows = parse_tag61_addendum(tag61_text)

    if tag64_doc is not None:
        tag64_text = _read_text(tag64_doc)
        tag64_rows = parse_tag64_companion(tag64_text)
        # In 8-Pool mode the Gesamt-Pool-Bilanz lives in the Tag-64 doc.
        pool_bilanz = parse_pool_bilanz(tag64_text)
        expected_total = EXPECTED_POOL_TOTAL_8
        bilanz_source_label = "Tag-64 §1 Gesamt-Pool-Bilanz"
    else:
        tag64_rows = []
        # 7-Pool mode: bilanz from Tag-61 doc, unchanged from Tag-62.
        pool_bilanz = parse_pool_bilanz(tag61_text)
        expected_total = EXPECTED_POOL_TOTAL_7
        bilanz_source_label = "Tag-61 §1 Gesamt-Pool-Bilanz"

    errors = []
    if len(tag59_rows) != EXPECTED_TAG59_COUNT:
        errors.append(
            f"Tag-59 §1 row count: got {len(tag59_rows)}, expected {EXPECTED_TAG59_COUNT}"
        )
    if len(tag61_rows) != EXPECTED_TAG61_COUNT:
        errors.append(
            f"Tag-61 §1 row count: got {len(tag61_rows)}, expected {EXPECTED_TAG61_COUNT}"
        )
    if tag64_doc is not None and len(tag64_rows) != EXPECTED_TAG64_COUNT:
        errors.append(
            f"Tag-64 §1 row count: got {len(tag64_rows)}, expected {EXPECTED_TAG64_COUNT}"
        )
    if len(pool_bilanz) != expected_total:
        errors.append(
            f"{bilanz_source_label} row count: got {len(pool_bilanz)}, "
            f"expected {expected_total}"
        )

    combined = tag59_rows + tag61_rows + tag64_rows
    names = [name for (_, name, _) in combined]

    # Duplicate detection
    seen = {}
    for idx, name, _ in combined:
        if name in seen:
            errors.append(
                f"duplicate display-name at row {idx}: '{name}' "
                f"(first seen row {seen[name]})"
            )
        else:
            seen[name] = idx

    # Empty-name detection
    for idx, name, _ in combined:
        if not name.strip():
            errors.append(f"empty display-name at row {idx}")

    # Pool-bilanz must agree with combined names (set-equality).
    bilanz_names = {name for (_, name, _, _) in pool_bilanz}
    combined_set = set(names)
    if bilanz_names != combined_set:
        only_in_bilanz = bilanz_names - combined_set
        only_in_combined = combined_set - bilanz_names
        if only_in_bilanz:
            errors.append(
                f"display-names in Pool-Bilanz only: {sorted(only_in_bilanz)}"
            )
        if only_in_combined:
            errors.append(
                f"display-names in §1 tables only: {sorted(only_in_combined)}"
            )

    return combined, pool_bilanz, errors


def render_plan_human(combined, pool_bilanz, errors, target_total=None) -> str:
    if target_total is None:
        target_total = EXPECTED_POOL_TOTAL_7
    plan_label = "Tag-64" if target_total == EXPECTED_POOL_TOTAL_8 else "Tag-62"
    lines = []
    lines.append(f"# {plan_label} Bulk-Activation Pre-Walk Plan")
    lines.append("")
    lines.append(f"target pool size: {target_total}")
    lines.append(f"parsed combined  : {len(combined)}")
    lines.append(f"parsed bilanz    : {len(pool_bilanz)}")
    lines.append("")
    lines.append("## Required-Status-Check contexts (verbatim, in pool order)")
    lines.append("")
    for idx, name, wf in combined:
        lines.append(f"  {idx}. {name}")
        lines.append(f"     workflow: {wf}")
    lines.append("")
    lines.append("## Planned PUT call shape")
    lines.append("")
    lines.append("  endpoint: PUT repos/wakir-labs/wakir-runtime/branches/main/protection")
    lines.append("  payload : { required_status_checks: { strict: true, contexts: [...] } }")
    lines.append("  contexts: " + str(len(combined)) + " entries (see above)")
    lines.append("")
    lines.append("## Idempotency note")
    lines.append("")
    lines.append("  GitHub branch-protection PUT is full-replace. The Operator")
    lines.append("  must take a pre-snapshot via gh api .../protection --jq")
    lines.append("  '.required_status_checks.contexts' BEFORE issuing the PUT,")
    lines.append("  and diff against the post-snapshot AFTER. The planner")
    lines.append("  cannot fetch the live state from inside the sandbox.")
    lines.append("")
    if errors:
        lines.append("## Errors")
        lines.append("")
        for err in errors:
            lines.append(f"  - {err}")
        lines.append("")
        lines.append("verdict: BULK-ACTIVATION-DEFECT")
    else:
        lines.append("verdict: PLAN-CONSISTENT")
    return "\n".join(lines)


def render_plan_json(combined, pool_bilanz, errors, target_total=None) -> str:
    if target_total is None:
        target_total = EXPECTED_POOL_TOTAL_7
    tag_label = "tag-64" if target_total == EXPECTED_POOL_TOTAL_8 else "tag-62"
    contexts = [name for (_, name, _) in combined]
    envelope = {
        "tag": tag_label,
        "schema": "bulk-activate-required-checks/plan/v1",
        "target_pool_size": target_total,
        "parsed_combined_count": len(combined),
        "parsed_pool_bilanz_count": len(pool_bilanz),
        "endpoint": "PUT repos/wakir-labs/wakir-runtime/branches/main/protection",
        "required_status_checks": {
            "strict": True,
            "contexts": contexts,
        },
        "errors": errors,
        "verdict": "PLAN-CONSISTENT" if not errors else "BULK-ACTIVATION-DEFECT",
    }
    return json.dumps(envelope, indent=2, sort_keys=False, ensure_ascii=False)


def render_put_payload(combined) -> str:
    contexts = [name for (_, name, _) in combined]
    payload = {
        "required_status_checks": {
            "strict": True,
            "contexts": contexts,
        },
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _read_snapshot(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SystemExit(
            f"--mock-api-mode: missing pre-snapshot fixture: {path} ({exc})"
        ) from exc
    try:
        snap = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"--mock-api-mode: invalid JSON in pre-snapshot {path}: {exc}"
        ) from exc
    if not isinstance(snap, dict):
        raise SystemExit(
            f"--mock-api-mode: pre-snapshot must be a JSON object: {path}"
        )
    rsc = snap.get("required_status_checks")
    if not isinstance(rsc, dict):
        raise SystemExit(
            f"--mock-api-mode: pre-snapshot missing required_status_checks: {path}"
        )
    if "contexts" not in rsc or not isinstance(rsc["contexts"], list):
        raise SystemExit(
            f"--mock-api-mode: pre-snapshot missing required_status_checks.contexts list: {path}"
        )
    return snap


def render_mock_post_snapshot(combined, pre_snapshot: dict) -> dict:
    """Simulate the GitHub branch-protection PUT (full-replace).

    The mock applies the target pool as the new full
    `required_status_checks` block, preserving the `branch` and
    fixture metadata fields when present so the post-snapshot is
    byte-identical to the expected fixture.

    Pool-size aware: emits ``Tag-63``-shape description when pool is
    7, ``Tag-64``-shape description when pool is 8. The Tag-63
    walking-skeleton expected fixture lives at
    ``tests/observability/fixtures/branch-protection-walking-
    skeleton/expected-post-snapshot.json`` (unchanged); the Tag-64
    fixture lives at the parallel ``-tag64/`` directory.
    """
    contexts = [name for (_, name, _) in combined]
    pool_size = len(contexts)
    if pool_size == EXPECTED_POOL_TOTAL_8:
        description = (
            "Tag-64 Walking-Skeleton fixture — expected post-snapshot. "
            "Represents the GitHub branch-protection state for "
            "wakir-labs/wakir-runtime main AFTER the Tag-64 bulk-"
            "activation pre-walk pipeline has run, with all 8 "
            "Required-Status-Checks wired (Tag-59 5 + Tag-61 2 + "
            "Tag-64 1). Byte-identical equality check against this "
            "fixture is the Tag-64 walking-skeleton acceptance gate."
        )
    else:
        description = (
            "Tag-63 Walking-Skeleton fixture — expected post-snapshot. "
            "Represents the GitHub branch-protection state for "
            "wakir-labs/wakir-runtime main AFTER the bulk-activation "
            "pre-walk pipeline has run, with all 7 Required-Status-"
            "Checks wired. Byte-identical equality check against this "
            "fixture is the walking-skeleton acceptance gate."
        )
    post = {
        "_fixture_description": description,
        "_fixture_id": "expected-post-snapshot",
        "branch": pre_snapshot.get("branch", "main"),
        "required_status_checks": {
            "strict": True,
            "contexts": contexts,
        },
    }
    return post


def verify_post_activate_snapshot(combined, snapshot: dict) -> Tuple[List[str], dict]:
    """Tag-65 Post-Activate-Verify mode.

    Compares a post-activate snapshot against the assembled pool and
    returns ``(discrepancies, report)``. A clean snapshot yields an
    empty ``discrepancies`` list. The report is a structured envelope
    suitable for the Tag-65 walking-skeleton Stage-5 emitter.

    Verification invariants (load-bearing):

      1. ``required_status_checks`` block present.
      2. ``strict`` is True (full GitHub branch-protection contract).
      3. ``contexts`` is a list.
      4. Every expected pool context appears verbatim in the snapshot
         (missing-context detection).
      5. No EXTRA context appears in the snapshot beyond the expected
         pool (extra-context detection — guards against leftover
         pre-existing required-checks that the bulk-activation PUT
         should have swept away).
      6. Order-equality: the snapshot context order matches the pool
         order. The bulk-activation PUT writes contexts in pool
         order; drift here means either a manual edit or a planner
         bug. Order-equality is a Tag-65 acceptance criterion.

    All discrepancies are accumulated; the function does NOT
    short-circuit. The caller renders the full discrepancy list so
    the Operator can fix all defects in one round-trip.
    """
    expected_contexts = [name for (_, name, _) in combined]
    discrepancies: List[str] = []

    if not isinstance(snapshot, dict):
        discrepancies.append("post-activate snapshot must be a JSON object")
        return discrepancies, {
            "tag": "tag-65",
            "schema": "bulk-activate-required-checks/post-activate-verify/v1",
            "expected_pool_size": len(expected_contexts),
            "expected_contexts": expected_contexts,
            "observed_contexts": [],
            "observed_strict": None,
            "discrepancies": discrepancies,
            "verdict": "POST-ACTIVATE-DEFECT",
        }

    rsc = snapshot.get("required_status_checks")
    observed_contexts: List[str] = []
    observed_strict = None
    if not isinstance(rsc, dict):
        discrepancies.append(
            "post-activate snapshot missing required_status_checks block"
        )
    else:
        observed_strict = rsc.get("strict")
        if observed_strict is not True:
            discrepancies.append(
                f"required_status_checks.strict is not True (got {observed_strict!r})"
            )
        ctxs = rsc.get("contexts")
        if not isinstance(ctxs, list):
            discrepancies.append(
                "required_status_checks.contexts is not a list"
            )
        else:
            observed_contexts = list(ctxs)
            expected_set = set(expected_contexts)
            observed_set = set(observed_contexts)
            missing = expected_set - observed_set
            extra = observed_set - expected_set
            for name in sorted(missing):
                discrepancies.append(f"missing required-check context: '{name}'")
            for name in sorted(extra):
                discrepancies.append(f"extra (unexpected) context registered: '{name}'")
            # Order-equality is checked only when the sets match — an
            # order-violation message is meaningless if there are also
            # missing/extra contexts (set-mismatch dominates).
            if not missing and not extra and observed_contexts != expected_contexts:
                discrepancies.append(
                    "context order mismatch: snapshot order does not equal "
                    "pool order"
                )

    report = {
        "tag": "tag-65",
        "schema": "bulk-activate-required-checks/post-activate-verify/v1",
        "expected_pool_size": len(expected_contexts),
        "expected_contexts": expected_contexts,
        "observed_contexts": observed_contexts,
        "observed_strict": observed_strict,
        "discrepancies": discrepancies,
        "verdict": "POST-ACTIVATE-CLEAN" if not discrepancies else "POST-ACTIVATE-DEFECT",
    }
    return discrepancies, report


def render_verify_report_human(report: dict) -> str:
    lines = []
    lines.append("# Tag-65 Post-Activate-Verify Report")
    lines.append("")
    lines.append(f"expected pool size : {report['expected_pool_size']}")
    lines.append(f"observed contexts  : {len(report['observed_contexts'])}")
    lines.append(f"observed strict    : {report['observed_strict']}")
    lines.append("")
    lines.append("## Expected pool order")
    lines.append("")
    for i, name in enumerate(report["expected_contexts"], start=1):
        lines.append(f"  {i}. {name}")
    lines.append("")
    if report["discrepancies"]:
        lines.append("## Discrepancies")
        lines.append("")
        for d in report["discrepancies"]:
            lines.append(f"  - {d}")
        lines.append("")
        lines.append(f"verdict: {report['verdict']}")
    else:
        lines.append(f"verdict: {report['verdict']}")
    return "\n".join(lines)


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Tag-62 bulk-activation planner (stdlib-only, hermetic)"
    )
    parser.add_argument(
        "--tag59-doc",
        type=Path,
        required=True,
        help="Path to Tag-59 wiring doc",
    )
    parser.add_argument(
        "--tag61-doc",
        type=Path,
        required=True,
        help="Path to Tag-61 addendum doc",
    )
    parser.add_argument(
        "--tag64-doc",
        type=Path,
        default=None,
        help=(
            "Path to Tag-64 companion doc (OPTIONAL). When supplied, "
            "the planner emits the 8-Pool target set. When absent, the "
            "planner falls back to the Tag-62-lineage 7-Pool (Kai "
            "walking-skeleton compatibility preserved)."
        ),
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON envelope"
    )
    parser.add_argument(
        "--put-payload",
        action="store_true",
        help="Emit raw required_status_checks PUT payload (for shell wrapper)",
    )
    parser.add_argument(
        "--mock-api-mode",
        action="store_true",
        help=(
            "Tag-63 Walking-Skeleton mode: read pre-snapshot from "
            "--mock-pre-snapshot, write post-snapshot to "
            "--mock-post-snapshot. Sandbox-boundary safe (no network)."
        ),
    )
    parser.add_argument(
        "--mock-pre-snapshot",
        type=Path,
        default=None,
        help="Pre-snapshot JSON fixture path (for --mock-api-mode)",
    )
    parser.add_argument(
        "--mock-post-snapshot",
        type=Path,
        default=None,
        help="Output path for the simulated post-snapshot (for --mock-api-mode)",
    )
    parser.add_argument(
        "--post-activate-verify",
        action="store_true",
        help=(
            "Tag-65 Post-Activate-Verify mode: read post-activate "
            "snapshot from --post-activate-snapshot and verify all "
            "expected required-checks are registered (verbatim, in "
            "pool order, with strict=true). No network. Sandbox-"
            "boundary safe."
        ),
    )
    parser.add_argument(
        "--post-activate-snapshot",
        type=Path,
        default=None,
        help="Post-activate snapshot JSON fixture (for --post-activate-verify)",
    )
    args = parser.parse_args(argv)

    combined, pool_bilanz, errors = assemble_pool(
        args.tag59_doc, args.tag61_doc, args.tag64_doc
    )
    target_total = (
        EXPECTED_POOL_TOTAL_8 if args.tag64_doc is not None else EXPECTED_POOL_TOTAL_7
    )

    if args.mock_api_mode:
        if errors:
            print(
                "REFUSED: --mock-api-mode requested but plan is inconsistent:",
                file=sys.stderr,
            )
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            return 1
        if args.mock_pre_snapshot is None or args.mock_post_snapshot is None:
            print(
                "REFUSED: --mock-api-mode requires --mock-pre-snapshot and "
                "--mock-post-snapshot",
                file=sys.stderr,
            )
            return 1
        pre = _read_snapshot(args.mock_pre_snapshot)
        post = render_mock_post_snapshot(combined, pre)
        # Trailing newline keeps the file POSIX-clean and matches the
        # expected fixture's trailing-newline shape, which is required
        # for the Stage-3 byte-identical equality check.
        args.mock_post_snapshot.write_text(
            json.dumps(post, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(
            f"MOCK-API-MODE: wrote post-snapshot to {args.mock_post_snapshot} "
            f"({len(combined)} contexts, pre had "
            f"{len(pre['required_status_checks']['contexts'])})"
        )
        return 0

    if args.post_activate_verify:
        if errors:
            print(
                "REFUSED: --post-activate-verify requested but plan is inconsistent:",
                file=sys.stderr,
            )
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            return 1
        if args.post_activate_snapshot is None:
            print(
                "REFUSED: --post-activate-verify requires --post-activate-snapshot",
                file=sys.stderr,
            )
            return 1
        try:
            snap_text = args.post_activate_snapshot.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            print(
                f"REFUSED: post-activate snapshot not found: "
                f"{args.post_activate_snapshot} ({exc})",
                file=sys.stderr,
            )
            return 1
        try:
            snapshot = json.loads(snap_text)
        except json.JSONDecodeError as exc:
            print(
                f"REFUSED: invalid JSON in post-activate snapshot "
                f"{args.post_activate_snapshot}: {exc}",
                file=sys.stderr,
            )
            return 1
        discrepancies, report = verify_post_activate_snapshot(combined, snapshot)
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            print(render_verify_report_human(report))
        return 0 if not discrepancies else 1

    if args.put_payload:
        if errors:
            print(
                "REFUSED: --put-payload requested but plan is inconsistent:",
                file=sys.stderr,
            )
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            return 1
        print(render_put_payload(combined))
        return 0

    if args.json:
        print(render_plan_json(combined, pool_bilanz, errors, target_total))
    else:
        print(render_plan_human(combined, pool_bilanz, errors, target_total))

    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
