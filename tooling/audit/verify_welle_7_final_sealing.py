#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Tag-75 Welle-7 Final-Sealing Spec-Conformance Verifier.

Audit-only mode. This helper validates a *final-sealing
document* against the Welle-7 (Final-Sealing) conformance
invariants for the Phase-3c-Cutover-Marathon-Schluss-Sealing.
It does NOT actually execute the engine, does NOT load the
schema-registry, does NOT touch the audit-trail WAT-leaves,
does NOT call the protocol-spec compiler, does NOT open any
promotion-PR, and does NOT cut a release tag. It is a
structural / invariant inspector over a sealing-document of
shape::

    {
      "tag": "Tag-75",
      "welle": "Welle-7",
      "audit_only": true,
      "doc_form_only": true,
      "sealing_scope": "Final-Sealing",
      "sealing_id": "<opaque-sealing-identifier>",
      "predecessor_wellen": [<welle-record>, ...],
      "marker_families": [<family-record>, ...],
      "ots_anchor_chain": {
        "links": [<chain-link>, ...],
        "head_anchor_pin": "<opaque pin>",
        "tail_anchor_pin": "<opaque pin>",
        "chain_complete":  <bool>
      },
      "sealing_budget": {
        "max_unfinalised_families":  <integer 0..2>,
        "max_chain_gap_count":       <integer 0..1>,
        "tolerated_signoff_kinds":   [<string>, ...]
      },
      "sandbox_boundary": {
        "no_engine_invocation":      true,
        "no_schema_registry_write":  true,
        "no_audit_trail_write":      true,
        "no_spec_compiler_call":     true,
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
        "wat_layer_4_anchor":        "...",
        "wirelang_layer_3_schema":   "...",
        "tag_73_capability_layer":   "...",
        "tag_74_parity_layer":       "..."
      }
    }

A welle-record (one for each predecessor welle 1..6) has::

    {
      "welle_id":       "<one of: Welle-1 .. Welle-6>",
      "tag_origin":     "<Tag-69 .. Tag-74>",
      "signoff_kind":   "<one of: spec | producer | verifier |
                                   sweep | substrate | parity>",
      "signoff_status": "<one of: signed-off | pending | rejected>",
      "anchor_pin":     "<opaque pin string>"
    }

A marker-family-record has::

    {
      "family_id":       "<unique id matching ^family-[a-z0-9-]{3,48}$>",
      "family_kind":     "<one of: capability | parity | substrate |
                                    sweep | spec | producer>",
      "finalisation_status": "<one of: finalised | partial | open>",
      "marker_count":    <integer >=1>,
      "anchor_pins":     [<opaque pin string>, ...]
    }

A chain-link (one rung in the OTS-anchor-chain) has::

    {
      "link_index":      <integer >=0>,
      "predecessor_pin": "<opaque pin string or null for head>",
      "successor_pin":   "<opaque pin string or null for tail>",
      "anchor_pin":      "<opaque pin string>"
    }

Invariants checked (Welle-7 Final-Sealing):

  I-1   ``tag`` is ``Tag-75`` and ``welle`` is ``Welle-7``.
  I-2   ``audit_only`` and ``doc_form_only`` are both true. The
        helper refuses to validate a non-audit-only document.
  I-3   ``sealing_scope`` is exactly ``Final-Sealing``.
  I-4   ``sealing_id`` is a non-empty string matching
        ``^sealing-[a-z0-9-]{4,64}$``.
  I-5   ``predecessor_wellen`` is a list of exactly six welle-
        records, one for each of Welle-1 .. Welle-6.  Duplicates
        are rejected, missing wellen are rejected.
  I-6   Each welle-record carries the five required fields and
        no extras.  ``signoff_status`` MUST be ``signed-off``
        for every predecessor welle (final sealing cannot
        proceed with any pending or rejected predecessor).
  I-7   ``marker_families`` is a non-empty list of family-records
        (at least one family per Welle-1..6 producer is expected
        but not required; budget allows partial finalisation).
        Each family_id is unique.  At least one family must have
        ``family_kind == 'capability'`` and one
        ``family_kind == 'parity'`` (the two cornerstone families).
  I-8   Each family-record carries the five required fields and
        no extras.  ``marker_count`` is int >=1; ``anchor_pins``
        is a non-empty list of non-empty strings; ``family_id``
        matches ``^family-[a-z0-9-]{3,48}$``.
  I-9   ``finalisation_status`` is one of
        ``finalised | partial | open``.  ``finalised`` requires
        ``marker_count == len(anchor_pins)``.  ``open`` requires
        ``anchor_pins == []`` (but I-8 forbids empty, so
        ``open`` actually means there are pins recorded but the
        family is not closed -- the invariant is that
        ``open`` MUST NOT appear together with marker_count == 0).
        ``partial`` requires ``0 < len(anchor_pins) < marker_count``.
  I-10  ``ots_anchor_chain`` carries the four required fields.
        ``links`` is a non-empty list.  ``chain_complete`` is
        a bool.  ``head_anchor_pin`` and ``tail_anchor_pin`` are
        non-empty strings.
  I-11  Each chain-link carries the four required fields.
        ``link_index`` is int >=0 and unique across links.
        ``anchor_pin`` is a non-empty string.  ``predecessor_pin``
        is null for the link with ``link_index == 0`` and equal
        to the previous link's ``anchor_pin`` for all others.
        ``successor_pin`` is null for the last link and equal
        to the next link's ``anchor_pin`` for all others.
  I-12  ``head_anchor_pin`` equals the anchor_pin of the link
        with the lowest link_index; ``tail_anchor_pin`` equals
        the anchor_pin of the link with the highest link_index.
  I-13  ``chain_complete`` is true iff there is no gap between
        link_index values (i.e. they form a contiguous sequence
        starting at 0).  If ``chain_complete`` is false, the
        gap count MUST NOT exceed
        ``sealing_budget.max_chain_gap_count``.
  I-14  ``sealing_budget`` carries the three required fields.
        ``max_unfinalised_families`` is int in [0, 2];
        ``max_chain_gap_count`` is int in [0, 1];
        ``tolerated_signoff_kinds`` is a list (possibly empty)
        of strings drawn from the canonical signoff_kind set.
  I-15  Count of families with ``finalisation_status != 'finalised'``
        MUST NOT exceed ``sealing_budget.max_unfinalised_families``.
  I-16  ``sandbox_boundary`` declares ALL six boolean defaults true
        (no_engine_invocation, no_schema_registry_write,
        no_audit_trail_write, no_spec_compiler_call,
        no_promotion_pr_opening, no_release_tag_cut) and
        ``probe_default_mode == 'inspection-only'``.
  I-17  ``cross_anchors`` references the nine baseline anchors
        including ``tag_74_parity_layer`` (Welle-6 carry-forward).
  I-18  No top-level unknown fields (strict shape).
  I-19  ``audit_only`` is type bool exactly; integers / strings
        rejected.
  I-20  Every welle-record's ``signoff_kind`` is in the canonical
        signoff_kind set; if any welle's ``signoff_status`` is
        ``rejected`` the seal is rejected outright regardless of
        ``tolerated_signoff_kinds`` (rejection is terminal).
  I-21  Helper itself does not write any file, does not open any
        network socket, does not call the engine, does not invoke
        any spec-compiler, does not consult any environment
        variable that would gate the inspection, and does not
        cut a release tag.

The helper exits 0 on green (all invariants pass), 1 on any
failure with a clear stderr message naming the first failing
invariant.

Standard library only.  CLI usage::

    python tooling/audit/verify_welle_7_final_sealing.py \\
        <path-to-sealing-document.json>

Programmatic usage::

    from verify_welle_7_final_sealing import verify_sealing
    verify_sealing(doc)  # raises VerifyError on failure

Sandbox-boundary recital:

  - No engine invocation by this helper.
  - No schema-registry write by this helper.
  - No audit-trail (WAT-leaf) write by this helper.
  - No spec-compiler call by this helper.
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
)
CANONICAL_TAG_ORIGINS = (
    "Tag-69",
    "Tag-70",
    "Tag-71",
    "Tag-72",
    "Tag-73",
    "Tag-74",
)
CANONICAL_SIGNOFF_KINDS = (
    "spec",
    "producer",
    "verifier",
    "sweep",
    "substrate",
    "parity",
)
CANONICAL_SIGNOFF_STATUSES = ("signed-off", "pending", "rejected")
CANONICAL_FAMILY_KINDS = (
    "capability",
    "parity",
    "substrate",
    "sweep",
    "spec",
    "producer",
)
CANONICAL_FINALISATION_STATUSES = ("finalised", "partial", "open")
CANONICAL_BOUNDARY_BOOL_KEYS = (
    "no_engine_invocation",
    "no_schema_registry_write",
    "no_audit_trail_write",
    "no_spec_compiler_call",
    "no_promotion_pr_opening",
    "no_release_tag_cut",
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
    "tag_74_parity_layer",
)
SEALING_ID_RE = re.compile(r"^sealing-[a-z0-9-]{4,64}$")
FAMILY_ID_RE = re.compile(r"^family-[a-z0-9-]{3,48}$")
WELLE_RECORD_ALLOWED_KEYS = frozenset(
    {
        "welle_id",
        "tag_origin",
        "signoff_kind",
        "signoff_status",
        "anchor_pin",
    }
)
FAMILY_RECORD_ALLOWED_KEYS = frozenset(
    {
        "family_id",
        "family_kind",
        "finalisation_status",
        "marker_count",
        "anchor_pins",
    }
)
CHAIN_LINK_ALLOWED_KEYS = frozenset(
    {
        "link_index",
        "predecessor_pin",
        "successor_pin",
        "anchor_pin",
    }
)
OTS_CHAIN_ALLOWED_KEYS = frozenset(
    {
        "links",
        "head_anchor_pin",
        "tail_anchor_pin",
        "chain_complete",
    }
)
SEALING_BUDGET_ALLOWED_KEYS = frozenset(
    {
        "max_unfinalised_families",
        "max_chain_gap_count",
        "tolerated_signoff_kinds",
    }
)
TOP_LEVEL_REQUIRED_KEYS = frozenset(
    {
        "tag",
        "welle",
        "audit_only",
        "doc_form_only",
        "sealing_scope",
        "sealing_id",
        "predecessor_wellen",
        "marker_families",
        "ots_anchor_chain",
        "sealing_budget",
        "sandbox_boundary",
        "cross_anchors",
    }
)
# REUSE-IgnoreEnd


class VerifyError(Exception):
    """Raised when a Welle-7 final-sealing-spec invariant fails."""


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
        f"sealing document must be an object, got {type(doc).__name__}",
    )
    missing = TOP_LEVEL_REQUIRED_KEYS - set(doc.keys())
    _require(
        not missing,
        "I-0",
        f"sealing document missing required top-level keys: "
        f"{sorted(missing)!r}",
    )
    extra = set(doc.keys()) - TOP_LEVEL_REQUIRED_KEYS
    _require(
        not extra,
        "I-18",
        f"sealing document carries unknown top-level fields: "
        f"{sorted(extra)!r}",
    )


def _check_tag_and_welle(doc: dict) -> None:
    _require(
        doc.get("tag") == "Tag-75",
        "I-1",
        f"tag must be 'Tag-75', got {doc.get('tag')!r}",
    )
    _require(
        doc.get("welle") == "Welle-7",
        "I-1",
        f"welle must be 'Welle-7', got {doc.get('welle')!r}",
    )


def _check_audit_only(doc: dict) -> None:
    _require(
        _is_bool(doc.get("audit_only")),
        "I-19",
        f"audit_only must be a bool, got "
        f"{type(doc.get('audit_only')).__name__}",
    )
    _require(
        _is_bool(doc.get("doc_form_only")),
        "I-19",
        f"doc_form_only must be a bool, got "
        f"{type(doc.get('doc_form_only')).__name__}",
    )
    _require(
        doc.get("audit_only") is True,
        "I-2",
        "sealing document must declare 'audit_only: true' "
        "(Tag-75 helper refuses non-audit-only documents)",
    )
    _require(
        doc.get("doc_form_only") is True,
        "I-2",
        "sealing document must declare 'doc_form_only: true'",
    )


def _check_sealing_scope(doc: dict) -> None:
    _require(
        doc.get("sealing_scope") == "Final-Sealing",
        "I-3",
        f"sealing_scope must be 'Final-Sealing', got "
        f"{doc.get('sealing_scope')!r}",
    )


def _check_sealing_id(doc: dict) -> None:
    sid = doc.get("sealing_id")
    _require(
        isinstance(sid, str) and SEALING_ID_RE.match(sid) is not None,
        "I-4",
        f"sealing_id must match {SEALING_ID_RE.pattern!r}, got {sid!r}",
    )


def _check_welle_record(rec: Any, idx: int) -> None:
    _require(
        isinstance(rec, dict),
        "I-6",
        f"predecessor_wellen[{idx}] must be an object, got "
        f"{type(rec).__name__}",
    )
    missing = WELLE_RECORD_ALLOWED_KEYS - set(rec.keys())
    _require(
        not missing,
        "I-6",
        f"predecessor_wellen[{idx}] missing fields: {sorted(missing)!r}",
    )
    extra = set(rec.keys()) - WELLE_RECORD_ALLOWED_KEYS
    _require(
        not extra,
        "I-6",
        f"predecessor_wellen[{idx}] carries unknown fields: "
        f"{sorted(extra)!r}",
    )
    wid = rec.get("welle_id")
    _require(
        wid in CANONICAL_WELLE_IDS,
        "I-5",
        f"predecessor_wellen[{idx}].welle_id must be one of "
        f"{CANONICAL_WELLE_IDS!r}, got {wid!r}",
    )
    tag_origin = rec.get("tag_origin")
    _require(
        tag_origin in CANONICAL_TAG_ORIGINS,
        "I-6",
        f"predecessor_wellen[{idx}].tag_origin must be one of "
        f"{CANONICAL_TAG_ORIGINS!r}, got {tag_origin!r}",
    )
    skind = rec.get("signoff_kind")
    _require(
        skind in CANONICAL_SIGNOFF_KINDS,
        "I-20",
        f"predecessor_wellen[{idx}].signoff_kind must be one of "
        f"{CANONICAL_SIGNOFF_KINDS!r}, got {skind!r}",
    )
    sstatus = rec.get("signoff_status")
    _require(
        sstatus in CANONICAL_SIGNOFF_STATUSES,
        "I-6",
        f"predecessor_wellen[{idx}].signoff_status must be one of "
        f"{CANONICAL_SIGNOFF_STATUSES!r}, got {sstatus!r}",
    )
    _require(
        sstatus != "rejected",
        "I-20",
        f"predecessor_wellen[{idx}] welle_id={wid!r} has "
        f"signoff_status='rejected' -- final sealing is terminal-"
        f"refused on any rejection",
    )
    _require(
        sstatus == "signed-off",
        "I-6",
        f"predecessor_wellen[{idx}] welle_id={wid!r} has "
        f"signoff_status={sstatus!r}; final sealing requires every "
        f"predecessor welle to be signed-off",
    )
    pin = rec.get("anchor_pin")
    _require(
        isinstance(pin, str) and pin,
        "I-6",
        f"predecessor_wellen[{idx}].anchor_pin must be a non-empty "
        f"string, got {pin!r}",
    )


def _check_predecessor_wellen(doc: dict) -> None:
    wellen = doc.get("predecessor_wellen")
    _require(
        isinstance(wellen, list),
        "I-5",
        f"predecessor_wellen must be a list, got {type(wellen).__name__}",
    )
    _require(
        len(wellen) == 6,
        "I-5",
        f"predecessor_wellen must contain exactly 6 welle-records "
        f"(one per Welle-1..6), got {len(wellen)}",
    )
    for idx, rec in enumerate(wellen):
        _check_welle_record(rec, idx)
    ids = [rec.get("welle_id") for rec in wellen]
    _require(
        len(set(ids)) == 6,
        "I-5",
        f"welle_ids must be unique across predecessor_wellen, got "
        f"{ids!r}",
    )
    missing_canonical = set(CANONICAL_WELLE_IDS) - set(ids)
    _require(
        not missing_canonical,
        "I-5",
        f"predecessor_wellen is missing canonical welle-ids: "
        f"{sorted(missing_canonical)!r}",
    )


def _check_family_record(rec: Any, idx: int) -> None:
    _require(
        isinstance(rec, dict),
        "I-8",
        f"marker_families[{idx}] must be an object, got "
        f"{type(rec).__name__}",
    )
    missing = FAMILY_RECORD_ALLOWED_KEYS - set(rec.keys())
    _require(
        not missing,
        "I-8",
        f"marker_families[{idx}] missing fields: {sorted(missing)!r}",
    )
    extra = set(rec.keys()) - FAMILY_RECORD_ALLOWED_KEYS
    _require(
        not extra,
        "I-8",
        f"marker_families[{idx}] carries unknown fields: "
        f"{sorted(extra)!r}",
    )
    fid = rec.get("family_id")
    _require(
        isinstance(fid, str) and FAMILY_ID_RE.match(fid) is not None,
        "I-8",
        f"marker_families[{idx}].family_id must match "
        f"{FAMILY_ID_RE.pattern!r}, got {fid!r}",
    )
    fkind = rec.get("family_kind")
    _require(
        fkind in CANONICAL_FAMILY_KINDS,
        "I-8",
        f"marker_families[{idx}].family_kind must be one of "
        f"{CANONICAL_FAMILY_KINDS!r}, got {fkind!r}",
    )
    fstatus = rec.get("finalisation_status")
    _require(
        fstatus in CANONICAL_FINALISATION_STATUSES,
        "I-9",
        f"marker_families[{idx}].finalisation_status must be one of "
        f"{CANONICAL_FINALISATION_STATUSES!r}, got {fstatus!r}",
    )
    mc = rec.get("marker_count")
    _require(
        _is_int(mc) and mc >= 1,
        "I-8",
        f"marker_families[{idx}].marker_count must be int >=1, "
        f"got {mc!r}",
    )
    pins = rec.get("anchor_pins")
    _require(
        isinstance(pins, list) and pins,
        "I-8",
        f"marker_families[{idx}].anchor_pins must be a non-empty list, "
        f"got {pins!r}",
    )
    for pidx, pin in enumerate(pins):
        _require(
            isinstance(pin, str) and pin,
            "I-8",
            f"marker_families[{idx}].anchor_pins[{pidx}] must be a "
            f"non-empty string, got {pin!r}",
        )
    # I-9 status-consistency checks
    pin_count = len(pins)
    if fstatus == "finalised":
        _require(
            pin_count == mc,
            "I-9",
            f"marker_families[{idx}] declared "
            f"finalisation_status='finalised' but anchor_pins count "
            f"{pin_count} != marker_count {mc}",
        )
    elif fstatus == "partial":
        _require(
            0 < pin_count < mc,
            "I-9",
            f"marker_families[{idx}] declared "
            f"finalisation_status='partial' requires "
            f"0 < anchor_pins count < marker_count, got "
            f"{pin_count} pins for marker_count {mc}",
        )
    elif fstatus == "open":
        # 'open' means recorded but not closed; require pin_count <= mc
        # and that the family is genuinely incomplete.
        _require(
            pin_count < mc,
            "I-9",
            f"marker_families[{idx}] declared "
            f"finalisation_status='open' but anchor_pins count "
            f"{pin_count} >= marker_count {mc}",
        )


def _check_marker_families(doc: dict) -> None:
    fams = doc.get("marker_families")
    _require(
        isinstance(fams, list),
        "I-7",
        f"marker_families must be a list, got {type(fams).__name__}",
    )
    _require(
        len(fams) >= 1,
        "I-7",
        "marker_families must contain at least one family-record",
    )
    seen_ids: set = set()
    for idx, rec in enumerate(fams):
        _check_family_record(rec, idx)
        fid = rec.get("family_id")
        _require(
            fid not in seen_ids,
            "I-7",
            f"marker_families[{idx}].family_id={fid!r} is duplicated",
        )
        seen_ids.add(fid)
    kinds = [rec.get("family_kind") for rec in fams]
    _require(
        "capability" in kinds,
        "I-7",
        "marker_families must contain at least one family with "
        "family_kind='capability' (Welle-5 cornerstone)",
    )
    _require(
        "parity" in kinds,
        "I-7",
        "marker_families must contain at least one family with "
        "family_kind='parity' (Welle-6 cornerstone)",
    )


def _check_chain_link(rec: Any, idx: int) -> None:
    _require(
        isinstance(rec, dict),
        "I-11",
        f"ots_anchor_chain.links[{idx}] must be an object, got "
        f"{type(rec).__name__}",
    )
    missing = CHAIN_LINK_ALLOWED_KEYS - set(rec.keys())
    _require(
        not missing,
        "I-11",
        f"ots_anchor_chain.links[{idx}] missing fields: "
        f"{sorted(missing)!r}",
    )
    extra = set(rec.keys()) - CHAIN_LINK_ALLOWED_KEYS
    _require(
        not extra,
        "I-11",
        f"ots_anchor_chain.links[{idx}] carries unknown fields: "
        f"{sorted(extra)!r}",
    )
    li = rec.get("link_index")
    _require(
        _is_int(li) and li >= 0,
        "I-11",
        f"ots_anchor_chain.links[{idx}].link_index must be int >=0, "
        f"got {li!r}",
    )
    ap = rec.get("anchor_pin")
    _require(
        isinstance(ap, str) and ap,
        "I-11",
        f"ots_anchor_chain.links[{idx}].anchor_pin must be a non-empty "
        f"string, got {ap!r}",
    )
    pp = rec.get("predecessor_pin")
    _require(
        pp is None or (isinstance(pp, str) and pp),
        "I-11",
        f"ots_anchor_chain.links[{idx}].predecessor_pin must be a "
        f"non-empty string or null, got {pp!r}",
    )
    sp = rec.get("successor_pin")
    _require(
        sp is None or (isinstance(sp, str) and sp),
        "I-11",
        f"ots_anchor_chain.links[{idx}].successor_pin must be a "
        f"non-empty string or null, got {sp!r}",
    )


def _check_ots_anchor_chain(doc: dict) -> None:
    chain = doc.get("ots_anchor_chain")
    _require(
        isinstance(chain, dict),
        "I-10",
        f"ots_anchor_chain must be an object, got {type(chain).__name__}",
    )
    missing = OTS_CHAIN_ALLOWED_KEYS - set(chain.keys())
    _require(
        not missing,
        "I-10",
        f"ots_anchor_chain missing fields: {sorted(missing)!r}",
    )
    extra = set(chain.keys()) - OTS_CHAIN_ALLOWED_KEYS
    _require(
        not extra,
        "I-10",
        f"ots_anchor_chain carries unknown fields: {sorted(extra)!r}",
    )
    links = chain.get("links")
    _require(
        isinstance(links, list) and links,
        "I-10",
        f"ots_anchor_chain.links must be a non-empty list, got "
        f"{type(links).__name__}",
    )
    head_pin = chain.get("head_anchor_pin")
    _require(
        isinstance(head_pin, str) and head_pin,
        "I-10",
        f"ots_anchor_chain.head_anchor_pin must be a non-empty string, "
        f"got {head_pin!r}",
    )
    tail_pin = chain.get("tail_anchor_pin")
    _require(
        isinstance(tail_pin, str) and tail_pin,
        "I-10",
        f"ots_anchor_chain.tail_anchor_pin must be a non-empty string, "
        f"got {tail_pin!r}",
    )
    chain_complete = chain.get("chain_complete")
    _require(
        _is_bool(chain_complete),
        "I-10",
        f"ots_anchor_chain.chain_complete must be a bool, got "
        f"{type(chain_complete).__name__}",
    )
    for idx, link in enumerate(links):
        _check_chain_link(link, idx)
    # I-11 cross-link consistency
    indices = [link.get("link_index") for link in links]
    _require(
        len(set(indices)) == len(indices),
        "I-11",
        f"ots_anchor_chain.links link_index values must be unique, got "
        f"{indices!r}",
    )
    # sort by link_index for adjacency check
    sorted_links = sorted(links, key=lambda l: l.get("link_index"))
    min_idx = sorted_links[0].get("link_index")
    _require(
        min_idx == 0,
        "I-11",
        f"ots_anchor_chain.links lowest link_index must be 0, got "
        f"{min_idx!r}",
    )
    for pos, link in enumerate(sorted_links):
        if pos == 0:
            _require(
                link.get("predecessor_pin") is None,
                "I-11",
                f"ots_anchor_chain head link (link_index="
                f"{link.get('link_index')!r}) must have "
                f"predecessor_pin=null, got "
                f"{link.get('predecessor_pin')!r}",
            )
        else:
            prev = sorted_links[pos - 1]
            _require(
                link.get("predecessor_pin") == prev.get("anchor_pin"),
                "I-11",
                f"ots_anchor_chain.links[link_index="
                f"{link.get('link_index')!r}].predecessor_pin must "
                f"equal previous link's anchor_pin "
                f"{prev.get('anchor_pin')!r}, got "
                f"{link.get('predecessor_pin')!r}",
            )
        if pos == len(sorted_links) - 1:
            _require(
                link.get("successor_pin") is None,
                "I-11",
                f"ots_anchor_chain tail link (link_index="
                f"{link.get('link_index')!r}) must have "
                f"successor_pin=null, got "
                f"{link.get('successor_pin')!r}",
            )
        else:
            nxt = sorted_links[pos + 1]
            _require(
                link.get("successor_pin") == nxt.get("anchor_pin"),
                "I-11",
                f"ots_anchor_chain.links[link_index="
                f"{link.get('link_index')!r}].successor_pin must "
                f"equal next link's anchor_pin "
                f"{nxt.get('anchor_pin')!r}, got "
                f"{link.get('successor_pin')!r}",
            )
    # I-12 head/tail pin consistency
    _require(
        head_pin == sorted_links[0].get("anchor_pin"),
        "I-12",
        f"ots_anchor_chain.head_anchor_pin must equal anchor_pin of "
        f"the link with the lowest link_index "
        f"({sorted_links[0].get('anchor_pin')!r}), got {head_pin!r}",
    )
    _require(
        tail_pin == sorted_links[-1].get("anchor_pin"),
        "I-12",
        f"ots_anchor_chain.tail_anchor_pin must equal anchor_pin of "
        f"the link with the highest link_index "
        f"({sorted_links[-1].get('anchor_pin')!r}), got {tail_pin!r}",
    )
    # I-13 chain_complete consistency
    max_idx = sorted_links[-1].get("link_index")
    expected_contiguous = max_idx == len(sorted_links) - 1
    gap_count = max_idx + 1 - len(sorted_links)
    if chain_complete:
        _require(
            expected_contiguous,
            "I-13",
            f"ots_anchor_chain.chain_complete=true but link_index "
            f"sequence has gaps (max_index={max_idx}, "
            f"link_count={len(sorted_links)})",
        )
    else:
        budget_gap = (doc.get("sealing_budget") or {}).get(
            "max_chain_gap_count"
        )
        if _is_int(budget_gap):
            _require(
                gap_count <= budget_gap,
                "I-13",
                f"ots_anchor_chain.chain_complete=false with gap_count "
                f"{gap_count} exceeds max_chain_gap_count budget "
                f"{budget_gap}",
            )


def _check_sealing_budget(doc: dict) -> None:
    sb = doc.get("sealing_budget")
    _require(
        isinstance(sb, dict),
        "I-14",
        f"sealing_budget must be an object, got {type(sb).__name__}",
    )
    missing = SEALING_BUDGET_ALLOWED_KEYS - set(sb.keys())
    _require(
        not missing,
        "I-14",
        f"sealing_budget missing fields: {sorted(missing)!r}",
    )
    extra = set(sb.keys()) - SEALING_BUDGET_ALLOWED_KEYS
    _require(
        not extra,
        "I-14",
        f"sealing_budget carries unknown fields: {sorted(extra)!r}",
    )
    muf = sb.get("max_unfinalised_families")
    _require(
        _is_int(muf) and 0 <= muf <= 2,
        "I-14",
        f"sealing_budget.max_unfinalised_families must be int in "
        f"[0,2], got {muf!r}",
    )
    mcg = sb.get("max_chain_gap_count")
    _require(
        _is_int(mcg) and 0 <= mcg <= 1,
        "I-14",
        f"sealing_budget.max_chain_gap_count must be int in [0,1], "
        f"got {mcg!r}",
    )
    tsk = sb.get("tolerated_signoff_kinds")
    _require(
        isinstance(tsk, list),
        "I-14",
        f"sealing_budget.tolerated_signoff_kinds must be a list, got "
        f"{type(tsk).__name__}",
    )
    for tidx, kind in enumerate(tsk):
        _require(
            kind in CANONICAL_SIGNOFF_KINDS,
            "I-14",
            f"sealing_budget.tolerated_signoff_kinds[{tidx}]="
            f"{kind!r} is not a canonical signoff_kind",
        )


def _check_budget_enforcement(doc: dict) -> None:
    sb = doc.get("sealing_budget") or {}
    fams = doc.get("marker_families") or []
    unfinalised = [
        f for f in fams
        if f.get("finalisation_status") != "finalised"
    ]
    muf = sb.get("max_unfinalised_families")
    _require(
        len(unfinalised) <= muf,
        "I-15",
        f"unfinalised marker_families count {len(unfinalised)} exceeds "
        f"max_unfinalised_families budget {muf}",
    )


def _check_sandbox_boundary(doc: dict) -> None:
    sb = doc.get("sandbox_boundary")
    _require(
        isinstance(sb, dict),
        "I-16",
        f"sandbox_boundary must be an object, got {type(sb).__name__}",
    )
    for key in CANONICAL_BOUNDARY_BOOL_KEYS:
        _require(
            sb.get(key) is True,
            "I-16",
            f"sandbox_boundary.{key} must be true (got {sb.get(key)!r})",
        )
    _require(
        sb.get("probe_default_mode") == "inspection-only",
        "I-16",
        f"sandbox_boundary.probe_default_mode must be "
        f"'inspection-only', got {sb.get('probe_default_mode')!r}",
    )


def _check_cross_anchors(doc: dict) -> None:
    anchors = doc.get("cross_anchors")
    _require(
        isinstance(anchors, dict),
        "I-17",
        f"cross_anchors must be an object, got {type(anchors).__name__}",
    )
    missing = [a for a in REQUIRED_CROSS_ANCHORS if a not in anchors]
    _require(
        not missing,
        "I-17",
        f"cross_anchors missing required anchors: {missing!r}",
    )
    for key in REQUIRED_CROSS_ANCHORS:
        val = anchors.get(key)
        _require(
            isinstance(val, str) and val,
            "I-17",
            f"cross_anchors.{key} must be a non-empty string, got "
            f"{val!r}",
        )


def verify_sealing(doc: Any) -> None:
    """Validate a Welle-7 final-sealing-spec document.

    Raises ``VerifyError`` with an invariant-tagged message on the
    first failing invariant. Returns ``None`` on success.
    """
    _check_top_level_shape(doc)
    _check_tag_and_welle(doc)
    _check_audit_only(doc)
    _check_sealing_scope(doc)
    _check_sealing_id(doc)
    _check_predecessor_wellen(doc)
    _check_marker_families(doc)
    _check_sealing_budget(doc)
    _check_ots_anchor_chain(doc)
    _check_budget_enforcement(doc)
    _check_sandbox_boundary(doc)
    _check_cross_anchors(doc)


def _fail(msg: str) -> int:
    sys.stderr.write(
        f"verify_welle_7_final_sealing: FAIL: {msg}\n"
    )
    return 1


def main(argv: Iterable[str]) -> int:
    args = list(argv)
    if len(args) != 1:
        return _fail(
            "usage: verify_welle_7_final_sealing.py <sealing.json>"
        )
    path = args[0]
    try:
        with open(path, encoding="utf-8") as handle:
            doc = json.load(handle)
    except FileNotFoundError:
        return _fail(f"sealing document not found: {path!r}")
    except json.JSONDecodeError as exc:
        return _fail(f"sealing document {path!r} is not valid JSON: {exc}")
    try:
        verify_sealing(doc)
    except VerifyError as exc:
        return _fail(str(exc))
    print(
        "verify_welle_7_final_sealing: OK "
        "(Tag-75 Welle-7 final-sealing-spec conformance, "
        "21 invariants, audit-only)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
