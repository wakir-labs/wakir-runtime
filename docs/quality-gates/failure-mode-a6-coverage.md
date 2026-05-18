# Quality-Gate — Failure-Mode A6 Cosign-Verification-Drift Coverage Matrix

| Field | Value |
|---|---|
| Owner | Kai Hoffmann (DevOps / Container-Image-Pipeline), with Zone-C cross-review by Tomás Reinhart |
| Status | Tag-46 closeout — A6 PARTIAL -> COVERED |
| Phase | 3 (closing): substrate-layer A6 coverage extension |
| Source | Amara Tag-45 Pre-Mortem Coverage-Audit PR #293 (`docs/quality-gates/pre-mortem-failure-mode-coverage.md` §2 A6, Tag-46+ follow-up table row 2); Kai Tag-46 spawn 2026-05-18 |
| Date | 2026-05-18 (creation, Tag-46 A6-coverage spawn) |
| Test-File | `tests/infra/test_cosign_drift_coverage_a6.py` (17 hermetic invariants — 15 parametric + 5 standalone) |
| Companion (CI-workflow shape) | `tests/ci/test_build_wakir_provisioner_workflow.py` (`test_cosign_login_step_present`, `test_cosign_login_runs_before_sign`) |
| Companion (policy-substrate shape) | `tests/infra/test_cosign_policy_phase_3b.py` (Tag-23..Tag-45 inventory invariants) |
| Companion (Quadlet-installer shape) | `tests/infra/test_tag45_quadlet_cosign_15_binary_substrate.py` (Tag-45 13->15 closeout) |
| Companion (planned Marathon-Layer-5) | `tests/phase_3c/test_cosign_chain_marathon_image_hash_stability.py` (Amara owner, Tag-46+ follow-up table row 2) |

## 0. Contract scope

This document is the **substrate-layer coverage matrix** for
failure-mode **A6 — Cosign-Verification-Drift (Image-Re-Bake
mid-Marathon)** as classified in Amara's Tag-45 Pre-Mortem
Coverage-Audit (`pre-mortem-failure-mode-coverage.md` §2 A6).

The Tag-45 audit classified A6 as **PARTIAL** with two pinning tests
(both CI-workflow-shape: `test_cosign_login_step_present`,
`test_cosign_login_runs_before_sign`). The Tag-46+ follow-up table
named two closers:

  * `test_cosign_chain_marathon_image_hash_stability.py` — Layer-5
    Phase-3c-marathon-level closer, **Amara owner with Kai cross-review**.
  * `tests/infra/test_cosign_drift_coverage_a6.py` (this file) —
    Layer-3 substrate-layer closer, **Kai owner with Zone-C
    cross-review**.

The substrate-layer closer fires the A6 PARTIAL -> COVERED transition
in the Tag-45 coverage matrix. The Layer-5 marathon-level closer
(Amara, separate spawn) extends the COVERED classification across
the Welle-N -> Welle-N+1 image-hash-stability invariant during the
KW-24..KW-27 marathon.

## 1. The 20 test-vectors

The 17-invariant test file is organised into 20 logical test-vectors
(15 parametric runs of TV-A6-01..15 + 5 standalone invariants
TV-A6-16..20).

### Per-binary cosign-drift detection (TV-A6-01 .. TV-A6-15)

`test_a6_per_binary_cosign_drift_invariant` runs once per binary
in the 15-binary Tag-45-closeout inventory. Each run asserts the
policy entry carries the four substrate slots that an A6 re-bake
would silently corrupt (`component`, `crate_path`, `in_image_path`,
`env_switch`) AND that `in_image_path` is rooted under
`/opt/wakir/bin/` so the Operator-Hand
`step_3_in_image_binary_probe` shell-loop can enumerate it as a
drift target.

| TV | Binary | Source-Tag |
|---|---|---|
| TV-A6-01 | recovery | Tag-17 Mini-Welle PR #167 |
| TV-A6-02 | state-backing | Tag-17 Mini-Welle PR #167 |
| TV-A6-03 | fsm | Tag-18 Mini-Welle PR #169 |
| TV-A6-04 | v907-verify | Tag-19 Mini-Welle PR #171 |
| TV-A6-05 | bridge-diff | Tag-20 Mini-Welle PR #175 |
| TV-A6-06 | subscribe-loop | Tag-22 Mini-Welle PR #181 |
| TV-A6-07 | anchor-emitter | Tag-23 Mini-Welle PR #184 |
| TV-A6-08 | svid-workload-identity | Tag-25/Tag-29 PR #191 + Welle-2 image-build |
| TV-A6-09 | bridge-audit-writer | Tag-31 Mini-Welle (Welle-3 image-build) |
| TV-A6-10 | state-backing-welle4 | Tag-33 Mini-Welle (Welle-4 cutover image) |
| TV-A6-11 | fsm-welle5 | Tag-33 Mini-Welle (Welle-5 cutover image) |
| TV-A6-12 | subscribe-loop-welle6 | Tag-33 Mini-Welle (Welle-6 cutover image) |
| TV-A6-13 | recovery-welle7 | Tag-33 Mini-Welle (Welle-7 cutover image) |
| TV-A6-14 | bridge-audit-replay | Tag-37/Tag-45 PR #246 (14. Phase-3a Modul) |
| TV-A6-15 | migrate-version | Tag-38/Tag-45 PR #250 (15. Phase-3a Modul; sweep closeout) |

### Standalone invariants (TV-A6-16 .. TV-A6-20)

| TV | Invariant | Test | Failure-mode angle |
|---|---|---|---|
| TV-A6-16 | Image-digest-mismatch recovery posture | `test_a6_image_digest_mismatch_recovery_posture` | Halt-on-drift recipe + non-zero exit |
| TV-A6-17 | Cosign verification-timeout / installer pin | `test_a6_cosign_installer_semver_pin` | SemVer pin against silent installer rollover |
| TV-A6-18 | Keyless-OIDC-identity drift detection | `test_a6_keyless_oidc_identity_drift_detection` | Anti-wildcard-org-drift + canonical issuer |
| TV-A6-19 | Sigstore-trust-root-update-race posture | `test_a6_sigstore_trust_root_posture` | Sigstore-maintained action, anti-fork |
| TV-A6-20 | Coverage-classification consistency | `test_a6_coverage_classification_covered` + `test_a6_coverage_matrix_doc_exists_and_named` | Pre-Mortem matrix doc in sync with substrate |

## 2. A6 PARTIAL -> COVERED transition

The Tag-45 PARTIAL classification was based on two CI-workflow-shape
tests that verified the cosign-login step exists and runs before the
sign step. That coverage is necessary but not sufficient: it pins
the workflow shape, not the substrate slots that an A6 image-re-bake
would silently corrupt.

The Tag-46 closeout adds 17 substrate-layer invariants (15 parametric
per-binary + 5 standalone) that pin:

  * **Per-binary substrate integrity** (TV-A6-01..15) — the 15-binary
    inventory matches the Tag-45 Quadlet+Cosign closeout byte-for-byte,
    and each binary's drift-anchor slots are present and well-formed.
  * **Recovery automation** (TV-A6-16) — the cosign-verify-images.yml
    workflow exits non-zero on digest drift, AND the policy ships the
    halt-recipe paragraph.
  * **Installer pin discipline** (TV-A6-17) — the cosign-installer
    action is SemVer-major-pinned (no floating tags).
  * **OIDC identity discipline** (TV-A6-18) — the
    `certificate_identity_regexp` anchors `wakir-labs/wakir-runtime`
    (no wildcard widening), AND the issuer is the canonical
    GitHub-Actions OIDC URL (no Fulcio-mirror drift).
  * **Trust-root discipline** (TV-A6-19) — the cosign-installer is the
    Sigstore-maintained action, not a third-party fork.
  * **Matrix consistency** (TV-A6-20) — the Pre-Mortem coverage doc
    §2 A6 is updated to COVERED and lists this test file as the
    pinning anchor.

Together with the two Tag-45 CI-workflow-shape tests and the
planned Layer-5 marathon-level test, A6 has three-fold coverage:

  * **Layer-1 (CI-workflow shape)**: cosign-login step present + runs
    before sign (Tag-45, in
    `tests/ci/test_build_wakir_provisioner_workflow.py`).
  * **Layer-3 (substrate)**: per-binary drift-anchor slots +
    recovery posture + installer pin + OIDC identity + trust-root
    discipline (Tag-46, this file).
  * **Layer-5 (marathon)**: Welle-N image-hash MUST equal Welle-N+1
    image-hash for the same image — pending Amara spawn (Tag-46+
    follow-up table row 2).

The Tag-46 substrate-layer closer is sufficient for the A6 PARTIAL
-> COVERED transition at the Pre-Mortem coverage matrix level. The
Layer-5 marathon-level test is an additional defence-in-depth pin
that extends COVERED across the cutover sequence.

## 3. Out-of-scope (sandbox boundary)

Per `feedback_sandbox_host_trennung.md` + ADR-0051, the test surface
reads files on disk only. NO sandbox process calls cosign, crane,
skopeo, or podman against `ghcr.io`. The following live-verification
events remain Operator-Hand:

  * `cosign verify ghcr.io/wakir-labs/wakir-persona-engine:<tag>@<digest>`
    — Operator-Hand per
    `docs/operations/cosign-policy-phase-3b.md` §3.
  * `crane digest ghcr.io/wakir-labs/wakir-persona-engine:<tag>`
    cross-resolve — same recipe.
  * Sigstore Rekor transparency-log entry inspection on a
    digest-mismatch event — Operator-Hand Zone-C cross-review.

The hermetic test surface pins the substrate; the live verification
is the operator's responsibility per the on-mismatch recipe in the
policy YAML.

## 4. Coverage summary

| Failure-mode | Pre-Tag-46 | Tag-46 (this file) | Post-Tag-46 |
|---|---|---|---|
| A6 — Cosign-Verification-Drift | PARTIAL (2 CI-shape tests) | +17 substrate invariants | COVERED |

## 5. Cross-review note (Zone C)

Zone C is the Container-Image-Pipeline x Tomás-OTS-Anchoring
cross-review boundary (per `agents-workspaces/kai/CLAUDE.md` §2).
The A6 substrate-layer extension touches the cosign-policy YAML
that the same `wakir-persona-engine` image is verified against —
the image Tomás's
`quadlet/wakir-persona-tomas.container` already pins. The Tag-46
extension does NOT change the image-build path, the digest-resolver
workflow (`resolve-image-pins-ci.yml`), or the OTS-anchoring
pipeline. It only adds 17 substrate-layer assertions on the
existing policy YAML + verify workflow.

The Tag-45 Quadlet+Cosign substrate refresh (PR #294) already had
Zone-C cross-review by Tomás (commit message anchor). The Tag-46
substrate-layer test extension is a follow-on within the same
Zone-C cross-review surface; no new Zone-C gate triggered.

— Kai
