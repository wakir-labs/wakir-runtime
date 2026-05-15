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
