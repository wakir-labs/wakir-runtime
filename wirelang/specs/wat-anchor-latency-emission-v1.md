<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Callandor GmbH and contributors

Licensed under the Creative Commons Attribution 4.0 International
License. Full text: https://creativecommons.org/licenses/by/4.0/
-->

# WAT-Anchor Per-Stage Latency Emission — Producer Contract v1

Version: `wakir-wat-anchor-latency-emission/v1`
Status: stable for Phase 2 operations-reife.
Audience: WAT-anchor pipeline implementers (producer side) and
SRE-owned observability aggregators (consumer side).

## 1. Scope

This document specifies the wire format and the operational semantics
of the per-anchor pipeline-stage latency JSONL stream emitted by the
WAT-anchor pipeline (`wat.anchor.ots_anchor.anchor_root`) and consumed
by the per-anchor latency aggregator
(`scripts/wat-anchor-pipeline-observability.py`, PR #145).

It is a value-derivation contract — the same shape that the consumer
already parses (PR #145 `read_latency_samples`, `_parse_stage_block`),
documented here as a stable cross-module reference so that an external
re-implementer of either side can reproduce the byte-level format.

Rationale for living in the Wirelang spec corpus: the JSONL stream is
a *boundary* between two modules under separate licences (WAT pipeline
under BUSL-1.1; observability scripts under Apache-2.0). The Wirelang
spec tree (`wirelang/specs/`) is the established home for cross-module
data-shape contracts (see `wat-leaf-projection.md` for the parallel
case of the WAT-leaf four-tuple). The CC-BY-4.0 licence on this
document mirrors the rest of the spec corpus.

## 2. Pipeline stages

The WAT-anchor pipeline is decomposed into four sequential stages.
Order is contractual; the consumer assumes a left-to-right reading
when rendering Prometheus histogram-bucket layouts and Grafana panels.

| stage                  | covers                                            |
| ---------------------- | ------------------------------------------------- |
| `enqueue_to_pre_ots`   | argument validation, root.bin write, args build   |
| `ots_call`             | `ots stamp` subprocess invocation                 |
| `post_ots_commit`      | calendar-response parse, threshold check, receipt-file glob |
| `wat_write`            | `AnchorReceipt` dataclass construction (finalise) |

Adding a stage is a schema-version bump (this document → `v2`).
Renaming a stage is a breaking change.

## 3. Wire format

One JSON object per line, append-only, UTF-8, newline-terminated:

```json
{
  "anchor_root_hex": "<64-hex>",
  "timestamp": "<ISO-8601 with Z suffix>",
  "stages": {
    "enqueue_to_pre_ots_ms": <float>,
    "ots_call_ms": <float>,
    "post_ots_commit_ms": <float>,
    "wat_write_ms": <float>
  }
}
```

Field semantics:

* `anchor_root_hex` — the 64-character lowercase hex form of the
  32-byte SHA-256 Merkle root that was submitted. Producers emit
  `AnchorReceipt.merkle_root.hex()` verbatim.
* `timestamp` — UTC wall-clock when the record was flushed (i.e.
  after the `wat_write` stage completed). Format
  `YYYY-MM-DDTHH:MM:SSZ`, matching the receipt-emitter's
  `submission_time` field.
* `stages` — closed object with exactly the four `<stage>_ms` keys
  listed above. Values are non-negative finite floats in
  *milliseconds*; the consumer converts to seconds for the
  Prometheus exposition layer (Prometheus convention is seconds).

The JSONL stream is append-only. Rotation is the host operator's
concern (logrotate, systemd-tmpfiles); the consumer reads the last
`--window` parseable lines and does not rely on monotonic ordering
of timestamps. Malformed lines (truncated mid-write during a
concurrent rotation, missing `stages` block, non-numeric values) are
silently dropped by the consumer.

## 4. Producer semantics

Opt-in via the environment variable `WAKIR_ANCHOR_LATENCY_JSONL`. The
variable's value is the absolute path to the target JSONL file.

* Unset or empty → producer is a no-op. The anchor pipeline does not
  touch the filesystem for observability. Default for all existing
  unit tests and dev shells.
* Set to an absolute path → producer creates the file (and parent
  directory) on first emit, then appends one record per successful
  anchor.

Failure semantics:

1. **Conditional-on-success.** A record is emitted only when the
   pipeline completed all four stages without raising. An
   `AnchorError` (calendar threshold not met, OTS subprocess timeout,
   missing receipt file) aborts before flush. SLO-2 measures the
   latency of *successful* anchors; failure-rate is a separate signal
   on the receipt-emitter's spool-totals gauges.
2. **Isolation.** Any failure inside the emitter itself (disk full,
   permission denied, racing rotation) is swallowed silently. The
   anchor pipeline never propagates an observability sickness signal
   into its return contract. Detection of emitter sickness is the
   consumer's job (absence-of-data surfaces via the existing
   `wat_anchor_pipeline_cli_failure` gauge).

## 5. Consumer semantics

Defined in `scripts/wat-anchor-pipeline-observability.py` (PR #145).
Default source path: `/var/lib/wakir/wat-anchor-latencies.jsonl`.
The script tails the last `--window` parseable lines (default 100,
env override `WAKIR_OBS_WINDOW_SIZE`) and computes per-stage
p50/p95/p99 quantiles plus a bucketed histogram. Output is either
JSON (operator inspection / CI assertions) or Prometheus
`# TYPE histogram` exposition for node-exporter scrape.

## 6. Conformance

A producer conforms to this spec iff:

1. The four-stage order from §2 is preserved.
2. Every flushed line is a single-line JSON object with the field
   set from §3.
3. Stage durations are non-negative finite floats in milliseconds.
4. A failed anchor (any uncaught exception in the pipeline body)
   produces no flushed line.
5. Producer failures do not propagate into the anchor pipeline's
   return contract.

The reference producer is `wat.anchor.latency_emitter.LatencyEmitter`
(BSL-1.1) wired into `wat.anchor.ots_anchor.anchor_root`. Conformance
is exercised end-to-end in
`tests/wat/test_anchor_latency_emission.py`, including a wire-format
roundtrip against the PR #145 consumer.

## 7. Versioning

This is version 1 of the contract. Future bumps are versioned via
the document title (`wakir-wat-anchor-latency-emission/v2`) and the
filename suffix (`-v2.md`). Both producer and consumer carry an
`EXPECTED_SCHEMA_VERSION = 1`-style constant; a mismatch flips the
existing `wat_anchor_pipeline_schema_drift` gauge to `1.0` on the
consumer side.

## 8. References

* PR #145 — Per-anchor latency observability (consumer side, Tag-12
  Mini-Welle).
* `docs/observability/sli-slo-wat-phase-2.md` — SLO-2 anchor-latency
  catalogue entry (Noa, Phase-2 deferred → activated 2026-05-16).
* `wirelang/specs/wat-leaf-projection.md` — parallel
  module-boundary spec.
* ADR-0064 §Folgeartefakte Phase-2-Observability (AR approval
  2026-05-16 ~15:30 CEST).
