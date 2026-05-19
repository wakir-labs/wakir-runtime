#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Tag-74 Cross-Substrate-Parity Spec-Conformance Verifier (Welle-6).

Audit-only mode. This helper validates a *cross-substrate-parity
spec document* against the Welle-6 (Cross-Substrate-Parity)
conformance invariants. It does NOT actually execute the engine,
does NOT load the schema-registry, does NOT touch the audit-trail
WAT-leaves, does NOT call the protocol-spec compiler, and does NOT
open any promotion-PR. It is a structural / invariant inspector
over a parity-document of shape::

    {
      "tag": "Tag-74",
      "welle": "Welle-6",
      "audit_only": true,
      "doc_form_only": true,
      "parity_scope": "Cross-Substrate-Parity",
      "parity_id": "<opaque-parity-identifier>",
      "substrates": [<substrate-record>, ...],
      "parity_claims": [<claim-record>, ...],
      "divergence_budget": {
        "max_divergent_claims":        <integer 0..3>,
        "max_substrate_lag_ticks":     <integer 0..16>,
        "tolerated_divergence_kinds":  [<string>, ...]
      },
      "sandbox_boundary": {
        "no_engine_invocation":        true,
        "no_schema_registry_write":    true,
        "no_audit_trail_write":        true,
        "no_spec_compiler_call":       true,
        "no_promotion_pr_opening":     true,
        "probe_default_mode":          "inspection-only"
      },
      "cross_anchors": {
        "adr_0007":                    "...",
        "adr_0017":                    "...",
        "adr_0023a":                   "...",
        "adr_0023b":                   "...",
        "adr_0025":                    "...",
        "wat_layer_4_anchor":          "...",
        "wirelang_layer_3_schema":     "...",
        "tag_73_capability_layer":     "..."
      }
    }

A substrate-record has the shape::

    {
      "substrate_id":   "<one of: engine | spec | schema-registry |
                                  audit-trail>",
      "version_pin":    "<opaque pin string>",
      "claim_coverage": [<claim_id>, ...],
      "lag_ticks":      <integer >=0>
    }

A claim-record (one assertion that MUST hold across substrates) has::

    {
      "claim_id":              "<unique id matching ^claim-[a-z0-9-]{3,48}$>",
      "claim_kind":            "<one of: invariant | shape | ordering |
                                          identity | overlap>",
      "claim_text":            "<human-readable, non-empty>",
      "expected_substrates":   [<substrate_id>, ...],
      "observed_in":           [<substrate_id>, ...],
      "parity_status":         "<one of: parity | divergent | unobserved>"
    }

Invariants checked (Welle-6 Cross-Substrate-Parity):

  I-1  ``tag`` is ``Tag-74`` and ``welle`` is ``Welle-6``.
  I-2  ``audit_only`` and ``doc_form_only`` are both true.  The
       helper refuses to validate a non-audit-only document.
  I-3  ``parity_scope`` is exactly ``Cross-Substrate-Parity``.
  I-4  ``parity_id`` is a non-empty string matching
       ``^parity-[a-z0-9-]{4,64}$``.
  I-5  ``substrates`` is a list of exactly four substrate-records,
       one for each canonical substrate-id (engine, spec,
       schema-registry, audit-trail).  Duplicates are rejected,
       missing substrates are rejected.
  I-6  Each substrate-record carries the four required fields and
       no extras.  ``version_pin`` is a non-empty string;
       ``lag_ticks`` is an int in [0, 16]; ``claim_coverage`` is a
       (possibly empty) list of strings.
  I-7  ``parity_claims`` is a non-empty list of claim-records.
       Each claim_id is unique.  At least one claim must have
       ``claim_kind == 'invariant'`` (a parity document with no
       invariant claim has no audit value).
  I-8  Each claim-record carries the six required fields and no
       extras (strict shape).  ``claim_text`` is non-empty.
       ``expected_substrates`` is non-empty and is a subset of the
       four canonical substrate-ids.  ``observed_in`` is a subset
       of ``expected_substrates`` (cannot observe a claim where it
       was not expected).
  I-9  ``parity_status`` is one of ``parity | divergent | unobserved``.
       ``parity`` requires ``set(observed_in) == set(expected_substrates)``.
       ``unobserved`` requires ``observed_in == []``.
       ``divergent`` requires ``observed_in`` to be a strict non-empty
       subset of ``expected_substrates``.
  I-10 Each claim_id referenced in any ``substrate.claim_coverage``
       MUST exist in ``parity_claims``.  Conversely each claim in
       ``parity_claims`` whose status is ``parity`` MUST be covered
       in every ``expected_substrate`` claim_coverage list.
  I-11 ``divergence_budget`` carries the three required fields.
       ``max_divergent_claims`` is int in [0, 3];
       ``max_substrate_lag_ticks`` is int in [0, 16];
       ``tolerated_divergence_kinds`` is a list (possibly empty)
       of strings drawn from the canonical claim_kind set.
  I-12 Actual divergent-claim count (parity_status == 'divergent')
       MUST NOT exceed ``divergence_budget.max_divergent_claims``.
  I-13 No substrate.lag_ticks may exceed
       ``divergence_budget.max_substrate_lag_ticks``.
  I-14 Every divergent claim's claim_kind MUST appear in
       ``divergence_budget.tolerated_divergence_kinds`` (a divergent
       claim of an intolerable kind is a hard fail).
  I-15 ``sandbox_boundary`` declares ALL five boolean defaults true
       (no_engine_invocation, no_schema_registry_write,
       no_audit_trail_write, no_spec_compiler_call,
       no_promotion_pr_opening) and
       ``probe_default_mode == 'inspection-only'``.
  I-16 ``cross_anchors`` references the seven baseline anchors plus
       ``tag_73_capability_layer`` (Welle-5 carry-forward).
  I-17 No top-level unknown fields (strict shape).
  I-18 ``audit_only`` is type bool exactly; integers / strings rejected.
  I-19 At least three of the four substrates MUST have non-empty
       ``claim_coverage`` (a parity document where only one
       substrate has coverage cannot demonstrate parity).
  I-20 Helper itself does not write any file, does not open any
       network socket, does not call the engine, does not invoke
       any spec-compiler, and does not consult any environment
       variable that would gate the inspection.

The helper exits 0 on green (all invariants pass), 1 on any
failure with a clear stderr message naming the first failing
invariant.

Standard library only.  CLI usage::

    python tooling/audit/verify_cross_substrate_parity_spec.py \\
        <path-to-parity-document.json>

Programmatic usage::

    from verify_cross_substrate_parity_spec import verify_parity
    verify_parity(doc)  # raises VerifyError on failure

Sandbox-boundary recital:

  - No engine invocation by this helper.
  - No schema-registry write by this helper.
  - No audit-trail (WAT-leaf) write by this helper.
  - No spec-compiler call by this helper.
  - No promotion-PR opening by this helper.
  - probe_default_mode is inspection-only.

-- Reza
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any, Iterable

# REUSE-IgnoreStart -- in-file constant block, no third-party text
CANONICAL_SUBSTRATE_IDS = (
    "engine",
    "spec",
    "schema-registry",
    "audit-trail",
)
CANONICAL_CLAIM_KINDS = (
    "invariant",
    "shape",
    "ordering",
    "identity",
    "overlap",
)
CANONICAL_PARITY_STATUSES = ("parity", "divergent", "unobserved")
CANONICAL_BOUNDARY_BOOL_KEYS = (
    "no_engine_invocation",
    "no_schema_registry_write",
    "no_audit_trail_write",
    "no_spec_compiler_call",
    "no_promotion_pr_opening",
)
REQUIRED_CROSS_ANCHORS = (
    "adr_0007",
    "adr_0017",
    "adr_0023a",
    "adr_0023b",
    "adr_0025",
    "wat_layer_4_anchor",
    "wirelang_layer_3_schema",
    "tag_73_capability_layer",
)
PARITY_ID_RE = re.compile(r"^parity-[a-z0-9-]{4,64}$")
CLAIM_ID_RE = re.compile(r"^claim-[a-z0-9-]{3,48}$")
SUBSTRATE_RECORD_ALLOWED_KEYS = frozenset(
    {
        "substrate_id",
        "version_pin",
        "claim_coverage",
        "lag_ticks",
    }
)
CLAIM_RECORD_ALLOWED_KEYS = frozenset(
    {
        "claim_id",
        "claim_kind",
        "claim_text",
        "expected_substrates",
        "observed_in",
        "parity_status",
    }
)
DIVERGENCE_BUDGET_ALLOWED_KEYS = frozenset(
    {
        "max_divergent_claims",
        "max_substrate_lag_ticks",
        "tolerated_divergence_kinds",
    }
)
TOP_LEVEL_REQUIRED_KEYS = frozenset(
    {
        "tag",
        "welle",
        "audit_only",
        "doc_form_only",
        "parity_scope",
        "parity_id",
        "substrates",
        "parity_claims",
        "divergence_budget",
        "sandbox_boundary",
        "cross_anchors",
    }
)
# REUSE-IgnoreEnd


class VerifyError(Exception):
    """Raised when a Welle-6 cross-substrate-parity-spec invariant fails."""


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
        f"parity document must be an object, got {type(doc).__name__}",
    )
    missing = TOP_LEVEL_REQUIRED_KEYS - set(doc.keys())
    _require(
        not missing,
        "I-0",
        f"parity document missing required top-level keys: "
        f"{sorted(missing)!r}",
    )
    extra = set(doc.keys()) - TOP_LEVEL_REQUIRED_KEYS
    _require(
        not extra,
        "I-17",
        f"parity document carries unknown top-level fields: "
        f"{sorted(extra)!r}",
    )


def _check_tag_and_welle(doc: dict) -> None:
    _require(
        doc.get("tag") == "Tag-74",
        "I-1",
        f"tag must be 'Tag-74', got {doc.get('tag')!r}",
    )
    _require(
        doc.get("welle") == "Welle-6",
        "I-1",
        f"welle must be 'Welle-6', got {doc.get('welle')!r}",
    )


def _check_audit_only(doc: dict) -> None:
    _require(
        _is_bool(doc.get("audit_only")),
        "I-18",
        f"audit_only must be a bool, got {type(doc.get('audit_only')).__name__}",
    )
    _require(
        _is_bool(doc.get("doc_form_only")),
        "I-18",
        f"doc_form_only must be a bool, got "
        f"{type(doc.get('doc_form_only')).__name__}",
    )
    _require(
        doc.get("audit_only") is True,
        "I-2",
        "parity document must declare 'audit_only: true' "
        "(Tag-74 helper refuses non-audit-only documents)",
    )
    _require(
        doc.get("doc_form_only") is True,
        "I-2",
        "parity document must declare 'doc_form_only: true'",
    )


def _check_parity_scope(doc: dict) -> None:
    _require(
        doc.get("parity_scope") == "Cross-Substrate-Parity",
        "I-3",
        f"parity_scope must be 'Cross-Substrate-Parity', got "
        f"{doc.get('parity_scope')!r}",
    )


def _check_parity_id(doc: dict) -> None:
    pid = doc.get("parity_id")
    _require(
        isinstance(pid, str) and PARITY_ID_RE.match(pid) is not None,
        "I-4",
        f"parity_id must match {PARITY_ID_RE.pattern!r}, got {pid!r}",
    )


def _check_substrate_record(rec: Any, idx: int) -> None:
    _require(
        isinstance(rec, dict),
        "I-6",
        f"substrates[{idx}] must be an object, got {type(rec).__name__}",
    )
    missing = SUBSTRATE_RECORD_ALLOWED_KEYS - set(rec.keys())
    _require(
        not missing,
        "I-6",
        f"substrates[{idx}] missing fields: {sorted(missing)!r}",
    )
    extra = set(rec.keys()) - SUBSTRATE_RECORD_ALLOWED_KEYS
    _require(
        not extra,
        "I-6",
        f"substrates[{idx}] carries unknown fields: {sorted(extra)!r}",
    )
    sid = rec.get("substrate_id")
    _require(
        sid in CANONICAL_SUBSTRATE_IDS,
        "I-5",
        f"substrates[{idx}].substrate_id must be one of "
        f"{CANONICAL_SUBSTRATE_IDS!r}, got {sid!r}",
    )
    vp = rec.get("version_pin")
    _require(
        isinstance(vp, str) and vp,
        "I-6",
        f"substrates[{idx}].version_pin must be a non-empty string, "
        f"got {vp!r}",
    )
    cc = rec.get("claim_coverage")
    _require(
        isinstance(cc, list),
        "I-6",
        f"substrates[{idx}].claim_coverage must be a list, got "
        f"{type(cc).__name__}",
    )
    for cidx, claim_ref in enumerate(cc):
        _require(
            isinstance(claim_ref, str) and claim_ref,
            "I-6",
            f"substrates[{idx}].claim_coverage[{cidx}] must be a "
            f"non-empty string, got {claim_ref!r}",
        )
    lag = rec.get("lag_ticks")
    _require(
        _is_int(lag) and 0 <= lag <= 16,
        "I-6",
        f"substrates[{idx}].lag_ticks must be int in [0,16], got {lag!r}",
    )


def _check_substrates(doc: dict) -> None:
    subs = doc.get("substrates")
    _require(
        isinstance(subs, list),
        "I-5",
        f"substrates must be a list, got {type(subs).__name__}",
    )
    _require(
        len(subs) == 4,
        "I-5",
        f"substrates must contain exactly 4 records (one per canonical "
        f"substrate-id), got {len(subs)}",
    )
    for idx, rec in enumerate(subs):
        _check_substrate_record(rec, idx)
    ids = [rec.get("substrate_id") for rec in subs]
    _require(
        len(set(ids)) == 4,
        "I-5",
        f"substrate_ids must be unique across substrates, got {ids!r}",
    )
    missing_canonical = set(CANONICAL_SUBSTRATE_IDS) - set(ids)
    _require(
        not missing_canonical,
        "I-5",
        f"substrates list is missing canonical substrate-ids: "
        f"{sorted(missing_canonical)!r}",
    )


def _check_claim_record(rec: Any, idx: int) -> None:
    _require(
        isinstance(rec, dict),
        "I-8",
        f"parity_claims[{idx}] must be an object, got {type(rec).__name__}",
    )
    missing = CLAIM_RECORD_ALLOWED_KEYS - set(rec.keys())
    _require(
        not missing,
        "I-8",
        f"parity_claims[{idx}] missing fields: {sorted(missing)!r}",
    )
    extra = set(rec.keys()) - CLAIM_RECORD_ALLOWED_KEYS
    _require(
        not extra,
        "I-8",
        f"parity_claims[{idx}] carries unknown fields: {sorted(extra)!r}",
    )
    cid = rec.get("claim_id")
    _require(
        isinstance(cid, str) and CLAIM_ID_RE.match(cid) is not None,
        "I-8",
        f"parity_claims[{idx}].claim_id must match "
        f"{CLAIM_ID_RE.pattern!r}, got {cid!r}",
    )
    kind = rec.get("claim_kind")
    _require(
        kind in CANONICAL_CLAIM_KINDS,
        "I-8",
        f"parity_claims[{idx}].claim_kind must be one of "
        f"{CANONICAL_CLAIM_KINDS!r}, got {kind!r}",
    )
    text = rec.get("claim_text")
    _require(
        isinstance(text, str) and text,
        "I-8",
        f"parity_claims[{idx}].claim_text must be a non-empty string",
    )
    exp = rec.get("expected_substrates")
    _require(
        isinstance(exp, list) and exp,
        "I-8",
        f"parity_claims[{idx}].expected_substrates must be a non-empty "
        f"list",
    )
    for eidx, sid in enumerate(exp):
        _require(
            sid in CANONICAL_SUBSTRATE_IDS,
            "I-8",
            f"parity_claims[{idx}].expected_substrates[{eidx}]={sid!r} "
            f"is not a canonical substrate-id",
        )
    obs = rec.get("observed_in")
    _require(
        isinstance(obs, list),
        "I-8",
        f"parity_claims[{idx}].observed_in must be a list",
    )
    for oidx, sid in enumerate(obs):
        _require(
            sid in CANONICAL_SUBSTRATE_IDS,
            "I-8",
            f"parity_claims[{idx}].observed_in[{oidx}]={sid!r} is not "
            f"a canonical substrate-id",
        )
    obs_set = set(obs)
    exp_set = set(exp)
    _require(
        obs_set <= exp_set,
        "I-8",
        f"parity_claims[{idx}].observed_in {sorted(obs_set)!r} must be "
        f"a subset of expected_substrates {sorted(exp_set)!r}",
    )
    status = rec.get("parity_status")
    _require(
        status in CANONICAL_PARITY_STATUSES,
        "I-9",
        f"parity_claims[{idx}].parity_status must be one of "
        f"{CANONICAL_PARITY_STATUSES!r}, got {status!r}",
    )
    if status == "parity":
        _require(
            obs_set == exp_set,
            "I-9",
            f"parity_claims[{idx}] declared status='parity' but "
            f"observed_in {sorted(obs_set)!r} != expected_substrates "
            f"{sorted(exp_set)!r}",
        )
    elif status == "unobserved":
        _require(
            obs == [],
            "I-9",
            f"parity_claims[{idx}] declared status='unobserved' but "
            f"observed_in is non-empty: {obs!r}",
        )
    elif status == "divergent":
        _require(
            obs_set and obs_set < exp_set,
            "I-9",
            f"parity_claims[{idx}] declared status='divergent' but "
            f"observed_in {sorted(obs_set)!r} is not a strict non-empty "
            f"subset of expected_substrates {sorted(exp_set)!r}",
        )


def _check_parity_claims(doc: dict) -> None:
    claims = doc.get("parity_claims")
    _require(
        isinstance(claims, list),
        "I-7",
        f"parity_claims must be a list, got {type(claims).__name__}",
    )
    _require(
        len(claims) >= 1,
        "I-7",
        "parity_claims must contain at least one claim-record",
    )
    seen_ids: set = set()
    for idx, rec in enumerate(claims):
        _check_claim_record(rec, idx)
        cid = rec.get("claim_id")
        _require(
            cid not in seen_ids,
            "I-7",
            f"parity_claims[{idx}].claim_id={cid!r} is duplicated",
        )
        seen_ids.add(cid)
    kinds = [rec.get("claim_kind") for rec in claims]
    _require(
        "invariant" in kinds,
        "I-7",
        "parity_claims must contain at least one claim with "
        "claim_kind='invariant' (parity doc without invariant claim "
        "has no audit value)",
    )


def _check_coverage_consistency(doc: dict) -> None:
    claim_ids = {rec.get("claim_id") for rec in doc.get("parity_claims") or []}
    subs = doc.get("substrates") or []
    for idx, rec in enumerate(subs):
        for cidx, claim_ref in enumerate(rec.get("claim_coverage") or []):
            _require(
                claim_ref in claim_ids,
                "I-10",
                f"substrates[{idx}].claim_coverage[{cidx}]={claim_ref!r} "
                f"references unknown claim_id (not in parity_claims)",
            )
    # Reverse direction: a claim declared 'parity' must be covered in
    # every expected substrate's claim_coverage list.
    coverage_index: dict = {
        rec.get("substrate_id"): set(rec.get("claim_coverage") or [])
        for rec in subs
    }
    for cidx, rec in enumerate(doc.get("parity_claims") or []):
        if rec.get("parity_status") == "parity":
            for sid in rec.get("expected_substrates") or []:
                _require(
                    rec.get("claim_id") in coverage_index.get(sid, set()),
                    "I-10",
                    f"parity_claims[{cidx}] claim_id="
                    f"{rec.get('claim_id')!r} declared status='parity' "
                    f"but substrate {sid!r} claim_coverage does not "
                    f"include it",
                )


def _check_divergence_budget(doc: dict) -> None:
    db = doc.get("divergence_budget")
    _require(
        isinstance(db, dict),
        "I-11",
        f"divergence_budget must be an object, got {type(db).__name__}",
    )
    missing = DIVERGENCE_BUDGET_ALLOWED_KEYS - set(db.keys())
    _require(
        not missing,
        "I-11",
        f"divergence_budget missing fields: {sorted(missing)!r}",
    )
    extra = set(db.keys()) - DIVERGENCE_BUDGET_ALLOWED_KEYS
    _require(
        not extra,
        "I-11",
        f"divergence_budget carries unknown fields: {sorted(extra)!r}",
    )
    mdc = db.get("max_divergent_claims")
    _require(
        _is_int(mdc) and 0 <= mdc <= 3,
        "I-11",
        f"divergence_budget.max_divergent_claims must be int in [0,3], "
        f"got {mdc!r}",
    )
    mslt = db.get("max_substrate_lag_ticks")
    _require(
        _is_int(mslt) and 0 <= mslt <= 16,
        "I-11",
        f"divergence_budget.max_substrate_lag_ticks must be int in "
        f"[0,16], got {mslt!r}",
    )
    tdk = db.get("tolerated_divergence_kinds")
    _require(
        isinstance(tdk, list),
        "I-11",
        f"divergence_budget.tolerated_divergence_kinds must be a list, "
        f"got {type(tdk).__name__}",
    )
    for tidx, kind in enumerate(tdk):
        _require(
            kind in CANONICAL_CLAIM_KINDS,
            "I-11",
            f"divergence_budget.tolerated_divergence_kinds[{tidx}]="
            f"{kind!r} is not a canonical claim_kind",
        )


def _check_budget_enforcement(doc: dict) -> None:
    db = doc.get("divergence_budget") or {}
    claims = doc.get("parity_claims") or []
    divergent = [c for c in claims if c.get("parity_status") == "divergent"]
    mdc = db.get("max_divergent_claims")
    _require(
        len(divergent) <= mdc,
        "I-12",
        f"divergent claim count {len(divergent)} exceeds "
        f"max_divergent_claims budget {mdc}",
    )
    mslt = db.get("max_substrate_lag_ticks")
    for idx, rec in enumerate(doc.get("substrates") or []):
        lag = rec.get("lag_ticks")
        _require(
            lag <= mslt,
            "I-13",
            f"substrates[{idx}] lag_ticks={lag} exceeds "
            f"max_substrate_lag_ticks budget {mslt}",
        )
    tolerated = set(db.get("tolerated_divergence_kinds") or [])
    for idx, rec in enumerate(claims):
        if rec.get("parity_status") == "divergent":
            _require(
                rec.get("claim_kind") in tolerated,
                "I-14",
                f"parity_claims[{idx}] is divergent with "
                f"claim_kind={rec.get('claim_kind')!r}, which is not in "
                f"tolerated_divergence_kinds {sorted(tolerated)!r}",
            )


def _check_sandbox_boundary(doc: dict) -> None:
    sb = doc.get("sandbox_boundary")
    _require(
        isinstance(sb, dict),
        "I-15",
        f"sandbox_boundary must be an object, got {type(sb).__name__}",
    )
    for key in CANONICAL_BOUNDARY_BOOL_KEYS:
        _require(
            sb.get(key) is True,
            "I-15",
            f"sandbox_boundary.{key} must be true (got {sb.get(key)!r})",
        )
    _require(
        sb.get("probe_default_mode") == "inspection-only",
        "I-15",
        f"sandbox_boundary.probe_default_mode must be "
        f"'inspection-only', got {sb.get('probe_default_mode')!r}",
    )


def _check_cross_anchors(doc: dict) -> None:
    anchors = doc.get("cross_anchors")
    _require(
        isinstance(anchors, dict),
        "I-16",
        f"cross_anchors must be an object, got {type(anchors).__name__}",
    )
    missing = [a for a in REQUIRED_CROSS_ANCHORS if a not in anchors]
    _require(
        not missing,
        "I-16",
        f"cross_anchors missing required anchors: {missing!r}",
    )
    for key in REQUIRED_CROSS_ANCHORS:
        val = anchors.get(key)
        _require(
            isinstance(val, str) and val,
            "I-16",
            f"cross_anchors.{key} must be a non-empty string, got "
            f"{val!r}",
        )


def _check_coverage_breadth(doc: dict) -> None:
    """I-19: at least 3 of 4 substrates must have non-empty coverage."""
    subs = doc.get("substrates") or []
    non_empty = sum(
        1 for rec in subs if (rec.get("claim_coverage") or [])
    )
    _require(
        non_empty >= 3,
        "I-19",
        f"parity document has only {non_empty}/4 substrates with non-"
        f"empty claim_coverage (minimum 3 required to demonstrate parity)",
    )


def verify_parity(doc: Any) -> None:
    """Validate a Welle-6 cross-substrate-parity-spec document.

    Raises ``VerifyError`` with an invariant-tagged message on the
    first failing invariant. Returns ``None`` on success.
    """
    _check_top_level_shape(doc)
    _check_tag_and_welle(doc)
    _check_audit_only(doc)
    _check_parity_scope(doc)
    _check_parity_id(doc)
    _check_substrates(doc)
    _check_parity_claims(doc)
    _check_coverage_consistency(doc)
    _check_divergence_budget(doc)
    _check_budget_enforcement(doc)
    _check_sandbox_boundary(doc)
    _check_cross_anchors(doc)
    _check_coverage_breadth(doc)


def _fail(msg: str) -> int:
    sys.stderr.write(
        f"verify_cross_substrate_parity_spec: FAIL: {msg}\n"
    )
    return 1


def main(argv: Iterable[str]) -> int:
    args = list(argv)
    if len(args) != 1:
        return _fail(
            "usage: verify_cross_substrate_parity_spec.py <parity.json>"
        )
    path = args[0]
    try:
        with open(path, encoding="utf-8") as handle:
            doc = json.load(handle)
    except FileNotFoundError:
        return _fail(f"parity document not found: {path!r}")
    except json.JSONDecodeError as exc:
        return _fail(f"parity document {path!r} is not valid JSON: {exc}")
    try:
        verify_parity(doc)
    except VerifyError as exc:
        return _fail(str(exc))
    print(
        "verify_cross_substrate_parity_spec: OK "
        "(Tag-74 Welle-6 cross-substrate-parity-spec conformance, "
        "20 invariants, audit-only)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
