#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Wire the Welle-7 audit-trail-anchor for the persona-engine producer.

Tag-75 Welle-7 Audit-Trail-Anchor-Integration (Tomás, Cross-Review-
Zone-K). FINAL Welle of the Phase-3c-Welle-Marathon. Mirror of the
Tag-69..Tag-74 ``wire_welle_*`` helpers, parameterised to Welle-7
(KW-27 Doppel-Welle-6+7 entry, Cutover-Mittwoch 2026-07-01, Sign-
off-Freitag 2026-07-03 = Global Acceptance-Verdict per
``docs/quality-gates/pre-cutover-acceptance-run-order.md`` §3.2).

Cross-coord with Selin (Tag-75 Welle-7 producer):

  * Tomás (this module): hash-construction over the canonical
    Welle-7 bundle, envelope emit, Phase-3-Final-Sealing-Tracking
    surface, Pre-Auditor-Final-Sealing-Signaling-Markers. Stdlib-
    only. No OTS calendar call.
  * Selin (engine.py, welle=7 path): triggers on Final-Sealing-
    Smoke-Green, calls this helper for the hash-side, writes the
    result into ``state/welle-7.json:audit_trail_anchor``.

The hash construction matches
``emit_manifest_hash_ots_marker.compute_welle_7_audit_anchor_hash``
exactly — the two entry points use the same underlying function via
import. Kept separate from the Tag-69..Tag-74 ``wire_welle_*``
helpers to keep the producer-facing surface narrow (one envelope
kind per welle) and to permit a future welle-specific divergence
without forcing a shared-helper refactor.

Cross-Substrate-Parity-Markers
------------------------------

The envelope's ``anchors`` block surfaces the Welle-1..6 cross-coord
PR references plus a ``cross_substrate_parity_markers`` list, so a
downstream consumer can trace the full Welle-1..7 audit-anchor
lineage from a single envelope (Welle-1..7-Kind-Disjointness-Pin:
identical hash recipe across all seven Wellen, distinct marker /
envelope kind strings per Welle).

Phase-3-Final-Sealing-Tracking
------------------------------

Welle-7 is the FINAL Welle of the Phase-3c-Welle-Marathon. The
envelope exposes a ``phase_3_final_sealing_tracking`` block so the
downstream observability surface can dispatch the Final-Sealing
gate (and Henrik's Zone-N Audit-Evidence-Index can pin Phase-3-
COMPLETE-marker readiness) without re-reading the bundle. **No
enforcement here** — the helper only surfaces tracking; the gate
itself lives in Henrik's Internal-Audit + Amara's QA workflows.

Pre-Auditor-Final-Sealing-Signaling-Markers
-------------------------------------------

The envelope carries TWO pre-auditor signaling flags:

  * ``pre_auditor_signaling_ready`` — True iff a pre-auditor-
    decision is present in the bundle (mirror of Welle-3 flag).
  * ``pre_auditor_final_sealing_signaling_ready`` — True iff
    pre-auditor-decision is present AND the final-sealing-
    tracking block reports ``global_acceptance_verdict_recorded
    == True``. This is the canonical Tomás -> Henrik hand-off
    signal for Phase-3-COMPLETE-marker readiness at Post-Welle-7
    sign-off (per pre-cutover-acceptance-run-order doc §7.2:
    Phase-3-COMPLETE-marker fires iff Global Verdict == GREEN).

Sandbox-boundary
----------------

stdlib only. ``argparse``, ``json``, ``pathlib``, ``datetime``,
``os``, ``sys``. No third-party imports. No network. No subprocess.
No filesystem writes outside ``--envelope-out``.

Usage (CLI)
-----------

::

    python3 tooling/ci/wire_welle_7_audit_trail_anchor.py \\
        --welle-7-rollup    state/welle-7.json \\
        --welle-7-sign-off  state/welle-7-sign-off.json \\
        --welle-7-validation state/welle-7-validation-last-verdict.json \\
        --welle-7-pre-auditor state/welle-7-pre-auditor-decision.json \\
        --envelope-out tooling/ots/markers/welle-7-audit-anchor.json

Envelope shape (schema v1)
--------------------------

::

  {
    "schema_version": 1,
    "kind": "welle-7-audit-trail-anchor-producer-envelope",
    "welle_number": 7,
    "audit_trail_anchor": "<64-hex SHA-256>",
    "bundle_keys": ["rollup", "sign_off", ...],
    "bundle_paths": { ... },
    "phase_3_final_sealing_tracking": {
      "phase_3_final_sealing_active": bool,
      "phase_3_final_sealing_status":
          "pending|sealed|escalated|unknown",
      "phase_3_final_sealing_iso": "<iso-or-empty>",
      "global_acceptance_verdict_recorded": bool,
      "phase_3_complete_marker_ready": bool,
      "phase_3_final_sealing_evidence_ref": "<free-form-or-empty>"
    },
    "pre_auditor_signaling_ready": bool,
    "pre_auditor_final_sealing_signaling_ready": bool,
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
    """Import the Tag-57/Tag-69..Tag-75 OTS-emit module."""
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


ENVELOPE_KIND: str = "welle-7-audit-trail-anchor-producer-envelope"
WELLE_NUMBER: int = 7


def build_envelope(
    *,
    bundle: dict,
    bundle_paths: dict,
    anchor_hash: str,
    actor: str,
    now_utc: _dt.datetime,
    phase_3_final_sealing_tracking: dict,
    pre_auditor_signaling_ready: bool,
    pre_auditor_final_sealing_signaling_ready: bool,
) -> dict:
    """Assemble the producer-facing envelope dict.

    ``phase_3_final_sealing_tracking`` is the derived Welle-7 tracking
    block (see emit_helper.derive_phase_3_final_sealing_tracking). The
    block is surfaced on the envelope so Selin's producer + the
    downstream observability surface can dispatch the Final-Sealing
    gate without re-reading the bundle.

    ``pre_auditor_signaling_ready`` and
    ``pre_auditor_final_sealing_signaling_ready`` are the two
    Tag-75-discipline pre-auditor signaling flags (see module
    docstring §Pre-Auditor-Final-Sealing-Signaling-Markers).
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
        "phase_3_final_sealing_tracking": dict(
            phase_3_final_sealing_tracking
        ),
        "pre_auditor_signaling_ready": pre_auditor_signaling_ready,
        "pre_auditor_final_sealing_signaling_ready": (
            pre_auditor_final_sealing_signaling_ready
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
            "tomas_tag_74_welle_6_audit_anchor_pr": 470,
            "selin_producer_plan": (
                "docs/persona-engine/state-file-producer-wiring-plan.md"
            ),
            "state_file_conventions_doc": (
                "docs/quality-gates/welle-n-state-file-conventions.md"
            ),
            "pre_cutover_acceptance_run_order_doc": (
                "docs/quality-gates/pre-cutover-acceptance-run-order.md"
            ),
            "phase_3_marathon_final_acceptance_doc": (
                "docs/quality-gates/phase-3-marathon-final-acceptance.md"
            ),
            "amara_tag_67_state_file_conventions_pr": 429,
            "welle_7_context": "phase-3-final-sealing-cutover-kw27",
            "welle_7_cutover_date": "2026-07-01",
            "welle_7_sign_off_date": "2026-07-03",
            "phase_3_final_sealing_discipline": (
                "tag-75-final-welle-global-acceptance-verdict-recording"
            ),
            "cross_substrate_parity_markers": [
                "welle-1",
                "welle-2",
                "welle-3",
                "welle-4",
                "welle-5",
                "welle-6",
                "welle-7",
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
    """Load the Welle-7 bundle, compute the anchor, return the envelope.

    This is the importable Python entry-point for tests and for
    Selin's Tag-75 producer (which can in principle import this
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

    bundle = emit_module.load_welle_7_bundle(
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

    anchor_hash = emit_module.compute_welle_7_audit_anchor_hash(bundle)
    tracking = emit_module.derive_phase_3_final_sealing_tracking(bundle)

    pre_auditor_present = "pre_auditor" in bundle and isinstance(
        bundle.get("pre_auditor"), dict
    )
    final_sealing_signaling_ready = bool(
        pre_auditor_present
        and tracking["global_acceptance_verdict_recorded"]
    )

    return build_envelope(
        bundle=bundle,
        bundle_paths=bundle_paths,
        anchor_hash=anchor_hash,
        actor=actor,
        now_utc=now_utc,
        phase_3_final_sealing_tracking=tracking,
        pre_auditor_signaling_ready=pre_auditor_present,
        pre_auditor_final_sealing_signaling_ready=(
            final_sealing_signaling_ready
        ),
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wire_welle_7_audit_trail_anchor",
        description=(
            "Compute the Welle-7 audit-trail-anchor SHA-256 from the "
            "sign-off-record bundle and emit a producer-facing envelope "
            "for Selin's Tag-75 persona-engine batch-writer (FINAL "
            "Welle of the Phase-3c-Welle-Marathon, KW-27 Doppel-Welle-"
            "6+7 entry, Sign-off-Freitag 2026-07-03 = Global "
            "Acceptance-Verdict). Surfaces the Phase-3-Final-Sealing-"
            "Tracking block + Pre-Auditor-Final-Sealing-Signaling-"
            "Markers (Tomás -> Henrik hand-off for Phase-3-COMPLETE-"
            "marker readiness)."
        ),
    )
    parser.add_argument(
        "--welle-7-rollup",
        type=Path,
        required=True,
        help="Path to state/welle-7.json (rollup state-file).",
    )
    parser.add_argument(
        "--welle-7-sign-off",
        type=Path,
        required=True,
        help="Path to state/welle-7-sign-off.json.",
    )
    parser.add_argument(
        "--welle-7-validation",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-7-validation-last-verdict.json "
            "(optional)."
        ),
    )
    parser.add_argument(
        "--welle-7-pre-auditor",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-7-pre-auditor-decision.json "
            "(optional; recommended for Phase-3-COMPLETE-marker "
            "readiness signaling)."
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

    if not args.welle_7_rollup.is_file():
        print(
            f"wire_welle_7_audit_trail_anchor: --welle-7-rollup not "
            f"a file: {args.welle_7_rollup}",
            file=sys.stderr,
        )
        return 1
    if not args.welle_7_sign_off.is_file():
        print(
            f"wire_welle_7_audit_trail_anchor: --welle-7-sign-off not "
            f"a file: {args.welle_7_sign_off}",
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
            rollup_path=args.welle_7_rollup,
            sign_off_path=args.welle_7_sign_off,
            validation_path=args.welle_7_validation,
            pre_auditor_path=args.welle_7_pre_auditor,
            actor=args.actor,
            now_utc=now_utc,
        )
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"wire_welle_7_audit_trail_anchor: bundle read/parse "
            f"error: {exc}",
            file=sys.stderr,
        )
        return 1
    except ValueError as exc:
        print(
            f"wire_welle_7_audit_trail_anchor: bundle shape error: "
            f"{exc}",
            file=sys.stderr,
        )
        return 1

    args.envelope_out.parent.mkdir(parents=True, exist_ok=True)
    args.envelope_out.write_text(
        json.dumps(envelope, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    tracking = envelope["phase_3_final_sealing_tracking"]
    print(
        f"wire_welle_7_audit_trail_anchor: welle=7 "
        f"audit_trail_anchor={envelope['audit_trail_anchor']} "
        f"bundle_keys={envelope['bundle_keys']} "
        f"phase_3_final_sealing_active="
        f"{tracking['phase_3_final_sealing_active']} "
        f"phase_3_final_sealing_status="
        f"{tracking['phase_3_final_sealing_status']} "
        f"global_acceptance_verdict_recorded="
        f"{tracking['global_acceptance_verdict_recorded']} "
        f"phase_3_complete_marker_ready="
        f"{tracking['phase_3_complete_marker_ready']} "
        f"pre_auditor_final_sealing_signaling_ready="
        f"{envelope['pre_auditor_final_sealing_signaling_ready']} "
        f"-> {args.envelope_out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
