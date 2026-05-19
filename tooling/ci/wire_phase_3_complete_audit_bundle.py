#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Wire the Phase-3-COMPLETE-marker audit-bundle for Marathon-Closeout.

Tag-76 Marathon-Closeout-Audit-Anchor-Bundle (Tomás, Cross-Review-
Zone-N hand-off). Consolidates the seven Welle-N audit-anchor markers
(outputs of the Tag-69..Tag-75 ``wire_welle_*`` helpers) into a single
Phase-3-COMPLETE-marker that Henrik's Zone-N Audit-Evidence-Index
ingests as the canonical Phase-3-COMPLETE hand-off envelope.

This is the consumer-facing pendant to ``wire_welle_7_audit_trail_anchor.py``
(which closed the per-Welle producer surface). Where the welle-N
helpers each produce ONE marker per Welle, this helper consumes ALL
seven markers and produces the Marathon-Closeout envelope.

Cross-coord with Henrik (Zone-N Audit-Evidence-Index):

  * Tomás (this module): bundle-anchor construction over the seven
    canonical Welle-1..7 audit-anchor markers, envelope emit,
    Welle-1..7-Kind-Disjointness-Pin enforcement at ingest, Phase-3-
    Final-Sealing-Tracking surface, Pre-Auditor-Final-Sealing-
    Signaling-Ready surface. Stdlib-only. No OTS calendar call.
  * Henrik (Zone-N consumer): reads the Phase-3-COMPLETE marker as
    the Marathon-Closeout hand-off file, dispatches the Audit-
    Evidence-Index Phase-3-COMPLETE entry, archives the bundle
    anchor as the Marathon-Closeout-Anchor of record.

The bundle hash construction matches ``emit_manifest_hash_ots_marker.
compute_phase_3_complete_bundle_anchor`` exactly -- this helper
imports the underlying function rather than reimplementing it, so
the two entry points (CLI ``--mode phase-3-complete-marker`` and
this wire helper) always agree.

Welle-1..7-Kind-Disjointness-Pin
--------------------------------

The seven input markers must:

  * cover ``welle_number`` 1..7 exactly with no duplicates and no
    gaps,
  * carry the expected ``kind`` string for their welle_number
    (``welle-N-audit-trail-anchor-marker``),
  * carry a 64-hex ``audit_trail_anchor``.

Any deviation raises ValueError at ingest -- BEFORE the bundle hash
is computed -- via ``assert_welle_1_7_kind_disjointness_pin``. This
keeps the closeout-bundle anchor stable: a malformed input never
ends up baked into a bundle hash that gets recorded as a Marathon-
Closeout-Anchor of record.

Phase-3-Final-Sealing-Tracking surface
--------------------------------------

The envelope's ``phase_3_final_sealing_tracking`` block is sourced
from the Welle-7 marker (markers[-1] after sort by ``welle_number``).
This surface lets Henrik's Zone-N Audit-Evidence-Index dispatch the
Phase-3-COMPLETE entry without re-reading the underlying Welle-7
bundle.

Pre-Auditor-Final-Sealing-Signaling-Ready surface
-------------------------------------------------

Mirrors the Tag-75 ``pre_auditor_final_sealing_signaling_ready``
flag from the Welle-7 marker. True iff Welle-7 had a pre-auditor-
decision present AND ``global_acceptance_verdict_recorded == True``.
This is the canonical Tomás -> Henrik hand-off signal for Phase-3-
COMPLETE-marker readiness (per pre-cutover-acceptance-run-order doc
§7.2: Phase-3-COMPLETE-marker fires iff Global Verdict == GREEN).

Sandbox-boundary
----------------

stdlib only. ``argparse``, ``json``, ``pathlib``, ``datetime``,
``os``, ``sys``. No third-party imports. No network. No subprocess.
No filesystem writes outside ``--envelope-out``.

Usage (CLI)
-----------

::

    python3 tooling/ci/wire_phase_3_complete_audit_bundle.py \\
        --welle-1-marker tooling/ots/markers/welle-1-audit-anchor.json \\
        --welle-2-marker tooling/ots/markers/welle-2-audit-anchor.json \\
        --welle-3-marker tooling/ots/markers/welle-3-audit-anchor.json \\
        --welle-4-marker tooling/ots/markers/welle-4-audit-anchor.json \\
        --welle-5-marker tooling/ots/markers/welle-5-audit-anchor.json \\
        --welle-6-marker tooling/ots/markers/welle-6-audit-anchor.json \\
        --welle-7-marker tooling/ots/markers/welle-7-audit-anchor.json \\
        --envelope-out tooling/ots/markers/phase-3-complete-marker.json

Envelope shape (schema v1)
--------------------------

::

  {
    "schema_version": 1,
    "kind": "phase-3-complete-marker-producer-envelope",
    "phase_3_complete_bundle_anchor": "<64-hex>",
    "welle_bundle_count": 7,
    "welle_bundle_anchors": [
      {"welle_number": N, "kind": "...", "audit_trail_anchor": "..."}
    ],
    "welle_marker_paths": { ... },
    "phase_3_final_sealing_tracking": { ... },  // from welle-7
    "global_acceptance_verdict_recorded": bool,
    "phase_3_complete_marker_ready": bool,
    "pre_auditor_final_sealing_signaling_ready": bool,
    "welle_1_7_kind_disjointness_pin_ok": true,
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

  * 0 -- envelope emitted successfully.
  * 1 -- bundle file missing / unreadable / malformed JSON /
        disjointness-pin violation.
  * 2 -- usage error.

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
    """Import the Tag-57/Tag-69..Tag-76 OTS-emit module."""
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


ENVELOPE_KIND: str = "phase-3-complete-marker-producer-envelope"
WELLE_COUNT: int = 7


def build_envelope(
    *,
    markers: list[dict],
    welle_marker_paths: dict[str, str],
    bundle_anchor: str,
    actor: str,
    now_utc: _dt.datetime,
) -> dict:
    """Assemble the Phase-3-COMPLETE producer-facing envelope dict.

    ``markers`` is the sorted list of seven Welle-N audit-anchor
    markers (sorted by ``welle_number`` ascending) that has already
    passed ``assert_welle_1_7_kind_disjointness_pin``.

    ``welle_marker_paths`` is a {"welle-1": str, ...} mapping of the
    source paths -- emitted for Henrik's Zone-N audit trail.
    """
    iso_now = now_utc.isoformat()
    # markers[-1] is welle-7 after sort.
    welle_7 = markers[-1]
    tracking = welle_7.get(
        "phase_3_final_sealing_tracking",
        {
            "phase_3_final_sealing_active": False,
            "phase_3_final_sealing_status": "unknown",
            "phase_3_final_sealing_iso": "",
            "global_acceptance_verdict_recorded": False,
            "phase_3_complete_marker_ready": False,
            "phase_3_final_sealing_evidence_ref": "",
        },
    )
    global_acceptance = bool(
        tracking.get("global_acceptance_verdict_recorded", False)
    )
    complete_ready = bool(
        tracking.get("phase_3_complete_marker_ready", False)
    )
    pre_auditor_final_sealing = bool(
        welle_7.get("pre_auditor_final_sealing_signaling_ready", False)
    )
    bundle_anchors = [
        {
            "welle_number": m.get("welle_number"),
            "kind": m.get("kind"),
            "audit_trail_anchor": m.get("audit_trail_anchor"),
        }
        for m in markers
    ]
    return {
        "schema_version": 1,
        "kind": ENVELOPE_KIND,
        "phase_3_complete_bundle_anchor": bundle_anchor,
        "welle_bundle_count": WELLE_COUNT,
        "welle_bundle_anchors": bundle_anchors,
        "welle_marker_paths": dict(welle_marker_paths),
        "phase_3_final_sealing_tracking": dict(tracking),
        "global_acceptance_verdict_recorded": global_acceptance,
        "phase_3_complete_marker_ready": complete_ready,
        "pre_auditor_final_sealing_signaling_ready": (
            pre_auditor_final_sealing
        ),
        "welle_1_7_kind_disjointness_pin_ok": True,
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
            "tomas_tag_75_welle_7_audit_anchor_pr": 477,
            "tomas_tag_76_closeout_bundle_pr": None,
            "henrik_zone_n_audit_evidence_index_consumer": (
                "internal-audit/zone-n-audit-evidence-index"
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
            "marathon_closeout_context": (
                "phase-3-marathon-closeout-audit-anchor-bundle"
            ),
            "phase_3_complete_marker_discipline": (
                "tag-76-marathon-closeout-bundle-handoff-to-henrik-"
                "zone-n-audit-evidence-index"
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
    welle_marker_paths: list[Path],
    actor: str,
    now_utc: _dt.datetime,
) -> dict:
    """Load seven Welle markers, compute the bundle anchor, return envelope.

    This is the importable Python entry-point for tests and for
    Henrik's Zone-N consumer (which can import this directly rather
    than shell out).

    Order of ``welle_marker_paths`` is irrelevant: the loader sorts
    by ``welle_number`` ascending before the hash is computed.
    """
    emit_module = _import_emit_helper()

    markers = emit_module.load_phase_3_complete_bundle(
        welle_marker_paths=welle_marker_paths,
    )
    emit_module.assert_welle_1_7_kind_disjointness_pin(markers)
    bundle_anchor = emit_module.compute_phase_3_complete_bundle_anchor(
        markers
    )

    paths_dict: dict[str, str] = {}
    for path, marker in zip(welle_marker_paths, markers):
        # NOTE: zip order matches input order, NOT sort order. We
        # store paths keyed by the marker's welle_number so the
        # output mapping is stable regardless of caller order.
        pass
    # Re-derive paths_dict by sort-order to keep the envelope
    # byte-stable. The input ``welle_marker_paths`` order maps 1:1
    # to the loader's internal list-order (which is preserved before
    # sort), but we want the output keyed by welle_number, so we
    # iterate the sorted ``markers`` and match each marker back to
    # its source path by welle_number.
    paths_dict = {}
    # Build a {welle_number: path} mapping by re-reading welle_number
    # from each input file. This is safe because the loader already
    # verified the files are well-formed JSON dicts.
    for path in welle_marker_paths:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            wn = doc.get("welle_number")
            if isinstance(wn, int):
                paths_dict[f"welle-{wn}"] = str(path)
        except (OSError, json.JSONDecodeError):
            # Already validated by the loader -- defensive only.
            continue

    return build_envelope(
        markers=markers,
        welle_marker_paths=paths_dict,
        bundle_anchor=bundle_anchor,
        actor=actor,
        now_utc=now_utc,
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wire_phase_3_complete_audit_bundle",
        description=(
            "Compute the Phase-3-COMPLETE-bundle anchor SHA-256 from "
            "the seven Welle-1..7 audit-anchor markers and emit a "
            "producer-facing envelope for Henrik's Zone-N Audit-"
            "Evidence-Index consumer (Tag-76 Marathon-Closeout-Audit-"
            "Anchor-Bundle, hand-off envelope for Phase-3-COMPLETE-"
            "marker readiness). Enforces the Welle-1..7-Kind-"
            "Disjointness-Pin at ingest. Surfaces Phase-3-Final-"
            "Sealing-Tracking + global-acceptance-verdict-recorded + "
            "Phase-3-COMPLETE-marker-ready + Pre-Auditor-Final-"
            "Sealing-Signaling-Ready (all sourced from welle-7)."
        ),
    )
    for n in (1, 2, 3, 4, 5, 6, 7):
        parser.add_argument(
            f"--welle-{n}-marker",
            type=Path,
            required=True,
            help=(
                f"Path to the Welle-{n} audit-anchor marker JSON "
                f"(emitted by --mode welle-{n}-audit-anchor of "
                f"emit_manifest_hash_ots_marker.py)."
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

    welle_paths = [
        args.welle_1_marker,
        args.welle_2_marker,
        args.welle_3_marker,
        args.welle_4_marker,
        args.welle_5_marker,
        args.welle_6_marker,
        args.welle_7_marker,
    ]

    for path in welle_paths:
        if not path.is_file():
            print(
                f"wire_phase_3_complete_audit_bundle: welle marker "
                f"file missing: {path}",
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
            welle_marker_paths=welle_paths,
            actor=args.actor,
            now_utc=now_utc,
        )
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"wire_phase_3_complete_audit_bundle: bundle "
            f"read/parse error: {exc}",
            file=sys.stderr,
        )
        return 1
    except ValueError as exc:
        print(
            f"wire_phase_3_complete_audit_bundle: bundle shape / "
            f"disjointness-pin error: {exc}",
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
        f"wire_phase_3_complete_audit_bundle: "
        f"phase_3_complete_bundle_anchor="
        f"{envelope['phase_3_complete_bundle_anchor']} "
        f"welle_bundle_count={envelope['welle_bundle_count']} "
        f"phase_3_final_sealing_status="
        f"{tracking['phase_3_final_sealing_status']} "
        f"global_acceptance_verdict_recorded="
        f"{tracking['global_acceptance_verdict_recorded']} "
        f"phase_3_complete_marker_ready="
        f"{tracking['phase_3_complete_marker_ready']} "
        f"pre_auditor_final_sealing_signaling_ready="
        f"{envelope['pre_auditor_final_sealing_signaling_ready']} "
        f"welle_1_7_kind_disjointness_pin_ok="
        f"{envelope['welle_1_7_kind_disjointness_pin_ok']} "
        f"-> {args.envelope_out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
