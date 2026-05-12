# Runbook — SPIRE-Server-Sidecar Phase-2.1 (Sprint-6-Tag-8 rebase)

**Owner:** Kai Hoffmann (DevOps).
**Status:** Phase-2.1 hermetic substrate authored (Tag-6) plus
  Cosign-Digest-Pin form (Tag-8 rebase). Image-digest substitution
  pending Operator-Hand + Tomás Zone-C cross-review.
**Hermetic-Status:** authored under ADR-0051 Sandbox-Trennung. No
  `podman run`, no live registry-pull in this sprint-tag.

## 1. Why

Sprint-6-Tag-6 laid down the SPIRE-Server-Sidecar as the Workload-
Identity-Substrate referenced by ADR-0020 (Phase-1b Container-
Orchestrator). The Tag-7 follow-up that added the Cosign-Digest-Pin
form was authored on a `/tmp`-worktree without `origin` setup — it
forked from a phantom baseline rather than the real Tag-6 tip
(`1d41dd8`). This Tag-8 box rebases the Tag-7 substance back onto the
real Tag-6 tip per Mira-Box-Brief.

The substrate consists of:

1. `compose/spire.yaml` — Podman/Docker-Compose service definition.
   Tag-6 carried the hermetic-network layout, named volumes, deploy
   limits, and `cap_drop: ALL` + `no-new-privileges:true` hardening.
   Tag-8 adds the **Cosign-Digest-Pin form** on the image reference,
   plus read-only root filesystem, non-root uid:gid, tmpfs for
   `/run/spire`, and an explicit loopback ports mapping.
2. `config/spire-server.conf` — SPIRE-Server HCL config. Tag-6's
   hermetic-only ``example.test`` trust-domain is **preserved**
   (not the Tag-7 ``wakir.dev`` drift). Production trust-domain
   migration is a Phase-2.4 NATS-JWT-Auth integration tag, not this
   rebase.

## 2. Image-Pin Workflow (Operator-Hand)

The compose file carries a **placeholder digest**:

```
image: "ghcr.io/spiffe/spire-server:1.14.6@sha256:DIGEST_PENDING_TOMAS_REVIEW"
```

This is deliberate. Per ADR-0051 the Mira-sandbox has no host-podman
or registry access, so the real digest cannot be fetched from this
agent context. Before the substrate is brought live the Operator
must:

1. **Verify upstream signature** (cosign):
   ```
   cosign verify \
     --certificate-identity-regexp 'https://github.com/spiffe/spire/.*' \
     --certificate-oidc-issuer https://token.actions.githubusercontent.com \
     ghcr.io/spiffe/spire-server:1.14.6
   ```
   The upstream SPIFFE project signs releases via GitHub-Actions
   OIDC. (P7 verification stamp: this command form is the documented
   cosign-keyless verification pattern; the exact identity-regex may
   need updating after a SPIFFE-release-engineering review — Tomás
   Zone-C-Cross-Review confirms.)

2. **Resolve the digest:**
   ```
   skopeo inspect docker://ghcr.io/spiffe/spire-server:1.14.6 \
     | jq -r '.Digest'
   ```
   Output is the canonical `sha256:<64-hex>` digest.

3. **Replace the placeholder** in `compose/spire.yaml` with the
   resolved digest. Commit message:
   `chore(spire): pin spire-server image to sha256:<short>`.

4. **Tomás Zone-C-Cross-Review** before the substrate is started
   live: Image-Pipeline × OTS-Anchoring impact must be confirmed
   (the Persona-Container-Image-Hash-Pinning workflow in V-907 will
   eventually need to anchor SPIRE-Server-image-digests too).

5. **Re-run the acceptance suite**:
   ```
   pytest tests/orchestrator/test_compose_spire.py \
          tests/orchestrator/test_compose_spire_cosign_pin.py
   ```
   The acceptance suite accepts either the placeholder or a 64-hex
   digest, so it stays green throughout the substitution workflow.

## 3. Bring-Up Procedure (Operator-Box, NOT Mira-Sandbox)

> **Run from an operator-controlled host with podman installed.**
> Never run from the Mira-sandbox (ADR-0051).

```
cd <repo-root>
podman-compose -f compose/spire.yaml up -d spire-server
podman logs -f wakir-spire-server   # expect: "spire-server listening on :8081"
```

The `wakir-orchestrator` bridge network is shared with
`compose/nats.yaml`; bringing up both files on the same network is a
no-op after the first.

### First-time bootstrap (generate a join-token for the future agent):

```
podman exec wakir-spire-server \
    /opt/spire/bin/spire-server token generate \
        -spiffeID spiffe://example.test/sprint-6/agent-bootstrap
```

(SPIFFE-ID uses the hermetic ``example.test`` trust-domain. Production
SPIFFE-IDs use the Phase-2.4 trust-domain, not this hermetic stand.)

Store the returned token in Infisical under
`infra/spire/join-tokens/sprint-6-agent-bootstrap` (Operator-Hand;
Mira-sandbox has no Infisical-write).

### Health-check:

```
podman exec wakir-spire-server /opt/spire/bin/spire-server healthcheck
# Exit 0 = healthy.
```

## 4. Acceptance Criteria (Sprint-6-Tag-8)

- [x] `compose/spire.yaml` exists and parses as valid Compose YAML.
- [x] Image is pinned in the form
      `ghcr.io/spiffe/spire-server:1.14.6@sha256:<digest-or-placeholder>`.
- [x] Container runs read-only-rootfs, drops ALL caps, has
      `no-new-privileges:true`, runs as uid:gid `1000:1000`.
- [x] tmpfs for `/run/spire` declared (rootfs is read-only).
- [x] Healthcheck uses the `spire-server healthcheck` built-in.
- [x] Config-file mount is read-only; data volume is named.
- [x] API port is bound to `127.0.0.1:8081` only (no exposure).
- [x] Trust-domain is `example.test` (hermetic only — see Tag-6
      header for IANA-RFC-6761 rationale).
- [x] JWT-SVID default TTL is `15m`.
- [x] Datastore is SQLite for Sprint-6 (Phase-3 migrates to
      Postgres).
- [x] NodeAttestor is `join_token` for manual bootstrap.
- [x] Acceptance suite: 16 (Tag-6 invariants) + 9 (Tag-8
      Cosign-Pin) = 25 SPIRE-Compose tests; full suite 304 passed +
      25 skipped = 329 collected.

Open items (deferred to a later sprint-tag, **not** in this Tag-8
scope):

- [ ] Real digest substitution (Operator-Hand + Tomás Zone-C).
- [ ] SPIRE-Agent-Sidecar (separate service block, Workload-API-
      Unix-Socket-share) — Phase-2.2 trigger once Reza delivers
      the SPIFFE-Workload-API-Adapter-impl-slot-1.
- [ ] Production trust-domain switch — Phase-2.4
      NATS-JWT-Auth-integration tag.
- [ ] Postgres-datastore-migration (Phase-3).
- [ ] Phala-Cloud-attestation-bridge (V-904 Phase-3, Zone-D-Reza-
      Cross-Review-Gate).

## 5. Rollback

There is nothing running in production from this sprint-tag — the
substrate is authored but not deployed. Rollback is a `git revert`
of the Tag-8-commit on the rebase branch; no live-system impact.

## 6. References

- ADR-0020 — Container-Orchestrator Phase-1b.
- ADR-0023b — V-904-Annex (Reza-Cross-Review-Pflicht für Phala-
  Cloud-Bridge).
- ADR-0049 — Worktree-Pattern (this sprint-tag worktree:
  `/tmp/kai-sprint-6-tag-8-rebase-runtime`, branch
  `kai/phase-2-sprint-6-tag-8-rebase-cosign-pin`).
- ADR-0050 — Tool-Surface-Pflicht-Stempel.
- ADR-0051 — Mira-Sandbox vs. Host-Operations Trennung
  (rejected variant; operational principle stays: no host-podman-
  socket in Mira-sandbox).
- Reza-Zone-A-Spec (SPIFFE/SPIRE-Workload-Identity).
- Cosign upstream docs (keyless-signing-verification pattern).

— Kai
