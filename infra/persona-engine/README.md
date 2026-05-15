# wakir-persona-engine image

**Image:** `ghcr.io/wakir-labs/wakir-persona-engine`
**Source:** [`infra/persona-engine/Containerfile`][cf]
**License:** Business Source License 1.1 (`BUSL-1.1`); see
[`LICENSE-BSL.md`](./LICENSE-BSL.md). Change Date: 2030-05-15.
Change License: Apache-2.0. CPython stdlib inside the image ships
under PSF-2.0 and is reachable via `python3 --version`; the BSL
header does not extend to the stdlib.
**Sprint context:** Phase-2 Sprint-10 Tag-4 — substrate-gap-closer
for ADR-0058 Schritt 9 (Pilot-Phase Tomás-Persona-Spawn). The
Quadlet `quadlet/wakir-persona-tomas.container` (Selin Sprint-
Pengine-7 Tag-5 OI-PILOT-1) was authored against this image tag
ahead of the binary itself landing; this directory fills the gap.

[cf]: ./Containerfile

## Scope

Minimal Python image carrying the substrate-stub persona-engine
binary that satisfies the Quadlet contract declared in
`quadlet/wakir-persona-tomas.container`:

- CLI surface: `spawn` + `healthcheck` (+ `version`) per
  `wirelang/specs/persona-engine-format-spec.md` §"CLI invocation
  contract".
- Env-var contract: reads `WAKIR_PERSONA_ID`, `WAKIR_ORG_ID`,
  `WAKIR_PERSONA_STATE_BUCKET`, `WAKIR_NATS_SERVERS`,
  `SPIFFE_ENDPOINT_SOCKET` per spec §"Env var contract".
- Persona-axis-A/C bind-mount reads from `/etc/wakir/persona/`.

The stub computes a deterministic SHA-256 over the axis-A bytes and
emits it as a stub-flavoured pin-hash (`sha256-stub:...`); it does
not yet cross-check against the expected V-907 pin (that is a
Sprint-Pengine-8 axis surface).

The stub idles on a heartbeat loop after spawn and exits clean on
SIGTERM/SIGINT (so the Quadlet `Restart=on-failure` policy never
fires by accident).

## Why the stub exists

ADR-0058 Schritt 9 (Tomás-Persona-Spawn on the Pilot-VM) declared
the Quadlet `wakir-persona-tomas.container` against the image tag
`ghcr.io/wakir-labs/wakir-persona-engine:0.1.0-pilot` ahead of the
persona-engine binary itself landing. The substrate-layer (Quadlet,
SPIRE-SVID, NATS-KV bucket, Doppelbetrieb-Shadow bridging) is the
actual ADR-0058 Schritt 9 risk-surface — those moving pieces benefit
from running against a real Pilot-VM with a stub engine, not from
waiting until the engine is real to find out whether the substrate
is sound.

Mira-Hand-Decision 2026-05-15 (Sprint-10 Tag-4): ship the stub now,
rotate to the real engine when Sprint-Pengine-8 lands. The
4-Wochen-Doppelbetrieb-Clock is qualified accordingly: stub-period
output is excluded from the 4-Achsen-Score-Bilanz; the clock
effectively starts when `0.2.0-pilot` lands.

## Deferred surfaces (Sprint-Pengine-8 axis)

The stub does NOT implement, and explicitly logs at startup that it
defers, the following surfaces:

- NATS-KV state-pack persistence (no `nats-py`).
- SPIRE-Workload-API SVID fetch (no `cryptography` client).
- Spawn-session lifecycle state-machine per spec §3.3.
- Persona-canonical-form / V-907 pin-hash verification per axis-C.
- Recovery-workflow R1..R4 per spec §3.7.4.
- Doppelbetrieb-Shadow output bridging per
  `infra/migration-pilot/TOMAS_SPAWN_RECIPE.md` §0.

When the Sprint-Pengine-8 axis lands these surfaces, the image tag
rotates (`0.2.0-pilot` or `1.0.0`) and
`scripts/image-pin-idempotent-resolver.sh` flips the digest pin on
the Quadlet via the standard `resolve-image-pins-ci` workflow.

## Sprint-Pengine-8 real-engine image (`0.2.0-pilot`)

Sprint-Pengine-8 (Selin) lands the **real** engine implementation
alongside the stub. The real engine is sourced from
`wirelang/persona_engine/` (a normal Python package under the
wakir-runtime tree) and entered via the thin shim
`infra/persona-engine/bin/persona-engine-real`. It implements all
six deferred surfaces:

1. NATS-KV state-pack persistence (`state_backing.py` —
   `InMemoryPersonaStateBacking` shipped; `NatsKvPersonaStateBacking`
   reserved for Sprint-Pengine-9 asyncio-binding).
2. SPIRE Workload-API probe (`svid_workload_identity.py` — socket-
   presence + SPIFFE-ID-template surface; full grpc SVID fetch
   reserved for Sprint-Pengine-9).
3. Lifecycle state-machine (`lifecycle_state_machine.py` — six states,
   nine transitions, full audit-replay surface).
4. V-907 pin-verify (`v907_verify.py` — delegates to the existing
   `wirelang.persona.persona_hash.compute_persona_hash_from_canonical`
   primitive, no new hash function introduced).
5. Recovery workflow R1..R4 (`recovery_workflow.py` — full
   phase-sequential implementation with 30s end-to-end budget and
   closed failure-mode enum).
6. Doppelbetrieb-shadow output bridging (`bridge_audit_writer.py` —
   double-sink JCS-canonical envelope to Pre-Framework Markdown +
   Wakir-Runtime structured log).

### Build path (real engine)

```
gh workflow run build-wakir-persona-engine.yml \
  -f version_tag=0.2.0-pilot \
  -f containerfile=Containerfile.real \
  -f push=true
```

The build workflow now exposes a `containerfile` input that selects
between `Containerfile` (stub, default; `0.1.0-pilot`) and
`Containerfile.real` (real engine; `0.2.0-pilot`).

### Image-swap rotation (operator runbook)

1. Build `0.2.0-pilot` real-engine image via the workflow above.
2. Open a Quadlet pin-rotation PR updating
   `quadlet/wakir-persona-tomas.container` Image= line tag from
   `0.1.0-pilot` to `0.2.0-pilot`.
3. Let `resolve-image-pins-ci` fill the `@sha256:DIGEST_PENDING_*`
   placeholder with the live digest.
4. Operator-Hand on the Pilot-VM:
   `sudo systemctl restart wakir-persona-tomas.service`.
5. Verify with `podman logs --tail 50 wakir-persona-tomas` — the
   real engine emits `engineering_output` events instead of the
   stub's `substrate-stub-deferred-surfaces` roll-call.

The CLI surface is byte-stable across the rotation: the Quadlet
`Exec=spawn --persona-slug tomas --pilot-phase doppelbetrieb-shadow`
line works against both images. Only the **semantics** change (stub
heartbeat -> real spawn+output+recovery cycle).

### Doppelbetrieb-Vergleichs-Clock anchor

The 4-Achsen-Score-Bilanz clock starts effectively when the real
engine emits its first `engineering_output` event (per the BridgeAuditWriter
JCS envelope). Stub-period output is filtered out by `output_kind`
discrimination (the stub emits no `engineering_output` events at all;
the real engine emits one per spawn-session step).

## Build path

`Operator-Hand` only, via `workflow_dispatch`:

```
gh workflow run build-wakir-persona-engine.yml \
  -f version_tag=0.1.0-pilot \
  -f push=true
```

The workflow:

1. Resolves `docker.io/library/python:3.13-slim` digest via
   skopeo + crane cross-check.
2. Materialises the digest into the Containerfile in-runner (NOT
   committed back to the repo).
3. Builds with buildah.
4. Sigstore-keyless signs against the GitHub-Actions OIDC identity.
5. Pushes to `ghcr.io/wakir-labs/wakir-persona-engine:<tag>`.
6. Emits the resulting digest to the workflow summary so the
   operator can run `resolve-image-pins-ci` (or the local resolver)
   to flip the Quadlet pin.

## Pin path

The image-pin lives in:

- `scripts/image-pin-idempotent-resolver.sh` PINS array (row
  `wakir_persona_engine|ghcr.io/wakir-labs/wakir-persona-engine|
  quadlet/wakir-persona-tomas.container`).
- `quadlet/wakir-persona-tomas.container` line 86 (image declaration
  with the `@sha256:<digest>` suffix).

The resolver tolerates `DIGEST_PENDING_<TOKEN>` placeholders for the
digest hex (any uppercase token prefixed with `DIGEST_PENDING_`).
The persona-engine pin uses `DIGEST_PENDING_KAI_CROSS_REVIEW` to
keep cross-pair ownership (Kai Zone-J) explicit in the diff history.

## Operator local smoke

The image is meant to run via Quadlet on the Pilot-VM. For local
debugging:

```
buildah bud \
    --tag wakir-persona-engine:local \
    -f infra/persona-engine/Containerfile \
    infra/persona-engine/

# Healthcheck (must run with a persona-def bind-mount or it exits 1):
podman run --rm \
    -v /tmp/persona-def:/etc/wakir/persona:ro \
    wakir-persona-engine:local healthcheck

# Version:
podman run --rm wakir-persona-engine:local version
```
