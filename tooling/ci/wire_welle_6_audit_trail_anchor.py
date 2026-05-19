#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Wire the Welle-6 audit-trail-anchor for the persona-engine producer.

Tag-74 Welle-6 State-File Audit-Trail-Anchor-Integration (Tomás,
Cross-Review-Zone-K). Mirror of the Tag-69 Welle-1 / Tag-70 Welle-2 /
Tag-71 Welle-3 / Tag-72 Welle-4 / Tag-73 Welle-5 helpers, parameterised
to Welle-6 (``subscribe_loop`` Cutover, KW-27, parallel to Welle-7).

Cross-coord with Selin (Tag-74 Welle-6 producer):

  * Tomás (this module): hash-construction over the canonical
    Welle-6 bundle, envelope emit, subscribe-loop Self-Repair-Hygiene
    tracking surface. Stdlib-only. No OTS calendar call.
  * Selin (engine.py, welle=6 path): triggers on subscribe_loop
    Cutover-Smoke-Green, calls this helper for the hash-side, writes
    the result into ``state/welle-6.json:audit_trail_anchor``.

The hash construction matches
``emit_manifest_hash_ots_marker.compute_welle_6_audit_anchor_hash``
exactly — the two entry points use the same underlying function via
import. Kept separate from the Tag-69 / Tag-70 / Tag-71 / Tag-72 /
Tag-73 ``wire_welle_*`` helpers to keep the producer-facing surface
narrow (one envelope kind per welle) and to permit a future welle-
specific divergence without forcing a shared-helper refactor.

Cross-Substrate-Parity-Markers
------------------------------

The envelope's ``anchors`` block surfaces the Welle-1..5 cross-coord
PR references plus a ``cross_substrate_parity_markers`` list, so a
downstream consumer can trace the full Welle-1..6 audit-anchor
lineage from a single envelope (Tag-74 auftrag).

Subscribe-Loop-Self-Repair-Hygiene-Tracking
-------------------------------------------

Welle-6 carries the subscribe-loop Self-Repair-Hygiene discipline
(Tag-73-Lehre: PR #461 cross-Persona Self-Repair-Hygiene-Fix
carries through to Welle-6 ``subscribe_loop`` Cutover). The envelope
exposes a ``subscribe_loop_self_repair_hygiene_tracking`` block so
the downstream observability surface can dispatch the hygiene-
discipline gate without re-reading the bundle. **No enforcement
here** — the helper only surfaces tracking; the gate itself lives
in Henrik's Internal-Audit + Reza-Identity-Substrate workflows.

Sandbox-boundary
----------------

stdlib only. ``argparse``, ``json``, ``pathlib``, ``datetime``,
``os``, ``sys``. No third-party imports. No network. No subprocess.
No filesystem writes outside ``--envelope-out``.

Usage (CLI)
-----------

::

    python3 tooling/ci/wire_welle_6_audit_trail_anchor.py \\
        --welle-6-rollup    state/welle-6.json \\
        --welle-6-sign-off  state/welle-6-sign-off.json \\
        --welle-6-validation state/welle-6-validation-last-verdict.json \\
        --welle-6-pre-auditor state/welle-6-pre-auditor-decision.json \\
        --envelope-out tooling/ots/markers/welle-6-audit-anchor.json

Envelope shape (schema v1)
--------------------------

::

  {
    "schema_version": 1,
    "kind": "welle-6-audit-trail-anchor-producer-envelope",
    "welle_number": 6,
    "audit_trail_anchor": "<64-hex SHA-256>",
    "bundle_keys": ["rollup", "sign_off", ...],
    "bundle_paths": { ... },
    "subscribe_loop_self_repair_hygiene_tracking": {
      "subscribe_loop_self_repair_hygiene_active": bool,
      "subscribe_loop_self_repair_hygiene_status":
          "pending|drilled|exempt|unknown",
      "subscribe_loop_last_hygiene_cycle_iso": "<iso-or-empty>",
      "subscribe_loop_re_subscribe_window_closed": bool,
      "subscribe_loop_self_repair_hygiene_evidence_ref":
          "<free-form-or-empty>"
    },
    "emitted_at_utc": "<iso>",
    "actor": "<actor>",
    "anchors": { ... },
    "sandbox_boundary": {
      "no_network_io": true,
      "no_ots_cli_subprocess": true,
      "stdlib_only": true
    }
  }

Exit codes
----------

  * 0 — envelope emitted successfully.
  * 1 — bundle file missing / unreadable / malformed JSON.
  * 2 — usage error.

Author: Tomás Reinhart (dev-engineering, Matrix-Lead).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path
from typing import Iterable


# Path-shimmed import: this helper sits in tooling/ci/, the hash
# function sits in tooling/ots/. We add the repo root to sys.path
# on demand so the import resolves regardless of cwd.
def _import_emit_helper():
    """Import the Tag-57/Tag-69..Tag-74 OTS-emit module."""
    here = Path(__file__).resolve()
    repo_root = here.parent.parent.parent  # tooling/ci/... -> repo root
    ots_dir = repo_root / "tooling" / "ots"
    sys.path.insert(0, str(ots_dir))
    try:
        import emit_manifest_hash_ots_marker as _emit  # type: ignore
    finally:
        # Defensive: keep sys.path tidy if the import succeeded.
        if str(ots_dir) in sys.path:
            sys.path.remove(str(ots_dir))
    return _emit


ENVELOPE_KIND: str = "welle-6-audit-trail-anchor-producer-envelope"
WELLE_NUMBER: int = 6


def build_envelope(
    *,
    bundle: dict,
    bundle_paths: dict,
    anchor_hash: str,
    actor: str,
    now_utc: _dt.datetime,
    subscribe_loop_self_repair_hygiene_tracking: dict,
) -> dict:
    """Assemble the producer-facing envelope dict.

    ``subscribe_loop_self_repair_hygiene_tracking`` is the derived
    Welle-6 tracking block (see emit_helper.derive_subscribe_loop_
    self_repair_hygiene_tracking). The block is surfaced on the
    envelope so Selin's producer + the downstream observability
    surface can dispatch the hygiene-discipline gate without
    re-reading the bundle.
    """
    iso_now = now_utc.isoformat()
    # Order-stable bundle_keys for downstream byte-stability.
    bundle_keys = sorted(bundle.keys())
    return {
        "schema_version": 1,
        "kind": ENVELOPE_KIND,
        "welle_number": WELLE_NUMBER,
        "audit_trail_anchor": anchor_hash,
        "bundle_keys": bundle_keys,
        "bundle_paths": {k: bundle_paths[k] for k in bundle_keys},
        "subscribe_loop_self_repair_hygiene_tracking": dict(
            subscribe_loop_self_repair_hygiene_tracking
        ),
        "emitted_at_utc": iso_now,
        "actor": actor,
        "anchors": {
            "tomas_emit_helper": (
                "tooling/ots/emit_manifest_hash_ots_marker.py"
            ),
            "tomas_tag_69_welle_1_audit_anchor_pr": 439,
            "tomas_tag_70_welle_2_audit_anchor_pr": 445,
            "tomas_tag_71_welle_3_audit_anchor_pr": 450,
            "tomas_tag_72_welle_4_audit_anchor_pr": 457,
            "tomas_tag_73_welle_5_audit_anchor_pr": 464,
            "selin_producer_plan": (
                "docs/persona-engine/state-file-producer-wiring-plan.md"
            ),
            "state_file_conventions_doc": (
                "docs/quality-gates/welle-n-state-file-conventions.md"
            ),
            "amara_tag_67_state_file_conventions_pr": 429,
            "welle_6_context": "subscribe-loop-cutover-kw27",
            "welle_6_runbook": (
                "docs/operations/phase-3c-welle-6-runbook.md"
            ),
            "subscribe_loop_self_repair_hygiene_discipline": (
                "tag-73-lehre-pr-461-cross-persona-self-repair-hygiene-fix"
            ),
            "cross_substrate_parity_markers": [
                "welle-1",
                "welle-2",
                "welle-3",
                "welle-4",
                "welle-5",
                "welle-6",
            ],
        },
        "sandbox_boundary": {
            "no_network_io": True,
            "no_ots_cli_subprocess": True,
            "stdlib_only": True,
        },
    }


def emit_envelope(
    *,
    rollup_path: Path,
    sign_off_path: Path,
    validation_path: Path | None,
    pre_auditor_path: Path | None,
    actor: str,
    now_utc: _dt.datetime,
) -> dict:
    """Load the Welle-6 bundle, compute the anchor, return the envelope.

    This is the importable Python entry-point for tests and for
    Selin's Tag-74 producer (which can in principle import this
    directly rather than shell out).
    """
    emit_module = _import_emit_helper()

    val_path = (
        validation_path
        if validation_path is not None and validation_path.is_file()
        else None
    )
    pre_path = (
        pre_auditor_path
        if pre_auditor_path is not None and pre_auditor_path.is_file()
        else None
    )

    bundle = emit_module.load_welle_6_bundle(
        rollup_path=rollup_path,
        sign_off_path=sign_off_path,
        validation_path=val_path,
        pre_auditor_path=pre_path,
    )

    bundle_paths: dict = {
        "rollup": str(rollup_path),
        "sign_off": str(sign_off_path),
    }
    if val_path is not None:
        bundle_paths["validation"] = str(val_path)
    if pre_path is not None:
        bundle_paths["pre_auditor"] = str(pre_path)

    anchor_hash = emit_module.compute_welle_6_audit_anchor_hash(bundle)
    tracking = emit_module.derive_subscribe_loop_self_repair_hygiene_tracking(
        bundle
    )

    return build_envelope(
        bundle=bundle,
        bundle_paths=bundle_paths,
        anchor_hash=anchor_hash,
        actor=actor,
        now_utc=now_utc,
        subscribe_loop_self_repair_hygiene_tracking=tracking,
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wire_welle_6_audit_trail_anchor",
        description=(
            "Compute the Welle-6 audit-trail-anchor SHA-256 from the "
            "sign-off-record bundle and emit a producer-facing envelope "
            "for Selin's Tag-74 persona-engine batch-writer "
            "(subscribe_loop Cutover, KW-27). Surfaces the subscribe-"
            "loop Self-Repair-Hygiene-Tracking block (Tag-73-Lehre, "
            "PR #461)."
        ),
    )
    parser.add_argument(
        "--welle-6-rollup",
        type=Path,
        required=True,
        help="Path to state/welle-6.json (rollup state-file).",
    )
    parser.add_argument(
        "--welle-6-sign-off",
        type=Path,
        required=True,
        help="Path to state/welle-6-sign-off.json.",
    )
    parser.add_argument(
        "--welle-6-validation",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-6-validation-last-verdict.json "
            "(optional)."
        ),
    )
    parser.add_argument(
        "--welle-6-pre-auditor",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-6-pre-auditor-decision.json "
            "(optional)."
        ),
    )
    parser.add_argument(
        "--envelope-out",
        type=Path,
        required=True,
        help=(
            "Output JSON envelope path. Parent dir will be mkdir -p'd."
        ),
    )
    parser.add_argument(
        "--actor",
        default=os.environ.get("GITHUB_ACTOR", "local"),
        help="Actor identifier (default: $GITHUB_ACTOR or 'local').",
    )
    parser.add_argument(
        "--now",
        default=None,
        help=(
            "Override emitted_at_utc (ISO-8601). Useful for "
            "deterministic tests."
        ),
    )

    args = parser.parse_args(list(argv) if argv is not None else None)

    if not args.welle_6_rollup.is_file():
        print(
            f"wire_welle_6_audit_trail_anchor: --welle-6-rollup not "
            f"a file: {args.welle_6_rollup}",
            file=sys.stderr,
        )
        return 1
    if not args.welle_6_sign_off.is_file():
        print(
            f"wire_welle_6_audit_trail_anchor: --welle-6-sign-off not "
            f"a file: {args.welle_6_sign_off}",
            file=sys.stderr,
        )
        return 1

    if args.now is None:
        now_utc = _dt.datetime.now(_dt.timezone.utc)
    else:
        now_utc = _dt.datetime.fromisoformat(args.now)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=_dt.timezone.utc)

    try:
        envelope = emit_envelope(
            rollup_path=args.welle_6_rollup,
            sign_off_path=args.welle_6_sign_off,
            validation_path=args.welle_6_validation,
            pre_auditor_path=args.welle_6_pre_auditor,
            actor=args.actor,
            now_utc=now_utc,
        )
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"wire_welle_6_audit_trail_anchor: bundle read/parse "
            f"error: {exc}",
            file=sys.stderr,
        )
        return 1
    except ValueError as exc:
        print(
            f"wire_welle_6_audit_trail_anchor: bundle shape error: "
            f"{exc}",
            file=sys.stderr,
        )
        return 1

    args.envelope_out.parent.mkdir(parents=True, exist_ok=True)
    args.envelope_out.write_text(
        json.dumps(envelope, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    tracking = envelope["subscribe_loop_self_repair_hygiene_tracking"]
    print(
        f"wire_welle_6_audit_trail_anchor: welle=6 "
        f"audit_trail_anchor={envelope['audit_trail_anchor']} "
        f"bundle_keys={envelope['bundle_keys']} "
        f"subscribe_loop_self_repair_hygiene_active="
        f"{tracking['subscribe_loop_self_repair_hygiene_active']} "
        f"subscribe_loop_self_repair_hygiene_status="
        f"{tracking['subscribe_loop_self_repair_hygiene_status']} "
        f"subscribe_loop_re_subscribe_window_closed="
        f"{tracking['subscribe_loop_re_subscribe_window_closed']} "
        f"-> {args.envelope_out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
