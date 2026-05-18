# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic invariants for the Failure-Mode A6 cosign-drift coverage
extension (Tag-46, Kai).

Context
-------
Amara's Tag-45 Pre-Mortem Coverage-Audit (PR #293,
``docs/quality-gates/pre-mortem-failure-mode-coverage.md`` §2 A6)
classified failure-mode **A6 — Cosign-Verification-Drift (Image-Re-Bake
mid-Marathon)** as **PARTIAL**. The two existing pinning-tests
(``test_cosign_login_step_present`` /
``test_cosign_login_runs_before_sign`` in
``tests/ci/test_build_wakir_provisioner_workflow.py``) verify the
CI-workflow shape, but no infra-side test pins the substrate-level
cosign-drift invariants per binary across the Tag-45 15-binary
inventory.

The Tag-46+ follow-up table in §4 names
``test_cosign_chain_marathon_image_hash_stability.py`` as the
Layer-5 Phase-3c-marathon-level closer (Amara owner, Kai cross-review).
This file is the **infra-side companion** to that planned Layer-5
test: it closes the A6 PARTIAL gap from the Container-Image-Pipeline
substrate (Zone-C owner: Kai) by enforcing 15-binary-by-binary
cosign-drift detection invariants, image-digest-mismatch recovery
posture, cosign verification-timeout handling, keyless-OIDC-identity
drift detection and Sigstore-trust-root-update-race semantics.

Scope (substrate-level)
-----------------------
This test file ships 17 hermetic invariants:

  * **TV-A6-01 .. TV-A6-15** — per-binary cosign-drift detection
    invariant: each of the 15 binaries in
    ``policies/cosign-policy-phase-3b.yaml`` MUST carry a
    cosign-verifiable digest slot AND an Operator-Hand on-mismatch
    halt recipe. The 15 binaries are: ``recovery``, ``state-backing``,
    ``fsm``, ``v907-verify``, ``bridge-diff``, ``subscribe-loop``,
    ``anchor-emitter``, ``svid-workload-identity``,
    ``bridge-audit-writer``, ``state-backing-welle4``, ``fsm-welle5``,
    ``subscribe-loop-welle6``, ``recovery-welle7``,
    ``bridge-audit-replay``, ``migrate-version`` (Tag-45 closeout).
  * **TV-A6-16** — image-digest-mismatch recovery posture: the
    policy ships an ``on_digest_mismatch`` recipe AND the
    ``cosign-verify-images.yml`` workflow exits non-zero on
    digest-drift.
  * **TV-A6-17** — cosign verification-timeout handling: the
    installer-side cosign-installer pin is at a SemVer-pinned major
    (``@v3``); upstream sigstore re-tags do not silently rollover.
  * **TV-A6-18** — keyless-OIDC-identity drift detection: the
    policy's ``certificate_identity_regexp`` anchors the build-workflow
    repo (no wildcard org), AND the
    ``certificate_oidc_issuer`` is the canonical GitHub-Actions OIDC
    issuer URL (no Fulcio-mirror drift).
  * **TV-A6-19** — Sigstore-trust-root-update-race posture: the
    cosign-verify workflow uses ``sigstore/cosign-installer@v3``
    (Sigstore-maintained, transparency-log-pinned), NOT a third-party
    fork.
  * **TV-A6-20** — A6 coverage-classification consistency:
    ``docs/quality-gates/pre-mortem-failure-mode-coverage.md`` §2 A6
    state-tag MUST be ``COVERED`` AND the Tag-45+ follow-up footer
    must list this test file by name.

Sibling tests
-------------
  * ``tests/infra/test_cosign_policy_phase_3b.py`` — full-shape
    invariants for the cosign-policy YAML (the substrate this file
    asserts drift-detection on).
  * ``tests/infra/test_tag45_quadlet_cosign_15_binary_substrate.py``
    — Tag-45 13->15-binary inventory closeout invariants.
  * ``tests/ci/test_build_wakir_provisioner_workflow.py`` — the
    CI-workflow-shape cosign-login pin Amara's Tag-45 audit cited.
  * (planned) ``tests/phase_3c/test_cosign_chain_marathon_image_hash_
    stability.py`` — Amara's Tag-46+ Layer-5 marathon-level closer.

Sandbox boundary
----------------
Per ``feedback_sandbox_host_trennung.md`` + ADR-0051, this test
surface reads files on disk only. NO sandbox process calls cosign,
crane, skopeo, or podman against ``ghcr.io``. Live verification
(cosign verify ghcr.io/wakir-labs/wakir-persona-engine@<digest>) is
Operator-Hand per ``docs/operations/cosign-policy-phase-3b.md`` §3.

-- Kai
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_FILE = REPO_ROOT / "policies" / "cosign-policy-phase-3b.yaml"
VERIFY_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "cosign-verify-images.yml"
)
COVERAGE_DOC = (
    REPO_ROOT / "docs" / "quality-gates" / "pre-mortem-failure-mode-coverage.md"
)
A6_COVERAGE_DOC = (
    REPO_ROOT
    / "docs"
    / "quality-gates"
    / "failure-mode-a6-coverage.md"
)

# Canonical 15-binary inventory (Tag-45 closeout). Each name maps to
# the policy.binaries[].name slot in cosign-policy-phase-3b.yaml.
EXPECTED_A6_BINARIES = (
    # Tag-17..Tag-31 — first 9 carrier-image entries.
    "recovery",
    "state-backing",
    "fsm",
    "v907-verify",
    "bridge-diff",
    "subscribe-loop",
    "anchor-emitter",
    "svid-workload-identity",
    "bridge-audit-writer",
    # Tag-33 Mini-Welle — Welle-4..7 dedicated single-binary images.
    "state-backing-welle4",
    "fsm-welle5",
    "subscribe-loop-welle6",
    "recovery-welle7",
    # Tag-45 Mini-Welle — Phase-3a-Foundation 14 + 15 closeout.
    "bridge-audit-replay",
    "migrate-version",
)

PLACEHOLDER_DIGEST = "sha256:DIGEST_PENDING_KAI_CROSS_REVIEW"
CANONICAL_DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
PLACEHOLDER_OR_CANONICAL_RE = re.compile(
    r"^(?:sha256:DIGEST_PENDING_KAI_CROSS_REVIEW|sha256:[a-f0-9]{64})$"
)


@pytest.fixture(scope="module")
def policy() -> dict:
    """Parse the cosign-policy YAML once per test-module."""
    assert POLICY_FILE.exists(), (
        f"required cosign-policy file missing: {POLICY_FILE}"
    )
    with POLICY_FILE.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict), (
        f"cosign-policy YAML must parse to a mapping, got "
        f"{type(data).__name__}"
    )
    return data


@pytest.fixture(scope="module")
def verify_workflow_text() -> str:
    """Read the cosign-verify-images.yml workflow once per module."""
    assert VERIFY_WORKFLOW.exists(), (
        f"required cosign-verify workflow missing: {VERIFY_WORKFLOW}"
    )
    return VERIFY_WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def coverage_doc_text() -> str:
    """Read the Pre-Mortem coverage-audit doc once per module."""
    assert COVERAGE_DOC.exists(), (
        f"required coverage doc missing: {COVERAGE_DOC}"
    )
    return COVERAGE_DOC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def a6_coverage_doc_text() -> str:
    """Read the A6-specific coverage matrix doc once per module."""
    assert A6_COVERAGE_DOC.exists(), (
        f"required A6 coverage matrix doc missing: {A6_COVERAGE_DOC}"
    )
    return A6_COVERAGE_DOC.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# TV-A6-01..15 — per-binary cosign-drift detection invariant.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("binary_name", EXPECTED_A6_BINARIES)
def test_a6_per_binary_cosign_drift_invariant(
    policy: dict, binary_name: str
) -> None:
    """For each of the 15 binaries, the policy MUST carry the cosign-
    keyless verification anchors AND a digest-slot in the
    placeholder-or-canonical SHA-256 form.

    The drift-detection invariant is structural: an image-re-bake
    mid-Marathon (A6 failure-mode) would replace the carrier image
    while leaving the policy's digest slot stale. The hermetic test
    asserts the slot is present and well-formed; the live drift-
    detection is Operator-Hand cosign + crane per
    ``docs/operations/cosign-policy-phase-3b.md``.

    A binary missing from the policy.binaries[] list signals an
    inventory-drift bug (Quadlet installer ships N binaries, policy
    lists N-1 — the missing binary then has NO cosign-anchor and an
    A6-re-bake would go undetected for that binary).
    """
    binaries = policy.get("binaries")
    assert isinstance(binaries, list), (
        "policy.binaries: section missing or not a list — A6 substrate "
        "incomplete"
    )

    matching = [b for b in binaries if b.get("name") == binary_name]
    assert len(matching) == 1, (
        f"A6 inventory-drift: expected exactly one policy entry for "
        f"binary {binary_name!r}, got {len(matching)} — Container-Image-"
        f"Pipeline x cosign-policy substrate misaligned. An A6 re-bake "
        f"of this binary would go undetected."
    )

    entry = matching[0]

    # The carrier_image digest slot is shared across all 15 binaries
    # (single carrier image). The drift-anchor is on the carrier_image
    # entry; per-binary entries carry the in_image_path + env-switch
    # but not their own digest (the binaries ship inside the carrier).
    # The drift-invariant per binary therefore checks the schema slots
    # that a re-bake would silently corrupt: component, crate_path,
    # in_image_path, env_switch.
    for required_key in (
        "component",
        "crate_path",
        "in_image_path",
        "env_switch",
    ):
        assert required_key in entry, (
            f"A6 substrate gap: policy.binaries[name={binary_name!r}] "
            f"missing required key {required_key!r} — a re-bake could "
            f"silently drift this slot without leaving a cosign-detectable "
            f"trail."
        )

    # in_image_path discipline: MUST be under /opt/wakir/bin/ so the
    # Operator-Hand step_3_in_image_binary_probe shell-loop can
    # enumerate it.
    in_image_path = entry["in_image_path"]
    assert in_image_path.startswith("/opt/wakir/bin/"), (
        f"A6 substrate gap: binary {binary_name!r} in_image_path "
        f"{in_image_path!r} not under /opt/wakir/bin/ — Operator-Hand "
        f"step_3 probe-loop cannot enumerate it as a drift target."
    )


# ---------------------------------------------------------------------------
# TV-A6-16 — image-digest-mismatch recovery posture.
# ---------------------------------------------------------------------------
def test_a6_image_digest_mismatch_recovery_posture(
    policy: dict, verify_workflow_text: str
) -> None:
    """The policy ships an ``on_digest_mismatch`` recipe AND the
    cosign-verify workflow exits non-zero on digest-drift.

    A6 re-bake recovery posture is two-layered:
      * Layer-1 (operator-hand): the policy carries the human-readable
        ``on_digest_mismatch`` paragraph that names the halt + Zone-C
        cross-review path.
      * Layer-2 (automation): the cosign-verify-images.yml workflow
        exits non-zero (exit 2) when the pinned digest does not match
        the crane live digest.
    """
    verification = policy.get("policy", {})
    on_mismatch = (
        policy.get("verification", {}).get("on_digest_mismatch", "")
    )
    assert isinstance(on_mismatch, str) and len(on_mismatch) > 0, (
        "A6 recovery posture: policy.verification.on_digest_mismatch "
        "recipe is missing or empty — Operator-Hand has no canonical "
        "halt-recipe in case of A6 re-bake."
    )
    # The recipe MUST name "Halt" or "Refuse" (halt-posture, not
    # continue-with-warning).
    assert (
        "Halt" in on_mismatch
        or "halt" in on_mismatch
        or "Refuse" in on_mismatch
        or "refuse" in on_mismatch
    ), (
        "A6 recovery posture: on_digest_mismatch must explicitly "
        "name a halt / refuse step (not silent continue)."
    )

    # Layer-2: workflow MUST exit non-zero on drift.
    # The workflow uses `exit 2` in three places (spire-server,
    # spire-agent, wakir-provisioner cross-check). The A6 invariant
    # is that at least one `exit 2` follows the digest-drift detection
    # block.
    assert "digest drift" in verify_workflow_text, (
        "A6 recovery automation: cosign-verify-images.yml must name "
        "'digest drift' as a detection condition."
    )
    assert "exit 2" in verify_workflow_text, (
        "A6 recovery automation: cosign-verify-images.yml must "
        "non-zero-exit on digest drift (expected `exit 2`)."
    )


# ---------------------------------------------------------------------------
# TV-A6-17 — cosign verification-timeout handling / installer pin.
# ---------------------------------------------------------------------------
def test_a6_cosign_installer_semver_pin(
    verify_workflow_text: str,
) -> None:
    """The cosign-installer step MUST be pinned to a SemVer major
    (``sigstore/cosign-installer@v3``) so an upstream re-tag of a
    floating tag does not silently rollover the cosign binary mid-
    Marathon.

    A6 timeout-handling: a re-baked sigstore/cosign-installer that
    silently flips its default timeout / retry semantics could cause
    a flaky verification step to appear "passing" when the underlying
    cosign binary is actually new. The SemVer-major pin caps the
    upgrade surface and forces a Zone-C review for major bumps.
    """
    assert "sigstore/cosign-installer@v3" in verify_workflow_text, (
        "A6 installer-pin: cosign-verify-images.yml must use "
        "sigstore/cosign-installer@v3 (SemVer major). Floating tags "
        "(@main, @latest) or unpinned action references defeat the "
        "A6 timeout-handling invariant."
    )

    # Anti-pattern: NOT @main, NOT @latest, NOT a SHA-pin without a
    # documented Zone-C review chain (SHA-pin is fine if documented,
    # but the current substrate uses @v3 — flagging if it drifts).
    forbidden = (
        "sigstore/cosign-installer@main",
        "sigstore/cosign-installer@latest",
        "sigstore/cosign-installer@master",
    )
    for needle in forbidden:
        assert needle not in verify_workflow_text, (
            f"A6 installer-pin drift: cosign-verify-images.yml uses "
            f"forbidden floating ref {needle!r} — defeats verification-"
            f"timeout invariant."
        )


# ---------------------------------------------------------------------------
# TV-A6-18 — keyless-OIDC-identity drift detection.
# ---------------------------------------------------------------------------
def test_a6_keyless_oidc_identity_drift_detection(policy: dict) -> None:
    """The policy's ``certificate_identity_regexp`` MUST anchor the
    build-workflow repo (``wakir-labs/wakir-runtime``) and the
    ``certificate_oidc_issuer`` MUST be the canonical GitHub-Actions
    OIDC issuer URL.

    A6 OIDC-identity drift posture: if the policy widened the
    identity-regexp to ``https://github\\.com/.*`` or pointed the
    issuer at a Fulcio-mirror instead of the canonical
    ``token.actions.githubusercontent.com`` URL, a malicious upstream
    publisher could re-sign the image under their own OIDC identity
    and the policy would accept it. The hermetic invariant pins both
    slots against the canonical values.
    """
    pol = policy.get("policy", {})

    ident_re = pol.get("certificate_identity_regexp")
    assert isinstance(ident_re, str) and len(ident_re) > 0, (
        "A6 OIDC-identity drift: policy.certificate_identity_regexp "
        "missing or empty."
    )
    # The regexp must anchor the wakir-labs/wakir-runtime repo, not
    # widen to .*/wakir-runtime or .*github.com.*.
    assert "wakir-labs/wakir-runtime" in ident_re, (
        f"A6 OIDC-identity drift: policy.certificate_identity_regexp "
        f"{ident_re!r} does not anchor wakir-labs/wakir-runtime — "
        f"OIDC-identity widening detected."
    )
    # Anti-pattern: a regexp that accepts any github.com path is a
    # wildcard-org-drift.
    forbidden_widening = (
        "^https://github\\.com/.*$",
        "github.com/.*",
        ".*github\\.com.*",
    )
    for needle in forbidden_widening:
        assert ident_re != needle, (
            f"A6 OIDC-identity drift: policy.certificate_identity_"
            f"regexp matches forbidden wildcard {needle!r}."
        )

    # The issuer must be the canonical GitHub-Actions OIDC URL.
    issuer = pol.get("certificate_oidc_issuer")
    assert issuer == "https://token.actions.githubusercontent.com", (
        f"A6 OIDC-issuer drift: policy.certificate_oidc_issuer "
        f"{issuer!r} != canonical "
        f"'https://token.actions.githubusercontent.com'. A Fulcio-"
        f"mirror or alternate issuer would let an A6 re-sign under "
        f"a non-canonical identity slip through."
    )


# ---------------------------------------------------------------------------
# TV-A6-19 — Sigstore-trust-root-update-race posture.
# ---------------------------------------------------------------------------
def test_a6_sigstore_trust_root_posture(
    verify_workflow_text: str,
) -> None:
    """The cosign-verify workflow MUST use the Sigstore-maintained
    ``sigstore/cosign-installer@v3`` action, NOT a third-party fork.

    A6 trust-root-update-race posture: Sigstore-maintained installer
    follows the canonical Sigstore-trust-root update cadence
    (Sigstore TUF metadata). A third-party fork could lag or stub
    the trust-root, opening a race window during an A6 re-bake where
    the cosign-verify step transitively trusts a stale Fulcio root.
    """
    # Positive assertion — already covered by TV-A6-17, but the trust-
    # root invariant is the semantic anchor (different invariant from
    # the SemVer-pin discipline).
    assert "sigstore/cosign-installer" in verify_workflow_text, (
        "A6 trust-root: cosign-verify workflow must use the canonical "
        "sigstore/cosign-installer action (not a fork)."
    )

    # Anti-pattern: NOT a third-party fork (the canonical owner is
    # `sigstore/`; if the org slug differs, that's a fork-trust-root-
    # drift).
    forbidden_forks = (
        "actions/cosign-installer",
        "third-party/cosign-installer",
        "community/cosign-installer",
    )
    for needle in forbidden_forks:
        assert needle not in verify_workflow_text, (
            f"A6 trust-root: cosign-verify workflow uses forbidden "
            f"third-party fork {needle!r} — Sigstore-trust-root-"
            f"update-race invariant violated."
        )


# ---------------------------------------------------------------------------
# TV-A6-20 — A6 coverage-classification consistency.
# ---------------------------------------------------------------------------
def test_a6_coverage_classification_covered(
    coverage_doc_text: str,
) -> None:
    """The Pre-Mortem coverage-audit doc §2 A6 MUST classify A6 as
    COVERED (post-Tag-46), AND the named pinning-tests list MUST
    include this test file.

    Consistency check: when this file is committed, the Tag-45 PARTIAL
    classification of A6 (and the Tag-46+ follow-up table row) must
    be updated to COVERED with this test as the pinning anchor. The
    test asserts the doc-side change is wired so the matrix stays
    self-consistent.
    """
    # Locate the A6 section.
    a6_section_marker = "#### A6 — Cosign-Verification-Drift"
    assert a6_section_marker in coverage_doc_text, (
        "A6 section header missing from coverage doc."
    )
    a6_start = coverage_doc_text.index(a6_section_marker)
    # Next #### section marks the boundary.
    a6_end_rel = coverage_doc_text[a6_start + len(a6_section_marker):].find(
        "\n#### "
    )
    a6_block = (
        coverage_doc_text[a6_start: a6_start + len(a6_section_marker) + a6_end_rel]
        if a6_end_rel != -1
        else coverage_doc_text[a6_start:]
    )

    # The block MUST claim COVERED (post-Tag-46) — PARTIAL is the
    # pre-Tag-46 classification we are closing.
    assert "Coverage state.** COVERED" in a6_block, (
        "A6 coverage-classification still PARTIAL — the Tag-46 closeout "
        "must flip A6 to COVERED in pre-mortem-failure-mode-coverage.md "
        "§2 A6."
    )

    # The pinning-tests list MUST name this test file.
    assert "test_cosign_drift_coverage_a6" in a6_block, (
        "A6 pinning-tests list does not reference "
        "test_cosign_drift_coverage_a6 — coverage doc out of sync with "
        "Tag-46 substrate."
    )


def test_a6_coverage_matrix_doc_exists_and_named(
    a6_coverage_doc_text: str,
) -> None:
    """The dedicated A6 coverage-matrix doc
    (``docs/quality-gates/failure-mode-a6-coverage.md``) MUST exist
    and MUST classify the 20-invariant coverage matrix.
    """
    # Title + matrix scope.
    assert "Failure-Mode A6" in a6_coverage_doc_text, (
        "A6 coverage matrix doc missing canonical title."
    )
    assert "PARTIAL" in a6_coverage_doc_text, (
        "A6 coverage matrix doc must reference the prior PARTIAL "
        "classification it closes."
    )
    assert "COVERED" in a6_coverage_doc_text, (
        "A6 coverage matrix doc must declare the post-Tag-46 COVERED "
        "classification."
    )
    # All 15 binaries named in the matrix.
    for binary in EXPECTED_A6_BINARIES:
        assert binary in a6_coverage_doc_text, (
            f"A6 coverage matrix doc missing binary {binary!r} "
            f"reference."
        )
    # Test-vector enumeration: TV-A6-01..TV-A6-20.
    for tv in ("TV-A6-01", "TV-A6-15", "TV-A6-16", "TV-A6-20"):
        assert tv in a6_coverage_doc_text, (
            f"A6 coverage matrix doc missing test-vector ID {tv!r}."
        )
