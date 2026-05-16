# Quadlet-Rotation-Stub — 0.4.2-pilot → 0.5.0-pilot

**Author:** Selin Çelik (Persona-Engine-Engineer)
**Date:** 2026-05-16
**Audience:** Kai (Federation-Substrate / Container-Bridge) — Zone J
**Status:** Stub document — Kai-Hand follow-up PR after Sprint-Pengine-13 merges

This document is the **operator-hand recipe** for rotating the
`wakir-persona-tomas.container` Quadlet pin from `0.4.2-pilot` to
`0.5.0-pilot` once Sprint-Pengine-13 merges and the build workflow
publishes the new image. Selin (Persona-Engine) does **not** edit
the Quadlet — that is Kai's domain (Cross-Review-Zone J).

## Pre-conditions

1. PR for Sprint-Pengine-13 merged on `wakir-runtime/main`.
2. `build-wakir-persona-engine.yml` workflow dispatched with:
   - `version_tag=0.5.0-pilot`
   - `containerfile=Containerfile.real`
   - `push=true`
3. GHCR digest resolved (workflow output: `steps.push.outputs.digest`).
4. Tomás OTS-anchor of the digest (Zone K) recorded.

## Quadlet edits required

File: `quadlet/wakir-persona-tomas.container`

### Edit 1 — `Image=` line tag bump

```diff
-Image=ghcr.io/wakir-labs/wakir-persona-engine:0.4.2-pilot@sha256:<old-digest>
+Image=ghcr.io/wakir-labs/wakir-persona-engine:0.5.0-pilot@sha256:DIGEST_PENDING_KAI_CROSS_REVIEW
```

Then run `scripts/image-pin-idempotent-resolver.sh` (or the
`resolve-image-pins-ci` workflow) to fill the `DIGEST_PENDING_*`
placeholder with the live GHCR digest.

### Edit 2 — Add `WAKIR_NATS_SUBSCRIBE_MODE` env var (NEW for Bug-42)

Insert into the `[Container]` section near the existing
`Environment=WAKIR_SUBSCRIBE_ENV=dev` line (or add that line too
if not yet present — required since Sprint-Pengine-12 for the
async path):

```diff
 Environment=WAKIR_PERSONA_ID=tomas
 Environment=WAKIR_ORG_ID=acme
+# Sprint-Pengine-12 — activate async-engine + subscribe-loop path.
+Environment=WAKIR_SUBSCRIBE_ENV=dev
+# Sprint-Pengine-13 Bug-42 — explicit subscribe mode selector.
+# Values: core-callback (default, production-safe), core-iterator
+# (backward-compat), jetstream-pull (Phase-2 substrate).
+# Leaving this unset is equivalent to ``core-callback``.
+Environment=WAKIR_NATS_SUBSCRIBE_MODE=core-callback
```

### Edit 3 — Bump Quadlet header comment version reference

The header comment in the Quadlet file probably references
`0.4.2-pilot` (or earlier) in the rotation pattern docstring.
Bump to `0.5.0-pilot` for clarity, no functional change.

## Live-VM smoke after rotation

1. `sudo systemctl restart wakir-persona-tomas` on the Pilot-VM.
2. `sudo podman logs wakir-persona-tomas --tail 50` — expect:
   - `engine_version=0.5.0-pilot`
   - `cli-async-dispatch ... subscribe_mode=core-callback`
   - `subscribe-loop-started ... subscribe_mode=core-callback`
3. From the operator host:
   ```
   python -m wirelang.cli.mira_dispatch \
     --persona-slug tomas \
     --prompt "Hallo Tomás, status?" \
     --nats-url nats://<pilot-vm-ip>:4222 \
     --env dev
   ```
4. Expect in `podman logs wakir-persona-tomas`:
   - `task-processing-begin auftrag_id=...`
   - `task-output-published auftrag_id=... subject=wakir.dev.agent.agent.task.output.tomas`
   - `task-processing-complete auftrag_id=...`
5. From the operator host:
   ```
   nats sub 'wakir.dev.agent.agent.task.output.tomas' --server nats://<pilot-vm-ip>:4222
   ```
   Expect: at least one envelope with the matching `auftrag_id` and
   `engine_version=0.5.0-pilot`.

## Rollback

If the live-VM smoke fails:
1. Edit Quadlet back to pin `0.4.2-pilot` digest.
2. `sudo systemctl restart wakir-persona-tomas`.
3. Bug-Report to Selin via Mira inbox; include `podman logs` output.

## Cross-Review hooks (Zone J)

- Kai owns the Quadlet edit + image-pin resolution.
- Selin (this doc) owns the recipe + the engine substrate.
- Aisha protocols the Zone-J cross-review consensus timestamp.

---

*— Selin Çelik (Persona-Engine-Engineer), Sprint-Pengine-13*
