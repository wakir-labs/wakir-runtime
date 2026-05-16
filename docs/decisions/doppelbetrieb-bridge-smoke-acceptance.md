# Decision Note — Doppelbetrieb-Bridge-Smoke Acceptance Surface

<!--
SPDX-License-Identifier: BUSL-1.1
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

**Status:** ACCEPTED — Sprint-10 Tag-9 (2026-05-15 ~23:35 CEST,
Mira-Hand-Welle-Tag-9 auftrag). Implementation-rationale, not an
ADR-vorlage; Tomás-Matrix-Lead-Hut entscheidet die Test-Substanz-
Granularität, Mira-Strategie-Decision bleibt unverändert.

## Context

Sprint-10 Tag-8 Bug-38b activated the federation-mode smoke gate
for the **single-Tomás** path (one persona-engine container per
side). Sprint-Pengine-12 (PR #75 merged 2026-05-15 ~20:30 CEST)
landed persona-engine `0.4.2-pilot` with CLI-async-wrap + auto
subscribe-loop activation — that is the **wakir-runtime Tomás**
binary.

The Doppelbetrieb-Vergleich-4-Wochen-Clock (Spec §3.7-bridge-audit)
runs **two** Tomás emissions in parallel:

1. **Pre-Framework Tomás** — the Operator-Hand-spawned
   Claude-Code-Subagent (Mira-Sandbox or claude-dev Sandbox). This
   is the incumbent emission source; it ran in production before
   `wakir-runtime` persona-engine existed.

2. **Wakir-Runtime Tomás** — the `wakir-persona-engine:0.4.2-pilot`
   container. This is the Phase-3-Production target.

Both emit engineering output (replies, tool-calls, audit-annotations)
into the **same** WAT-Anchor pipeline (Pre-Framework Markdown sink
at `/var/lib/wakir/persona/tomas/bridge-audit.md` + Wakir-Runtime
JSON envelope on stderr → `podman logs` → NATS-KV state-pack bucket
via Sprint-9 Tag-1 forwarder chain).

The audit substrate then **compares** the two emission streams
byte-for-byte to validate that the wakir-runtime engine reproduces
the incumbent Pre-Framework behaviour exactly. After 4 weeks of
clean comparison, the Pre-Framework spawn is retired (Phase-3-Cut).

## Question

How does the Doppelbetrieb-Bridge-Smoke acceptance surface have to
be shaped so that the 4-Wochen-Vergleich is hermetically testable
and the operator-side runtime invariant cannot drift silently?

## Decision

The Doppelbetrieb-Bridge-Smoke is shaped around two hermetic
invariants, exercised in `tests/infra/test_doppelbetrieb_bridge_smoke.py`
(8 test-vectors):

### Invariant 1 — Payload-Hash Agreement

When both engines emit the same semantic payload bytes (the actual
reply or tool-call payload bytes), the envelope's
`output_payload_sha256` field MUST be identical across engines.

Rationale: the hash is engine-version-agnostic — `BridgeAuditWriter`
computes it as `sha256(payload_bytes)`. The hash is the substrate
the audit substrate uses to detect "did the wakir-runtime engine
produce a payload that matches the Pre-Framework engine, byte-for-
byte?" If the hash drifts engine-side (e.g. encoding bug), the
4-Wochen-Vergleich is meaningless.

Test-vector: `TV-DB-BRIDGE-01` (positive) + `TV-DB-BRIDGE-06`
(negative control — distinct payloads must yield distinct hashes).

### Invariant 2 — Engine-Version Discrimination

The envelope's `engine_version` field MUST differ between
Pre-Framework and Wakir-Runtime emissions so the audit substrate can
attribute each emission to its origin engine.

Rationale: without the discriminator, the audit substrate cannot
compute per-engine byte-for-byte equivalence — it would see a
single undifferentiated stream of `(payload_hash, ts_utc)` tuples
and could not match Pre-Framework emission n with Wakir-Runtime
emission n. The convention:

- Pre-Framework spawn sets `engine_version="pre-framework-tomas"`
  (string literal, opaque per Spec).
- Wakir-Runtime container sets
  `engine_version="0.4.2-pilot"` (or whichever tag the running
  container carries; the persona-engine CLI auto-discovers from
  `pyproject.toml` per Sprint-Pengine-12).

Test-vector: `TV-DB-BRIDGE-02` (discrimination present) +
`TV-DB-BRIDGE-05` (mandatory non-empty) + `TV-DB-BRIDGE-07`
(`engine_version` is opaque — `BridgeAuditWriter` accepts any string,
no validation).

### Auxiliary invariants (3 vectors)

- `TV-DB-BRIDGE-03` — JCS canonical envelope keys are alphabetical
  (byte-stable across emissions and engines). This is the JCS
  RFC-8785 conformance check.

- `TV-DB-BRIDGE-04` — Both writers' Pre-Framework Markdown sinks
  can share a single file path (single-writer-per-sink is NOT
  enforced at the write boundary; the audit substrate handles
  ordering on the NATS-KV side).

- `TV-DB-BRIDGE-08` — Wakir-Runtime sink JSON line parses cleanly
  through `json.loads` for both engines (the audit substrate's
  NATS-KV forwarder relies on this).

## Acceptance criteria

- **Hermetic test suite** in
  `tests/infra/test_doppelbetrieb_bridge_smoke.py` with 8 PASS
  test-vectors.
- **`BridgeAuditWriter` engine-side caller** in
  `wirelang/persona_engine/bridge_audit_writer.py` is unchanged
  in this sprint — Tag-9 locks the invariants that Sprint-Pengine-8
  already shipped (PR #65 merged 2026-05-15 14:22 UTC).
- **Live-VM-Lane** that exercises real Pre-Framework + Wakir-Runtime
  emission on the same Pilot-VM is **Operator-Hand**, not
  Sandbox-testable. Tag-9 hermetic substrate is the prerequisite
  for the Operator-Hand probe; without these invariants locked,
  the Operator-Hand probe cannot validate.

## What this is NOT

- This is NOT a Live-VM bring-up. The Doppelbetrieb-Bridge-Smoke
  Live-Lane has to wait for the Operator-Hand because
  `feedback_sandbox_host_trennung.md` is in effect — the
  claude-dev Sandbox cannot reach the Pilot-VM.

- This is NOT a NATS-KV-substrate test. The
  `BridgeAuditWriter._write_wakir_runtime_sink` path writes to a
  generic `TextIO` — production wiring of that stderr stream into
  the NATS-KV bucket is the audit substrate's job (Sprint-9 Tag-1
  forwarder chain), not the persona-engine's.

- This is NOT a Spec §3.7-bridge-audit normative re-statement. The
  invariants here are the **engine-side caller's** responsibilities;
  the audit-substrate-side invariants (NATS-KV write ordering,
  4-Wochen-Vergleich computation, retire-cut-off semantics) live
  elsewhere.

## Operator-Hand follow-up

When the next Mira-Hand-Live-VM probe runs on `wakir-orbit` (Tag-9
re-run after merge), the expected Doppelbetrieb-Bridge-Smoke output:

1. Pre-Framework spawn writes one `## step 0 — reply` section to
   `/var/lib/wakir/persona/tomas/bridge-audit.md` with
   `engine_version="pre-framework-tomas"`.
2. Wakir-Runtime persona-engine container writes one section with
   `engine_version="0.4.2-pilot"`.
3. Both sections carry the **same** `output_payload_sha256` if
   the payload bytes match.

If (3) FAILS on the Pilot-VM with same-payload divergent hashes,
that is a **substance bug** (encoding drift between the two engines)
and not a Live-VM bring-up issue — the hermetic substrate locks the
hash-agreement invariant, so divergence has to be an upstream
payload-encoding bug.

— Tomás
