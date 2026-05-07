<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors

License: This document is licensed under the Creative Commons Attribution
4.0 International License. To view a copy, see
<https://creativecommons.org/licenses/by/4.0/>.
-->

# Wirelang Test-Vector Strategy (TV-W)

Status: draft, Phase 1b, Tag-13 spec-only.
Counterpart of: `wakir-runtime/docs/wat-tv1-test-plan.md`,
`wat-tv2-test-plan.md`, `wat-tv3-test-plan.md` (WAT side).
Author: Reza, 2026-05-07.

This document specifies the Wirelang-side test-vector strategy in
symmetry to the WAT TV-1 / TV-2 / TV-3 live-run series. Where WAT-TV
exercises the *audit-trail* substrate (Merkle build, OTS anchoring,
calendar upgrade), Wirelang-TV exercises the *trust* and *identity*
substrate (BIP-32 / SLIP-0010 derivation, Biscuit token chains, AIP
federation resolution).

The three vectors below are end-to-end golden-pipeline runs with
externally regenerable inputs and pinned outputs. They are not unit
tests; they are reproducible integration probes that an external
auditor can re-execute without our CI.

## 0. Symmetry table

| WAT side | Wirelang side | Concern |
|---|---|---|
| TV-1 (One-Hour-Volume, 100 events) | **TV-W-1 (Identity-Roundtrip, 9 vectors)** | Bulk hermetic correctness |
| TV-2 (Multi-Hour-Chain) | **TV-W-2 (Capability-Token-Multi-Step)** | Sequenced state, append-only chain |
| TV-3 (Backfill, public OTS) | **TV-W-3 (Federation-Resolver-Roundtrip)** | External-substrate roundtrip |

The symmetry is intentional: each TV-W vector matches its TV-N
counterpart in *operational shape* (volume, chain, external substrate)
and uses the same acceptance-criteria pattern (A1..A5).

Note on naming: the prefix `TV-W` (W for Wirelang) avoids collision with
`TV-1..TV-3` reserved by WAT. Within Wirelang, the short forms `W-1`,
`W-2`, `W-3` are unambiguous.

## 1. TV-W-1 — Identity Pin-Pack Roundtrip

### 1.1 Purpose

End-to-end derivation roundtrip across the full Wakir identity stack:
seed → master keys (two curves) → sub-key derivation along the Wakir
path → DID document → AIP document → signed-document verification.
The vector exercises the BIP-32 + SLIP-0010 + `WAKIR_COIN_TYPE`
(`0x57414B49`) derivation path defined in
`wirelang/specs/identity-substrate.md` §1.

This is the volume baseline: nine personas, two curves each, full
document roundtrip, all hermetic (no network).

### 1.2 Inputs

A fixed test seed (BIP-39-derived) and a fixed enumeration of nine
`(persona_idx, spawn_counter)` pairs covering:

- `persona_idx ∈ {0, 1, 2}` × `spawn_counter ∈ {0, 1, 2}` = 9 personas.
- The seed itself is the BIP-32 test vector 1 seed
  (`000102030405060708090a0b0c0d0e0f`) so the master keys are the
  pinned values from `identity-substrate.md` §1.
- All paths hardened on both curves per SLIP-0010 mandate.

### 1.3 Pipeline steps per persona

1. Derive secp256k1 sub-key at `m/44'/WAKIR_COIN_TYPE'/persona_idx'/spawn_counter'`.
2. Derive Ed25519 sub-key at the same path (SLIP-0010).
3. Build DID document (`did:web:wakir.dev/<role-string>`) with both
   verification methods.
4. Build AIP document referencing the same biscuit-root pubkey.
5. Sign DID and AIP documents (Ed25519 over JCS canonicalisation).
6. Verify signatures via the Pure-Python rfc8785 fallback path *and*
   via `cryptography`-backed path; both MUST agree.
7. Emit a deterministic pin-pack JSON containing:
   `(persona_idx, spawn_counter, secp256k1_pub, ed25519_pub,
   did_doc_hash, aip_doc_hash, did_signature, aip_signature)`.

### 1.4 Acceptance criteria (A1..A5)

- **A1.** Pin-pack hash matches a checked-in golden file
  `wirelang/tests/fixtures/tv-w-1/pin-pack.json`.
- **A2.** Pure-Python and `cryptography`-backed signature verification
  agree byte-for-byte for all 18 (9×2) signatures.
- **A3.** Sandbox-CI lane reproduces the pin-pack hash (no rfc8785,
  no jsonschema → Pure-Python only).
- **A4.** Production-CI lane reproduces the pin-pack hash (full stack).
- **A5.** External regeneration: a third-party auditor running the
  documented script offline against the published seed reproduces
  the identical pin-pack hash.

### 1.5 Counterpart to TV-1

| Aspect | TV-1 (WAT) | TV-W-1 (Wirelang) |
|---|---|---|
| Volume | 100 events | 9 personas × 2 curves = 18 derivations |
| Determinism source | Fixed hour `2026-05-26T17` | Fixed BIP-32 test seed |
| Pinned artefact | Manifest leaf order + Merkle root | Pin-pack JSON hash |
| External substrate | None (offline phase) | None (offline phase) |
| Performance budget | build < 2s p50 | full pin-pack < 1s p50 |

Both vectors are "hermetic, high-volume, hash-pinned". TV-W-1 is
deliberately smaller in event count because the per-derivation cost
is higher and the combinatorial coverage (curves × paths × document
types) is what matters, not raw count.

## 2. TV-W-2 — Capability-Token Multi-Step Chain

### 2.1 Purpose

End-to-end Biscuit v3 chain construction and verification across an
authority block plus N append-blocks plus optional sealing, with
caveat evaluation under multiple presentation contexts. This vector
exercises Layer-3 (`wirelang/specs/layer-3-capability-token.md`) in
its full sequenced form: not a single token check but a chain of
delegations where each block attenuates the privilege of its
predecessor.

This is the chain-correctness vector: append-only semantics, no
strengthening, caveat composition.

### 2.2 Inputs

- Issuer keypair derived from TV-W-1 persona `(0, 0)` Ed25519 sub-key.
- Three audience role-strings: `role=consumer-A`, `role=consumer-B`,
  `role=consumer-C`.
- A pinned set of Datalog caveats from
  `wirelang/specs/datalog-caveat-vocabulary.md`:
  - Authority block: time-bound (`not_before`, `not_after`),
    audience-pattern caveat.
  - Append block 1: scope-narrowing caveat (resource pattern).
  - Append block 2: rate-limit caveat (per-second cap).
  - Optional sealing block.

### 2.3 Pipeline steps

1. Build authority block (Block 0) signed by issuer Ed25519 key.
2. Append Block 1 (scope-narrowing) signed by Block-0's `next_pubkey`.
3. Append Block 2 (rate-limit) signed by Block-1's `next_pubkey`.
4. Optional sealing: produce a `proof_block` over the chain.
5. Run the verifier in three presentation contexts:
   - **Context α:** within all caveats → `accept`.
   - **Context β:** after `not_after` → `reject` with reason
     `time-bound-violated`.
   - **Context γ:** with mismatched audience → `reject` with reason
     `audience-pattern-mismatch`.
6. Emit a deterministic verification-trace JSON for each context.

### 2.4 Acceptance criteria

- **A1.** Verification-trace hashes match three golden files
  `wirelang/tests/fixtures/tv-w-2/trace-{alpha,beta,gamma}.json`.
- **A2.** Each block's signature verifies with the *previous* block's
  `next_pubkey` — the append-only invariant is checked at every step.
- **A3.** Caveat evaluation is deterministic: re-running the verifier
  on the same context produces byte-identical traces.
- **A4.** Strengthening detection: a synthetic mutation that *removes*
  a caveat from Block 1 must be rejected with reason
  `attenuation-violation`. (This is the negative-control case.)
- **A5.** Cross-lane parity: sandbox and production lanes produce
  identical trace hashes (the Datalog evaluator is Pure-Python and
  has no `rfc8785`/`jsonschema` dependency on the trace path).

### 2.5 Counterpart to TV-2

| Aspect | TV-2 (WAT) | TV-W-2 (Wirelang) |
|---|---|---|
| Sequenced state | Multi-hour Merkle chain | Multi-block Biscuit chain |
| Append-only invariant | Each hour-manifest references prior root | Each block signed by prior `next_pubkey` |
| Negative-control | Re-ordering rejection | Attenuation-violation rejection |
| Pinned artefact | Chain-of-roots manifest | Verification-trace JSON × 3 |

Both vectors are "sequenced, append-only, attenuation-respecting".

## 3. TV-W-3 — Federation Resolver Roundtrip

### 3.1 Purpose

End-to-end federation pipeline: DNS-anchor resolution → FTD-verifier →
AIP resolver → `verify_from_transport`. This vector exercises the
full external-substrate roundtrip that V-908 (Phase-1b I-5) introduces
and matches what a real-world consumer would do when verifying a
remote agent's identity.

This is the external-substrate vector: it is the Wirelang analogue of
TV-3 (which uses the public OTS calendars and Bitcoin block as its
external substrate).

### 3.2 Inputs

- A federated domain fixture (`wakir.dev/<role-string>`) with a known
  DNS TXT anchor and a published AIP document at the documented
  HTTPS endpoint. The fixture is recorded twice:
  - **Hermetic mode:** DNS responses and HTTPS responses are replayed
    from `wirelang/tests/fixtures/tv-w-3/replay/`.
  - **Live mode:** the test resolves against the real DNS and HTTPS,
    gated by an environment variable `WIRELANG_LIVE_FEDERATION=1`
    (analogue of WAT's `OTS_INTEGRATION_TEST=1`).
- The signing keypair from TV-W-1 persona `(1, 0)` (deliberately
  different from TV-W-2 to exercise multi-persona federation).
- A frame signed and transported as if over the wire (Layer-0 +
  Layer-1 + Layer-3 stacked).

### 3.3 Pipeline steps

1. Resolve DNS TXT anchor for `wakir.dev/<role-string>` via the
   DNS-anchor resolver module.
2. Fetch the AIP document via HTTPS-backend (V-908 `aip_https_backend`).
3. Run FTD-verifier: confirm DNS-anchored hash matches AIP-document hash.
4. Resolve AIP document → biscuit-root-pubkey.
5. Run `verify_from_transport` on the inbound frame using the
   resolved root pubkey.
6. Emit a federation-trace JSON: `(dns_anchor_hash, aip_doc_hash,
   ftd_verifier_status, aip_resolved_pubkey, frame_verify_status,
   frame_signature_hex)`.

### 3.4 Acceptance criteria

- **A1.** Hermetic mode produces a federation-trace whose hash matches
  the golden file `wirelang/tests/fixtures/tv-w-3/trace-hermetic.json`.
- **A2.** Hermetic mode runs in both sandbox and production CI lanes
  and produces identical trace hashes.
- **A3.** Live mode (gated, run on operator demand) produces a
  trace-live.json whose `dns_anchor_hash` and `aip_doc_hash` match
  the hermetic trace, proving the replay fixtures are faithful.
- **A4.** Negative control: a mutated DNS-anchor hash must cause
  FTD-verifier to fail with reason `ftd-mismatch`; the frame verify
  must not be reached.
- **A5.** Replay-fixture freshness: the replay bundle records its
  own captured-at timestamp; a pre-flight check warns if the bundle
  is older than 90 days, mirroring the OTS-calendar-freshness pattern
  on the WAT side.

### 3.5 Counterpart to TV-3

| Aspect | TV-3 (WAT) | TV-W-3 (Wirelang) |
|---|---|---|
| External substrate | Public OTS calendars + Bitcoin | Public DNS + HTTPS |
| Roundtrip | Stamp → upgrade → verify | Anchor → fetch → verify |
| Live-gate env | `OTS_INTEGRATION_TEST=1` | `WIRELANG_LIVE_FEDERATION=1` |
| Hermetic alternative | Replay against pinned proofs | Replay against captured fixtures |
| Freshness concern | Calendar bitcoin-attestation lag | DNS/HTTPS replay-bundle age |

Both vectors are "external-substrate, replay-or-live, freshness-aware".

## 4. Repository layout

```
wirelang/
  specs/
    wirelang-tv-strategy.md            (this file)
  tests/
    fixtures/
      tv-w-1/
        pin-pack.json                  (golden, 18 derivations)
      tv-w-2/
        trace-alpha.json
        trace-beta.json
        trace-gamma.json
      tv-w-3/
        trace-hermetic.json
        trace-live.json                (operator-produced, gitignored
                                        outside hermetic mode)
        replay/
          dns/                         (DNS query replay)
          https/                       (HTTPS body replay)
          captured-at.txt              (ISO 8601 timestamp)
    test_tv_w_1_identity_roundtrip.py
    test_tv_w_2_capability_chain.py
    test_tv_w_3_federation_roundtrip.py
```

Fixture files are deterministic JSON (RFC 8785 canonicalised) so the
golden hashes are stable across platforms. Replay bundles use the
existing DNS-anchor and HTTPS-backend replay protocols introduced in
Phase-1b Tag-5..Tag-8.

## 5. CI integration

| Lane | TV-W-1 | TV-W-2 | TV-W-3 hermetic | TV-W-3 live |
|---|---|---|---|---|
| sandbox-ci.yml (pure-Python) | yes | yes | yes | no |
| tests.yml (production) | yes | yes | yes | no |
| Live-federation operator-run | n/a | n/a | n/a | yes (gated) |

All three TV-W vectors are correctness-gates in both CI lanes
(hermetic). Live mode is operator-on-demand, mirroring the WAT
public-OTS pattern.

Drift-detection (Tag-12 Companion) covers TV-W tests in the existing
`production_count - sandbox_count = 144 ±5` envelope; if TV-W test
modules are added, the `EXPECTED_DELTA` constant requires explicit
re-baseline via workflow-PR.

## 6. Implementation sequencing

Implementation is *not* in scope for Tag-13 (spec-only per Mira-
Auftrag). The recommended sequencing for follow-up days:

1. **TV-W-1 first** — smallest scope, no external substrate, fastest
   to pin and to get golden-fixtures into the repo.
2. **TV-W-2 second** — depends on TV-W-1's persona keypair shape;
   adds the negative-control pattern.
3. **TV-W-3 last** — depends on TV-W-1 and TV-W-2 for keypair and
   chain-shape inputs; introduces external-substrate replay
   bundles.

Each implementation day is one Mira-box; per-day deliverable is the
golden-fixture file plus the test module plus a minimal addition to
this spec when the fixture pins crystallise.

## 7. Out of scope

- **Performance budgets:** the spec deliberately does not pin
  per-vector wall-clock budgets. TV-W is a correctness instrument,
  not a perf-gate. WAT TV-1 carries soft p50/p95 budgets because
  build/stamp/verify is dominated by I/O and is operator-relevant;
  TV-W is CPU-bound and adding budgets here is theatre.
- **Coverage metrics:** TV-W is hash-pinned-output verification, not
  coverage-driven. A separate coverage layer is a different topic
  (Tag-12 Option B).
- **Mutation testing:** TV-W-2 includes a single negative-control
  mutation (caveat-removal). Full mutation-testing on the Datalog
  evaluator is out of scope.
- **Cross-WAT integration:** the cross-module-vertrag with WAT
  Layer-1 frame shape is enforced separately by the schema-registry;
  TV-W does not duplicate that check.

## 8. Brand-guide §9 compliance

All examples use role-strings (`<role-string>`, `consumer-A`,
`consumer-B`, etc.). No personal names, no project-internal aliases
that would leak through to public golden fixtures.

## Annex A — Crystallised pin values

Pin values are added here as each TV-W vector is implemented. A
re-baseline of any pin is an explicit engineering event and requires
an updated entry below plus a workflow-PR note.

### A.1 TV-W-1 (Phase-1b Tag-14, 2026-05-07)

- Golden fixture: `wirelang/tests/fixtures/tv-w-1/pin-pack.json`.
- Builder / regenerator: `wirelang.tests._tv_w_1_pin_pack_builder`
  (also exposes `--check` for hash-only verification).
- `pin_pack_sha256`:
  `82149029a34d3595f587000073e62535491f47216ee6cf4aaa224345fe7d88bb`
- Coverage: 9 personas (`persona_idx` ∈ {0,1,2} × `spawn_counter` ∈
  {0,1,2}), each with secp256k1 pub, Ed25519 pub, JCS-SHA-256 of the
  unsigned DID-document body, JCS-SHA-256 of the signed AIP document,
  and the deterministic Ed25519 AIP signature.
- Determinism note: ECDSA-secp256k1 in the `cryptography.hazmat`
  stack is non-deterministic; the DID-document `proof` slot is
  excluded from the pin-pack. The unsigned DID-body JCS-SHA-256 is
  the byte-stable substitute.

— Reza
