# Phase-3c Welle-3 Cutover-Smoke Runbook (`bridge_audit_writer`)

| Field | Value |
|---|---|
| Owner | Selin Çelik (Persona-Engine), Tomás Reinhart (Matrix-Lead), Henrik Voss (Caution-Owner) |
| ADRs | [0065](../../decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md), [0066](../../decisions/0066-phase-3c-doppel-cutover-acceleration-kw24.md) |
| Script (Python) | [`scripts/phase-3c/welle-3-bridge-audit-writer-cutover-smoke.py`](../../scripts/phase-3c/welle-3-bridge-audit-writer-cutover-smoke.py) |
| Script (Bash wrapper) | [`scripts/phase-3c/welle-3-bridge-audit-writer-cutover-smoke.sh`](../../scripts/phase-3c/welle-3-bridge-audit-writer-cutover-smoke.sh) |
| Tests | [`tests/phase_3c/test_welle_3_cutover_smoke.py`](../../tests/phase_3c/test_welle_3_cutover_smoke.py) (15 tests) |
| Sibling | [`docs/phase-3c/welle-2-cutover-smoke.md`](welle-2-cutover-smoke.md), [`docs/phase-3c/welle-1-cutover-smoke.md`](welle-1-cutover-smoke.md), [`docs/operations/welle-3-day-0-pipeline-runbook.md`](../operations/welle-3-day-0-pipeline-runbook.md) |

## Purpose

This runbook describes the **End-to-End Cutover-Smoke** for ADR-0066
Welle-3 (`bridge_audit_writer`), the **KW-25 solo wave**.
Welle-3 is the structurally riskiest of the seven Phase-3c waves
because the focus-component (`bridge_audit_writer`) is the module
that emits the EngineeringOutputEvent audit envelopes — i.e. the
audit stream that the Doppelbetrieb-Shadow phase consumes to
compare Pre-Framework vs. Wakir-Runtime output byte-for-byte. When
this module itself cuts over, any naïve audit-stream observation
taken from *during* the cutover is describing its own switch.
Henrik (Internal Audit) flagged this as the
**Consistency-Oracle-Selbst-Cutover-Risiko** during the ADR-0066
review (or, in Selin-shorthand: **Self-Reference-Trap**).

The smoke is **not** the Monday Live-Smoke (that one is Pilot-VM
operator-hand-territory). It is the local-hermetic precursor: it
exercises the full pre-cutover / cutover-step / post-cutover /
rollback shape against the real
`resolve_bridge_audit_writer_backend` resolver (or the local shim
when the upstream resolver is not yet wired) and emits a tri-state
exit code that the operator can wire into shell gates and PR
checks.

## Self-Reference-Trap mitigation (substance, not ceremony)

The Welle-3 smoke adds **two** Welle-3-specific asserts on top of
the Welle-1/2 shape (A1..A5 + R1):

* **A6 bridge-audit-stream pre/post parity:** the smoke captures a
  deterministic audit-stream-hash by directly invoking
  `EngineeringOutputEvent.to_jcs_bytes()` against a fixed 3-emission
  fixture **BEFORE the cutover-step constructs the `PHASE_POST`
  env-map**. The same Python authority recomputes the hash
  post-cutover and the two hashes must be byte-equal. The substrate
  oracle is "the Python JCS encoder is byte-stable across the
  pre/post window" — the only oracle that does **not** fall into
  the circular-oracle trap. The Rust pendant byte-parity is pinned
  at a separate substrate layer (the F1/F2/F3 stream-fixture pins
  in `tests/fixtures/bridge-audit-writer-cross-lang/fixtures.json`,
  PR #210 `0168ac3`). Severity: **caution**.
* **A7 Self-Reference-Trap-Mitigation control:** verifies the
  control-flow invariant directly: the envelope's
  `baseline_captured_at_phase` field MUST equal
  `pre_cutover_python_baseline`. Any other value indicates a
  smoke-refactor regression that re-introduced the exact
  circular-oracle pattern Henrik flagged. Severity: **blocker** — a
  fail here halts the cutover, not because the engine is broken but
  because the smoke can no longer trust its own evidence. Henrik
  reviews this assert on every Welle-3 audit.

The other five engine-emission-level asserts (A1..A5 + R1) mirror
the Welle-1/2 shape verbatim, re-pointed at `bridge_audit_writer`
and `WAKIR_BRIDGE_AUDIT_WRITER_BACKEND`.

## Substrate inventory

| Substrate | PR | Commit | Role |
|---|---|---|---|
| Rust-CLI Container-Image-Build-Pipeline | [#210](https://github.com/wakir-labs/wakir-runtime/pull/210) | `0168ac3` | The Welle-3 Quadlet image (`wakir-persona-engine-bridge-audit-writer`). |
| Welle-3 Day-0 Operator-Pipeline | [#222](https://github.com/wakir-labs/wakir-runtime/pull/222) | Tag-32 | The operator-side orchestrator that calls this smoke as one gate. |
| Welle-3 Live-Telemetry-Setup | [#206](https://github.com/wakir-labs/wakir-runtime/pull/206) | Tag-31 | The high-frequency consistency-score emitter (ADR-0066 Mitigation-2). |
| Cosign-Policy 9-Binary | [#180](https://github.com/wakir-labs/wakir-runtime/pull/180), [#187](https://github.com/wakir-labs/wakir-runtime/pull/187) | Tag-23/24 | bridge-audit-writer signing-key surface. |
| Bridge-Audit-Writer Cross-Lang Pins | [#210](https://github.com/wakir-labs/wakir-runtime/pull/210) | `0168ac3` | F1/F2/F3 fixture vectors A6 cross-checks (Python JCS encoder byte-stability). |
| federation_resolver wire-in | [#200](https://github.com/wakir-labs/wakir-runtime/pull/200) | `1ea7a60` | 9th BackendDecision; baseline default `--expected-components 9`. |
| bridge_audit_writer resolver wire-in (Reza-Tag-36) | pending | — | Once landed, operators flip `--expected-components 10`; the smoke transparently switches resolver-provenance from `"shim"` to `"upstream"`. |

## Resolver-provenance (shim vs. upstream)

As of baseline `2ec0532` (Tag-35 tip), `wirelang.persona_engine.
rust_backend_switch` exposes `BRIDGE_AUDIT_WRITER_BACKEND_ENV`,
`BridgeAuditWriterBackend`, and `_resolve_bridge_audit_writer_bin`,
but the public resolver function
`resolve_bridge_audit_writer_backend(env, log_sink, binary_probe)`
is **not yet shipped**. The Reza-Tag-36 wire-in is scheduled to add
it.

This smoke handles both worlds via a resolver-shim:

* If the imported resolver module exposes
  `resolve_bridge_audit_writer_backend` (Reza-Tag-36 wire-in landed),
  the smoke uses it end-to-end and the envelope's
  `resolver_provenance.bridge_audit_writer` field reports
  `"upstream"`. Operators run with `--expected-components 10`.
* Otherwise, the smoke constructs a local shim that wraps the
  existing env-var + bin-resolver + `_binary_available` primitives
  to produce a BackendDecision with the same byte-shape as the
  other resolvers. The envelope's `resolver_provenance.
  bridge_audit_writer` field reports `"shim"`. Operators run with
  `--expected-components 9` (baseline inventory).

When Reza's wire-in lands, the same smoke script switches
provenance transparently — no smoke change required. The operator
only flips the `--expected-components` value from 9 to 10.

## Operator usage

```bash
# Baseline run (pre-Reza-Tag-36 wire-in): 9 expected components,
# resolver-shim used for bridge_audit_writer.
python3 scripts/phase-3c/welle-3-bridge-audit-writer-cutover-smoke.py \
    --expected-components 9 \
    --output out/welle-3-smoke.json
echo "exit=$?"

# Post-Reza-Tag-36-wire-in run: 10 expected components, upstream
# resolver used end-to-end.
python3 scripts/phase-3c/welle-3-bridge-audit-writer-cutover-smoke.py \
    --expected-components 10 \
    --output out/welle-3-smoke.json

# Same via the bash wrapper.
bash scripts/phase-3c/welle-3-bridge-audit-writer-cutover-smoke.sh \
    --expected-components 10 \
    --output out/welle-3-smoke.json

# Tighter latency tolerance (10 % instead of ADR-0065 §AC-2 20 %).
python3 scripts/phase-3c/welle-3-bridge-audit-writer-cutover-smoke.py \
    --latency-tolerance-pct 10

# Skip the A6 bridge-audit-stream-parity probe (e.g. when the
# wirelang package is not importable in the run environment, such
# as a minimal CI lane). A7 is also skipped when A6 is skipped.
python3 scripts/phase-3c/welle-3-bridge-audit-writer-cutover-smoke.py \
    --skip-bridge-audit-stream-parity
```

## KW-25 solo-wave sequencing

Per ADR-0066 §Welle-3-Sequencing, Welle-3 runs **solo** — no parallel
partner. The Mo-Operator-Hand window:

1. Run **Welle-3** smoke → expect `band=GREEN`, exit 0.
2. Verify the JSON envelope attaches cleanly to the cutover PR.
3. Proceed to the Pilot-VM Live-Smoke per ADR-0065
   §Verifikations-Plan Mo.
4. **Independent oracle check:** consult the
   `welle-3-telemetry-emitter` (PR #206) high-frequency consistency
   score. The dashboard's `Phase-2-Cross-Modul-Stress-Test-Oracle`
   panel must be GREEN before the operator flips the Quadlet
   default. The dual-oracle posture (smoke A1..A7 + stress-test
   oracle) is the substance of the Henrik-Caution mitigation.

If the smoke reports `band=CAUTION` or `band=ROLLBACK_RECOMMENDED`,
the operator pauses the Welle-3 cutover per ADR-0066 §Welle-3-Halt
(no partner wave to coordinate with, but the Doppelbetrieb-Shadow
phase depends on this module — a half-cut bridge_audit_writer
breaks the substrate-level cross-lang oracle for every downstream
wave).

## Henrik-Caution Decision-Matrix

The smoke evaluates eight checks per run. Each check is tagged as
**blocker** (failure → exit 2 ROLLBACK_RECOMMENDED) or **caution**
(failure → exit 1 CAUTION; mixed blocker+caution → exit 2).

| ID | Check | Severity | Henrik-Caution Item | What it verifies |
|---|---|---|---|---|
| A1 | backend-flip | blocker | — | Every focus-component (`bridge_audit_writer`) BackendDecision on the post-cutover phase reports `chosen_backend == "rust"`. |
| A2 | cross-lang parity-hash | blocker | — | SHA-256 over `(domain, fallback_reason)` for focus-component records is identical between **Post-Cutover-Rust** and **Rollback-Python** (the two clean happy-paths). `requested_backend` and `chosen_backend` are both projected out. Pre-Cutover is the explicit-python branch (`fallback_reason="explicit_python"`) — semantically distinct from implicit-python, compared informationally only. |
| A3 | latency within tolerance | caution | — | P95 focus-component latency on the post-cutover (Rust) path is at most `pre_p95 + tolerance_pct %`. Tolerance defaults to 20 % per ADR-0065 §AC-2. |
| A4 | decision-count in-place | caution | — | Engine emits exactly `expected_components` BackendDecisions per boot. Default tracks the baseline-2ec0532 inventory (9); operators running post-Reza-Tag-36-wire-in pass `--expected-components 10`. |
| A5 | fallback-clean | blocker | — | Zero focus-component records post-cutover carry `fallback_reason`. A fallback means the engine silently dropped back to Python; the audit-record would not say `backend: rust`. **Live-substrate caveat:** if the Quadlet does not yet have the `wakir-persona-engine-bridge-audit-writer` binary deployed, the live operator-VM resolver's `fallback_reason="binary_missing"` is the **expected** signal (ADR-0066 Welle-3 *precondition*, not a smoke bug — operators read it as "Welle-3 image not yet deployed"). |
| R1 | rollback to Python | blocker | — | After unsetting `WAKIR_BRIDGE_AUDIT_WRITER_BACKEND`, every focus-component BackendDecision reports `chosen_backend == "python"`. Verifies the ≤10 min rollback path per ADR-0065 §Rollback-SLA (ADR-0066 inherits the contract). |
| **A6** | **bridge-audit-stream parity** | **caution** | **Henrik-Caution-1: Self-Reference-Trap A** | Hash of the deterministic 3-emission audit-stream captured BEFORE the cutover-step matches the hash recomputed after. The substrate-level oracle is "the Python JCS encoder is byte-stable across the pre/post window". The Rust pendant byte-parity is pinned at the F1/F2/F3 fixture layer (separate substrate). Skipped + reported as `passed=true, skipped=true` when the bridge_audit_writer module or fixtures are missing. |
| **A7** | **Self-Reference-Trap control** | **blocker** | **Henrik-Caution-2: Self-Reference-Trap B** | The envelope's `baseline_captured_at_phase` field MUST equal `pre_cutover_python_baseline`. A fail here means a smoke-refactor accidentally re-introduced the circular-oracle pattern. **Blocker by design**: a broken control-flow invariant means the smoke can no longer trust its own evidence, regardless of whether the engine itself is healthy. Henrik reviews this on every Welle-3 audit. |

## Exit-code interpretation

| Exit | Band | Operator action |
|---|---|---|
| 0 | GREEN | Welle-3 cutover-PR can proceed to the Monday Pilot-VM Live-Smoke per ADR-0065 §Verifikations-Plan. The JSON envelope is admissible as cutover-PR evidence. |
| 1 | CAUTION | At least one caution-severity check failed (A3 latency drift, A4 component-count drift, A6 bridge-audit-stream drift). The engine-emission substance is intact (backend-flip + parity-hash + rollback all OK) and the temporal Self-Reference-Trap-Mitigation invariant (A7) is intact. **Investigate before the Monday Live-Smoke**: latency drift may indicate Rust-binary build-flag drift; component-count drift may indicate engine-inventory drift since the ADR-0066 baseline; A6 drift means the Python JCS encoder shifted between baseline-capture and post-cutover recompute (Tomás-Zone-K cross-review pre-empt). Escalate to Tomás (Matrix-Lead) for go/no-go; if A6 is the failure, copy Henrik (Internal Audit) — the substrate-parity oracle is his caution surface. |
| 2 | ROLLBACK_RECOMMENDED | At least one blocker-severity check failed (A1, A2, A5, A7, or R1). Do not proceed to the Monday Live-Smoke. Open a substance-bug-issue (label `welle-3-smoke-fail`), eskaliert to Priya (CTO) per ADR-0065 §Rollback-Procedure Step 1. **If A7 is the failure**, copy Henrik directly: the Self-Reference-Trap-Mitigation control invariant was violated, and the smoke can no longer trust any A6 evidence on this run. |
| (3+) | (not used by smoke) | I/O failure (`--output` not writable) is reported as exit 2 by convention — operator must consume the evidence before proceeding. |

## Envelope shape

The smoke emits a JSON envelope to `--output` (or stdout). The
top-level keys are:

```text
schema                              "wakir.phase-3c.welle-3-cutover-smoke/1"
timestamp_utc                       POSIX-epoch integer
welle                               3
focus_component                     "bridge_audit_writer"
focus_env_var                       "WAKIR_BRIDGE_AUDIT_WRITER_BACKEND"
engine_boot_components              list of in-place component names (default 10 in smoke; pre-wire-in user passes --expected-components 9)
expected_components                 int (CLI arg)
boots_per_phase                     int (CLI arg)
latency_tolerance_pct               int (CLI arg)
resolver_provenance                 { component_name: "upstream" | "shim" }
self_reference_trap_mitigation      { baseline_captured_at_phase: ..., baseline_stream_sha256: ..., baseline_skipped: ... }
phases                              { "pre_cutover_python_baseline": {...},
                                      "post_cutover_rust":          {...},
                                      "rollback_python":            {...} }
asserts                             { A1..A5, R1, A6, A7 → {passed, severity, ...} }
exit_code                           0 | 1 | 2
band                                "GREEN" | "CAUTION" | "ROLLBACK_RECOMMENDED"
```

Each `phases[*]` sub-record carries `boots`, `decision_count`,
`focus_p95_latency_us`, `parity_hash` (raw, including
`chosen_backend`), and `focus_parity_hash_normalised` (the A2-
relevant projection, with `chosen_backend` stripped).

The A6 record additionally carries `baseline_stream_sha256`,
`recomputed_stream_sha256`, `match`, and `captured_at_phase` so
the operator can pinpoint exactly where the substrate drifted. The
A7 record carries `captured_at_phase` and `expected_phase` so the
operator can see at a glance which phase the baseline was captured
in.

The top-level `self_reference_trap_mitigation` block is the
operator-facing temporal anchor — the one place to look to confirm
the smoke captured the baseline in the right phase.

## Hermeticity contract

The smoke is **stdlib-only** at the engine-emission level. The
optional A6 bridge-audit-stream check imports
`wirelang.persona_engine.bridge_audit_writer` and is **gracefully
skipped** (with `skipped=true, passed=true`) when unavailable. The
smoke never:

* Invokes the real Rust binary (`_binary_available` is stubbed to
  always-true; the smoke focuses on the backend-switch behaviour,
  not the binary-deployment posture — that's a separate Quadlet-
  Installer prerequisite per ADR-0065 §Trigger-Bedingung-3).
* Talks to NATS, the Anthropic API, or any container runtime.
* Mutates `os.environ` (the engine sees a private mapping).

The real-resolver path (`resolve_bridge_audit_writer_backend` once
Reza-Tag-36 wires it; or the local shim wrapping `_resolve_bridge_
audit_writer_bin` + `_binary_available` pre-wire-in) **is**
exercised end-to-end when the wirelang package is importable. The
test suite injects a fully-stubbed resolver module for hermetic CI
lanes.

## Real-resolver verification (Selin-Tag-36)

Selin-Tag-36 ran the smoke locally against the **real** resolver
module at baseline `2ec0532` (resolver-shim path, since
`resolve_bridge_audit_writer_backend` is not yet wired upstream):

```bash
PYTHONPATH=$(pwd) python3 \
  scripts/phase-3c/welle-3-bridge-audit-writer-cutover-smoke.py \
  --boots-per-phase 3 \
  --expected-components 10
# exit=0 (GREEN); A1/A2/A3/A5/A6/A7/R1 all passed;
# A6 reports "bridge-audit-stream parity ok (b1f1ec66250d6a34...)"
# A7 reports "Self-Reference-Trap-Mitigation OK: baseline captured
#   in 'pre_cutover_python_baseline' (pre-cutover)"
# resolver_provenance.bridge_audit_writer == "shim" (as expected
#   pre-Reza-wire-in); all other components == "upstream".
```

The A6 baseline-stream-hash `b1f1ec66250d6a34adfa73911a07d3662924
fa1aa54db612341b3fbd38e0e93d` (SHA-256 over the concatenated
JCS-bytes of the 3-emission `BRIDGE_AUDIT_DETERMINISTIC_EMISSIONS`
fixture, computed via the real
`wirelang.persona_engine.bridge_audit_writer.EngineeringOutputEvent
.to_jcs_bytes`) is the substrate-level oracle pin. The Rust pendant
(once it ships from the `persona-engine-bridge-audit-replay` crate)
must produce byte-equal output against the F1/F2/F3 fixtures in
`tests/fixtures/bridge-audit-writer-cross-lang/fixtures.json`.

## Welle-4..7 forward-compat

The script's focus-component / focus-env-var / engine-boot-components
constants are top-level module symbols. Future Welle-N cutover-smokes
can be written by copying this file and re-pointing those constants
plus the A6-substrate-probe (each wave with cross-lang fixtures will
have its own canonical-snapshot module). The asserts-evaluation logic
is component-agnostic except for the A2 parity-hash projection (uses
the focus-component name verbatim), A6 (bridge-audit-stream-specific
by design; remove or replace for Welle-4+), and A7 (the
Self-Reference-Trap control-flow invariant is Welle-3-specific —
later waves don't have a circular-oracle problem because they
aren't the audit-stream emitter themselves; A7 should be omitted
from Welle-4+ smokes).

## Cross-references

* **ADR-0065** §Verifikations-Plan (decision matrix derives from
  §AC-1..§AC-5 and §Rollback-Procedure).
* **ADR-0066** §Welle-3-Risiken (Henrik-Caution-Findings, KW-25 solo
  posture, Self-Reference-Trap), §Welle-3-Mitigation-2 (high-
  frequency consistency-score emitter as independent oracle).
* **PR #19** Bridge-Audit-Writer (Sprint-1 Tag-4, `2c1f3a6`) —
  EngineeringOutputEvent envelope writer (the substrate this smoke
  exercises for A6).
* **PR #170** Anchor-Emitter Cross-Lang fixtures (Tag-23) — A2
  parity-hash references this as substrate-level oracle.
* **PR #179** BackendDecision Observability (Tag-24) — A3 latency
  tolerance derives from the same percentile machinery this script
  reuses (`_nearest_rank_percentile`).
* **PR #200** federation_resolver wire-in (Tag-30, `1ea7a60`) — the
  9th BackendDecision; baseline-2ec0532 default `--expected-
  components 9` tracks this.
* **PR #206** Welle-3 Live-Telemetry-Setup (Tag-31) — independent
  oracle per ADR-0066 Mitigation-2; the dashboard's stress-test
  oracle panel.
* **PR #210** Bridge-Audit-Writer Container-Image-Build-Pipeline
  (Tag-32, `0168ac3`) — the Welle-3 Quadlet image + F1/F2/F3
  Cross-Lang fixtures.
* **PR #222** Welle-3 Day-0 Operator-Pipeline (Tag-32) — the
  operator-side orchestrator that calls this smoke as one gate.
* **PR #230** Welle-1 v907_verify Cutover-Smoke (Tag-34, `53af6ac`)
  — the sibling Welle-1 script; the smoke pattern.
* **PR #234** Welle-2 svid_workload_identity Cutover-Smoke (Tag-35)
  — the immediate sibling; A1..A5 + R1 pattern verbatim.
* **`docs/phase-3c/welle-1-cutover-smoke.md`** — the Welle-1 runbook.
* **`docs/phase-3c/welle-2-cutover-smoke.md`** — the Welle-2 runbook.
* **`docs/operations/welle-3-day-0-pipeline-runbook.md`** — the
  operator-day-0 orchestrator runbook (Kai Tag-32).

---

_— Selin Çelik (Persona-Engine), Tag-36, 2026-05-18._
