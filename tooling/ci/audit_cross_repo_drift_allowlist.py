#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-60 Cross-Repo-Drift-Allowlist-Audit (Noa).

Pre-Enforce-Flip-Readiness-Substrate. Hermetic, stdlib-only.

This helper consumes:

  * `.cross-repo-drift-allowlist.yaml` (the waiver file, empty by
    design since Tag-31)
  * `.github/workflows/cross-repo-drift-audit.yml` (the mirror-pair
    inventory shipped by PR #105)
  * `docs/operations/cross-repo-drift-enforce-flip-readiness.md`
    (the resolution-strategy ledger, Tag-31 baseline `clean=4, drift=6`)

and emits four artifacts on stdout (JSON-shaped) plus a human-readable
markdown summary on stderr:

  * Stage 1 — Parse: validates allowlist file structure.
  * Stage 2 — Coverage: cross-checks allowlist entries against the
    actual drift inventory recorded in the readiness doc.
  * Stage 3 — Enforce-Flip-Readiness-Score (0-100): blended on
    (a) coverage of resolution-strategies vs. expected pairs,
    (b) drift-trajectory (current clean-count vs. inventory size).
  * Stage 4 — Verdict: ENFORCE-READY (>= 90), ENFORCE-CAUTION (>= 60),
    ENFORCE-BLOCKED (< 60).

Score formula (locked, exposed for tests):

    score = round(60 * coverage_ratio + 40 * trajectory_ratio)

where

    coverage_ratio   = strategies_assigned / drift_count_baseline
                       (1.0 if drift_count_baseline == 0)
    trajectory_ratio = clean_count / total_pairs
                       (1.0 if total_pairs == 0)

Both ratios are clamped to [0.0, 1.0]. Allowlist YAML parser is a
minimal stdlib-only subset (top-level `allow:` sequence with
`runtime`/`protocol`/`reason`/`follow_up` keys). PyYAML is not used:
the workflow runner has it, but tests must run offline without it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Defaults — repo-root relative.
# ---------------------------------------------------------------------------

ALLOWLIST_DEFAULT = ".cross-repo-drift-allowlist.yaml"
WORKFLOW_DEFAULT = ".github/workflows/cross-repo-drift-audit.yml"
READINESS_DOC_DEFAULT = (
    "docs/operations/cross-repo-drift-enforce-flip-readiness.md"
)

# Verdict thresholds (locked; tests pin these).
SCORE_READY_MIN = 90
SCORE_CAUTION_MIN = 60

VERDICT_READY = "ENFORCE-READY"
VERDICT_CAUTION = "ENFORCE-CAUTION"
VERDICT_BLOCKED = "ENFORCE-BLOCKED"


# ---------------------------------------------------------------------------
# Stage 1 — Parse `.cross-repo-drift-allowlist.yaml`.
# ---------------------------------------------------------------------------


class AllowlistParseError(ValueError):
    """Raised on malformed allowlist YAML structure."""


def parse_allowlist(text: str) -> list[dict[str, str]]:
    """Stdlib YAML-subset parser.

    Accepts:

        allow: []
        allow:
          - runtime: <path>
            protocol: <path>
            reason: <text>
            follow_up: <ref>

    Returns a list of dicts. Comments and blank lines are skipped.
    Inline `allow: []` short-circuits to empty list. Malformed entries
    raise `AllowlistParseError`.
    """
    lines = text.splitlines()

    # Strip comments and blank lines.
    stripped: list[tuple[int, str]] = []
    for idx, raw in enumerate(lines, start=1):
        # Preserve indentation; only strip trailing whitespace.
        body = raw.rstrip()
        if not body.strip():
            continue
        if body.lstrip().startswith("#"):
            continue
        stripped.append((idx, body))

    if not stripped:
        raise AllowlistParseError("file has no `allow:` key (empty or all comments)")

    # Find the `allow:` anchor.
    anchor_idx = -1
    anchor_value = ""
    for i, (_, body) in enumerate(stripped):
        if body.startswith("allow:"):
            anchor_idx = i
            anchor_value = body[len("allow:"):].strip()
            break
    if anchor_idx < 0:
        raise AllowlistParseError("missing top-level `allow:` key")

    # Inline `allow: []`.
    if anchor_value == "[]":
        return []
    # Inline empty: `allow:` followed by nothing -> empty.
    if not anchor_value and anchor_idx == len(stripped) - 1:
        return []
    # Inline non-empty scalar (e.g. `allow: foo`) is malformed.
    if anchor_value:
        raise AllowlistParseError(
            f"inline value for `allow:` must be `[]` or omitted; got {anchor_value!r}"
        )

    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None

    valid_keys = {"runtime", "protocol", "reason", "follow_up"}

    for line_no, body in stripped[anchor_idx + 1:]:
        # Sequence start.
        if body.lstrip().startswith("- "):
            if current is not None:
                _validate_entry(current, line_no)
                entries.append(current)
            current = {}
            kv = body.lstrip()[2:].strip()
            if ":" in kv:
                k, v = kv.split(":", 1)
                k = k.strip()
                v = v.strip()
                if k not in valid_keys:
                    raise AllowlistParseError(
                        f"line {line_no}: unknown key {k!r}; "
                        f"valid keys: {sorted(valid_keys)}"
                    )
                current[k] = v
            elif kv:
                raise AllowlistParseError(
                    f"line {line_no}: sequence entry must be a key/value pair, "
                    f"got bare scalar {kv!r}"
                )
            continue

        # Continuation key under the current entry.
        if current is None:
            raise AllowlistParseError(
                f"line {line_no}: stray content outside sequence: {body!r}"
            )
        m = re.match(r"^(\s+)([A-Za-z_]+)\s*:\s*(.*)$", body)
        if not m:
            raise AllowlistParseError(
                f"line {line_no}: cannot parse as `<key>: <value>`: {body!r}"
            )
        key, value = m.group(2), m.group(3).strip()
        if key not in valid_keys:
            raise AllowlistParseError(
                f"line {line_no}: unknown key {key!r}; "
                f"valid keys: {sorted(valid_keys)}"
            )
        current[key] = value

    if current is not None:
        _validate_entry(current, len(lines))
        entries.append(current)

    return entries


def _validate_entry(entry: dict[str, str], line_no: int) -> None:
    """Validate a single allowlist entry."""
    for required in ("runtime", "protocol", "reason"):
        if not entry.get(required, "").strip():
            raise AllowlistParseError(
                f"line {line_no}: entry missing required key `{required}`"
            )


# ---------------------------------------------------------------------------
# Stage 2 — Coverage vs. drift inventory.
# ---------------------------------------------------------------------------


# Tag-31 baseline from the readiness doc §2 (locked here; the
# readiness-doc test in tests/infra/ already pins this table).
BASELINE_INVENTORY: tuple[dict[str, str], ...] = (
    {
        "runtime": "wirelang/schemas/layer-0-transport.json",
        "protocol": "wakir_protocol/schemas/layer-0-transport.json",
        "status": "drift",
        "strategy": "re-sync-protocol-from-runtime",
    },
    {
        "runtime": "wirelang/schemas/layer-1-wire.json",
        "protocol": "wakir_protocol/schemas/layer-1-wire.json",
        "status": "drift",
        "strategy": "re-sync-protocol-from-runtime",
    },
    {
        "runtime": "wirelang/schemas/layer-2-semantic.json",
        "protocol": "wakir_protocol/schemas/layer-2-semantic.json",
        "status": "drift",
        "strategy": "re-sync-protocol-from-runtime",
    },
    {
        "runtime": "wirelang/schemas/layer-3-capability-token.json",
        "protocol": "wakir_protocol/schemas/layer-3-capability-token.json",
        "status": "clean",
        "strategy": "",
    },
    {
        "runtime": "wirelang/schemas/aip-document.json",
        "protocol": "wakir_protocol/schemas/aip-document.json",
        "status": "drift",
        "strategy": "re-sync-runtime-from-protocol",
    },
    {
        "runtime": "wirelang/schemas/datalog-caveat.json",
        "protocol": "wakir_protocol/schemas/datalog-caveat.json",
        "status": "clean",
        "strategy": "",
    },
    {
        "runtime": "wirelang/schemas/federation-trust-document.json",
        "protocol": "wakir_protocol/schemas/federation-trust-document.json",
        "status": "clean",
        "strategy": "",
    },
    {
        "runtime": "wirelang/canonical/caveat_set.py",
        "protocol": "wakir_protocol/canonical/caveat_set.py",
        "status": "drift",
        "strategy": "allowlist-spdx-header-only",
    },
    {
        "runtime": "wirelang/identity/aip_document.py",
        "protocol": "wakir_protocol/identity_substrate/aip_document.py",
        "status": "drift",
        "strategy": "allowlist-spdx-header-only",
    },
    {
        "runtime": "wirelang/identity/dns_anchor.py",
        "protocol": "wakir_protocol/identity_substrate/dns_anchor.py",
        "status": "clean",
        "strategy": "",
    },
)


def compute_coverage(
    allowlist: list[dict[str, str]],
    inventory: tuple[dict[str, str], ...] = BASELINE_INVENTORY,
) -> dict[str, Any]:
    """Cross-check allowlist entries against the inventory.

    Returns a dict with:

      * `inventory_size`
      * `clean_count`
      * `drift_count_baseline`
      * `allowlist_size`
      * `allowlist_covers_inventory`: count of allowlist entries that
        match a baseline drift row
      * `unknown_allowlist_entries`: allowlist entries that do not
        match any inventory row (potential typo / stale waiver)
      * `expected_allowlist_pairs`: subset of inventory whose
        strategy is `allowlist-spdx-header-only`
      * `allowlist_completion`: fraction of expected pairs that have
        a matching allowlist entry
    """
    inv_index = {(r["runtime"], r["protocol"]): r for r in inventory}

    clean_count = sum(1 for r in inventory if r["status"] == "clean")
    drift_count = sum(1 for r in inventory if r["status"] == "drift")

    expected_allowlist_pairs = [
        (r["runtime"], r["protocol"])
        for r in inventory
        if r["strategy"] == "allowlist-spdx-header-only"
    ]

    covers = 0
    unknown: list[dict[str, str]] = []
    matched_expected: set[tuple[str, str]] = set()

    for entry in allowlist:
        key = (entry["runtime"], entry["protocol"])
        if key in inv_index:
            covers += 1
            if key in expected_allowlist_pairs:
                matched_expected.add(key)
        else:
            unknown.append(entry)

    if expected_allowlist_pairs:
        completion = len(matched_expected) / len(expected_allowlist_pairs)
    else:
        completion = 1.0

    return {
        "inventory_size": len(inventory),
        "clean_count": clean_count,
        "drift_count_baseline": drift_count,
        "allowlist_size": len(allowlist),
        "allowlist_covers_inventory": covers,
        "unknown_allowlist_entries": unknown,
        "expected_allowlist_pairs": expected_allowlist_pairs,
        "allowlist_completion": completion,
    }


# ---------------------------------------------------------------------------
# Stage 3 — Enforce-Flip-Readiness-Score.
# ---------------------------------------------------------------------------


def compute_readiness_score(
    coverage: dict[str, Any],
    strategies_assigned: int | None = None,
    inventory: tuple[dict[str, str], ...] = BASELINE_INVENTORY,
) -> dict[str, Any]:
    """Score 0..100 blending coverage and trajectory.

    `strategies_assigned` defaults to the count of inventory rows
    that have a non-empty `strategy` (i.e. resolution path declared).
    """
    if strategies_assigned is None:
        strategies_assigned = sum(1 for r in inventory if r["strategy"])

    drift_baseline = coverage["drift_count_baseline"]
    total = coverage["inventory_size"]
    clean = coverage["clean_count"]

    if drift_baseline == 0:
        coverage_ratio = 1.0
    else:
        coverage_ratio = min(1.0, strategies_assigned / drift_baseline)

    if total == 0:
        trajectory_ratio = 1.0
    else:
        trajectory_ratio = min(1.0, clean / total)

    coverage_ratio = max(0.0, coverage_ratio)
    trajectory_ratio = max(0.0, trajectory_ratio)

    score = round(60 * coverage_ratio + 40 * trajectory_ratio)
    return {
        "score": score,
        "coverage_ratio": coverage_ratio,
        "trajectory_ratio": trajectory_ratio,
        "strategies_assigned": strategies_assigned,
    }


# ---------------------------------------------------------------------------
# Stage 3b — Trajectory-Re-Sync detection (Tag-61, Reza).
# ---------------------------------------------------------------------------
#
# The Tag-31 BASELINE_INVENTORY is locked: every row's `status` is
# the captured baseline (`clean=4, drift=6`). The Stage-3 score-of-
# record is also locked at 76 / ENFORCE-CAUTION while we are pre-re-
# sync. Tag-61 introduces a *post-re-sync trajectory*: the canonical
# mirror-seed for a `re-sync-*` drift row, landed inside
# `wakir-runtime` under `wirelang/specs/protocol-mirror-seed/<canonical-
# path>`, counts as a trajectory-clean signal. The mirror-seed has
# been canonical-form-mirrored from the runtime side; once the
# Engineering-Lead hand-off PR lands it on the `wakir-protocol` side
# at its canonical path, the row flips to actually-clean in the next
# BASELINE_INVENTORY refresh.
#
# Sandbox boundary: this helper only reads files inside the runtime
# repo. The protocol-side presence is *not* inferred — only the
# runtime-side seed file presence is. The trajectory-resync signal is
# therefore a *ready-to-land* signal, not a *landed* signal.

RESYNC_STRATEGIES: tuple[str, ...] = (
    "re-sync-protocol-from-runtime",
    "re-sync-runtime-from-protocol",
)

PROTOCOL_MIRROR_SEED_DIR = "wirelang/specs/protocol-mirror-seed"


def _canonical_protocol_subpath(protocol_path: str) -> str:
    """Strip the `wakir_protocol/` prefix to produce the seed sub-path.

    Examples:
        `wakir_protocol/schemas/layer-0-transport.json`
            -> `schemas/layer-0-transport.json`
        `wakir_protocol/identity_substrate/aip_document.py`
            -> `identity_substrate/aip_document.py`

    Rows that do not start with `wakir_protocol/` return the input
    untouched (the seed lookup will then fail-closed).
    """
    prefix = "wakir_protocol/"
    if protocol_path.startswith(prefix):
        return protocol_path[len(prefix):]
    return protocol_path


def detect_trajectory_resync(
    repo_root: Path,
    inventory: tuple[dict[str, str], ...] = BASELINE_INVENTORY,
) -> dict[str, Any]:
    """Detect protocol-mirror-seed files for re-sync drift rows.

    For every inventory row with status=`drift` and a re-sync strategy,
    check whether the seed file
    `<repo_root>/wirelang/specs/protocol-mirror-seed/<canonical-sub-
    path>` exists. Return a structured report.
    """
    seed_root = repo_root / PROTOCOL_MIRROR_SEED_DIR
    resync_rows: list[dict[str, Any]] = []
    seeded = 0

    for row in inventory:
        if row["status"] != "drift":
            continue
        if row["strategy"] not in RESYNC_STRATEGIES:
            continue
        canonical_sub = _canonical_protocol_subpath(row["protocol"])
        seed_path = seed_root / canonical_sub
        present = seed_path.is_file()
        if present:
            seeded += 1
        resync_rows.append(
            {
                "runtime": row["runtime"],
                "protocol": row["protocol"],
                "strategy": row["strategy"],
                "seed_path": str(seed_path.relative_to(repo_root))
                if seed_path.is_relative_to(repo_root)
                else str(seed_path),
                "seed_present": present,
            }
        )

    expected = len(resync_rows)
    completion = (seeded / expected) if expected else 1.0

    return {
        "resync_rows": resync_rows,
        "expected_seeded": expected,
        "actually_seeded": seeded,
        "resync_completion": completion,
    }


def compute_post_resync_score(
    coverage: dict[str, Any],
    resync: dict[str, Any],
    strategies_assigned: int | None = None,
    inventory: tuple[dict[str, str], ...] = BASELINE_INVENTORY,
) -> dict[str, Any]:
    """Post-re-sync score: trajectory accounts for landed seeds.

    Formula (locked):

        post_resync_clean = clean_count + actually_seeded
        post_resync_trajectory_ratio = post_resync_clean / total
        post_resync_score = round(60 * coverage_ratio
                                  + 40 * post_resync_trajectory_ratio)

    Coverage ratio is unchanged (strategies were already assigned at
    Tag-31). The score is clamped to [0, 100] via the [0.0, 1.0]
    ratio clamps. The verdict is then computed by `compute_verdict`
    on the post-re-sync score.
    """
    if strategies_assigned is None:
        strategies_assigned = sum(1 for r in inventory if r["strategy"])

    drift_baseline = coverage["drift_count_baseline"]
    total = coverage["inventory_size"]
    clean = coverage["clean_count"]
    seeded = resync["actually_seeded"]

    if drift_baseline == 0:
        coverage_ratio = 1.0
    else:
        coverage_ratio = min(1.0, strategies_assigned / drift_baseline)

    post_clean = clean + seeded
    if total == 0:
        post_trajectory_ratio = 1.0
    else:
        post_trajectory_ratio = min(1.0, post_clean / total)

    coverage_ratio = max(0.0, coverage_ratio)
    post_trajectory_ratio = max(0.0, post_trajectory_ratio)

    post_score = round(60 * coverage_ratio + 40 * post_trajectory_ratio)
    return {
        "post_resync_score": post_score,
        "post_resync_trajectory_ratio": post_trajectory_ratio,
        "post_resync_clean_count": post_clean,
        "coverage_ratio": coverage_ratio,
        "strategies_assigned": strategies_assigned,
    }


# ---------------------------------------------------------------------------
# Stage 4 — Verdict.
# ---------------------------------------------------------------------------


def compute_verdict(score: int) -> str:
    if score >= SCORE_READY_MIN:
        return VERDICT_READY
    if score >= SCORE_CAUTION_MIN:
        return VERDICT_CAUTION
    return VERDICT_BLOCKED


# ---------------------------------------------------------------------------
# Top-level audit driver.
# ---------------------------------------------------------------------------


def run_audit(
    allowlist_path: Path,
    workflow_path: Path | None = None,
    readiness_doc_path: Path | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Run all four stages and return a JSON-shape report.

    `workflow_path` and `readiness_doc_path` are accepted for parity
    with the workflow caller; the baseline inventory is locked in
    this module and the file references are recorded in the report
    for traceability.

    `repo_root` enables the Tag-61 Stage-3b trajectory-resync
    detection. When omitted, the resync stage runs against the
    allowlist file's parent (best-effort) so the existing CLI
    keeps working without an explicit flag.
    """
    text = allowlist_path.read_text(encoding="utf-8")
    parse_error = None
    try:
        allow = parse_allowlist(text)
    except AllowlistParseError as exc:
        parse_error = str(exc)
        allow = []

    coverage = compute_coverage(allow)
    score_info = compute_readiness_score(coverage)
    verdict = compute_verdict(score_info["score"])

    if repo_root is None:
        repo_root = allowlist_path.resolve().parent
    resync = detect_trajectory_resync(repo_root)
    post_resync = compute_post_resync_score(coverage, resync)
    post_resync_verdict = compute_verdict(post_resync["post_resync_score"])

    return {
        "tag": "tag-60",
        "owner": "noa",
        "tag_61_extension": {
            "tag": "tag-61",
            "owner": "reza",
            "purpose": "trajectory-resync-detection",
        },
        "allowlist_path": str(allowlist_path),
        "workflow_path": str(workflow_path) if workflow_path else None,
        "readiness_doc_path": (
            str(readiness_doc_path) if readiness_doc_path else None
        ),
        "stage_1_parse": {
            "ok": parse_error is None,
            "error": parse_error,
            "entry_count": len(allow),
        },
        "stage_2_coverage": coverage,
        "stage_3_readiness_score": score_info,
        "stage_3b_trajectory_resync": resync,
        "stage_3b_post_resync_score": post_resync,
        "stage_4_verdict": verdict,
        "stage_4_post_resync_verdict": post_resync_verdict,
    }


def render_markdown_summary(report: dict[str, Any]) -> str:
    cov = report["stage_2_coverage"]
    score = report["stage_3_readiness_score"]
    parse = report["stage_1_parse"]
    verdict = report["stage_4_verdict"]
    lines = [
        "# Cross-Repo-Drift-Allowlist-Audit (Tag-60)",
        "",
        f"**Verdict:** `{verdict}`",
        f"**Score:** `{score['score']}/100`",
        "",
        "## Stage 1 — Parse",
        "",
        f"- ok: `{parse['ok']}`",
        f"- entries: `{parse['entry_count']}`",
        f"- error: `{parse['error'] or '—'}`",
        "",
        "## Stage 2 — Coverage",
        "",
        f"- inventory size: `{cov['inventory_size']}`",
        f"- clean: `{cov['clean_count']}`",
        f"- drift (baseline): `{cov['drift_count_baseline']}`",
        f"- allowlist entries: `{cov['allowlist_size']}`",
        f"- allowlist covers inventory: `{cov['allowlist_covers_inventory']}`",
        f"- unknown allowlist entries: `{len(cov['unknown_allowlist_entries'])}`",
        f"- expected allowlist pairs (spdx-header-only): "
        f"`{len(cov['expected_allowlist_pairs'])}`",
        f"- allowlist completion: `{cov['allowlist_completion']:.2f}`",
        "",
        "## Stage 3 — Readiness Score",
        "",
        f"- coverage_ratio: `{score['coverage_ratio']:.2f}`",
        f"- trajectory_ratio: `{score['trajectory_ratio']:.2f}`",
        f"- strategies_assigned: `{score['strategies_assigned']}`",
        f"- formula: `round(60 * coverage_ratio + 40 * trajectory_ratio)`",
        "",
        "## Stage 3b — Trajectory-Re-Sync (Tag-61, Reza)",
        "",
    ]
    resync = report.get("stage_3b_trajectory_resync")
    post = report.get("stage_3b_post_resync_score")
    if resync is not None and post is not None:
        lines.extend(
            [
                f"- expected seeded rows: `{resync['expected_seeded']}`",
                f"- actually seeded rows: `{resync['actually_seeded']}`",
                f"- resync completion: `{resync['resync_completion']:.2f}`",
                f"- post-resync trajectory_ratio: "
                f"`{post['post_resync_trajectory_ratio']:.2f}`",
                f"- post-resync clean_count: `{post['post_resync_clean_count']}`",
                f"- post-resync score: `{post['post_resync_score']}/100`",
                f"- post-resync verdict: "
                f"`{report.get('stage_4_post_resync_verdict', '—')}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Stage 4 — Verdict",
            "",
            f"- `{verdict}`",
            f"  - `>= {SCORE_READY_MIN}` = {VERDICT_READY}",
            f"  - `>= {SCORE_CAUTION_MIN}` = {VERDICT_CAUTION}",
            f"  - `<  {SCORE_CAUTION_MIN}` = {VERDICT_BLOCKED}",
            "",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Tag-60 Cross-Repo-Drift-Allowlist-Audit "
            "(Pre-Enforce-Flip-Readiness-Substrate)"
        )
    )
    parser.add_argument(
        "--allowlist",
        default=ALLOWLIST_DEFAULT,
        help="path to allowlist YAML (default: %(default)s)",
    )
    parser.add_argument(
        "--workflow",
        default=WORKFLOW_DEFAULT,
        help="path to drift-audit workflow (default: %(default)s)",
    )
    parser.add_argument(
        "--readiness-doc",
        default=READINESS_DOC_DEFAULT,
        help="path to enforce-flip readiness doc (default: %(default)s)",
    )
    parser.add_argument(
        "--summary",
        default=None,
        help="optional path to write a markdown summary",
    )
    parser.add_argument(
        "--fail-on",
        choices=("never", "caution", "blocked"),
        default="never",
        help=(
            "exit non-zero when the verdict reaches this level "
            "(default: never — pure audit mode)"
        ),
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help=(
            "repo root for Tag-61 trajectory-resync detection "
            "(default: derived from allowlist parent)"
        ),
    )
    parser.add_argument(
        "--post-resync",
        action="store_true",
        help=(
            "evaluate --fail-on against the post-resync verdict "
            "instead of the locked baseline verdict"
        ),
    )
    args = parser.parse_args(argv)

    allowlist_path = Path(args.allowlist)
    workflow_path = Path(args.workflow)
    readiness_path = Path(args.readiness_doc)
    repo_root = Path(args.repo_root) if args.repo_root else None

    if not allowlist_path.exists():
        print(
            f"[FATAL] allowlist not found: {allowlist_path}",
            file=sys.stderr,
        )
        return 2

    report = run_audit(
        allowlist_path=allowlist_path,
        workflow_path=workflow_path if workflow_path.exists() else None,
        readiness_doc_path=readiness_path if readiness_path.exists() else None,
        repo_root=repo_root,
    )

    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")

    summary_md = render_markdown_summary(report)
    if args.summary:
        Path(args.summary).write_text(summary_md, encoding="utf-8")
    else:
        print(summary_md, file=sys.stderr)

    if args.post_resync:
        verdict = report["stage_4_post_resync_verdict"]
    else:
        verdict = report["stage_4_verdict"]
    if args.fail_on == "blocked" and verdict == VERDICT_BLOCKED:
        return 1
    if args.fail_on == "caution" and verdict in (VERDICT_BLOCKED, VERDICT_CAUTION):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
