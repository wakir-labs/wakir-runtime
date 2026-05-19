#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Tag-76 Marathon-Closeout-Aggregator (Welle-1..7 Verifier-Family Bundler).

Audit-only mode. This helper aggregates the seven per-Welle verifier
outcomes (Welle-1..7 Final-Sealing-Verifier-Family) into a single
marathon-closeout verdict and inspects the Production-Bringup-Marker
post-Welle-7-sign-off-trigger and the Phase-3-COMPLETE-Marker-Readiness
state. It does NOT execute any per-Welle verifier, does NOT consult
the audit-trail WAT-leaves, does NOT touch the schema-registry, does
NOT open any promotion-PR, does NOT cut a release tag, and does NOT
emit the Phase-3-COMPLETE-marker. It is a structural / invariant
inspector over a closeout-document of shape::

    {
      "tag":              "Tag-76",
      "marathon_id":      "phase-3c-welle-marathon",
      "audit_only":       true,
      "doc_form_only":    true,
      "closeout_id":      "<opaque closeout identifier>",
      "welle_verifier_outcomes": [<welle-outcome>, ...],
      "production_bringup_marker": {
        "trigger_kind":              "post-welle-7-signoff",
        "trigger_date":              "2026-07-03",
        "production_substrate":      "<substrate-id>",
        "bringup_status":            "<one of: ready | pending | blocked>",
        "operator_handoff_required": <bool>
      },
      "phase_3_complete_marker_readiness": {
        "all_welle_signed_off":      <bool>,
        "global_verdict":            "<one of: GREEN | CAUTION | RED>",
        "live_verify_gate_status":   "<one of: GREEN | CAUTION | RED>",
        "marker_emit_ready":         <bool>,
        "emit_blocked_reason":       "<string or null>"
      },
      "sandbox_boundary": {
        "no_engine_invocation":      true,
        "no_schema_registry_write":  true,
        "no_audit_trail_write":      true,
        "no_per_welle_verifier_exec":true,
        "no_marker_emission":        true,
        "no_promotion_pr_opening":   true,
        "no_release_tag_cut":        true,
        "probe_default_mode":        "inspection-only"
      },
      "cross_anchors": {
        "adr_0007":                  "...",
        "adr_0017":                  "...",
        "adr_0023a":                 "...",
        "adr_0023b":                 "...",
        "adr_0025":                  "...",
        "adr_0066":                  "...",
        "pre_cutover_acceptance_run_order_doc": "...",
        "tag_75_welle_7_final_sealing_verifier": "...",
        "tag_74_welle_6_parity_verifier":        "...",
        "tag_73_welle_5_capability_verifier":    "..."
      }
    }

A welle-outcome (one for each Welle-1..7) has::

    {
      "welle_id":         "<one of: Welle-1 .. Welle-7>",
      "verifier_pin":     "<opaque verifier-identity pin>",
      "verifier_kind":    "<one of: v907-verify | state-conventions |
                                    recipe-patch-doc | state-backing |
                                    capability-token | parity |
                                    final-sealing>",
      "verdict":          "<one of: GREEN | CAUTION | RED>",
      "signoff_date":     "<ISO-8601 date string>",
      "test_count":       <integer >=1>
    }

Invariants checked (Marathon-Closeout):

  I-1   ``tag`` is exactly ``Tag-76``.
  I-2   ``marathon_id`` is exactly ``phase-3c-welle-marathon``.
  I-3   ``audit_only`` and ``doc_form_only`` are both type bool and
        both true. Helper refuses to validate a non-audit-only
        document.
  I-4   ``closeout_id`` is a non-empty string matching
        ``^closeout-[a-z0-9-]{4,64}$``.
  I-5   ``welle_verifier_outcomes`` is a list of exactly seven welle-
        outcome records, one for each of Welle-1 .. Welle-7.
        Duplicates rejected, missing wellen rejected, unknown
        welle-ids rejected.
  I-6   Each welle-outcome carries the six required fields and no
        extras. ``verifier_pin`` non-empty string; ``test_count`` int
        >=1; ``verdict`` in {GREEN, CAUTION, RED}.
  I-7   Each ``verifier_kind`` is from the canonical set; the kind
        MUST match the canonical-kind-per-welle expectation derived
        from the run-order doc (Welle-1=v907-verify,
        Welle-2=state-conventions, Welle-3=recipe-patch-doc,
        Welle-4=state-backing, Welle-5=capability-token,
        Welle-6=parity, Welle-7=final-sealing).
  I-8   ``signoff_date`` is an ISO-8601 date string matching
        ``^\\d{4}-\\d{2}-\\d{2}$``. For Welle-6 and Welle-7 the date
        MUST be ``2026-07-03`` (canonical sign-off-Freitag per the
        run-order doc); for Welle-1/2 ``2026-06-12``, Welle-3
        ``2026-06-19``, Welle-4/5 ``2026-06-26``.
  I-9   ``production_bringup_marker`` carries the five required
        fields and no extras. ``trigger_kind`` is exactly
        ``post-welle-7-signoff``. ``trigger_date`` matches
        ``^\\d{4}-\\d{2}-\\d{2}$`` and equals ``2026-07-03`` (the
        Welle-7 sign-off-Freitag). ``production_substrate`` is a
        non-empty string.
  I-10  ``bringup_status`` is one of {ready, pending, blocked}.
        ``operator_handoff_required`` is type bool.
  I-11  ``phase_3_complete_marker_readiness`` carries the five
        required fields and no extras. ``all_welle_signed_off`` and
        ``marker_emit_ready`` are type bool. ``global_verdict`` and
        ``live_verify_gate_status`` are in {GREEN, CAUTION, RED}.
        ``emit_blocked_reason`` is null when ``marker_emit_ready`` is
        true, and a non-empty string when ``marker_emit_ready`` is
        false (justification-required principle).
  I-12  Marker-emit-readiness consistency: if every welle-outcome's
        verdict is GREEN AND ``global_verdict`` is GREEN AND
        ``live_verify_gate_status`` is GREEN AND
        ``all_welle_signed_off`` is true, then ``marker_emit_ready``
        MUST be true. Conversely, if any of these is non-GREEN/false,
        ``marker_emit_ready`` MUST be false.
  I-13  ``sandbox_boundary`` declares ALL seven boolean defaults true
        (no_engine_invocation, no_schema_registry_write,
        no_audit_trail_write, no_per_welle_verifier_exec,
        no_marker_emission, no_promotion_pr_opening,
        no_release_tag_cut) and ``probe_default_mode`` is
        ``inspection-only``.
  I-14  ``cross_anchors`` references the ten baseline anchors
        including the three latest verifier-anchors
        (tag-73/74/75) and the run-order doc.
  I-15  No top-level unknown fields (strict shape).
  I-16  ``audit_only`` is type bool exactly; ints/strings rejected.
  I-17  Helper itself does not write any file, does not open any
        network socket, does not call the engine, does not invoke
        any per-welle verifier, does not emit any marker, and does
        not cut a release tag.

The helper exits 0 on green (all invariants pass) and emits a
verdict envelope to stdout:

    {
      "schema_version": "1.0.0",
      "doc_version": "tag-76",
      "marathon_id": "phase-3c-welle-marathon",
      "verdict": "MARATHON-CLOSEOUT-READY" | "PARTIAL" | "DEFECT",
      "welle_count": 7,
      "all_green": <bool>,
      "marker_emit_ready": <bool>,
      "blocking_wellen": [<welle_id>, ...]
    }

Verdict-mapping rules:

  MARATHON-CLOSEOUT-READY :  all seven welle-outcomes GREEN AND
                             phase_3_complete_marker_readiness.
                             marker_emit_ready is true AND
                             production_bringup_marker.bringup_status
                             is 'ready'.
  PARTIAL                 :  at least one CAUTION-but-no-RED across
                             welle-outcomes / global_verdict /
                             live_verify_gate_status AND no RED.
                             bringup_status MAY be 'pending'.
  DEFECT                  :  any RED in welle-outcomes,
                             global_verdict, live_verify_gate_status,
                             OR bringup_status == 'blocked', OR
                             marker_emit_ready is false while
                             all_welle_signed_off is true (logical
                             inconsistency).

The helper exits 1 on any invariant failure with a clear stderr
message naming the first failing invariant. The verdict envelope is
emitted on stdout regardless of MARATHON-CLOSEOUT-READY / PARTIAL /
DEFECT, but only when invariants pass.

Standard library only. CLI usage::

    python tooling/audit/verify_marathon_closeout.py \\
        <path-to-closeout-document.json>

Programmatic usage::

    from verify_marathon_closeout import verify_closeout, compute_verdict
    verify_closeout(doc)              # raises VerifyError on failure
    envelope = compute_verdict(doc)   # returns verdict envelope dict

Sandbox-boundary recital:

  - No engine invocation by this helper.
  - No schema-registry write by this helper.
  - No audit-trail (WAT-leaf) write by this helper.
  - No per-welle verifier execution by this helper.
  - No Phase-3-COMPLETE-marker emission by this helper.
  - No promotion-PR opening by this helper.
  - No release-tag cut by this helper.
  - probe_default_mode is inspection-only.

-- Reza
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any, Iterable

# REUSE-IgnoreStart -- in-file constant block, no third-party text
CANONICAL_WELLE_IDS = (
    "Welle-1",
    "Welle-2",
    "Welle-3",
    "Welle-4",
    "Welle-5",
    "Welle-6",
    "Welle-7",
)
CANONICAL_VERIFIER_KINDS = (
    "v907-verify",
    "state-conventions",
    "recipe-patch-doc",
    "state-backing",
    "capability-token",
    "parity",
    "final-sealing",
)
CANONICAL_VERIFIER_KIND_PER_WELLE = {
    "Welle-1": "v907-verify",
    "Welle-2": "state-conventions",
    "Welle-3": "recipe-patch-doc",
    "Welle-4": "state-backing",
    "Welle-5": "capability-token",
    "Welle-6": "parity",
    "Welle-7": "final-sealing",
}
CANONICAL_SIGNOFF_DATE_PER_WELLE = {
    "Welle-1": "2026-06-12",
    "Welle-2": "2026-06-12",
    "Welle-3": "2026-06-19",
    "Welle-4": "2026-06-26",
    "Welle-5": "2026-06-26",
    "Welle-6": "2026-07-03",
    "Welle-7": "2026-07-03",
}
CANONICAL_VERDICTS = ("GREEN", "CAUTION", "RED")
CANONICAL_BRINGUP_STATUSES = ("ready", "pending", "blocked")
CANONICAL_BOUNDARY_BOOL_KEYS = (
    "no_engine_invocation",
    "no_schema_registry_write",
    "no_audit_trail_write",
    "no_per_welle_verifier_exec",
    "no_marker_emission",
    "no_promotion_pr_opening",
    "no_release_tag_cut",
)
REQUIRED_CROSS_ANCHORS = (
    "adr_0007",
    "adr_0017",
    "adr_0023a",
    "adr_0023b",
    "adr_0025",
    "adr_0066",
    "pre_cutover_acceptance_run_order_doc",
    "tag_75_welle_7_final_sealing_verifier",
    "tag_74_welle_6_parity_verifier",
    "tag_73_welle_5_capability_verifier",
)
CLOSEOUT_ID_RE = re.compile(r"^closeout-[a-z0-9-]{4,64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
WELLE_OUTCOME_ALLOWED_KEYS = frozenset(
    {
        "welle_id",
        "verifier_pin",
        "verifier_kind",
        "verdict",
        "signoff_date",
        "test_count",
    }
)
PRODUCTION_BRINGUP_ALLOWED_KEYS = frozenset(
    {
        "trigger_kind",
        "trigger_date",
        "production_substrate",
        "bringup_status",
        "operator_handoff_required",
    }
)
PHASE_3_READINESS_ALLOWED_KEYS = frozenset(
    {
        "all_welle_signed_off",
        "global_verdict",
        "live_verify_gate_status",
        "marker_emit_ready",
        "emit_blocked_reason",
    }
)
TOP_LEVEL_REQUIRED_KEYS = frozenset(
    {
        "tag",
        "marathon_id",
        "audit_only",
        "doc_form_only",
        "closeout_id",
        "welle_verifier_outcomes",
        "production_bringup_marker",
        "phase_3_complete_marker_readiness",
        "sandbox_boundary",
        "cross_anchors",
    }
)
EXPECTED_WELLE_7_SIGNOFF_DATE = "2026-07-03"
# REUSE-IgnoreEnd


class VerifyError(Exception):
    """Raised when a Tag-76 Marathon-Closeout invariant fails."""


def _require(condition: bool, invariant_id: str, message: str) -> None:
    if not condition:
        raise VerifyError(f"{invariant_id}: {message}")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _check_top_level_shape(doc: Any) -> None:
    _require(
        isinstance(doc, dict),
        "I-0",
        f"closeout document must be an object, got {type(doc).__name__}",
    )
    missing = TOP_LEVEL_REQUIRED_KEYS - set(doc.keys())
    _require(
        not missing,
        "I-0",
        f"closeout document missing required top-level keys: "
        f"{sorted(missing)!r}",
    )
    extra = set(doc.keys()) - TOP_LEVEL_REQUIRED_KEYS
    _require(
        not extra,
        "I-15",
        f"closeout document carries unknown top-level fields: "
        f"{sorted(extra)!r}",
    )


def _check_tag(doc: dict) -> None:
    _require(
        doc.get("tag") == "Tag-76",
        "I-1",
        f"tag must be 'Tag-76', got {doc.get('tag')!r}",
    )


def _check_marathon_id(doc: dict) -> None:
    _require(
        doc.get("marathon_id") == "phase-3c-welle-marathon",
        "I-2",
        f"marathon_id must be 'phase-3c-welle-marathon', got "
        f"{doc.get('marathon_id')!r}",
    )


def _check_audit_only(doc: dict) -> None:
    _require(
        _is_bool(doc.get("audit_only")),
        "I-16",
        f"audit_only must be type bool, got "
        f"{type(doc.get('audit_only')).__name__}",
    )
    _require(
        _is_bool(doc.get("doc_form_only")),
        "I-16",
        f"doc_form_only must be type bool, got "
        f"{type(doc.get('doc_form_only')).__name__}",
    )
    _require(
        doc.get("audit_only") is True,
        "I-3",
        "closeout document must declare 'audit_only: true' "
        "(Tag-76 helper refuses non-audit-only documents)",
    )
    _require(
        doc.get("doc_form_only") is True,
        "I-3",
        "closeout document must declare 'doc_form_only: true'",
    )


def _check_closeout_id(doc: dict) -> None:
    cid = doc.get("closeout_id")
    _require(
        isinstance(cid, str) and CLOSEOUT_ID_RE.match(cid) is not None,
        "I-4",
        f"closeout_id must match {CLOSEOUT_ID_RE.pattern!r}, got {cid!r}",
    )


def _check_welle_outcome(rec: Any, idx: int) -> None:
    _require(
        isinstance(rec, dict),
        "I-6",
        f"welle_verifier_outcomes[{idx}] must be an object, got "
        f"{type(rec).__name__}",
    )
    missing = WELLE_OUTCOME_ALLOWED_KEYS - set(rec.keys())
    _require(
        not missing,
        "I-6",
        f"welle_verifier_outcomes[{idx}] missing fields: "
        f"{sorted(missing)!r}",
    )
    extra = set(rec.keys()) - WELLE_OUTCOME_ALLOWED_KEYS
    _require(
        not extra,
        "I-6",
        f"welle_verifier_outcomes[{idx}] carries unknown fields: "
        f"{sorted(extra)!r}",
    )
    wid = rec.get("welle_id")
    _require(
        wid in CANONICAL_WELLE_IDS,
        "I-5",
        f"welle_verifier_outcomes[{idx}].welle_id must be one of "
        f"{CANONICAL_WELLE_IDS!r}, got {wid!r}",
    )
    pin = rec.get("verifier_pin")
    _require(
        isinstance(pin, str) and pin,
        "I-6",
        f"welle_verifier_outcomes[{idx}].verifier_pin must be a "
        f"non-empty string, got {pin!r}",
    )
    vkind = rec.get("verifier_kind")
    _require(
        vkind in CANONICAL_VERIFIER_KINDS,
        "I-7",
        f"welle_verifier_outcomes[{idx}].verifier_kind must be one of "
        f"{CANONICAL_VERIFIER_KINDS!r}, got {vkind!r}",
    )
    expected_kind = CANONICAL_VERIFIER_KIND_PER_WELLE.get(wid)
    _require(
        vkind == expected_kind,
        "I-7",
        f"welle_verifier_outcomes[{idx}] welle_id={wid!r} expects "
        f"verifier_kind={expected_kind!r}, got {vkind!r}",
    )
    verdict = rec.get("verdict")
    _require(
        verdict in CANONICAL_VERDICTS,
        "I-6",
        f"welle_verifier_outcomes[{idx}].verdict must be one of "
        f"{CANONICAL_VERDICTS!r}, got {verdict!r}",
    )
    sdate = rec.get("signoff_date")
    _require(
        isinstance(sdate, str) and DATE_RE.match(sdate) is not None,
        "I-8",
        f"welle_verifier_outcomes[{idx}].signoff_date must match "
        f"{DATE_RE.pattern!r}, got {sdate!r}",
    )
    expected_date = CANONICAL_SIGNOFF_DATE_PER_WELLE.get(wid)
    _require(
        sdate == expected_date,
        "I-8",
        f"welle_verifier_outcomes[{idx}] welle_id={wid!r} expects "
        f"signoff_date={expected_date!r} (canonical sign-off-Freitag "
        f"per run-order doc), got {sdate!r}",
    )
    tc = rec.get("test_count")
    _require(
        _is_int(tc) and tc >= 1,
        "I-6",
        f"welle_verifier_outcomes[{idx}].test_count must be int >=1, "
        f"got {tc!r}",
    )


def _check_welle_verifier_outcomes(doc: dict) -> None:
    outcomes = doc.get("welle_verifier_outcomes")
    _require(
        isinstance(outcomes, list),
        "I-5",
        f"welle_verifier_outcomes must be a list, got "
        f"{type(outcomes).__name__}",
    )
    _require(
        len(outcomes) == 7,
        "I-5",
        f"welle_verifier_outcomes must contain exactly 7 records "
        f"(one per Welle-1..7), got {len(outcomes)}",
    )
    for idx, rec in enumerate(outcomes):
        _check_welle_outcome(rec, idx)
    ids = [rec.get("welle_id") for rec in outcomes]
    _require(
        len(set(ids)) == 7,
        "I-5",
        f"welle_ids must be unique across welle_verifier_outcomes, "
        f"got {ids!r}",
    )
    missing_canonical = set(CANONICAL_WELLE_IDS) - set(ids)
    _require(
        not missing_canonical,
        "I-5",
        f"welle_verifier_outcomes is missing canonical welle-ids: "
        f"{sorted(missing_canonical)!r}",
    )


def _check_production_bringup_marker(doc: dict) -> None:
    pbm = doc.get("production_bringup_marker")
    _require(
        isinstance(pbm, dict),
        "I-9",
        f"production_bringup_marker must be an object, got "
        f"{type(pbm).__name__}",
    )
    missing = PRODUCTION_BRINGUP_ALLOWED_KEYS - set(pbm.keys())
    _require(
        not missing,
        "I-9",
        f"production_bringup_marker missing fields: {sorted(missing)!r}",
    )
    extra = set(pbm.keys()) - PRODUCTION_BRINGUP_ALLOWED_KEYS
    _require(
        not extra,
        "I-9",
        f"production_bringup_marker carries unknown fields: "
        f"{sorted(extra)!r}",
    )
    tk = pbm.get("trigger_kind")
    _require(
        tk == "post-welle-7-signoff",
        "I-9",
        f"production_bringup_marker.trigger_kind must be "
        f"'post-welle-7-signoff', got {tk!r}",
    )
    td = pbm.get("trigger_date")
    _require(
        isinstance(td, str) and DATE_RE.match(td) is not None,
        "I-9",
        f"production_bringup_marker.trigger_date must match "
        f"{DATE_RE.pattern!r}, got {td!r}",
    )
    _require(
        td == EXPECTED_WELLE_7_SIGNOFF_DATE,
        "I-9",
        f"production_bringup_marker.trigger_date must equal "
        f"{EXPECTED_WELLE_7_SIGNOFF_DATE!r} (the canonical Welle-7 "
        f"sign-off-Freitag per run-order doc §3.2), got {td!r}",
    )
    ps = pbm.get("production_substrate")
    _require(
        isinstance(ps, str) and ps,
        "I-9",
        f"production_bringup_marker.production_substrate must be a "
        f"non-empty string, got {ps!r}",
    )
    bs = pbm.get("bringup_status")
    _require(
        bs in CANONICAL_BRINGUP_STATUSES,
        "I-10",
        f"production_bringup_marker.bringup_status must be one of "
        f"{CANONICAL_BRINGUP_STATUSES!r}, got {bs!r}",
    )
    ohr = pbm.get("operator_handoff_required")
    _require(
        _is_bool(ohr),
        "I-10",
        f"production_bringup_marker.operator_handoff_required must be "
        f"type bool, got {type(ohr).__name__}",
    )


def _check_phase_3_complete_marker_readiness(doc: dict) -> None:
    rd = doc.get("phase_3_complete_marker_readiness")
    _require(
        isinstance(rd, dict),
        "I-11",
        f"phase_3_complete_marker_readiness must be an object, got "
        f"{type(rd).__name__}",
    )
    missing = PHASE_3_READINESS_ALLOWED_KEYS - set(rd.keys())
    _require(
        not missing,
        "I-11",
        f"phase_3_complete_marker_readiness missing fields: "
        f"{sorted(missing)!r}",
    )
    extra = set(rd.keys()) - PHASE_3_READINESS_ALLOWED_KEYS
    _require(
        not extra,
        "I-11",
        f"phase_3_complete_marker_readiness carries unknown fields: "
        f"{sorted(extra)!r}",
    )
    aws = rd.get("all_welle_signed_off")
    _require(
        _is_bool(aws),
        "I-11",
        f"phase_3_complete_marker_readiness.all_welle_signed_off must "
        f"be type bool, got {type(aws).__name__}",
    )
    gv = rd.get("global_verdict")
    _require(
        gv in CANONICAL_VERDICTS,
        "I-11",
        f"phase_3_complete_marker_readiness.global_verdict must be one "
        f"of {CANONICAL_VERDICTS!r}, got {gv!r}",
    )
    lvgs = rd.get("live_verify_gate_status")
    _require(
        lvgs in CANONICAL_VERDICTS,
        "I-11",
        f"phase_3_complete_marker_readiness.live_verify_gate_status "
        f"must be one of {CANONICAL_VERDICTS!r}, got {lvgs!r}",
    )
    mer = rd.get("marker_emit_ready")
    _require(
        _is_bool(mer),
        "I-11",
        f"phase_3_complete_marker_readiness.marker_emit_ready must be "
        f"type bool, got {type(mer).__name__}",
    )
    ebr = rd.get("emit_blocked_reason")
    if mer:
        _require(
            ebr is None,
            "I-11",
            f"phase_3_complete_marker_readiness.emit_blocked_reason "
            f"must be null when marker_emit_ready=true, got {ebr!r}",
        )
    else:
        _require(
            isinstance(ebr, str) and ebr,
            "I-11",
            f"phase_3_complete_marker_readiness.emit_blocked_reason "
            f"must be a non-empty string when marker_emit_ready=false, "
            f"got {ebr!r}",
        )


def _check_marker_emit_consistency(doc: dict) -> None:
    rd = doc.get("phase_3_complete_marker_readiness") or {}
    outcomes = doc.get("welle_verifier_outcomes") or []
    all_green_welle = all(
        rec.get("verdict") == "GREEN" for rec in outcomes
    )
    gv_green = rd.get("global_verdict") == "GREEN"
    lvgs_green = rd.get("live_verify_gate_status") == "GREEN"
    all_signed = rd.get("all_welle_signed_off") is True
    expected_emit_ready = (
        all_green_welle and gv_green and lvgs_green and all_signed
    )
    actual_emit_ready = rd.get("marker_emit_ready") is True
    _require(
        actual_emit_ready == expected_emit_ready,
        "I-12",
        f"marker_emit_ready={actual_emit_ready} is inconsistent with "
        f"derived readiness={expected_emit_ready} "
        f"(all_green_welle={all_green_welle}, "
        f"global_verdict_green={gv_green}, "
        f"live_verify_gate_green={lvgs_green}, "
        f"all_welle_signed_off={all_signed})",
    )


def _check_sandbox_boundary(doc: dict) -> None:
    sb = doc.get("sandbox_boundary")
    _require(
        isinstance(sb, dict),
        "I-13",
        f"sandbox_boundary must be an object, got {type(sb).__name__}",
    )
    for key in CANONICAL_BOUNDARY_BOOL_KEYS:
        _require(
            sb.get(key) is True,
            "I-13",
            f"sandbox_boundary.{key} must be true (got {sb.get(key)!r})",
        )
    _require(
        sb.get("probe_default_mode") == "inspection-only",
        "I-13",
        f"sandbox_boundary.probe_default_mode must be "
        f"'inspection-only', got {sb.get('probe_default_mode')!r}",
    )


def _check_cross_anchors(doc: dict) -> None:
    anchors = doc.get("cross_anchors")
    _require(
        isinstance(anchors, dict),
        "I-14",
        f"cross_anchors must be an object, got {type(anchors).__name__}",
    )
    missing = [a for a in REQUIRED_CROSS_ANCHORS if a not in anchors]
    _require(
        not missing,
        "I-14",
        f"cross_anchors missing required anchors: {missing!r}",
    )
    for key in REQUIRED_CROSS_ANCHORS:
        val = anchors.get(key)
        _require(
            isinstance(val, str) and val,
            "I-14",
            f"cross_anchors.{key} must be a non-empty string, got "
            f"{val!r}",
        )


def verify_closeout(doc: Any) -> None:
    """Validate a Tag-76 Marathon-Closeout document.

    Raises ``VerifyError`` with an invariant-tagged message on the
    first failing invariant. Returns ``None`` on success.
    """
    _check_top_level_shape(doc)
    _check_tag(doc)
    _check_marathon_id(doc)
    _check_audit_only(doc)
    _check_closeout_id(doc)
    _check_welle_verifier_outcomes(doc)
    _check_production_bringup_marker(doc)
    _check_phase_3_complete_marker_readiness(doc)
    _check_marker_emit_consistency(doc)
    _check_sandbox_boundary(doc)
    _check_cross_anchors(doc)


def compute_verdict(doc: dict) -> dict:
    """Compute the marathon-closeout verdict envelope.

    Assumes the document has already passed ``verify_closeout``.
    Returns the verdict envelope dict (schema_version, doc_version,
    marathon_id, verdict, welle_count, all_green, marker_emit_ready,
    blocking_wellen).
    """
    outcomes = doc.get("welle_verifier_outcomes") or []
    rd = doc.get("phase_3_complete_marker_readiness") or {}
    pbm = doc.get("production_bringup_marker") or {}

    red_wellen = [
        rec.get("welle_id") for rec in outcomes
        if rec.get("verdict") == "RED"
    ]
    caution_wellen = [
        rec.get("welle_id") for rec in outcomes
        if rec.get("verdict") == "CAUTION"
    ]
    all_green_welle = (not red_wellen) and (not caution_wellen)
    gv = rd.get("global_verdict")
    lvgs = rd.get("live_verify_gate_status")
    mer = rd.get("marker_emit_ready") is True
    bs = pbm.get("bringup_status")
    all_signed = rd.get("all_welle_signed_off") is True

    any_red = (
        bool(red_wellen)
        or gv == "RED"
        or lvgs == "RED"
        or bs == "blocked"
    )
    # logical inconsistency case: all-signed-off but emit not ready
    # is DEFECT (run-order doc §6.3 cascade)
    logical_defect = all_signed and all_green_welle and (
        gv == "GREEN" and lvgs == "GREEN"
    ) and not mer

    if any_red or logical_defect:
        verdict = "DEFECT"
    elif (
        all_green_welle
        and gv == "GREEN"
        and lvgs == "GREEN"
        and mer
        and bs == "ready"
    ):
        verdict = "MARATHON-CLOSEOUT-READY"
    else:
        verdict = "PARTIAL"

    blocking = sorted(set(red_wellen) | set(caution_wellen))

    return {
        "schema_version": "1.0.0",
        "doc_version": "tag-76",
        "marathon_id": doc.get("marathon_id"),
        "verdict": verdict,
        "welle_count": len(outcomes),
        "all_green": all_green_welle,
        "marker_emit_ready": mer,
        "blocking_wellen": blocking,
    }


def _fail(msg: str) -> int:
    sys.stderr.write(
        f"verify_marathon_closeout: FAIL: {msg}\n"
    )
    return 1


def main(argv: Iterable[str]) -> int:
    args = list(argv)
    if len(args) != 1:
        return _fail(
            "usage: verify_marathon_closeout.py <closeout.json>"
        )
    path = args[0]
    try:
        with open(path, encoding="utf-8") as handle:
            doc = json.load(handle)
    except FileNotFoundError:
        return _fail(f"closeout document not found: {path!r}")
    except json.JSONDecodeError as exc:
        return _fail(f"closeout document {path!r} is not valid JSON: {exc}")
    try:
        verify_closeout(doc)
    except VerifyError as exc:
        return _fail(str(exc))
    envelope = compute_verdict(doc)
    print(json.dumps(envelope, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
