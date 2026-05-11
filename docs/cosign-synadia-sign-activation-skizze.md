# Cosign + Synadia-Sign Activation — Skizze (Phase-2 Sprint-6 Tag-4)

- **Status:** draft, Phase-2 Sprint-6 Tag-4
- **Owner:** Kai Hoffmann (DevOps / Container-Orchestration)
- **Cross-Review:** Zone-C (Container-Image-Pipeline x OTS-Anchoring,
  Tomas Matrix-Lead-Side ack required before production-cutover); the
  hermetic mock-verification surface in this skizze does NOT modify any
  Zone-C contract surface (compose image-pin and quadlet image-pin
  remain byte-precise-aligned).
- **Scope-Cut:** doc skizze + hermetic mock-verify-tests; NO production
  signing keys, NO registry push, NO cosign binary install in the
  authoring sandbox (Mira-Sandbox-vs-Host-Operations-Trennung per
  ADR-0051-rejected). All real signing operations are operator-hand on
  the build-host.

---

## 0 / Section index

| # | Topic | Source |
|---|---|---|
| 1 | Why this skizze now (motivation, Phase-2 Hardening) | Phase-2 Sprint-6 Tag-3 follow-item 6, Phase-2 Sprint-6 Tag-4 |
| 2 | Existing surface (Tag-3 hermetic baseline) | scripts/verify-image-digest.sh `--with-cosign` flag |
| 3 | Production-Path A: Cosign Container-Image-Signing | Phase-2 Sprint-6 Tag-4 |
| 4 | Production-Path B: NATS NKey Operator/Account-Signing | Phase-2 Sprint-6 Tag-4 |
| 5 | Hermetic test-wire-up (Mock-cosign-binary pattern) | Phase-2 Sprint-6 Tag-4 |
| 6 | Cross-Review-Zone-C non-touched stamp | Phase-2 Sprint-6 Tag-4 |
| 7 | Operator runbook stub (production cutover) | Phase-2 Sprint-6 Tag-4 |
| 8 | Open items / Phase-3 deferrals | Phase-2 Sprint-6 Tag-4 |
| 9 | Box-Stempel | Phase-2 Sprint-6 Tag-4 |

---

## 1 / Why this skizze now

Phase-2 Sprint-6 Tag-3 closed with a follow-item list. Item 6 (NIEDRIG
carryover from Sprint-6 Tag-2) was Cosign + Synadia-Sign-Activation
for the substrate hardening path. Tag-4 picks it up as a doc+test
skizze, because the production activation requires:

* a private signing key (KMS-backed or file-backed, operator
  generates),
* a public registry push (image-push from a controlled build-host),
* in the NATS case: an operator-jwt swap on the running cluster
  (production-down or rolling-restart depending on cluster topology).

None of those are in scope for the CEO-side authoring sandbox per
the Sandbox-Host-Trennung directive. The skizze therefore documents:

1. the production-step sequence an operator follows on a build-host
   to do the real activation, and
2. a hermetic mock-verification harness so the wakir-runtime test
   surface gains coverage of the cosign-verify flag-surface without
   requiring the cosign binary or network access during pytest.

## 2 / Existing surface (Tag-3 hermetic baseline)

The `scripts/verify-image-digest.sh` script already has a
`--with-cosign` flag, added in Sprint-4 Tag-3 as part of the Zone-C
digest-pin upgrade. The flag is gated by `command -v cosign` and by
the image-form being digest-pinned (not tag-only). It is documented
as operator-hand in the script preamble; the hermetic test suite
`tests/orchestrator/test_verify_image_digest.py` deliberately skips
the `--with-cosign` path because the authoring sandbox does not
have cosign installed.

This skizze upgrades the test surface by adding a Mock-cosign-binary
pattern so the `--with-cosign` codepath can be exercised
hermetically.

## 3 / Production-Path A — Cosign Container-Image-Signing

### 3.1 Goal

Make every Wakir-controlled container image (Phase-3+ scope:
`wakir-orchestrator`, `wakir-evaluator`, `wakir-persona-*` images
when they exist) cosign-signed with a Wakir-controlled keypair and
let downstream consumers verify the signature via
`cosign verify <image>@sha256:<digest>` before deployment.

For Phase-2 the substrate image is `nats:2.11-alpine` (upstream
Synadia). Synadia does not currently publish a cosign signature on
that image (see Section 4 for the NATS-side discussion). The
Phase-2-Hardening posture is therefore:

* substrate image (`nats:`): digest-pinned (already done Sprint-4
  Tag-3), `--with-cosign` is a no-op for now but the surface is
  ready for the day Synadia ships signatures,
* future Wakir-built images: cosign-sign on the build-host before
  push, cosign-verify on the deployment-host before run.

### 3.2 Operator steps on the build-host (production)

```
# 1. Install cosign (Fedora Atomic via rpm-ostree or toolbox)
rpm-ostree install cosign
# or (toolbox / non-atomic):
sudo dnf install cosign

# 2. Generate a keypair (interactive password prompt; key file is
#    cosign.key, public material is cosign.pub). Operator stores
#    the .key file in Infisical or a hardware-backed KMS; the .pub
#    file is checked into the repo for verifier-side use.
cosign generate-key-pair

# 3. Build the image with reproducible flags (BuildKit, SOURCE_DATE_
#    EPOCH set, content-addressable layers); push to registry.
podman build -t ghcr.io/wakir-labs/wakir-orchestrator:0.1.0 .
podman push ghcr.io/wakir-labs/wakir-orchestrator:0.1.0

# 4. Resolve the post-push digest (registry-side, not local).
DIGEST="$(podman image inspect \
  ghcr.io/wakir-labs/wakir-orchestrator:0.1.0 \
  --format '{{ index .RepoDigests 0 }}')"
echo "${DIGEST}"
# Expected form: ghcr.io/wakir-labs/wakir-orchestrator@sha256:<64-hex>

# 5. Sign with the cosign key (COSIGN_PASSWORD picked up from
#    Infisical-injected env on the build-host).
cosign sign --key cosign.key "${DIGEST}"

# 6. Verify locally before declaring the build clean.
cosign verify --key cosign.pub "${DIGEST}"
```

### 3.3 Verifier-side (deployment-host)

```
# Pre-deployment gate, hermetic verification (cosign.pub from repo):
scripts/verify-image-digest.sh \
    --compose-file compose/wakir-orchestrator.yaml \
    --with-cosign \
    --cosign-pubkey ./cosign.pub \
    --strict
```

Phase-2 Sprint-6 Tag-4 NOTE: the `--cosign-pubkey` flag is a
**future** extension of `scripts/verify-image-digest.sh`. Tag-4 does
NOT add it yet because the substrate image is not signed; the
extension is in Section 8 open-items as a Phase-3 follow-up.

### 3.4 Threat model

* Compromised registry: cosign-sig binds the digest to the key; an
  attacker who replaces the digest server-side cannot forge the
  signature without the private key.
* Compromised build-host: if the build-host's private key is
  exfiltrated, an attacker can sign arbitrary images. Mitigation:
  KMS-backed key (cosign with `--key gcpkms://...` or `awskms://...`)
  so the key never leaves the KMS boundary; operator's account
  needs sign-permission on the KMS resource.
* Compromised deployment-host: cosign-verify can be bypassed by
  removing the `--strict` gate; mitigation is a CI smoke gate on
  the deployment substrate that re-runs cosign verify
  pre-rollout.

## 4 / Production-Path B — NATS NKey Operator/Account-Signing

### 4.1 Goal

Enable NATS account isolation and JWT-based authorization on the
Phase-1b substrate so the orchestrator, the agent containers, and
the (future) federation route registry are each in their own
account with explicit publish/subscribe permissions on their
respective subject prefix.

This is the NATS-server-side equivalent of "Synadia-Sign-Aktivierung":
operators generate an operator-NKey, an account-NKey per logical
namespace, and per-account user-NKeys, then the NATS server
verifies inbound CONNECT messages against a JWT signed by the
account-NKey, which in turn is signed by the operator-NKey.

### 4.2 Current Phase-1b state

The Phase-1b substrate uses **no auth** (loopback-bound,
single-tenant). The `compose/nats.yaml` opens only `127.0.0.1:4222`
and `127.0.0.1:8222`. The orchestrator client connects over
loopback without TLS, without auth.

This is acceptable for Phase-1b dev-substrate. It is NOT acceptable
for Phase-2 multi-agent operation if agents are co-tenanted with
the orchestrator on the same NATS cluster. Phase-2 hardening
direction: introduce NKey-based auth.

### 4.3 Operator steps on the build-host (production)

```
# 1. Install the nsc CLI (NATS Account-NKey ops; ships separately
#    from the nats-server).
curl -L https://github.com/nats-io/nsc/releases/latest/download/\
nsc-linux-amd64.tar.gz | tar xz
sudo install -m 755 nsc /usr/local/bin/

# 2. Create an operator (one per Wakir cluster identity).
nsc add operator --name wakir-operator --sys

# 3. Create accounts: one per logical namespace.
nsc add account --name wakir-orchestrator
nsc add account --name wakir-agents
nsc add account --name wakir-federation

# 4. Create users with subject-scoped permissions.
nsc add user --account wakir-orchestrator --name orch-1 \
    --allow-pub 'wakir.orch.>' \
    --allow-sub 'wakir.orch.>'
nsc add user --account wakir-agents --name agent-tomas \
    --allow-pub 'wakir.agents.tomas.>' \
    --allow-sub '_INBOX.>'
# ... per agent

# 5. Generate the operator JWT and accounts JWT bundle.
nsc generate config > /etc/nats/auth.conf

# 6. Reference the JWTs from the NATS server config.
#    nats-server.conf snippet:
#      operator: file:///etc/nats/operator.jwt
#      resolver: MEMORY
#      resolver_preload {
#        <account-id-1>: <account-jwt-1>
#        <account-id-2>: <account-jwt-2>
#      }

# 7. Reload (rolling restart on cluster, or SIGHUP on single-node).
sudo systemctl reload wakir-nats.service
```

### 4.4 Compose/Quadlet impact

When this lands in production, the compose and quadlet files gain
a bind-mount for `/etc/nats/auth.conf` (or equivalent volume) and
the `nats-server` command-line gains `-c /etc/nats/auth.conf`.
This is a Cross-Review Zone-C touchpoint (compose-pin surface
changes), so a Tomas Matrix-Lead-Side ack is required before
production cutover.

Phase-2 Sprint-6 Tag-4: NOT applied to the substrate yet. The
substrate stays no-auth for Phase-2 single-tenant operation. Auth
activation is a Phase-3 item.

### 4.5 Threat model

* Compromised operator-NKey: an attacker can issue arbitrary
  account JWTs. Mitigation: operator-NKey lives only on a
  developer-laptop (or HSM) and is never on the NATS server.
* Compromised account-NKey: an attacker can issue user-JWTs for
  that account. Mitigation: account-NKey rotation procedure
  (re-issue user-JWTs, push new account-JWT to resolver).
* Compromised user-credential file: subject-scoped permissions
  limit blast radius to the subject prefix that user can
  publish/subscribe on.

## 5 / Hermetic test-wire-up (Mock-cosign-binary pattern)

### 5.1 Why mock

The authoring sandbox does not have cosign installed (and per the
ADR-0051 directive, must not invoke network operations or
host-podman). But the `--with-cosign` codepath in
`scripts/verify-image-digest.sh` is non-trivial: it does flag
parsing, form gating, and exit-code semantics. A mock-binary
harness lets the test surface verify that codepath without the
real cosign.

### 5.2 Mechanism

The test fixture writes a tiny `cosign` shell script to `tmp_path /
"bin" / "cosign"` and runs the script under
`PATH=<tmp_path/bin>:<original PATH>`. The mock script reads its
own argv, optionally an env-var like `MOCK_COSIGN_VERIFY_EXIT`, and
exits with the configured exit-code. This is a standard "PATH-
shim" pattern used in CI test harnesses.

The pattern is hermetic by construction: no network, no real cosign
on disk, no podman, no NATS. It only verifies the bash-side flag
handling and exit-code mapping in the script.

### 5.3 Coverage matrix

| # | Scenario | Mock-binary returns | Expected script exit |
|---|---|---|---|
| 1 | `--with-cosign` on digest-pinned compose, mock passes | exit 0 | exit 0 |
| 2 | `--with-cosign` on digest-pinned compose, mock fails | exit 1 with error stderr | exit 1 (`cosign_status: verify-failed`) |
| 3 | `--with-cosign` without cosign on PATH at all | (no mock) | exit 1 (`cosign_status: binary-missing`) |
| 4 | `--with-cosign` on tag-only compose | mock unreachable | exit 1 (`cosign_status: not-digest-pinned`) |

All four scenarios are added in `tests/orchestrator/
test_verify_image_digest_cosign_mock.py` (new Tag-4 file, sibling
to `test_verify_image_digest.py`).

### 5.4 What the mock does NOT cover

The mock does not exercise:

* real sigstore TUF-root verification,
* real keyless OIDC flow (Fulcio + Rekor),
* network probes from cosign itself.

Those are operator-hand on the build-host, gated by a separate CI
smoke that runs `cosign verify` against a known-good signed image
(future Phase-3+ scope, when Wakir publishes its first signed
image).

## 6 / Cross-Review-Zone-C non-touched stamp

This skizze does not modify:

* `compose/nats.yaml` (image-pin form unchanged),
* `quadlet/wakir-nats.container` (image-pin form unchanged),
* `scripts/verify-image-digest.sh` (Tag-4 does NOT extend the
  script's flag surface; the future `--cosign-pubkey` extension
  in Section 3.3 is a Phase-3 follow-up listed in Section 8),
* the Zone-C parity test
  `tests/orchestrator/test_quadlet_nats.py::
  test_quadlet_image_matches_compose_digest_pin`.

Zone-C contract surface stays byte-precise-aligned. The Tag-4 work
is doc-only plus a new sibling test file, no source-pinned
artefact mutation.

## 7 / Operator runbook stub (production cutover)

When Phase-3+ Wakir-built images exist:

1. Operator on build-host: install cosign, generate or load keypair
   (KMS-backed preferred).
2. Build + push image; record post-push digest from registry.
3. `cosign sign --key <key> <image>@sha256:<digest>`.
4. `cosign verify --key <pub> <image>@sha256:<digest>` to confirm
   sign worked.
5. Update consumer compose-files / quadlet-units with the
   post-push digest.
6. Run `scripts/verify-image-digest.sh --with-cosign
   --cosign-pubkey <pub> --strict` on the deployment-host.
7. Post-deployment: smoke-test the container, confirm health-probe
   pass.

For Phase-2 substrate (`nats:2.11-alpine` unsigned):

1. `scripts/verify-image-digest.sh` runs in default mode (no
   `--with-cosign`). Digest-pin form is enforced.
2. If Synadia publishes a signature in the future:
   * operator confirms the public key,
   * extends `--with-cosign` invocation with the appropriate
     `--cosign-pubkey` or keyless-OIDC verifier-identity,
   * promotes the cosign-verify to the standard pre-rollout gate.

For Phase-2 NATS-auth-activation (currently deferred to Phase-3):

1. Operator on build-host: install nsc, generate operator-NKey,
   account-NKeys, user-NKeys.
2. Generate operator-JWT and account-JWT bundle.
3. Update `compose/nats.yaml` to bind-mount `/etc/nats/auth.conf`
   (Cross-Review Zone-C touchpoint — needs Tomas Matrix-Lead-Side
   ack).
4. Rolling-restart the NATS substrate.
5. Update orchestrator client config to present user-credentials
   on connect.
6. Confirm the orchestrator can publish/subscribe under its
   account's subject scope, and that cross-account publishes
   are rejected.

## 8 / Open items / Phase-3 deferrals

| # | Item | Disposition |
|---|---|---|
| O1 | Extend `verify-image-digest.sh` with `--cosign-pubkey <pub>` flag | Phase-3 follow-up; not in Tag-4 scope (substrate image is unsigned upstream) |
| O2 | Build-host CI smoke gate calling `--with-cosign` on a known-good signed image | Phase-3 follow-up; requires first Wakir-built signed image |
| O3 | NATS NKey activation (operator-JWT + account-JWT resolver) | Phase-3 follow-up; Zone-C touchpoint; requires Tomas ack |
| O4 | Synadia upstream cosign-sign tracking | external dependency; revisit when Synadia announces sigstore integration for `nats` image |
| O5 | KMS-backed cosign-keypair (vs. file-backed) | Phase-3 follow-up; depends on KMS choice (GCP-KMS / AWS-KMS / HashiCorp-Vault-Transit) |
| O6 | OTS-Anchoring of cosign-signed digests (Cross-Review Zone-C) | Phase-3 follow-up; current OTS pipeline anchors commit-hashes, the image-digest anchoring is a separate (Tomas-owned) addition |

## 9 / Box-Stempel

- **Date:** 2026-05-11 (CEST `date -Iseconds` 2026-05-11T~23:30+02:00).
- **Box:** Sprint-6 Tag-4 ~90-Min-Box (Continuous-Mode-Welle
  follow-up to Tag-3 follow-item 6).
- **Worktree:** `/tmp/kai-sprint-6-tag-4-cosign-sign-runtime`
  (ADR-0049-konform, dediziertes `git worktree add` aus
  `agents-workspaces/kai/wakir-runtime` forked from Sprint-6 Tag-3
  tip `dddcac2`).
- **Branch:** `kai/phase-2-sprint-6-tag-4-cosign-sign-skizze`.
- **Tool-Surface-Stempel (ADR-0050):** Bash, Read, Edit, Write,
  Grep. **NO Agent-Tool** (per Persona §7). **NO Host-podman-Socket**
  (per ADR-0051-rejected operative sandbox directive).
- **Zone-A/B/C/D non-touched:** SPIFFE-Constants unchanged,
  NATS-Subject-Schema unchanged, compose-pin unchanged, quadlet-pin
  unchanged, no Phala-touchpoints.
- **Sibling artefact (new Tag-4 file):** `tests/orchestrator/
  test_verify_image_digest_cosign_mock.py` adds hermetic
  Mock-cosign-binary coverage for the `--with-cosign` codepath.

— Kai
