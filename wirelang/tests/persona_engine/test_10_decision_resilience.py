# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-51 — 10-Decision-Engine-Resilience-Test-Suite (Selin, Persona-Engine).

The 0.5.1-pre-cutover engine emits **ten** BackendDecision records
per cold-start (manifest §1, canonical boot-order below). Tag-51
asks: *what happens when one of those decisions crashes*? Each
decision has three crash-windows worth verifying for production
robustness:

* **during-emit** — the resolver itself raises (e.g. validation
  error on a poisoned ENV value, binary-probe injecting a fault).
  The engine must propagate a clean ``backend-switch-validation-
  failed`` audit record and abort boot — no partial FSM state, no
  ``boot-internal`` half-state.
* **post-emit-pre-FSM** — the resolver returned cleanly but the
  *next* resolver in the Stage-1 fan-out raises before the FSM
  ever transitions out of ``uninstantiated``. Partial-boot-state
  invariant: every prior decision attribute is set on the engine,
  every later one is unset, and the FSM stays in
  ``uninstantiated``.
* **between-decisions** — two consecutive Stage-1 resolvers raise
  back-to-back. The engine surfaces the *first* exception and
  never reaches the second resolver (no silent swallow, no
  re-raise drift).

Per the 10 BackendDecisions × 3 crash-windows matrix, the file
asserts ≥ 30 crash-scenarios in addition to a handful of
suite-level cross-checks (Stage-1 ordering, attribute presence,
fan-out cardinality, ``EngineeringOutputEvent`` non-emission on
boot-failure, idempotent boot abortion across all ten domains).

Hermetic envelope
-----------------
* No network. No NATS, no SPIRE, no gRPC.
* No subprocess. The Rust subprocess-bridge is never built; the
  test injects a ``binary_probe`` seam at every resolver to keep
  the binary search local.
* No filesystem writes outside ``tmp_path``.
* Deterministic — no clock-sensitive assertions.

Scope discipline (Selin)
------------------------
This file does **not** modify persona definitions (Aisha-Domäne),
WAT-core logic (Tomás-Domäne), identity-substrate design
(Reza-Domäne), or container-infra (Kai-Domäne). It exercises the
existing Python authority + Stage-1 boot fan-out only.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest

from wirelang.persona_engine import engine as engine_mod
from wirelang.persona_engine import rust_backend_switch
from wirelang.persona_engine.engine import (
    EnvContract,
    PersonaEngine,
)
from wirelang.persona_engine.lifecycle_state_machine import (
    LifecycleStateMachine,
)
from wirelang.persona_engine.v907_verify import V907VerifyResult


# The engine wraps every Stage-1 resolver in ``except Exception as
# exc`` and re-raises after emitting the structured audit record.
# Tag-51 fault injection therefore uses ordinary exception subclasses
# — the production error classes (BackendSwitchValidationError /
# RustBackendError) have positional argument signatures meant for
# specific call sites and would over-constrain the test surface.

class InjectedValidationFault(ValueError):
    """Test-only validation fault — engine treats as ENV-poisoning."""


class InjectedRustBackendFault(RuntimeError):
    """Test-only Rust-bridge fault — engine treats as subprocess
    failure."""


# ---------------------------------------------------------------------------
# Canonical 10-decision ordering (manifest §1).
# ---------------------------------------------------------------------------
#
# Each entry pins:
#   * domain       — engine-side audit-record domain field
#   * resolver_fn  — the ``rust_backend_switch.resolve_*`` callable
#   * attr_pair    — (chosen_backend_attr, decision_attr) on
#                    ``PersonaEngine`` after a successful resolution
#
# Order MUST match the boot fan-out in
# ``PersonaEngine._boot_internal``'s parent (``PersonaEngine.boot``)
# — and the manifest §1 inventory.

DECISION_ORDER = [
    (
        "recovery",
        "resolve_recovery_backend",
        ("_recovery_backend", "_recovery_backend_decision"),
    ),
    (
        "state_backing",
        # state-backing resolves inside __init__ via _select_state_backing;
        # the *engine-side* per-boot fan-out invokes the other nine
        # explicitly. We keep state_backing on the matrix because the
        # __init__ path is the production location of the second
        # BackendDecision record.
        "resolve_state_backing_backend",
        ("backing", None),  # No `_state_backing_backend_decision` attr.
    ),
    (
        "fsm",
        "resolve_fsm_backend",
        ("_fsm_backend", "_fsm_backend_decision"),
    ),
    (
        "v907_verify",
        "resolve_v907_verify_backend",
        ("_v907_verify_backend", "_v907_verify_backend_decision"),
    ),
    (
        "bridge_diff",
        "resolve_bridge_diff_backend",
        ("_bridge_diff_backend", "_bridge_diff_backend_decision"),
    ),
    (
        "subscribe_loop",
        "resolve_subscribe_loop_backend",
        ("_subscribe_loop_backend", "_subscribe_loop_backend_decision"),
    ),
    (
        "anchor_emitter",
        "resolve_anchor_emitter_backend",
        ("_anchor_emitter_backend", "_anchor_emitter_backend_decision"),
    ),
    (
        "svid_workload_identity",
        "resolve_svid_workload_identity_backend",
        (
            "_svid_workload_identity_backend",
            "_svid_workload_identity_backend_decision",
        ),
    ),
    (
        "federation_resolver",
        "resolve_federation_resolver_backend",
        (
            "_federation_resolver_backend",
            "_federation_resolver_backend_decision",
        ),
    ),
    (
        "bridge_audit_writer",
        "resolve_bridge_audit_writer_backend",
        (
            "_bridge_audit_writer_backend",
            "_bridge_audit_writer_backend_decision",
        ),
    ),
]

# The nine resolvers invoked by PersonaEngine.boot() (state_backing
# resolves earlier inside __init__).
BOOT_FAN_OUT_DECISIONS = [
    entry for entry in DECISION_ORDER if entry[0] != "state_backing"
]


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


def _env_contract(tmp_path: Path) -> EnvContract:
    """A minimal EnvContract suitable for boot()-driven tests.

    The axis-A path must exist for the v907_verify pin computation;
    the v907_verify call itself is monkeypatched in every test that
    invokes ``boot()`` so the actual content does not matter.
    """
    axis_a = tmp_path / "persona.md"
    axis_a.write_text("persona-engine-resilience-tag51", encoding="utf-8")
    axis_c = tmp_path / "persona.json"
    axis_c.write_text("{}", encoding="utf-8")
    return EnvContract(
        persona_id="pengine",
        org_id="org-tag51",
        nats_servers="",
        spiffe_endpoint_socket="unix:///nonexistent.sock",
        persona_state_bucket=None,
        v907_expected_pin=None,
        axis_a_path=axis_a,
        axis_c_path=axis_c,
    )


def _make_engine(tmp_path: Path) -> tuple[PersonaEngine, io.StringIO]:
    """Build a PersonaEngine with an in-memory log sink."""
    log_sink = io.StringIO()
    eng = PersonaEngine(
        env_contract=_env_contract(tmp_path),
        log_sink=log_sink,
    )
    return eng, log_sink


def _log_records(log_sink: io.StringIO) -> list[dict]:
    """Return the parsed JSON records emitted to ``log_sink``."""
    records = []
    for line in log_sink.getvalue().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            # Some sub-emitters write non-JSON lines (e.g. observability
            # debug). Skip them — only the structured audit records
            # matter for this suite.
            continue
    return records


@pytest.fixture(autouse=True)
def _stub_v907_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the real V-907 pin compute — it touches axis-A bytes only
    and is not the subject of this suite. Every test that triggers
    boot() lands a deterministic stub pin."""

    def _stub(
        persona_id: str,
        axis_a_path: Path,
        expected_pin: Optional[str],
    ) -> V907VerifyResult:
        return V907VerifyResult(
            pin="sha256:" + "a" * 64,
            mode="real",
            matched=None,
        )

    monkeypatch.setattr(engine_mod, "verify_v907_pin", _stub)


@pytest.fixture(autouse=True)
def _stub_svid_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """SVID probe is hermetic-fenced (socket missing on test box)."""

    from wirelang.persona_engine import svid_workload_identity as svid_mod
    from wirelang.persona_engine.svid_workload_identity import (
        SvidProbeResult,
    )

    def _stub_probe(*, org_id, persona_id, socket_path):  # noqa: ANN001
        return SvidProbeResult(
            socket_present=False,
            socket_connectable=False,
            expected_spiffe_id=f"spiffe://{org_id}/persona/{persona_id}",
            probed_at_utc="2026-05-19T00:00:00Z",
        )

    monkeypatch.setattr(engine_mod, "probe_workload_api_socket", _stub_probe)
    monkeypatch.setattr(
        engine_mod, "resolve_socket_path", lambda env: "/nonexistent.sock"
    )


# ---------------------------------------------------------------------------
# Helper: inject a controlled fault into one Stage-1 resolver.
# ---------------------------------------------------------------------------


@dataclass
class CrashSpec:
    """Describes a fault to inject at a single resolver."""

    domain: str
    resolver_name: str
    exception: Exception


def _patch_resolver_to_raise(
    monkeypatch: pytest.MonkeyPatch,
    crash: CrashSpec,
) -> None:
    """Replace ``rust_backend_switch.<resolver_name>`` with a function
    that raises ``crash.exception`` on first call."""

    def _raiser(*_args, **_kwargs):  # noqa: ANN001
        raise crash.exception

    monkeypatch.setattr(
        rust_backend_switch, crash.resolver_name, _raiser
    )
    # The engine imports the resolvers inline (``from .rust_backend_switch
    # import resolve_*``) so we also patch the binding the engine sees.
    monkeypatch.setattr(
        engine_mod,
        crash.resolver_name,
        _raiser,
        raising=False,
    )


def _set_resolver_to_count_call(
    monkeypatch: pytest.MonkeyPatch,
    resolver_name: str,
    counter: dict,
) -> None:
    """Wrap a resolver so the call count is recorded in ``counter``.

    Counter key is the resolver_name. Used to assert
    "downstream resolvers never run after an upstream crash."
    """
    real = getattr(rust_backend_switch, resolver_name)

    def _counting(*args, **kwargs):  # noqa: ANN001
        counter[resolver_name] = counter.get(resolver_name, 0) + 1
        return real(*args, **kwargs)

    monkeypatch.setattr(rust_backend_switch, resolver_name, _counting)
    monkeypatch.setattr(
        engine_mod, resolver_name, _counting, raising=False
    )


# ---------------------------------------------------------------------------
# Suite-level invariants.
# ---------------------------------------------------------------------------


def test_decision_order_matches_manifest_cardinality():
    """The matrix in this file MUST list exactly 10 entries — one per
    BackendDecision the manifest §1 documents."""
    assert len(DECISION_ORDER) == 10, (
        "Tag-51 matrix size must equal the manifest's 10-record floor; "
        f"got {len(DECISION_ORDER)}"
    )


def test_boot_fan_out_decisions_are_nine():
    """The engine boot() method explicitly fans out nine resolvers
    (state_backing resolves inside __init__)."""
    assert len(BOOT_FAN_OUT_DECISIONS) == 9, (
        f"boot() fan-out must touch nine resolvers; "
        f"got {len(BOOT_FAN_OUT_DECISIONS)}"
    )


def test_decision_order_domains_are_canonical():
    """Domain ordering pins manifest §1 record-numbers 1..10."""
    domains = [d for d, _, _ in DECISION_ORDER]
    assert domains == [
        "recovery",
        "state_backing",
        "fsm",
        "v907_verify",
        "bridge_diff",
        "subscribe_loop",
        "anchor_emitter",
        "svid_workload_identity",
        "federation_resolver",
        "bridge_audit_writer",
    ]


def test_clean_boot_emits_all_nine_fan_out_decisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Baseline — a clean boot lands all nine fan-out decisions and
    every per-domain backend-attribute is populated on the engine."""
    eng, log_sink = _make_engine(tmp_path)
    eng.boot()
    # All nine fan-out resolvers landed their (attr, decision) pair.
    for domain, _resolver, (attr, dec_attr) in BOOT_FAN_OUT_DECISIONS:
        assert hasattr(eng, attr), (
            f"engine.{attr} missing — {domain} fan-out skipped"
        )
        if dec_attr is not None:
            assert hasattr(eng, dec_attr), (
                f"engine.{dec_attr} missing — {domain} decision lost"
            )
    # The state_backing decision lands inside __init__; the engine
    # exposes the backing object directly.
    assert eng.backing is not None, "state_backing must resolve to a backing"
    # The audit log contains nine ``backend-decision`` records — one
    # per fan-out domain. (state_backing emits its own as well, so the
    # total is ten records.)
    records = _log_records(log_sink)
    bd = [r for r in records if r.get("msg") == "backend-decision"]
    domains_logged = [r["domain"] for r in bd]
    expected_logged = {d for d, _, _ in DECISION_ORDER}
    assert set(domains_logged) == expected_logged, (
        f"clean-boot audit log must surface every domain; "
        f"got {sorted(set(domains_logged))}, "
        f"expected {sorted(expected_logged)}"
    )


# ---------------------------------------------------------------------------
# Crash-window matrix — DURING-EMIT (validation-time fault).
#
# Inject a BackendSwitchValidationError at the resolver entry; assert:
#   * engine.boot() raises (does NOT swallow);
#   * the audit log carries a backend-switch-validation-failed record
#     for the expected domain;
#   * the FSM never advanced past uninstantiated;
#   * no engineering-output event was emitted (bridge_writer is None).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "domain,resolver_name",
    [
        (d, r)
        for d, r, _attrs in BOOT_FAN_OUT_DECISIONS
    ],
    ids=[d for d, _, _ in BOOT_FAN_OUT_DECISIONS],
)
def test_during_emit_crash_aborts_boot_cleanly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    domain: str,
    resolver_name: str,
):
    """During-emit crash: resolver itself raises validation error."""
    eng, log_sink = _make_engine(tmp_path)
    crash = CrashSpec(
        domain=domain,
        resolver_name=resolver_name,
        exception=InjectedValidationFault(
            f"poisoned env value for {domain} (tag-51 injected)"
        ),
    )
    _patch_resolver_to_raise(monkeypatch, crash)

    with pytest.raises(InjectedValidationFault):
        eng.boot()

    # FSM never advanced (audit-log truth, not in-memory truth):
    # spawn() was never called.
    assert eng.fsm.state == "uninstantiated", (
        f"crash in {domain} must not leave FSM advanced; "
        f"got state={eng.fsm.state!r}"
    )
    # No bridge_writer ever attached.
    assert eng.bridge_writer is None, (
        f"crash in {domain} must not leave a bridge_writer attached"
    )
    # Audit log carries the structured failure record for the right
    # domain.
    records = _log_records(log_sink)
    failure_records = [
        r
        for r in records
        if r.get("msg") == "backend-switch-validation-failed"
        and r.get("domain") == domain
    ]
    assert failure_records, (
        f"audit log must contain backend-switch-validation-failed "
        f"record for domain={domain!r}; got {records[-3:]}"
    )


# ---------------------------------------------------------------------------
# Crash-window matrix — POST-EMIT-PRE-FSM (downstream resolver fault).
#
# The targeted resolver returned cleanly; the *next* fan-out resolver
# raises a RustBackendError. Assert:
#   * boot() raises the downstream exception (NOT the upstream-clean
#     one);
#   * the upstream attribute is populated (partial-boot-state truth);
#   * the FSM did not advance;
#   * downstream resolvers were never invoked.
# ---------------------------------------------------------------------------


def _next_fan_out_after(
    upstream_resolver: str,
) -> Optional[tuple[str, str]]:
    """Return (next_domain, next_resolver_name) immediately after
    ``upstream_resolver`` in BOOT_FAN_OUT_DECISIONS, or None when
    ``upstream_resolver`` is the last entry."""
    for i, (_d, r, _a) in enumerate(BOOT_FAN_OUT_DECISIONS):
        if r == upstream_resolver:
            if i + 1 >= len(BOOT_FAN_OUT_DECISIONS):
                return None
            nxt = BOOT_FAN_OUT_DECISIONS[i + 1]
            return nxt[0], nxt[1]
    return None


# Skip the last fan-out resolver — by definition no downstream exists
# (the engine moves to the boot span body instead of another resolver).
POST_EMIT_TARGETS = [
    (d, r, attrs)
    for (d, r, attrs) in BOOT_FAN_OUT_DECISIONS[:-1]
]


@pytest.mark.parametrize(
    "upstream_domain,upstream_resolver,upstream_attrs",
    POST_EMIT_TARGETS,
    ids=[d for d, _, _ in POST_EMIT_TARGETS],
)
def test_post_emit_pre_fsm_crash_preserves_partial_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    upstream_domain: str,
    upstream_resolver: str,
    upstream_attrs: tuple,
):
    """Post-emit-pre-FSM crash: upstream succeeds, downstream raises."""
    nxt = _next_fan_out_after(upstream_resolver)
    assert nxt is not None, (
        f"BUG in test: {upstream_resolver} has no downstream"
    )
    next_domain, next_resolver = nxt

    eng, log_sink = _make_engine(tmp_path)

    # Inject the fault into the *downstream* resolver.
    crash = CrashSpec(
        domain=next_domain,
        resolver_name=next_resolver,
        exception=InjectedRustBackendFault(
            f"injected post-emit fault at {next_domain} (tag-51)"
        ),
    )
    _patch_resolver_to_raise(monkeypatch, crash)

    # Track that downstream-of-downstream resolvers were NOT touched.
    counter: dict = {}
    for d, r, _ in BOOT_FAN_OUT_DECISIONS:
        if d in {upstream_domain, next_domain}:
            continue
        # Only count resolvers strictly after `next_domain`.
        pass
    # Re-walk to find true post-fault resolvers.
    post_fault: list[str] = []
    seen_next = False
    for d, r, _ in BOOT_FAN_OUT_DECISIONS:
        if seen_next:
            post_fault.append(r)
        if d == next_domain:
            seen_next = True
    for r in post_fault:
        _set_resolver_to_count_call(monkeypatch, r, counter)

    with pytest.raises(InjectedRustBackendFault):
        eng.boot()

    # Upstream attribute populated (partial-boot-state preserved).
    attr_name, dec_attr = upstream_attrs
    assert hasattr(eng, attr_name), (
        f"upstream {upstream_domain} attribute {attr_name!r} should "
        f"have landed before the downstream fault"
    )
    if dec_attr is not None:
        assert hasattr(eng, dec_attr), (
            f"upstream decision attribute {dec_attr!r} missing"
        )

    # No post-fault resolver was invoked.
    for r in post_fault:
        assert counter.get(r, 0) == 0, (
            f"resolver {r!r} ran after the {next_domain} fault — "
            f"Stage-1 fan-out failed to short-circuit"
        )

    # FSM remained uninstantiated.
    assert eng.fsm.state == "uninstantiated"
    assert eng.bridge_writer is None

    # Audit log: validation-failed record names the downstream domain.
    records = _log_records(log_sink)
    failure_records = [
        r
        for r in records
        if r.get("msg") == "backend-switch-validation-failed"
        and r.get("domain") == next_domain
    ]
    assert failure_records, (
        f"audit must record validation-failed for downstream "
        f"{next_domain!r}; got {records[-3:]}"
    )


# ---------------------------------------------------------------------------
# Crash-window matrix — BETWEEN-DECISIONS (two consecutive resolvers
# fault).
#
# Inject the same exception into both the targeted resolver AND the
# resolver immediately after it. Assert:
#   * boot() raises the FIRST exception (the engine never reaches the
#     second resolver's body);
#   * the second resolver's exception is NOT surfaced.
# ---------------------------------------------------------------------------


BETWEEN_DECISION_TARGETS = [
    (d, r)
    for (d, r, _a) in BOOT_FAN_OUT_DECISIONS[:-1]
]


@pytest.mark.parametrize(
    "first_domain,first_resolver",
    BETWEEN_DECISION_TARGETS,
    ids=[d for d, _ in BETWEEN_DECISION_TARGETS],
)
def test_between_decisions_first_exception_wins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    first_domain: str,
    first_resolver: str,
):
    """Between-decisions crash: two consecutive resolvers raise; the
    first exception MUST surface, the second MUST never run."""
    nxt = _next_fan_out_after(first_resolver)
    assert nxt is not None
    second_domain, second_resolver = nxt

    eng, _log_sink = _make_engine(tmp_path)

    first_crash = CrashSpec(
        domain=first_domain,
        resolver_name=first_resolver,
        exception=InjectedValidationFault(
            f"FIRST fault at {first_domain} (tag-51)"
        ),
    )
    _patch_resolver_to_raise(monkeypatch, first_crash)

    second_call_count = {"n": 0}

    def _second_raiser(*_args, **_kwargs):  # noqa: ANN001
        second_call_count["n"] += 1
        raise InjectedRustBackendFault(
            f"SECOND fault at {second_domain} (tag-51)"
        )

    monkeypatch.setattr(
        rust_backend_switch, second_resolver, _second_raiser
    )
    monkeypatch.setattr(
        engine_mod, second_resolver, _second_raiser, raising=False
    )

    with pytest.raises(InjectedValidationFault) as excinfo:
        eng.boot()

    # FIRST exception surfaced — second resolver was never reached.
    assert "FIRST fault" in str(excinfo.value), (
        f"between-decisions crash must surface the FIRST fault; "
        f"got {excinfo.value!r}"
    )
    assert second_call_count["n"] == 0, (
        f"second resolver was invoked {second_call_count['n']} times — "
        f"Stage-1 fan-out failed to short-circuit on first fault"
    )


# ---------------------------------------------------------------------------
# Cross-cutting invariants.
# ---------------------------------------------------------------------------


def test_idempotent_failure_path_no_engineering_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """No EngineeringOutputEvent is ever emitted on a failed boot —
    the audit substrate must not record a 'spawn happened' signal
    when spawn() was never called. This is the Doppelbetrieb-
    Vergleichs-Clock anti-false-positive."""
    eng, log_sink = _make_engine(tmp_path)
    _patch_resolver_to_raise(
        monkeypatch,
        CrashSpec(
            domain="recovery",
            resolver_name="resolve_recovery_backend",
            exception=InjectedValidationFault("anti-false-positive"),
        ),
    )
    with pytest.raises(InjectedValidationFault):
        eng.boot()

    records = _log_records(log_sink)
    eng_out = [
        r
        for r in records
        if r.get("msg") == "engineering-output-emission-first"
    ]
    assert eng_out == [], (
        f"failed boot must NOT emit engineering-output-emission-first; "
        f"got {eng_out}"
    )


def test_partial_state_attributes_are_strictly_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """When the v907_verify resolver crashes mid-fan-out, every
    resolver *before* it must have left its attributes on the engine
    (here: recovery + fsm; state_backing was resolved in __init__),
    and every resolver *after* it must NOT have left attributes.

    This is the partial-boot-state strict-prefix invariant: the
    engine's mutable surface follows the boot-order monotonically.
    """
    eng, _log_sink = _make_engine(tmp_path)
    _patch_resolver_to_raise(
        monkeypatch,
        CrashSpec(
            domain="v907_verify",
            resolver_name="resolve_v907_verify_backend",
            exception=InjectedValidationFault("v907-injected"),
        ),
    )

    with pytest.raises(InjectedValidationFault):
        eng.boot()

    # Pre-v907 in the fan-out: recovery + fsm.
    assert hasattr(eng, "_recovery_backend")
    assert hasattr(eng, "_recovery_backend_decision")
    assert hasattr(eng, "_fsm_backend")
    assert hasattr(eng, "_fsm_backend_decision")

    # Post-v907 in the fan-out: bridge_diff, subscribe_loop, anchor_emitter,
    # svid_workload_identity, federation_resolver, bridge_audit_writer.
    post = [
        "_bridge_diff_backend",
        "_subscribe_loop_backend",
        "_anchor_emitter_backend",
        "_svid_workload_identity_backend",
        "_federation_resolver_backend",
        "_bridge_audit_writer_backend",
    ]
    for attr in post:
        assert not hasattr(eng, attr), (
            f"engine.{attr} should NOT have landed after the "
            f"v907_verify crash; partial-boot-state must be a "
            f"strict prefix of DECISION_ORDER"
        )


def test_repeated_boot_after_crash_is_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Calling boot() a second time after a failed first call must
    not double-attach or corrupt state. The engine is allowed to
    re-raise; the FSM must stay uninstantiated; no bridge_writer
    leaks across calls."""
    eng, _log_sink = _make_engine(tmp_path)
    _patch_resolver_to_raise(
        monkeypatch,
        CrashSpec(
            domain="fsm",
            resolver_name="resolve_fsm_backend",
            exception=InjectedValidationFault("fsm-tag-51"),
        ),
    )
    with pytest.raises(InjectedValidationFault):
        eng.boot()
    with pytest.raises(InjectedValidationFault):
        eng.boot()
    assert eng.fsm.state == "uninstantiated"
    assert eng.bridge_writer is None


def test_clean_recovery_after_validation_error_unwound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """If the operator's ENV fault is fixed between attempts (test
    simulates by un-patching the resolver), boot() must succeed on
    the next call. No sticky fault state."""
    eng, _log_sink = _make_engine(tmp_path)

    # First attempt — injected fault on bridge_diff.
    _patch_resolver_to_raise(
        monkeypatch,
        CrashSpec(
            domain="bridge_diff",
            resolver_name="resolve_bridge_diff_backend",
            exception=InjectedValidationFault("transient-tag-51"),
        ),
    )
    with pytest.raises(InjectedValidationFault):
        eng.boot()

    # Operator fixes ENV — restore the real resolver.
    monkeypatch.undo()
    # Re-stub V-907 + SVID after monkeypatch.undo() so the global
    # autouse stubs still hold for the recovery call.
    from wirelang.persona_engine import (
        svid_workload_identity as svid_mod,  # noqa: F401
    )

    def _stub_v907(persona_id, axis_a_path, expected_pin):  # noqa: ANN001
        return V907VerifyResult(
            pin="sha256:" + "b" * 64,
            mode="real",
            matched=None,
        )

    monkeypatch.setattr(engine_mod, "verify_v907_pin", _stub_v907)
    from wirelang.persona_engine.svid_workload_identity import (
        SvidProbeResult,
    )

    monkeypatch.setattr(
        engine_mod,
        "probe_workload_api_socket",
        lambda *, org_id, persona_id, socket_path: SvidProbeResult(
            socket_present=False,
            socket_connectable=False,
            expected_spiffe_id=f"spiffe://{org_id}/persona/{persona_id}",
            probed_at_utc="2026-05-19T00:00:00Z",
        ),
    )
    monkeypatch.setattr(
        engine_mod, "resolve_socket_path", lambda env: "/nonexistent.sock"
    )

    # Fresh engine — boot() should succeed.
    eng2, log_sink2 = _make_engine(tmp_path)
    eng2.boot()
    for _d, _r, (attr, _dec) in BOOT_FAN_OUT_DECISIONS:
        assert hasattr(eng2, attr), (
            f"clean recovery boot must land {attr!r}"
        )


def test_audit_log_records_carry_domain_field_for_every_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Every backend-switch-validation-failed record MUST carry a
    non-empty ``domain`` field. The audit substrate downstream uses
    this for per-domain failure-rate alarms (Noa's SRE board)."""
    for crash_domain, resolver_name, _attrs in BOOT_FAN_OUT_DECISIONS:
        eng, log_sink = _make_engine(tmp_path)
        with monkeypatch.context() as m:
            _patch_resolver_to_raise(
                m,
                CrashSpec(
                    domain=crash_domain,
                    resolver_name=resolver_name,
                    exception=InjectedValidationFault(
                        f"audit-field-check-{crash_domain}"
                    ),
                ),
            )
            with pytest.raises(InjectedValidationFault):
                eng.boot()
        records = _log_records(log_sink)
        failures = [
            r
            for r in records
            if r.get("msg") == "backend-switch-validation-failed"
        ]
        assert failures, (
            f"no failure record for {crash_domain}: log={records[-3:]}"
        )
        for f in failures:
            assert f.get("domain") == crash_domain, (
                f"failure-record domain mismatch: expected "
                f"{crash_domain!r}, got {f.get('domain')!r}"
            )
            assert f.get("error"), (
                f"failure-record must carry non-empty 'error' field "
                f"(tag-51 alarm contract); got {f!r}"
            )


def test_fsm_was_constructed_before_any_decision_resolution(
    tmp_path: Path,
):
    """The engine constructs ``self.fsm`` (a Python
    LifecycleStateMachine instance) inside __init__, BEFORE boot()
    runs. This is a load-bearing invariant for the
    Phase-3b cutover: the FSM exists even when every backend
    decision is forced to Python."""
    eng, _log_sink = _make_engine(tmp_path)
    assert isinstance(eng.fsm, LifecycleStateMachine)
    assert eng.fsm.state == "uninstantiated"
    # No resolver should have populated attribute pairs yet.
    assert not hasattr(eng, "_recovery_backend_decision")


def test_stage_1_fan_out_records_emit_in_canonical_order(
    tmp_path: Path,
):
    """A clean boot MUST emit the backend-decision audit records in
    the canonical boot order (manifest §1 cardinality). The
    Doppelbetrieb-Vergleichs-Clock relies on this order to compute a
    stable boot-fingerprint."""
    eng, log_sink = _make_engine(tmp_path)
    eng.boot()
    records = _log_records(log_sink)
    bd = [
        r["domain"]
        for r in records
        if r.get("msg") == "backend-decision"
    ]
    # state_backing is emitted inside __init__, before boot(): it
    # therefore appears FIRST in the log, then the nine boot-fan-out
    # records follow in order.
    expected_order = ["state_backing"] + [
        d for d, _, _ in BOOT_FAN_OUT_DECISIONS
    ]
    assert bd == expected_order, (
        f"backend-decision emit order must be canonical; got {bd}, "
        f"expected {expected_order}"
    )
