<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# Cosign-Strict-Mode G1+G2 Operator-Hand Setup-Guide

Tag-56 deliverable (Kai). Companion to
`docs/operations/cosign-strict-mode-activation.md` §5 Step 2 + Step 3
and `docs/operations/cosign-keyless-oidc-drift-probe.md` §3 + §4.

Tag-55 PR #357 reduced the strict-flip readiness gates from
6 BLOCKED to 2 BLOCKED — G3+G5 flipped GREEN, G4+G6 stayed GREEN,
**G1 + G2 remain BLOCKED because both require host-side egress that
the sandbox-CI runner does not have** (per
`feedback_sandbox_host_trennung.md`).

This guide is the operational step-by-step the operator-host follows
to close G1 (placeholder-digest resolution against real production
digests) and G2 (trust-root pin against the live Sigstore trust-root)
in two strictly-ordered Operator-Hand PRs.

---

## 1. Scope and sandbox boundary

| What | In-scope | Out-of-scope |
|---|---|---|
| Host-host with `ghcr.io` push + Sigstore-network egress | Yes — Operator-Hand only | No — sandbox-CI runner |
| Live `cosign` + `crane` + `skopeo` against `ghcr.io` | Yes | No — `feedback_sandbox_host_trennung.md` |
| YAML / JSON edits against `policies/` and `state/cosign-drift/` | Yes — both substrate edits land here | n/a |
| PR review by Tomás (Zone-C) | Required for both G1 and G2 PRs | n/a |
| ADR vorlage | Not required — this is procedural closeout, not architecture | n/a |

The two BLOCKED gates close in **two separate Operator-Hand PRs**
(PR #N1 for G1, PR #N2 for G2). They MUST land in order
(G1 first, then G2) because the G2 fixture-mode probe verifies the
G1 digest is real before the trust-root axis can be ground-truthed
against a live snapshot.

---

## 2. Pre-flight — verify Tag-55 baseline still holds

Before starting either PR, the operator confirms the post-Tag-55
substrate is intact. Run the readiness check on the current `main`:

```bash
gh workflow run cosign-strict-mode-readiness-check \
    -R wakir-labs/wakir-runtime
```

Expected verdict:

| Gate | Expected verdict | Source |
|---|---|---|
| G1 | BLOCKED (15 placeholders) | `policies/cosign-policy-phase-3b.yaml` carrier-image + 14 per-binary placeholder slots |
| G2 | BLOCKED (both PENDING) | `state/cosign-drift/pinned-trust-root.json` — `fulcio_root_ca_sha256` + `rekor_log_shard_id` |
| G3 | GREEN | `state/cosign-drift/last-probe-envelope.json` baseline-mode envelope |
| G4 | GREEN | 15-binary inventory size |
| G5 | GREEN | quadlet glob-union ↔ policy parity |
| G6 | GREEN | branch-protection display-names |

If G1, G2 status diverges from BLOCKED, **STOP** — the substrate has
drifted since Tag-55. Open a triage ticket; do not start either
Operator-Hand PR until the drift is reconciled.

If G3, G4, G5 or G6 has flipped to non-GREEN, **STOP** — a parallel
substrate change has invalidated the Tag-55 baseline. Re-run the
Tag-55 closeout artefact production before proceeding (see Step 1
of `cosign-strict-mode-activation.md`).

---

## 3. Step G1 — placeholder-digest resolution

### 3.1 Inventory the placeholders

The placeholder convention is `sha256:DIGEST_PENDING_KAI_CROSS_REVIEW`
(literal string, never a fake hex). The full inventory of placeholder
slots that must be replaced in PR #N1:

| File | Slot count | Image |
|---|---|---|
| `policies/cosign-policy-phase-3b.yaml` (carrier-image) | 1 | `ghcr.io/wakir-labs/wakir-persona-engine:0.5.0-pilot` |
| `quadlet/wakir-rust-cli.container` | 1 | same carrier image (Welle-1..3 install path) |
| `quadlet/wakir-persona-tomas.container` | 1 | `ghcr.io/wakir-labs/wakir-persona-engine:0.1.0-pilot` (Pilot-Persona) |
| `quadlet/wakir-rust-cli-welle4.container` | 1 | `ghcr.io/wakir-labs/wakir-persona-engine-state-backing-welle4:0.5.0-pilot` |
| `quadlet/wakir-rust-cli-welle5.container` | 1 | `ghcr.io/wakir-labs/wakir-persona-engine-fsm-welle5:0.5.0-pilot` |
| `quadlet/wakir-rust-cli-welle6.container` | 1 | `ghcr.io/wakir-labs/wakir-persona-engine-subscribe-loop-welle6:0.5.0-pilot` |
| `quadlet/wakir-rust-cli-welle7.container` | 1 | `ghcr.io/wakir-labs/wakir-persona-engine-recovery-welle7:0.5.0-pilot` |

The exact placeholder text is the literal string
`DIGEST_PENDING_KAI_CROSS_REVIEW` (no `sha256:` prefix when grep'd, but
ALWAYS preceded by `sha256:` in the file). A repository-wide grep gives
the canonical list:

```bash
grep -rn 'DIGEST_PENDING_KAI_CROSS_REVIEW' \
    policies/ quadlet/
```

The output count must match the table above. If the count diverges,
**STOP** — a new placeholder slot has been introduced since Tag-55
and this guide is stale. Update the inventory table in PR #N1 to
match the on-disk reality before continuing.

### 3.2 Resolve the carrier-image digest

On the operator-host (with `ghcr.io` egress + `crane` installed):

```bash
# Carrier image (0.5.0-pilot). The :0.5.0-pilot tag must resolve to
# the production-signed manifest. Tag-mutation discipline: the
# operator commits the digest the carrier-build workflow produced,
# NOT the tag.
crane digest ghcr.io/wakir-labs/wakir-persona-engine:0.5.0-pilot
# Output: sha256:[hex64] (64-char lowercase hex)
```

Verify the digest format byte-for-byte: 64 lowercase hex chars,
no `sha256:` doubled. Reject anything else as a malformed digest
output.

### 3.3 Resolve the per-Welle dedicated-image digests

The four Welle-4..7 dedicated single-binary images are independent
images per the Tag-33 Mini-Welle (they are NOT in the carrier image
— see `docs/operations/cosign-strict-mode-activation.md` Step 2a
rationale for Resolution-B).

```bash
for welle in 4:state-backing 5:fsm 6:subscribe-loop 7:recovery; do
    n=${welle%%:*}; bin=${welle##*:}
    crane digest \
        "ghcr.io/wakir-labs/wakir-persona-engine-${bin}-welle${n}:0.5.0-pilot"
done
```

Capture all four digests. Reject any output that is not a 64-char
lowercase hex string.

### 3.4 Resolve the Pilot-Persona image digest

```bash
crane digest ghcr.io/wakir-labs/wakir-persona-engine:0.1.0-pilot
```

The 0.1.0-pilot tag is the Tomás-Pilot-Persona carrier; this is a
distinct manifest from the 0.5.0-pilot carrier. Confirm the digest
output is the production-pilot digest, NOT the development-default
tag — cross-check against the Pilot-Persona image-build workflow
run-id in the carrier-build workflow run history.

### 3.5 Apply the replacements

Open PR #N1 against `wakir-runtime` with a single atomic commit that
replaces all 7 placeholder slots. The PR diff should touch exactly
the 7 files in §3.1 and nothing else. The commit message follows
the form:

```text
ops(cosign-strict-G1): resolve carrier+Welle-N+Pilot digests

Closes G1 of the Cosign-Strict-Mode readiness gates. Replaces
the DIGEST_PENDING_KAI_CROSS_REVIEW placeholder convention with
the real ghcr.io production digests resolved via crane on the
operator-host.

Cross-Review-Zone-C: Tomás (Container-Image-Pipeline x OTS-Anchoring).
```

### 3.6 Verify PR #N1 against the readiness-check

After PR #N1 merges into `main`:

```bash
gh workflow run cosign-strict-mode-readiness-check \
    -R wakir-labs/wakir-runtime
```

Confirm G1 flips from BLOCKED to GREEN. If G1 stays BLOCKED, the
operator returns to §3.1 — at least one placeholder slot was missed
in the replacement.

### 3.7 Failure modes — G1

| Failure | Diagnosis | Recovery |
|---|---|---|
| `crane digest` returns 404 | Image tag not pushed | Halt — the build pipeline is the bug, not the digest pin. Open a build-pipeline triage ticket; do not invent a digest. |
| `crane digest` returns a non-64-char string | Malformed digest output | Halt — re-pull `crane` from upstream, do not commit a malformed digest. |
| readiness-check shows G1 still BLOCKED post-merge | Missed placeholder slot | Re-run `grep -rn 'DIGEST_PENDING_KAI_CROSS_REVIEW' policies/ quadlet/` and patch the missed slot in a follow-up PR. |
| Tomás (Zone-C) rejects PR #N1 | Cross-review surfaced a digest-resolution discrepancy | Halt the merge; reconcile per Tomás's review comments before re-attempting. |

---

## 4. Step G2 — pinned-trust-root refresh

### 4.1 Pre-condition — G1 GREEN on `main`

Step G2 MUST NOT start until G1 is GREEN on `main` because the
fixture-mode probe (which validates the G2 trust-root pin against
a live Sigstore snapshot) requires real per-binary digests to
cross-check the OIDC identities. Starting G2 first means the
fixture-mode probe trivially fails on the placeholder digests.

Verify the precondition:

```bash
gh workflow run cosign-strict-mode-readiness-check \
    -R wakir-labs/wakir-runtime
# Confirm G1 verdict = GREEN, G2 verdict = BLOCKED in the run artefact.
```

If G1 is not GREEN, **STOP** — return to §3.

### 4.2 Capture the live trust-root snapshot

The recipe is the same as
`docs/operations/cosign-keyless-oidc-drift-probe.md` §3.1, repeated
here for self-containment.

```bash
# Pull the current cosign-installer SemVer-major from the workflow.
COSIGN_ACTION=$(grep -h 'sigstore/cosign-installer' \
    .github/workflows/cosign-verify-images.yml | head -n1 \
    | sed -E 's/.*(sigstore\/cosign-installer@v[0-9]+).*/\1/')
SEMVER_MAJOR=$(echo "$COSIGN_ACTION" | sed -E 's/.*@(v[0-9]+)/\1/')

# Pull the Fulcio root CA SHA-256 from the live trust-root.
FULCIO_SHA=$(cosign initialize 2>&1 > /dev/null \
    && find ~/.sigstore -name 'fulcio_v1*.pem' \
    | head -n1 | xargs sha256sum | awk '{print $1}')

# Pull the Rekor shard ID via the public Rekor API.
REKOR_SHARD=$(curl -fsSL https://rekor.sigstore.dev/api/v1/log \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["treeID"])')

# Sanity-check shapes before writing them anywhere.
echo "FULCIO_SHA=${FULCIO_SHA}"   # 64-char lowercase hex
echo "REKOR_SHARD=${REKOR_SHARD}" # numeric tree-id (integer string)
```

The two captured values must satisfy:

* `FULCIO_SHA` is a 64-char lowercase hex string (sha256sum output
  shape).
* `REKOR_SHARD` is a numeric string (Rekor tree-id, currently a
  large integer).

Reject any other shape — the trust-root pin would itself be
malformed and would falsely red the next probe run.

### 4.3 Apply the replacements

Open PR #N2 against `wakir-runtime` with a single atomic commit that
replaces the two `PENDING_OPERATOR_HAND_REFRESH` values in
`state/cosign-drift/pinned-trust-root.json`. The PR diff should
touch exactly one file. The four substrate fields after the edit:

| Field | Source | Shape |
|---|---|---|
| `cosign_installer_action` | grep on `cosign-verify-images.yml` | `sigstore/cosign-installer@vN` |
| `cosign_installer_semver_major` | sed-derived | `vN` |
| `fulcio_root_ca_sha256` | `sha256sum` of the live Fulcio CA PEM | 64-char lowercase hex |
| `rekor_log_shard_id` | `curl rekor.sigstore.dev/api/v1/log` | numeric string |

The `pinned_at` field gets the operator-host's UTC date (ISO-8601
`YYYY-MM-DD`); the `pinned_by` field gets the operator's name +
the closeout reference (e.g. `"Kai Hoffmann (Tag-56 G2 closeout)"`).
The `notes` field gains a short paragraph explaining the live
snapshot source (e.g. `"Captured on operator-host 2026-MM-DD via
cosign initialize + Rekor API; cosign-installer pinned to vN."`).

The commit message follows the form:

```text
ops(cosign-strict-G2): pin Sigstore trust-root snapshot

Closes G2 of the Cosign-Strict-Mode readiness gates. Replaces the
two PENDING_OPERATOR_HAND_REFRESH values in pinned-trust-root.json
with the live Fulcio CA SHA-256 + Rekor shard ID captured on the
operator-host via cosign initialize + Rekor API.

Cross-Review-Zone-C: Tomás (Container-Image-Pipeline x OTS-Anchoring).
```

### 4.4 Verify PR #N2 against the readiness-check + fixture-mode probe

After PR #N2 merges into `main`:

```bash
# 1. Readiness check.
gh workflow run cosign-strict-mode-readiness-check \
    -R wakir-labs/wakir-runtime
# Expected: G2 BLOCKED -> GREEN.

# 2. Fixture-mode drift-probe (against the live snapshot).
gh workflow run cosign-keyless-oidc-drift-probe \
    -R wakir-labs/wakir-runtime \
    -f mode=fixture \
    -f exit_non_zero_on_drift=true
# Expected: aggregate_verdict = GREEN.
```

Both runs must be GREEN for G2 to count as truly closed.

### 4.5 Failure modes — G2

| Failure | Diagnosis | Recovery |
|---|---|---|
| `cosign initialize` cannot reach Sigstore | Operator-host network restriction | Halt — switch to a host with Sigstore-network egress; do not work around with cached PEMs. |
| Fulcio SHA-256 differs across two consecutive captures | Sigstore re-tagged Fulcio mid-capture | Halt — wait for the upstream Sigstore release announcement to clarify the rotation, then re-capture. |
| Rekor `treeID` is non-numeric | API contract change | Halt — open a Rekor-API-contract drift ticket; do not commit a non-numeric value. |
| readiness-check shows G2 still BLOCKED post-merge | At least one `PENDING_OPERATOR_HAND_REFRESH` slot still on disk | Re-run `grep -n 'PENDING_OPERATOR_HAND_REFRESH' state/cosign-drift/pinned-trust-root.json` and patch the missed field. |
| fixture-mode probe is non-GREEN despite G2 GREEN | Drift between the pinned values and a fresh snapshot taken at probe-time | Halt — reconcile per `docs/operations/cosign-keyless-oidc-drift-probe.md` §5 (halt-on-drift recipe). |
| Tomás (Zone-C) rejects PR #N2 | Cross-review surfaced a trust-root capture discrepancy | Halt the merge; reconcile per Tomás's review comments before re-attempting. |

---

## 5. Step 5 — Cross-Review-Zone-C sign-off (joint)

After both G1 and G2 are GREEN on `main`, Tomás reviews the
post-Step-4 readiness-check run and the post-Step-4 fixture-mode
probe run and leaves a single sign-off comment referencing this
document. The sign-off comment is the audit-trail entry for
both PRs combined; no separate ADR.

The sign-off comment lists:

  1. Baseline run-id pre-G1 (from §2 pre-flight).
  2. PR #N1 (G1 closeout) merge SHA.
  3. PR #N2 (G2 closeout) merge SHA.
  4. Post-G2 readiness-check run-id (must be 6/6 GREEN).
  5. Post-G2 fixture-mode probe run-id (must be aggregate GREEN).

Once Tomás's sign-off comment lands, the operator is cleared to
proceed to `cosign-strict-mode-activation.md` §5 Step 6 — the
S1+S2+S3 atomic strict-flip PR.

---

## 6. Acceptance gates for this guide

The guide itself is normatively contracted via the hermetic test
`tests/observability/test_cosign_g1_g2_operator_setup_guide.py`.
The tests pin the following invariants byte-for-byte:

| # | Invariant | Test |
|---|---|---|
| 1 | Guide file exists at the documented path | T-G1G2-01 |
| 2 | Guide carries the SPDX-License-Identifier header | T-G1G2-02 |
| 3 | Guide carries the six top-level sections (1..6) | T-G1G2-03 |
| 4 | G1 inventory table lists all 7 placeholder-slot files | T-G1G2-04 |
| 5 | G1 placeholder token matches the on-disk repo grep | T-G1G2-05 |
| 6 | G2 PENDING token matches the on-disk pinned-trust-root field | T-G1G2-06 |
| 7 | Guide references the Zone-C cross-review by Tomás for both PRs | T-G1G2-07 |
| 8 | Guide ordering enforces G1-first / G2-second sequence | T-G1G2-08 |
| 9 | Guide cross-links to the parent strict-mode-activation runbook | T-G1G2-09 |
| 10 | Guide cross-links to the cosign-keyless-OIDC-drift-probe runbook | T-G1G2-10 |
| 11 | Guide signs off with the persona-name line | T-G1G2-11 |

A future change that drops one of these invariants regresses the
hermetic test surface with a clear pointer at the failing line.

---

## 7. Anchors

  * Tag-54 PR #351 — readiness-check substrate baseline (4 BLOCKED).
  * Tag-55 PR #357 — G3 + G5 closeout (down to 2 BLOCKED).
  * Tag-56 (this guide) — G1 + G2 Operator-Hand step-by-step recipe.
  * `docs/operations/cosign-strict-mode-activation.md` — parent runbook §5 Step 2 + Step 3.
  * `docs/operations/cosign-keyless-oidc-drift-probe.md` — sibling recipe for trust-root capture.
  * `feedback_sandbox_host_trennung.md` — sandbox boundary; no Sigstore-network egress in CI.
  * `feedback_branch_protection_check_names.md` — branch-protection display-name discipline.
  * Cross-Review-Zone-C: Container-Image-Pipeline × Tomás-OTS-Anchoring (ADR-0020 Zone C).

— Kai
