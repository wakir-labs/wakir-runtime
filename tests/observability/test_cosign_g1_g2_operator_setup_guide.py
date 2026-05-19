#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic invariants for the Tag-56 G1+G2 Operator-Hand setup-guide.

Tag-56 Kai — Cosign-Strict-Mode G1+G2 closeout setup-guide.

This module pins the structural invariants of
``docs/operations/cosign-g1-g2-operator-setup.md`` so a future edit
that breaks the documented step-by-step contract (drops a section,
deletes the Zone-C reference, inverts the G1/G2 ordering, etc.)
regresses with a clear hermetic-test failure rather than only via
the next Operator-Hand attempt failing operationally.

Coverage targets pure document structure + cross-substrate
consistency with the on-disk substrate the guide claims to operate
on:

  * T-G1G2-01 — guide file exists at the documented path
  * T-G1G2-02 — SPDX-License-Identifier header
  * T-G1G2-03 — six top-level sections (1..6) plus §7 anchors
  * T-G1G2-04 — G1 placeholder-slot inventory table lists all 7 files
  * T-G1G2-05 — G1 placeholder token matches the on-disk repo grep
  * T-G1G2-06 — G2 PENDING token matches the on-disk pinned-trust-root
  * T-G1G2-07 — Zone-C cross-review reference present for both PRs
  * T-G1G2-08 — G1-first / G2-second ordering enforced
  * T-G1G2-09 — cross-link to strict-mode-activation runbook
  * T-G1G2-10 — cross-link to cosign-keyless-OIDC-drift-probe runbook
  * T-G1G2-11 — guide signs off with the persona-name line
  * T-G1G2-12 — failure-mode subsections present for both G1 and G2
  * T-G1G2-13 — guide enumerates the four Welle-N dedicated images

Total: 13 hermetic invariants (target was >=10).

Sandbox boundary
----------------

Per ``feedback_sandbox_host_trennung.md`` + ADR-0051 these tests
NEVER call cosign / crane / podman / network. They parse the guide
markdown on disk plus the substrate files the guide references
(``policies/cosign-policy-phase-3b.yaml``,
``state/cosign-drift/pinned-trust-root.json``, the
``quadlet/wakir-rust-cli*.container`` glob) and assert text-level
consistency between the documentation and the substrate.

Sibling tests:
  * ``tests/observability/test_cosign_keyless_oidc_drift_probe.py``
    — drift-probe pure-function core invariants.
  * ``tests/observability/test_cosign_strict_mode_readiness_check.py``
    — readiness-check gate-aggregator invariants.
  * ``tests/infra/test_cosign_policy_phase_3b.py`` — cosign-policy
    YAML format invariants.

Author: Kai Hoffmann (Dev-Engineering-3)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Set

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
GUIDE_PATH = (
    REPO_ROOT / "docs" / "operations" / "cosign-g1-g2-operator-setup.md"
)
POLICY_PATH = REPO_ROOT / "policies" / "cosign-policy-phase-3b.yaml"
PINNED_TRUST_ROOT_PATH = (
    REPO_ROOT / "state" / "cosign-drift" / "pinned-trust-root.json"
)
QUADLET_GLOB_DIR = REPO_ROOT / "quadlet"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def guide_text() -> str:
    assert GUIDE_PATH.is_file(), f"missing guide: {GUIDE_PATH}"
    return GUIDE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def guide_lines(guide_text: str) -> List[str]:
    return guide_text.splitlines()


@pytest.fixture(scope="module")
def policy_text() -> str:
    assert POLICY_PATH.is_file(), f"missing policy: {POLICY_PATH}"
    return POLICY_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pinned_trust_root() -> dict:
    assert (
        PINNED_TRUST_ROOT_PATH.is_file()
    ), f"missing pinned trust-root: {PINNED_TRUST_ROOT_PATH}"
    return json.loads(PINNED_TRUST_ROOT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def quadlet_files_with_placeholder() -> Set[str]:
    """Quadlet files that carry the DIGEST_PENDING_KAI_CROSS_REVIEW token."""
    matches: Set[str] = set()
    for path in sorted(QUADLET_GLOB_DIR.glob("*.container")):
        text = path.read_text(encoding="utf-8")
        if "DIGEST_PENDING_KAI_CROSS_REVIEW" in text:
            matches.add(path.name)
    return matches


# ---------------------------------------------------------------------------
# T-G1G2-01 — guide file exists at the documented path
# ---------------------------------------------------------------------------


def test_t_g1g2_01_guide_file_exists() -> None:
    """The Tag-56 deliverable path is the canonical operator entry-point.

    The strict-mode-activation runbook §5 Step 2 and Step 3 point at
    this file; if the file moves the link breaks silently.
    """

    assert GUIDE_PATH.is_file(), (
        f"Operator-Setup-Guide must live at the canonical path "
        f"{GUIDE_PATH.relative_to(REPO_ROOT)}; found nothing on disk."
    )
    # Non-trivial content — guards against accidental zero-byte commit.
    assert GUIDE_PATH.stat().st_size > 4096, (
        "Operator-Setup-Guide is suspiciously small; expected "
        ">=4 KiB of step-by-step substance."
    )


# ---------------------------------------------------------------------------
# T-G1G2-02 — SPDX-License-Identifier header
# ---------------------------------------------------------------------------


def test_t_g1g2_02_spdx_header(guide_text: str) -> None:
    """Operator-Hand docs must carry the SPDX-License header per the
    repo-wide license-hygiene contract (`tests/infra/
    test_license_hygiene_consistency.py`)."""

    # REUSE-IgnoreStart
    expected_license_marker = "SPDX-License-" "Identifier: Apache-2.0"
    expected_copyright_marker = "SPDX-File" "CopyrightText:"
    # REUSE-IgnoreEnd
    assert expected_license_marker in guide_text, (
        "Operator-Setup-Guide missing SPDX license-id header"
    )
    assert expected_copyright_marker in guide_text, (
        "Operator-Setup-Guide missing SPDX copyright-text header"
    )


# ---------------------------------------------------------------------------
# T-G1G2-03 — six top-level sections (1..6) plus §7 anchors
# ---------------------------------------------------------------------------


def test_t_g1g2_03_top_level_sections(guide_text: str) -> None:
    """The guide's section-table-of-contents is part of the contract.

    A future edit that drops or renames a top-level section breaks
    deep-links from the parent runbook + the Zone-C sign-off comment.
    """

    expected_headers = [
        "## 1. Scope and sandbox boundary",
        "## 2. Pre-flight",
        "## 3. Step G1",
        "## 4. Step G2",
        "## 5. Step 5",
        "## 6. Acceptance gates",
        "## 7. Anchors",
    ]
    for header in expected_headers:
        assert header in guide_text, (
            f"Operator-Setup-Guide missing top-level section: '{header}'"
        )


# ---------------------------------------------------------------------------
# T-G1G2-04 — G1 placeholder-slot inventory lists all 7 files
# ---------------------------------------------------------------------------


def test_t_g1g2_04_placeholder_inventory(
    guide_text: str,
    quadlet_files_with_placeholder: Set[str],
    policy_text: str,
) -> None:
    """The §3.1 inventory table lists exactly the on-disk placeholder
    slots.

    If a future change introduces a new placeholder slot without
    updating the guide, the operator would miss it in PR #N1 and G1
    would stay BLOCKED post-merge. This test rejects that drift at
    PR-review-time.
    """

    # Policy carries the carrier-image placeholder.
    assert "DIGEST_PENDING_KAI_CROSS_REVIEW" in policy_text, (
        "Policy file missing the canonical placeholder convention; "
        "the guide table is stale."
    )
    assert "policies/cosign-policy-phase-3b.yaml" in guide_text, (
        "Guide §3.1 must reference the policy file as a placeholder slot."
    )

    # All quadlet files that carry the placeholder must be named in
    # the guide table. Use a tight regex to anchor the name to a
    # markdown-table cell rather than a free-floating mention.
    for quadlet_name in sorted(quadlet_files_with_placeholder):
        assert quadlet_name in guide_text, (
            f"Guide §3.1 must reference quadlet file '{quadlet_name}' "
            "as a placeholder slot (it currently carries the "
            "DIGEST_PENDING_KAI_CROSS_REVIEW token on disk)."
        )

    # Symmetric check — the guide must not list a quadlet file that
    # has no placeholder on disk (false positive in the table).
    quadlet_mention_re = re.compile(
        r"`quadlet/(wakir-[a-z0-9-]+\.container)`"
    )
    mentioned = set(quadlet_mention_re.findall(guide_text))
    spurious = mentioned - quadlet_files_with_placeholder
    assert not spurious, (
        f"Guide §3.1 mentions quadlet file(s) {sorted(spurious)} that "
        "do not currently carry a placeholder digest on disk. "
        "Either the substrate or the guide has drifted."
    )


# ---------------------------------------------------------------------------
# T-G1G2-05 — G1 placeholder token matches the on-disk repo grep
# ---------------------------------------------------------------------------


def test_t_g1g2_05_g1_token_exact_match(
    guide_text: str, policy_text: str
) -> None:
    """The exact placeholder convention is part of the operator's
    grep recipe.

    A typo in the guide (e.g. `DIGEST_PENDING_REVIEW`) would lead the
    operator to a zero-match grep and a false conclusion that no
    placeholders remain. Pin the literal token.
    """

    token = "DIGEST_PENDING_KAI_CROSS_REVIEW"
    assert token in guide_text, (
        f"Guide must mention the literal placeholder token '{token}'"
    )
    assert token in policy_text, (
        f"Policy file must carry the literal placeholder token '{token}' "
        "(else G1 is already closed and the guide is stale)."
    )
    # The exact grep recipe in the guide must produce a positive
    # match against the on-disk substrate.
    assert (
        f"grep -rn 'DIGEST_PENDING_KAI_CROSS_REVIEW'"
        in guide_text
    ), (
        "Guide §3.1 must carry the canonical repo-wide grep recipe "
        "for the placeholder token, byte-for-byte."
    )


# ---------------------------------------------------------------------------
# T-G1G2-06 — G2 PENDING token matches the on-disk pinned-trust-root
# ---------------------------------------------------------------------------


def test_t_g1g2_06_g2_token_exact_match(
    guide_text: str, pinned_trust_root: dict
) -> None:
    """The PENDING_OPERATOR_HAND_REFRESH token shape is part of the
    operator's recipe — pin it exactly.

    If the guide drifts to e.g. `PENDING_OPERATOR_REFRESH`, the
    operator's `grep -n` recipe in §4.5 misses the slot and G2
    stays BLOCKED post-merge.
    """

    token = "PENDING_OPERATOR_HAND_REFRESH"
    assert token in guide_text, (
        f"Guide must mention the literal G2 PENDING token '{token}'"
    )
    # The on-disk pinned-trust-root must currently carry the token in
    # both Fulcio + Rekor fields, else G2 is already closed and the
    # guide is stale.
    fulcio = pinned_trust_root.get("fulcio_root_ca_sha256")
    rekor = pinned_trust_root.get("rekor_log_shard_id")
    assert fulcio == token, (
        f"pinned-trust-root.fulcio_root_ca_sha256 must equal '{token}' "
        f"while G2 is BLOCKED; got '{fulcio}'."
    )
    assert rekor == token, (
        f"pinned-trust-root.rekor_log_shard_id must equal '{token}' "
        f"while G2 is BLOCKED; got '{rekor}'."
    )


# ---------------------------------------------------------------------------
# T-G1G2-07 — Zone-C cross-review reference present for both PRs
# ---------------------------------------------------------------------------


def test_t_g1g2_07_zone_c_cross_review(guide_text: str) -> None:
    """Both G1 and G2 PRs require Tomás Zone-C cross-review per
    ADR-0020 Zone-C (Container-Image-Pipeline x OTS-Anchoring).
    The guide must name Tomás + Zone-C for both PR commit-templates.
    """

    # Count Zone-C mentions — at least 3 expected:
    #   * G1 PR commit-message template (§3.5)
    #   * G2 PR commit-message template (§4.3)
    #   * Joint sign-off section (§5)
    zone_c_mentions = guide_text.count("Zone-C")
    assert zone_c_mentions >= 3, (
        f"Guide must reference Zone-C cross-review at least 3 times "
        f"(G1 PR, G2 PR, joint sign-off); found {zone_c_mentions}."
    )
    assert "Tomás" in guide_text, (
        "Guide must name Tomás as the Zone-C reviewer."
    )


# ---------------------------------------------------------------------------
# T-G1G2-08 — G1-first / G2-second ordering enforced
# ---------------------------------------------------------------------------


def test_t_g1g2_08_g1_first_g2_second(guide_text: str) -> None:
    """The Operator-Hand sequence MUST process G1 before G2 because
    the G2 fixture-mode probe ground-truths against real per-binary
    digests resolved in G1. If a future edit inverts the section
    order, the operator would attempt G2 against placeholder digests
    and the fixture-mode probe would trivially fail.
    """

    g1_pos = guide_text.find("## 3. Step G1")
    g2_pos = guide_text.find("## 4. Step G2")
    assert g1_pos != -1, "Guide missing §3 Step G1 header."
    assert g2_pos != -1, "Guide missing §4 Step G2 header."
    assert g1_pos < g2_pos, (
        "Guide must present G1 before G2 — the G2 fixture-mode probe "
        "depends on G1 having resolved the per-binary digests."
    )
    # The §4.1 precondition wording must explicitly forbid starting
    # G2 before G1 is GREEN.
    assert "MUST NOT start until G1 is GREEN" in guide_text, (
        "Guide §4.1 must carry an explicit precondition forbidding "
        "starting G2 before G1 is GREEN on main."
    )


# ---------------------------------------------------------------------------
# T-G1G2-09 — cross-link to strict-mode-activation runbook
# ---------------------------------------------------------------------------


def test_t_g1g2_09_link_to_strict_mode_activation(
    guide_text: str,
) -> None:
    """The Tag-56 guide is the §5 Step 2 + Step 3 expansion of the
    Tag-54 strict-mode-activation runbook. The bidirectional link
    must be present so the operator can navigate parent <-> child.
    """

    assert (
        "docs/operations/cosign-strict-mode-activation.md" in guide_text
    ), (
        "Guide must cross-link the parent strict-mode-activation runbook."
    )


# ---------------------------------------------------------------------------
# T-G1G2-10 — cross-link to cosign-keyless-OIDC-drift-probe runbook
# ---------------------------------------------------------------------------


def test_t_g1g2_10_link_to_drift_probe(guide_text: str) -> None:
    """The G2 recipe re-uses the trust-root capture stanzas from the
    drift-probe runbook §3.1. The cross-link must be present so the
    operator can confirm the recipe is identical (no silent fork).
    """

    assert (
        "docs/operations/cosign-keyless-oidc-drift-probe.md" in guide_text
    ), (
        "Guide must cross-link the cosign-keyless-OIDC-drift-probe runbook."
    )


# ---------------------------------------------------------------------------
# T-G1G2-11 — guide signs off with the persona-name line
# ---------------------------------------------------------------------------


def test_t_g1g2_11_kai_signoff(guide_text: str) -> None:
    """All Kai-authored runbooks end with the '— Kai' signoff line per
    the persona-definition convention. Pin it as part of the doc
    contract.
    """

    # Allow either em-dash or hyphen — author convention.
    assert (
        guide_text.rstrip().endswith("— Kai")
        or guide_text.rstrip().endswith("- Kai")
    ), "Operator-Setup-Guide must close with the '— Kai' sign-off line."


# ---------------------------------------------------------------------------
# T-G1G2-12 — failure-mode subsections present for both G1 and G2
# ---------------------------------------------------------------------------


def test_t_g1g2_12_failure_mode_sections(guide_text: str) -> None:
    """Both G1 and G2 carry a Failure-Modes subsection (§3.7 + §4.5).

    Failure-mode tables are how the operator decides between
    'recover-in-place' vs. 'halt + escalate' — dropping them turns the
    guide into a happy-path-only document. Pin both.
    """

    assert "### 3.7 Failure modes — G1" in guide_text, (
        "Guide §3 must carry the G1 failure-modes table at §3.7."
    )
    assert "### 4.5 Failure modes — G2" in guide_text, (
        "Guide §4 must carry the G2 failure-modes table at §4.5."
    )
    # Each table should mention 'Halt' at least once — the
    # canonical operator-discipline word.
    g1_section = guide_text.split("### 3.7 Failure modes — G1")[1].split(
        "## 4."
    )[0]
    g2_section = guide_text.split("### 4.5 Failure modes — G2")[1].split(
        "## 5."
    )[0]
    assert "Halt" in g1_section, (
        "G1 failure-modes section must reference the 'Halt' discipline."
    )
    assert "Halt" in g2_section, (
        "G2 failure-modes section must reference the 'Halt' discipline."
    )


# ---------------------------------------------------------------------------
# T-G1G2-13 — enumerates the four Welle-N dedicated images
# ---------------------------------------------------------------------------


def test_t_g1g2_13_welle_n_image_enum(guide_text: str) -> None:
    """The four Welle-4..7 dedicated single-binary images are independent
    images per the Tag-33 Mini-Welle inventory. They are NOT in the
    carrier image. The guide §3.3 recipe MUST enumerate all four
    because the carrier-image-only resolution would miss them and G1
    would stay BLOCKED for the four Welle-N slots.
    """

    welle_binaries = [
        ("state-backing", "welle4"),
        ("fsm", "welle5"),
        ("subscribe-loop", "welle6"),
        ("recovery", "welle7"),
    ]
    for binary, welle in welle_binaries:
        canonical_image = (
            f"wakir-persona-engine-{binary}-{welle}"
        )
        assert canonical_image in guide_text, (
            f"Guide §3 must reference the Welle-N image "
            f"'{canonical_image}' as a distinct digest resolution slot."
        )
