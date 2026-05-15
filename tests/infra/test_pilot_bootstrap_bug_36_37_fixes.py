# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic tests for Sprint-10 Tag-7 Bug-36 + Bug-37 substance fixes
in ``infra/spire/federation/wakir-pilot-bootstrap.sh``.

Anlass — Live-VM-Acceptance against wakir-orbit 2026-05-15 ~20:10
CEST (Mira-Hand-Live-Run via AR-Approval after Kai-Subagent
classifier-block). Two new substance bugs surfaced post Bug-30..33-
validation:

* **Bug-36 — Resolver-skip-cosign-mode-Lücke für SPIRE-Images.**
  Sprint-10 Tag-5 Bug-33 fix narrowed the skip-cosign-mode resolver
  call to ``--provisioner-only``, leaving the three SPIRE/python
  ``@sha256:DIGEST_PENDING_TOMAS_REVIEW`` placeholders in place.
  SPIRE-server-federation + spire-agent-federation Quadlets refused
  to start with ``parsing reference "...DIGEST_PENDING_TOMAS_REVIEW":
  invalid reference format``. Fix: skip-cosign-mode now resolves ALL
  4 images via skopeo and calls the resolver with the full digest
  argv (no ``--provisioner-only``). The ``--provisioner-only``
  resolver flag stays in the resolver for ad-hoc Operator-Hand
  re-runs that only need to rotate the provisioner pin.

* **Bug-37 — SPIRE-Agent NodeAttestor join_token config-coherency
  drift in federation-mode.** Sprint-10 Tag-3 federation-mode-switch
  stripped the ``-joinToken WAKIR_JOIN_TOKEN_PLACEHOLDER`` arg from
  the agent Quadlet's ExecStart line in step-6j, but left the
  agent-config (spire-agent-<side>.conf) declaring ``NodeAttestor
  "join_token"`` as the attestor plugin. The Quadlet started
  without a token, the plugin rejected attestation with
  ``InvalidArgument: join token was not provided``, the agent
  restart-looped forever, and the workload-API socket never bound.
  Fix: federation-mode now runs the SAME token-generate + sed-
  inject path as single-org (step-6i is mode-agnostic; step-6j's
  federation-strip branch is removed). The agent-config + Quadlet
  stay coherent: both declare/wire join_token.

Sandbox boundary
----------------

Source-file inspection plus hermetic bash-subprocess exercise of the
bootstrap source through ``bash -c``. No podman, no systemctl, no
live VM — see ``feedback_sandbox_host_trennung.md``. The live-VM
acceptance lane is ``scripts/federation-live-vm-acceptance.sh``
(Operator-Hand on the Pilot-VM).

Test-Vector index
-----------------

Bug-36 resolver-mode (4 vectors):

* ``TV-BUG-36-01`` step-5 skip-cosign branch resolves ALL 4 image
  pins via skopeo (loop over the same image list as the cosign-
  branch).
* ``TV-BUG-36-02`` step-5 skip-cosign branch calls the resolver with
  the full ``--spire-server-digest`` / ``--spire-agent-digest`` /
  ``--python-digest`` / ``--wakir-provisioner-digest`` argv (no
  ``--provisioner-only``).
* ``TV-BUG-36-03`` step-5 skip-cosign branch falls back gracefully
  when the wakir-provisioner image is not yet published (provisioner
  pin is skipped, the three SPIRE/python pins still resolve).
* ``TV-BUG-36-04`` step-5 skip-cosign branch aborts hard when
  skopeo-inspect fails for one of the three mandatory images
  (spire-server, spire-agent, python). The misleading "tag-only"
  comment is replaced.

Bug-37 config-coherency (4 vectors):

* ``TV-BUG-37-01`` step-6i token-generate runs for BOTH single-org
  AND federation mode (no mode-gating on the token-generate path).
* ``TV-BUG-37-02`` step-6j NO LONGER sed-deletes the placeholder
  in federation-mode. The "stripped join-token placeholder" log-
  output is gone.
* ``TV-BUG-37-03`` The token-generate log message is mode-aware
  (mentions WAKIR_PILOT_MODE for diagnose).
* ``TV-BUG-37-04`` Bug-37 disagree-note is documented in the source
  (Mira's Bug-37 brief recommended Option A x509pop; Kai's Option B
  rationale is captured in-line for Reza-Zone-B-Cross-Review).

Config-coherency invariants (2 vectors):

* ``TV-BUG-37-COHERENT-01`` Both federation-agent configs (orbit +
  wakir) declare ``NodeAttestor "join_token"`` as the agent plugin.
* ``TV-BUG-37-COHERENT-02`` The federation-agent Quadlet template
  has ``-joinToken WAKIR_JOIN_TOKEN_PLACEHOLDER`` in the ExecStart
  line — the placeholder the bootstrap step-6i substitutes.

End-to-end shape test (1 vector):

* ``TV-BUG-37-E2E-01`` Step-6i + step-6j combined have a coherent
  control-flow: no ``WAKIR_PILOT_MODE == "single-org"`` gate around
  the token-generate, no ``WAKIR_PILOT_MODE == "federation"`` strip
  in step-6j.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_BOOTSTRAP = _REPO_ROOT / "infra" / "spire" / "federation" / "wakir-pilot-bootstrap.sh"
_AGENT_CONFIG_ORBIT = (
    _REPO_ROOT / "infra" / "spire" / "agent" / "config" / "spire-agent-orbit.conf"
)
_AGENT_CONFIG_WAKIR = (
    _REPO_ROOT / "infra" / "spire" / "agent" / "config" / "spire-agent-wakir.conf"
)
_AGENT_FED_QUADLET = (
    _REPO_ROOT
    / "infra"
    / "spire"
    / "agent"
    / "quadlet"
    / "wakir-spire-agent-federation.container"
)


@pytest.fixture(scope="module")
def bootstrap_source() -> str:
    assert _BOOTSTRAP.is_file(), f"bootstrap script not found: {_BOOTSTRAP}"
    return _BOOTSTRAP.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def agent_config_orbit() -> str:
    assert _AGENT_CONFIG_ORBIT.is_file(), (
        f"orbit agent config not found: {_AGENT_CONFIG_ORBIT}"
    )
    return _AGENT_CONFIG_ORBIT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def agent_config_wakir() -> str:
    assert _AGENT_CONFIG_WAKIR.is_file(), (
        f"wakir agent config not found: {_AGENT_CONFIG_WAKIR}"
    )
    return _AGENT_CONFIG_WAKIR.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def agent_fed_quadlet() -> str:
    assert _AGENT_FED_QUADLET.is_file(), (
        f"federation agent quadlet not found: {_AGENT_FED_QUADLET}"
    )
    return _AGENT_FED_QUADLET.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Helper: extract the step-5 skip-cosign branch precisely.
# ---------------------------------------------------------------------------


def _extract_step_5_skip_cosign_branch(source: str) -> str:
    """Extract the inner body of the ``if [[ "$WAKIR_SKIP_COSIGN_VERIFY"
    == "1" ]]; then`` block that lives INSIDE the
    ``step_5_image_pins()`` function. The bootstrap has TWO matching
    ``if`` headers — one in the pre-flight warning banner near line
    391, one in step-5 around line 767. We need the step-5 one.
    """
    step_5_start = source.find("step_5_image_pins()")
    assert step_5_start > 0, "step_5_image_pins() function not found"
    step_5_end = source.find("\n# ---", step_5_start + 10)
    if step_5_end < 0:
        step_5_end = source.find("step_6", step_5_start + 10)
    assert step_5_end > step_5_start, "step_5_image_pins() end not found"

    step_5_body = source[step_5_start:step_5_end]

    # Find the if-skip-cosign header inside step-5.
    if_idx = step_5_body.find(
        'if [[ "$WAKIR_SKIP_COSIGN_VERIFY" == "1" ]]; then'
    )
    assert if_idx > 0, "skip-cosign if-header not found in step-5"

    after_if = step_5_body[if_idx:]

    # Walk forward and find the closing ``fi`` at the SAME indentation
    # level as the ``if``. The if-header is indented with 2 spaces; the
    # closing fi at line-start with 2 spaces is its match.
    fi_match = re.search(r"^\s{2}fi\s*$", after_if, re.MULTILINE)
    assert fi_match, "skip-cosign closing fi not found in step-5"

    return after_if[: fi_match.start()]


# ---------------------------------------------------------------------------
# Bash syntax invariant.
# ---------------------------------------------------------------------------


def test_bootstrap_bash_syntax_clean() -> None:
    """The bootstrap script must parse cleanly with ``bash -n`` after
    the Bug-36 + Bug-37 fixes. A syntax error would have masked the
    real test failures below."""
    rc = subprocess.run(
        ["bash", "-n", str(_BOOTSTRAP)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert rc.returncode == 0, (
        f"bash -n failed: stderr={rc.stderr!r}"
    )


# ---------------------------------------------------------------------------
# TV-BUG-36-01: step-5 skip-cosign branch resolves ALL 4 image pins via
# skopeo.
# ---------------------------------------------------------------------------


def test_skip_cosign_resolves_all_four_images(bootstrap_source: str) -> None:
    """Sprint-10 Tag-7 Bug-36 fix: the skip-cosign branch enumerates
    the SAME four images as the cosign+skopeo cross-check branch."""
    branch = _extract_step_5_skip_cosign_branch(bootstrap_source)

    for image in (
        "ghcr.io/spiffe/spire-server:1.14.6",
        "ghcr.io/spiffe/spire-agent:1.14.6",
        "docker.io/library/python:3.13-slim",
        "ghcr.io/wakir-labs/wakir-provisioner:0.1.2",
    ):
        assert image in branch, (
            f"Bug-36 fix: skip-cosign branch must list {image} for "
            f"skopeo resolution; it is missing in the branch body."
        )


# ---------------------------------------------------------------------------
# TV-BUG-36-02: step-5 skip-cosign branch calls the resolver with the
# full digest argv (no --provisioner-only).
# ---------------------------------------------------------------------------


def test_skip_cosign_calls_resolver_with_full_argv(
    bootstrap_source: str,
) -> None:
    """The skip-cosign branch MUST pass --spire-server-digest +
    --spire-agent-digest + --python-digest. --provisioner-only stays
    in the resolver for ad-hoc rotations but is no longer used by the
    bootstrap step-5 skip-cosign branch."""
    branch = _extract_step_5_skip_cosign_branch(bootstrap_source)

    assert "--spire-server-digest" in branch, (
        "Bug-36 fix: skip-cosign branch must call the resolver with "
        "--spire-server-digest"
    )
    assert "--spire-agent-digest" in branch, (
        "Bug-36 fix: skip-cosign branch must call the resolver with "
        "--spire-agent-digest"
    )
    assert "--python-digest" in branch, (
        "Bug-36 fix: skip-cosign branch must call the resolver with "
        "--python-digest"
    )
    # --provisioner-only must NOT be in the skip-cosign branch
    # anymore. (It remains in the resolver script for ad-hoc
    # re-runs.)
    assert "--provisioner-only" not in branch, (
        "Bug-36 fix: --provisioner-only must NOT be in the bootstrap "
        "step-5 skip-cosign branch (Bug-33's narrow fix). Skip-cosign "
        "now runs the full skopeo-only resolve."
    )


# ---------------------------------------------------------------------------
# TV-BUG-36-03: provisioner-image-unavailable graceful fallback.
# ---------------------------------------------------------------------------


def test_skip_cosign_provisioner_optional_when_unpublished(
    bootstrap_source: str,
) -> None:
    """The wakir-provisioner image may not yet be published on first
    bring-up (Sprint-9 Tag-4 baseline). The skip-cosign branch must
    treat a provisioner skopeo-failure as non-fatal (log + continue)
    while still hard-failing on the three mandatory SPIRE/python
    images."""
    branch = _extract_step_5_skip_cosign_branch(bootstrap_source)

    # The provisioner-specific non-fatal branch:
    assert "wakir-provisioner" in branch, (
        "Bug-36 fix: skip-cosign branch must reference wakir-provisioner "
        "in the optional/skip fallback"
    )
    assert re.search(
        r"image may not be published yet", branch, re.IGNORECASE
    ), (
        "Bug-36 fix: skip-cosign branch must log a not-yet-published "
        "fallback for wakir-provisioner (Sprint-9 Tag-4 baseline parity)"
    )


# ---------------------------------------------------------------------------
# TV-BUG-36-04: skip-cosign hard-failure on mandatory image skopeo
# failure + misleading comment removed.
# ---------------------------------------------------------------------------


def test_skip_cosign_misleading_tag_only_comment_removed(
    bootstrap_source: str,
) -> None:
    """The prior step-5 skip-cosign branch carried the comment
    ``SPIRE + python images run with tag reference only`` which was
    factually wrong (the SPIRE/python Quadlets DO carry @sha256
    placeholders). The Bug-36 fix removes this misleading comment."""
    # The misleading comment must not appear as a code-comment NOR
    # in a log_warn banner anymore.
    assert (
        "SPIRE + python images run with tag reference only"
        not in bootstrap_source
    ), (
        "Bug-36 fix: the misleading 'tag reference only' comment must "
        "be removed from the bootstrap (it was factually wrong and "
        "masked Bug-36 for 2 sprints)"
    )


def test_skip_cosign_hard_fail_on_spire_skopeo_failure(
    bootstrap_source: str,
) -> None:
    """If skopeo-inspect fails for spire-server / spire-agent / python
    in skip-cosign-mode, the bootstrap MUST hard-fail (return 2) — the
    Quadlet cannot start without a real digest. Only wakir-provisioner
    is allowed to silently skip."""
    branch = _extract_step_5_skip_cosign_branch(bootstrap_source)

    # The hard-fail path must return 2 inside the loop for non-
    # provisioner images.
    assert re.search(
        r'skopeo inspect failed for \$\{image\} in skip-cosign-mode',
        branch,
    ), (
        "Bug-36 fix: skip-cosign branch must hard-fail with a clear "
        "diagnostic when skopeo-inspect fails for a mandatory image"
    )
    assert re.search(r"return 2", branch), (
        "Bug-36 fix: skip-cosign branch must return 2 on mandatory-image "
        "skopeo failure (bootstrap-step contract)"
    )


# ---------------------------------------------------------------------------
# TV-BUG-37-01: step-6i token-generate runs for BOTH modes (no mode gate).
# ---------------------------------------------------------------------------


def test_step_6i_token_generate_mode_agnostic(bootstrap_source: str) -> None:
    """Sprint-10 Tag-7 Bug-37 fix: step-6i token-generate must run for
    BOTH single-org AND federation mode. The prior single-org-only
    gate is removed.

    Invariant: the bootstrap source must NOT contain a single-org-
    only gate wrapping the agent-already-attested probe + token-
    generate call. The prior code shape was:

        if [[ "$WAKIR_PILOT_MODE" == "single-org" ]]; then
          local agent_quadlet_dst="${dst}/wakir-spire-agent-${side}.container"
          ...
          spire-server token generate
          ...
        fi

    We assert by searching for the single-org-gate-line FOLLOWED by
    the agent_quadlet_dst local declaration within a small window —
    that pattern existed in the pre-fix code and must be gone.
    """
    # Hard invariant: the literal single-org-mode-gate around the
    # token-generate code-block must be gone.
    pattern = re.compile(
        r'if\s+\[\[\s+"\$WAKIR_PILOT_MODE"\s*==\s*"single-org"\s*\]\];\s*then'
        r'\s*\n\s*local\s+agent_quadlet_dst',
        re.MULTILINE,
    )
    assert not pattern.search(bootstrap_source), (
        "Bug-37 fix: the single-org-only gate around the agent_quadlet_dst "
        "+ token-generate code-block must be removed (token-generate "
        "now runs for both modes)"
    )

    # Positive assertion: the agent_quadlet_dst local declaration must
    # exist OUTSIDE a single-org-gate (it is now part of the mode-
    # agnostic step-6i body).
    assert re.search(
        r'local\s+agent_quadlet_dst="\$\{dst\}/wakir-spire-agent-\$\{side\}\.container"',
        bootstrap_source,
    ), (
        "Bug-37 fix: the agent_quadlet_dst local must still exist (it "
        "is referenced by the now-mode-agnostic token-injection path)"
    )


# ---------------------------------------------------------------------------
# TV-BUG-37-02: step-6j federation-mode strip is removed.
# ---------------------------------------------------------------------------


def test_step_6j_no_federation_mode_strip(bootstrap_source: str) -> None:
    """Sprint-10 Tag-7 Bug-37 fix: step-6j must NOT sed-delete the
    ``-joinToken WAKIR_JOIN_TOKEN_PLACEHOLDER`` segment from the
    agent Quadlet ExecStart in federation-mode. The token is now
    injected by step-6i for BOTH modes."""
    # The literal sed-delete pattern from the prior federation-mode
    # branch must not appear anywhere in the bootstrap source.
    assert "sed -i 's| -joinToken WAKIR_JOIN_TOKEN_PLACEHOLDER||g'" not in (
        bootstrap_source
    ), (
        "Bug-37 fix: the federation-mode placeholder-strip sed-delete "
        "must be removed from step-6j"
    )
    # The "stripped join-token placeholder" log-message must also be
    # removed (it was the operator-visible symptom of the now-gone
    # codepath).
    assert "stripped join-token placeholder" not in bootstrap_source, (
        "Bug-37 fix: the 'stripped join-token placeholder' log message "
        "must be removed (its codepath is gone)"
    )


# ---------------------------------------------------------------------------
# TV-BUG-37-03: token-generate log-message is mode-aware.
# ---------------------------------------------------------------------------


def test_token_generate_log_is_mode_aware(bootstrap_source: str) -> None:
    """The Bug-37 fix makes step-6i mode-agnostic. The injection log-
    message must include WAKIR_PILOT_MODE for diagnose clarity (so an
    operator scanning the bootstrap-log can confirm federation-mode
    actually injected a token)."""
    # The log_ok line for token-injection must include
    # ``mode=${WAKIR_PILOT_MODE}`` or similar.
    assert re.search(
        r'log_ok "join-token issued.*mode=\$\{WAKIR_PILOT_MODE\}',
        bootstrap_source,
    ), (
        "Bug-37 fix: the token-injection log message must mention "
        "${WAKIR_PILOT_MODE} so federation-mode token-issuance is "
        "operator-visible"
    )


# ---------------------------------------------------------------------------
# TV-BUG-37-04: Disagree-note documented inline for Reza-Cross-Review.
# ---------------------------------------------------------------------------


def test_bug_37_disagree_note_documented(bootstrap_source: str) -> None:
    """Mira's Bug-37 brief recommended Option A (x509pop). Kai's
    Option B (mode-symmetric join-token) is the implemented fix.
    The disagree-note must be documented inline in the bootstrap
    source for Reza-Zone-B-Cross-Review."""
    # Mention of x509pop must exist with explicit rationale.
    assert "x509pop" in bootstrap_source, (
        "Bug-37 disagree-note: the x509pop alternative must be named "
        "in the source comment for Reza-Cross-Review context"
    )
    # The rationale must mention that join-token is the existing-
    # pattern with minimal delta.
    assert re.search(
        r"join-token is the existing-pattern", bootstrap_source
    ), (
        "Bug-37 disagree-note: the rationale must explicitly state "
        "join-token is the existing-pattern + minimal-delta choice"
    )
    # The disagree-note must explicitly mention Reza-Cross-Review.
    assert re.search(
        r"Reza-Cross-Review", bootstrap_source, re.IGNORECASE
    ), (
        "Bug-37 disagree-note: Reza-Cross-Review must be named so the "
        "review-trail is discoverable from the source"
    )


# ---------------------------------------------------------------------------
# TV-BUG-37-COHERENT-01: Both federation agent configs declare
# NodeAttestor "join_token".
# ---------------------------------------------------------------------------


def test_agent_config_orbit_declares_join_token(
    agent_config_orbit: str,
) -> None:
    """The orbit-side federation agent-config must declare
    ``NodeAttestor "join_token"`` — the plugin the Bug-37 fix wires
    coherently with the ExecStart -joinToken arg."""
    assert re.search(
        r'NodeAttestor\s+"join_token"', agent_config_orbit
    ), (
        "spire-agent-orbit.conf must declare NodeAttestor \"join_token\""
    )


def test_agent_config_wakir_declares_join_token(
    agent_config_wakir: str,
) -> None:
    """The wakir-side federation agent-config must declare
    ``NodeAttestor "join_token"`` — symmetric to orbit-side."""
    assert re.search(
        r'NodeAttestor\s+"join_token"', agent_config_wakir
    ), (
        "spire-agent-wakir.conf must declare NodeAttestor \"join_token\""
    )


# ---------------------------------------------------------------------------
# TV-BUG-37-COHERENT-02: federation-agent Quadlet template ExecStart
# has -joinToken WAKIR_JOIN_TOKEN_PLACEHOLDER.
# ---------------------------------------------------------------------------


def test_agent_fed_quadlet_has_joinToken_placeholder(
    agent_fed_quadlet: str,
) -> None:
    """The federation-agent Quadlet template MUST carry the
    ``-joinToken WAKIR_JOIN_TOKEN_PLACEHOLDER`` segment that step-6i
    substitutes."""
    assert "-joinToken WAKIR_JOIN_TOKEN_PLACEHOLDER" in agent_fed_quadlet, (
        "wakir-spire-agent-federation.container template must carry "
        "the -joinToken WAKIR_JOIN_TOKEN_PLACEHOLDER segment that "
        "step-6i substitutes"
    )


# ---------------------------------------------------------------------------
# TV-BUG-37-E2E-01: end-to-end control-flow shape.
# ---------------------------------------------------------------------------


def test_step_6i_step_6j_control_flow_shape(
    bootstrap_source: str,
) -> None:
    """End-to-end control-flow shape: step-6i runs token-generate
    for both modes; step-6j has NO mode-specific strip branch."""
    # The marker for step-6i must precede the marker for step-6j.
    step_6i_idx = bootstrap_source.find("6i.")
    step_6j_idx = bootstrap_source.find("6j.")
    assert 0 < step_6i_idx < step_6j_idx, (
        "step-6i must precede step-6j in the bootstrap source"
    )
    # The block between 6i. and 6j. must contain "spire-server token
    # generate" (the token-generate call).
    block_6i = bootstrap_source[step_6i_idx:step_6j_idx]
    assert "spire-server token generate" in block_6i, (
        "step-6i block must contain the spire-server token generate "
        "call"
    )
    # The block AFTER 6j. (until the next 6-marker or end of step-6)
    # must NOT contain ``WAKIR_PILOT_MODE" == "federation"`` followed
    # by a sed-delete on -joinToken.
    block_6j = bootstrap_source[step_6j_idx : step_6j_idx + 2500]
    assert (
        "sed -i 's| -joinToken WAKIR_JOIN_TOKEN_PLACEHOLDER" not in block_6j
    ), (
        "step-6j must not contain the -joinToken sed-delete (Bug-37 "
        "fix removed this code-path)"
    )
