<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Phase-2 Doppelbetrieb-Bridge — Acceptance Gates

**Status:** Living operations document.
**Scope:** Cross-language acceptance criteria for the Phase-2 / Phase-3a
Doppelbetrieb-Bridge between the Python `wirelang.persona_engine` and
the Rust `wirelang-rust/crates/persona-engine-*` substrate.
**Last update:** 2026-05-17 (Tag-14 Mini-Welle —
Bridge-Audit-Roundtrip-E2E acceptance criterion added, gate #4).

---

## 1. Purpose

During the four-week Phase-3a Doppelbetrieb-Vergleich window the Python
persona-engine and the Rust persona-engine run in parallel. Both
implementations MUST produce byte-identical engineering-output
envelopes for the same logical input — otherwise the cutover from
Python to Rust as the engine-of-record cannot be trusted.

This document inventories the acceptance gates that turn that contract
into testable CI signals. Each gate corresponds to one or more
hermetic test files; a gate is "green" when every test in its file
passes on the production CI lane.

The gate list grows monotonically: once a gate is added it stays in
the inventory (gates may evolve their assertions; they are not
removed). A gate that flips red blocks the Doppelbetrieb-Vergleich
acceptance — the four-week clock pauses until the regression is
fixed.

---

## 2. Acceptance gates (current)

### Gate 1 — Per-envelope JCS pin (Python writer)

**Test file:** `wirelang/tests/persona_engine/test_bridge_audit_writer.py`.

The Python `EngineeringOutputEvent.to_jcs_bytes()` output is byte-pinned
to a known fixture. Drift in field-order, missing fields, or coercion
quirks (e.g. integer-to-float widening) fails the gate.

This is the source-of-truth gate: every other Doppelbetrieb gate
hashes envelopes whose canonical bytes are pinned here.

### Gate 2 — Per-envelope JCS pin (Rust pendant)

**Test file:**
`wirelang-rust/crates/persona-engine-bridge-audit-replay/tests/replay_smoke_test.rs`,
vectors 2-4.

The Rust `AuditRecord::to_envelope()` + `jcs_hash()` output is
byte-pinned to the same fixture as Gate 1 record-for-record. If
either Gate 1 or this gate moves, both must move together — a
divergence here is a cross-language contract break.

### Gate 3 — Single-envelope drift oracle (Python ↔ Rust)

**Test files:**
- `wirelang/tests/persona_engine/test_bridge_audit_diff_engine.py` (Python).
- `wirelang-rust/crates/persona-engine-bridge-diff/tests/` (Rust).

The diff-engine pair detects single-envelope drift between Python and
Rust outputs. Both sides emit the same `value-mismatch` / `only-in-a`
/ `only-in-b` / `type-mismatch` alphabet so an operator's tooling
works against either side's JSON report.

### Gate 4 — Stream-level roundtrip E2E (Python emit ↔ Rust replay)

**Test file:** `tests/integration/test_bridge_audit_roundtrip_e2e.py`.

This is the **stream-level** acceptance gate added in Tag-14 Mini-Welle
(2026-05-17). The roundtrip wires the production-side Python emit
path to the Rust replay engine end-to-end:

1. Python `BridgeAuditWriter.emit()` produces a real
   `EngineeringOutputEvent` sequence into a hermetic
   `io.StringIO` sink.
2. Python `wirelang.persona_engine.bridge_audit_stream_hash.records_to_jsonl_bytes()`
   serialises the sequence as JSONL (one JCS-canonical envelope per
   line) to a temp file.
3. Rust `replay_cli --actual <path> [--expected <path>]` consumes
   the JSONL, runs `ReplayEngine::replay_stream()`, and emits a
   JSON CliReport on stdout.
4. Python asserts:
   - Python-computed `stream_hash(events)` equals the Rust-reported
     `stream_hash_actual` / `stream_hash_expected` (cross-language
     stream-hash pin).
   - Rust report's `divergences` list is empty on clean-stream match.
   - `time_to_divergence_steps` is `None` on clean-stream match;
     a pinned step-index on injected drift.

Three drift scenarios are covered by the gate:

| Scenario | What changes | Expected outcome |
|---|---|---|
| Clean-stream-match | 5-record emit replayed against itself | `success=True`, `divergences=[]`, `time_to_divergence_steps=None` |
| Single-record-divergence | Step-2 `output_kind` mutated `tool_call` → `audit_annotation` | `success=False`, `time_to_divergence_steps=2`, one `value-mismatch` divergence with `/output_kind` in field-diff paths |
| Missing-record-detection | Actual stream truncated to first 3 of 5 records | `success=False`, `time_to_divergence_steps=3`, two `missing-in-actual` divergences at steps 3+4 |

Plus the symmetric `extra-in-actual` case (test 10), the canonical F3
fixture round-trip (test 11), the blank-line-tolerance case (test 12),
and the binary-discovery / exec-bit guards (tests 13-14).

The gate also pins the three cross-language stream-hash anchors:

| Fixture | Records | Hash |
|---|---|---|
| F1 | empty | `sha256:64d11dbb5fe0c2c5e807d22438aedf3912852d81717e532f5c9d2750afa15469` |
| F2 | F3 record-0 only | `sha256:5d259cab58d5d75772f230ac86d18b6a61fd228829cea7aa1887e98cea3cc770` |
| F3 | 3-record session | `sha256:fca1381878f461ea00520d9ee87d3e8c5b536e028e368c002f8de56d8b643bd4` |

These are the canonical references — any new substance touching either
the Python `record_envelope()` / `stream_envelope()` builders or the
Rust `AuditRecord::to_envelope()` / `stream_hash()` builders MUST keep
all three pins green.

**CI binding.** The gate runs in the `production-suite` job of
`.github/workflows/tests.yml`. The job builds `replay_cli` via
`cargo build -p persona-engine-bridge-audit-replay --bin replay_cli`
and exports `WAKIR_REPLAY_CLI_BIN` for the integration-test discovery
helper. Without the binary the test SKIPs its E2E lane (7 Python-only
tests still pass); the CI-built binary turns those 7 skips into 14
passes.

---

## 3. Hermetic envelope

Every gate above is hermetic:

- No live NATS, no live network, no container runtime.
- All filesystem writes go to `tempfile.TemporaryDirectory()` /
  pytest `tmp_path` / the `CARGO_TARGET_DIR` build tree.
- The Pre-Framework Markdown sink path is pinned inside `tmp_path` in
  Gate 4 so the writer's default `/var/lib/wakir/...` path does not
  affect the test.

The hermetic envelope is what lets these gates run on any CI runner
without a side-channel between runs. A Doppelbetrieb-Vergleich gate
that depended on operator-substrate state would be far harder to keep
green for the four-week window.

---

## 4. What is NOT in scope

- **Live engine re-execution.** "Replay" in Gate 4 means re-walking a
  recorded record sequence against an expected trajectory — not
  re-running the persona-engine itself. Engine re-execution is
  out-of-scope; the V-907 pin-pack cross-check is the separate
  acceptance for that surface.
- **Live NATS / state-pack persistence.** The stream-hash-pin gates
  cover the in-memory envelope contract. Persistence on NATS-KV is
  a separate substrate; its acceptance lives in the
  `wakir-runtime/tests/wat/` and `tests/infra/` lanes.
- **Persona-side V-907 drift.** Persona-hash drift fails the V-907
  recompute-bench (separate crate); the Doppelbetrieb gates assume
  V-907 is stable.

---

## 5. Adding a new gate

Each new gate is one PR. The PR MUST:

1. Add the test file (hermetic, no live network).
2. Append a section to §2 above with the test-file path, scenario
   matrix, and CI binding.
3. If the gate consumes a new fixture, pin the fixture hash in BOTH
   the Python and Rust sides of the contract (Gate 1 + Gate 2 are
   the pattern).
4. Document the failure mode: what does a red gate mean for the
   four-week Doppelbetrieb-Vergleich clock?

Gates are accreted, not replaced.

---

## 6. Open items

* **Gate 5 (proposed):** 1000-event mock-trace stream-hash pin. The
  current Gate 4 fixture is 3-record (canonical F3) plus a 5-record
  writer emit. A scale-test gate that pins a 1000-event trace would
  add confidence that the JCS canonicaliser stays byte-stable at
  realistic session lengths. Out of scope for Tag-14; candidate for
  Phase-3a Sprint-1.
* **Gate 6 (proposed):** Persistence-roundtrip — emit, persist to
  NATS-KV stream, replay from NATS-KV. Pending NATS-KV Tag-N+
  integration; out-of-scope for Tag-14.
* **Cross-org gate (proposed):** When `wakir-protocol` ships its own
  bridge-audit-replay pendant, the cross-repo-drift gate should
  extend to assert stream-hash agreement across the two repos for
  the same fixtures. Pending `wakir-protocol` substrate;
  out-of-scope for Tag-14.

— Tomás
