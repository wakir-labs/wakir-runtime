# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-57 — ``state_backing`` pre-boot emit-order pin (Selin, Persona-Engine).

The 0.5.2-final engine wires **ten** BackendDecision records into the
canonical boot fan-out (manifest §1, pin-pack ``boot_wired_crates``
record #1–#10). Nine of those records emit *inside* :meth:`boot` —
they are the explicit ``resolve_*_backend`` calls in
``PersonaEngine.boot``. **One** of them — ``state_backing`` —
emits *before* :meth:`boot` is ever called, from the
:meth:`__init__` → :meth:`_select_state_backing` →
:func:`resolve_state_backing_backend` path.

That asymmetry has been a Source-of-Truth in the Tag-51 resilience
suite (``test_stage_1_fan_out_records_emit_in_canonical_order``)
since the 0.5.1-pre-cutover wire-in, but only as a side-effect of
a 30+ scenario fan-out matrix. The Tag-56 0.5.2-final
production-readiness audit (PR #362, ``a7e8878``) flagged
**Finding D** (emit-order pin): the pre-boot ``state_backing``
emit MUST be pinned as a *single-purpose* hermetic test so any
future refactor that accidentally moves the resolver into
:meth:`boot` (or another resolver out of :meth:`boot`) fails a
test whose name and intent are unambiguous.

This file is that pin.

The ten records, in canonical emit order:

  0. ``state_backing``        — emitted inside ``__init__``
                                (``_select_state_backing``).
  1. ``recovery``             — emitted in ``boot``.
  2. ``fsm``                  — emitted in ``boot``.
  3. ``v907_verify``          — emitted in ``boot``.
  4. ``bridge_diff``          — emitted in ``boot``.
  5. ``subscribe_loop``       — emitted in ``boot``.
  6. ``anchor_emitter``       — emitted in ``boot``.
  7. ``svid_workload_identity`` — emitted in ``boot``.
  8. ``federation_resolver``  — emitted in ``boot``.
  9. ``bridge_audit_writer``  — emitted in ``boot``.

Note that the manifest §1 / pin-pack record numbering (where
``state_backing`` is *record #2*) describes the *wire-in order*
of the ten substrates over the engine's evolution, **not** the
per-boot emit order. The emit order is the order in which
``log_backend_decision`` actually writes to the log sink during a
clean cold-start, and that is what this file pins.

Hermetic envelope
-----------------
* No network. No NATS, no SPIRE, no gRPC.
* No subprocess. The Rust subprocess-bridge is never built.
* No filesystem writes outside ``tmp_path``.
* Deterministic — no clock-sensitive assertions.

Scope discipline (Selin)
------------------------
This file does **not** modify persona definitions (Aisha-Domäne),
WAT-core logic (Tomás-Domäne, Zone-K), identity-substrate design
(Reza-Domäne, Zone-L), or container-infra (Kai-Domäne, Zone-J).
It only exercises the existing Python authority + Stage-0
(``__init__``) + Stage-1 (``boot``) emit substrate.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Optional

import pytest
import yaml

from wirelang.persona_engine import engine as engine_mod
from wirelang.persona_engine.engine import (
    EnvContract,
    PersonaEngine,
)
from wirelang.persona_engine.v907_verify import V907VerifyResult


# ---------------------------------------------------------------------------
# Canonical 10-record emit order (this is the *invariant under test*).
# ---------------------------------------------------------------------------

# state_backing is at index 0 — it emits inside __init__, BEFORE boot().
EXPECTED_EMIT_ORDER = [
    "state_backing",
    "recovery",
    "fsm",
    "v907_verify",
    "bridge_diff",
    "subscribe_loop",
    "anchor_emitter",
    "svid_workload_identity",
    "federation_resolver",
    "bridge_audit_writer",
]

PRE_BOOT_DOMAIN = "state_backing"
BOOT_DOMAINS = EXPECTED_EMIT_ORDER[1:]  # the nine that emit in boot()
TOTAL_DECISION_COUNT = len(EXPECTED_EMIT_ORDER)  # 10

# Pin-pack on disk — used to assert the boot-wired-crates set contains
# all ten records (the pre-boot record is wired, just resolved earlier).
PIN_PACK_PATH = (
    Path(__file__).resolve().parents[3]
    / "infra"
    / "persona-engine"
    / "pin-pack-0.5.2-final-pre-cutover.yaml"
)

# Manifest on disk — §1 inventory must spiegel the emit-order pattern.
MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "persona_engine"
    / "MANIFEST-0.5.2-final-pre-cutover.md"
)


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


def _env_contract(tmp_path: Path) -> EnvContract:
    """A minimal EnvContract for hermetic engine construction.

    Mirrors the Tag-51 resilience-suite shape (same persona/org slug
    pattern, same axis-A/axis-C file scaffolding). The axis-A file
    must exist for V-907 pin computation; the actual verify call is
    monkeypatched away in this suite so the bytes do not matter.
    """
    axis_a = tmp_path / "persona.md"
    axis_a.write_text("persona-engine-emit-order-tag57", encoding="utf-8")
    axis_c = tmp_path / "persona.json"
    axis_c.write_text("{}", encoding="utf-8")
    return EnvContract(
        persona_id="pengine",
        org_id="org-tag57",
        nats_servers="",  # forces InMemory state-backing fence — hermetic.
        spiffe_endpoint_socket="unix:///nonexistent.sock",
        persona_state_bucket=None,
        v907_expected_pin=None,
        axis_a_path=axis_a,
        axis_c_path=axis_c,
    )


def _make_engine(tmp_path: Path) -> tuple[PersonaEngine, io.StringIO]:
    """Build a PersonaEngine with an in-memory log sink.

    The ``state_backing`` BackendDecision emits during this call —
    that is the central invariant of this suite. We never inject a
    pre-built ``state_backing=`` kwarg (which would bypass the
    resolver) because the production engine ships *without* that
    kwarg and the boot-self-test CI gate boots through the production
    path.
    """
    log_sink = io.StringIO()
    eng = PersonaEngine(
        env_contract=_env_contract(tmp_path),
        log_sink=log_sink,
    )
    return eng, log_sink


def _log_records(log_sink: io.StringIO) -> list[dict]:
    """Return the parsed JSON records emitted to ``log_sink``.

    Non-JSON observability debug lines are skipped — only the
    structured audit substrate is the subject of this suite.
    """
    records: list[dict] = []
    for line in log_sink.getvalue().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _decision_records(log_sink: io.StringIO) -> list[dict]:
    """Filter ``_log_records`` to just the BackendDecision audit lines."""
    return [
        r for r in _log_records(log_sink) if r.get("msg") == "backend-decision"
    ]


def _decision_domains_in_order(log_sink: io.StringIO) -> list[str]:
    """Return the ``domain`` field of each backend-decision record, in
    the order they were emitted to the sink."""
    return [r["domain"] for r in _decision_records(log_sink)]


@pytest.fixture(autouse=True)
def _stub_v907_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the real V-907 pin compute — touches axis-A bytes only and
    is not the subject of this suite. Tag-51 resilience-suite parity."""

    def _stub(
        persona_id: str,
        axis_a_path: Path,
        expected_pin: Optional[str],
    ) -> V907VerifyResult:
        return V907VerifyResult(
            pin="sha256:" + "5" * 64,
            mode="real",
            matched=None,
        )

    monkeypatch.setattr(engine_mod, "verify_v907_pin", _stub)


@pytest.fixture(autouse=True)
def _stub_svid_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """SVID probe is hermetic-fenced (socket missing on test box).

    Tag-51 resilience-suite parity. Required because ``boot()`` calls
    into the SVID-substrate before completing the fan-out, and the
    emit-order assertions require ``boot()`` to run to completion.
    """
    from wirelang.persona_engine import svid_workload_identity as svid_mod  # noqa: F401
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
# T-01 — state_backing emit happens BEFORE boot() is ever called.
# ---------------------------------------------------------------------------


def test_01_state_backing_emits_before_boot_is_called(tmp_path: Path) -> None:
    """Constructing a PersonaEngine MUST emit exactly the
    ``state_backing`` BackendDecision record — no other decision
    records, and no boot-side fan-out records.

    This is the central pin: the resolver lives in ``__init__``,
    not ``boot``. If a future refactor moves it into ``boot``, this
    test fails immediately (zero decision records after ``__init__``).
    If a future refactor moves *another* resolver into ``__init__``,
    this test also fails (>1 decision record after ``__init__``).
    """
    eng, log_sink = _make_engine(tmp_path)
    # Critical: boot() has NOT been called yet.
    assert not hasattr(eng, "_recovery_backend_decision"), (
        "Pre-condition: boot() must not have run yet (no boot-fan-out "
        "decision attributes should exist on the engine)."
    )
    domains = _decision_domains_in_order(log_sink)
    assert domains == [PRE_BOOT_DOMAIN], (
        f"Pre-boot emit set must be exactly {[PRE_BOOT_DOMAIN]}; "
        f"got {domains}. If state_backing has been moved into boot() "
        f"or another resolver has been moved into __init__, the "
        f"engine's Stage-0 contract has drifted."
    )


# ---------------------------------------------------------------------------
# T-02 — the OTHER nine resolvers emit only INSIDE boot().
# ---------------------------------------------------------------------------


def test_02_nine_other_decisions_emit_only_inside_boot(tmp_path: Path) -> None:
    """The nine non-state_backing resolvers MUST emit only after
    ``boot()`` is invoked, and only once per boot. Before boot is
    called, the log sink contains zero records for any of them.
    """
    eng, log_sink = _make_engine(tmp_path)
    pre_boot_domains = set(_decision_domains_in_order(log_sink))
    for domain in BOOT_DOMAINS:
        assert domain not in pre_boot_domains, (
            f"{domain!r} BackendDecision must NOT emit before boot(); "
            f"got pre-boot domains={sorted(pre_boot_domains)}"
        )
    eng.boot()
    post_boot_domains = _decision_domains_in_order(log_sink)
    for domain in BOOT_DOMAINS:
        assert domain in post_boot_domains, (
            f"{domain!r} BackendDecision must emit during boot(); "
            f"got post-boot domains={post_boot_domains}"
        )
    # Each of the nine emits exactly once per boot.
    for domain in BOOT_DOMAINS:
        count = post_boot_domains.count(domain)
        assert count == 1, (
            f"{domain!r} emitted {count}× during a single boot(); "
            f"the engine fan-out must be idempotent — one emit per "
            f"resolver per boot."
        )


# ---------------------------------------------------------------------------
# T-03 — full 10-record emit order, single boot.
# ---------------------------------------------------------------------------


def test_03_full_ten_record_emit_order_single_boot(tmp_path: Path) -> None:
    """A clean cold-start (``__init__`` + ``boot()``) MUST emit
    exactly the ten canonical BackendDecision records in
    ``EXPECTED_EMIT_ORDER``.

    This is the cardinality + ordering pin. The Doppelbetrieb-
    Vergleichs-Clock relies on this exact sequence to compute a
    stable boot-fingerprint; any drift here is a Phase-3b regression.
    """
    eng, log_sink = _make_engine(tmp_path)
    eng.boot()
    domains = _decision_domains_in_order(log_sink)
    assert domains == EXPECTED_EMIT_ORDER, (
        f"Emit order drift detected.\n"
        f"  expected ({len(EXPECTED_EMIT_ORDER)}): {EXPECTED_EMIT_ORDER}\n"
        f"  got      ({len(domains)}): {domains}"
    )


# ---------------------------------------------------------------------------
# T-04 — emit order is deterministic across three cold-starts.
# ---------------------------------------------------------------------------


def test_04_emit_order_deterministic_over_three_boot_cycles(
    tmp_path: Path,
) -> None:
    """Three independent ``__init__ + boot()`` cycles MUST produce
    byte-identical decision-domain sequences. The pin defends against
    accidental non-determinism (dict-ordering, set-ordering, hash
    randomization, async task scheduling) sneaking into the fan-out.
    """
    sequences: list[list[str]] = []
    for cycle in range(3):
        cycle_tmp = tmp_path / f"cycle-{cycle}"
        cycle_tmp.mkdir()
        eng, log_sink = _make_engine(cycle_tmp)
        eng.boot()
        sequences.append(_decision_domains_in_order(log_sink))
    assert sequences[0] == sequences[1] == sequences[2], (
        f"Emit order drift across boot cycles — non-determinism!\n"
        f"  cycle 0: {sequences[0]}\n"
        f"  cycle 1: {sequences[1]}\n"
        f"  cycle 2: {sequences[2]}"
    )
    # And — defensively — every cycle MUST also match the canonical
    # expected order (catches the case where all three cycles agree on
    # a *drifted* order).
    for cycle_idx, seq in enumerate(sequences):
        assert seq == EXPECTED_EMIT_ORDER, (
            f"Cycle {cycle_idx} agreed with the other cycles but on a "
            f"drifted order: {seq} (expected {EXPECTED_EMIT_ORDER})"
        )


# ---------------------------------------------------------------------------
# T-05 — exactly TEN records emit per cold-start, no more, no fewer.
# ---------------------------------------------------------------------------


def test_05_exactly_ten_records_per_cold_start(tmp_path: Path) -> None:
    """A clean cold-start emits ``TOTAL_DECISION_COUNT`` (=10) records.
    The cardinality pin catches both accidental duplicates and silent
    omissions in either ``__init__`` or ``boot()``.
    """
    eng, log_sink = _make_engine(tmp_path)
    eng.boot()
    records = _decision_records(log_sink)
    assert len(records) == TOTAL_DECISION_COUNT, (
        f"Expected {TOTAL_DECISION_COUNT} backend-decision records per "
        f"cold-start; got {len(records)}.\n"
        f"  records: {[r.get('domain') for r in records]}"
    )


# ---------------------------------------------------------------------------
# T-06 — pre-boot decision record carries the contracted JSON shape.
# ---------------------------------------------------------------------------


def test_06_pre_boot_record_carries_full_audit_shape(tmp_path: Path) -> None:
    """The pre-boot ``state_backing`` record MUST carry the same
    structured fields as the nine boot-side records. Operators parse
    this audit substrate by field name, not by line offset — a drift
    in the field set would break downstream consumers (cutover-script
    Welle-2 stanza, Doppelbetrieb diff oracle, boot-self-test pin).
    """
    eng, log_sink = _make_engine(tmp_path)
    records = _decision_records(log_sink)
    assert len(records) == 1, (
        f"Pre-boot must produce exactly one decision record; got "
        f"{len(records)}: {[r.get('domain') for r in records]}"
    )
    rec = records[0]
    required_fields = {
        "level",
        "msg",
        "domain",
        "requested_backend",
        "chosen_backend",
        "resolution_latency_us",
        "fallback_reason",
        "bin_path",
    }
    missing = required_fields - rec.keys()
    assert not missing, (
        f"Pre-boot state_backing record is missing fields {sorted(missing)};"
        f" full record: {rec}"
    )
    assert rec["level"] == "INFO"
    assert rec["msg"] == "backend-decision"
    assert rec["domain"] == PRE_BOOT_DOMAIN


# ---------------------------------------------------------------------------
# T-07 — pin-pack ``boot_wired_crates`` enumerates ALL TEN substrates.
# ---------------------------------------------------------------------------


def test_07_pin_pack_boot_wired_crates_contains_all_ten(tmp_path: Path) -> None:
    """The 0.5.2-final pin-pack ``boot_wired_crates`` list MUST contain
    all ten records — including ``persona-engine-state-backing``
    (record #2 by wire-in numbering, even though it emits at order
    position 0 by emit-order). The pre-boot location does NOT remove
    state_backing from the wired set — it is still part of the
    Phase-3b production-default-switch contract surface.
    """
    pp = yaml.safe_load(PIN_PACK_PATH.read_text(encoding="utf-8"))
    wired = pp.get("boot_wired_crates") or []
    assert isinstance(wired, list), (
        f"pin-pack boot_wired_crates must be a list; got {type(wired)}"
    )
    assert len(wired) == TOTAL_DECISION_COUNT, (
        f"pin-pack boot_wired_crates length must be "
        f"{TOTAL_DECISION_COUNT}; got {len(wired)}"
    )
    names = [c.get("name") for c in wired]
    assert "persona-engine-state-backing" in names, (
        f"pin-pack must list persona-engine-state-backing even though "
        f"it resolves pre-boot; got names={names}"
    )
    # Every record number 1..10 present exactly once.
    record_numbers = sorted(c.get("record") for c in wired)
    assert record_numbers == list(range(1, TOTAL_DECISION_COUNT + 1)), (
        f"pin-pack record numbering drift; got {record_numbers}"
    )


# ---------------------------------------------------------------------------
# T-08 — manifest §1 spiegelt the ten-substrate inventory.
# ---------------------------------------------------------------------------


def test_08_manifest_section_1_reflects_ten_substrate_inventory() -> None:
    """The on-disk manifest MUST reference all ten boot-wired crate
    names. The manifest is the human/machine source-of-truth for the
    cutover gate; the pre-boot state_backing emit-order asymmetry
    does NOT remove ``persona-engine-state-backing`` from §1.
    """
    assert MANIFEST_PATH.is_file(), (
        f"Manifest missing at {MANIFEST_PATH}; cannot pin emit-order "
        f"against its inventory."
    )
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    expected_crate_names = [
        "persona-engine-recovery",
        "persona-engine-state-backing",
        "persona-engine-fsm",
        "persona-engine-v907-verify",
        "persona-engine-bridge-diff",
        "persona-engine-subscribe-loop",
        "persona-engine-anchor-emitter",
        "persona-engine-svid-workload-identity",
        "persona-engine-federation-resolver",
        "persona-engine-bridge-audit-writer",
    ]
    missing = [n for n in expected_crate_names if n not in text]
    assert not missing, (
        f"Manifest §1 must reference all ten boot-wired crates; "
        f"missing: {missing}"
    )


# ---------------------------------------------------------------------------
# T-09 — boot-fan-out decision attributes match emit order.
# ---------------------------------------------------------------------------


def test_09_boot_attribute_population_matches_emit_order(
    tmp_path: Path,
) -> None:
    """After ``boot()``, each of the nine boot-side resolvers MUST
    have populated its decision attribute on the engine. Combined
    with the emit-order test, this proves that the resolver-attribute
    side-effect and the audit-record emit side-effect are coupled
    (no silent decoupling drift).
    """
    eng, log_sink = _make_engine(tmp_path)
    # state_backing surfaces as ``eng.backing`` (set in __init__),
    # NOT as a ``_state_backing_backend_decision`` attribute — there
    # is no engine attribute for the state_backing decision because
    # __init__ does not retain the decision struct. The emit-order
    # invariant therefore covers state_backing via the log sink only,
    # which is exactly what T-01/T-03/T-04 assert.
    assert eng.backing is not None, (
        "state_backing resolver must have populated eng.backing during "
        "__init__"
    )
    eng.boot()
    expected_attrs = [
        "_recovery_backend_decision",
        "_fsm_backend_decision",
        "_v907_verify_backend_decision",
        "_bridge_diff_backend_decision",
        "_subscribe_loop_backend_decision",
        "_anchor_emitter_backend_decision",
        "_svid_workload_identity_backend_decision",
        "_federation_resolver_backend_decision",
        "_bridge_audit_writer_backend_decision",
    ]
    missing = [a for a in expected_attrs if not hasattr(eng, a)]
    assert not missing, (
        f"boot() must populate every per-resolver decision attribute; "
        f"missing: {missing}"
    )


# ---------------------------------------------------------------------------
# T-10 — pre-boot record retained even when boot() raises.
# ---------------------------------------------------------------------------


def test_10_pre_boot_state_backing_record_retained_on_boot_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ``boot()`` raises during the Stage-1 fan-out, the pre-boot
    ``state_backing`` record MUST still be present in the audit log
    (it was emitted during ``__init__``, before any boot-side
    resolver had a chance to crash). This proves the audit substrate
    survives crash windows on later resolvers — operators can still
    see the pre-boot decision even when boot aborts.
    """
    eng, log_sink = _make_engine(tmp_path)
    # Pre-boot: state_backing already emitted exactly once.
    pre_boot_records = _decision_records(log_sink)
    assert len(pre_boot_records) == 1, (
        "Pre-condition: exactly one pre-boot decision record."
    )
    assert pre_boot_records[0]["domain"] == PRE_BOOT_DOMAIN
    # Inject a fault into the FIRST boot-side resolver (recovery).
    from wirelang.persona_engine import rust_backend_switch as rbs

    def _raise(*args, **kwargs):  # noqa: ANN001
        raise RuntimeError("tag57-injected-recovery-fault")

    monkeypatch.setattr(rbs, "resolve_recovery_backend", _raise)
    with pytest.raises(RuntimeError, match="tag57-injected-recovery-fault"):
        eng.boot()
    # Post-failure: state_backing record STILL there; no boot-side
    # records were emitted (recovery is the first, and it raised).
    post_records = _decision_records(log_sink)
    assert post_records, (
        "Audit substrate vanished on boot failure — pre-boot record "
        "must survive."
    )
    assert post_records[0]["domain"] == PRE_BOOT_DOMAIN, (
        f"Pre-boot state_backing record must remain the first audit "
        f"line after a recovery-resolver crash; got "
        f"{[r['domain'] for r in post_records]}"
    )
    # No boot-side decisions emitted (recovery crashed first).
    boot_side_emitted = [
        r["domain"] for r in post_records if r["domain"] in BOOT_DOMAINS
    ]
    assert not boot_side_emitted, (
        f"No boot-side decisions should have emitted when the first "
        f"boot-side resolver crashed; got {boot_side_emitted}"
    )


# ---------------------------------------------------------------------------
# T-11 — emit-order list-position pin (defensive: state_backing@0).
# ---------------------------------------------------------------------------


def test_11_state_backing_is_emit_order_index_zero(tmp_path: Path) -> None:
    """Sentinel pin: ``state_backing`` MUST be index 0 in the
    ``EXPECTED_EMIT_ORDER`` list AND in the runtime emit sequence.
    Catches the case where someone reorders ``EXPECTED_EMIT_ORDER``
    to "fix" a failing test instead of investigating the engine drift.
    """
    # Module-constant invariant.
    assert EXPECTED_EMIT_ORDER[0] == PRE_BOOT_DOMAIN
    assert len(EXPECTED_EMIT_ORDER) == TOTAL_DECISION_COUNT
    # Runtime invariant.
    eng, log_sink = _make_engine(tmp_path)
    eng.boot()
    domains = _decision_domains_in_order(log_sink)
    assert domains[0] == PRE_BOOT_DOMAIN, (
        f"state_backing must be the FIRST emitted decision record "
        f"(it lives in __init__); got first record domain={domains[0]!r}"
    )
