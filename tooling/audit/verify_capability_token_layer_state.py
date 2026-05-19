#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Tag-73 Capability-Token-Layer State-Conformance Verifier (Welle-5).

Audit-only mode. This helper validates a *capability-token-layer
state document* against the Welle-5 (Capability-Token-Rotation)
conformance invariants. It does NOT actually rotate any token, does
NOT call any Biscuit/AIP issuer, does NOT mint or revoke keys, does
NOT touch the NATS-KV capability-policy bucket, and does NOT open
any promotion-PR. It is a structural / invariant inspector over a
state-document of shape::

    {
      "tag": "Tag-73",
      "welle": "Welle-5",
      "audit_only": true,
      "doc_form_only": true,
      "layer": "Layer-3-AIP+Biscuit",
      "rotation_id": "<opaque-rotation-identifier>",
      "rotation_state": "<one of: pre-rotation | rotation-in-progress |
                                  post-rotation-grace |
                                  post-rotation-sealed>",
      "issuer_curve": "<Ed25519 | secp256k1>",
      "token_format": "biscuit-v3",
      "attenuation_depth_max": <integer 1..8>,
      "active_tokens": [<token-record>, ...],
      "rotation_steps": [<step-record>, ...],
      "audit_trail_refs": [<wat-leaf-ref>, ...],
      "sandbox_boundary": {
        "no_token_mint":            true,
        "no_token_revoke":          true,
        "no_aip_issuer_call":       true,
        "no_nats_kv_bucket_write":  true,
        "no_promotion_pr_opening":  true,
        "probe_default_mode":       "inspection-only"
      },
      "cross_anchors": {
        "adr_0007": "...",
        "adr_0017": "...",
        "adr_0023a": "...",
        "adr_0023b": "...",
        "adr_0025": "...",
        "wat_layer_4_anchor": "...",
        "wirelang_layer_3_schema": "..."
      }
    }

Invariants checked (Welle-5 / Doppel-Welle-4+5):

  I-1  ``tag`` is ``Tag-73`` and ``welle`` is ``Welle-5``.
  I-2  ``audit_only`` and ``doc_form_only`` are both true. (Tag-73
       MUST NOT claim to actually perform rotation; the helper
       refuses to validate a non-audit-only document.)
  I-3  ``layer`` is ``Layer-3-AIP+Biscuit`` (load-bearing for the
       Reza domain, ADR-0009 / capability-token-layer charter).
  I-4  ``rotation_state`` is one of the four canonical states
       (pre-rotation, rotation-in-progress, post-rotation-grace,
       post-rotation-sealed). Any other value rejects.
  I-5  ``issuer_curve`` is one of Ed25519 / secp256k1 (Two-Curve-
       Stack per Reza-Strang-2-Korrektur, 2026-05-06).
  I-6  ``token_format`` is ``biscuit-v3`` (single supported format
       in the Welle-5 cutover; v2 is forbidden by ADR-0017 anchor).
  I-7  ``attenuation_depth_max`` is an integer in [1, 8]. Depth 0
       is forbidden (an unattenuable root-token is not a Welle-5
       valid state); depth >8 exceeds Biscuit-v3 conservative
       budget.
  I-8  ``active_tokens`` is a list (possibly empty in pre-rotation
       state, but MUST be non-empty in rotation-in-progress and
       post-rotation-grace). Each token-record carries the four
       fields: ``token_id``, ``issuer_pubkey``, ``not_before``,
       ``not_after``, plus ``attenuation_depth`` and
       ``rotation_role`` of ``outgoing|incoming|stable``.
  I-9  Overlapping validity-windows are allowed in rotation-in-
       progress (outgoing.not_after >= incoming.not_before) and
       MANDATORY in post-rotation-grace (an outgoing token MUST
       still validate during the grace window per ADOL overlap
       semantics).
  I-10 ``rotation_steps`` is an ordered list. Each step carries
       ``step_id``, ``step_kind``
       (one of: announce-incoming, dual-validity-window-open,
       outgoing-drain, dual-validity-window-close, seal), and a
       ``status`` of ``planned|done|skipped``. Step ordering MUST
       match the canonical 5-step sequence: announce-incoming ->
       dual-validity-window-open -> outgoing-drain ->
       dual-validity-window-close -> seal.
  I-11 In ``post-rotation-sealed`` state ALL rotation_steps[*].status
       are ``done``, and active_tokens carry no ``outgoing`` role.
  I-12 ``audit_trail_refs`` carries at least one WAT-leaf reference
       (string of form ``wat-leaf://<hex-32>``). Each ref MUST be
       syntactically well-formed (hex-32 lower-case).
  I-13 ``sandbox_boundary`` declares ALL six boolean defaults true
       (no_token_mint, no_token_revoke, no_aip_issuer_call,
       no_nats_kv_bucket_write, no_promotion_pr_opening, plus
       probe_default_mode == ``inspection-only``).
  I-14 ``cross_anchors`` references ADR-0007, ADR-0017 (embodied
       capability tokens), ADR-0023a, ADR-0023b, ADR-0025, plus
       ``wat_layer_4_anchor`` and ``wirelang_layer_3_schema``.
  I-15 No active_token's ``not_before`` is in the future relative
       to its ``not_after`` (NB <= NA).
  I-16 No token-record carries an unrecognised field at the top
       level (strict shape; unknown fields are rejected to make
       the audit catalogue auditable).
  I-17 ``rotation_id`` is a non-empty string and matches
       ``^rot-[a-z0-9-]{4,64}$`` (opaque but bounded).
  I-18 In pre-rotation state, rotation_steps either is empty or
       all step statuses are ``planned``.
  I-19 An ``incoming`` token's ``not_after`` MUST be strictly
       greater than any ``outgoing`` token's ``not_after`` (forward-
       progress invariant: a rotation that does not extend reach
       has no audit value).
  I-20 Helper itself does not write the NATS-KV bucket, does not
       open any PR, does not call any external service, and does
       not consult any environment variable that would gate the
       inspection.

The helper exits 0 on green (all invariants pass), 1 on any failure
with a clear stderr message naming the first failing invariant.

Standard library only. CLI usage::

    python tooling/audit/verify_capability_token_layer_state.py \
        <path-to-state-document.json>

Programmatic usage::

    from verify_capability_token_layer_state import verify_state
    verify_state(state_dict)  # raises VerifyError on failure

Sandbox-boundary recital:

  - No token-mint by this helper.
  - No token-revoke by this helper.
  - No AIP-issuer call by this helper.
  - No NATS-KV bucket write by this helper.
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
CANONICAL_ROTATION_STATES = (
    "pre-rotation",
    "rotation-in-progress",
    "post-rotation-grace",
    "post-rotation-sealed",
)
CANONICAL_CURVES = ("Ed25519", "secp256k1")
CANONICAL_TOKEN_FORMAT = "biscuit-v3"
CANONICAL_STEP_KINDS_ORDER = (
    "announce-incoming",
    "dual-validity-window-open",
    "outgoing-drain",
    "dual-validity-window-close",
    "seal",
)
CANONICAL_STEP_STATUSES = ("planned", "done", "skipped")
CANONICAL_ROTATION_ROLES = ("outgoing", "incoming", "stable")
CANONICAL_BOUNDARY_BOOL_KEYS = (
    "no_token_mint",
    "no_token_revoke",
    "no_aip_issuer_call",
    "no_nats_kv_bucket_write",
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
)
ROTATION_ID_RE = re.compile(r"^rot-[a-z0-9-]{4,64}$")
WAT_LEAF_RE = re.compile(r"^wat-leaf://[0-9a-f]{32}$")
TOKEN_RECORD_ALLOWED_KEYS = frozenset(
    {
        "token_id",
        "issuer_pubkey",
        "not_before",
        "not_after",
        "attenuation_depth",
        "rotation_role",
    }
)
TOP_LEVEL_REQUIRED_KEYS = frozenset(
    {
        "tag",
        "welle",
        "audit_only",
        "doc_form_only",
        "layer",
        "rotation_id",
        "rotation_state",
        "issuer_curve",
        "token_format",
        "attenuation_depth_max",
        "active_tokens",
        "rotation_steps",
        "audit_trail_refs",
        "sandbox_boundary",
        "cross_anchors",
    }
)
# REUSE-IgnoreEnd


class VerifyError(Exception):
    """Raised when a Welle-5 capability-token-layer-state invariant fails."""


def _require(condition: bool, invariant_id: str, message: str) -> None:
    if not condition:
        raise VerifyError(f"{invariant_id}: {message}")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_top_level_shape(state: Any) -> None:
    _require(
        isinstance(state, dict),
        "I-0",
        f"state document must be an object, got {type(state).__name__}",
    )
    missing = TOP_LEVEL_REQUIRED_KEYS - set(state.keys())
    _require(
        not missing,
        "I-0",
        f"state document missing required top-level keys: {sorted(missing)!r}",
    )


def _check_tag_and_welle(state: dict) -> None:
    _require(
        state.get("tag") == "Tag-73",
        "I-1",
        f"tag must be 'Tag-73', got {state.get('tag')!r}",
    )
    _require(
        state.get("welle") == "Welle-5",
        "I-1",
        f"welle must be 'Welle-5', got {state.get('welle')!r}",
    )


def _check_audit_only(state: dict) -> None:
    _require(
        state.get("audit_only") is True,
        "I-2",
        "state document must declare 'audit_only: true' "
        "(Tag-73 helper refuses non-audit-only documents)",
    )
    _require(
        state.get("doc_form_only") is True,
        "I-2",
        "state document must declare 'doc_form_only: true'",
    )


def _check_layer(state: dict) -> None:
    _require(
        state.get("layer") == "Layer-3-AIP+Biscuit",
        "I-3",
        f"layer must be 'Layer-3-AIP+Biscuit', got {state.get('layer')!r}",
    )


def _check_rotation_state(state: dict) -> None:
    rs = state.get("rotation_state")
    _require(
        rs in CANONICAL_ROTATION_STATES,
        "I-4",
        f"rotation_state must be one of {CANONICAL_ROTATION_STATES!r}, "
        f"got {rs!r}",
    )


def _check_issuer_curve(state: dict) -> None:
    curve = state.get("issuer_curve")
    _require(
        curve in CANONICAL_CURVES,
        "I-5",
        f"issuer_curve must be one of {CANONICAL_CURVES!r}, got {curve!r}",
    )


def _check_token_format(state: dict) -> None:
    fmt = state.get("token_format")
    _require(
        fmt == CANONICAL_TOKEN_FORMAT,
        "I-6",
        f"token_format must be {CANONICAL_TOKEN_FORMAT!r}, got {fmt!r}",
    )


def _check_attenuation_depth(state: dict) -> None:
    depth = state.get("attenuation_depth_max")
    _require(
        _is_int(depth) and 1 <= depth <= 8,
        "I-7",
        f"attenuation_depth_max must be int in [1,8], got {depth!r}",
    )


def _check_token_record_shape(rec: Any, idx: int) -> None:
    _require(
        isinstance(rec, dict),
        "I-8",
        f"active_tokens[{idx}] must be an object, got {type(rec).__name__}",
    )
    missing = TOKEN_RECORD_ALLOWED_KEYS - set(rec.keys())
    _require(
        not missing,
        "I-8",
        f"active_tokens[{idx}] missing fields: {sorted(missing)!r}",
    )
    extra = set(rec.keys()) - TOKEN_RECORD_ALLOWED_KEYS
    _require(
        not extra,
        "I-16",
        f"active_tokens[{idx}] carries unknown fields: {sorted(extra)!r}",
    )
    _require(
        isinstance(rec.get("token_id"), str) and rec.get("token_id"),
        "I-8",
        f"active_tokens[{idx}].token_id must be a non-empty string",
    )
    _require(
        isinstance(rec.get("issuer_pubkey"), str)
        and rec.get("issuer_pubkey"),
        "I-8",
        f"active_tokens[{idx}].issuer_pubkey must be a non-empty string",
    )
    nb = rec.get("not_before")
    na = rec.get("not_after")
    _require(
        _is_int(nb) and nb >= 0,
        "I-8",
        f"active_tokens[{idx}].not_before must be non-negative int",
    )
    _require(
        _is_int(na) and na >= 0,
        "I-8",
        f"active_tokens[{idx}].not_after must be non-negative int",
    )
    _require(
        nb <= na,
        "I-15",
        f"active_tokens[{idx}]: not_before ({nb}) must be <= "
        f"not_after ({na})",
    )
    depth = rec.get("attenuation_depth")
    _require(
        _is_int(depth) and depth >= 0,
        "I-8",
        f"active_tokens[{idx}].attenuation_depth must be non-negative int",
    )
    role = rec.get("rotation_role")
    _require(
        role in CANONICAL_ROTATION_ROLES,
        "I-8",
        f"active_tokens[{idx}].rotation_role must be one of "
        f"{CANONICAL_ROTATION_ROLES!r}, got {role!r}",
    )


def _check_active_tokens(state: dict) -> None:
    tokens = state.get("active_tokens")
    _require(
        isinstance(tokens, list),
        "I-8",
        f"active_tokens must be a list, got {type(tokens).__name__}",
    )
    for idx, rec in enumerate(tokens):
        _check_token_record_shape(rec, idx)

    rs = state.get("rotation_state")
    if rs in ("rotation-in-progress", "post-rotation-grace"):
        _require(
            len(tokens) >= 1,
            "I-8",
            f"active_tokens must be non-empty in state {rs!r}",
        )
    # Validate role-set in sealed state -- no outgoing allowed.
    if rs == "post-rotation-sealed":
        for idx, rec in enumerate(tokens):
            _require(
                rec.get("rotation_role") != "outgoing",
                "I-11",
                f"active_tokens[{idx}] has rotation_role='outgoing' "
                f"in post-rotation-sealed state",
            )


def _check_overlap_windows(state: dict) -> None:
    rs = state.get("rotation_state")
    tokens = state.get("active_tokens") or []
    outgoing = [t for t in tokens if t.get("rotation_role") == "outgoing"]
    incoming = [t for t in tokens if t.get("rotation_role") == "incoming"]
    if rs == "post-rotation-grace":
        _require(
            outgoing and incoming,
            "I-9",
            "post-rotation-grace requires at least one outgoing and "
            "one incoming token (ADOL overlap semantics)",
        )
        for ot in outgoing:
            for it in incoming:
                _require(
                    ot["not_after"] >= it["not_before"],
                    "I-9",
                    f"post-rotation-grace overlap violated: outgoing "
                    f"{ot['token_id']!r} not_after={ot['not_after']} < "
                    f"incoming {it['token_id']!r} "
                    f"not_before={it['not_before']}",
                )
    if rs == "rotation-in-progress" and outgoing and incoming:
        # Overlap allowed but not strictly required at this state.
        # Verify no incoming starts strictly after an outgoing ends with
        # no gap-coverage: i.e. for each outgoing there exists at least
        # one incoming with not_before <= outgoing.not_after (no orphan
        # gap).  This is the forward-progress mid-rotation invariant.
        for ot in outgoing:
            _require(
                any(
                    it["not_before"] <= ot["not_after"]
                    for it in incoming
                ),
                "I-9",
                f"rotation-in-progress: outgoing {ot['token_id']!r} "
                f"has no overlapping incoming token (orphan gap)",
            )


def _check_rotation_steps(state: dict) -> None:
    steps = state.get("rotation_steps")
    _require(
        isinstance(steps, list),
        "I-10",
        f"rotation_steps must be a list, got {type(steps).__name__}",
    )
    rs = state.get("rotation_state")
    # Pre-rotation: steps may be empty or all planned.
    if rs == "pre-rotation":
        for idx, step in enumerate(steps):
            status = (step or {}).get("status")
            _require(
                status == "planned",
                "I-18",
                f"pre-rotation: rotation_steps[{idx}].status must be "
                f"'planned', got {status!r}",
            )
    # If non-empty, ordering must match canonical sequence.
    if steps:
        kinds = [s.get("step_kind") for s in steps]
        for k in kinds:
            _require(
                k in CANONICAL_STEP_KINDS_ORDER,
                "I-10",
                f"rotation_steps step_kind {k!r} is not canonical "
                f"(allowed: {CANONICAL_STEP_KINDS_ORDER!r})",
            )
        # Strict prefix of canonical order.
        expected_prefix = CANONICAL_STEP_KINDS_ORDER[: len(kinds)]
        _require(
            tuple(kinds) == expected_prefix,
            "I-10",
            f"rotation_steps step_kind order {kinds!r} does not match "
            f"canonical prefix {list(expected_prefix)!r}",
        )
        for idx, step in enumerate(steps):
            _require(
                isinstance(step, dict),
                "I-10",
                f"rotation_steps[{idx}] must be object, got "
                f"{type(step).__name__}",
            )
            _require(
                isinstance(step.get("step_id"), str)
                and step.get("step_id"),
                "I-10",
                f"rotation_steps[{idx}].step_id must be non-empty str",
            )
            _require(
                step.get("status") in CANONICAL_STEP_STATUSES,
                "I-10",
                f"rotation_steps[{idx}].status must be one of "
                f"{CANONICAL_STEP_STATUSES!r}, got {step.get('status')!r}",
            )
    # Post-rotation-sealed: must contain all 5 steps and all status=done.
    if rs == "post-rotation-sealed":
        _require(
            len(steps) == 5,
            "I-11",
            f"post-rotation-sealed must enumerate all 5 rotation_steps, "
            f"got {len(steps)}",
        )
        for idx, step in enumerate(steps):
            _require(
                step.get("status") == "done",
                "I-11",
                f"post-rotation-sealed: rotation_steps[{idx}].status "
                f"must be 'done', got {step.get('status')!r}",
            )


def _check_audit_trail_refs(state: dict) -> None:
    refs = state.get("audit_trail_refs")
    _require(
        isinstance(refs, list),
        "I-12",
        f"audit_trail_refs must be a list, got {type(refs).__name__}",
    )
    _require(
        len(refs) >= 1,
        "I-12",
        "audit_trail_refs must contain at least one WAT-leaf reference",
    )
    for idx, ref in enumerate(refs):
        _require(
            isinstance(ref, str) and WAT_LEAF_RE.match(ref) is not None,
            "I-12",
            f"audit_trail_refs[{idx}] {ref!r} is not a well-formed "
            f"'wat-leaf://<hex-32>' reference",
        )


def _check_sandbox_boundary(state: dict) -> None:
    sb = state.get("sandbox_boundary")
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


def _check_cross_anchors(state: dict) -> None:
    anchors = state.get("cross_anchors")
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


def _check_rotation_id(state: dict) -> None:
    rid = state.get("rotation_id")
    _require(
        isinstance(rid, str) and ROTATION_ID_RE.match(rid) is not None,
        "I-17",
        f"rotation_id must match {ROTATION_ID_RE.pattern!r}, got {rid!r}",
    )


def _check_forward_progress(state: dict) -> None:
    """I-19: incoming.not_after MUST strictly exceed every outgoing.not_after."""
    tokens = state.get("active_tokens") or []
    outgoing = [t for t in tokens if t.get("rotation_role") == "outgoing"]
    incoming = [t for t in tokens if t.get("rotation_role") == "incoming"]
    if not outgoing or not incoming:
        return
    max_outgoing_na = max(t["not_after"] for t in outgoing)
    for it in incoming:
        _require(
            it["not_after"] > max_outgoing_na,
            "I-19",
            f"forward-progress invariant violated: incoming "
            f"{it['token_id']!r} not_after={it['not_after']} is not "
            f"strictly greater than max outgoing not_after "
            f"({max_outgoing_na})",
        )


def verify_state(state: Any) -> None:
    """Validate a Welle-5 capability-token-layer state document.

    Raises ``VerifyError`` with an invariant-tagged message on the
    first failing invariant. Returns ``None`` on success.
    """
    _check_top_level_shape(state)
    _check_tag_and_welle(state)
    _check_audit_only(state)
    _check_layer(state)
    _check_rotation_state(state)
    _check_issuer_curve(state)
    _check_token_format(state)
    _check_attenuation_depth(state)
    _check_rotation_id(state)
    _check_active_tokens(state)
    _check_overlap_windows(state)
    _check_rotation_steps(state)
    _check_audit_trail_refs(state)
    _check_sandbox_boundary(state)
    _check_cross_anchors(state)
    _check_forward_progress(state)


def _fail(msg: str) -> "int":
    sys.stderr.write(
        f"verify_capability_token_layer_state: FAIL: {msg}\n"
    )
    return 1


def main(argv: Iterable[str]) -> int:
    args = list(argv)
    if len(args) != 1:
        return _fail(
            "usage: verify_capability_token_layer_state.py <state.json>"
        )
    path = args[0]
    try:
        with open(path, encoding="utf-8") as handle:
            state = json.load(handle)
    except FileNotFoundError:
        return _fail(f"state document not found: {path!r}")
    except json.JSONDecodeError as exc:
        return _fail(f"state document {path!r} is not valid JSON: {exc}")
    try:
        verify_state(state)
    except VerifyError as exc:
        return _fail(str(exc))
    print(
        "verify_capability_token_layer_state: OK "
        "(Tag-73 Welle-5 capability-token-layer-state conformance, "
        "20 invariants, audit-only)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
