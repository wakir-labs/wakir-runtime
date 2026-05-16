# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic Doppelbetrieb-Bridge-Smoke tests (Sprint-10 Tag-9).

Anlass — Sprint-10 Tag-8 Phase-3 smoke gate (Bug-38b) activated the
two federation-substance checks (federation-bundle-sync-reachable +
federation-cross-trust-domain-verify) for the **single-Tomás** path
(wakir-runtime persona-engine 0.4.2-pilot). Tag-9 extends the smoke
to the **Doppelbetrieb-Bridge** scenario: two Tomás emissions in
parallel from two distinct engine binaries hitting the same WAT-
Anchor pipeline.

Doppelbetrieb-Bridge — what it is
---------------------------------

Two engineering output sources coexist during the Doppelbetrieb-
Vergleich-4-Wochen-Clock (Spec §3.7-bridge-audit):

1. **Pre-Framework Tomás** — Claude-Code-Subagent spawn from the
   Operator-Hand (Mira-Sandbox or claude-dev Sandbox). Emits to the
   Pre-Framework Markdown sink at
   ``/var/lib/wakir/persona/tomas/bridge-audit.md``.
   ``engine_version`` field marks the emission as
   ``"pre-framework-tomas"``.

2. **Wakir-Runtime Tomás** — persona-engine container
   (``wakir-persona-engine:0.4.2-pilot``, post Sprint-Pengine-12).
   Emits via ``BridgeAuditWriter`` to the same Pre-Framework sink
   AND to the structured-log JSON envelope on stderr (Quadlet
   ``podman logs`` substrate). ``engine_version`` field marks the
   emission as ``"0.4.2-pilot"``.

Bridge-smoke invariants
-----------------------

The Doppelbetrieb-Vergleich substrate needs **two** properties to be
hermetically true so the audit substrate can compare outputs:

* **Payload-hash agreement.** When both engines emit the same
  semantic payload bytes (the actual reply or tool-call payload),
  the envelope's ``output_payload_sha256`` field MUST be identical.
  The hash is engine-version-agnostic — it is a function of the
  payload bytes alone.

* **Engine-version discrimination.** The envelope's
  ``engine_version`` field MUST differ between the two emissions so
  the audit substrate can attribute each emission to its origin
  engine. Without this discriminator the 4-Wochen-Vergleich cannot
  compute byte-for-byte equivalence on a per-engine basis.

Additionally, the JCS-canonical envelope shape MUST be byte-stable
across emissions (alphabetical key order, no whitespace).

Sandbox boundary
----------------

Source-file inspection + in-memory ``BridgeAuditWriter`` exercise
only. No podman, no NATS, no live VM — see
``feedback_sandbox_host_trennung.md``. The bridge-smoke substrate
is the Operator-Hand Live-VM-Lane's responsibility; this file
exercises the engine-side caller and locks the invariants that
the Live-VM-Lane depends on.

Test-Vector index
-----------------

Doppelbetrieb-Bridge-Smoke (8 vectors):

* ``TV-DB-BRIDGE-01`` Two writers (pre-framework + 0.4.2-pilot)
  emit the same payload bytes → same ``output_payload_sha256``.
* ``TV-DB-BRIDGE-02`` Two writers emit the same payload →
  ``engine_version`` field discriminates origin.
* ``TV-DB-BRIDGE-03`` JCS envelope keys are byte-stable (alphabetical
  order) across both emissions.
* ``TV-DB-BRIDGE-04`` Both writers' Pre-Framework sinks merge
  cleanly into the same Markdown file (audit-readability invariant).
* ``TV-DB-BRIDGE-05`` Engine-version field is mandatory and
  non-empty in both envelopes.
* ``TV-DB-BRIDGE-06`` Distinct payloads → distinct
  ``output_payload_sha256`` (cross-emission collision negative
  control).
* ``TV-DB-BRIDGE-07`` ``BridgeAuditWriter`` accepts the
  ``"pre-framework-tomas"`` engine_version string verbatim
  (no validation rejection — engine_version is opaque per Spec).
* ``TV-DB-BRIDGE-08`` Wakir-Runtime sink JSON line parses cleanly
  and round-trips through ``json.loads`` for both engines.

-- Tomás
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from wirelang.persona_engine.bridge_audit_writer import (
    BridgeAuditWriter,
    EngineeringOutputEvent,
    ENGINEERING_OUTPUT_SCHEMA,
)


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


_ORG = "acme"
_PERSONA = "tomas"
_SESSION = "doppelbetrieb-bridge-smoke"
_V907_PIN = "sha256:" + "f" * 64
_PRE_FRAMEWORK_VERSION = "pre-framework-tomas"
_WAKIR_RUNTIME_VERSION = "0.4.2-pilot"
_TS = "2026-05-15T23:35:00Z"


def _make_writer(
    tmp_path: Path,
    sink: io.StringIO,
    engine_version: str,
    *,
    shared_sink_filename: str = "bridge-audit.md",
) -> BridgeAuditWriter:
    """Construct a writer pointing at a shared Pre-Framework sink (the
    Doppelbetrieb-Bridge writes both engines into one Markdown file)."""
    return BridgeAuditWriter(
        org_id=_ORG,
        persona_id=_PERSONA,
        session_id=_SESSION + "-" + engine_version,
        engine_version=engine_version,
        v907_pin=_V907_PIN,
        preframework_sink_path=tmp_path / shared_sink_filename,
        wakir_runtime_sink=sink,
    )


# ---------------------------------------------------------------------------
# TV-DB-BRIDGE-01 … 08.
# ---------------------------------------------------------------------------


def test_tv_db_bridge_01_same_payload_yields_same_hash(tmp_path):
    """Two distinct engines, same payload bytes → identical
    ``output_payload_sha256`` (hash is engine-version-agnostic)."""
    sink_a = io.StringIO()
    sink_b = io.StringIO()
    pre = _make_writer(tmp_path, sink_a, _PRE_FRAMEWORK_VERSION)
    run = _make_writer(tmp_path, sink_b, _WAKIR_RUNTIME_VERSION)
    payload = b'{"reply":"hello-from-tomas"}'

    evt_pre = pre.emit("reply", payload, ts_utc=_TS)
    evt_run = run.emit("reply", payload, ts_utc=_TS)

    assert evt_pre.output_payload_sha256 == evt_run.output_payload_sha256, (
        "doppelbetrieb-bridge invariant: same payload bytes must yield "
        "the same envelope output_payload_sha256 across engines "
        f"(pre={evt_pre.output_payload_sha256!r} "
        f"run={evt_run.output_payload_sha256!r})"
    )


def test_tv_db_bridge_02_engine_version_field_discriminates(tmp_path):
    """``engine_version`` field discriminates origin engine."""
    sink_a = io.StringIO()
    sink_b = io.StringIO()
    pre = _make_writer(tmp_path, sink_a, _PRE_FRAMEWORK_VERSION)
    run = _make_writer(tmp_path, sink_b, _WAKIR_RUNTIME_VERSION)
    payload = b'{"reply":"hello"}'

    evt_pre = pre.emit("reply", payload, ts_utc=_TS)
    evt_run = run.emit("reply", payload, ts_utc=_TS)

    assert evt_pre.engine_version == _PRE_FRAMEWORK_VERSION
    assert evt_run.engine_version == _WAKIR_RUNTIME_VERSION
    assert evt_pre.engine_version != evt_run.engine_version, (
        "engine_version field must discriminate the two origin engines"
    )


def test_tv_db_bridge_03_jcs_envelope_keys_byte_stable(tmp_path):
    """JCS envelope keys are alphabetically ordered (byte-stable across
    emissions and engines)."""
    sink_a = io.StringIO()
    sink_b = io.StringIO()
    pre = _make_writer(tmp_path, sink_a, _PRE_FRAMEWORK_VERSION)
    run = _make_writer(tmp_path, sink_b, _WAKIR_RUNTIME_VERSION)
    payload = b"some-bytes"

    evt_pre = pre.emit("tool_call", payload, ts_utc=_TS)
    evt_run = run.emit("tool_call", payload, ts_utc=_TS)

    # Extract the key sequence from each envelope and assert
    # alphabetical order.
    for evt in (evt_pre, evt_run):
        envelope = json.loads(evt.to_jcs_bytes().decode("utf-8"))
        keys = list(envelope.keys())
        assert keys == sorted(keys), (
            f"JCS envelope keys not alphabetical: {keys}"
        )


def test_tv_db_bridge_04_shared_preframework_sink_merges_cleanly(tmp_path):
    """Both writers can append to the same Pre-Framework Markdown sink
    without conflict (single-writer-per-sink is not enforced at the
    write boundary — the audit substrate handles ordering)."""
    sink_a = io.StringIO()
    sink_b = io.StringIO()
    pre = _make_writer(tmp_path, sink_a, _PRE_FRAMEWORK_VERSION)
    run = _make_writer(tmp_path, sink_b, _WAKIR_RUNTIME_VERSION)
    pre.emit("reply", b"payload-from-pre", ts_utc=_TS)
    run.emit("reply", b"payload-from-run", ts_utc=_TS)

    shared = tmp_path / "bridge-audit.md"
    content = shared.read_text(encoding="utf-8")

    # Both engine envelopes are present in the shared sink.
    assert _PRE_FRAMEWORK_VERSION in content, (
        "Pre-Framework engine_version not in shared bridge-audit.md"
    )
    assert _WAKIR_RUNTIME_VERSION in content, (
        "Wakir-Runtime engine_version not in shared bridge-audit.md"
    )
    # Both step-0 headers present (each writer starts its own session
    # at step 0).
    assert content.count("## step 0 — reply") == 2, (
        "shared sink should contain one step-0 header per writer "
        f"(got {content.count('## step 0 — reply')})"
    )


def test_tv_db_bridge_05_engine_version_mandatory_nonempty(tmp_path):
    """``engine_version`` is mandatory and non-empty in both envelopes."""
    sink_a = io.StringIO()
    sink_b = io.StringIO()
    pre = _make_writer(tmp_path, sink_a, _PRE_FRAMEWORK_VERSION)
    run = _make_writer(tmp_path, sink_b, _WAKIR_RUNTIME_VERSION)
    evt_pre = pre.emit("audit_annotation", b"a", ts_utc=_TS)
    evt_run = run.emit("audit_annotation", b"a", ts_utc=_TS)

    for evt in (evt_pre, evt_run):
        envelope = json.loads(evt.to_jcs_bytes().decode("utf-8"))
        assert "engine_version" in envelope, (
            "envelope missing engine_version key"
        )
        assert envelope["engine_version"], (
            "engine_version must be non-empty"
        )


def test_tv_db_bridge_06_distinct_payloads_distinct_hashes(tmp_path):
    """Negative control: distinct payload bytes → distinct
    ``output_payload_sha256``."""
    sink_a = io.StringIO()
    sink_b = io.StringIO()
    pre = _make_writer(tmp_path, sink_a, _PRE_FRAMEWORK_VERSION)
    run = _make_writer(tmp_path, sink_b, _WAKIR_RUNTIME_VERSION)

    evt_pre = pre.emit("reply", b"payload-A", ts_utc=_TS)
    evt_run = run.emit("reply", b"payload-B-different", ts_utc=_TS)

    assert evt_pre.output_payload_sha256 != evt_run.output_payload_sha256, (
        "distinct payloads must yield distinct output_payload_sha256 "
        "(collision negative control)"
    )


def test_tv_db_bridge_07_pre_framework_version_string_accepted(tmp_path):
    """``engine_version="pre-framework-tomas"`` is accepted verbatim
    (engine_version is opaque per Spec §3.7-bridge-audit; the audit
    substrate parses it, the writer does not validate it)."""
    sink = io.StringIO()
    w = _make_writer(tmp_path, sink, _PRE_FRAMEWORK_VERSION)
    evt = w.emit("reply", b"payload", ts_utc=_TS)
    assert evt.engine_version == _PRE_FRAMEWORK_VERSION


def test_tv_db_bridge_08_wakir_runtime_sink_json_roundtrip(tmp_path):
    """Wakir-Runtime sink line parses as JSON for both engines
    (the audit substrate's NATS-KV forwarder relies on this)."""
    sink_pre = io.StringIO()
    sink_run = io.StringIO()
    pre = _make_writer(tmp_path, sink_pre, _PRE_FRAMEWORK_VERSION)
    run = _make_writer(tmp_path, sink_run, _WAKIR_RUNTIME_VERSION)
    pre.emit("reply", b"p1", ts_utc=_TS)
    run.emit("reply", b"p2", ts_utc=_TS)

    pre_line = sink_pre.getvalue().strip()
    run_line = sink_run.getvalue().strip()
    pre_obj = json.loads(pre_line)
    run_obj = json.loads(run_line)

    # Schema present, event_kind canonical.
    for obj in (pre_obj, run_obj):
        assert obj["schema"] == ENGINEERING_OUTPUT_SCHEMA
        assert obj["event_kind"] == "engineering_output"

    # Engine discriminator preserved through sink.
    assert pre_obj["engine_version"] == _PRE_FRAMEWORK_VERSION
    assert run_obj["engine_version"] == _WAKIR_RUNTIME_VERSION
