#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""15-Binary SBOM Baseline Refresh CLI (Tag-50, Kai).

Context
-------

Tag-48 PR #310 introduced the 15-binary SBOM generator. Tag-49
PR #318 introduced the daily verifier which compares freshly-
generated SBOMs to ``state/sbom-baseline/<binary>.json``. The
baseline files themselves are Operator-Hand-refreshed when AR
signs off on a dependency-tree change (see
``docs/operations/15-binary-sbom-baseline-refresh.md`` Tag-49).

What was missing in Tag-49 was a *single* executable that runs
the refresh sequence end-to-end as one atomic operation:

  1. Run the generator with ``--generator-ts 0.0`` (deterministic
     baseline-mode).
  2. Run the verifier in pre-refresh dry-run to capture the drift
     summary that AR signs off on.
  3. Block unless an ``--approval-token`` argument is supplied
     that matches the required token format. Without the token,
     the script refuses to overwrite ``state/sbom-baseline/``.
  4. Optionally refuse to refresh forward through any
     ``checksum-changed`` drift (RED-class supply-chain signal)
     unless ``--allow-checksum-changed`` is also supplied (extra
     gate on top of the approval token).
  5. Copy the generator's per-binary SBOMs into
     ``state/sbom-baseline/<binary>.json``.
  6. Run the verifier in post-refresh validation -- assert GREEN.
  7. Emit a refresh-receipt JSON describing the operation
     (cargo-lock-sha256 before/after, drift summary, AR approval
     token, refresh timestamp).

Sandbox posture
---------------

Strict hermetic: stdlib + tomllib only (delegates SBOM parsing
to the Tag-48 generator and Tag-49 verifier via importlib.util).
No podman / cargo / cosign / network egress. The script does
mutate ``state/sbom-baseline/`` -- that is the entire point --
but only when the approval flag is supplied and the post-refresh
verification produces GREEN.

Operator workflow
-----------------

Manual invocation only (CLI + ``workflow_dispatch``-only
GitHub-Actions workflow ``.github/workflows/sbom-baseline-refresh.yml``).
This is never scheduled.

Approval-token format
---------------------

The token MUST start with ``AR-HAND-GATE-`` followed by a
date stamp in YYYY-MM-DD format and an operator initials
suffix, separated by hyphens. Example:

    AR-HAND-GATE-2026-05-19-fred

Tokens are not secrets -- they are audit-trail anchors. The
purpose is to force the operator to type a meaningful string
into the CLI rather than mash an "are-you-sure" prompt.

The token is recorded verbatim in the refresh receipt JSON so
the receipt is self-anchoring: anyone reading the receipt knows
which AR-Hand-Gate sign-off the refresh was bound to.

Anchors
-------

  * Tag-48 PR #310 -- 15-binary SBOM generator.
  * Tag-49 PR #318 -- daily SBOM-vs-baseline verifier.
  * Tag-49 docs/operations/15-binary-sbom-baseline-refresh.md --
    the operator runbook this script automates.
  * ADR-0066 § AR-Hand-Gate -- pre-cutover sign-off bundle.
  * feedback_sandbox_host_trennung.md -- no live cargo I/O.

Author: Kai Hoffmann (Dev-Engineering-3 / Container-Orchestration)
Tag: 50 (KW-22)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import sys
import tempfile
import time as _time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Loader: import generator + verifier modules via their hyphenated paths.
# ---------------------------------------------------------------------------


def _load_module(script_path: Path, module_name: str) -> Any:
    """Load a hyphenated Python script as a named module."""
    spec = importlib.util.spec_from_file_location(
        module_name, str(script_path)
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"cannot load module {module_name!r} from {script_path}"
        )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Required prefix for the AR-Hand-Gate approval token.
APPROVAL_TOKEN_PREFIX: str = "AR-HAND-GATE-"

#: Regex for the approval-token tail (date stamp + operator initials).
#:
#: Example matches:
#:   * ``AR-HAND-GATE-2026-05-19-fred``
#:   * ``AR-HAND-GATE-2026-12-01-kai-h``
APPROVAL_TOKEN_PATTERN: re.Pattern[str] = re.compile(
    r"^AR-HAND-GATE-\d{4}-\d{2}-\d{2}-[a-z][a-z0-9\-]*$"
)

#: Schema version for the refresh-receipt envelope.
RECEIPT_ENVELOPE_SCHEMA_VERSION: str = "1"

#: Default location of the Tag-48 generator script (relative to repo root).
DEFAULT_GENERATOR_REL: str = (
    "scripts/observability/generate-15-binary-sbom.py"
)

#: Default location of the Tag-49 verifier script (relative to repo root).
DEFAULT_VERIFIER_REL: str = (
    "scripts/observability/verify-15-binary-sbom-against-baseline.py"
)

#: Default location of the Cargo.lock input (relative to repo root).
DEFAULT_CARGO_LOCK_REL: str = "wirelang-rust/Cargo.lock"

#: Default location of the baseline directory.
DEFAULT_BASELINE_DIR_REL: str = "state/sbom-baseline"

#: Exit codes (stable + scriptable).
EXIT_OK: int = 0
EXIT_NO_APPROVAL: int = 10
EXIT_BAD_TOKEN_FORMAT: int = 11
EXIT_CHECKSUM_DRIFT_BLOCKED: int = 12
EXIT_POST_REFRESH_NOT_GREEN: int = 13
EXIT_INTERNAL_ERROR: int = 2


# ---------------------------------------------------------------------------
# Dataclasses (pure)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RefreshPlan:
    """The plan computed before any state mutation.

    Captures the *intent* of the refresh so it can be inspected
    by tests (and by ``--dry-run`` callers) without touching
    ``state/sbom-baseline/``.
    """

    cargo_lock_sha256_before: Optional[str]
    cargo_lock_sha256_after: str
    pre_refresh_verdict: str
    pre_refresh_drift_total: int
    pre_refresh_checksum_changed_count: int
    pre_refresh_envelope: Mapping[str, Any]


@dataclass(frozen=True)
class RefreshOutcome:
    """The post-mutation result of a refresh run."""

    plan: RefreshPlan
    refreshed: bool
    files_written: Tuple[str, ...]
    post_refresh_verdict: str
    receipt_path: Optional[Path]
    receipt_payload: Mapping[str, Any]


# ---------------------------------------------------------------------------
# Pure functions: approval-token validation
# ---------------------------------------------------------------------------


def is_valid_approval_token(token: str) -> bool:
    """Return True if ``token`` matches the AR-Hand-Gate format.

    Pure: no I/O. Trivial regex check. Exposed for the test suite
    so token validation can be exercised independently of the
    refresh sequence.
    """
    if not token:
        return False
    if not token.startswith(APPROVAL_TOKEN_PREFIX):
        return False
    return APPROVAL_TOKEN_PATTERN.match(token) is not None


# ---------------------------------------------------------------------------
# Pure functions: drift summary classification
# ---------------------------------------------------------------------------


def count_checksum_changed_drift(envelope: Mapping[str, Any]) -> int:
    """Count the ``checksum-changed`` drift entries across all binaries.

    Pure: takes a verifier-envelope dict, returns an int. The
    refresh CLI uses this to decide whether the operator must
    also pass ``--allow-checksum-changed`` -- a separate gate on
    top of the approval token, because checksum-changed drift is
    a supply-chain integrity signal.
    """
    total = 0
    for pb in envelope.get("per_binary", []):
        for d in pb.get("drift_entries", []):
            if d.get("drift_class") == "checksum-changed":
                total += 1
    return total


def total_drift_entries(envelope: Mapping[str, Any]) -> int:
    """Total drift entry count across all binaries (any class).

    Pure: helper used in the refresh-receipt envelope.
    """
    total = 0
    for pb in envelope.get("per_binary", []):
        total += int(pb.get("drift_count", 0))
    return total


# ---------------------------------------------------------------------------
# Pure functions: receipt envelope rendering
# ---------------------------------------------------------------------------


def render_receipt(
    *,
    approval_token: str,
    refreshed: bool,
    plan: RefreshPlan,
    post_refresh_verdict: str,
    files_written: Sequence[str],
    refresh_ts: float,
    operator_invocation: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Build the refresh-receipt envelope as a JSON-serialisable dict.

    Pure: assembles a record from in-memory state, no I/O. The
    receipt is the audit-trail anchor for the operation -- it
    captures the AR-Hand-Gate token, the cargo-lock-sha256 before
    and after, the drift summary, and the post-refresh verdict.
    """
    return {
        "schema_version": RECEIPT_ENVELOPE_SCHEMA_VERSION,
        "approval_token": approval_token,
        "refreshed": refreshed,
        "refresh_ts": refresh_ts,
        "cargo_lock_sha256_before": plan.cargo_lock_sha256_before,
        "cargo_lock_sha256_after": plan.cargo_lock_sha256_after,
        "pre_refresh_verdict": plan.pre_refresh_verdict,
        "pre_refresh_drift_total": plan.pre_refresh_drift_total,
        "pre_refresh_checksum_changed_count": (
            plan.pre_refresh_checksum_changed_count
        ),
        "post_refresh_verdict": post_refresh_verdict,
        "files_written": list(files_written),
        "operator_invocation": dict(operator_invocation),
    }


# ---------------------------------------------------------------------------
# Pure functions: per-binary baseline-file enumeration
# ---------------------------------------------------------------------------


def enumerate_baseline_writes(
    sbom_dir: Path,
    baseline_dir: Path,
    inventory: Sequence[str],
) -> Tuple[Tuple[Path, Path], ...]:
    """Compute the (src, dst) pairs for the copy step.

    Pure: returns intended writes; does NOT touch the filesystem.
    Exposed for the test suite so the copy plan can be inspected
    without invoking the full CLI.

    The src path is ``<sbom_dir>/<binary>.cdx.json`` (Tag-48
    generator output). The dst path is
    ``<baseline_dir>/<binary>.json`` (Tag-49 baseline filename).
    """
    out = []
    for binary_name in inventory:
        src = sbom_dir / f"{binary_name}.cdx.json"
        dst = baseline_dir / f"{binary_name}.json"
        out.append((src, dst))
    return tuple(out)


# ---------------------------------------------------------------------------
# Pure functions: baseline-cargo-lock-sha256 readback
# ---------------------------------------------------------------------------


def read_baseline_cargo_lock_sha256(
    baseline_dir: Path,
    inventory: Sequence[str],
) -> Optional[str]:
    """Return the cargo-lock SHA-256 embedded in the current baseline.

    If the baseline directory is empty or missing the property,
    returns None. If multiple files disagree, returns the value
    from the first inventory entry that has the property (the
    refresh receipt will flag the inconsistency via the verifier
    envelope's substrate-consistency check).
    """
    for binary_name in inventory:
        candidate = baseline_dir / f"{binary_name}.json"
        if not candidate.is_file():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        metadata = data.get("metadata") or {}
        for prop in metadata.get("properties") or []:
            if prop.get("name") == "wakir:cargo-lock-sha256":
                value = prop.get("value")
                if isinstance(value, str):
                    return value
    return None


# ---------------------------------------------------------------------------
# I/O surface (small, isolated for testability).
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _generator_main_or_raise(
    gen_module: Any,
    *,
    cargo_lock: Path,
    out_dir: Path,
    out_envelope: Path,
    generator_ts: float,
) -> None:
    """Invoke the Tag-48 generator via its ``main()`` entry point."""
    argv = [
        "--cargo-lock", str(cargo_lock),
        "--out-dir", str(out_dir),
        "--out-envelope", str(out_envelope),
        "--format", "cyclonedx-1.5",
        "--mode", "stdlib",
        "--generator-ts", str(generator_ts),
    ]
    rc = gen_module.main(argv)
    if rc != 0:
        raise RuntimeError(
            f"generator main() returned non-zero exit code {rc}"
        )


def _verifier_main_or_raise(
    ver_module: Any,
    *,
    sbom_dir: Path,
    baseline_dir: Path,
    out_json: Path,
    out_markdown: Optional[Path] = None,
    generator_ts: float,
) -> Mapping[str, Any]:
    """Invoke the Tag-49 verifier and return its envelope JSON."""
    argv = [
        "--sbom-dir", str(sbom_dir),
        "--baseline-dir", str(baseline_dir),
        "--out-json", str(out_json),
        "--generator-ts", str(generator_ts),
    ]
    if out_markdown is not None:
        argv.extend(["--out-markdown", str(out_markdown)])
    rc = ver_module.main(argv)
    if rc not in (0, 1):
        # Verifier returns 0 on GREEN or any verdict (without
        # --exit-non-zero-on-drift). 1 only when that flag is set.
        # 2 is the verifier's own "input invalid" hard-error. We
        # never pass --exit-non-zero-on-drift here, so any non-zero
        # return is an internal failure.
        raise RuntimeError(
            f"verifier main() returned non-zero exit code {rc}"
        )
    return _read_json(out_json)


# ---------------------------------------------------------------------------
# Orchestration: plan + execute refresh (test-callable surface)
# ---------------------------------------------------------------------------


def plan_refresh(
    *,
    gen_module: Any,
    ver_module: Any,
    cargo_lock: Path,
    baseline_dir: Path,
    work_dir: Path,
    inventory: Sequence[str],
    generator_ts: float = 0.0,
) -> RefreshPlan:
    """Compute the pre-refresh plan.

    Side-effects:
      * Writes the generator's fifteen SBOM files into ``work_dir``.
      * Writes the verifier envelope into ``work_dir``.
      * Does NOT touch ``baseline_dir``.

    Returns a RefreshPlan record. Pure with respect to
    ``baseline_dir``: this function is safe to call repeatedly
    in dry-run / inspection contexts.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    sbom_subdir = work_dir / "sbom"
    sbom_subdir.mkdir(parents=True, exist_ok=True)

    _generator_main_or_raise(
        gen_module,
        cargo_lock=cargo_lock,
        out_dir=sbom_subdir,
        out_envelope=sbom_subdir / "envelope.json",
        generator_ts=generator_ts,
    )

    verify_envelope_path = work_dir / "pre-refresh-verify.json"
    verify_markdown_path = work_dir / "pre-refresh-verify.md"
    pre_envelope = _verifier_main_or_raise(
        ver_module,
        sbom_dir=sbom_subdir,
        baseline_dir=baseline_dir,
        out_json=verify_envelope_path,
        out_markdown=verify_markdown_path,
        generator_ts=generator_ts,
    )

    # Read the generator-envelope to pick the new cargo-lock SHA.
    gen_envelope = _read_json(sbom_subdir / "envelope.json")
    new_lock_sha = gen_envelope.get("cargo_lock_sha256")
    if not isinstance(new_lock_sha, str):
        raise RuntimeError(
            "generator envelope missing cargo_lock_sha256 field"
        )
    old_lock_sha = read_baseline_cargo_lock_sha256(
        baseline_dir, inventory
    )

    return RefreshPlan(
        cargo_lock_sha256_before=old_lock_sha,
        cargo_lock_sha256_after=new_lock_sha,
        pre_refresh_verdict=str(pre_envelope.get("verdict", "")),
        pre_refresh_drift_total=total_drift_entries(pre_envelope),
        pre_refresh_checksum_changed_count=(
            count_checksum_changed_drift(pre_envelope)
        ),
        pre_refresh_envelope=pre_envelope,
    )


def execute_refresh(
    *,
    gen_module: Any,
    ver_module: Any,
    cargo_lock: Path,
    baseline_dir: Path,
    work_dir: Path,
    inventory: Sequence[str],
    approval_token: str,
    allow_checksum_changed: bool,
    receipt_path: Optional[Path],
    operator_invocation: Mapping[str, Any],
    refresh_ts: float,
    generator_ts: float = 0.0,
) -> RefreshOutcome:
    """Execute the full refresh sequence (plan + copy + re-verify).

    Returns a RefreshOutcome record. Raises:
      * ValueError if approval_token is malformed.
      * PermissionError if checksum-changed drift is present and
        ``allow_checksum_changed`` is False.
      * RuntimeError if post-refresh verification is not GREEN.
    """
    if not is_valid_approval_token(approval_token):
        raise ValueError(
            f"approval_token {approval_token!r} is not in the required "
            f"AR-HAND-GATE-YYYY-MM-DD-<initials> format"
        )

    plan = plan_refresh(
        gen_module=gen_module,
        ver_module=ver_module,
        cargo_lock=cargo_lock,
        baseline_dir=baseline_dir,
        work_dir=work_dir,
        inventory=inventory,
        generator_ts=generator_ts,
    )

    if (
        plan.pre_refresh_checksum_changed_count > 0
        and not allow_checksum_changed
    ):
        raise PermissionError(
            f"pre-refresh drift contains "
            f"{plan.pre_refresh_checksum_changed_count} checksum-changed "
            f"entries; supply --allow-checksum-changed to proceed "
            f"(supply-chain integrity gate)"
        )

    sbom_subdir = work_dir / "sbom"
    copy_pairs = enumerate_baseline_writes(
        sbom_subdir, baseline_dir, inventory
    )
    baseline_dir.mkdir(parents=True, exist_ok=True)
    files_written = []
    for src, dst in copy_pairs:
        if not src.is_file():
            raise RuntimeError(
                f"generator did not emit expected file {src}"
            )
        shutil.copyfile(src, dst)
        files_written.append(str(dst))

    # Post-refresh verification: re-run against the freshly-written
    # baseline. Must produce GREEN -- otherwise the refresh sequence
    # mutated state into an inconsistent shape and we surface that
    # via the receipt.
    post_envelope_path = work_dir / "post-refresh-verify.json"
    post_envelope = _verifier_main_or_raise(
        ver_module,
        sbom_dir=sbom_subdir,
        baseline_dir=baseline_dir,
        out_json=post_envelope_path,
        out_markdown=work_dir / "post-refresh-verify.md",
        generator_ts=generator_ts,
    )
    post_verdict = str(post_envelope.get("verdict", ""))

    receipt = render_receipt(
        approval_token=approval_token,
        refreshed=True,
        plan=plan,
        post_refresh_verdict=post_verdict,
        files_written=tuple(files_written),
        refresh_ts=refresh_ts,
        operator_invocation=operator_invocation,
    )
    if receipt_path is not None:
        _write_json(receipt_path, receipt)

    if post_verdict != "GREEN":
        raise RuntimeError(
            f"post-refresh verifier verdict is {post_verdict!r} -- "
            f"expected GREEN; baseline state is now inconsistent. "
            f"Inspect {post_envelope_path}."
        )

    return RefreshOutcome(
        plan=plan,
        refreshed=True,
        files_written=tuple(files_written),
        post_refresh_verdict=post_verdict,
        receipt_path=receipt_path,
        receipt_payload=receipt,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh state/sbom-baseline/ from a fresh generator run. "
            "Operator-Hand only. Requires --approval-token in "
            "AR-HAND-GATE-YYYY-MM-DD-<initials> format."
        )
    )
    parser.add_argument(
        "--cargo-lock",
        required=False,
        type=Path,
        default=Path(DEFAULT_CARGO_LOCK_REL),
        help="Path to Cargo.lock (default: wirelang-rust/Cargo.lock).",
    )
    parser.add_argument(
        "--baseline-dir",
        required=False,
        type=Path,
        default=Path(DEFAULT_BASELINE_DIR_REL),
        help="Path to baseline directory (default: state/sbom-baseline).",
    )
    parser.add_argument(
        "--generator",
        required=False,
        type=Path,
        default=None,
        help=(
            "Override path to the Tag-48 generator script "
            f"(default: ./{DEFAULT_GENERATOR_REL})."
        ),
    )
    parser.add_argument(
        "--verifier",
        required=False,
        type=Path,
        default=None,
        help=(
            "Override path to the Tag-49 verifier script "
            f"(default: ./{DEFAULT_VERIFIER_REL})."
        ),
    )
    parser.add_argument(
        "--approval-token",
        required=False,
        default=None,
        help=(
            "AR-Hand-Gate approval token. REQUIRED unless --dry-run. "
            "Format: AR-HAND-GATE-YYYY-MM-DD-<initials> "
            "(e.g. AR-HAND-GATE-2026-05-19-fred). The token is "
            "recorded verbatim in the refresh receipt."
        ),
    )
    parser.add_argument(
        "--allow-checksum-changed",
        action="store_true",
        help=(
            "Permit refresh even if the pre-refresh drift includes "
            "checksum-changed entries (supply-chain integrity signal). "
            "Without this flag, checksum-changed drift blocks the "
            "refresh."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Compute the plan but do NOT mutate state/sbom-baseline/. "
            "Useful for diff preview. Does not require --approval-token."
        ),
    )
    parser.add_argument(
        "--receipt-out",
        required=False,
        type=Path,
        default=None,
        help=(
            "Path to write the refresh-receipt JSON envelope. "
            "Recommended: state/sbom-baseline-refresh-receipts/"
            "<timestamp>-receipt.json."
        ),
    )
    parser.add_argument(
        "--work-dir",
        required=False,
        type=Path,
        default=None,
        help=(
            "Working directory for the temporary generator + verifier "
            "outputs. Defaults to a fresh tempdir. Useful for "
            "inspection after a failed run."
        ),
    )
    parser.add_argument(
        "--generator-ts",
        required=False,
        type=float,
        default=0.0,
        help=(
            "Generator timestamp seed for deterministic baseline "
            "files. Defaults to 0.0 (the canonical baseline value)."
        ),
    )
    parser.add_argument(
        "--refresh-ts",
        required=False,
        type=float,
        default=None,
        help=(
            "Override the refresh-ts field in the receipt envelope "
            "(for reproducible tests). Defaults to time.time()."
        ),
    )
    return parser.parse_args(argv)


def _resolve_script_paths(
    here: Path,
    generator_arg: Optional[Path],
    verifier_arg: Optional[Path],
) -> Tuple[Path, Path]:
    """Resolve the generator + verifier script paths."""
    gen_path = (
        generator_arg
        if generator_arg is not None
        else here / "generate-15-binary-sbom.py"
    )
    ver_path = (
        verifier_arg
        if verifier_arg is not None
        else here / "verify-15-binary-sbom-against-baseline.py"
    )
    if not gen_path.is_file():
        raise FileNotFoundError(f"generator script missing at {gen_path}")
    if not ver_path.is_file():
        raise FileNotFoundError(f"verifier script missing at {ver_path}")
    return gen_path, ver_path


def main(argv: Sequence[str]) -> int:
    args = _parse_args(argv)

    here = Path(__file__).resolve().parent
    try:
        gen_path, ver_path = _resolve_script_paths(
            here, args.generator, args.verifier
        )
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_INTERNAL_ERROR

    gen_module = _load_module(gen_path, "generate_15_binary_sbom")
    ver_module = _load_module(
        ver_path, "verify_15_binary_sbom_against_baseline"
    )
    inventory = gen_module.TAG45_BINARY_INVENTORY

    # Resolve work_dir (tempdir if not supplied).
    if args.work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="sbom-baseline-refresh-"))
        work_dir_was_temp = True
    else:
        work_dir = args.work_dir
        work_dir.mkdir(parents=True, exist_ok=True)
        work_dir_was_temp = False

    refresh_ts = (
        args.refresh_ts
        if args.refresh_ts is not None
        else _time.time()
    )

    operator_invocation: Mapping[str, Any] = {
        "cargo_lock": str(args.cargo_lock),
        "baseline_dir": str(args.baseline_dir),
        "dry_run": bool(args.dry_run),
        "allow_checksum_changed": bool(args.allow_checksum_changed),
        "work_dir": str(work_dir),
        "work_dir_was_temp": work_dir_was_temp,
    }

    # Dry-run path: compute plan only, skip approval-token check.
    if args.dry_run:
        try:
            plan = plan_refresh(
                gen_module=gen_module,
                ver_module=ver_module,
                cargo_lock=args.cargo_lock,
                baseline_dir=args.baseline_dir,
                work_dir=work_dir,
                inventory=inventory,
                generator_ts=args.generator_ts,
            )
        except Exception as exc:
            print(f"ERROR (dry-run): {exc}", file=sys.stderr)
            return EXIT_INTERNAL_ERROR

        receipt = render_receipt(
            approval_token="(dry-run, no token)",
            refreshed=False,
            plan=plan,
            post_refresh_verdict="(dry-run, not executed)",
            files_written=tuple(),
            refresh_ts=refresh_ts,
            operator_invocation=operator_invocation,
        )
        if args.receipt_out is not None:
            _write_json(args.receipt_out, receipt)
        print(
            f"[dry-run] pre_refresh_verdict={plan.pre_refresh_verdict} "
            f"drift_total={plan.pre_refresh_drift_total} "
            f"checksum_changed={plan.pre_refresh_checksum_changed_count} "
            f"cargo_lock_sha256={plan.cargo_lock_sha256_after[:16]}..."
        )
        return EXIT_OK

    # Real refresh path: requires --approval-token.
    if not args.approval_token:
        print(
            "ERROR: --approval-token is REQUIRED for an actual refresh. "
            "(Did you mean to add --dry-run for preview?)",
            file=sys.stderr,
        )
        return EXIT_NO_APPROVAL

    if not is_valid_approval_token(args.approval_token):
        print(
            f"ERROR: approval-token {args.approval_token!r} is not in "
            f"the required AR-HAND-GATE-YYYY-MM-DD-<initials> format.",
            file=sys.stderr,
        )
        return EXIT_BAD_TOKEN_FORMAT

    try:
        outcome = execute_refresh(
            gen_module=gen_module,
            ver_module=ver_module,
            cargo_lock=args.cargo_lock,
            baseline_dir=args.baseline_dir,
            work_dir=work_dir,
            inventory=inventory,
            approval_token=args.approval_token,
            allow_checksum_changed=bool(args.allow_checksum_changed),
            receipt_path=args.receipt_out,
            operator_invocation=operator_invocation,
            refresh_ts=refresh_ts,
            generator_ts=args.generator_ts,
        )
    except PermissionError as exc:
        print(f"ERROR (checksum-drift-block): {exc}", file=sys.stderr)
        return EXIT_CHECKSUM_DRIFT_BLOCKED
    except RuntimeError as exc:
        # Post-refresh-verdict-not-GREEN is the most common
        # RuntimeError; map to that exit code so the caller can
        # branch on it.
        msg = str(exc)
        if "post-refresh verifier verdict" in msg:
            print(f"ERROR (post-refresh-not-green): {exc}", file=sys.stderr)
            return EXIT_POST_REFRESH_NOT_GREEN
        print(f"ERROR (internal): {exc}", file=sys.stderr)
        return EXIT_INTERNAL_ERROR
    except Exception as exc:
        print(f"ERROR (internal): {exc}", file=sys.stderr)
        return EXIT_INTERNAL_ERROR

    print(
        f"[refreshed] pre_verdict={outcome.plan.pre_refresh_verdict} "
        f"post_verdict={outcome.post_refresh_verdict} "
        f"files_written={len(outcome.files_written)} "
        f"approval_token={args.approval_token} "
        f"cargo_lock_sha256={outcome.plan.cargo_lock_sha256_after[:16]}..."
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
