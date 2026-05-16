<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Wakir Labs contributors
-->

# persona-engine-subscribe-loop

Initial Rust scaffold of the persona-engine NATS Subscribe-Loop
(Phase-3a Item 4, ADR-0063 §Folgeartefakte).

## Purpose

First substantive Rust implementation of a persona-engine module.
The Python reference implementation lives at
`wirelang/persona_engine/nats_subscribe_loop.py` (Selin Bug-42-Fix
PR #79, Sprint-Pengine-13). This crate is the third leg of the
Doppelbetrieb-Konsistenz triangle (Selin PR #113) — Python /
audit-substrate / Rust.

## Scope of this scaffold

The crate intentionally does **not** open a live NATS socket. The
`async-nats` dependency is declared so that the Phase-3a live-binding
follow-up can extend `run_subscribe_loop` to a real NATS subscription
without revisiting the crate-choice decision.

The smoke-test surface uses an in-process
`tokio::sync::mpsc::Receiver<SubscribeMessage>` instead of a real
NATS server — this is the same posture as the Python hermetic-test
surface (`run_with_iterator(asyncio.Queue)`).

## Public surface

| Type / fn | Parity reference |
|---|---|
| `SubscribeLoopConfig` | Python `SubscribeLoopConfig` (sprint subset) |
| `SubscribeLoopState` | Python `TaskProcessingTracker` + Sprint-SRE Tag-15 lag |
| `SubscribeMessage` | Python `InboundMessage` protocol |
| `MessageHandler` trait | Python `LlmCallHook` + `_handle_message_inner` |
| `ParsedEnvelope` | Python `ParsedAuftrag` |
| `parse_inbound_envelope` | Python `parse_inbound_envelope` |
| `build_subscribe_subject` | Python `build_subscribe_subject` |
| `compute_subscribe_lag_seconds` | Python `_compute_subscribe_lag_seconds` |
| `utc_now_rfc3339` | Python `_utc_now_rfc3339` |
| `run_subscribe_loop` | Python `NatsSubscribeLoop.run_with_iterator` |
| `run_subscribe_loop_with_timeout` | (Rust-only convenience) |

## Hard-Constraints (verified)

- No touches to `wakir-runtime/wirelang/` (Python engine unchanged).
- No `LICENSING/` / `NOTICE` / `.github/workflows/` touches.
- `cargo test -p persona-engine-subscribe-loop` runs green.
- `cargo clippy -p persona-engine-subscribe-loop --tests -- -D warnings` clean.

## ADR anchors

- ADR-0063 §Folgeartefakte Phase-3a Item 4 — initial Rust scaffold.
- Selin PR #79 — Schema-Quelle, Bug-42 fix.
- Selin PR #113 — 3-way-triangle Doppelbetrieb.
- Selin PR #118 — rust-adapter-hook skeleton.
- Reza PR #120 — Phase-3a crate-smoke (dependency-island precedent).
