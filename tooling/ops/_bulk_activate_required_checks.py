#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Tag-62 Bulk-Activation Pre-Walk Recipe — Planner Helper.

Hermetic, stdlib-only. Parses the Tag-59 + Tag-61 Branch-Protection
Required-Check Wiring Docs to extract the 7-Pool target list, then
emits one of three output forms:

  * default            human-readable plan (used by --dry-run)
  * --json             machine-readable plan envelope
  * --put-payload      raw required_status_checks JSON block for
                       gh api -X PUT (used by the shell wrapper's
                       --enforce path)

The planner does NOT touch GitHub. It is pure parse + render. The
shell wrapper around it (`bulk_activate_required_checks.sh`) is
responsible for sandbox-boundary detection + gh-CLI invocation.

Exit codes
==========

  0   plan parsed cleanly, 7-Pool target set assembled
  1   plan inconsistent: doc parse error, count mismatch, duplicate
      display-name, or empty display-name
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Tuple


# Expected pool size. Tag-59 contributes 5 checks; Tag-61 adds 2.
EXPECTED_TAG59_COUNT = 5
EXPECTED_TAG61_COUNT = 2
EXPECTED_POOL_TOTAL = EXPECTED_TAG59_COUNT + EXPECTED_TAG61_COUNT

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
        if idx < EXPECTED_TAG59_COUNT + 1 or idx > EXPECTED_POOL_TOTAL:
            continue
        rows.append((idx, match.group("name"), match.group("wf")))
        if len(rows) == EXPECTED_TAG61_COUNT:
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


def assemble_pool(tag59_doc: Path, tag61_doc: Path):
    tag59_text = _read_text(tag59_doc)
    tag61_text = _read_text(tag61_doc)

    tag59_rows = parse_tag59_doc(tag59_text)
    tag61_rows = parse_tag61_addendum(tag61_text)
    pool_bilanz = parse_pool_bilanz(tag61_text)

    errors = []
    if len(tag59_rows) != EXPECTED_TAG59_COUNT:
        errors.append(
            f"Tag-59 §1 row count: got {len(tag59_rows)}, expected {EXPECTED_TAG59_COUNT}"
        )
    if len(tag61_rows) != EXPECTED_TAG61_COUNT:
        errors.append(
            f"Tag-61 §1 row count: got {len(tag61_rows)}, expected {EXPECTED_TAG61_COUNT}"
        )
    if len(pool_bilanz) != EXPECTED_POOL_TOTAL:
        errors.append(
            f"Tag-61 §1 Gesamt-Pool-Bilanz row count: got {len(pool_bilanz)}, "
            f"expected {EXPECTED_POOL_TOTAL}"
        )

    combined = tag59_rows + tag61_rows
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


def render_plan_human(combined, pool_bilanz, errors) -> str:
    lines = []
    lines.append("# Tag-62 Bulk-Activation Pre-Walk Plan")
    lines.append("")
    lines.append(f"target pool size: {EXPECTED_POOL_TOTAL}")
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


def render_plan_json(combined, pool_bilanz, errors) -> str:
    contexts = [name for (_, name, _) in combined]
    envelope = {
        "tag": "tag-62",
        "schema": "bulk-activate-required-checks/plan/v1",
        "target_pool_size": EXPECTED_POOL_TOTAL,
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
        "--json", action="store_true", help="Emit machine-readable JSON envelope"
    )
    parser.add_argument(
        "--put-payload",
        action="store_true",
        help="Emit raw required_status_checks PUT payload (for shell wrapper)",
    )
    args = parser.parse_args(argv)

    combined, pool_bilanz, errors = assemble_pool(args.tag59_doc, args.tag61_doc)

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
        print(render_plan_json(combined, pool_bilanz, errors))
    else:
        print(render_plan_human(combined, pool_bilanz, errors))

    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
