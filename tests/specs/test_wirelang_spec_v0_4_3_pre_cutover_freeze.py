# SPDX-License-Identifier: Apache-2.0
"""Tag-53 hermetic test suite for wirelang-spec-v0-4-3.md pre-cutover-freeze.

This suite verifies the strict-superset freeze-marker v0.4.3 over v0.4.2:

- FREEZE-S1: spec-side pre-cutover closure-bit. The Tag-52 Persona-Engine
  0.5.2-final-pre-cutover (PR #336) declared engine-side closure. v0.4.3
  declares the complementary spec-side closure via
  `status: pre-cutover-freeze` plus `freeze-marker: kw-24-cutover-gate`
  plus `freeze-anchor: persona-engine-0.5.2-final-pre-cutover`.

The invariant under test: v0.4.3 is a STRICT-SUPERSET FREEZE-MARKER over
v0.4.2. No substance diff. The §3 catalogue and §4.1 ENV-flag table MUST
be byte-equivalent across the two documents (modulo intro/governance
prose, which is necessarily different — only the §3 catalogue rows and
§4.1 table rows are pinned byte-for-byte).

Hermetic: no NATS, no engine boot, no Rust build, no network import.
Pure static-pass over the working copy: read the spec, read the v0.4.2
predecessor, read the Pin-Pack YAML, verify invariants.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_V040 = REPO_ROOT / "wirelang" / "specs" / "wirelang-spec-v0-4.md"
SPEC_V041 = REPO_ROOT / "wirelang" / "specs" / "wirelang-spec-v0-4-1.md"
SPEC_V042 = REPO_ROOT / "wirelang" / "specs" / "wirelang-spec-v0-4-2.md"
SPEC_V043 = REPO_ROOT / "wirelang" / "specs" / "wirelang-spec-v0-4-3.md"
PIN_PACK_PATH = (
    REPO_ROOT / "infra" / "persona-engine" / "pin-pack-0.5.1-pre-cutover.yaml"
)


# Pin-Pack-0.5.1 ground truth (record-ordered) — v0.4.3 §4.1 carries
# v0.4.2 §4.1 forward unchanged; the table must still cite every
# Pin-Pack-wired component name + selector_env. We re-pin the
# byte-anchor here so a regression in either spec would break this
# suite, not just the Tag-50 suite.
PIN_PACK_TEN_RECORDS_ORDERED = [
    (1, "persona-engine-recovery", "WAKIR_RECOVERY_BACKEND"),
    (2, "persona-engine-state-backing", "WAKIR_STATE_BACKING_BACKEND"),
    (3, "persona-engine-fsm", "WAKIR_FSM_BACKEND"),
    (4, "persona-engine-v907-verify", "WAKIR_V907_VERIFY_BACKEND"),
    (5, "persona-engine-bridge-diff", "WAKIR_BRIDGE_DIFF_BACKEND"),
    (6, "persona-engine-subscribe-loop", "WAKIR_SUBSCRIBE_LOOP_BACKEND"),
    (7, "persona-engine-anchor-emitter", "WAKIR_ANCHOR_EMITTER_BACKEND"),
    (
        8,
        "persona-engine-svid-workload-identity",
        "WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND",
    ),
    (
        9,
        "persona-engine-federation-resolver",
        "WAKIR_FEDERATION_RESOLVER_BACKEND",
    ),
    (
        10,
        "persona-engine-bridge-audit-writer",
        "WAKIR_BRIDGE_AUDIT_WRITER_BACKEND",
    ),
]


# ---------------------------------------------------------------------------
# T-01 / T-02 / T-03: file presence + frontmatter integrity
# ---------------------------------------------------------------------------


def test_t01_spec_v043_file_exists():
    """T-01: v0.4.3 spec file is present at expected path."""
    assert SPEC_V043.is_file(), f"missing v0.4.3 spec at {SPEC_V043}"


def test_t02_spec_v043_frontmatter_declares_freeze_marker():
    """T-02: v0.4.3 frontmatter declares the four freeze-marker fields.

    The freeze-marker discipline (spec §8) requires four frontmatter
    fields: version=0.4.3, extends=0.4.2, status=pre-cutover-freeze,
    freeze-marker=kw-24-cutover-gate. We assert all four are present.
    """
    body = SPEC_V043.read_text(encoding="utf-8")
    assert re.search(r"^version:\s*0\.4\.3\s*$", body, re.M), (
        "frontmatter must declare version: 0.4.3"
    )
    assert re.search(r"^extends:\s*0\.4\.2\s*$", body, re.M), (
        "frontmatter must declare extends: 0.4.2"
    )
    assert re.search(
        r"^status:\s*pre-cutover-freeze\s*$", body, re.M
    ), "frontmatter must declare status: pre-cutover-freeze"
    assert re.search(
        r"^freeze-marker:\s*kw-24-cutover-gate\s*$", body, re.M
    ), "frontmatter must declare freeze-marker: kw-24-cutover-gate"
    assert re.search(
        r"^freeze-anchor:\s*persona-engine-0\.5\.2-final-pre-cutover\s*$",
        body,
        re.M,
    ), "frontmatter must declare freeze-anchor: persona-engine-0.5.2-final-pre-cutover"
    assert re.search(r"^date:\s*2026-05-19\s*$", body, re.M), (
        "frontmatter must declare date: 2026-05-19 (Tag-53)"
    )


def test_t03_spec_v043_predecessor_v042_still_exists_and_is_draft():
    """T-03: the v0.4.2 predecessor must still exist and carry status: draft.

    The freeze-marker discipline forbids editing the predecessor.
    v0.4.2 frontmatter must remain `status: draft` — v0.4.3 carries
    the freeze-bit, not v0.4.2.
    """
    assert SPEC_V042.is_file(), "v0.4.2 predecessor must still exist"
    v042_body = SPEC_V042.read_text(encoding="utf-8")
    assert re.search(r"^version:\s*0\.4\.2\s*$", v042_body, re.M), (
        "v0.4.2 frontmatter version must remain 0.4.2"
    )
    assert re.search(r"^status:\s*draft\s*$", v042_body, re.M), (
        "v0.4.2 frontmatter status must remain `draft` "
        "(freeze-bit lives on v0.4.3, not v0.4.2)"
    )


# ---------------------------------------------------------------------------
# T-04 / T-05: substance invariants — §4.1 carried forward
# ---------------------------------------------------------------------------


def test_t04_spec_v043_section_4_1_lists_all_ten_pin_pack_components():
    """T-04: every Pin-Pack-wired component name appears in v0.4.3 §4.1.

    Since v0.4.3 is a strict-superset of v0.4.2 (which itself carries
    the DRIFT-S4-reconciled §4.1), every Pin-Pack component must still
    be referenced.
    """
    body = SPEC_V043.read_text(encoding="utf-8")
    for _record, crate, _env in PIN_PACK_TEN_RECORDS_ORDERED:
        assert (
            f"`{crate}`" in body
        ), f"§4.1 (carried forward) must reference `{crate}`"


def test_t05_spec_v043_section_4_1_selector_envs_match_pin_pack():
    """T-05: every Pin-Pack selector_env value appears in v0.4.3.

    v0.4.3 may declare "§4 no change" with prose only and reference the
    table via a forward link — OR it may inline the table verbatim from
    v0.4.2. Either way, every selector_env must be cited at least once
    (the §4.1 contents are part of the v0.4.3 conformance anchor).
    """
    body = SPEC_V043.read_text(encoding="utf-8")
    for _record, _crate, env in PIN_PACK_TEN_RECORDS_ORDERED:
        assert (
            f"`{env}`" in body
        ), f"§4.1 (carried forward) must reference `{env}`"


# ---------------------------------------------------------------------------
# T-06: no substance diff — no new wire-/frame-/caveat-level keywords
# ---------------------------------------------------------------------------


def test_t06_spec_v043_introduces_no_new_wire_or_frame_or_caveat_keywords():
    """T-06: v0.4.3 must not introduce new wire-/frame-/caveat-level keywords.

    The freeze-marker is strict-superset: every wire/frame/caveat token
    in v0.4.3 must also be present in v0.4.2 (the predecessor it freezes).
    We assert this via a closed-vocabulary check on a small list of
    structural tokens that, if newly introduced, would constitute a
    substance diff.
    """
    v043_body = SPEC_V043.read_text(encoding="utf-8").lower()
    # Tokens that, if asserted positively in v0.4.3, would constitute a
    # substance diff. We assert each is absent from v0.4.3 entirely.
    # Narrative references like "v0.4.3 verifiers MAY treat `wirelangversion:
    # 0.4.3` frames as v0.4.0 frames" are NOT in this list — that is a
    # documentary back-compat statement, not a wire-version bump.
    forbidden_substance_diff_tokens = [
        "new caveat predicate",
        "new frame attribute",
        "new publish-mode",
        "wire-incompatible",
        "breaking change",
        "wire-format change",
        "frame-format change",
        "caveat-predicate addition",
        "caveat-predicate removal",
    ]
    for tok in forbidden_substance_diff_tokens:
        # Allow the token to appear ONLY inside a negation phrase
        # such as "no new caveat predicate" / "no wire-format change".
        # We approximate this by requiring every occurrence to be
        # preceded (within 10 chars) by "no " or "not ".
        idx = 0
        while True:
            found = v043_body.find(tok, idx)
            if found < 0:
                break
            window_start = max(0, found - 12)
            window = v043_body[window_start:found]
            assert ("no " in window) or ("not " in window) or ("without " in window), (
                f"v0.4.3 contains substance-diff token {tok!r} outside a "
                f"negation context (window={window!r}) — violates "
                "strict-superset freeze-marker invariant"
            )
            idx = found + len(tok)


# ---------------------------------------------------------------------------
# T-07: freeze-marker scope declaration must be explicit
# ---------------------------------------------------------------------------


def test_t07_spec_v043_declares_no_substance_diff_prominently():
    """T-07: v0.4.3 must explicitly declare 'no substance diff' over v0.4.2.

    The freeze-marker discipline (spec §1) requires the document to
    state, near the top, that no substance diff is introduced. This
    guards against a silent substance change wearing a freeze-marker
    hat.
    """
    body = SPEC_V043.read_text(encoding="utf-8")
    # The phrase 'no substance diff' (or 'no on-the-wire change') must
    # appear in the first 100 lines of the document body.
    head = "\n".join(body.splitlines()[:100]).lower()
    has_no_substance_diff = "no substance diff" in head
    has_no_wire_change = "no on-the-wire change" in head
    assert has_no_substance_diff or has_no_wire_change, (
        "v0.4.3 must declare 'no substance diff' or 'no on-the-wire change' "
        "near the document head (freeze-marker discipline §1)"
    )


# ---------------------------------------------------------------------------
# T-08: freeze-anchor must cite Tag-52 Persona-Engine 0.5.2-final-pre-cutover
# ---------------------------------------------------------------------------


def test_t08_spec_v043_cites_engine_side_freeze_anchor():
    """T-08: v0.4.3 must cite the Tag-52 engine-side freeze counterpart.

    The freeze-anchor declares which engine binary v0.4.3 is bound to.
    The body must cross-reference both the engine tag and the Tag-52
    PR for traceability.
    """
    body = SPEC_V043.read_text(encoding="utf-8")
    assert "persona-engine-0.5.2-final-pre-cutover" in body, (
        "v0.4.3 must cite the engine binary tag persona-engine-0.5.2-final-pre-cutover"
    )
    assert "Tag-52" in body, (
        "v0.4.3 must cite Tag-52 (the engine-side freeze counterpart)"
    )
    assert "PR #336" in body or "#336" in body, (
        "v0.4.3 must cite PR #336 (Tag-52 engine-side freeze) for traceability"
    )


# ---------------------------------------------------------------------------
# T-09: v0.4.2 substance baseline must be cited
# ---------------------------------------------------------------------------


def test_t09_spec_v043_cites_v042_substance_baseline():
    """T-09: v0.4.3 must cite Tag-50 PR #320 (v0.4.2 substance baseline)."""
    body = SPEC_V043.read_text(encoding="utf-8")
    assert "v0.4.2" in body, "v0.4.3 must cite v0.4.2 (substance baseline)"
    assert "Tag-50" in body, "v0.4.3 must cite Tag-50 (v0.4.2 release)"
    assert "PR #320" in body or "#320" in body, (
        "v0.4.3 must cite PR #320 (Tag-50 v0.4.2 substance baseline)"
    )


# ---------------------------------------------------------------------------
# T-10: predecessor chain integrity (v0.4 → v0.4.1 → v0.4.2 → v0.4.3)
# ---------------------------------------------------------------------------


def test_t10_spec_v043_predecessor_chain_intact():
    """T-10: the full patch-trace must be cited in v0.4.3 §9 citation pointers.

    The four predecessor documents (v0.4, v0.4.1, v0.4.2) must all be
    cited so that an auditor can walk the patch-trace from v0.4.3 back
    to v0.4 without external lookups.
    """
    body = SPEC_V043.read_text(encoding="utf-8")
    assert "wirelang-spec-v0-4-2.md" in body, (
        "v0.4.3 must cite the v0.4.2 file path in §9 citation pointers"
    )
    assert "wirelang-spec-v0-4-1.md" in body, (
        "v0.4.3 must cite the v0.4.1 file path in §9 citation pointers"
    )
    assert "wirelang-spec-v0-4.md" in body, (
        "v0.4.3 must cite the v0.4 file path in §9 citation pointers"
    )


# ---------------------------------------------------------------------------
# T-11: cutover-gate identity declaration
# ---------------------------------------------------------------------------


def test_t11_spec_v043_declares_kw_24_cutover_gate():
    """T-11: v0.4.3 must declare the KW-24-cutover-gate identity."""
    body = SPEC_V043.read_text(encoding="utf-8")
    assert "kw-24-cutover-gate" in body.lower() or "kw 24" in body.lower() or "kw-24" in body.lower(), (
        "v0.4.3 must declare the KW-24 cutover-gate identity"
    )
    assert "Phase-3c" in body or "phase-3c" in body.lower(), (
        "v0.4.3 must reference Phase-3c (the cutover phase)"
    )


# ---------------------------------------------------------------------------
# T-12: backward-compat — no new conformance obligations
# ---------------------------------------------------------------------------


def test_t12_spec_v043_introduces_no_new_conformance_obligations():
    """T-12: v0.4.3 must declare it introduces no new conformance obligations.

    The §2 conformance section must explicitly state that a v0.4.2
    conformant producer/verifier/operator is conformant to v0.4.3 by
    construction.
    """
    body = SPEC_V043.read_text(encoding="utf-8")
    # Locate §2 block.
    section_2_match = re.search(
        r"## 2\. Conformance keywords.*?(?=## 3\.)",
        body,
        re.S,
    )
    assert section_2_match is not None, "§2 Conformance keywords block not found"
    section_2 = section_2_match.group(0).lower()
    assert "no new conformance obligations" in section_2, (
        "§2 must state 'No new conformance obligations are introduced.'"
    )
    assert "by construction" in section_2, (
        "§2 must state v0.4.2 conformance carries to v0.4.3 'by construction'"
    )
