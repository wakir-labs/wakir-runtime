---
title: "Architecture layers and the proof path"
status: "active"
audience: "external,contributors,maintainers"
updated: "2026-09-14"
related_adrs:
  - "ADR-0072"
related_docs:
  - "STABILITY.md"
  - "docs/operations/demo-proof-runbook.md"
  - "docs/ci/branch-protection-required-checks.md"
---

<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# Architecture layers and the proof path

Wakir is built in five layers. Each answers exactly one question, and
the questions stack: you cannot answer the fourth without having
answered the first three. This document names the layers, maps each
onto the real modules in this repository, draws the boundaries
between them, and then draws the one line that matters — the path
from an organizational action to a claim a stranger can check.

Per-component maturity is in [`STABILITY.md`](../../STABILITY.md).
The split across the three repositories is in the
[README](../../README.md#how-the-three-repositories-fit-together).

## The five layers at a glance

| Layer | Answers | Where it lives | On the proof path |
|---|---|---|---|
| 1 — Protocol | What does an accountable organizational action look like? | `wakir-protocol`; consumed here via `wirelang/schemas/`, `wirelang/builder/`, `wirelang/canonical/` | yes |
| 2 — Accountability runtime | How is an organizational action created under bounded authority? | `wirelang/persona_engine/`, `wirelang/cli/`, `wat/anchor/bridge_audit_writer.py` | yes, through the bridge |
| 3 — Proof kernel / WAT | How is an action turned into a tamper-evident record? | `wat/` | yes |
| 4 — Independent verification | Can a third party independently verify the claim? | `wakir-verify`; here `wat/verify/`, `scripts/demo-proof.sh`, `tooling/external-verifier-*` | yes |
| 5 — Organizational infrastructure | Can this operate as a real organization rather than a toy demo? | `infra/`, `quadlet/`, `compose/`, `wirelang/federation/`, `wirelang/nats/`, `wirelang-rust/` | **no — see below** |

## Layer 1 — Protocol

> What does an accountable organizational action look like?

Actors, messages, schemas, frames, identity and capability
representations, and the contracts between them. The layer is
normative: it says what a valid action *is*, independently of who
runs it.

**In this repository**

- `wirelang/schemas/layer-0-transport.json`, `layer-1-wire.json`,
  `layer-2-semantic.json` — the frame contract
- `wirelang/schemas/layer-3-capability-token.json`,
  `datalog-caveat.json` — bounded authority
- `wirelang/builder/frame_builder.py` — frame construction
- `wirelang/canonical/`, `wirelang/identity/_jcs_pure.py` — canonical
  byte form (RFC 8785), the precondition for every hash above
- `wirelang/specs/` — the prose specifications, frozen at v0.4.3

**Boundary downward:** none. This is the bottom; everything else is
an interpretation of it.

**Boundary upward:** layer 1 knows nothing about execution. It never
decides whether an action *may* happen, only what it looks like when
it does. The authoritative copies of these artefacts live in
`wakir-protocol`; this repository consumes them and keeps local
copies in sync through `cross-repo-compat.yml`.

## Layer 2 — Accountability runtime

> How is an organizational action created under bounded authority?

Persona execution, capability checks, action requests, human
approvals, handoffs, and the bridge that turns all of that into audit
input.

**In this repository**

- `wirelang/persona_engine/engine.py`, `engine_async.py` — the
  execution loop
- `lifecycle_state_machine*.py`, `state_backing.py`,
  `recovery_workflow*.py` — bounded, resumable state
- `v907_verify*.py`, `wirelang/persona/persona_hash.py` — the persona
  a run actually executed, pinned by hash
- `wirelang/persona_engine/bridge_audit_writer.py`,
  `wat/anchor/bridge_audit_writer.py`, `wat/cmd/bridge_audit_cli.py` —
  the bridge to layer 3
- `wirelang/cli/bridge_forward*.py` — forwarding between boundaries

**Boundary downward:** layer 2 may only emit what layer 1 permits. A
frame the schemas reject never reaches the audit trail.

**Boundary upward:** layer 2 hands layer 3 an event and is then done
with it. It does not hash, does not aggregate, does not anchor, and
cannot influence a record once written. That asymmetry is
deliberate: a runtime that could rewrite its own audit trail would
make the whole construction pointless.

## Layer 3 — Proof kernel / WAT

> How is an action turned into a tamper-evident record?

Audit event projection, deterministic hashing, Merkle aggregation,
manifests, anchoring, proof artefacts.

**In this repository**

- `wat/ingestion/spool_writer.py`, `wirelang_bridge.py` — append-only
  hourly spool (`docs/wat-spool-spec.md`)
- `wat/merkle/aggregator.py` — leaf projection and Merkle
  construction (`wirelang/specs/wat-leaf-projection.md`,
  `docs/wat-hash-spec.md`)
- `wirelang/schemas/wakir-wat-manifest-v1.json`,
  `wirelang/schemas/wakir-inclusion-proof-v1.json` — the two published
  formats a verifier needs
- `wat/identity/manifest_signing.py`, `anchor_kid.py` — manifest
  signatures and key identity
- `wat/anchor/ots_anchor.py`, `backfill.py`, `esplora.py` — Bitcoin
  time-binding via OpenTimestamps

**Boundary downward:** layer 3 accepts events, never produces them.
It has no opinion about whether an action was wise, only about
whether the record of it is complete and fixed.

**Boundary upward:** layer 3 publishes formats, not code. Everything a
verifier needs — leaf rule, manifest, sibling hashes with side
markers — is documented and recomputable with a plain SHA-256
implementation. If verification required our code, it would not be
independent verification.

## Layer 4 — Independent verification

> Can a third party independently verify the claim?

Manifest, inclusion-proof and receipt verification, by someone who
does not trust us.

**In this repository**

- `scripts/demo-proof.sh`, `scripts/demo_proof_helpers.py` — the
  one-command path (`make demo-proof`,
  `docs/operations/demo-proof-runbook.md`)
- `scripts/ci/validate_demo_proof_report.py` — the strict gate half
- `wat/verify/`, `wat/cli.py` — server-side helpers (convenience, not
  the authority)
- `tooling/external-verifier-ajv/`, `tooling/external-verifier-hyperjump/`
  — our schemas checked by two foreign JSON-Schema implementations
  (`docs/external-verifier-conformance.md`)

**Boundary downward:** layer 4 reads published artefacts only. It
never calls into runtime code, and the verifier that matters —
`wakir-verify` — is a separate repository, Apache-2.0, with no
dependency on anything in here.

**Boundary upward:** none. This is the top of the claim. Layer 5 sits
beside it, not above it.

## Layer 5 — Organizational infrastructure

> Can this accountability system operate as a real organization
> rather than a toy demo?

SPIFFE/SPIRE, NATS, federation, deployment, recovery, systemd and
Quadlet units, supply-chain controls, virtual-machine acceptance,
operator tooling, and the Rust implementation crates.

**In this repository**

- `infra/spire/`, `wirelang/adapters/real_spiffe_workload_api.py` —
  workload identity
- `wirelang/federation/**`, `wirelang/identity/federation_resolver*.py`
  — cross-organization trust
- `wirelang/nats/`, `wirelang/adapters/real_nats_adapter/` —
  messaging substrate
- `quadlet/`, `compose/`, `policies/`, `scripts/install-persona-quadlet.sh`
  — deployment
- `wirelang-rust/crates/**` — the secondary implementation, kept
  behind an environment switch
- `dashboards/`, observability emitters, recovery drills,
  supply-chain workflows

### Layer 5 is not on the proof path

**This is the load-bearing statement of this document.** None of the
components above appear in the seven steps below. You can verify a
Wakir audit trail with none of them running: no SPIRE server, no NATS
cluster, no containers, no Rust binaries, no dashboards. The proof
path needs an event, a spool, a Merkle manifest, an inclusion proof
and a verifier.

The misreading this prevents is the common one — that Wakir is an
audit-logging product with organizational features attached, so that
a critique of the messaging substrate is a critique of the proof.
It is not. Layer 5 answers whether the thing can be *operated*;
layers 1–4 answer whether the claim *holds*. The two failure modes
are independent: layer 5 can be immature (and per
[`STABILITY.md`](../../STABILITY.md) most of it is `experimental`)
without weakening a single proof, and a flawless layer 5 would not
rescue a broken hash rule.

The converse matters too, which is why layer 5 exists at all: a proof
path nobody can run in production is a research artefact. The honest
summary today is that layers 1–4 are gated on every pull request and
layer 5 is not.

## The proof path

The canonical line, from an organizational action to something a
stranger can check. Every step names the file that implements it and
the gate that would fail if it broke.

```text
  Layer 1     protocol event
                 |
  Layer 2     runtime bridge
                 |
  Layer 3     WAT spool  ->  Merkle manifest  ->  inclusion proof
                 |
  Layer 4     external verification  ->  machine-readable report
```

| # | Step | Layer | Implemented by | Secured by |
|---|---|---|---|---|
| 1 | protocol event | 1 | `wirelang/builder/frame_builder.py` + the layer-0/1/2 schemas; materialised in the demo by `build-event` in `scripts/demo_proof_helpers.py` | `proof-path.yml` step `protocol_event`; required contexts `wirelang suite with rfc8785 + jsonschema` and its dependency-free shadow; `wirelang-spec-freeze-seal-probe.yml` |
| 2 | runtime bridge | 2 | `wat/anchor/bridge_audit_writer.py` via `run-bridge`; fans out to spool and activity log in one contract | `proof-path.yml` step `runtime_bridge`; byte parity pinned by `tests/fixtures/bridge-audit-writer-cross-lang/fixtures.json` |
| 3 | WAT spool | 3 | `wat/ingestion/spool_writer.py`, format in `docs/wat-spool-spec.md` | the spool is the sole input of step 4: a spool record with a missing, non-string or empty B1 field fails `proof-path.yml` instead of being reconstructed from `event.envelope.json` (the exception is `capability_token_hash`, whose empty string is the no-capability sentinel of `wirelang/specs/wat-leaf-projection.md` §3.4 and passes through verbatim). Envelope projection is available only behind `--allow-envelope-projection`, which the proof path does not pass, and a run that used it is marked `envelope_projection_used: true` in the report and rejected by the report validator. Until 2026-09-14 this row overstated the guarantee: falsy fields were repaired from the envelope. `tests/wat/` (47 modules, run on every pull request in the `Lane — WAT core` job since the Welle-3 lane promotion), `tests/scripts/test_demo_proof.py` (run inside the required `proof-path` context itself, which is also the only job that installs `wakir_verify` — two of its tests skip without it) |
| 4 | Merkle manifest | 3 | `wat/merkle/aggregator.py`, `wat/cmd/aggregator_cli.py`; format `wirelang/schemas/wakir-wat-manifest-v1.json` | `proof-path.yml` step `merkle_manifest`; `tests/wat/test_hash_consistency.py` (run on every pull request in the `Lane — WAT core` job since the Welle-3 lane promotion); recomputable against the real cohorts in `tests/fixtures/wat-tv2-real/`, `wat-tv3-real/` |
| 5 | inclusion proof | 3 → 4 | `verify-proof` in `scripts/demo_proof_helpers.py`; format `wirelang/schemas/wakir-inclusion-proof-v1.json` (sibling hashes with side markers, plain SHA-256) | `proof-path.yml` step `inclusion_proof`; vectors in `tests/fixtures/proof-path-vectors/` |
| 6 | external verification | 4 | `wakir_verify.manifest` and `wakir_verify.merkle_proof` from the sibling repository, called through `external-verify`; root re-derived by the verifier's own code, not ours | `proof-path.yml` step `external_verify`; the report validator's strict default requires status `ok` *and* `manifest_consistent` / `root_match` / `leaf_present` / `proof_verified` all true; verifier pinned by `WAKIR_VERIFY_PIN`; `cross-repo-compat.yml` watches the sibling's `main` |
| 7 | machine-readable report | 4 | `scripts/demo-proof.sh` emits `demo-report.json`, schema `wakir-demo-proof/v1`, five steps in fixed order | `scripts/ci/validate_demo_proof_report.py`, strict by default: schema, canonical step order, every step status exactly `ok`, every `exit_code` exactly `0`, step details that do not contradict the status, and `commits.wakir_runtime` equal to the commit under test |

Run the whole line locally:

```bash
make demo-proof
```

### Three honest notes on this line

**The report cannot be quietly emptied.** Step 6 may report
`skipped` when `wakir-verify` is not importable — that is a legitimate
local state and the driver exits 0 for it. The gate does not: the
validator is strict by default and accepts only `ok`, so a skipped
external check can never pass continuous integration — the leniency is
a named flag (`--allow-skipped-external-verify`) that CI does not
pass. The step is also never
silently dropped; all five demo steps appear in every report,
including failed ones, with downstream steps marked `not_run`.

**`capability_token_hash` had two definitions, and the demo was
hiding the difference.** The leaf-projection rule
(`wirelang/specs/wat-leaf-projection.md` §3.4) makes the empty string
the value for an event without `caprefs`; the canonical manifest
schema constrains the same field to `^[0-9a-f]{64}$`. Cross-Review
Zone 3 decided in favour of the schema — inside an anchored manifest
the field is a fixed-width digest, and "no capability" is the all-zero
one — and tracked the producer change as a follow-up
(`tests/compat/test_zone3_capability_token_hash.py`). Nothing forced
the follow-up, because the bridge audit writer emitted the empty
string into the spool and step 3 replaced it with the demo envelope's
all-zero placeholder before hashing: the manifest satisfied the schema
while describing a tuple the spool never held. Removing that repair on
2026-09-14 turned `cross-repo-compat.yml` red and named the pin. The
follow-up is now done on both sides: the writer defaults to
`NO_CAPABILITY_DIGEST` and forwards a real digest when the caller has
one, and `aggregator_cli._validate_events` enforces the schema pattern
so a manifest that could not be published can no longer be built. The
leaf-hash primitive stays permissive on purpose.

**Bitcoin time-binding sits one step beyond this line.** Anchoring an
hourly root through OpenTimestamps (`wat/anchor/ots_anchor.py`) is
what converts "this record is internally consistent" into "this
record existed before block *N*". Bitcoin-attested receipts exist in
the tree — the eight under `tests/fixtures/wat-tv2-real/` and
`tests/fixtures/wat-tv2-real-signed/`. The other two `.ots` fixtures
(`wat-tv3-real/`, `wat-real-manifest/`) carry pending calendar
attestations only and are not evidence of a Bitcoin binding; see the
OpenTimestamps row in `STABILITY.md`. Either way the anchor leg is
not part of the gated seven steps: the demo only exercises it in an
optional online mode, and production anchoring is still behind an
operator activation gate. Treat the gated line as proof of
*inclusion*, and the anchor as proof of *time* that currently rests
on operator-run evidence rather than on a standing gate.

### Where each layer's gate lives

| Layer | Standing gates on every pull request |
|---|---|
| 1 | `tests.yml` (two required contexts), `wirelang-spec-freeze-seal-probe.yml`, `hash-derivate-gate.yml` |
| 2 | `proof-path.yml` (bridge leg), `runtime-acceptance-gates.yml`, `v907-persona-hash-pin-build-step.yml` |
| 3 | `proof-path.yml` (spool, manifest, proof legs), `tests.yml` |
| 4 | `proof-path.yml` (external leg plus report validation), `cross-repo-compat.yml` |
| 5 | `containerfile-digest-pin-gate.yml`, `cosign-verify-images.yml`, `cross-substrate-parity-gate.yml`, and daily supply-chain workflows. The live bring-up lanes (`live-vm-acceptance.yml`, the real leg of `e2e-vm-acceptance-gate.yml`) are dispatch-only — and measured 2026-09-14, neither has ever been dispatched. Treat live bring-up as unexercised in CI, not as point-in-time evidence. |

Current branch-protection state for these contexts is inventoried in
[`docs/ci/branch-protection-required-checks.md`](../ci/branch-protection-required-checks.md).
