<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# Stability Matrix — wakir-runtime

What in this repository you can build on, what you should treat as
moving, and what is only here because an operator needs it. One row
per component, one status, and a reason you can check against the
tree.

Scope is **this repository only**. `wakir-protocol` (the wire
formats) and `wakir-verify` (the third-party verifier) publish their
own matrices; where a row here depends on one of them, the row says
so. The three-repository split is explained in the
[README](README.md#how-the-three-repositories-fit-together), the
layer split in [`docs/architecture/layers.md`](docs/architecture/layers.md).

## Status vocabulary

| Status | Means |
|---|---|
| `stable-ish` | Format or behaviour is pinned by a gate that runs on every pull request. A breaking change has to change a test vector or a workflow in the same commit, so it cannot happen quietly. Not a compatibility promise — we are pre-1.0 — but a promise that breakage is visible. |
| `beta` | Substance is complete and tested, but either the gate coverage is narrower than the surface, or the component has never been operated outside a test harness. |
| `experimental` | Shape is expected to change. Tested hermetically, exercised in a sandbox at best. Do not build on the interface. |
| `internal` | Exists for operators and maintainers of this repository. No external contract, may disappear without a migration path. |
| `deprecated` | Still accepted, still tested, scheduled to go. A replacement exists and is named in the note. |
| `planned` | Specified in the tree, not implemented. Present so the intended shape can be reviewed before code lands. |

**The single most important caveat in this file:** with the
exception of the Bitcoin anchoring receipts in
`tests/fixtures/wat-tv2-real*/` and `tests/fixtures/wat-tv3-real/`,
nothing here has been run in production. "Tested" in the notes below
means hermetic tests and continuous-integration runs on a clean
runner. Where a component has additionally been exercised against a
live virtual machine, the note says so explicitly; where it has not,
assume it has not.

## Layer 1 — Protocol surface consumed here

| Component | Status | Notes |
|---|---|---|
| Wirelang frame schemas (`wirelang/schemas/layer-0-transport.json`, `layer-1-wire.json`, `layer-2-semantic.json`) + `wirelang/builder/frame_builder.py` | `stable-ish` | Spec v0.4.3 is frozen and the freeze is guarded by `.github/workflows/wirelang-spec-freeze-seal-probe.yml`; schema conformance runs in the required contexts `wirelang suite with rfc8785 + jsonschema` and the dependency-free shadow suite. 174 test modules under `wirelang/tests/`. |
| Canonical form / JCS (`wirelang/canonical/`, `wirelang/identity/_jcs_pure.py`) | `stable-ish` | Byte-level canonicalisation is what every hash downstream depends on. Pinned twice: against `rfc8785` and against the pure-Python fallback, in two separate required contexts, plus `tests/fixtures/jcs-leaf-vectors/`. |
| Capability-token envelope + Datalog caveat vocabulary (`wirelang/schemas/layer-3-capability-token.json`, `wirelang/schemas/datalog-caveat.json`, `wirelang/canonical/caveat_set.py`) | `beta` | Envelope and caveat-set canonicalisation have vector tests. The phase-2 vocabulary in `wirelang/specs/datalog-caveat-vocabulary-phase-2.md` is still a draft, and the attenuation-chain verifiers that consume it live in the federation subtree, which is `experimental`. |
| Schema registry + publisher CLI (`wirelang/schemas/registry_nats_kv_backend.py`, `publisher_cli.py`, revoke/unrevoke paths) | `experimental` | Documented in `docs/wakir-schema-versioning.md`, `docs/publisher-cli-revoke.md`; schema-byte drift against the recorded hash derivates is caught by `.github/workflows/hash-derivate-gate.yml`. Tested hermetically and against an embedded NATS only; the key-value backend has never run against an operated NATS cluster. Interface expected to change with the registry spec. |
| Persona schema `persona-v0` (`wirelang/schemas/persona-v0.json`) | `deprecated` | Accepted as migration input only. `PERSONA_SCHEMA_VERSION_LATEST` in `wirelang/persona/persona_migration.py` is `persona-v1`; the v0→v1 step is registered and vector-tested. |
| Persona schema `persona-v2` (`wirelang/schemas/persona-v2.json`) | `planned` | Converter step exists in the registry, the default target deliberately stays at v1. Do not emit v2 yet. |

## Layer 2 — Accountability runtime

| Component | Status | Notes |
|---|---|---|
| Bridge audit writer (`wat/anchor/bridge_audit_writer.py`, `wat/cmd/bridge_audit_cli.py`) | `stable-ish` | **Raised from the review's `beta`.** It is step 2 of the proof path, so every pull request runs it on a clean runner through `.github/workflows/proof-path.yml` and the report validator refuses anything but `ok`. Byte parity against the Rust sibling is pinned by `tests/fixtures/bridge-audit-writer-cross-lang/fixtures.json` and its derive script. The dual-sink atomicity contract (spool + activity log) is covered hermetically; it has never seen production message volume. |
| Wirelang → WAT ingestion bridge (`wat/ingestion/wirelang_bridge.py`, `spool_writer.py`) | `stable-ish` | Spool layout is specified in `docs/wat-spool-spec.md` and is the input of the Merkle aggregator, so a silent change breaks the `proof-path` gate. 55 test modules under `tests/wat/`. |
| Bridge forward / diff / replay (`wirelang/cli/bridge_forward*.py`, `wirelang/persona_engine/bridge_audit_diff_engine*.py`, `bridge_audit_replay*.py`) | `beta` | Complete and cross-language vector-tested (three fixture packs under `tests/fixtures/`), with canonical Python siblings for each Rust crate. Off the proof path: no required gate fails if the replay semantics move. |
| Persona engine, deterministic core (`engine.py`, `lifecycle_state_machine*.py`, `state_backing.py`, `recovery_workflow*.py`, `v907_verify*.py`) | `beta` | **Raised from the review's `experimental`.** The persona hash is pinned by `wirelang/persona_engine/v907-hash-baseline.json` plus `.github/workflows/v907-persona-hash-pin-build-step.yml`, and four of these modules carry byte-parity fixture packs against their Rust siblings. What keeps it out of `stable-ish` is operation, not substance: it has never run an organisation for a day. |
| Persona engine, model-call and routing layer (`llm_call_shim.py`, `llm_classifier.py`, `heuristic_router.py`, `anthropic_call.py`, `anthropic_cache.py`, `classifier_cache.py`) | `experimental` | Tested against shims and recorded responses. Never exercised against a live model endpoint in continuous integration, and the routing heuristics are expected to change. |
| Persona engine messaging loop (`nats_subscribe_loop.py`, `subscribe_ack.py`, `nats_subjects.py`) | `experimental` | Subject mapping is specified (`wirelang/specs/nats-subject-mapping-v1.md`) and vector-tested; the loop itself runs against an embedded or sandbox NATS only. Inherits the `experimental` state of the NATS runtime below. |

## Layer 3 — Proof kernel / WAT

| Component | Status | Notes |
|---|---|---|
| WAT spool format (`docs/wat-spool-spec.md`, leaf projection in `docs/wat-leaf-projection.md`) | `stable-ish` | Frozen by the hash specification and by `tests/fixtures/proof-path-vectors/`; a change to the leaf projection changes the Merkle root of every recorded test vector, which is loud by construction. |
| Merkle aggregator (`wat/merkle/aggregator.py`, `wat/cmd/aggregator_cli.py`) | `stable-ish` | The core of the claim. Hash rules in `docs/wat-hash-spec.md`, cross-checked by `tests/wat/test_hash_consistency.py`, re-derived independently by `wakir-verify` in step 5 of the proof path, and re-derivable from the real hour cohorts in `tests/fixtures/wat-tv2-real/` and `wat-tv3-real/`. |
| WAT manifest v1 (`wirelang/schemas/wakir-wat-manifest-v1.json`, `docs/wat-manifest-spec.md`) | `stable-ish` | Produced in step 3 of the proof path and consumed by the external verifier in step 5, so the format is pinned across two repositories by `proof-path.yml` and `cross-repo-compat.yml`. |
| WAT manifest v2 (`wirelang/schemas/wat-manifest-v2.json`, `wat/verify/manifest_v2.py`) | `beta` | Specified in `docs/wat-manifest-v2-spec.md` and implemented with test vectors under `tests/fixtures/wat-manifest-v2/`, but v1 is what the proof path emits. Treat v2 as reviewable, not as production output. |
| Multi-capability manifest trigger (`docs/wat-manifest-v2-multi-cap-stub.md`) | `planned` | Explicitly a stub specification, not an implementation directive. Present so the shape can be reviewed before code lands. |
| Manifest signing + anchor key identity (`wat/identity/manifest_signing.py`, `anchor_kid.py`) | `beta` | Ed25519 signing with a resolvable key identifier; signed cohorts exist under `tests/fixtures/wat-tv2-real-signed/` and are re-verifiable from the published demo seed. Not on the proof path: the demo verifies an unsigned manifest, so no required gate covers the signing path today. Key rotation is documented, not exercised. |
| OpenTimestamps anchor pipeline (`wat/anchor/ots_anchor.py`, `backfill.py`, `esplora.py`, `scripts/wat-hourly.sh`) | `beta` | The strongest live evidence in the repository and the clearest limitation at once: `tests/fixtures/wat-tv*-real/*/root.bin.ots` are real receipts with real Bitcoin attestation, so the pipeline has demonstrably produced anchored roots. Production anchoring is nonetheless not switched on — `.github/workflows/ots-pre-anchor-activation-probe.yml` is a hermetic dry-run that walks the call shape without network input or output, and the real activation is an operator step behind a cutover gate. |
| Inclusion proof format v1 (`wirelang/schemas/wakir-inclusion-proof-v1.json`) | `stable-ish` | Sibling hashes with side markers, recomputable with plain SHA-256 and nothing else. Emitted in step 4 of the proof path, re-checked by the external verifier's own code in step 5. |

## Layer 4 — Independent verification

| Component | Status | Notes |
|---|---|---|
| One-command proof path (`make demo-proof`, `scripts/demo-proof.sh`, `scripts/demo_proof_helpers.py`) | `stable-ish` | Five steps in fixed order, a `wakir-demo-proof/v1` report on every run, `shellcheck` on the driver in the same job. The driver exits 0 on a `skipped` external step; the gate does not. |
| Proof-path report validator (`scripts/ci/validate_demo_proof_report.py`) | `stable-ish` | The strict half of the gate: schema check, exactly five steps in canonical order, no `failed` or `not_run`, `external_verify == ok`, and the report must name the commit under test. This is what makes the proof path non-bypassable. |
| In-tree verification helpers and CLI (`wat/verify/`, `wat/cli.py`) | `stable-ish` | Server-side counterpart of the external verifier; exercised by the same fixture cohorts. Note that a third party should not need this code — that is the whole point of `wakir-verify`. |
| External-verifier conformance harness (`tooling/external-verifier-ajv/`, `tooling/external-verifier-hyperjump/`, `docs/external-verifier-conformance.md`) | `beta` | Two independent JSON-Schema implementations validate our published schemas, with a drift workflow (`external-verifier-drift.yml`) watching for divergence. Not a required context, so drift is reported rather than blocking. |
| Cross-repository compatibility gate (`.github/workflows/cross-repo-compat.yml`) | `beta` | Checks protocol ↔ runtime ↔ verify against the siblings' `main` on every pull request. Substance is in place; the branch-protection context swap is still an operator step (`docs/ci/branch-protection-required-checks.md` §1 row 5, §2.3), so today it reports without blocking. |

The verifier binary itself lives in `wakir-verify` and is out of scope
for this file. The proof-path gate pins it to a commit
(`WAKIR_VERIFY_PIN` in `proof-path.yml`) so a change on that side
cannot move this side quietly.

## Layer 5 — Organizational infrastructure

Everything in this section is **off the proof path**. A third party
verifying a Wakir audit trail needs none of it. It answers whether
this can be operated as a real organisation, not whether the claim
holds. See `docs/architecture/layers.md` §Layer 5.

| Component | Status | Notes |
|---|---|---|
| SPIFFE/SPIRE workload identity (`wirelang/adapters/real_spiffe_workload_api.py`, `wirelang/identity/svid_workload_identity_canonical.py`, `infra/spire/`) | `experimental` | Server and agent setup are documented (`docs/spire-server-phase-2-1.md`, `docs/spire-agent-phase-2-2.md`, `docs/spire-trust-bundle-rotation.md`) and the Python client has a graceful fallback path. Live validation runs only through `.github/workflows/live-vm-acceptance.yml`, which is `workflow_dispatch` with no automatic trigger — so the live evidence is a manual, point-in-time artefact, not a standing gate. |
| Cross-organization federation substrate (`wirelang/federation/**`) | `experimental` | The largest untested-in-anger surface in the repository: attenuation-chain verification, multi-organization attestation replication, trust-bundle fetching, sequence-number ledgers. One test module under `tests/federation/` plus hermetic coverage in `wirelang/tests/`. Shape will change. |
| Federation and identity resolvers (`wirelang/identity/federation_resolver*.py`, `kid_resolver.py`, `ftd_verifier.py`, `aip_*`, `did_document*.py`) | `experimental` | Vector-tested (`tests/fixtures/wakir-ftd-vectors/`, `did-document-vectors/`, `aip-document-vectors/`) with documented trust modes (`docs/RESOLVER-TRUST-MODES.md`). Transport fetching has never resolved against a live remote. |
| NATS runtime (`wirelang/nats/subject_mapping.py`, `wirelang/adapters/real_nats_adapter/`, JetStream and key-value wiring) | `experimental` | Subject mapping is specified and audited (`.github/workflows/nats-jetstream-subjects-audit.yml`); the runtime itself is only ever brought up embedded or in a sandbox. Bring-up runbooks exist (`docs/orchestrator-nats-kv-phase-1-runbook.md`, `docs/nats-jwt-auth-phase-2-4.md`); the gap between a documented runbook and an operated cluster is exactly what `experimental` means here. |
| Rust implementation crates (28 of the 32 workspace crates under `wirelang-rust/crates/`, grouped) | `experimental` | Secondary implementation, not the hot path: `wirelang/persona_engine/rust_backend_switch.py` keeps Python as the production default and the Rust bridge behind an environment variable. What is solid is the parity claim where it is made — 15 fixture packs under `tests/fixtures/*-cross-lang/` pin Python and Rust output byte-for-byte for the crates they cover, and the covered crates have their own build workflows. What is not solid is the operational story, and parity is not claimed for every crate in the group. |
| Rust benchmark, smoke and integration crates (`persona-engine-loop-latency-bench`, `persona-engine-v907-recompute-bench`, `persona-engine-smoke`, `persona-engine-integration-tests`) | `internal` | Development instruments. No contract, no external consumers. |
| Container and deployment surface (`quadlet/`, `compose/`, `infra/`, `scripts/install-persona-quadlet.sh`) | `experimental` | Quadlet units, network and volume definitions, cosign-verified images and a bring-up path exist and are lint-checked; end-to-end bring-up runs through `e2e-bringup-ci.yml` on a narrow path filter, and the real virtual-machine leg of `e2e-vm-acceptance-gate.yml` only runs on manual dispatch. Nothing here is continuously proven. |
| Supply-chain controls (cosign verification, SBOM dailies, base-image digest pins, build reproducibility) | `beta` | The best-covered part of layer 5: `containerfile-digest-pin-gate.yml` and `cosign verify SPIRE images` are required contexts, and four daily workflows watch SBOM and reproducibility drift. It is `beta` rather than `stable-ish` because cosign strict mode is still only a readiness check (`cosign-strict-mode-readiness-check.yml`), not enforcement. |
| Observability surface (`dashboards/`, `scripts/prometheus-textfile-adapter.py`, latency and routing emitters) | `experimental` | 28 test modules under `tests/observability/` cover the emitters' shape. No dashboard has ever been pointed at a running system, so panel definitions are design artefacts. |
| Recovery drill and anchor timer (`wirelang/persona/recovery_drill_anchor.py`, `wirelang/identity/recovery_drill.py`, `quadlet/*recovery-drill-anchor*`) | `experimental` | Drill outcome schema and Shamir key splitting are vector-tested; the drill has been run hermetically, never against a real outage. |
| Continuous-integration gate set (41 workflows, aggregator in `scripts/ci/ci_aggregator.py`) | `stable-ish` | The gates are the most reliably exercised component in the repository — they run on every pull request, and their configuration is itself tested (`tests/ci/`, `tests/workflows/`, `tooling/ci/verify_branch_protection_required_checks_doc.py`). Nine of the twelve inventoried contexts are active in branch protection; three await an operator step, tracked in `docs/ci/branch-protection-required-checks.md`. |
| Operator and one-off tooling (`wirelang/cli/` dispatch and scoring helpers, `persona-pilot-export`, migration helpers, `tooling/baselines/`) | `internal` | Maintainer instruments for this repository's own operation. No external contract; may be removed without notice. |
| Live virtual-machine acceptance path (`.github/workflows/live-vm-acceptance.yml`, `scripts/ci-live-vm-*`, `scripts/federation-live-vm-acceptance.sh`) | `internal` | Requires operator credentials and a provisioned host, so it cannot run for an outside contributor. Deliberately `workflow_dispatch` only. Valuable — it is where hermetic tests have historically been proven insufficient — but not a standing guarantee. |

## Where this matrix deviates from the external review

The review of 2026-09-10 suggested example values in its stability
section. Four rows are set differently here, each for a reason
visible in the tree:

1. **Bridge audit writer: `beta` → `stable-ish`.** When the example
   was written the proof path was not yet a gate. It is now: the
   writer is step 2 of `make demo-proof`, runs on a clean runner on
   every pull request, and the report validator rejects any status
   other than `ok`. A component whose output is re-derived and
   checked on every change is not `beta` any more.
2. **Persona engine: `experimental` → `beta` for the deterministic
   core, `experimental` kept for the model-call and routing layer.**
   A single row hid a real difference. The hash, state machine,
   state backing and recovery paths are hash-pinned and
   parity-tested against Rust siblings; the routing and model-call
   layer is neither. Splitting the row is more useful than averaging
   it.
3. **"Rust secondary tooling": one row → two.** The benchmark and
   smoke crates are development instruments, not an experimental
   product surface, so they are `internal`. The 28 implementation crates keep `experimental` as the review
   suggested.
4. **"wakir-verify CLI": not listed here.** It is a different
   repository with its own matrix. What this repository can state
   about it is the pin in `proof-path.yml` and the compatibility
   gate, so those are the rows that appear above.

SPIFFE federation and the NATS runtime stay `experimental` exactly as
the review suggested, and for the reason the review gave: hermetic
tests do not substitute for operation.

## Keeping this file honest

A status here is a claim about evidence, not an aspiration. If you
change a component such that its note no longer describes the tree,
change the note in the same pull request. Two rules make that
checkable:

- A `stable-ish` row must name the gate that would fail if the
  component changed silently. No gate, no `stable-ish`.
- A row that claims live evidence must name the artefact — a receipt,
  a fixture cohort, a dispatch-only workflow. "It worked once" without
  an artefact in the tree is not evidence.
