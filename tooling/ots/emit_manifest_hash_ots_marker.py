#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Emit an OTS-anchor stub marker for a persona-engine manifest hash.

Tag-57 OPEN-K2 closeout (from Selin's Tag-56 0.5.2-final audit, PR #362):

  > OPEN-K2: OTS-anchor of manifest hash via WAT spool (Tomás Zone-K)

This helper is the **audit-only stub** for the future OTS-anchor wiring
of persona-engine manifest hashes via the WAT spool. It computes the
SHA-256 of a manifest file (e.g. ``MANIFEST-0.5.2-final-pre-cutover.md``),
records the intent-to-anchor in a marker JSON file under
``tooling/ots/markers/``, and emits a WAT-spool envelope describing the
anchor request.

**Audit-only.** This helper does NOT call out to an OpenTimestamps
calendar server. The Sandbox-boundary is explicitly preserved:

  * No network I/O.
  * No subprocess calls to ``ots`` CLI.
  * No filesystem writes outside the marker output directory.

The Operator-Hand picks up the marker file in a later runbook step
and runs the real ``ots stamp`` invocation on a host that has network
access to the OTS calendar. The marker file then gets the real
``.ots`` proof attached (out-of-band, Phase-3c-Schritt-N+1).

Tag-59 Pre-Activation-Probe extension
-------------------------------------

The ``--mode pre-activation-probe`` flag adds a dry-run pass that walks
the *exact* shape an actual ``ots stamp`` invocation would receive,
without performing any network I/O. Concretely the probe verifies:

  * Input validation: manifest path exists, is a file, is readable,
    matches the in-tree anchor-stub registry.
  * Hash computation: SHA-256 streamed in 64 KiB chunks, byte-stable.
  * Payload shape: marker JSON validates against schema-v1 (all
    required keys, no unexpected keys) AND the additional Tag-59
    ``pre_activation_probe`` envelope is present.
  * Sandbox boundary still intact: no network calls, no ots CLI
    subprocess, no podman socket. The probe asserts this by being
    stdlib-only and emitting an explicit ``sandbox_boundary_intact:
    true`` flag in the verdict payload.

The probe emits a verdict envelope to ``--probe-verdict-out``:

  {
    "schema_version": 1,
    "kind": "ots-pre-activation-probe-verdict",
    "mode": "pre-activation-probe",
    "verdict": "PROBE-READY" | "PROBE-DEFECT",
    "stages": {
      "input_validation": "OK" | "FAIL: <reason>",
      "hash_computation": "OK: <hex>" | "FAIL: <reason>",
      "payload_shape":    "OK"  | "FAIL: <reason>",
      "sandbox_boundary": "OK"
    },
    "manifest_sha256": "<64-hex-or-empty>",
    "manifest_size_bytes": <int-or-zero>,
    "probed_at_utc": "<iso>",
    "ar_authorisation_required": true,
    "anchors": {
      "tomas_tag_59_pre_anchor_probe_pr": null,
      "reza_tag_58_spec_seal_pr": 371,
      "operator_hand_runbook":
        "docs/operations/manifest-hash-ots-anchor-wiring.md"
    }
  }

The probe is hermetic. **It still performs no real OTS calendar call.**
AR-authorisation flips a future runtime gate (see §6 + §7 of the
runbook doc); the probe itself never crosses the Sandbox boundary.

Tag-69 Welle-1 audit-trail-anchor extension
-------------------------------------------

The ``--mode welle-1-audit-anchor`` flag computes the SHA-256 audit-
trail-anchor over the Welle-1 sign-off-record bundle (rollup +
sign-off + validation + pre-auditor) and emits a marker JSON for
Selin's Tag-69 Persona-Engine producer
(``engine.py::backfill_audit_trail_anchors``, producer-wiring-plan
§2.4). Cross-Review-Zone-K (Tomás OTS / WAT-Hash semantics).

Tag-70 Welle-2 audit-trail-anchor extension
-------------------------------------------

The ``--mode welle-2-audit-anchor`` flag mirrors the Welle-1 wiring
for the Welle-2 Doppelbetrieb-Sealing sign-off-record bundle (same
canonical bundle shape: rollup + sign-off + validation + pre-auditor).
Cross-coordinated with Selin's Tag-70 Welle-2 Persona-Engine producer
(``engine.py::backfill_audit_trail_anchors`` parametrised by welle
number). The hash recipe is identical to Welle-1 (canonical-JSON
concat with ``b"\\n"`` separator in ``WELLE_N_BUNDLE_ORDER``); only
the kind/marker namespaces carry the welle number.

Tag-71 Welle-3 audit-trail-anchor extension
-------------------------------------------

The ``--mode welle-3-audit-anchor`` flag mirrors the Welle-1 / Welle-2
wiring for the Welle-3 Bridge-Audit-Writer sign-off-record bundle
(same canonical bundle shape: rollup + sign-off + validation +
pre-auditor). Cross-coordinated with Selin's Tag-71 Welle-3 Persona-
Engine producer (``engine.py::backfill_audit_trail_anchors``
parametrised to welle=3).

Welle-3 carries an additional discipline: Henrik (Internal Audit)
applies §11-Discipline / IIA-1130 to Welle-3 pre-auditor signaling
— the pre-auditor decision MUST be present in the bundle, and the
marker exposes a ``pre_auditor_signaling_ready`` flag for the
downstream observability surface to consume. The hash recipe is
identical to Welle-1 / Welle-2 (canonical-JSON concat with ``b"\\n"``
separator in ``WELLE_3_BUNDLE_ORDER``); only the kind/marker
namespaces and the pre-auditor-signaling field carry Welle-3
semantics.

Tag-72 Welle-4 audit-trail-anchor extension
-------------------------------------------

The ``--mode welle-4-audit-anchor`` flag mirrors the Welle-1 /
Welle-2 / Welle-3 wiring for the Welle-4 State-Backing-Snapshot-
Restore sign-off-record bundle. Same canonical bundle shape
(rollup + sign-off + validation + pre-auditor), same hash recipe.

Tag-73 Welle-5 audit-trail-anchor extension
-------------------------------------------

The ``--mode welle-5-audit-anchor`` flag mirrors the Welle-1 /
Welle-2 / Welle-3 / Welle-4 wiring for the Welle-5 Lifecycle-State-
Machine / FSM-Phantom-Detection sign-off-record bundle. Same
canonical bundle shape (rollup + sign-off + validation + pre-
auditor), same hash recipe.

Welle-5 carries its own discipline: the Capability-Token-Rotation
markers (Reza Sprint-9 Capability-Token-Rotation+Replay sub).
Capability-Tokens minted by ``/agent/`` SVIDs are short-lived and
rotated on a schedule; the Welle-5 sign-off-record carries the
rotation cadence + last-rotation timestamp + replay-window flag so
the audit-trail anchor can pin the rotation discipline at sign-off.
The marker exposes a ``capability_token_rotation_tracking`` block:

  * ``capability_token_rotation_active``: bool — True iff the
    rollup / sign-off carries the rotation discipline at all.
  * ``capability_token_rotation_status``: one of "pending" /
    "rotated" / "exempt" / "unknown" — derived from the rollup or
    sign-off payload when present; "unknown" otherwise.
  * ``capability_token_last_rotation_iso``: ISO-8601 timestamp of
    the most recent rotation, or empty string.
  * ``capability_token_replay_window_closed``: bool — True iff the
    sign-off declares the replay-window closed (Reza Sprint-9
    replay-window discipline).
  * ``capability_token_rotation_evidence_ref``: free-form evidence
    pointer (URL, doc-path, runbook-section) or empty string.

This block lets the downstream observability surface dispatch the
rotation-discipline gate without re-reading the bundle. **No
enforcement here** — the helper only surfaces tracking; the gate
itself lives in Henrik's Internal-Audit + Reza-Identity-Substrate
workflows.

Tag-74 Welle-6 audit-trail-anchor extension
-------------------------------------------

The ``--mode welle-6-audit-anchor`` flag mirrors the Welle-1 /
Welle-2 / Welle-3 / Welle-4 / Welle-5 wiring for the Welle-6
``subscribe_loop`` Cutover (KW-27, parallel to Welle-7). Same
canonical bundle shape, same hash recipe (Cross-Substrate-Parity-
Markers asserted in the Tag-74 test suite).

Welle-6 carries its own discipline: the subscribe-loop Self-Repair-
Hygiene-Tracking (Tag-73-Lehre: PR #461 cross-Persona Self-Repair-
Hygiene-Fix carry-through). The Welle-6 sign-off-record carries the
Self-Repair-Hygiene cadence + last-cycle timestamp + re-subscribe-
window flag + evidence-ref so the audit-trail anchor can pin the
hygiene discipline at sign-off. The marker exposes a
``subscribe_loop_self_repair_hygiene_tracking`` block:

  * ``subscribe_loop_self_repair_hygiene_active``: bool — True iff
    the rollup / sign-off carries the hygiene discipline at all.
  * ``subscribe_loop_self_repair_hygiene_status``: one of "pending"
    / "drilled" / "exempt" / "unknown" — derived from the rollup or
    sign-off payload when present; "unknown" otherwise.
  * ``subscribe_loop_last_hygiene_cycle_iso``: ISO-8601 timestamp
    of the most recent Self-Repair-Hygiene drill, or empty string.
  * ``subscribe_loop_re_subscribe_window_closed``: bool — True iff
    the sign-off declares the re-subscribe-window closed.
  * ``subscribe_loop_self_repair_hygiene_evidence_ref``: free-form
    evidence pointer (URL, doc-path, runbook-section) or empty.

This block lets the downstream observability surface dispatch the
hygiene-discipline gate without re-reading the bundle. **No
enforcement here** — the helper only surfaces tracking.

Tag-75 Welle-7 audit-trail-anchor extension (FINAL Welle)
---------------------------------------------------------

The ``--mode welle-7-audit-anchor`` flag mirrors the Welle-1..6
wiring for the FINAL Welle-7 sign-off-record bundle. Same canonical
bundle shape (rollup + sign-off + validation + pre-auditor), same
hash recipe (Welle-1..7-Kind-Disjointness-Pin: identical recipe
across all seven Wellen, distinct kind strings per Welle).

Welle-7 is the closing Welle of the Phase-3c-Welle-Marathon
(KW-27 Doppel-Welle-6+7 entry, Cutover-Mittwoch 2026-07-01,
Sign-off-Freitag 2026-07-03 = the Global Acceptance-Verdict per
``docs/quality-gates/pre-cutover-acceptance-run-order.md`` §3.2).
Welle-7 carries the Phase-3-Final-Sealing discipline. The marker
exposes a ``phase_3_final_sealing_tracking`` block:

  * ``phase_3_final_sealing_active``: bool — True iff the rollup
    / sign-off carries the Final-Sealing discipline at all.
  * ``phase_3_final_sealing_status``: one of "pending" / "sealed"
    / "escalated" / "unknown" — derived from the rollup or sign-
    off payload when present; "unknown" otherwise.
  * ``phase_3_final_sealing_iso``: ISO-8601 timestamp at which
    Final-Sealing was recorded, or empty string.
  * ``global_acceptance_verdict_recorded``: bool — True iff the
    sign-off declares the verdict-aggregator output has been
    recorded (necessary precondition for the Phase-3-COMPLETE-
    marker per Surface-1..5 conjunction).
  * ``phase_3_complete_marker_ready``: bool — True iff the sign-
    off declares the Phase-3-COMPLETE-marker is ready to fire.
  * ``phase_3_final_sealing_evidence_ref``: free-form evidence
    pointer (URL, doc-path, runbook-section) or empty string.

Pre-Auditor-Signaling-Markers (Tag-75 final-welle variant): the
Welle-7 marker carries TWO signaling flags. The first
(``pre_auditor_signaling_ready``) mirrors the Welle-3 flag. The
second (``pre_auditor_final_sealing_signaling_ready``) is the
canonical Tomás -> Henrik hand-off signal for Phase-3-COMPLETE-
marker readiness, true iff a pre-auditor-decision is present in
the bundle AND ``global_acceptance_verdict_recorded == True``.

Tag-76 Marathon-Closeout-Audit-Anchor-Bundle (Phase-3-Complete-Marker)
----------------------------------------------------------------------

The ``--mode phase-3-complete-marker`` flag consolidates the seven
Welle-N audit-anchor markers (the outputs of the welle-1..welle-7-
audit-anchor modes) into a single Phase-3-COMPLETE-marker that
Henrik's Zone-N Audit-Evidence-Index ingests as the canonical
Phase-3-COMPLETE hand-off envelope.

Hash recipe: identical to the per-Welle recipe (canonical-JSON of
each Welle marker dict, concatenated in welle-number order with a
single ``b"\n"`` separator, SHA-256 over the concatenation). The
seven input markers are themselves byte-stable, so the closeout
bundle anchor is deterministic across re-runs.

The Welle-1..7-Kind-Disjointness-Pin is enforced at ingest: the
seven input markers must cover ``welle_number`` 1..7 exactly with
no duplicates and no gaps, and each marker's ``kind`` must match
the expected ``welle-N-audit-trail-anchor-marker`` string. Any
deviation raises ValueError before the bundle hash is computed.

Inputs:

  * ``--welle-N-marker`` for N in 1..7 (all seven required): paths
    to the per-Welle audit-anchor marker JSON files.
  * ``--marker-out`` (required): output path for the Phase-3-
    COMPLETE-marker.

Output: marker JSON at ``--marker-out`` with shape::

  {
    "schema_version": 1,
    "kind": "phase-3-complete-marker",
    "mode": "phase-3-complete-marker",
    "phase_3_complete_bundle_anchor": "<64-hex>",
    "welle_bundle_count": 7,
    "welle_bundle_anchors": [
      {"welle_number": N, "kind": "...", "audit_trail_anchor": "..."}
    ],
    "phase_3_final_sealing_tracking": { ... },  // from welle-7
    "global_acceptance_verdict_recorded": bool,
    "phase_3_complete_marker_ready": bool,
    "pre_auditor_final_sealing_signaling_ready": bool,
    "welle_1_7_kind_disjointness_pin_ok": true,
    "wat_spool_envelope": { ... },
    "emitted_at_utc": "<iso>",
    "anchors": { ... },
    "operator_hand_next_step": "..."
  }

The closeout-marker is **hermetic and audit-only**: no network
I/O, no OTS calendar call, no subprocess. Real OTS stamping of
the Phase-3-COMPLETE marker is an Operator-Hand follow-up step.

Welle-4 carries its own discipline: the State-Backing-Snapshot-
Restore-Pflicht-Flag (see Amara Tag-67 state-file conventions). The
marker exposes a ``snapshot_restore_pflicht_tracking`` block:

  * ``snapshot_restore_pflicht_active``: bool — True iff the
    rollup carries the Pflicht-Flag at all.
  * ``snapshot_restore_status``: one of "pending" / "executed" /
    "exempt" / "unknown" — derived from the rollup or sign-off
    payload when present; "unknown" otherwise.
  * ``snapshot_restore_iso``: ISO-8601 timestamp from the bundle
    or empty string.
  * ``snapshot_restore_evidence_ref``: free-form evidence pointer
    (URL, doc-path) or empty string.

This block lets the downstream observability surface dispatch the
restore-Pflicht gate without re-reading the bundle. **No
enforcement here** — the helper only surfaces tracking; the gate
itself lives in Henrik's Internal-Audit + Amara-QA workflows.

Inputs:

  * ``--welle-1-rollup`` (required): path to ``state/welle-1.json``.
  * ``--welle-1-sign-off`` (required): path to
    ``state/welle-1-sign-off.json``.
  * ``--welle-1-validation`` (optional): path to
    ``state/welle-1-validation-last-verdict.json``.
  * ``--welle-1-pre-auditor`` (optional): path to
    ``state/welle-1-pre-auditor-decision.json``.

Output: marker JSON at ``--marker-out`` with shape::

  {
    "schema_version": 1,
    "kind": "welle-1-audit-trail-anchor-marker",
    "mode": "welle-1-audit-anchor",
    "welle_number": 1,
    "audit_trail_anchor": "<64-hex>",
    "bundle_keys": ["rollup", "sign_off", ...],
    "wat_spool_envelope": { ... },
    "emitted_at_utc": "<iso>",
    "anchors": { ... },
    "operator_hand_next_step": "..."
  }

The Welle-1 mode is **hermetic and audit-only**: no network I/O,
no OTS calendar call, no subprocess. Selin's producer reads the
marker, extracts ``audit_trail_anchor``, writes it into
``state/welle-1.json:audit_trail_anchor``. Real OTS stamping is
an Operator-Hand follow-up (separate runbook step).

Schema (v1) — JSON marker emitted to ``--marker-out``
-----------------------------------------------------

  {
    "schema_version": 1,
    "kind": "manifest-hash-ots-anchor-marker",
    "mode": "audit-only",
    "manifest_path": "wirelang/persona_engine/MANIFEST-0.5.2-final-pre-cutover.md",
    "manifest_sha256": "<64-hex>",
    "manifest_size_bytes": 12345,
    "wat_spool_envelope": {
      "schema_version": 1,
      "kind": "ots-anchor-request",
      "manifest_sha256": "<64-hex>",
      "requested_at_utc": "2026-05-19T...",
      "actor": "<github.actor|local>",
      "anchor_target": "opentimestamps-calendar"
    },
    "emitted_at_utc": "2026-05-19T...",
    "anchors": {
      "adr_audit_trail": "decisions/0007-internal-audit-trail-ots.md",
      "selin_tag_56_audit": "decisions/0062-..."
    },
    "operator_hand_next_step": (
      "Run `ots stamp <marker_out>` on a network-attached host; "
      "attach resulting .ots proof to this marker out-of-band."
    )
  }

Exit codes
----------

  * 0 — marker emitted successfully.
  * 1 — manifest file not found / unreadable.
  * 2 — usage error.

Hermetic
--------

stdlib only. ``argparse``, ``hashlib``, ``json``, ``pathlib``,
``datetime``, ``os``, ``sys``. No third-party imports. No network.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Iterable


MODE_AUDIT_ONLY: str = "audit-only"
MODE_PRE_ACTIVATION_PROBE: str = "pre-activation-probe"
MODE_WELLE_1_AUDIT_ANCHOR: str = "welle-1-audit-anchor"
MODE_WELLE_2_AUDIT_ANCHOR: str = "welle-2-audit-anchor"
MODE_WELLE_3_AUDIT_ANCHOR: str = "welle-3-audit-anchor"
MODE_WELLE_4_AUDIT_ANCHOR: str = "welle-4-audit-anchor"
MODE_WELLE_5_AUDIT_ANCHOR: str = "welle-5-audit-anchor"
MODE_WELLE_6_AUDIT_ANCHOR: str = "welle-6-audit-anchor"
MODE_WELLE_7_AUDIT_ANCHOR: str = "welle-7-audit-anchor"
MODE_PHASE_3_COMPLETE_MARKER: str = "phase-3-complete-marker"
ANCHOR_TARGET_OTS_CALENDAR: str = "opentimestamps-calendar"

# Tag-69 Welle-1 audit-trail-anchor mode constants.
# The anchor is computed over a canonical, byte-stable concatenation of
# the Welle-1 sign-off-record-bundle: rollup + sign-off + validation +
# pre-auditor decision (when present). Cross-coordinated with Selin's
# Tag-69 Persona-Engine producer (`engine.py::backfill_audit_trail_
# anchors`, plan §2.4) which calls this helper for the hash-side and
# writes the result into `state/welle-1.json:audit_trail_anchor`.
WELLE_1_BUNDLE_ORDER: tuple[str, ...] = (
    "rollup",
    "sign_off",
    "validation",
    "pre_auditor",
)
WELLE_1_BUNDLE_REQUIRED: frozenset[str] = frozenset({"rollup", "sign_off"})
WELLE_1_KIND_MARKER: str = "welle-1-audit-trail-anchor-marker"
WELLE_1_KIND_ENVELOPE: str = "welle-1-audit-trail-anchor-envelope"

# Tag-70 Welle-2 audit-trail-anchor mode constants. Mirror of the
# Welle-1 wiring (same canonical bundle shape and same hash recipe);
# only the marker/envelope kind strings carry the welle number so
# downstream consumers can tell the two apart.
WELLE_2_BUNDLE_ORDER: tuple[str, ...] = WELLE_1_BUNDLE_ORDER
WELLE_2_BUNDLE_REQUIRED: frozenset[str] = WELLE_1_BUNDLE_REQUIRED
WELLE_2_KIND_MARKER: str = "welle-2-audit-trail-anchor-marker"
WELLE_2_KIND_ENVELOPE: str = "welle-2-audit-trail-anchor-envelope"

# Tag-71 Welle-3 audit-trail-anchor mode constants. Mirror of the
# Welle-1 / Welle-2 wiring (same canonical bundle shape and same hash
# recipe); only the marker/envelope kind strings carry the welle number
# so downstream consumers can dispatch unambiguously on ``kind``. Welle-3
# additionally carries Henrik-IIA-1130 §11-Discipline pre-auditor
# signaling — the marker exposes ``pre_auditor_signaling_ready`` to
# downstream observability and Selin's producer.
WELLE_3_BUNDLE_ORDER: tuple[str, ...] = WELLE_1_BUNDLE_ORDER
WELLE_3_BUNDLE_REQUIRED: frozenset[str] = WELLE_1_BUNDLE_REQUIRED
WELLE_3_KIND_MARKER: str = "welle-3-audit-trail-anchor-marker"
WELLE_3_KIND_ENVELOPE: str = "welle-3-audit-trail-anchor-envelope"

# Tag-72 Welle-4 audit-trail-anchor mode constants. Mirror of the
# Welle-1 / Welle-2 / Welle-3 wiring (same canonical bundle shape and
# same hash recipe). Welle-4 covers State-Backing-Snapshot-Restore;
# additional discipline: the marker exposes a
# ``snapshot_restore_pflicht_tracking`` block carrying the
# snapshot-restore-Pflicht-Flag plus restore-iso / restore-evidence-ref
# so the downstream observability surface can pin restore-readiness
# without re-reading the bundle.
WELLE_4_BUNDLE_ORDER: tuple[str, ...] = WELLE_1_BUNDLE_ORDER
WELLE_4_BUNDLE_REQUIRED: frozenset[str] = WELLE_1_BUNDLE_REQUIRED
WELLE_4_KIND_MARKER: str = "welle-4-audit-trail-anchor-marker"
WELLE_4_KIND_ENVELOPE: str = "welle-4-audit-trail-anchor-envelope"

# Tag-73 Welle-5 audit-trail-anchor mode constants. Mirror of the
# Welle-1 / Welle-2 / Welle-3 / Welle-4 wiring (same canonical bundle
# shape and same hash recipe). Welle-5 covers Lifecycle-State-Machine
# / FSM-Phantom-Detection; additional discipline: the marker exposes
# a ``capability_token_rotation_tracking`` block carrying the
# Capability-Token-Rotation cadence + last-rotation-iso +
# replay-window-closed flag + rotation-evidence-ref so the downstream
# observability surface can pin rotation-discipline at sign-off
# without re-reading the bundle. Cross-coord with Reza Sprint-9
# Capability-Token-Rotation+Replay sub.
WELLE_5_BUNDLE_ORDER: tuple[str, ...] = WELLE_1_BUNDLE_ORDER
WELLE_5_BUNDLE_REQUIRED: frozenset[str] = WELLE_1_BUNDLE_REQUIRED
WELLE_5_KIND_MARKER: str = "welle-5-audit-trail-anchor-marker"
WELLE_5_KIND_ENVELOPE: str = "welle-5-audit-trail-anchor-envelope"

# Tag-74 Welle-6 audit-trail-anchor mode constants. Mirror of the
# Welle-1 / Welle-2 / Welle-3 / Welle-4 / Welle-5 wiring (same canonical
# bundle shape and same hash recipe). Welle-6 covers ``subscribe_loop``
# Cutover (KW-27, parallel to Welle-7); additional discipline: the
# marker exposes a ``subscribe_loop_self_repair_hygiene_tracking``
# block carrying the Self-Repair-Hygiene cadence + last-cycle-iso +
# re-subscribe-window-closed flag + hygiene-evidence-ref so the
# downstream observability surface can pin Self-Repair-Hygiene
# readiness at sign-off without re-reading the bundle. Tag-73-Lehre
# (cross-Persona Self-Repair-Hygiene-Fix from PR #461) carries through.
# Cross-Substrate-Parity-Markers: the Welle-6 marker references the
# Welle-1..5 cross-coord anchors (parity-pin), and recipe-identity
# with Welle-1..5 is asserted in the Tag-74 test suite.
WELLE_6_BUNDLE_ORDER: tuple[str, ...] = WELLE_1_BUNDLE_ORDER
WELLE_6_BUNDLE_REQUIRED: frozenset[str] = WELLE_1_BUNDLE_REQUIRED
WELLE_6_KIND_MARKER: str = "welle-6-audit-trail-anchor-marker"
WELLE_6_KIND_ENVELOPE: str = "welle-6-audit-trail-anchor-envelope"

# Tag-75 Welle-7 audit-trail-anchor mode constants. Mirror of the
# Welle-1 / Welle-2 / Welle-3 / Welle-4 / Welle-5 / Welle-6 wiring
# (same canonical bundle shape and same hash recipe). Welle-7 is the
# FINAL Welle of the Phase-3c-Welle-Marathon (KW-27, Doppel-Welle-6+7
# entry, Cutover-Mittwoch 2026-07-01, Sign-off-Freitag 2026-07-03 —
# the Global Acceptance-Verdict sign-off-Freitag per
# ``docs/quality-gates/pre-cutover-acceptance-run-order.md`` §3.2).
# Additional discipline: the marker exposes a
# ``phase_3_final_sealing_tracking`` block carrying the Phase-3
# Final-Sealing status + sealing-iso + global-acceptance-verdict-
# recorded flag + Phase-3-COMPLETE-marker-readiness + sealing-
# evidence-ref so the downstream observability surface (and Henrik's
# Zone-N Audit-Evidence-Index) can pin Final-Sealing readiness at
# Post-Welle-7 sign-off without re-reading the bundle.
#
# Pre-Auditor-Signaling-Markers (Tag-75 auftrag, final-welle
# variant): mirroring the Tag-71 Welle-3 ``pre_auditor_signaling_ready``
# discipline, the Welle-7 marker exposes a
# ``pre_auditor_signaling_ready`` flag (Henrik-IIA-1130 §11-
# Discipline) AND a Welle-7-specific ``pre_auditor_final_sealing_
# signaling_ready`` flag that is true only when (a) a pre-auditor-
# decision is present in the bundle AND (b) the final-sealing-
# tracking block reports the global-acceptance-verdict has been
# recorded. The second flag is the canonical hand-off signal from
# Tomás's audit-anchor side to Henrik's Audit-Evidence-Index for
# Phase-3-COMPLETE-marker readiness.
#
# Cross-Substrate-Parity-Markers: the Welle-7 marker references
# Welle-1..6 cross-coord anchors (parity-pin spans the full
# Welle-1..7 lineage). Recipe-identity with Welle-1..6 is asserted
# in the Tag-75 test suite (Welle-1..7-Kind-Disjointness-Pin: each
# Welle has its own marker/envelope kind string but the hash recipe
# is identical).
WELLE_7_BUNDLE_ORDER: tuple[str, ...] = WELLE_1_BUNDLE_ORDER
WELLE_7_BUNDLE_REQUIRED: frozenset[str] = WELLE_1_BUNDLE_REQUIRED
WELLE_7_KIND_MARKER: str = "welle-7-audit-trail-anchor-marker"
WELLE_7_KIND_ENVELOPE: str = "welle-7-audit-trail-anchor-envelope"

# Tag-76 Phase-3-Complete-Marker mode constants. Marathon-Closeout-
# Audit-Anchor-Bundle: consolidates the Welle-1..7 audit-anchor
# markers (the outputs of the seven welle-N-audit-anchor modes added
# on Tag-69..Tag-75) into a single Phase-3-COMPLETE marker that
# Henrik's Zone-N Audit-Evidence-Index ingests as the canonical
# Phase-3-COMPLETE-marker hand-off envelope.
#
# Hash recipe: identical to the Welle-N recipe -- ``_canonical_json_
# bytes`` over each Welle-N marker dict (sort_keys + compact
# separators), concatenated in welle-number order with a single
# ``b"\n"`` separator, SHA-256 over the concatenation. The seven
# input markers are themselves byte-stable artefacts (they were
# emitted with ``json.dumps(..., sort_keys=True)``), so the
# closeout-bundle anchor is deterministic across re-runs that pass
# the same seven files.
#
# Welle-1..7-Kind-Disjointness-Pin: each welle marker carries a
# distinct ``kind`` string (welle-N-audit-trail-anchor-marker) but
# the underlying hash recipe is identical. The closeout marker
# enforces this disjointness at ingest time by asserting that the
# seven input markers cover ``welle_number`` 1..7 exactly with no
# duplicates and no gaps -- any deviation raises ValueError before
# the bundle hash is computed.
#
# Phase-3-COMPLETE-marker-readiness gate: the closeout marker
# surfaces ``phase_3_complete_marker_ready`` (derived from welle-7's
# tracking block) and ``global_acceptance_verdict_recorded`` (also
# welle-7) plus ``pre_auditor_final_sealing_signaling_ready``
# (welle-7) so a downstream consumer can dispatch the Henrik hand-
# off without re-reading the underlying welle bundles.
PHASE_3_COMPLETE_KIND_MARKER: str = "phase-3-complete-marker"
PHASE_3_COMPLETE_KIND_ENVELOPE: str = "phase-3-complete-marker-envelope"
PHASE_3_COMPLETE_WELLE_COUNT: int = 7
PHASE_3_COMPLETE_EXPECTED_WELLE_NUMBERS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7)
PHASE_3_COMPLETE_EXPECTED_KINDS: tuple[str, ...] = (
    WELLE_1_KIND_MARKER,
    WELLE_2_KIND_MARKER,
    WELLE_3_KIND_MARKER,
    WELLE_4_KIND_MARKER,
    WELLE_5_KIND_MARKER,
    WELLE_6_KIND_MARKER,
    WELLE_7_KIND_MARKER,
)

# Required top-level keys for a schema-v1 marker payload. Used by the
# pre-activation-probe's ``payload_shape`` stage.
MARKER_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "kind",
        "mode",
        "manifest_path",
        "manifest_sha256",
        "manifest_size_bytes",
        "wat_spool_envelope",
        "emitted_at_utc",
        "anchors",
        "operator_hand_next_step",
    }
)

# Required top-level keys for a schema-v1 probe-verdict payload.
PROBE_VERDICT_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "kind",
        "mode",
        "verdict",
        "stages",
        "manifest_sha256",
        "manifest_size_bytes",
        "probed_at_utc",
        "ar_authorisation_required",
        "anchors",
    }
)

PROBE_STAGE_KEYS: tuple[str, ...] = (
    "input_validation",
    "hash_computation",
    "payload_shape",
    "sandbox_boundary",
)

PROBE_VERDICT_READY: str = "PROBE-READY"
PROBE_VERDICT_DEFECT: str = "PROBE-DEFECT"


def compute_sha256(path: Path) -> tuple[str, int]:
    """Return (hex-digest, byte-size) for the file at ``path``.

    Streams the file in 64 KiB chunks to keep memory flat.
    """
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def build_marker(
    *,
    manifest_path: Path,
    manifest_sha256: str,
    manifest_size_bytes: int,
    actor: str,
    now_utc: _dt.datetime,
    repo_root: Path,
) -> dict:
    """Assemble the marker dict for the given manifest hash."""
    rel_manifest = (
        str(manifest_path.relative_to(repo_root))
        if manifest_path.is_absolute() and repo_root in manifest_path.parents
        else str(manifest_path)
    )
    iso_now = now_utc.isoformat()
    return {
        "schema_version": 1,
        "kind": "manifest-hash-ots-anchor-marker",
        "mode": MODE_AUDIT_ONLY,
        "manifest_path": rel_manifest,
        "manifest_sha256": manifest_sha256,
        "manifest_size_bytes": manifest_size_bytes,
        "wat_spool_envelope": {
            "schema_version": 1,
            "kind": "ots-anchor-request",
            "manifest_sha256": manifest_sha256,
            "requested_at_utc": iso_now,
            "actor": actor,
            "anchor_target": ANCHOR_TARGET_OTS_CALENDAR,
        },
        "emitted_at_utc": iso_now,
        "anchors": {
            "adr_audit_trail": "decisions/0007-internal-audit-trail-ots.md",
            "selin_tag_56_audit": (
                "tag-56 PR #362 OPEN-K2 (persona-engine 0.5.2-final "
                "production-readiness audit)"
            ),
        },
        "operator_hand_next_step": (
            "Run `ots stamp <marker_out>` on a network-attached host; "
            "attach resulting .ots proof to this marker out-of-band."
        ),
    }


def _empty_probe_stages() -> dict:
    return {key: None for key in PROBE_STAGE_KEYS}


def build_probe_verdict(
    *,
    stages: dict,
    manifest_sha256: str,
    manifest_size_bytes: int,
    now_utc: _dt.datetime,
) -> dict:
    """Assemble the Tag-59 pre-activation-probe verdict envelope.

    ``stages`` must contain entries for all four ``PROBE_STAGE_KEYS``.
    Verdict is ``PROBE-READY`` iff every stage starts with ``"OK"``,
    otherwise ``PROBE-DEFECT``.
    """
    iso_now = now_utc.isoformat()
    all_ok = all(
        isinstance(stages.get(k), str) and stages[k].startswith("OK")
        for k in PROBE_STAGE_KEYS
    )
    verdict = PROBE_VERDICT_READY if all_ok else PROBE_VERDICT_DEFECT
    return {
        "schema_version": 1,
        "kind": "ots-pre-activation-probe-verdict",
        "mode": MODE_PRE_ACTIVATION_PROBE,
        "verdict": verdict,
        "stages": {k: stages[k] for k in PROBE_STAGE_KEYS},
        "manifest_sha256": manifest_sha256,
        "manifest_size_bytes": manifest_size_bytes,
        "probed_at_utc": iso_now,
        "ar_authorisation_required": True,
        "anchors": {
            "tomas_tag_59_pre_anchor_probe_pr": None,
            "reza_tag_58_spec_seal_pr": 371,
            "operator_hand_runbook": (
                "docs/operations/manifest-hash-ots-anchor-wiring.md"
            ),
        },
    }


def _stub_registry_paths(repo_root: Path) -> set[str]:
    """Return the set of manifest paths listed in the anchor-stub.

    Returns an empty set when the stub is missing or malformed — the
    caller treats that as a probe defect.
    """
    stub_path = repo_root / "tooling" / "ots" / "manifest-hash-ots-anchor-stub.json"
    try:
        text = stub_path.read_text(encoding="utf-8")
        data = json.loads(text)
        return {m["path"] for m in data.get("wired_manifests", [])}
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return set()


def run_pre_activation_probe(
    *,
    manifest_path: Path,
    actor: str,
    now_utc: _dt.datetime,
    repo_root: Path,
) -> dict:
    """Execute the four-stage hermetic probe and return a verdict dict.

    The probe never calls out to the OTS calendar; it only walks the
    same code paths that a real ``ots stamp`` invocation would touch
    on the Repo-Side. Sandbox-boundary stage is OK-by-construction:
    this module is stdlib-only and never invokes subprocess or sockets.
    """
    stages: dict = _empty_probe_stages()
    manifest_sha256 = ""
    manifest_size_bytes = 0

    # Stage 1 — input validation.
    if not manifest_path.exists():
        stages["input_validation"] = (
            f"FAIL: manifest not found: {manifest_path}"
        )
    elif not manifest_path.is_file():
        stages["input_validation"] = (
            f"FAIL: manifest is not a regular file: {manifest_path}"
        )
    else:
        # Optional registry-membership check: only enforced when the
        # manifest lives inside ``repo_root`` (test fixtures live in
        # tmp_path and are exempt).
        try:
            rel = manifest_path.resolve().relative_to(repo_root.resolve())
            rel_str = str(rel).replace("\\", "/")
            registry = _stub_registry_paths(repo_root)
            if registry and rel_str not in registry:
                stages["input_validation"] = (
                    "FAIL: manifest not listed in "
                    "tooling/ots/manifest-hash-ots-anchor-stub.json: "
                    f"{rel_str}"
                )
            else:
                stages["input_validation"] = "OK"
        except ValueError:
            # Manifest outside repo_root — accept (used by tmp_path
            # fixtures in tests).
            stages["input_validation"] = "OK"

    # Stage 2 — hash computation.
    if stages["input_validation"].startswith("OK"):
        try:
            manifest_sha256, manifest_size_bytes = compute_sha256(manifest_path)
            stages["hash_computation"] = f"OK: {manifest_sha256}"
        except OSError as exc:
            stages["hash_computation"] = f"FAIL: read error: {exc}"
    else:
        stages["hash_computation"] = "FAIL: skipped (input_validation failed)"

    # Stage 3 — payload shape: build a marker against the same builder
    # the audit-only emit uses, then validate shape.
    if stages["hash_computation"].startswith("OK"):
        candidate = build_marker(
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            manifest_size_bytes=manifest_size_bytes,
            actor=actor,
            now_utc=now_utc,
            repo_root=repo_root,
        )
        cand_keys = set(candidate.keys())
        if cand_keys != MARKER_REQUIRED_KEYS:
            missing = MARKER_REQUIRED_KEYS - cand_keys
            extra = cand_keys - MARKER_REQUIRED_KEYS
            stages["payload_shape"] = (
                f"FAIL: marker key drift missing={sorted(missing)} "
                f"extra={sorted(extra)}"
            )
        elif candidate["schema_version"] != 1:
            stages["payload_shape"] = (
                f"FAIL: schema_version != 1 ({candidate['schema_version']})"
            )
        elif candidate["kind"] != "manifest-hash-ots-anchor-marker":
            stages["payload_shape"] = (
                f"FAIL: marker kind drift: {candidate['kind']}"
            )
        elif candidate["wat_spool_envelope"]["anchor_target"] != (
            ANCHOR_TARGET_OTS_CALENDAR
        ):
            stages["payload_shape"] = (
                "FAIL: wat_spool_envelope.anchor_target drift: "
                f"{candidate['wat_spool_envelope']['anchor_target']}"
            )
        else:
            stages["payload_shape"] = "OK"
    else:
        stages["payload_shape"] = "FAIL: skipped (hash_computation failed)"

    # Stage 4 — sandbox boundary. This module is stdlib-only and
    # performs no subprocess / no socket / no network. The Tag-57
    # invariant test ``test_t09_k2_stdlib_only`` plus the Tag-59
    # tests reinforce this at CI time. The flag here is the
    # runtime acknowledgement.
    stages["sandbox_boundary"] = "OK"

    return build_probe_verdict(
        stages=stages,
        manifest_sha256=manifest_sha256,
        manifest_size_bytes=manifest_size_bytes,
        now_utc=now_utc,
    )


def _canonical_json_bytes(doc: dict) -> bytes:
    """Return a byte-stable JSON serialization for hashing.

    Uses ``sort_keys=True`` + ``separators=(",", ":")`` so the same
    logical document always produces the same bytes regardless of
    insertion order or whitespace. UTF-8 encoded.
    """
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def compute_welle_1_audit_anchor_hash(bundle: dict) -> str:
    """Compute the Welle-1 audit-trail-anchor SHA-256 from a bundle.

    ``bundle`` must be a dict with at least the keys in
    ``WELLE_1_BUNDLE_REQUIRED``. Optional keys in ``WELLE_1_BUNDLE_ORDER``
    are included when present. Each value is canonicalised with
    ``_canonical_json_bytes`` and concatenated in ``WELLE_1_BUNDLE_ORDER``
    with a single ``b"\\n"`` separator between parts.

    The deterministic concat-with-separator scheme matches the format
    that Selin's Persona-Engine batch-writer (plan §2.4) expects when
    it backfills `audit_trail_anchor` from this helper's envelope.
    """
    missing = WELLE_1_BUNDLE_REQUIRED - set(bundle.keys())
    if missing:
        raise ValueError(
            f"welle-1 bundle missing required keys: {sorted(missing)}"
        )

    parts: list[bytes] = []
    for key in WELLE_1_BUNDLE_ORDER:
        if key not in bundle:
            continue
        value = bundle[key]
        if not isinstance(value, dict):
            raise ValueError(
                f"welle-1 bundle key {key!r} must be a JSON object dict, "
                f"got {type(value).__name__}"
            )
        parts.append(_canonical_json_bytes(value))

    return hashlib.sha256(b"\n".join(parts)).hexdigest()


def build_welle_1_audit_anchor_marker(
    *,
    bundle: dict,
    anchor_hash: str,
    actor: str,
    now_utc: _dt.datetime,
) -> dict:
    """Assemble the Welle-1 audit-trail-anchor marker dict.

    The marker is the audit-only artefact that Tomás emits and that
    Selin's producer reads to populate
    ``state/welle-1.json:audit_trail_anchor``.
    """
    iso_now = now_utc.isoformat()
    return {
        "schema_version": 1,
        "kind": WELLE_1_KIND_MARKER,
        "mode": MODE_WELLE_1_AUDIT_ANCHOR,
        "welle_number": 1,
        "audit_trail_anchor": anchor_hash,
        "bundle_keys": sorted(
            k for k in WELLE_1_BUNDLE_ORDER if k in bundle
        ),
        "wat_spool_envelope": {
            "schema_version": 1,
            "kind": WELLE_1_KIND_ENVELOPE,
            "audit_trail_anchor": anchor_hash,
            "requested_at_utc": iso_now,
            "actor": actor,
            "anchor_target": ANCHOR_TARGET_OTS_CALENDAR,
        },
        "emitted_at_utc": iso_now,
        "anchors": {
            "adr_audit_trail": "decisions/0007-internal-audit-trail-ots.md",
            "amara_tag_67_state_file_conventions_pr": 429,
            "selin_tag_69_producer_pr": None,
            "tomas_tag_69_audit_anchor_pr": None,
            "state_file_conventions_doc": (
                "docs/quality-gates/welle-n-state-file-conventions.md"
            ),
            "producer_wiring_plan_doc": (
                "docs/persona-engine/state-file-producer-wiring-plan.md"
            ),
        },
        "operator_hand_next_step": (
            "Selin's persona-engine batch-writer "
            "(engine.py::backfill_audit_trail_anchors) reads this "
            "marker and writes the audit_trail_anchor into "
            "state/welle-1.json. Real OTS calendar stamping is "
            "Operator-Hand on a network-attached host, separate step."
        ),
    }


def load_welle_1_bundle(
    *,
    rollup_path: Path,
    sign_off_path: Path,
    validation_path: Path | None,
    pre_auditor_path: Path | None,
) -> dict:
    """Load the Welle-1 sign-off-record bundle from disk.

    Reads the four JSON files into a dict keyed by the canonical
    ``WELLE_1_BUNDLE_ORDER`` names. Optional inputs are omitted from
    the bundle when their path is ``None`` (the caller decides).
    """
    bundle: dict = {}
    bundle["rollup"] = json.loads(rollup_path.read_text(encoding="utf-8"))
    bundle["sign_off"] = json.loads(sign_off_path.read_text(encoding="utf-8"))
    if validation_path is not None:
        bundle["validation"] = json.loads(
            validation_path.read_text(encoding="utf-8")
        )
    if pre_auditor_path is not None:
        bundle["pre_auditor"] = json.loads(
            pre_auditor_path.read_text(encoding="utf-8")
        )
    return bundle


def compute_welle_2_audit_anchor_hash(bundle: dict) -> str:
    """Compute the Welle-2 audit-trail-anchor SHA-256 from a bundle.

    Identical recipe to ``compute_welle_1_audit_anchor_hash`` (canonical
    JSON concat in ``WELLE_2_BUNDLE_ORDER`` joined by ``b"\\n"``). The
    function is kept as its own symbol — rather than aliasing the
    Welle-1 entry — so a future recipe divergence between welles can be
    introduced without breaking the call-site contract that Selin's
    Tag-70 producer relies on.
    """
    missing = WELLE_2_BUNDLE_REQUIRED - set(bundle.keys())
    if missing:
        raise ValueError(
            f"welle-2 bundle missing required keys: {sorted(missing)}"
        )

    parts: list[bytes] = []
    for key in WELLE_2_BUNDLE_ORDER:
        if key not in bundle:
            continue
        value = bundle[key]
        if not isinstance(value, dict):
            raise ValueError(
                f"welle-2 bundle key {key!r} must be a JSON object dict, "
                f"got {type(value).__name__}"
            )
        parts.append(_canonical_json_bytes(value))

    return hashlib.sha256(b"\n".join(parts)).hexdigest()


def build_welle_2_audit_anchor_marker(
    *,
    bundle: dict,
    anchor_hash: str,
    actor: str,
    now_utc: _dt.datetime,
) -> dict:
    """Assemble the Welle-2 audit-trail-anchor marker dict.

    Mirror of the Welle-1 marker (Tag-69), with ``welle_number=2`` and
    Welle-2-specific kind strings. The marker is the audit-only
    artefact that Tomás emits and that Selin's Tag-70 producer reads
    to populate ``state/welle-2.json:audit_trail_anchor``.
    """
    iso_now = now_utc.isoformat()
    return {
        "schema_version": 1,
        "kind": WELLE_2_KIND_MARKER,
        "mode": MODE_WELLE_2_AUDIT_ANCHOR,
        "welle_number": 2,
        "audit_trail_anchor": anchor_hash,
        "bundle_keys": sorted(
            k for k in WELLE_2_BUNDLE_ORDER if k in bundle
        ),
        "wat_spool_envelope": {
            "schema_version": 1,
            "kind": WELLE_2_KIND_ENVELOPE,
            "audit_trail_anchor": anchor_hash,
            "requested_at_utc": iso_now,
            "actor": actor,
            "anchor_target": ANCHOR_TARGET_OTS_CALENDAR,
        },
        "emitted_at_utc": iso_now,
        "anchors": {
            "adr_audit_trail": "decisions/0007-internal-audit-trail-ots.md",
            "amara_tag_67_state_file_conventions_pr": 429,
            "tomas_tag_69_welle_1_audit_anchor_pr": 439,
            "selin_tag_70_producer_pr": None,
            "tomas_tag_70_audit_anchor_pr": None,
            "state_file_conventions_doc": (
                "docs/quality-gates/welle-n-state-file-conventions.md"
            ),
            "producer_wiring_plan_doc": (
                "docs/persona-engine/state-file-producer-wiring-plan.md"
            ),
            "welle_2_context": "doppelbetrieb-sealing",
        },
        "operator_hand_next_step": (
            "Selin's persona-engine batch-writer "
            "(engine.py::backfill_audit_trail_anchors, welle=2) reads "
            "this marker and writes the audit_trail_anchor into "
            "state/welle-2.json. Real OTS calendar stamping is "
            "Operator-Hand on a network-attached host, separate step."
        ),
    }


def load_welle_2_bundle(
    *,
    rollup_path: Path,
    sign_off_path: Path,
    validation_path: Path | None,
    pre_auditor_path: Path | None,
) -> dict:
    """Load the Welle-2 sign-off-record bundle from disk.

    Same shape as ``load_welle_1_bundle``. Kept as its own symbol so a
    future Welle-2-specific schema-divergence does not require touching
    the Welle-1 call-sites.
    """
    bundle: dict = {}
    bundle["rollup"] = json.loads(rollup_path.read_text(encoding="utf-8"))
    bundle["sign_off"] = json.loads(sign_off_path.read_text(encoding="utf-8"))
    if validation_path is not None:
        bundle["validation"] = json.loads(
            validation_path.read_text(encoding="utf-8")
        )
    if pre_auditor_path is not None:
        bundle["pre_auditor"] = json.loads(
            pre_auditor_path.read_text(encoding="utf-8")
        )
    return bundle


def compute_welle_3_audit_anchor_hash(bundle: dict) -> str:
    """Compute the Welle-3 audit-trail-anchor SHA-256 from a bundle.

    Identical recipe to Welle-1 / Welle-2 (canonical-JSON concat in
    ``WELLE_3_BUNDLE_ORDER`` joined by ``b"\\n"``). Kept as its own
    symbol — rather than aliasing the Welle-1 / Welle-2 entry — so a
    future recipe divergence between welles can be introduced without
    breaking the call-site contract that Selin's Tag-71 producer relies
    on (Bridge-Audit-Writer welle).
    """
    missing = WELLE_3_BUNDLE_REQUIRED - set(bundle.keys())
    if missing:
        raise ValueError(
            f"welle-3 bundle missing required keys: {sorted(missing)}"
        )

    parts: list[bytes] = []
    for key in WELLE_3_BUNDLE_ORDER:
        if key not in bundle:
            continue
        value = bundle[key]
        if not isinstance(value, dict):
            raise ValueError(
                f"welle-3 bundle key {key!r} must be a JSON object dict, "
                f"got {type(value).__name__}"
            )
        parts.append(_canonical_json_bytes(value))

    return hashlib.sha256(b"\n".join(parts)).hexdigest()


def build_welle_3_audit_anchor_marker(
    *,
    bundle: dict,
    anchor_hash: str,
    actor: str,
    now_utc: _dt.datetime,
) -> dict:
    """Assemble the Welle-3 audit-trail-anchor marker dict.

    Mirror of the Welle-1 / Welle-2 marker, with ``welle_number=3`` and
    Welle-3-specific kind strings. The marker is the audit-only
    artefact that Tomás emits and that Selin's Tag-71 producer reads
    to populate ``state/welle-3.json:audit_trail_anchor``.

    Tag-71 carries an extra discipline: Welle-3 falls under Henrik's
    §11-Discipline / IIA-1130 pre-auditor signaling. The marker
    exposes ``pre_auditor_signaling_ready`` (True iff the bundle
    contains a ``pre_auditor`` part) so the downstream observability
    surface (Henrik-Internal-Audit, Amara-QA) can pin pre-auditor
    readiness without re-reading the bundle.
    """
    iso_now = now_utc.isoformat()
    pre_auditor_signaling_ready = "pre_auditor" in bundle
    return {
        "schema_version": 1,
        "kind": WELLE_3_KIND_MARKER,
        "mode": MODE_WELLE_3_AUDIT_ANCHOR,
        "welle_number": 3,
        "audit_trail_anchor": anchor_hash,
        "bundle_keys": sorted(
            k for k in WELLE_3_BUNDLE_ORDER if k in bundle
        ),
        "pre_auditor_signaling_ready": pre_auditor_signaling_ready,
        "wat_spool_envelope": {
            "schema_version": 1,
            "kind": WELLE_3_KIND_ENVELOPE,
            "audit_trail_anchor": anchor_hash,
            "requested_at_utc": iso_now,
            "actor": actor,
            "anchor_target": ANCHOR_TARGET_OTS_CALENDAR,
        },
        "emitted_at_utc": iso_now,
        "anchors": {
            "adr_audit_trail": "decisions/0007-internal-audit-trail-ots.md",
            "amara_tag_67_state_file_conventions_pr": 429,
            "tomas_tag_69_welle_1_audit_anchor_pr": 439,
            "tomas_tag_70_welle_2_audit_anchor_pr": 445,
            "selin_tag_71_producer_pr": None,
            "tomas_tag_71_audit_anchor_pr": None,
            "state_file_conventions_doc": (
                "docs/quality-gates/welle-n-state-file-conventions.md"
            ),
            "producer_wiring_plan_doc": (
                "docs/persona-engine/state-file-producer-wiring-plan.md"
            ),
            "welle_3_context": "bridge-audit-writer",
            "henrik_pre_auditor_discipline": "IIA-1130-§11",
        },
        "operator_hand_next_step": (
            "Selin's persona-engine batch-writer "
            "(engine.py::backfill_audit_trail_anchors, welle=3) reads "
            "this marker and writes the audit_trail_anchor into "
            "state/welle-3.json. Henrik-IIA-1130 §11-Discipline: "
            "pre_auditor_signaling_ready surfaces on the observability "
            "channel for pre-auditor-decision gate. Real OTS calendar "
            "stamping is Operator-Hand on a network-attached host, "
            "separate step."
        ),
    }


def load_welle_3_bundle(
    *,
    rollup_path: Path,
    sign_off_path: Path,
    validation_path: Path | None,
    pre_auditor_path: Path | None,
) -> dict:
    """Load the Welle-3 sign-off-record bundle from disk.

    Same shape as ``load_welle_1_bundle`` / ``load_welle_2_bundle``.
    Kept as its own symbol so a future Welle-3-specific schema
    divergence (e.g. Bridge-Audit-Writer-specific fields) does not
    require touching the Welle-1 / Welle-2 call-sites.
    """
    bundle: dict = {}
    bundle["rollup"] = json.loads(rollup_path.read_text(encoding="utf-8"))
    bundle["sign_off"] = json.loads(sign_off_path.read_text(encoding="utf-8"))
    if validation_path is not None:
        bundle["validation"] = json.loads(
            validation_path.read_text(encoding="utf-8")
        )
    if pre_auditor_path is not None:
        bundle["pre_auditor"] = json.loads(
            pre_auditor_path.read_text(encoding="utf-8")
        )
    return bundle


def compute_welle_4_audit_anchor_hash(bundle: dict) -> str:
    """Compute the Welle-4 audit-trail-anchor SHA-256 from a bundle.

    Identical recipe to Welle-1 / Welle-2 / Welle-3 (canonical-JSON
    concat in ``WELLE_4_BUNDLE_ORDER`` joined by ``b"\\n"``). Kept as
    its own symbol — rather than aliasing the prior entries — so a
    future recipe divergence (e.g. State-Backing-Snapshot-Restore-
    specific canonicalisation) can be introduced without breaking the
    call-site contract that Selin's Tag-72 producer relies on.
    """
    missing = WELLE_4_BUNDLE_REQUIRED - set(bundle.keys())
    if missing:
        raise ValueError(
            f"welle-4 bundle missing required keys: {sorted(missing)}"
        )

    parts: list[bytes] = []
    for key in WELLE_4_BUNDLE_ORDER:
        if key not in bundle:
            continue
        value = bundle[key]
        if not isinstance(value, dict):
            raise ValueError(
                f"welle-4 bundle key {key!r} must be a JSON object dict, "
                f"got {type(value).__name__}"
            )
        parts.append(_canonical_json_bytes(value))

    return hashlib.sha256(b"\n".join(parts)).hexdigest()


# Allowed snapshot-restore-status enum (defensive — narrow vocab so
# downstream consumers can dispatch on a small fixed set; anything
# else becomes "unknown" in the tracking block).
SNAPSHOT_RESTORE_STATUS_VALUES: frozenset[str] = frozenset(
    {"pending", "executed", "exempt", "unknown"}
)


def derive_snapshot_restore_tracking(bundle: dict) -> dict:
    """Derive the Welle-4 ``snapshot_restore_pflicht_tracking`` block.

    Tag-72 Welle-4 carries the State-Backing-Snapshot-Restore-Pflicht-
    Flag. The tracking block is read from the rollup / sign-off
    payloads (in that order) so the marker can surface restore-
    readiness without forcing downstream consumers to re-read the
    bundle. Conservative defaults: unknown status, empty iso /
    evidence-ref, Pflicht-Flag False unless the bundle says so.

    Shape::

      {
        "snapshot_restore_pflicht_active": bool,
        "snapshot_restore_status": str (enum),
        "snapshot_restore_iso": str (ISO-8601 or empty),
        "snapshot_restore_evidence_ref": str,
      }
    """
    rollup = bundle.get("rollup", {}) if isinstance(
        bundle.get("rollup"), dict
    ) else {}
    sign_off = bundle.get("sign_off", {}) if isinstance(
        bundle.get("sign_off"), dict
    ) else {}

    # Pflicht-Flag: rollup carries the canonical value; sign-off may
    # override only if rollup is silent.
    pflicht_active = bool(
        rollup.get("snapshot_restore_pflicht_active",
                   sign_off.get("snapshot_restore_pflicht_active", False))
    )

    raw_status = (
        rollup.get("snapshot_restore_status")
        or sign_off.get("snapshot_restore_status")
        or "unknown"
    )
    if raw_status not in SNAPSHOT_RESTORE_STATUS_VALUES:
        raw_status = "unknown"

    restore_iso = (
        rollup.get("snapshot_restore_iso")
        or sign_off.get("snapshot_restore_iso")
        or ""
    )
    if not isinstance(restore_iso, str):
        restore_iso = ""

    evidence_ref = (
        rollup.get("snapshot_restore_evidence_ref")
        or sign_off.get("snapshot_restore_evidence_ref")
        or ""
    )
    if not isinstance(evidence_ref, str):
        evidence_ref = ""

    return {
        "snapshot_restore_pflicht_active": pflicht_active,
        "snapshot_restore_status": raw_status,
        "snapshot_restore_iso": restore_iso,
        "snapshot_restore_evidence_ref": evidence_ref,
    }


def build_welle_4_audit_anchor_marker(
    *,
    bundle: dict,
    anchor_hash: str,
    actor: str,
    now_utc: _dt.datetime,
) -> dict:
    """Assemble the Welle-4 audit-trail-anchor marker dict.

    Mirror of the Welle-1 / Welle-2 / Welle-3 marker, with
    ``welle_number=4`` and Welle-4-specific kind strings. The marker
    is the audit-only artefact that Tomás emits and that Selin's
    Tag-72 producer reads to populate
    ``state/welle-4.json:audit_trail_anchor``.

    Tag-72 discipline: the marker exposes the
    ``snapshot_restore_pflicht_tracking`` block so the State-Backing-
    Snapshot-Restore-Pflicht-Flag and accompanying restore metadata
    surface on the observability channel without re-reading the
    bundle.
    """
    iso_now = now_utc.isoformat()
    tracking = derive_snapshot_restore_tracking(bundle)
    return {
        "schema_version": 1,
        "kind": WELLE_4_KIND_MARKER,
        "mode": MODE_WELLE_4_AUDIT_ANCHOR,
        "welle_number": 4,
        "audit_trail_anchor": anchor_hash,
        "bundle_keys": sorted(
            k for k in WELLE_4_BUNDLE_ORDER if k in bundle
        ),
        "snapshot_restore_pflicht_tracking": tracking,
        "wat_spool_envelope": {
            "schema_version": 1,
            "kind": WELLE_4_KIND_ENVELOPE,
            "audit_trail_anchor": anchor_hash,
            "requested_at_utc": iso_now,
            "actor": actor,
            "anchor_target": ANCHOR_TARGET_OTS_CALENDAR,
        },
        "emitted_at_utc": iso_now,
        "anchors": {
            "adr_audit_trail": "decisions/0007-internal-audit-trail-ots.md",
            "amara_tag_67_state_file_conventions_pr": 429,
            "tomas_tag_69_welle_1_audit_anchor_pr": 439,
            "tomas_tag_70_welle_2_audit_anchor_pr": 445,
            "tomas_tag_71_welle_3_audit_anchor_pr": 450,
            "selin_tag_72_producer_pr": None,
            "tomas_tag_72_audit_anchor_pr": None,
            "state_file_conventions_doc": (
                "docs/quality-gates/welle-n-state-file-conventions.md"
            ),
            "producer_wiring_plan_doc": (
                "docs/persona-engine/state-file-producer-wiring-plan.md"
            ),
            "welle_4_context": "state-backing-snapshot-restore",
            "snapshot_restore_discipline": (
                "amara-tag-67-snapshot-restore-pflicht-flag"
            ),
        },
        "operator_hand_next_step": (
            "Selin's persona-engine batch-writer "
            "(engine.py::backfill_audit_trail_anchors, welle=4) reads "
            "this marker and writes the audit_trail_anchor into "
            "state/welle-4.json. State-Backing-Snapshot-Restore-Pflicht-"
            "Tracking surfaces on the observability channel for the "
            "restore-Pflicht gate. Real OTS calendar stamping is "
            "Operator-Hand on a network-attached host, separate step."
        ),
    }


def load_welle_4_bundle(
    *,
    rollup_path: Path,
    sign_off_path: Path,
    validation_path: Path | None,
    pre_auditor_path: Path | None,
) -> dict:
    """Load the Welle-4 sign-off-record bundle from disk.

    Same shape as ``load_welle_1_bundle`` / ``load_welle_2_bundle`` /
    ``load_welle_3_bundle``. Kept as its own symbol so a future
    Welle-4-specific schema divergence (e.g. State-Backing-Snapshot-
    Restore-specific fields) does not require touching the prior
    call-sites.
    """
    bundle: dict = {}
    bundle["rollup"] = json.loads(rollup_path.read_text(encoding="utf-8"))
    bundle["sign_off"] = json.loads(sign_off_path.read_text(encoding="utf-8"))
    if validation_path is not None:
        bundle["validation"] = json.loads(
            validation_path.read_text(encoding="utf-8")
        )
    if pre_auditor_path is not None:
        bundle["pre_auditor"] = json.loads(
            pre_auditor_path.read_text(encoding="utf-8")
        )
    return bundle


def compute_welle_5_audit_anchor_hash(bundle: dict) -> str:
    """Compute the Welle-5 audit-trail-anchor SHA-256 from a bundle.

    Identical recipe to Welle-1 / Welle-2 / Welle-3 / Welle-4
    (canonical-JSON concat in ``WELLE_5_BUNDLE_ORDER`` joined by
    ``b"\\n"``). Kept as its own symbol — rather than aliasing the
    prior entries — so a future recipe divergence (e.g. Lifecycle-
    State-Machine-specific canonicalisation or capability-token-
    payload normalisation) can be introduced without breaking the
    call-site contract that Selin's Tag-73 producer relies on.
    """
    missing = WELLE_5_BUNDLE_REQUIRED - set(bundle.keys())
    if missing:
        raise ValueError(
            f"welle-5 bundle missing required keys: {sorted(missing)}"
        )

    parts: list[bytes] = []
    for key in WELLE_5_BUNDLE_ORDER:
        if key not in bundle:
            continue
        value = bundle[key]
        if not isinstance(value, dict):
            raise ValueError(
                f"welle-5 bundle key {key!r} must be a JSON object dict, "
                f"got {type(value).__name__}"
            )
        parts.append(_canonical_json_bytes(value))

    return hashlib.sha256(b"\n".join(parts)).hexdigest()


# Allowed capability-token-rotation-status enum (defensive — narrow
# vocab so downstream consumers can dispatch on a small fixed set;
# anything else becomes "unknown" in the tracking block).
CAPABILITY_TOKEN_ROTATION_STATUS_VALUES: frozenset[str] = frozenset(
    {"pending", "rotated", "exempt", "unknown"}
)


def derive_capability_token_rotation_tracking(bundle: dict) -> dict:
    """Derive the Welle-5 ``capability_token_rotation_tracking`` block.

    Tag-73 Welle-5 carries the Capability-Token-Rotation discipline
    (Reza Sprint-9 sub: Capability-Tokens minted by ``/agent/`` SVIDs
    are short-lived and rotated on a schedule, with a replay-window
    that the sign-off declares closed at cutover-time).

    The tracking block is read from the rollup / sign-off payloads
    (in that order) so the marker can surface rotation-readiness
    without forcing downstream consumers to re-read the bundle.
    Conservative defaults: unknown status, empty iso / evidence-ref,
    rotation-active False unless the bundle says so, replay-window-
    closed False unless the sign-off says so.

    Shape::

      {
        "capability_token_rotation_active": bool,
        "capability_token_rotation_status": str (enum),
        "capability_token_last_rotation_iso": str (ISO-8601 or empty),
        "capability_token_replay_window_closed": bool,
        "capability_token_rotation_evidence_ref": str,
      }
    """
    rollup = bundle.get("rollup", {}) if isinstance(
        bundle.get("rollup"), dict
    ) else {}
    sign_off = bundle.get("sign_off", {}) if isinstance(
        bundle.get("sign_off"), dict
    ) else {}

    # Rotation-active: rollup carries the canonical value; sign-off
    # may declare it only if rollup is silent.
    rotation_active = bool(
        rollup.get(
            "capability_token_rotation_active",
            sign_off.get("capability_token_rotation_active", False),
        )
    )

    raw_status = (
        rollup.get("capability_token_rotation_status")
        or sign_off.get("capability_token_rotation_status")
        or "unknown"
    )
    if raw_status not in CAPABILITY_TOKEN_ROTATION_STATUS_VALUES:
        raw_status = "unknown"

    last_rotation_iso = (
        rollup.get("capability_token_last_rotation_iso")
        or sign_off.get("capability_token_last_rotation_iso")
        or ""
    )
    if not isinstance(last_rotation_iso, str):
        last_rotation_iso = ""

    # Replay-window-closed: sign-off carries the canonical value
    # (cutover-time declaration); rollup may surface it only as
    # a fallback (e.g. for pre-cutover tracking).
    replay_window_closed = bool(
        sign_off.get(
            "capability_token_replay_window_closed",
            rollup.get("capability_token_replay_window_closed", False),
        )
    )

    evidence_ref = (
        rollup.get("capability_token_rotation_evidence_ref")
        or sign_off.get("capability_token_rotation_evidence_ref")
        or ""
    )
    if not isinstance(evidence_ref, str):
        evidence_ref = ""

    return {
        "capability_token_rotation_active": rotation_active,
        "capability_token_rotation_status": raw_status,
        "capability_token_last_rotation_iso": last_rotation_iso,
        "capability_token_replay_window_closed": replay_window_closed,
        "capability_token_rotation_evidence_ref": evidence_ref,
    }


def build_welle_5_audit_anchor_marker(
    *,
    bundle: dict,
    anchor_hash: str,
    actor: str,
    now_utc: _dt.datetime,
) -> dict:
    """Assemble the Welle-5 audit-trail-anchor marker dict.

    Mirror of the Welle-1 / Welle-2 / Welle-3 / Welle-4 marker, with
    ``welle_number=5`` and Welle-5-specific kind strings. The marker
    is the audit-only artefact that Tomás emits and that Selin's
    Tag-73 producer reads to populate
    ``state/welle-5.json:audit_trail_anchor``.

    Tag-73 discipline: the marker exposes the
    ``capability_token_rotation_tracking`` block so the Capability-
    Token-Rotation cadence + last-rotation-iso + replay-window-closed
    flag + rotation-evidence-ref surface on the observability channel
    without re-reading the bundle (Reza Sprint-9 cross-coord).
    """
    iso_now = now_utc.isoformat()
    tracking = derive_capability_token_rotation_tracking(bundle)
    return {
        "schema_version": 1,
        "kind": WELLE_5_KIND_MARKER,
        "mode": MODE_WELLE_5_AUDIT_ANCHOR,
        "welle_number": 5,
        "audit_trail_anchor": anchor_hash,
        "bundle_keys": sorted(
            k for k in WELLE_5_BUNDLE_ORDER if k in bundle
        ),
        "capability_token_rotation_tracking": tracking,
        "wat_spool_envelope": {
            "schema_version": 1,
            "kind": WELLE_5_KIND_ENVELOPE,
            "audit_trail_anchor": anchor_hash,
            "requested_at_utc": iso_now,
            "actor": actor,
            "anchor_target": ANCHOR_TARGET_OTS_CALENDAR,
        },
        "emitted_at_utc": iso_now,
        "anchors": {
            "adr_audit_trail": "decisions/0007-internal-audit-trail-ots.md",
            "amara_tag_67_state_file_conventions_pr": 429,
            "tomas_tag_69_welle_1_audit_anchor_pr": 439,
            "tomas_tag_70_welle_2_audit_anchor_pr": 445,
            "tomas_tag_71_welle_3_audit_anchor_pr": 450,
            "tomas_tag_72_welle_4_audit_anchor_pr": 457,
            "selin_tag_73_producer_pr": None,
            "tomas_tag_73_audit_anchor_pr": None,
            "state_file_conventions_doc": (
                "docs/quality-gates/welle-n-state-file-conventions.md"
            ),
            "producer_wiring_plan_doc": (
                "docs/persona-engine/state-file-producer-wiring-plan.md"
            ),
            "welle_5_context": "lifecycle-state-machine-fsm-phantom-detection",
            "capability_token_rotation_discipline": (
                "reza-sprint-9-capability-token-rotation-replay"
            ),
        },
        "operator_hand_next_step": (
            "Selin's persona-engine batch-writer "
            "(engine.py::backfill_audit_trail_anchors, welle=5) reads "
            "this marker and writes the audit_trail_anchor into "
            "state/welle-5.json. Capability-Token-Rotation-Tracking "
            "surfaces on the observability channel for the rotation-"
            "discipline gate. Real OTS calendar stamping is "
            "Operator-Hand on a network-attached host, separate step."
        ),
    }


def load_welle_5_bundle(
    *,
    rollup_path: Path,
    sign_off_path: Path,
    validation_path: Path | None,
    pre_auditor_path: Path | None,
) -> dict:
    """Load the Welle-5 sign-off-record bundle from disk.

    Same shape as ``load_welle_1_bundle`` / ``load_welle_2_bundle`` /
    ``load_welle_3_bundle`` / ``load_welle_4_bundle``. Kept as its
    own symbol so a future Welle-5-specific schema divergence (e.g.
    Lifecycle-State-Machine-specific fields or capability-token-
    payload normalisation) does not require touching the prior
    call-sites.
    """
    bundle: dict = {}
    bundle["rollup"] = json.loads(rollup_path.read_text(encoding="utf-8"))
    bundle["sign_off"] = json.loads(sign_off_path.read_text(encoding="utf-8"))
    if validation_path is not None:
        bundle["validation"] = json.loads(
            validation_path.read_text(encoding="utf-8")
        )
    if pre_auditor_path is not None:
        bundle["pre_auditor"] = json.loads(
            pre_auditor_path.read_text(encoding="utf-8")
        )
    return bundle


# --------------------------------------------------------------------- #
# Tag-74 Welle-6 audit-trail-anchor (subscribe_loop)
# --------------------------------------------------------------------- #


def compute_welle_6_audit_anchor_hash(bundle: dict) -> str:
    """Compute the Welle-6 audit-trail-anchor SHA-256 from a bundle.

    Identical recipe to Welle-1 / Welle-2 / Welle-3 / Welle-4 / Welle-5
    (canonical-JSON concat in ``WELLE_6_BUNDLE_ORDER`` joined by
    ``b"\\n"``). Kept as its own symbol — rather than aliasing the
    prior entries — so a future recipe divergence (e.g. subscribe-loop-
    specific canonicalisation or self-repair-hygiene-payload
    normalisation) can be introduced without breaking the call-site
    contract that Selin's Tag-74 producer relies on. Recipe-identity
    with Welle-1..5 is asserted in the Tag-74 test suite (Cross-
    Substrate-Parity-Markers).
    """
    missing = WELLE_6_BUNDLE_REQUIRED - set(bundle.keys())
    if missing:
        raise ValueError(
            f"welle-6 bundle missing required keys: {sorted(missing)}"
        )

    parts: list[bytes] = []
    for key in WELLE_6_BUNDLE_ORDER:
        if key not in bundle:
            continue
        value = bundle[key]
        if not isinstance(value, dict):
            raise ValueError(
                f"welle-6 bundle key {key!r} must be a JSON object dict, "
                f"got {type(value).__name__}"
            )
        parts.append(_canonical_json_bytes(value))

    return hashlib.sha256(b"\n".join(parts)).hexdigest()


# Allowed subscribe-loop-self-repair-hygiene-status enum (defensive —
# narrow vocab so downstream consumers can dispatch on a small fixed
# set; anything else becomes "unknown" in the tracking block). Mirrors
# the Welle-5 capability-token-rotation-status enum shape.
SUBSCRIBE_LOOP_SELF_REPAIR_HYGIENE_STATUS_VALUES: frozenset[str] = frozenset(
    {"pending", "drilled", "exempt", "unknown"}
)


def derive_subscribe_loop_self_repair_hygiene_tracking(bundle: dict) -> dict:
    """Derive the Welle-6 ``subscribe_loop_self_repair_hygiene_tracking``.

    Tag-74 Welle-6 carries the subscribe-loop Self-Repair-Hygiene
    discipline (Tag-73-Lehre: PR #461 cross-Persona Self-Repair-Hygiene-
    Fix carries through to Welle-6 ``subscribe_loop`` Cutover). The
    rollup / sign-off declares whether the Self-Repair-Hygiene cycle
    was drilled prior to cutover, when the last cycle was performed,
    whether the re-subscribe-window is declared closed at cutover-time
    by the sign-off, and where the hygiene-drill evidence lives.

    The tracking block is read from the rollup / sign-off payloads
    (in that order) so the marker can surface hygiene-readiness
    without forcing downstream consumers to re-read the bundle.
    Conservative defaults: unknown status, empty iso / evidence-ref,
    hygiene-active False unless the bundle says so, re-subscribe-
    window-closed False unless the sign-off says so.

    Shape::

      {
        "subscribe_loop_self_repair_hygiene_active": bool,
        "subscribe_loop_self_repair_hygiene_status": str (enum),
        "subscribe_loop_last_hygiene_cycle_iso": str (ISO-8601 or empty),
        "subscribe_loop_re_subscribe_window_closed": bool,
        "subscribe_loop_self_repair_hygiene_evidence_ref": str,
      }
    """
    rollup = bundle.get("rollup", {}) if isinstance(
        bundle.get("rollup"), dict
    ) else {}
    sign_off = bundle.get("sign_off", {}) if isinstance(
        bundle.get("sign_off"), dict
    ) else {}

    # Hygiene-active: rollup carries the canonical value; sign-off
    # may declare it only if rollup is silent.
    hygiene_active = bool(
        rollup.get(
            "subscribe_loop_self_repair_hygiene_active",
            sign_off.get(
                "subscribe_loop_self_repair_hygiene_active", False
            ),
        )
    )

    raw_status = (
        rollup.get("subscribe_loop_self_repair_hygiene_status")
        or sign_off.get("subscribe_loop_self_repair_hygiene_status")
        or "unknown"
    )
    if raw_status not in SUBSCRIBE_LOOP_SELF_REPAIR_HYGIENE_STATUS_VALUES:
        raw_status = "unknown"

    last_cycle_iso = (
        rollup.get("subscribe_loop_last_hygiene_cycle_iso")
        or sign_off.get("subscribe_loop_last_hygiene_cycle_iso")
        or ""
    )
    if not isinstance(last_cycle_iso, str):
        last_cycle_iso = ""

    # Re-subscribe-window-closed: sign-off carries the canonical value
    # (cutover-time declaration); rollup may surface it only as a
    # fallback (e.g. for pre-cutover tracking). Mirrors Welle-5
    # replay-window-closed precedence.
    re_subscribe_window_closed = bool(
        sign_off.get(
            "subscribe_loop_re_subscribe_window_closed",
            rollup.get(
                "subscribe_loop_re_subscribe_window_closed", False
            ),
        )
    )

    evidence_ref = (
        rollup.get("subscribe_loop_self_repair_hygiene_evidence_ref")
        or sign_off.get("subscribe_loop_self_repair_hygiene_evidence_ref")
        or ""
    )
    if not isinstance(evidence_ref, str):
        evidence_ref = ""

    return {
        "subscribe_loop_self_repair_hygiene_active": hygiene_active,
        "subscribe_loop_self_repair_hygiene_status": raw_status,
        "subscribe_loop_last_hygiene_cycle_iso": last_cycle_iso,
        "subscribe_loop_re_subscribe_window_closed": re_subscribe_window_closed,
        "subscribe_loop_self_repair_hygiene_evidence_ref": evidence_ref,
    }


def build_welle_6_audit_anchor_marker(
    *,
    bundle: dict,
    anchor_hash: str,
    actor: str,
    now_utc: _dt.datetime,
) -> dict:
    """Assemble the Welle-6 audit-trail-anchor marker dict.

    Mirror of the Welle-1 / Welle-2 / Welle-3 / Welle-4 / Welle-5
    marker, with ``welle_number=6`` and Welle-6-specific kind strings.
    The marker is the audit-only artefact that Tomás emits and that
    Selin's Tag-74 producer reads to populate
    ``state/welle-6.json:audit_trail_anchor``.

    Tag-74 discipline: the marker exposes the
    ``subscribe_loop_self_repair_hygiene_tracking`` block so the
    Self-Repair-Hygiene cadence + last-cycle-iso + re-subscribe-window-
    closed flag + hygiene-evidence-ref surface on the observability
    channel without re-reading the bundle (Tag-73-Lehre carry-through:
    PR #461 cross-Persona Self-Repair-Hygiene-Fix discipline).

    Cross-Substrate-Parity-Markers (Tag-74 auftrag): the ``anchors``
    block references Welle-1..5 cross-coord PRs so a downstream
    consumer can trace the full Welle-1..6 audit-anchor lineage in
    a single envelope.
    """
    iso_now = now_utc.isoformat()
    tracking = derive_subscribe_loop_self_repair_hygiene_tracking(bundle)
    return {
        "schema_version": 1,
        "kind": WELLE_6_KIND_MARKER,
        "mode": MODE_WELLE_6_AUDIT_ANCHOR,
        "welle_number": 6,
        "audit_trail_anchor": anchor_hash,
        "bundle_keys": sorted(
            k for k in WELLE_6_BUNDLE_ORDER if k in bundle
        ),
        "subscribe_loop_self_repair_hygiene_tracking": tracking,
        "wat_spool_envelope": {
            "schema_version": 1,
            "kind": WELLE_6_KIND_ENVELOPE,
            "audit_trail_anchor": anchor_hash,
            "requested_at_utc": iso_now,
            "actor": actor,
            "anchor_target": ANCHOR_TARGET_OTS_CALENDAR,
        },
        "emitted_at_utc": iso_now,
        "anchors": {
            "adr_audit_trail": "decisions/0007-internal-audit-trail-ots.md",
            "amara_tag_67_state_file_conventions_pr": 429,
            "tomas_tag_69_welle_1_audit_anchor_pr": 439,
            "tomas_tag_70_welle_2_audit_anchor_pr": 445,
            "tomas_tag_71_welle_3_audit_anchor_pr": 450,
            "tomas_tag_72_welle_4_audit_anchor_pr": 457,
            "tomas_tag_73_welle_5_audit_anchor_pr": 464,
            "selin_tag_74_producer_pr": None,
            "tomas_tag_74_audit_anchor_pr": None,
            "state_file_conventions_doc": (
                "docs/quality-gates/welle-n-state-file-conventions.md"
            ),
            "producer_wiring_plan_doc": (
                "docs/persona-engine/state-file-producer-wiring-plan.md"
            ),
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
        "operator_hand_next_step": (
            "Selin's persona-engine batch-writer "
            "(engine.py::backfill_audit_trail_anchors, welle=6) reads "
            "this marker and writes the audit_trail_anchor into "
            "state/welle-6.json. Subscribe-Loop-Self-Repair-Hygiene-"
            "Tracking surfaces on the observability channel for the "
            "hygiene-discipline gate. Real OTS calendar stamping is "
            "Operator-Hand on a network-attached host, separate step."
        ),
    }


def load_welle_6_bundle(
    *,
    rollup_path: Path,
    sign_off_path: Path,
    validation_path: Path | None,
    pre_auditor_path: Path | None,
) -> dict:
    """Load the Welle-6 sign-off-record bundle from disk.

    Same shape as ``load_welle_1_bundle`` / ``load_welle_2_bundle`` /
    ``load_welle_3_bundle`` / ``load_welle_4_bundle`` /
    ``load_welle_5_bundle``. Kept as its own symbol so a future
    Welle-6-specific schema divergence (e.g. subscribe-loop-specific
    fields or self-repair-hygiene-payload normalisation) does not
    require touching the prior call-sites.
    """
    bundle: dict = {}
    bundle["rollup"] = json.loads(rollup_path.read_text(encoding="utf-8"))
    bundle["sign_off"] = json.loads(sign_off_path.read_text(encoding="utf-8"))
    if validation_path is not None:
        bundle["validation"] = json.loads(
            validation_path.read_text(encoding="utf-8")
        )
    if pre_auditor_path is not None:
        bundle["pre_auditor"] = json.loads(
            pre_auditor_path.read_text(encoding="utf-8")
        )
    return bundle


def compute_welle_7_audit_anchor_hash(bundle: dict) -> str:
    """Compute the Welle-7 audit-trail-anchor SHA-256 from a bundle.

    Identical recipe to Welle-1..6 (canonical-JSON concat in
    ``WELLE_7_BUNDLE_ORDER`` joined by ``b"\\n"``). Kept as its own
    symbol — rather than aliasing the prior entries — so a future
    Welle-7-specific recipe divergence (e.g. final-sealing-specific
    canonicalisation or Phase-3-COMPLETE-marker-payload normalisation)
    can be introduced without breaking the call-site contract. Recipe-
    identity with Welle-1..6 is asserted in the Tag-75 test suite
    (Welle-1..7-Kind-Disjointness-Pin).
    """
    missing = WELLE_7_BUNDLE_REQUIRED - set(bundle.keys())
    if missing:
        raise ValueError(
            f"welle-7 bundle missing required keys: {sorted(missing)}"
        )

    parts: list[bytes] = []
    for key in WELLE_7_BUNDLE_ORDER:
        if key not in bundle:
            continue
        value = bundle[key]
        if not isinstance(value, dict):
            raise ValueError(
                f"welle-7 bundle key {key!r} must be a JSON object dict, "
                f"got {type(value).__name__}"
            )
        parts.append(_canonical_json_bytes(value))

    return hashlib.sha256(b"\n".join(parts)).hexdigest()


# Allowed phase-3-final-sealing-status enum (defensive — narrow vocab
# so downstream consumers can dispatch on a small fixed set; anything
# else becomes "unknown" in the tracking block). Mirrors the Welle-6
# subscribe-loop-self-repair-hygiene-status enum shape.
PHASE_3_FINAL_SEALING_STATUS_VALUES: frozenset[str] = frozenset(
    {"pending", "sealed", "escalated", "unknown"}
)


def derive_phase_3_final_sealing_tracking(bundle: dict) -> dict:
    """Derive the Welle-7 ``phase_3_final_sealing_tracking`` block.

    Tag-75 Welle-7 is the FINAL Welle of the Phase-3c-Welle-Marathon
    (Post-Welle-7 = Global Acceptance-Verdict per the run-order doc
    §3.2). The rollup / sign-off declares whether Final-Sealing was
    activated for this cutover, the canonical sealing-iso (the
    timestamp at which Final-Sealing was recorded), whether the
    Global-Acceptance-Verdict has been recorded by the verdict-
    aggregator (necessary precondition for the Phase-3-COMPLETE-
    marker per Surface-1..5 conjunction), whether the Phase-3-
    COMPLETE-marker is ready to fire, and where the Final-Sealing
    evidence lives.

    The tracking block is read from the rollup / sign-off payloads
    (in that order) so the marker can surface sealing-readiness
    without forcing downstream consumers to re-read the bundle.
    Conservative defaults: unknown status, empty iso / evidence-ref,
    sealing-active False unless the bundle says so, global-
    acceptance-verdict-recorded False unless the sign-off says so,
    Phase-3-COMPLETE-marker-ready False unless the sign-off says so.

    Shape::

      {
        "phase_3_final_sealing_active": bool,
        "phase_3_final_sealing_status": str (enum),
        "phase_3_final_sealing_iso": str (ISO-8601 or empty),
        "global_acceptance_verdict_recorded": bool,
        "phase_3_complete_marker_ready": bool,
        "phase_3_final_sealing_evidence_ref": str,
      }
    """
    rollup = bundle.get("rollup", {}) if isinstance(
        bundle.get("rollup"), dict
    ) else {}
    sign_off = bundle.get("sign_off", {}) if isinstance(
        bundle.get("sign_off"), dict
    ) else {}

    # Sealing-active: rollup carries the canonical value; sign-off may
    # declare it only if rollup is silent.
    sealing_active = bool(
        rollup.get(
            "phase_3_final_sealing_active",
            sign_off.get("phase_3_final_sealing_active", False),
        )
    )

    raw_status = (
        rollup.get("phase_3_final_sealing_status")
        or sign_off.get("phase_3_final_sealing_status")
        or "unknown"
    )
    if raw_status not in PHASE_3_FINAL_SEALING_STATUS_VALUES:
        raw_status = "unknown"

    sealing_iso = (
        rollup.get("phase_3_final_sealing_iso")
        or sign_off.get("phase_3_final_sealing_iso")
        or ""
    )
    if not isinstance(sealing_iso, str):
        sealing_iso = ""

    # Global-Acceptance-Verdict-recorded: sign-off carries the canonical
    # value (sign-off-Freitag = the moment the verdict is recorded);
    # rollup may surface it only as a fallback (e.g. for pre-sign-off
    # tracking).
    global_verdict_recorded = bool(
        sign_off.get(
            "global_acceptance_verdict_recorded",
            rollup.get("global_acceptance_verdict_recorded", False),
        )
    )

    # Phase-3-COMPLETE-marker-ready: same precedence as global-
    # acceptance-verdict-recorded (sign-off canonical).
    complete_marker_ready = bool(
        sign_off.get(
            "phase_3_complete_marker_ready",
            rollup.get("phase_3_complete_marker_ready", False),
        )
    )

    evidence_ref = (
        rollup.get("phase_3_final_sealing_evidence_ref")
        or sign_off.get("phase_3_final_sealing_evidence_ref")
        or ""
    )
    if not isinstance(evidence_ref, str):
        evidence_ref = ""

    return {
        "phase_3_final_sealing_active": sealing_active,
        "phase_3_final_sealing_status": raw_status,
        "phase_3_final_sealing_iso": sealing_iso,
        "global_acceptance_verdict_recorded": global_verdict_recorded,
        "phase_3_complete_marker_ready": complete_marker_ready,
        "phase_3_final_sealing_evidence_ref": evidence_ref,
    }


def build_welle_7_audit_anchor_marker(
    *,
    bundle: dict,
    anchor_hash: str,
    actor: str,
    now_utc: _dt.datetime,
) -> dict:
    """Assemble the Welle-7 audit-trail-anchor marker dict.

    Mirror of the Welle-1..6 marker, with ``welle_number=7`` and
    Welle-7-specific kind strings. The marker is the audit-only
    artefact that Tomás emits and that Selin's Tag-75 producer reads
    to populate ``state/welle-7.json:audit_trail_anchor``.

    Tag-75 discipline: the marker exposes the
    ``phase_3_final_sealing_tracking`` block so the Phase-3 Final-
    Sealing status + global-acceptance-verdict-recorded + Phase-3-
    COMPLETE-marker-ready flag surface on the observability channel
    without re-reading the bundle.

    Pre-Auditor-Signaling-Markers (Tag-75 auftrag, final-welle
    variant): the marker carries TWO signaling flags:

      * ``pre_auditor_signaling_ready`` (bool) — true iff a
        pre-auditor-decision is present in the bundle. Mirror of the
        Tag-71 Welle-3 flag.
      * ``pre_auditor_final_sealing_signaling_ready`` (bool) — true
        iff (a) pre-auditor-decision is present AND (b) the final-
        sealing-tracking block reports
        ``global_acceptance_verdict_recorded == True``. This is the
        canonical Tomás -> Henrik hand-off signal for Phase-3-
        COMPLETE-marker readiness at Post-Welle-7 sign-off.

    Cross-Substrate-Parity-Markers (Tag-75 auftrag): the ``anchors``
    block references Welle-1..6 cross-coord PRs so a downstream
    consumer can trace the full Welle-1..7 audit-anchor lineage in a
    single envelope (Welle-1..7-Kind-Disjointness-Pin: same hash
    recipe across all seven Wellen, distinct marker/envelope kind
    strings per Welle).
    """
    iso_now = now_utc.isoformat()
    tracking = derive_phase_3_final_sealing_tracking(bundle)
    pre_auditor_present = "pre_auditor" in bundle and isinstance(
        bundle.get("pre_auditor"), dict
    )
    final_sealing_signaling_ready = bool(
        pre_auditor_present
        and tracking["global_acceptance_verdict_recorded"]
    )
    return {
        "schema_version": 1,
        "kind": WELLE_7_KIND_MARKER,
        "mode": MODE_WELLE_7_AUDIT_ANCHOR,
        "welle_number": 7,
        "audit_trail_anchor": anchor_hash,
        "bundle_keys": sorted(
            k for k in WELLE_7_BUNDLE_ORDER if k in bundle
        ),
        "phase_3_final_sealing_tracking": tracking,
        "pre_auditor_signaling_ready": pre_auditor_present,
        "pre_auditor_final_sealing_signaling_ready": (
            final_sealing_signaling_ready
        ),
        "wat_spool_envelope": {
            "schema_version": 1,
            "kind": WELLE_7_KIND_ENVELOPE,
            "audit_trail_anchor": anchor_hash,
            "requested_at_utc": iso_now,
            "actor": actor,
            "anchor_target": ANCHOR_TARGET_OTS_CALENDAR,
        },
        "emitted_at_utc": iso_now,
        "anchors": {
            "adr_audit_trail": "decisions/0007-internal-audit-trail-ots.md",
            "amara_tag_67_state_file_conventions_pr": 429,
            "tomas_tag_69_welle_1_audit_anchor_pr": 439,
            "tomas_tag_70_welle_2_audit_anchor_pr": 445,
            "tomas_tag_71_welle_3_audit_anchor_pr": 450,
            "tomas_tag_72_welle_4_audit_anchor_pr": 457,
            "tomas_tag_73_welle_5_audit_anchor_pr": 464,
            "tomas_tag_74_welle_6_audit_anchor_pr": 470,
            "selin_tag_75_producer_pr": None,
            "tomas_tag_75_audit_anchor_pr": None,
            "state_file_conventions_doc": (
                "docs/quality-gates/welle-n-state-file-conventions.md"
            ),
            "producer_wiring_plan_doc": (
                "docs/persona-engine/state-file-producer-wiring-plan.md"
            ),
            "pre_cutover_acceptance_run_order_doc": (
                "docs/quality-gates/pre-cutover-acceptance-run-order.md"
            ),
            "phase_3_marathon_final_acceptance_doc": (
                "docs/quality-gates/phase-3-marathon-final-acceptance.md"
            ),
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
        "operator_hand_next_step": (
            "Selin's persona-engine batch-writer "
            "(engine.py::backfill_audit_trail_anchors, welle=7) reads "
            "this marker and writes the audit_trail_anchor into "
            "state/welle-7.json. Phase-3-Final-Sealing-Tracking + "
            "Pre-Auditor-Final-Sealing-Signaling-Ready surface on "
            "the observability channel for Henrik's Zone-N Audit-"
            "Evidence-Index hand-off (Phase-3-COMPLETE-marker "
            "readiness gate). Real OTS calendar stamping is "
            "Operator-Hand on a network-attached host, separate step."
        ),
    }


def load_welle_7_bundle(
    *,
    rollup_path: Path,
    sign_off_path: Path,
    validation_path: Path | None,
    pre_auditor_path: Path | None,
) -> dict:
    """Load the Welle-7 sign-off-record bundle from disk.

    Same shape as ``load_welle_1_bundle`` .. ``load_welle_6_bundle``.
    Kept as its own symbol so a future Welle-7-specific schema
    divergence (e.g. final-sealing-specific fields or Phase-3-
    COMPLETE-marker-payload normalisation) does not require touching
    the prior call-sites.
    """
    bundle: dict = {}
    bundle["rollup"] = json.loads(rollup_path.read_text(encoding="utf-8"))
    bundle["sign_off"] = json.loads(sign_off_path.read_text(encoding="utf-8"))
    if validation_path is not None:
        bundle["validation"] = json.loads(
            validation_path.read_text(encoding="utf-8")
        )
    if pre_auditor_path is not None:
        bundle["pre_auditor"] = json.loads(
            pre_auditor_path.read_text(encoding="utf-8")
        )
    return bundle


def load_phase_3_complete_bundle(
    *,
    welle_marker_paths: list[Path],
) -> list[dict]:
    """Load the seven Welle-N audit-anchor markers from disk.

    The returned list is sorted by ``welle_number`` ascending so the
    closeout bundle hash is deterministic regardless of the input
    order.

    Raises ``OSError`` if a file is unreadable, ``json.JSONDecodeError``
    if a file is malformed, and ``ValueError`` if the markers do not
    cover welle_number 1..7 exactly.
    """
    if len(welle_marker_paths) != PHASE_3_COMPLETE_WELLE_COUNT:
        raise ValueError(
            f"phase-3-complete bundle expects "
            f"{PHASE_3_COMPLETE_WELLE_COUNT} welle markers, "
            f"got {len(welle_marker_paths)}"
        )

    markers: list[dict] = []
    for path in welle_marker_paths:
        markers.append(json.loads(path.read_text(encoding="utf-8")))

    return sorted(markers, key=lambda m: m.get("welle_number", -1))


def assert_welle_1_7_kind_disjointness_pin(markers: list[dict]) -> None:
    """Enforce the Welle-1..7-Kind-Disjointness-Pin at ingest.

    The seven input markers must:

      * cover ``welle_number`` 1..7 exactly with no duplicates and
        no gaps,
      * carry the expected ``kind`` string for their welle_number
        (``welle-N-audit-trail-anchor-marker``),
      * carry a 64-hex ``audit_trail_anchor``.

    Raises ``ValueError`` on any deviation.
    """
    if len(markers) != PHASE_3_COMPLETE_WELLE_COUNT:
        raise ValueError(
            f"phase-3-complete bundle expects "
            f"{PHASE_3_COMPLETE_WELLE_COUNT} markers, got {len(markers)}"
        )

    seen_welle_numbers: list[int] = []
    for idx, marker in enumerate(markers):
        if not isinstance(marker, dict):
            raise ValueError(
                f"phase-3-complete bundle marker #{idx} is not a dict: "
                f"{type(marker).__name__}"
            )
        welle_number = marker.get("welle_number")
        expected_welle = PHASE_3_COMPLETE_EXPECTED_WELLE_NUMBERS[idx]
        if welle_number != expected_welle:
            raise ValueError(
                f"phase-3-complete bundle marker #{idx} carries "
                f"welle_number={welle_number!r}, expected "
                f"{expected_welle} (markers must be sorted 1..7 "
                f"with no gaps and no duplicates)"
            )
        if welle_number in seen_welle_numbers:
            raise ValueError(
                f"phase-3-complete bundle marker #{idx} has "
                f"duplicate welle_number={welle_number}"
            )
        seen_welle_numbers.append(welle_number)

        expected_kind = PHASE_3_COMPLETE_EXPECTED_KINDS[idx]
        if marker.get("kind") != expected_kind:
            raise ValueError(
                f"phase-3-complete bundle marker #{idx} "
                f"(welle_number={welle_number}) carries "
                f"kind={marker.get('kind')!r}, expected "
                f"{expected_kind!r} (Welle-1..7-Kind-Disjointness-Pin "
                f"violated)"
            )

        anchor = marker.get("audit_trail_anchor")
        if not isinstance(anchor, str) or len(anchor) != 64 or not all(
            c in "0123456789abcdef" for c in anchor
        ):
            raise ValueError(
                f"phase-3-complete bundle marker #{idx} "
                f"(welle_number={welle_number}) carries an invalid "
                f"audit_trail_anchor (must be 64-hex SHA-256), got "
                f"{anchor!r}"
            )


def compute_phase_3_complete_bundle_anchor(markers: list[dict]) -> str:
    """Compute the Phase-3-COMPLETE bundle SHA-256 from seven markers.

    Hash recipe: identical to the per-Welle recipe (canonical-JSON
    of each Welle marker dict, concatenated in welle-number order
    with a single ``b"\\n"`` separator, SHA-256 over concat).
    Assumes the markers are already sorted by welle_number and have
    passed ``assert_welle_1_7_kind_disjointness_pin``.
    """
    parts: list[bytes] = []
    for marker in markers:
        parts.append(_canonical_json_bytes(marker))
    return hashlib.sha256(b"\n".join(parts)).hexdigest()


def derive_phase_3_complete_summary(markers: list[dict]) -> dict:
    """Derive the Phase-3-COMPLETE summary from the seven markers.

    Surfaces the Phase-3-Final-Sealing-Tracking block (sourced from
    the Welle-7 marker) plus the two Tag-75 signaling flags
    (``global_acceptance_verdict_recorded``,
    ``pre_auditor_final_sealing_signaling_ready``) so the Henrik
    Zone-N hand-off does not have to re-read the welle bundles.
    """
    # markers[-1] is Welle-7 after sort.
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
        welle_7.get(
            "pre_auditor_final_sealing_signaling_ready", False
        )
    )
    return {
        "phase_3_final_sealing_tracking": dict(tracking),
        "global_acceptance_verdict_recorded": global_acceptance,
        "phase_3_complete_marker_ready": complete_ready,
        "pre_auditor_final_sealing_signaling_ready": (
            pre_auditor_final_sealing
        ),
    }


def build_phase_3_complete_marker(
    *,
    markers: list[dict],
    bundle_anchor: str,
    actor: str,
    now_utc: _dt.datetime,
) -> dict:
    """Assemble the Phase-3-COMPLETE marker dict (Tag-76).

    Marathon-Closeout-Audit-Anchor-Bundle. Bundles the seven
    Welle-N audit-anchor markers under a single byte-stable
    envelope keyed by ``phase_3_complete_bundle_anchor`` so
    Henrik's Zone-N Audit-Evidence-Index can dispatch the Phase-3-
    COMPLETE hand-off from one file.
    """
    iso_now = now_utc.isoformat()
    summary = derive_phase_3_complete_summary(markers)
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
        "kind": PHASE_3_COMPLETE_KIND_MARKER,
        "mode": MODE_PHASE_3_COMPLETE_MARKER,
        "phase_3_complete_bundle_anchor": bundle_anchor,
        "welle_bundle_count": PHASE_3_COMPLETE_WELLE_COUNT,
        "welle_bundle_anchors": bundle_anchors,
        "phase_3_final_sealing_tracking": summary[
            "phase_3_final_sealing_tracking"
        ],
        "global_acceptance_verdict_recorded": summary[
            "global_acceptance_verdict_recorded"
        ],
        "phase_3_complete_marker_ready": summary[
            "phase_3_complete_marker_ready"
        ],
        "pre_auditor_final_sealing_signaling_ready": summary[
            "pre_auditor_final_sealing_signaling_ready"
        ],
        "welle_1_7_kind_disjointness_pin_ok": True,
        "wat_spool_envelope": {
            "schema_version": 1,
            "kind": PHASE_3_COMPLETE_KIND_ENVELOPE,
            "phase_3_complete_bundle_anchor": bundle_anchor,
            "requested_at_utc": iso_now,
            "actor": actor,
            "anchor_target": ANCHOR_TARGET_OTS_CALENDAR,
        },
        "emitted_at_utc": iso_now,
        "anchors": {
            "adr_audit_trail": "decisions/0007-internal-audit-trail-ots.md",
            "amara_tag_67_state_file_conventions_pr": 429,
            "tomas_tag_69_welle_1_audit_anchor_pr": 439,
            "tomas_tag_70_welle_2_audit_anchor_pr": 445,
            "tomas_tag_71_welle_3_audit_anchor_pr": 450,
            "tomas_tag_72_welle_4_audit_anchor_pr": 457,
            "tomas_tag_73_welle_5_audit_anchor_pr": 464,
            "tomas_tag_74_welle_6_audit_anchor_pr": 470,
            "tomas_tag_75_welle_7_audit_anchor_pr": 477,
            "tomas_tag_76_closeout_bundle_pr": None,
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
        "operator_hand_next_step": (
            "Henrik's Zone-N Audit-Evidence-Index ingests this "
            "Phase-3-COMPLETE marker as the canonical Marathon-"
            "Closeout hand-off envelope. The bundle anchor "
            "consolidates the Welle-1..7 audit-trail-anchors into "
            "a single byte-stable artefact. Real OTS calendar "
            "stamping of the Phase-3-COMPLETE marker is an "
            "Operator-Hand follow-up step on a network-attached "
            "host, separate from this audit-only emit."
        ),
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="emit_manifest_hash_ots_marker",
        description=(
            "Emit an audit-only OTS-anchor marker for a persona-engine "
            "manifest hash (Tag-57 OPEN-K2, audit-only mode), or run a "
            "Tag-59 pre-activation-probe verdict (--mode "
            "pre-activation-probe)."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=(
            MODE_AUDIT_ONLY,
            MODE_PRE_ACTIVATION_PROBE,
            MODE_WELLE_1_AUDIT_ANCHOR,
            MODE_WELLE_2_AUDIT_ANCHOR,
            MODE_WELLE_3_AUDIT_ANCHOR,
            MODE_WELLE_4_AUDIT_ANCHOR,
            MODE_WELLE_5_AUDIT_ANCHOR,
            MODE_WELLE_6_AUDIT_ANCHOR,
            MODE_WELLE_7_AUDIT_ANCHOR,
            MODE_PHASE_3_COMPLETE_MARKER,
        ),
        default=MODE_AUDIT_ONLY,
        help=(
            "audit-only (default, Tag-57): emit marker JSON. "
            "pre-activation-probe (Tag-59): run hermetic dry-run probe "
            "of the OTS-call pipeline and emit verdict envelope. "
            "welle-1-audit-anchor (Tag-69): compute Welle-1 audit-"
            "trail-anchor SHA-256 from sign-off-record bundle "
            "(rollup + sign-off + validation + pre-auditor) and emit "
            "marker JSON for Selin's persona-engine producer. "
            "welle-2-audit-anchor (Tag-70): same as welle-1 mode, but "
            "for the Welle-2 Doppelbetrieb-Sealing bundle. "
            "welle-3-audit-anchor (Tag-71): same as welle-1 / welle-2 "
            "mode, but for the Welle-3 Bridge-Audit-Writer bundle. "
            "Carries Henrik-IIA-1130 §11-Discipline pre-auditor "
            "signaling flag. "
            "welle-4-audit-anchor (Tag-72): same as welle-1 / welle-2 / "
            "welle-3 mode, but for the Welle-4 State-Backing-Snapshot-"
            "Restore bundle. Carries the snapshot_restore_pflicht_"
            "tracking block (Amara Tag-67 Pflicht-Flag). "
            "welle-5-audit-anchor (Tag-73): same as welle-1 / welle-2 / "
            "welle-3 / welle-4 mode, but for the Welle-5 Lifecycle-"
            "State-Machine / FSM-Phantom-Detection bundle. Carries "
            "the capability_token_rotation_tracking block (Reza "
            "Sprint-9 Capability-Token-Rotation+Replay sub). "
            "welle-6-audit-anchor (Tag-74): same recipe as welle-1..5 "
            "(Cross-Substrate-Parity-Markers), but for the Welle-6 "
            "subscribe_loop Cutover bundle (KW-27, parallel to "
            "Welle-7). Carries the subscribe_loop_self_repair_hygiene_"
            "tracking block (Tag-73-Lehre: PR #461 cross-Persona "
            "Self-Repair-Hygiene-Fix carry-through). "
            "welle-7-audit-anchor (Tag-75): same recipe as welle-1..6 "
            "(Cross-Substrate-Parity-Markers, full Welle-1..7-Kind-"
            "Disjointness-Pin), but for the FINAL Welle-7 Final-"
            "Sealing bundle (KW-27 Doppel-Welle-6+7, Cutover "
            "2026-07-01, Sign-off-Freitag 2026-07-03 = Global "
            "Acceptance-Verdict). Carries the phase_3_final_sealing_"
            "tracking block + Pre-Auditor-Final-Sealing-Signaling-"
            "Markers (Tomás -> Henrik hand-off signal for Phase-3-"
            "COMPLETE-marker readiness). "
            "phase-3-complete-marker (Tag-76): consolidates the "
            "seven Welle-N audit-anchor markers (outputs of "
            "welle-1..7-audit-anchor modes) into a single Marathon-"
            "Closeout-Audit-Anchor-Bundle. Bundle hash recipe "
            "identical to per-Welle recipe (canonical-JSON concat + "
            "SHA-256). Enforces the Welle-1..7-Kind-Disjointness-Pin "
            "at ingest. Surfaces Phase-3-Final-Sealing-Tracking + "
            "global-acceptance-verdict-recorded + Phase-3-COMPLETE-"
            "marker-ready + Pre-Auditor-Final-Sealing-Signaling-"
            "Ready (all sourced from welle-7) so Henrik's Zone-N "
            "Audit-Evidence-Index hand-off dispatches without "
            "re-reading the underlying bundles."
        ),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        required=False,
        default=None,
        help=(
            "Path to the manifest file to hash "
            "(required for audit-only / pre-activation-probe modes). "
            "Ignored in welle-1-audit-anchor mode."
        ),
    )
    parser.add_argument(
        "--welle-1-rollup",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-1.json (required for "
            "welle-1-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-1-sign-off",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-1-sign-off.json (required for "
            "welle-1-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-1-validation",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-1-validation-last-verdict.json "
            "(optional for welle-1-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-1-pre-auditor",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-1-pre-auditor-decision.json "
            "(optional for welle-1-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-2-rollup",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-2.json (required for "
            "welle-2-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-2-sign-off",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-2-sign-off.json (required for "
            "welle-2-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-2-validation",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-2-validation-last-verdict.json "
            "(optional for welle-2-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-2-pre-auditor",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-2-pre-auditor-decision.json "
            "(optional for welle-2-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-3-rollup",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-3.json (required for "
            "welle-3-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-3-sign-off",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-3-sign-off.json (required for "
            "welle-3-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-3-validation",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-3-validation-last-verdict.json "
            "(optional for welle-3-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-3-pre-auditor",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-3-pre-auditor-decision.json "
            "(optional for welle-3-audit-anchor mode; recommended for "
            "Henrik-IIA-1130 §11-Discipline pre-auditor signaling)."
        ),
    )
    parser.add_argument(
        "--welle-4-rollup",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-4.json (required for "
            "welle-4-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-4-sign-off",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-4-sign-off.json (required for "
            "welle-4-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-4-validation",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-4-validation-last-verdict.json "
            "(optional for welle-4-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-4-pre-auditor",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-4-pre-auditor-decision.json "
            "(optional for welle-4-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-5-rollup",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-5.json (required for "
            "welle-5-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-5-sign-off",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-5-sign-off.json (required for "
            "welle-5-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-5-validation",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-5-validation-last-verdict.json "
            "(optional for welle-5-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-5-pre-auditor",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-5-pre-auditor-decision.json "
            "(optional for welle-5-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-6-rollup",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-6.json (required for "
            "welle-6-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-6-sign-off",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-6-sign-off.json (required for "
            "welle-6-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-6-validation",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-6-validation-last-verdict.json "
            "(optional for welle-6-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-6-pre-auditor",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-6-pre-auditor-decision.json "
            "(optional for welle-6-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-7-rollup",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-7.json (required for "
            "welle-7-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-7-sign-off",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-7-sign-off.json (required for "
            "welle-7-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-7-validation",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-7-validation-last-verdict.json "
            "(optional for welle-7-audit-anchor mode)."
        ),
    )
    parser.add_argument(
        "--welle-7-pre-auditor",
        type=Path,
        default=None,
        help=(
            "Path to state/welle-7-pre-auditor-decision.json "
            "(optional for welle-7-audit-anchor mode; recommended "
            "for Phase-3-COMPLETE-marker readiness signaling)."
        ),
    )
    parser.add_argument(
        "--welle-1-marker",
        type=Path,
        default=None,
        help=(
            "Path to the Welle-1 audit-anchor marker JSON "
            "(required for phase-3-complete-marker mode)."
        ),
    )
    parser.add_argument(
        "--welle-2-marker",
        type=Path,
        default=None,
        help=(
            "Path to the Welle-2 audit-anchor marker JSON "
            "(required for phase-3-complete-marker mode)."
        ),
    )
    parser.add_argument(
        "--welle-3-marker",
        type=Path,
        default=None,
        help=(
            "Path to the Welle-3 audit-anchor marker JSON "
            "(required for phase-3-complete-marker mode)."
        ),
    )
    parser.add_argument(
        "--welle-4-marker",
        type=Path,
        default=None,
        help=(
            "Path to the Welle-4 audit-anchor marker JSON "
            "(required for phase-3-complete-marker mode)."
        ),
    )
    parser.add_argument(
        "--welle-5-marker",
        type=Path,
        default=None,
        help=(
            "Path to the Welle-5 audit-anchor marker JSON "
            "(required for phase-3-complete-marker mode)."
        ),
    )
    parser.add_argument(
        "--welle-6-marker",
        type=Path,
        default=None,
        help=(
            "Path to the Welle-6 audit-anchor marker JSON "
            "(required for phase-3-complete-marker mode)."
        ),
    )
    parser.add_argument(
        "--welle-7-marker",
        type=Path,
        default=None,
        help=(
            "Path to the Welle-7 audit-anchor marker JSON "
            "(required for phase-3-complete-marker mode)."
        ),
    )
    parser.add_argument(
        "--marker-out",
        type=Path,
        default=None,
        help=(
            "Output JSON marker path (mode=audit-only; required). "
            "Parent dir will be mkdir -p'd."
        ),
    )
    parser.add_argument(
        "--probe-verdict-out",
        type=Path,
        default=None,
        help=(
            "Output JSON probe-verdict path (mode=pre-activation-probe; "
            "required). Parent dir will be mkdir -p'd."
        ),
    )
    parser.add_argument(
        "--actor",
        default=os.environ.get("GITHUB_ACTOR", "local"),
        help="Actor identifier (default: $GITHUB_ACTOR or 'local').",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root (default: cwd).",
    )
    parser.add_argument(
        "--now",
        default=None,
        help=(
            "Override emitted_at_utc / requested_at_utc / probed_at_utc "
            "(ISO-8601). Useful for deterministic tests."
        ),
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.now is None:
        now_utc = _dt.datetime.now(_dt.timezone.utc)
    else:
        # ``fromisoformat`` accepts ``+00:00`` and naive forms; we
        # coerce naive to UTC.
        now_utc = _dt.datetime.fromisoformat(args.now)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=_dt.timezone.utc)

    if args.mode == MODE_WELLE_1_AUDIT_ANCHOR:
        if args.welle_1_rollup is None or args.welle_1_sign_off is None:
            print(
                "emit_manifest_hash_ots_marker: "
                "--welle-1-rollup and --welle-1-sign-off are required "
                "when --mode welle-1-audit-anchor",
                file=sys.stderr,
            )
            return 2
        if args.marker_out is None:
            print(
                "emit_manifest_hash_ots_marker: "
                "--marker-out is required when --mode welle-1-audit-anchor",
                file=sys.stderr,
            )
            return 2

        if not args.welle_1_rollup.is_file():
            print(
                f"emit_manifest_hash_ots_marker: --welle-1-rollup not "
                f"a file: {args.welle_1_rollup}",
                file=sys.stderr,
            )
            return 1
        if not args.welle_1_sign_off.is_file():
            print(
                f"emit_manifest_hash_ots_marker: --welle-1-sign-off "
                f"not a file: {args.welle_1_sign_off}",
                file=sys.stderr,
            )
            return 1

        try:
            bundle = load_welle_1_bundle(
                rollup_path=args.welle_1_rollup,
                sign_off_path=args.welle_1_sign_off,
                validation_path=(
                    args.welle_1_validation
                    if args.welle_1_validation
                    and args.welle_1_validation.is_file()
                    else None
                ),
                pre_auditor_path=(
                    args.welle_1_pre_auditor
                    if args.welle_1_pre_auditor
                    and args.welle_1_pre_auditor.is_file()
                    else None
                ),
            )
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"emit_manifest_hash_ots_marker: welle-1 bundle "
                f"read/parse error: {exc}",
                file=sys.stderr,
            )
            return 1

        try:
            anchor_hash = compute_welle_1_audit_anchor_hash(bundle)
        except ValueError as exc:
            print(
                f"emit_manifest_hash_ots_marker: welle-1 bundle "
                f"shape error: {exc}",
                file=sys.stderr,
            )
            return 1

        marker = build_welle_1_audit_anchor_marker(
            bundle=bundle,
            anchor_hash=anchor_hash,
            actor=args.actor,
            now_utc=now_utc,
        )

        args.marker_out.parent.mkdir(parents=True, exist_ok=True)
        args.marker_out.write_text(
            json.dumps(marker, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        print(
            f"emit_manifest_hash_ots_marker: mode={marker['mode']} "
            f"welle=1 audit_trail_anchor={anchor_hash} "
            f"bundle_keys={marker['bundle_keys']} -> {args.marker_out}"
        )
        return 0

    if args.mode == MODE_WELLE_2_AUDIT_ANCHOR:
        if args.welle_2_rollup is None or args.welle_2_sign_off is None:
            print(
                "emit_manifest_hash_ots_marker: "
                "--welle-2-rollup and --welle-2-sign-off are required "
                "when --mode welle-2-audit-anchor",
                file=sys.stderr,
            )
            return 2
        if args.marker_out is None:
            print(
                "emit_manifest_hash_ots_marker: "
                "--marker-out is required when --mode welle-2-audit-anchor",
                file=sys.stderr,
            )
            return 2

        if not args.welle_2_rollup.is_file():
            print(
                f"emit_manifest_hash_ots_marker: --welle-2-rollup not "
                f"a file: {args.welle_2_rollup}",
                file=sys.stderr,
            )
            return 1
        if not args.welle_2_sign_off.is_file():
            print(
                f"emit_manifest_hash_ots_marker: --welle-2-sign-off "
                f"not a file: {args.welle_2_sign_off}",
                file=sys.stderr,
            )
            return 1

        try:
            bundle = load_welle_2_bundle(
                rollup_path=args.welle_2_rollup,
                sign_off_path=args.welle_2_sign_off,
                validation_path=(
                    args.welle_2_validation
                    if args.welle_2_validation
                    and args.welle_2_validation.is_file()
                    else None
                ),
                pre_auditor_path=(
                    args.welle_2_pre_auditor
                    if args.welle_2_pre_auditor
                    and args.welle_2_pre_auditor.is_file()
                    else None
                ),
            )
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"emit_manifest_hash_ots_marker: welle-2 bundle "
                f"read/parse error: {exc}",
                file=sys.stderr,
            )
            return 1

        try:
            anchor_hash = compute_welle_2_audit_anchor_hash(bundle)
        except ValueError as exc:
            print(
                f"emit_manifest_hash_ots_marker: welle-2 bundle "
                f"shape error: {exc}",
                file=sys.stderr,
            )
            return 1

        marker = build_welle_2_audit_anchor_marker(
            bundle=bundle,
            anchor_hash=anchor_hash,
            actor=args.actor,
            now_utc=now_utc,
        )

        args.marker_out.parent.mkdir(parents=True, exist_ok=True)
        args.marker_out.write_text(
            json.dumps(marker, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        print(
            f"emit_manifest_hash_ots_marker: mode={marker['mode']} "
            f"welle=2 audit_trail_anchor={anchor_hash} "
            f"bundle_keys={marker['bundle_keys']} -> {args.marker_out}"
        )
        return 0

    if args.mode == MODE_WELLE_3_AUDIT_ANCHOR:
        if args.welle_3_rollup is None or args.welle_3_sign_off is None:
            print(
                "emit_manifest_hash_ots_marker: "
                "--welle-3-rollup and --welle-3-sign-off are required "
                "when --mode welle-3-audit-anchor",
                file=sys.stderr,
            )
            return 2
        if args.marker_out is None:
            print(
                "emit_manifest_hash_ots_marker: "
                "--marker-out is required when --mode welle-3-audit-anchor",
                file=sys.stderr,
            )
            return 2

        if not args.welle_3_rollup.is_file():
            print(
                f"emit_manifest_hash_ots_marker: --welle-3-rollup not "
                f"a file: {args.welle_3_rollup}",
                file=sys.stderr,
            )
            return 1
        if not args.welle_3_sign_off.is_file():
            print(
                f"emit_manifest_hash_ots_marker: --welle-3-sign-off "
                f"not a file: {args.welle_3_sign_off}",
                file=sys.stderr,
            )
            return 1

        try:
            bundle = load_welle_3_bundle(
                rollup_path=args.welle_3_rollup,
                sign_off_path=args.welle_3_sign_off,
                validation_path=(
                    args.welle_3_validation
                    if args.welle_3_validation
                    and args.welle_3_validation.is_file()
                    else None
                ),
                pre_auditor_path=(
                    args.welle_3_pre_auditor
                    if args.welle_3_pre_auditor
                    and args.welle_3_pre_auditor.is_file()
                    else None
                ),
            )
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"emit_manifest_hash_ots_marker: welle-3 bundle "
                f"read/parse error: {exc}",
                file=sys.stderr,
            )
            return 1

        try:
            anchor_hash = compute_welle_3_audit_anchor_hash(bundle)
        except ValueError as exc:
            print(
                f"emit_manifest_hash_ots_marker: welle-3 bundle "
                f"shape error: {exc}",
                file=sys.stderr,
            )
            return 1

        marker = build_welle_3_audit_anchor_marker(
            bundle=bundle,
            anchor_hash=anchor_hash,
            actor=args.actor,
            now_utc=now_utc,
        )

        args.marker_out.parent.mkdir(parents=True, exist_ok=True)
        args.marker_out.write_text(
            json.dumps(marker, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        print(
            f"emit_manifest_hash_ots_marker: mode={marker['mode']} "
            f"welle=3 audit_trail_anchor={anchor_hash} "
            f"bundle_keys={marker['bundle_keys']} "
            f"pre_auditor_signaling_ready="
            f"{marker['pre_auditor_signaling_ready']} "
            f"-> {args.marker_out}"
        )
        return 0

    if args.mode == MODE_WELLE_4_AUDIT_ANCHOR:
        if args.welle_4_rollup is None or args.welle_4_sign_off is None:
            print(
                "emit_manifest_hash_ots_marker: "
                "--welle-4-rollup and --welle-4-sign-off are required "
                "when --mode welle-4-audit-anchor",
                file=sys.stderr,
            )
            return 2
        if args.marker_out is None:
            print(
                "emit_manifest_hash_ots_marker: "
                "--marker-out is required when --mode welle-4-audit-anchor",
                file=sys.stderr,
            )
            return 2

        if not args.welle_4_rollup.is_file():
            print(
                f"emit_manifest_hash_ots_marker: --welle-4-rollup not "
                f"a file: {args.welle_4_rollup}",
                file=sys.stderr,
            )
            return 1
        if not args.welle_4_sign_off.is_file():
            print(
                f"emit_manifest_hash_ots_marker: --welle-4-sign-off "
                f"not a file: {args.welle_4_sign_off}",
                file=sys.stderr,
            )
            return 1

        try:
            bundle = load_welle_4_bundle(
                rollup_path=args.welle_4_rollup,
                sign_off_path=args.welle_4_sign_off,
                validation_path=(
                    args.welle_4_validation
                    if args.welle_4_validation
                    and args.welle_4_validation.is_file()
                    else None
                ),
                pre_auditor_path=(
                    args.welle_4_pre_auditor
                    if args.welle_4_pre_auditor
                    and args.welle_4_pre_auditor.is_file()
                    else None
                ),
            )
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"emit_manifest_hash_ots_marker: welle-4 bundle "
                f"read/parse error: {exc}",
                file=sys.stderr,
            )
            return 1

        try:
            anchor_hash = compute_welle_4_audit_anchor_hash(bundle)
        except ValueError as exc:
            print(
                f"emit_manifest_hash_ots_marker: welle-4 bundle "
                f"shape error: {exc}",
                file=sys.stderr,
            )
            return 1

        marker = build_welle_4_audit_anchor_marker(
            bundle=bundle,
            anchor_hash=anchor_hash,
            actor=args.actor,
            now_utc=now_utc,
        )

        args.marker_out.parent.mkdir(parents=True, exist_ok=True)
        args.marker_out.write_text(
            json.dumps(marker, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        tracking = marker["snapshot_restore_pflicht_tracking"]
        print(
            f"emit_manifest_hash_ots_marker: mode={marker['mode']} "
            f"welle=4 audit_trail_anchor={anchor_hash} "
            f"bundle_keys={marker['bundle_keys']} "
            f"snapshot_restore_pflicht_active="
            f"{tracking['snapshot_restore_pflicht_active']} "
            f"snapshot_restore_status={tracking['snapshot_restore_status']} "
            f"-> {args.marker_out}"
        )
        return 0

    if args.mode == MODE_WELLE_5_AUDIT_ANCHOR:
        if args.welle_5_rollup is None or args.welle_5_sign_off is None:
            print(
                "emit_manifest_hash_ots_marker: "
                "--welle-5-rollup and --welle-5-sign-off are required "
                "when --mode welle-5-audit-anchor",
                file=sys.stderr,
            )
            return 2
        if args.marker_out is None:
            print(
                "emit_manifest_hash_ots_marker: "
                "--marker-out is required when --mode welle-5-audit-anchor",
                file=sys.stderr,
            )
            return 2

        if not args.welle_5_rollup.is_file():
            print(
                f"emit_manifest_hash_ots_marker: --welle-5-rollup not "
                f"a file: {args.welle_5_rollup}",
                file=sys.stderr,
            )
            return 1
        if not args.welle_5_sign_off.is_file():
            print(
                f"emit_manifest_hash_ots_marker: --welle-5-sign-off "
                f"not a file: {args.welle_5_sign_off}",
                file=sys.stderr,
            )
            return 1

        try:
            bundle = load_welle_5_bundle(
                rollup_path=args.welle_5_rollup,
                sign_off_path=args.welle_5_sign_off,
                validation_path=(
                    args.welle_5_validation
                    if args.welle_5_validation
                    and args.welle_5_validation.is_file()
                    else None
                ),
                pre_auditor_path=(
                    args.welle_5_pre_auditor
                    if args.welle_5_pre_auditor
                    and args.welle_5_pre_auditor.is_file()
                    else None
                ),
            )
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"emit_manifest_hash_ots_marker: welle-5 bundle "
                f"read/parse error: {exc}",
                file=sys.stderr,
            )
            return 1

        try:
            anchor_hash = compute_welle_5_audit_anchor_hash(bundle)
        except ValueError as exc:
            print(
                f"emit_manifest_hash_ots_marker: welle-5 bundle "
                f"shape error: {exc}",
                file=sys.stderr,
            )
            return 1

        marker = build_welle_5_audit_anchor_marker(
            bundle=bundle,
            anchor_hash=anchor_hash,
            actor=args.actor,
            now_utc=now_utc,
        )

        args.marker_out.parent.mkdir(parents=True, exist_ok=True)
        args.marker_out.write_text(
            json.dumps(marker, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        tracking = marker["capability_token_rotation_tracking"]
        print(
            f"emit_manifest_hash_ots_marker: mode={marker['mode']} "
            f"welle=5 audit_trail_anchor={anchor_hash} "
            f"bundle_keys={marker['bundle_keys']} "
            f"capability_token_rotation_active="
            f"{tracking['capability_token_rotation_active']} "
            f"capability_token_rotation_status="
            f"{tracking['capability_token_rotation_status']} "
            f"capability_token_replay_window_closed="
            f"{tracking['capability_token_replay_window_closed']} "
            f"-> {args.marker_out}"
        )
        return 0

    if args.mode == MODE_WELLE_6_AUDIT_ANCHOR:
        if args.welle_6_rollup is None or args.welle_6_sign_off is None:
            print(
                "emit_manifest_hash_ots_marker: "
                "--welle-6-rollup and --welle-6-sign-off are required "
                "when --mode welle-6-audit-anchor",
                file=sys.stderr,
            )
            return 2
        if args.marker_out is None:
            print(
                "emit_manifest_hash_ots_marker: "
                "--marker-out is required when --mode welle-6-audit-anchor",
                file=sys.stderr,
            )
            return 2

        if not args.welle_6_rollup.is_file():
            print(
                f"emit_manifest_hash_ots_marker: --welle-6-rollup not "
                f"a file: {args.welle_6_rollup}",
                file=sys.stderr,
            )
            return 1
        if not args.welle_6_sign_off.is_file():
            print(
                f"emit_manifest_hash_ots_marker: --welle-6-sign-off "
                f"not a file: {args.welle_6_sign_off}",
                file=sys.stderr,
            )
            return 1

        try:
            bundle = load_welle_6_bundle(
                rollup_path=args.welle_6_rollup,
                sign_off_path=args.welle_6_sign_off,
                validation_path=(
                    args.welle_6_validation
                    if args.welle_6_validation
                    and args.welle_6_validation.is_file()
                    else None
                ),
                pre_auditor_path=(
                    args.welle_6_pre_auditor
                    if args.welle_6_pre_auditor
                    and args.welle_6_pre_auditor.is_file()
                    else None
                ),
            )
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"emit_manifest_hash_ots_marker: welle-6 bundle "
                f"read/parse error: {exc}",
                file=sys.stderr,
            )
            return 1

        try:
            anchor_hash = compute_welle_6_audit_anchor_hash(bundle)
        except ValueError as exc:
            print(
                f"emit_manifest_hash_ots_marker: welle-6 bundle "
                f"shape error: {exc}",
                file=sys.stderr,
            )
            return 1

        marker = build_welle_6_audit_anchor_marker(
            bundle=bundle,
            anchor_hash=anchor_hash,
            actor=args.actor,
            now_utc=now_utc,
        )

        args.marker_out.parent.mkdir(parents=True, exist_ok=True)
        args.marker_out.write_text(
            json.dumps(marker, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        tracking = marker["subscribe_loop_self_repair_hygiene_tracking"]
        print(
            f"emit_manifest_hash_ots_marker: mode={marker['mode']} "
            f"welle=6 audit_trail_anchor={anchor_hash} "
            f"bundle_keys={marker['bundle_keys']} "
            f"subscribe_loop_self_repair_hygiene_active="
            f"{tracking['subscribe_loop_self_repair_hygiene_active']} "
            f"subscribe_loop_self_repair_hygiene_status="
            f"{tracking['subscribe_loop_self_repair_hygiene_status']} "
            f"subscribe_loop_re_subscribe_window_closed="
            f"{tracking['subscribe_loop_re_subscribe_window_closed']} "
            f"-> {args.marker_out}"
        )
        return 0

    if args.mode == MODE_WELLE_7_AUDIT_ANCHOR:
        if args.welle_7_rollup is None or args.welle_7_sign_off is None:
            print(
                "emit_manifest_hash_ots_marker: "
                "--welle-7-rollup and --welle-7-sign-off are required "
                "when --mode welle-7-audit-anchor",
                file=sys.stderr,
            )
            return 2
        if args.marker_out is None:
            print(
                "emit_manifest_hash_ots_marker: "
                "--marker-out is required when --mode welle-7-audit-anchor",
                file=sys.stderr,
            )
            return 2

        if not args.welle_7_rollup.is_file():
            print(
                f"emit_manifest_hash_ots_marker: --welle-7-rollup not "
                f"a file: {args.welle_7_rollup}",
                file=sys.stderr,
            )
            return 1
        if not args.welle_7_sign_off.is_file():
            print(
                f"emit_manifest_hash_ots_marker: --welle-7-sign-off "
                f"not a file: {args.welle_7_sign_off}",
                file=sys.stderr,
            )
            return 1

        try:
            bundle = load_welle_7_bundle(
                rollup_path=args.welle_7_rollup,
                sign_off_path=args.welle_7_sign_off,
                validation_path=(
                    args.welle_7_validation
                    if args.welle_7_validation
                    and args.welle_7_validation.is_file()
                    else None
                ),
                pre_auditor_path=(
                    args.welle_7_pre_auditor
                    if args.welle_7_pre_auditor
                    and args.welle_7_pre_auditor.is_file()
                    else None
                ),
            )
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"emit_manifest_hash_ots_marker: welle-7 bundle "
                f"read/parse error: {exc}",
                file=sys.stderr,
            )
            return 1

        try:
            anchor_hash = compute_welle_7_audit_anchor_hash(bundle)
        except ValueError as exc:
            print(
                f"emit_manifest_hash_ots_marker: welle-7 bundle "
                f"shape error: {exc}",
                file=sys.stderr,
            )
            return 1

        marker = build_welle_7_audit_anchor_marker(
            bundle=bundle,
            anchor_hash=anchor_hash,
            actor=args.actor,
            now_utc=now_utc,
        )

        args.marker_out.parent.mkdir(parents=True, exist_ok=True)
        args.marker_out.write_text(
            json.dumps(marker, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        tracking = marker["phase_3_final_sealing_tracking"]
        print(
            f"emit_manifest_hash_ots_marker: mode={marker['mode']} "
            f"welle=7 audit_trail_anchor={anchor_hash} "
            f"bundle_keys={marker['bundle_keys']} "
            f"phase_3_final_sealing_active="
            f"{tracking['phase_3_final_sealing_active']} "
            f"phase_3_final_sealing_status="
            f"{tracking['phase_3_final_sealing_status']} "
            f"global_acceptance_verdict_recorded="
            f"{tracking['global_acceptance_verdict_recorded']} "
            f"phase_3_complete_marker_ready="
            f"{tracking['phase_3_complete_marker_ready']} "
            f"pre_auditor_final_sealing_signaling_ready="
            f"{marker['pre_auditor_final_sealing_signaling_ready']} "
            f"-> {args.marker_out}"
        )
        return 0

    if args.mode == MODE_PHASE_3_COMPLETE_MARKER:
        welle_marker_args = [
            args.welle_1_marker,
            args.welle_2_marker,
            args.welle_3_marker,
            args.welle_4_marker,
            args.welle_5_marker,
            args.welle_6_marker,
            args.welle_7_marker,
        ]
        if any(p is None for p in welle_marker_args):
            print(
                "emit_manifest_hash_ots_marker: "
                "--welle-1-marker .. --welle-7-marker are all "
                "required when --mode phase-3-complete-marker",
                file=sys.stderr,
            )
            return 2
        if args.marker_out is None:
            print(
                "emit_manifest_hash_ots_marker: "
                "--marker-out is required when "
                "--mode phase-3-complete-marker",
                file=sys.stderr,
            )
            return 2

        for path in welle_marker_args:
            if not path.is_file():
                print(
                    f"emit_manifest_hash_ots_marker: welle marker "
                    f"file missing: {path}",
                    file=sys.stderr,
                )
                return 1

        try:
            markers = load_phase_3_complete_bundle(
                welle_marker_paths=welle_marker_args,
            )
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"emit_manifest_hash_ots_marker: phase-3-complete "
                f"bundle read/parse error: {exc}",
                file=sys.stderr,
            )
            return 1
        except ValueError as exc:
            print(
                f"emit_manifest_hash_ots_marker: phase-3-complete "
                f"bundle shape error: {exc}",
                file=sys.stderr,
            )
            return 1

        try:
            assert_welle_1_7_kind_disjointness_pin(markers)
        except ValueError as exc:
            print(
                f"emit_manifest_hash_ots_marker: phase-3-complete "
                f"disjointness-pin violation: {exc}",
                file=sys.stderr,
            )
            return 1

        bundle_anchor = compute_phase_3_complete_bundle_anchor(markers)
        marker = build_phase_3_complete_marker(
            markers=markers,
            bundle_anchor=bundle_anchor,
            actor=args.actor,
            now_utc=now_utc,
        )

        args.marker_out.parent.mkdir(parents=True, exist_ok=True)
        args.marker_out.write_text(
            json.dumps(marker, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        print(
            f"emit_manifest_hash_ots_marker: mode={marker['mode']} "
            f"phase_3_complete_bundle_anchor={bundle_anchor} "
            f"welle_bundle_count={marker['welle_bundle_count']} "
            f"global_acceptance_verdict_recorded="
            f"{marker['global_acceptance_verdict_recorded']} "
            f"phase_3_complete_marker_ready="
            f"{marker['phase_3_complete_marker_ready']} "
            f"pre_auditor_final_sealing_signaling_ready="
            f"{marker['pre_auditor_final_sealing_signaling_ready']} "
            f"welle_1_7_kind_disjointness_pin_ok="
            f"{marker['welle_1_7_kind_disjointness_pin_ok']} "
            f"-> {args.marker_out}"
        )
        return 0

    if args.mode in (MODE_AUDIT_ONLY, MODE_PRE_ACTIVATION_PROBE):
        if args.manifest is None:
            print(
                "emit_manifest_hash_ots_marker: "
                "--manifest is required when "
                f"--mode {args.mode}",
                file=sys.stderr,
            )
            return 2

    if args.mode == MODE_PRE_ACTIVATION_PROBE:
        if args.probe_verdict_out is None:
            print(
                "emit_manifest_hash_ots_marker: "
                "--probe-verdict-out is required when "
                "--mode pre-activation-probe",
                file=sys.stderr,
            )
            return 2

        verdict = run_pre_activation_probe(
            manifest_path=args.manifest,
            actor=args.actor,
            now_utc=now_utc,
            repo_root=args.repo_root,
        )

        args.probe_verdict_out.parent.mkdir(parents=True, exist_ok=True)
        args.probe_verdict_out.write_text(
            json.dumps(verdict, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        print(
            f"emit_manifest_hash_ots_marker: mode={verdict['mode']} "
            f"verdict={verdict['verdict']} "
            f"sha256={verdict['manifest_sha256'] or '-'} "
            f"size={verdict['manifest_size_bytes']} "
            f"-> {args.probe_verdict_out}"
        )

        # Exit 0 even on PROBE-DEFECT — the workflow surfaces the
        # verdict and decides enforcement. Tests cover both cases.
        return 0

    # mode == audit-only (default, Tag-57 path).
    if args.marker_out is None:
        print(
            "emit_manifest_hash_ots_marker: "
            "--marker-out is required when --mode audit-only",
            file=sys.stderr,
        )
        return 2

    if not args.manifest.is_file():
        print(
            f"emit_manifest_hash_ots_marker: --manifest not a file: "
            f"{args.manifest}",
            file=sys.stderr,
        )
        return 1

    try:
        sha256_hex, size_bytes = compute_sha256(args.manifest)
    except OSError as exc:
        print(
            f"emit_manifest_hash_ots_marker: read failed: {exc}",
            file=sys.stderr,
        )
        return 1

    marker = build_marker(
        manifest_path=args.manifest,
        manifest_sha256=sha256_hex,
        manifest_size_bytes=size_bytes,
        actor=args.actor,
        now_utc=now_utc,
        repo_root=args.repo_root,
    )

    args.marker_out.parent.mkdir(parents=True, exist_ok=True)
    args.marker_out.write_text(
        json.dumps(marker, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(
        f"emit_manifest_hash_ots_marker: mode={marker['mode']} "
        f"sha256={sha256_hex} size={size_bytes} -> {args.marker_out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
