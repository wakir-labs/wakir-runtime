<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# persona-engine-loop-latency-bench

End-to-end latency benchmark for the NATS Subscribe-Loop crate
(`persona-engine-subscribe-loop`, Phase-3a Item 4, PR #132).

**Phase-3a Item 15 (LAST) — closes Foundation 15/15.**

## What this measures

For a given target rate (Hz) and duration (sec), drives the
`run_subscribe_loop` driver with `rate_hz * duration_sec` synthetic
envelopes and records the per-frame **wire-receive -> handler-dispatch**
latency in microseconds. Output is a `LatencyReport`:

```json
{
  "rate_hz_target": 100.0,
  "duration_sec": 1,
  "frames_planned": 100,
  "frames_received": 100,
  "frames_processed": 100,
  "frames_dropped": 0,
  "throughput_actual_hz": 100.0,
  "latency_micros": {
    "p50": 120,
    "p95": 480,
    "p99": 950,
    "max": 1200
  }
}
```

## Scope: in-process only

The bench feeds the loop via the same `tokio::sync::mpsc` channel
substrate the loop's smoke-tests use. It does **not** open a NATS
socket — `async-nats` is not exercised. The numbers are therefore a
**lower bound** on production latency: they capture the loop's own
overhead (envelope parse + handler dispatch + state update) but not
the wire-side. A future live-NATS bench can be layered on top
without re-doing the harness.

## Determinism

`SyntheticFrameGen` is a deterministic splitmix64-based PRNG: the
same `(seed, frame_count)` produces the same envelope bytes (down to
`auftrag_id` and `prompt_payload`). Timing numbers are inherently
non-deterministic; unit-tests assert structural properties only.

## Cross-lang comparison

`LatencyReport::to_json_pretty()` emits a stable JSON shape. A future
Python sibling (Selin Sprint-Pengine-13 follow-up) can byte-match
this contract for cross-lang performance-parity audits.

## Usage

```rust
use persona_engine_loop_latency_bench::LoopLatencyBench;

#[tokio::main]
async fn main() {
    let bench = LoopLatencyBench::new(0xCAFE_F00D, "dev", "kai");
    let report = bench.run(100.0, 5).await;  // 100 Hz, 5 sec
    println!("{}", report.to_json_pretty());
}
```

Or synchronously (no `#[tokio::main]` needed):

```rust
let bench = LoopLatencyBench::new(0xCAFE_F00D, "dev", "kai");
let report = bench.run_blocking(100.0, 5);
```

## Operator-hand bench-execution

CI compiles the bench file but does **not** run it (criterion benches
are scheduler-sensitive and would be flaky in CI). To run the bench
locally:

```bash
cargo bench -p persona-engine-loop-latency-bench
```

Three rates run by default (10 Hz / 100 Hz / 1000 Hz over 1 sec each),
each at criterion `sample_size = 10` for a ~30-sec total wall-clock.

## ADR anchors

- ADR-0063 §Folgeartefakte Phase-3a Item 15 (LAST — this crate).
- ADR-0035 Errata 1 — Rust as Phase-1c language for persona-engine.
- Reza PR #132 — subscribe-loop scaffold (Phase-3a Item 4).
- Selin PR #79 — Python schema-parity reference.
