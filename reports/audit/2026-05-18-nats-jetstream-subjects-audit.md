# NATS-JetStream Subjects + Publish-Mode Audit

- Generated: `2026-05-18T20:00:00Z`
- Repo root: `/var/home/fred/AI-Corp/.worktree-selin-tag43-nats-audit-runtime`
- Scanned files (Python + Rust): 259
- Total drift rows: **0**

This report mirrors `docs/audit/nats-jetstream-subjects-audit.md`. See that document for the audit charter, exclusion rules, and remediation guidance.

## 1. Inventory — publish/subscribe call sites

| File | Line | Kind | Snippet |
|------|-----:|------|---------|
| `wirelang/cli/bridge_forward.py` | 400 | `publish-jetstream` | `await js.publish(` |
| `wirelang/cli/bridge_forward.py` | 406 | `publish-core` | `await nc.publish(subject, canonical)` |
| `wirelang/persona_engine/cli.py` | 368 | `subscribe-core` | `sub = await nc.subscribe(` |
| `wirelang/persona_engine/cli.py` | 379 | `subscribe-core` | `sub = await nc.subscribe(subscribe_subject)` |
| `wirelang/persona_engine/nats_subscribe_loop.py` | 916 | `subscribe-core` | `sub = await nc.subscribe(subject, cb=_msg_handler)` |
| `wirelang/persona_engine/nats_subscribe_loop.py` | 963 | `subscribe-core` | `sub = await nc.subscribe(subject)` |

## 2. Subject-Pattern-Drift Check

- Total wakir.* literals: 24 (NATS subjects: 7, namespace-ids: 17)
- Drift rows: **0**

_No subject-pattern drift detected — every `wakir.<env>.*` literal matches the canonical `wakir.<env>.<domain>.<event>[.<sub_id>]` form._

<details><summary>17 namespace-id literal(s) (informational, not drift)</summary>

| File | Line | Literal | Detail |
|------|-----:|---------|--------|
| `infra/spire/agent/bin/spire_agent_fed_attest.py` | 57 | `wakir.test` | literal 'wakir.test' uses wakir.* namespace but is not a wakir.<env>.* NATS subject (likely a metric/schema-id) |
| `scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.py` | 743 | `wakir.persona.welle-6.smoke` | literal 'wakir.persona.welle-6.smoke' uses wakir.* namespace but is not a wakir.<env>.* NATS subject (likely a metric/schema-id) |
| `scripts/spiffe_skizze_constants.py` | 39 | `wakir.local` | literal 'wakir.local' uses wakir.* namespace but is not a wakir.<env>.* NATS subject (likely a metric/schema-id) |
| `scripts/welle-1-2-doppel-telemetry-emitter.py` | 162 | `wakir.persona-engine.welle-1-2-doppel-telemetry.v1` | literal 'wakir.persona-engine.welle-1-2-doppel-telemetry.v1' uses wakir.* namespace but is not a wakir.<env>.* NATS subject (likely a metric/schema-id) |
| `scripts/welle-3-telemetry-emitter.py` | 148 | `wakir.persona-engine.welle-3-telemetry.v1` | literal 'wakir.persona-engine.welle-3-telemetry.v1' uses wakir.* namespace but is not a wakir.<env>.* NATS subject (likely a metric/schema-id) |
| `wirelang-rust/crates/persona-engine-format/src/lib.rs` | 435 | `wakir.persona.id` | literal 'wakir.persona.id' uses wakir.* namespace but is not a wakir.<env>.* NATS subject (likely a metric/schema-id) |
| `wirelang-rust/crates/persona-engine-format/src/lib.rs` | 436 | `wakir.persona.hash` | literal 'wakir.persona.hash' uses wakir.* namespace but is not a wakir.<env>.* NATS subject (likely a metric/schema-id) |
| `wirelang-rust/crates/persona-engine-format/src/lib.rs` | 437 | `wakir.persona.schema_version` | literal 'wakir.persona.schema_version' uses wakir.* namespace but is not a wakir.<env>.* NATS subject (likely a metric/schema-id) |
| `wirelang-rust/crates/persona-engine-loop-latency-bench/src/lib.rs` | 184 | `wakir.{}.agent.agent.task.assigned.{}` | template 'wakir.{}.agent.agent.task.assigned.{}' uses wakir.* namespace but is not a wakir.{env}.* NATS subject template (likely a metric/schema-id template) |
| `wirelang-rust/crates/persona-engine-loop-latency-bench/src/lib.rs` | 346 | `wakir.{}.agent.agent.task.assigned.{}` | template 'wakir.{}.agent.agent.task.assigned.{}' uses wakir.* namespace but is not a wakir.{env}.* NATS subject template (likely a metric/schema-id template) |
| `wirelang/adapters/spiffe_workload_api.py` | 323 | `wakir.local` | literal 'wakir.local' uses wakir.* namespace but is not a wakir.<env>.* NATS subject (likely a metric/schema-id) |
| `wirelang/builder/frame_builder.py` | 36 | `wakir.core` | literal 'wakir.core' uses wakir.* namespace but is not a wakir.<env>.* NATS subject (likely a metric/schema-id) |
| `wirelang/builder/frame_builder.py` | 79 | `wakir.meta.` | literal 'wakir.meta.' uses wakir.* namespace but is not a wakir.<env>.* NATS subject (likely a metric/schema-id) |
| `wirelang/builder/frame_builder.py` | 206 | `wakir.treasury.read` | literal 'wakir.treasury.read' uses wakir.* namespace but is not a wakir.<env>.* NATS subject (likely a metric/schema-id) |
| `wirelang/identity/did_document.py` | 58 | `wakir.dev` | literal 'wakir.dev' uses wakir.* namespace but is not a wakir.<env>.* NATS subject (likely a metric/schema-id) |
| `wirelang/persona_engine/observability.py` | 644 | `wakir.persona_engine` | literal 'wakir.persona_engine' uses wakir.* namespace but is not a wakir.<env>.* NATS subject (likely a metric/schema-id) |
| `wirelang/persona_engine/observability.py` | 645 | `wakir.persona_engine` | literal 'wakir.persona_engine' uses wakir.* namespace but is not a wakir.<env>.* NATS subject (likely a metric/schema-id) |

</details>

## 3. Mode-Cross-Validation (Bug-42 Adapter-B)

- Modules in scope: 3
- Adapter-incomplete rows: **0**

| File | Verdict | Detail |
|------|---------|--------|
| `wirelang/cli/bridge_forward.py` | `ok` | module dispatches both nc.publish and js.publish with publish-mode discriminator — Adapter-B complete |
| `wirelang/persona_engine/cli.py` | `no-publish-mode` | module references publish-mode discriminator but has no publish call — likely a contract or helper |
| `wirelang/persona_engine/publish_mode_contract.py` | `no-publish-mode` | module references publish-mode discriminator but has no publish call — likely a contract or helper |

## 4. Adapter-Config-Audit (require_compatible gate)

- Modules in scope: 3
- Preflight-gate-missing rows: **0**

| File | Verdict | Detail |
|------|---------|--------|
| `wirelang/cli/bridge_forward.py` | `publisher-no-gate` | module imports publish_mode_contract and publishes but has no subscribe call — gate responsibility is on the subscriber counterpart (informational, not drift) |
| `wirelang/persona_engine/cli.py` | `ok` | module imports contract, calls require_compatible, and dispatches publish/subscribe — Bug-42 gate in place |
| `wirelang/persona_engine/nats_subscribe_loop.py` | `no-contract-import` | module has publish/subscribe call(s) but does not import publish_mode_contract — caller-side gate responsibility unknown |

## 5. Recommended fixes

_No drift detected. The codebase is Bug-42-compliant: every publish-mode-aware module either gates with `require_compatible` or dispatches both `nc.publish` and `js.publish` consistently with its publish-mode discriminator._

---
Generated by `scripts/audit/nats-jetstream-subjects-audit.py` (Selin, Tag-43).
