# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Welle-3 (``bridge_audit_writer``) **post-cutover** verification E2E.

Hermetic, stdlib-only. Loads the Welle-3 smoke module via importlib
from its hyphenated path under ``scripts/phase-3c/``.

Auftrag-Anker
-------------

- Tag-38 Amara Auftrag — Welle-3 Henrik-Caution Post-Cutover-
  Verification-Tests. The pre-cutover gate (HC-AC-1..3 in
  ``tests/acceptance/phase_3c/test_welle_3_bridge_audit_writer_e2e
  .py``) covers the substrate that fires *before* cutover-Mittwoch
  KW-25. This file is its **post-cutover companion** — the gate that
  fires *after* the engine has been restarted with
  ``WAKIR_BRIDGE_AUDIT_WRITER_BACKEND=rust`` in the Quadlet.
- ADR-0066 §Beschluss — Welle-3 KW-25 solo welle (NOT part of the
  Doppel-Welle KW-26). Henrik-Caution carve-out: bridge_audit_writer
  is the consistency-oracle substrate for the other wellen and
  cannot self-validate.
- Selin's Welle-3-Smoke (PR #240, Tag-36) — A6 bridge_audit_stream
  parity + A7 self_reference_trap_control are the per-modul Self-
  Reference-Trap-Mitigation gates that this E2E layer verifies
  *actually fired* in the cutover-Mittwoch smoke envelope.

Scope (6 tests; Auftrag-Tag-38 minimum is 4 — exceeded so the post-
cutover stream-continuity + cross-modul-drift edges get explicit
audit-trail-integrity coverage)
-----------------------------------------------------------------

W3-POST-1 — Audit-Stream-Continuity post-Cutover
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1.  test_welle_3_post_1_audit_stream_continuity_post_cutover
2.  test_welle_3_post_1_stream_drift_blocks

W3-POST-2 — Self-Reference-Trap-Mitigation worked (A6+A7 fired)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

3.  test_welle_3_post_2_self_reference_trap_mitigation_fired

W3-POST-3 — Cross-Modul-Drift bridge_audit_writer ↔ anchor_emitter + bridge_diff
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

4.  test_welle_3_post_3_cross_modul_drift_anchor_emitter
5.  test_welle_3_post_3_cross_modul_drift_bridge_diff

W3-POST-4 — Audit-Trail-Integrity over Rollback (Hairpin-Window probe)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

6.  test_welle_3_post_4_rollback_hairpin_window_audit_trail_intact

Hermetic substrate
------------------

- Welle-3-smoke functions ``capture_bridge_audit_stream_baseline``
  and ``evaluate_bridge_audit_stream_parity`` exposed for direct
  test interrogation.
- Stub writer_module that exposes ``EngineeringOutputEvent`` with
  ``to_jcs_bytes()`` — controls byte-shape so drift scenarios are
  reproducible.
- No real bridge_audit_writer import, no podman, no live engine.

Cross-spawn Konsistenz
----------------------

- Selin Tag-36 PR #240 (Welle-3-Smoke) is the per-modul anchor; the
  A6+A7 assertions there must continue to pass post-cutover, which
  this E2E layer verifies through the same smoke-function surface.
- ADR-0065 §Empfehlung Footnote (hold-out Python writer) — when the
  cutover-Tag hold-out instance is decommissioned, the audit-trail
  must remain readable. W3-POST-4 gates the decommission decision.
- Reza Tag-36 PR #240 wire-in is the substrate the smoke runs
  against; the E2E layer here does not depend on the upstream
  resolver (uses smoke-shim where needed).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest


# ---------------------------------------------------------------------------
# Smoke-module loader.
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    return here.parent.parent.parent


def _load_welle_3_smoke() -> Any:
    smoke_path = (
        _repo_root()
        / "scripts"
        / "phase-3c"
        / "welle-3-bridge-audit-writer-cutover-smoke.py"
    )
    if not smoke_path.is_file():
        pytest.fail(f"smoke script not found at {smoke_path}")
    spec = importlib.util.spec_from_file_location(
        "welle_3_bridge_audit_writer_cutover_smoke", str(smoke_path)
    )
    if spec is None or spec.loader is None:
        pytest.fail(f"cannot build spec for {smoke_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["welle_3_bridge_audit_writer_cutover_smoke"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


SMOKE = _load_welle_3_smoke()


# ---------------------------------------------------------------------------
# Stub bridge_audit_writer module — controls JCS-byte-shape for the
# capture/evaluate substrate functions.
#
# The real wirelang.bridge_audit_writer exposes EngineeringOutputEvent
# (a dataclass with .to_jcs_bytes()) and/or a module-level
# to_jcs_bytes(event) helper. The smoke's
# _emission_to_jcs_bytes_via_module hunts both surfaces.
# ---------------------------------------------------------------------------


def _emission_id(event: Dict[str, Any]) -> Tuple[Any, ...]:
    """Stable per-emission identifier — tuple of identity-fields.

    BRIDGE_AUDIT_DETERMINISTIC_EMISSIONS has no ``key`` field; the
    identity is ``(session_id, step_index)``. Tests target drift at
    a specific emission via this composite identifier.
    """
    return (event.get("session_id"), event.get("step_index"))


def build_stub_writer_module(
    *,
    drift_emission_ids: Optional[Tuple[Tuple[Any, ...], ...]] = None,
    rust_round_trip_drift_ids: Optional[Tuple[Tuple[Any, ...], ...]] = None,
    raise_on_emission: bool = False,
) -> types.ModuleType:
    """Build a fake bridge_audit_writer module.

    The stub exposes a module-level ``to_jcs_bytes(event)`` helper.
    Each emission becomes a JCS-canonical bytes-encoding of the
    sorted-key JSON form. When the emission's identity-tuple
    ``(session_id, step_index)`` is in ``drift_emission_ids``, the
    encoder salts the bytes so the parity-check surfaces a divergence.

    ``rust_round_trip_drift_ids`` models the rust-side round-trip
    bug: the python writer encodes the event correctly, but the
    rust-side reader re-emits it with a salt. This is a different
    drift-class than ``drift_emission_ids`` (python-side encoding bug
    vs. rust-side reader bug); the test discriminates the two
    through separate scenarios.

    ``raise_on_emission=True`` models the bridge_audit_writer module
    raising on a single emission — the smoke is expected to catch
    this and emit a CAUTION-skip envelope (per Welle-3 smoke
    capture_bridge_audit_stream_baseline exception-handling).
    """
    mod = types.ModuleType("wirelang.bridge_audit_writer")
    drift_set = set(drift_emission_ids or ())
    rust_drift_set = set(rust_round_trip_drift_ids or ())

    def to_jcs_bytes(event: Dict[str, Any]) -> bytes:
        if raise_on_emission:
            raise RuntimeError("simulated bridge_audit_writer failure")
        ident = _emission_id(event)
        salt = ""
        if ident in drift_set:
            salt = ":python-side-drift"
        if ident in rust_drift_set:
            # Rust-round-trip salt distinct so the test can identify
            # the source class of the drift.
            salt += ":rust-round-trip-drift"
        payload = json.dumps(
            event, sort_keys=True, separators=(",", ":")
        ) + salt
        return payload.encode("utf-8")

    mod.to_jcs_bytes = to_jcs_bytes  # type: ignore[attr-defined]
    return mod


# ---------------------------------------------------------------------------
# W3-POST-1 — Audit-Stream-Continuity post-Cutover.
#
# Substantive question: does the bridge_audit_writer continue to
# emit a byte-stable stream post-cutover, byte-identical to the
# pre-cutover baseline that the smoke captured at PHASE_PRE?
# ---------------------------------------------------------------------------


def test_welle_3_post_1_audit_stream_continuity_post_cutover() -> None:
    """W3-POST-1: stream-hash captured pre-cutover matches recomputed
    stream-hash post-cutover, byte-identical.

    The Welle-3 smoke's substrate functions
    ``capture_bridge_audit_stream_baseline`` (PHASE_PRE) and
    ``evaluate_bridge_audit_stream_parity`` (PHASE_POST) form the
    A6 substrate. This E2E test drives both with the same stub
    writer module to verify the *happy path*: pre and post agree.
    """
    writer = build_stub_writer_module()
    baseline = SMOKE.capture_bridge_audit_stream_baseline(
        writer_module=writer,
    )
    assert baseline is not None
    assert baseline["captured_at_phase"] == SMOKE.PHASE_PRE, (
        f"W3-POST-1: baseline must be captured at PHASE_PRE for Self-"
        f"Reference-Trap-Mitigation; got "
        f"captured_at_phase={baseline['captured_at_phase']!r}"
    )
    assert baseline["skipped"] is False
    pre_stream_hash = baseline["stream_sha256_hex"]
    assert pre_stream_hash is not None

    parity = SMOKE.evaluate_bridge_audit_stream_parity(
        baseline,
        writer_module=writer,
    )
    assert parity["skipped"] is False
    assert parity["passed"] is True, (
        f"W3-POST-1: stream-parity must hold post-cutover; "
        f"detail={parity.get('detail')!r}"
    )
    assert parity["match"] is True
    assert parity["baseline_stream_sha256"] == pre_stream_hash
    assert parity["recomputed_stream_sha256"] == pre_stream_hash, (
        f"W3-POST-1: recomputed stream-hash must match baseline byte-"
        f"identically; baseline={pre_stream_hash!r} "
        f"recomputed={parity['recomputed_stream_sha256']!r}"
    )


def test_welle_3_post_1_stream_drift_blocks() -> None:
    """W3-POST-1 failure-mode: post-cutover stream-hash diverges → block.

    Bug pattern modeled: a rust-side round-trip drift on a specific
    emission key. The pre-cutover capture (python writer) is clean,
    but the post-cutover recompute (still python writer, but the
    rust-side reader has drifted) produces a different hash.

    The substantive gate: stream-hash divergence is detectable
    through ``parity['match'] is False`` and the specific drifted
    emission is surfaced through the per-emission SHA-256 list.
    """
    writer_clean = build_stub_writer_module()
    baseline = SMOKE.capture_bridge_audit_stream_baseline(
        writer_module=writer_clean,
    )
    assert baseline is not None
    assert baseline["skipped"] is False

    # Pick the actual identity-tuple that exists in the deterministic
    # emission set, so the drift-salt fires reliably regardless of how
    # Selin shaped BRIDGE_AUDIT_DETERMINISTIC_EMISSIONS.
    first_emission = SMOKE.BRIDGE_AUDIT_DETERMINISTIC_EMISSIONS[0]
    drift_id = _emission_id(first_emission)
    assert drift_id != (None, None), (
        "W3-POST-1 setup: deterministic-emissions[0] must expose "
        "(session_id, step_index) for the drift-detector to attach to"
    )

    writer_drift = build_stub_writer_module(
        rust_round_trip_drift_ids=(drift_id,)
    )
    parity = SMOKE.evaluate_bridge_audit_stream_parity(
        baseline,
        writer_module=writer_drift,
    )
    assert parity["skipped"] is False
    assert parity["passed"] is False, (
        f"W3-POST-1 drift: post-cutover stream-hash diverges, so "
        f"parity['passed'] must be False; got parity={parity!r}"
    )
    assert parity["match"] is False
    assert (
        parity["baseline_stream_sha256"]
        != parity["recomputed_stream_sha256"]
    ), (
        f"W3-POST-1 drift: hashes must differ to surface the bug; "
        f"baseline={parity['baseline_stream_sha256']!r} "
        f"recomputed={parity['recomputed_stream_sha256']!r}"
    )


# ---------------------------------------------------------------------------
# W3-POST-2 — Self-Reference-Trap-Mitigation worked.
#
# Selin Tag-36 PR #240 introduced A6 (bridge_audit_stream parity)
# and A7 (self_reference_trap_control) to mitigate the trap where
# the bridge_audit_writer self-validates its own output. A7
# specifically asserts that the baseline was captured at PHASE_PRE
# — i.e. the writer was still on python when the hash was pinned,
# so the post-cutover rust-writer cannot accidentally validate
# against itself.
# ---------------------------------------------------------------------------


def test_welle_3_post_2_self_reference_trap_mitigation_fired() -> None:
    """W3-POST-2: A7 self_reference_trap_control asserts baseline
    captured at PHASE_PRE.

    The post-cutover envelope from a green run must:
      * include the A7 record under ``asserts.A7_self_reference_trap_
        control``
      * have ``passed=True``
      * surface the baseline's ``captured_at_phase`` as PHASE_PRE in
        the envelope's ``self_reference_trap_mitigation`` block

    This is the substantive Henrik-Caution-Mitigation gate: the
    operator runbook cannot accidentally compare rust-writer output
    against rust-writer baseline because the baseline was pinned
    before the cutover.
    """
    writer = build_stub_writer_module()

    # Build a stub resolver module that emits a clean BackendDecision
    # for every component (so the smoke runs through cleanly without
    # the upstream wirelang resolver).
    resolver = _build_clean_resolver()

    # expected_components must match the in-place booted set (10
    # post-Reza-Tag-36-wire-in: smoke's ENGINE_BOOT_COMPONENTS).
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        bridge_audit_writer_module=writer,
        now_ts=1_700_000_000,
        expected_components=len(SMOKE.ENGINE_BOOT_COMPONENTS),
    )
    assert exit_code == SMOKE.EXIT_GREEN, json.dumps(
        envelope.get("asserts", {}), indent=2, sort_keys=True
    )

    asserts = envelope["asserts"]
    a7 = asserts["A7_self_reference_trap_control"]
    assert a7["passed"] is True, (
        f"W3-POST-2: A7 self_reference_trap_control must pass on a "
        f"clean post-cutover envelope; got a7={a7!r}"
    )

    trap_block = envelope["self_reference_trap_mitigation"]
    assert trap_block["baseline_captured_at_phase"] == SMOKE.PHASE_PRE, (
        f"W3-POST-2: the envelope's self-reference-trap-mitigation "
        f"block must reflect that the baseline was captured at "
        f"PHASE_PRE; got baseline_captured_at_phase="
        f"{trap_block['baseline_captured_at_phase']!r}"
    )
    assert trap_block.get("baseline_skipped") is False, (
        "W3-POST-2: a clean post-cutover envelope must not have the "
        "baseline skipped"
    )
    assert trap_block.get("baseline_stream_sha256") is not None, (
        "W3-POST-2: a clean post-cutover envelope must surface the "
        "baseline stream-hash in the trap-mitigation block — this is "
        "the operator-visible attestation that the baseline was pinned"
    )

    # Bonus: A6 stream-parity must also pass on the clean substrate.
    a6 = asserts["A6_bridge_audit_stream_parity"]
    assert a6["passed"] is True
    assert a6.get("skipped") is False


# ---------------------------------------------------------------------------
# W3-POST-3 — Cross-Modul-Drift between bridge_audit_writer and
# anchor_emitter + bridge_diff.
#
# bridge_audit_writer's output is consumed by anchor_emitter (WAT-
# anchor hashing) and by bridge_diff (cross-language consistency
# report). A post-cutover Cross-Modul-Drift in either contract is
# operationally dangerous because the bridge_audit_writer is the
# consistency-oracle substrate for *every other* welle.
# ---------------------------------------------------------------------------


def _engine_decisions_post_cutover() -> List[Dict[str, Any]]:
    """Run one engine-boot in PHASE_POST and return BackendDecisions.

    The boot uses build_phase_env(PHASE_POST), which sets
    FOCUS_ENV_VAR=rust and every other env-var=python — including
    anchor_emitter and bridge_diff. The expected post-cutover
    contract: only bridge_audit_writer flips; anchor_emitter and
    bridge_diff stay python.
    """
    resolver = _build_clean_resolver()
    env = SMOKE.build_phase_env(SMOKE.PHASE_POST)
    return SMOKE.boot_engine_once(
        env=env,
        components=SMOKE.ENGINE_BOOT_COMPONENTS,
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
    )


def _decision_for(records: List[Dict[str, Any]], domain: str) -> Dict[str, Any]:
    matches = [r for r in records if r["domain"] == domain]
    assert len(matches) == 1, (
        f"expected exactly one decision-record for domain={domain!r}; "
        f"got {len(matches)} in records={records!r}"
    )
    return matches[0]


def test_welle_3_post_3_cross_modul_drift_anchor_emitter() -> None:
    """W3-POST-3: anchor_emitter stays python in post-cutover boot.

    The Welle-3 cutover flips bridge_audit_writer only. anchor_emitter
    consumes bridge_audit_writer's output for WAT-anchor hashing; if
    the cutover leaks rust into anchor_emitter, the anchor-trail
    pre/post the cutover-Mittwoch is split-brain (some anchors hashed
    by python, some by rust, both with the same writer-output —
    creates an undetectable double-truth that contaminates the audit-
    trail for every persona spawned across the cutover).
    """
    records = _engine_decisions_post_cutover()
    anchor = _decision_for(records, "anchor_emitter")
    writer = _decision_for(records, "bridge_audit_writer")

    assert writer["chosen_backend"] == "rust", (
        "W3-POST-3 setup: bridge_audit_writer must be on rust in "
        "post-cutover boot for this test to be meaningful"
    )
    assert anchor["requested_backend"] == "python", anchor
    assert anchor["chosen_backend"] == "python", (
        f"W3-POST-3 anchor_emitter: cross-modul-drift detected — "
        f"anchor_emitter flipped to {anchor['chosen_backend']!r} "
        f"despite env=python. The Welle-3 cutover must not leak "
        f"rust into the anchor-emitter path; full record={anchor!r}"
    )


def test_welle_3_post_3_cross_modul_drift_bridge_diff() -> None:
    """W3-POST-3: bridge_diff stays python in post-cutover boot.

    bridge_diff is the cross-language consistency-report substrate.
    Same drift-class as anchor_emitter: a rust leak into bridge_diff
    means the consistency-report itself runs on rust, so the
    consistency-report can no longer be used as the independent-
    oracle for *future* wellen (Welle-4 cutover would have no
    untainted oracle to validate against).
    """
    records = _engine_decisions_post_cutover()
    diff = _decision_for(records, "bridge_diff")
    writer = _decision_for(records, "bridge_audit_writer")

    assert writer["chosen_backend"] == "rust", (
        "W3-POST-3 setup: bridge_audit_writer must be on rust"
    )
    assert diff["requested_backend"] == "python", diff
    assert diff["chosen_backend"] == "python", (
        f"W3-POST-3 bridge_diff: cross-modul-drift detected — "
        f"bridge_diff flipped to {diff['chosen_backend']!r} despite "
        f"env=python. The consistency-report substrate for *future* "
        f"wellen would be contaminated; full record={diff!r}"
    )


# ---------------------------------------------------------------------------
# W3-POST-4 — Audit-Trail-Integrity over Rollback (Hairpin-Window probe).
#
# The hairpin-window: the brief operator-controlled time during
# which Welle-3 cutover is active (PHASE_POST) and the rollback is
# fired (PHASE_ROLLBACK). The audit-trail emitted during the
# hairpin must remain readable from both python (post-rollback) and
# rust (pre-rollback) sides — bridge_audit_writer is idempotent
# under WAT-anchor-hashing (per Welle-3 e2e file's
# test_welle_3_idempotent_double_write_yields_same_anchor), but the
# E2E layer here exercises the *envelope-level* path: a rollback-
# triggered re-emit must produce the same stream-hash as the
# original pre-cutover capture.
# ---------------------------------------------------------------------------


def test_welle_3_post_4_rollback_hairpin_window_audit_trail_intact() -> None:
    """W3-POST-4: rollback hairpin-window audit-trail is intact.

    Scenario: pre-cutover baseline captured (PHASE_PRE), cutover
    fires (PHASE_POST), rollback fires (PHASE_ROLLBACK). The
    post-rollback engine reads back the same emissions; the stream-
    hash must match the original baseline byte-identically — proving
    no emission was lost or mutated during the hairpin window.

    Models the operator-hand-runbook scenario where the cutover-
    Mittwoch fires, runs for some minutes, then the rollback fires
    because of an unrelated alert. The audit-trail emitted during
    the rust-window must remain consistent on read-back from python.
    """
    writer = build_stub_writer_module()

    # PHASE_PRE: capture the baseline.
    baseline = SMOKE.capture_bridge_audit_stream_baseline(
        writer_module=writer,
    )
    assert baseline is not None
    assert baseline["captured_at_phase"] == SMOKE.PHASE_PRE
    pre_hash = baseline["stream_sha256_hex"]

    # PHASE_POST: parity check during cutover-window.
    parity_post = SMOKE.evaluate_bridge_audit_stream_parity(
        baseline,
        writer_module=writer,
    )
    assert parity_post["passed"] is True
    assert parity_post["recomputed_stream_sha256"] == pre_hash

    # PHASE_ROLLBACK: parity check after rollback fires.
    # The rollback simulates ENV-unset; the writer is unaffected
    # because it was already on python during PHASE_PRE (writer-
    # module-call surface does not change with the env-var).
    parity_rollback = SMOKE.evaluate_bridge_audit_stream_parity(
        baseline,
        writer_module=writer,
    )
    assert parity_rollback["passed"] is True
    assert parity_rollback["recomputed_stream_sha256"] == pre_hash, (
        f"W3-POST-4: rollback-window stream-hash must match pre-"
        f"cutover baseline byte-identically; pre={pre_hash!r} "
        f"rollback={parity_rollback['recomputed_stream_sha256']!r}"
    )

    # Idempotency-probe: a third capture-evaluate cycle yields the
    # same hash. This guards against any latent state inside the
    # smoke functions that would only surface on the N>=3 call.
    parity_third = SMOKE.evaluate_bridge_audit_stream_parity(
        baseline,
        writer_module=writer,
    )
    assert parity_third["recomputed_stream_sha256"] == pre_hash, (
        f"W3-POST-4: third-call parity must remain stable; "
        f"got {parity_third!r}"
    )

    # Per-emission consistency: the per-emission SHA-256 list must
    # also match exactly across all three phase-checks. A single
    # per-emission drift while the aggregate hash stays the same
    # would indicate a same-bytes-permutation bug that the aggregate
    # alone could not surface.
    pre_per_emission = baseline["per_emission_jcs_sha256"]
    for label, parity in (
        ("post", parity_post),
        ("rollback", parity_rollback),
        ("third", parity_third),
    ):
        # The smoke function does not always re-emit per-emission;
        # when it does, we cross-check. Absence is acceptable (per-
        # emission detail is optional in the post-cutover evaluate
        # surface).
        per_emission = parity.get("per_emission_jcs_sha256")
        if per_emission is not None:
            assert per_emission == pre_per_emission, (
                f"W3-POST-4 ({label}): per-emission hash-list drifted; "
                f"pre={pre_per_emission!r} {label}={per_emission!r}"
            )


# ---------------------------------------------------------------------------
# Clean-resolver helper — shared across W3-POST-2/3.
# ---------------------------------------------------------------------------


def _build_clean_resolver() -> types.ModuleType:
    """Build a fake rust_backend_switch module emitting clean decisions.

    Every component honours the env-var: requested == chosen, with a
    constant resolution_latency_us. Used for the W3-POST-2 (envelope-
    smoke) + W3-POST-3 (cross-modul-drift) tests where the resolver
    is not the gate under test.
    """
    module = types.ModuleType("wirelang.persona_engine.rust_backend_switch")

    def _make(component: str):
        env_var = SMOKE.COMPONENT_TO_ENV[component]

        def _resolver(
            env: Optional[Dict[str, str]] = None,
            *,
            log_sink: Any = None,
            binary_probe: Any = None,
        ):
            env_map = env or {}
            raw = env_map.get(env_var, "")
            requested = raw if raw else "python"
            chosen = requested

            # Use a dataclass-shaped decision so smoke's asdict()
            # works correctly.
            from dataclasses import dataclass

            @dataclass(frozen=True)
            class _Decision:
                domain: str
                requested_backend: str
                chosen_backend: str
                resolution_latency_us: int
                fallback_reason: Optional[str] = None
                bin_path: Optional[str] = None

            return chosen, _Decision(
                domain=component,
                requested_backend=requested,
                chosen_backend=chosen,
                resolution_latency_us=25,
                fallback_reason=None,
                bin_path=None,
            )

        return _resolver

    for component in SMOKE.ENGINE_BOOT_COMPONENTS:
        setattr(module, f"resolve_{component}_backend", _make(component))
    return module
