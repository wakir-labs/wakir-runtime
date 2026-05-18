<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# Cosign-Keyless-OIDC-Drift-Probe — Operator Recipe

**Status:** Tag-47 substrate, Operator-Hand refresh recipe.
**Owner:** Kai Hoffmann (Dev-Engineering-3, Container-Orchestration).
**Cross-Review zones:** C (Container-Image-Pipeline x Tomás-OTS).

## 1. What this probe does

Tracks the **time-axis** drift of the Sigstore-keyless-OIDC chain
that signs the 15-binary Tag-45 Cosign-Policy inventory:

  * **Trust-Root axis** — Sigstore project re-tags the cosign-installer
    action, rotates the Fulcio root CA, or cuts a new Rekor
    transparency-log shard.
  * **OIDC-identity axis** — the GitHub-Actions OIDC issuer URL
    changes, or the per-binary build_workflow path is renamed and
    the identity-claim regexp no longer matches.

Tag-45 PR #294 + Tag-46 PR #298 pin the static substrate shape;
this probe extends the coverage along the time-axis so an operator
notices upstream shifts within ~24h instead of at the next
cosign-verify failure.

## 2. Daily baseline mode (CI workflow)

The daily CI workflow at 06:30 UTC runs:

```
python3 scripts/observability/cosign-keyless-oidc-drift-probe.py \
    --policy policies/cosign-policy-phase-3b.yaml \
    --pinned-trust-root state/cosign-drift/pinned-trust-root.json \
    --repo-root . \
    --mode baseline
```

Baseline mode synthesises a self-consistent snapshot from the
policy + pinned-trust-root files. It catches substrate-side drift:

  - policy YAML inventory drifted from the Tag-45 canonical 15
  - per-binary build_workflow path renamed / deleted
  - policy schema_version changed
  - pinned-trust-root JSON malformed / missing keys

It does NOT catch upstream-Sigstore drift, because baseline mode
has no Sigstore network egress. That's covered by Operator-Hand
fixture-mode refreshes (Section 3 below).

## 3. Operator-Hand fixture-mode refresh

On a host with cosign + crane + Sigstore-network egress (NOT the
sandbox-CI runner per `feedback_sandbox_host_trennung.md`), an
operator captures a live snapshot and feeds it into the probe.

### 3.1 Capture the Trust-Root snapshot

```bash
# Pull the current cosign-installer SemVer-major from the workflow.
COSIGN_ACTION=$(grep -h 'sigstore/cosign-installer' \
    .github/workflows/cosign-verify-images.yml | head -n1 \
    | sed -E 's/.*(sigstore\/cosign-installer@v[0-9]+).*/\1/')
SEMVER_MAJOR=$(echo "$COSIGN_ACTION" | sed -E 's/.*@(v[0-9]+)/\1/')

# Pull the Fulcio root CA from the live trust-root.
FULCIO_SHA=$(cosign initialize 2>&1 > /dev/null \
    && find ~/.sigstore -name 'fulcio_v1*.pem' \
    | head -n1 | xargs sha256sum | awk '{print $1}')

# Pull the Rekor shard ID.
REKOR_SHARD=$(curl -fsSL https://rekor.sigstore.dev/api/v1/log \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["treeID"])')

cat > /tmp/snapshot.json <<EOF
{
  "snapshot_ts": $(date +%s),
  "trust_root": {
    "cosign_installer_action": "${COSIGN_ACTION}",
    "cosign_installer_semver_major": "${SEMVER_MAJOR}",
    "fulcio_root_ca_sha256": "${FULCIO_SHA}",
    "rekor_log_shard_id": "${REKOR_SHARD}"
  },
  "per_binary_oidc": [
    // ... one entry per binary; see step 3.2.
  ]
}
EOF
```

### 3.2 Capture per-binary OIDC identities

For each of the 15 binaries in the Tag-45 inventory, cosign-verify
against the carrier image and extract the identity from the
keyless cert:

```bash
for name in recovery state-backing fsm v907-verify bridge-diff \
            subscribe-loop anchor-emitter svid-workload-identity \
            bridge-audit-writer state-backing-welle4 fsm-welle5 \
            subscribe-loop-welle6 recovery-welle7 \
            bridge-audit-replay migrate-version; do
    cosign verify \
        --certificate-identity-regexp \
            'https://github\.com/wakir-labs/wakir-runtime/' \
        --certificate-oidc-issuer \
            'https://token.actions.githubusercontent.com' \
        --output-file "/tmp/verify-${name}.json" \
        ghcr.io/wakir-labs/wakir-persona-engine:0.5.0-pilot
    # Extract the identity URL from the cert.
    # ...
done
```

### 3.3 Run the probe in fixture mode

```bash
python3 scripts/observability/cosign-keyless-oidc-drift-probe.py \
    --policy policies/cosign-policy-phase-3b.yaml \
    --pinned-trust-root state/cosign-drift/pinned-trust-root.json \
    --repo-root . \
    --mode fixture \
    --snapshot /tmp/snapshot.json \
    --exit-non-zero-on-drift
```

Exit code 0 = aggregate GREEN. Exit code 2 = drift detected;
review the Markdown summary for the per-binary verdict + reason.

## 4. Pinned-trust-root refresh

When the Sigstore project re-tags the cosign-installer or rotates
the Fulcio CA, an Operator-Hand PR updates
`state/cosign-drift/pinned-trust-root.json` with the new values.
Zone-C cross-review by Tomás is required (Container-Image-Pipeline
x OTS-Anchoring).

The PR should:

  1. Update the four fields (`cosign_installer_action`,
     `cosign_installer_semver_major`, `fulcio_root_ca_sha256`,
     `rekor_log_shard_id`).
  2. Update the `pinned_at` date and `pinned_by` byline.
  3. Add a short note in the `notes` field explaining the upstream
     event that triggered the refresh (e.g. "Sigstore re-tagged
     cosign-installer to v4 on 2026-MM-DD").

After merge, the daily baseline-mode probe automatically picks up
the new values; the next Operator-Hand fixture-mode run will
verify the upstream chain matches.

## 5. Halt-on-drift recipe

If the probe emits a non-GREEN aggregate verdict:

  1. **Do NOT roll out new images** until the drift is reconciled.
  2. Review the Markdown summary's per-binary table for the
     specific drift reason.
  3. For `DRIFT-TRUST-ROOT`: check the Sigstore project's release
     announcements; the upstream re-tag may be benign (SemVer-minor
     rollover) or may be a security-relevant rotation. Refresh the
     pinned-trust-root JSON per Section 4 if benign; halt + escalate
     if security-relevant.
  4. For `DRIFT-OIDC-IDENTITY`: check the Sigstore Rekor
     transparency log for the binary's signing event; verify the
     OIDC subject claim matches a known build-workflow URL. If the
     identity URL is unfamiliar, the carrier image may have been
     signed by an unauthorised workflow run — halt + escalate to
     Tomás (Zone-C) + Mira.
  5. For `DRIFT-CERTIFICATE-ISSUER`: the OIDC issuer URL changed.
     The canonical issuer is
     `https://token.actions.githubusercontent.com`. A different
     issuer = the signing event did not come from GitHub-Actions.
     Halt + escalate.
  6. For `DRIFT-WORKFLOW-PATH`: the policy points at a build_workflow
     file that no longer exists on disk. Substrate-side bug; fix
     in a Zone-C cross-reviewed PR.

## 6. Anchors

  * Tag-45 PR #294 — Quadlet+Cosign 15-Binary substrate refresh.
  * Tag-46 PR #298 — A6 substrate-layer coverage matrix.
  * `feedback_sandbox_host_trennung.md` — no sandbox cosign egress.
  * `docs/operations/cosign-policy-phase-3b.md` — sibling living
    operator reference for the policy substrate.
