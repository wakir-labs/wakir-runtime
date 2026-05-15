# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic acceptance tests for the Sprint-9-Tag-6 bring-up-cleanup
substance-fixes (10 bugs from the live Pilot-VM bring-up 2026-05-14).

Context
-------

The 2026-05-14 ~01:40 CEST Pilot-VM bring-up succeeded 6/6 on the
smoke matrix but required 15 substance patches by Operator-Hand. Kai
owns 10 of the 15 fixes; Tomás owns Bugs 3 + 6, Amara owns Bugs 13
+ 14. This module is the Kai hermetic surface.

Test-Vector index (Bug-numbered to keep cross-reference trivial)
----------------------------------------------------------------

  * ``TV-S9T6-01`` Bootstrap step 6i issues
    ``spire-server token generate`` + sed-substitutes the literal
    ``WAKIR_JOIN_TOKEN_PLACEHOLDER`` in the agent Quadlet (Bug 1/15).
  * ``TV-S9T6-02`` Bootstrap step 6g chown 1000:1000 the five named
    volumes before unit start (Bug 2).
  * ``TV-S9T6-04`` Bootstrap step 5 SKIP-COSIGN branch still resolves
    the wakir-provisioner digest via skopeo and passes it as
    ``--wakir-provisioner-digest`` to the resolver (Bug 4).
  * ``TV-S9T6-05`` ``wakir-nats-kv-bucket-init.container`` carries
    ``TimeoutStartSec=300`` (Bug 5).
  * ``TV-S9T6-07`` server Quadlet template ``Exec=`` does NOT carry
    the literal ``run`` token (Bug 7).
  * ``TV-S9T6-08`` agent Quadlet template ``Exec=`` does NOT carry
    the literal ``run`` token AND carries the
    ``WAKIR_JOIN_TOKEN_PLACEHOLDER`` for single-org injection (Bug 8).
  * ``TV-S9T6-09`` single-org server config binds ``0.0.0.0`` not
    ``127.0.0.1`` (Bug 9).
  * ``TV-S9T6-10`` server Quadlet template declares
    ``NetworkAlias=spire-server-<SIDE>`` (Bug 10).
  * ``TV-S9T6-11`` single-org agent config uses ``KeyManager "disk"``
    with directory pointing into ``/var/lib/spire/agent`` (Bug 11).
  * ``TV-S9T6-12`` both Quadlet templates declare
    ``Tmpfs=/run/spire:rw,size=16m,mode=0755`` (Bug 12).

Sandbox boundary
----------------

All tests read source files and parse them. No subprocess invocations
that touch network / podman / systemd. Bug 1/15 + Bug 2 + Bug 4
exercise the bootstrap-script source pattern only — no live agent
attestation, no live volume creation, no live skopeo inspect.

-- Kai
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
FED_CONFIG_DIR = REPO_ROOT / "infra" / "spire" / "federation" / "config"
AGENT_CONFIG_DIR = REPO_ROOT / "infra" / "spire" / "agent" / "config"
FED_QUADLET_DIR = REPO_ROOT / "infra" / "spire" / "federation" / "quadlet"
AGENT_QUADLET_DIR = REPO_ROOT / "infra" / "spire" / "agent" / "quadlet"
BOOTSTRAP = (
    REPO_ROOT / "infra" / "spire" / "federation" / "wakir-pilot-bootstrap.sh"
)

SERVER_SINGLE_ORG_CONF = FED_CONFIG_DIR / "spire-server-pilot-single-org.conf"
AGENT_SINGLE_ORG_CONF = AGENT_CONFIG_DIR / "spire-agent-pilot-single-org.conf"
SERVER_FED_TPL = FED_QUADLET_DIR / "wakir-spire-server-federation.container"
AGENT_FED_TPL = AGENT_QUADLET_DIR / "wakir-spire-agent-federation.container"
BUCKET_INIT_QUADLET = (
    REPO_ROOT / "quadlet" / "wakir-nats-kv-bucket-init.container"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_hcl_comments(text: str) -> str:
    """Return text with HCL comment lines removed."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        lines.append(line)
    return "\n".join(lines)


def _bootstrap_text() -> str:
    return BOOTSTRAP.read_text(encoding="utf-8")


def _strip_systemd_comments(text: str) -> str:
    """Return text with systemd-style comment lines removed.

    systemd unit-file parser strips ``;`` and ``#`` line-prefixed
    comments. We mirror that to avoid false positives where commentary
    contains keyword tokens.
    """
    lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#") or stripped.startswith(";"):
            continue
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# TV-S9T6-01 — Bug 1/15: bootstrap step 6i issues join-token + sed-sub
# ---------------------------------------------------------------------------


def test_tv_s9t6_01_bootstrap_single_org_join_token_workflow() -> None:
    text = _bootstrap_text()
    # The single-org branch must invoke spire-server token generate
    # against the just-started server container.
    assert re.search(
        r"spire-server\s+token\s+generate", text
    ), (
        "bootstrap.sh single-org branch MUST call "
        "``spire-server token generate`` to issue the agent join-token "
        "(Bug 1/15 substance-fix)."
    )
    # SPIFFE-ID must follow the canonical pilot pattern.
    assert re.search(
        r"spiffe://.*\$\{?WAKIR_TRUST_DOMAIN\}?.*agent/pilot",
        text,
    ), (
        "bootstrap.sh MUST issue the join-token against a SPIFFE-ID of "
        "the form ``spiffe://${WAKIR_TRUST_DOMAIN}/${WAKIR_ORG_ID}/"
        "agent/pilot``."
    )
    # TTL must be 3600 (1h pilot default).
    assert re.search(r"-ttl\s+3600", text), (
        "bootstrap.sh MUST issue the join-token with a 3600s TTL."
    )
    # sed-substitute against the placeholder.
    assert "WAKIR_JOIN_TOKEN_PLACEHOLDER" in text, (
        "bootstrap.sh MUST sed-substitute the literal "
        "``WAKIR_JOIN_TOKEN_PLACEHOLDER`` in the agent Quadlet."
    )
    # Re-run guard: agent-list grep for an already-attested pilot.
    assert re.search(
        r"spire-server\s+agent\s+list",
        text,
    ), (
        "bootstrap.sh MUST grep ``spire-server agent list`` for an "
        "already-attested pilot to keep the workflow idempotent."
    )


def test_tv_s9t6_01b_agent_quadlet_carries_placeholder() -> None:
    """The agent Quadlet template must carry the literal placeholder
    that the bootstrap then substitutes. Without the placeholder the
    sed-substitute is a silent no-op and Bug 1/15 reopens."""
    text = AGENT_FED_TPL.read_text(encoding="utf-8")
    body = _strip_systemd_comments(text)
    assert "WAKIR_JOIN_TOKEN_PLACEHOLDER" in body, (
        "agent Quadlet template MUST carry the literal placeholder "
        "token ``WAKIR_JOIN_TOKEN_PLACEHOLDER`` on its Exec= line "
        "(active unit-file body, not just commentary) so the bootstrap "
        "single-org branch has something to substitute into."
    )


# ---------------------------------------------------------------------------
# TV-S9T6-02 — Bug 2: chown 1000:1000 named-volume backing dirs
# ---------------------------------------------------------------------------


def test_tv_s9t6_02_bootstrap_chown_named_volumes() -> None:
    text = _bootstrap_text()
    # The bootstrap must podman-create the volumes (idempotent --ignore)
    # and chown their Mountpoint.
    assert re.search(
        r"volume\s+create\s+--ignore", text
    ), (
        "bootstrap.sh MUST podman-create the named volumes with "
        "``--ignore`` to make the chown step idempotent (Bug 2)."
    )
    assert re.search(
        r"chown\s+-R\s+1000:1000", text
    ), (
        "bootstrap.sh MUST chown -R 1000:1000 the named-volume backing "
        "directories so the uid:1000 SPIRE containers can write "
        "(``agent-data.json``, ``keys.json``, the Workload-API socket) "
        "without permission-denied errors (Bug 2)."
    )
    # All five required volume names must be present in the chown loop.
    required = [
        "wakir-spire-server-federation-${side}-data",
        "wakir-spire-server-federation-${side}-sockets",
        "wakir-spire-server-federation-${side}-bundles",
        "wakir-spire-agent-${side}-data",
        "wakir-spire-agent-${side}-sockets",
    ]
    for v in required:
        assert v in text, (
            f"bootstrap.sh volume-permission-loop MUST include {v} "
            f"(Bug 2 substrate)."
        )


# ---------------------------------------------------------------------------
# TV-S9T6-04 — Bug 4: SKIP-COSIGN still resolves wakir-provisioner digest
# ---------------------------------------------------------------------------


def test_tv_s9t6_04_skip_cosign_still_passes_provisioner_digest() -> None:
    """Sprint-9-Tag-6 Bug 4 invariant + Sprint-10-Tag-7 Bug-36 extension.

    Bug 4: skip-cosign branch MUST still pass the provisioner digest
    to the resolver (Sprint-9-Tag-6 substance-fix; the bucket-init
    Quadlet placeholder must be resolved even in skip-cosign mode).

    Bug-36 (Sprint-10-Tag-7) extends the branch to ALSO pass
    spire-server / spire-agent / python digests via skopeo-only
    resolution. The provisioner digest remains conditional (the image
    may not yet be published) and is appended to skip_args only when
    skopeo-inspect succeeds for the provisioner. This test verifies
    BOTH invariants: the branch references --wakir-provisioner-digest
    (conditionally), AND attempts a skopeo inspect against the
    provisioner image, AND references the canonical tag.
    """
    text = _bootstrap_text()
    # Anchor on the step-5 function header so we never match the
    # pre-banner WARNING block (which carries the same env-var
    # literal).
    step_5_start = text.find("step_5_image_pins()")
    assert step_5_start > 0, "bootstrap.sh MUST define step_5_image_pins()"
    # Walk forward until the next ``^step_`` header at column 0 (or
    # end-of-step-comment marker) — this is the function body bound.
    step_5_end_match = re.search(
        r"^step_\w+\s*\(\)\s*\{", text[step_5_start + 30 :], re.MULTILINE
    )
    if step_5_end_match:
        step_5_end = step_5_start + 30 + step_5_end_match.start()
    else:
        step_5_end = len(text)
    step5_body = text[step_5_start:step_5_end]

    # Find the skip-cosign if-then header (must be the step-5 one, not
    # the pre-flight banner — we already anchored to step-5).
    if_idx = step5_body.find(
        'if [[ "$WAKIR_SKIP_COSIGN_VERIFY" == "1" ]]; then'
    )
    assert if_idx > 0, (
        "bootstrap.sh step_5_image_pins MUST carry a "
        "WAKIR_SKIP_COSIGN_VERIFY=1 branch."
    )

    # Walk forward over the branch body, tracking if/fi nesting depth
    # so we find the MATCHING ``fi`` (not the first inner ``fi``).
    after = step5_body[if_idx:]
    depth = 0
    branch_end = None
    for m in re.finditer(
        r"^\s*(if\s|fi\s*$|fi\s*$)", after, re.MULTILINE
    ):
        token = m.group(1).strip()
        if token.startswith("if"):
            depth += 1
        else:  # ``fi``
            depth -= 1
            if depth == 0:
                branch_end = m.end()
                break
    assert branch_end is not None, (
        "could not locate the matching fi for the skip-cosign branch"
    )
    branch_body = after[:branch_end]

    # Sprint-9-Tag-6 Bug 4 invariant: branch MUST pass --wakir-
    # provisioner-digest. (After Bug-36 fix it is conditional on a
    # successful skopeo-inspect; the literal flag still appears in the
    # skip_args conditional append.)
    assert "--wakir-provisioner-digest" in branch_body, (
        "bootstrap.sh WAKIR_SKIP_COSIGN_VERIFY=1 branch MUST pass "
        "``--wakir-provisioner-digest`` to resolve-image-pins.sh "
        "(Bug 4 substance-fix; Bug-36 extension keeps this invariant)."
    )
    # And it MUST attempt a skopeo inspect against the provisioner image.
    assert re.search(r"skopeo\s+inspect", branch_body), (
        "bootstrap.sh SKIP-COSIGN branch MUST attempt a skopeo inspect "
        "(Bug 4 + Bug-36)."
    )
    # And reference the wakir-provisioner image.
    assert "wakir-provisioner:0.1.2" in branch_body, (
        "bootstrap.sh SKIP-COSIGN branch MUST reference "
        "wakir-provisioner:0.1.2 (Bug 4)."
    )


# ---------------------------------------------------------------------------
# TV-S9T6-05 — Bug 5: bucket-init TimeoutStartSec=300
# ---------------------------------------------------------------------------


def test_tv_s9t6_05_bucket_init_timeout_300s() -> None:
    text = BUCKET_INIT_QUADLET.read_text(encoding="utf-8")
    body = _strip_systemd_comments(text)
    m = re.search(r"^\s*TimeoutStartSec=(\d+)s\b", body, re.MULTILINE)
    assert m, (
        "wakir-nats-kv-bucket-init.container MUST declare an explicit "
        "TimeoutStartSec= directive (Bug 5)."
    )
    assert int(m.group(1)) >= 300, (
        f"wakir-nats-kv-bucket-init.container TimeoutStartSec="
        f"{m.group(1)}s is too short for a cold-start GHCR pull "
        f"(~131MB image). Bug 5 target: 300s."
    )


# ---------------------------------------------------------------------------
# TV-S9T6-07 — Bug 7: server Quadlet Exec= drops literal "run"
# ---------------------------------------------------------------------------


def test_tv_s9t6_07_server_quadlet_exec_no_run_token() -> None:
    text = SERVER_FED_TPL.read_text(encoding="utf-8")
    body = _strip_systemd_comments(text)
    m = re.search(r"^\s*Exec=(.+)$", body, re.MULTILINE)
    assert m, "server Quadlet template MUST carry an Exec= line"
    exec_value = m.group(1).strip()
    # Exec= must start with -config (the entrypoint supplies ``run``).
    assert exec_value.startswith("-config"), (
        f"server Quadlet Exec= MUST start with ``-config`` (Bug 7). "
        f"Got: {exec_value!r}"
    )
    # And explicitly point at the per-side server.conf bind-mount.
    assert "/etc/spire/server/server.conf" in exec_value, (
        f"server Quadlet Exec= MUST reference "
        f"/etc/spire/server/server.conf (Bug 7). Got: {exec_value!r}"
    )


# ---------------------------------------------------------------------------
# TV-S9T6-08 — Bug 8: agent Quadlet Exec= drops literal "run"
# ---------------------------------------------------------------------------


def test_tv_s9t6_08_agent_quadlet_exec_no_run_token() -> None:
    text = AGENT_FED_TPL.read_text(encoding="utf-8")
    body = _strip_systemd_comments(text)
    m = re.search(r"^\s*Exec=(.+)$", body, re.MULTILINE)
    assert m, "agent Quadlet template MUST carry an Exec= line"
    exec_value = m.group(1).strip()
    assert exec_value.startswith("-config"), (
        f"agent Quadlet Exec= MUST start with ``-config`` (Bug 8). "
        f"Got: {exec_value!r}"
    )
    assert "/etc/spire/agent/agent.conf" in exec_value, (
        f"agent Quadlet Exec= MUST reference "
        f"/etc/spire/agent/agent.conf (Bug 8). Got: {exec_value!r}"
    )
    # Single-org join-token placeholder must be present on the Exec=
    # line so the bootstrap's sed-substitute (Bug 1/15) has a target.
    assert "WAKIR_JOIN_TOKEN_PLACEHOLDER" in exec_value, (
        f"agent Quadlet Exec= MUST carry the literal "
        f"``WAKIR_JOIN_TOKEN_PLACEHOLDER`` token for single-org "
        f"join-token injection (Bug 1/15 + Bug 8). Got: {exec_value!r}"
    )


# ---------------------------------------------------------------------------
# TV-S9T6-09 — Bug 9: single-org server bind_address = 0.0.0.0
# ---------------------------------------------------------------------------


def test_tv_s9t6_09_server_single_org_bind_address_zero() -> None:
    body = _strip_hcl_comments(
        SERVER_SINGLE_ORG_CONF.read_text(encoding="utf-8")
    )
    # Find the active bind_address declaration in the HCL body.
    m = re.search(r'bind_address\s*=\s*"([^"]+)"', body)
    assert m, (
        "single-org server config MUST declare a bind_address."
    )
    assert m.group(1) == "0.0.0.0", (
        f"single-org server config bind_address MUST be 0.0.0.0 to "
        f"accept the cross-container connect from the agent inside the "
        f"wakir-federation bridge network. Got: {m.group(1)!r} (Bug 9)."
    )


# ---------------------------------------------------------------------------
# TV-S9T6-10 — Bug 10: server Quadlet NetworkAlias=spire-server-<SIDE>
# ---------------------------------------------------------------------------


def test_tv_s9t6_10_server_quadlet_network_alias() -> None:
    text = SERVER_FED_TPL.read_text(encoding="utf-8")
    body = _strip_systemd_comments(text)
    assert re.search(
        r"^\s*NetworkAlias=spire-server-<SIDE>\s*$", body, re.MULTILINE
    ), (
        "server Quadlet template MUST declare "
        "``NetworkAlias=spire-server-<SIDE>`` so the single-org agent's "
        "``server_address = \"spire-server-wakir\"`` resolves inside "
        "the wakir-federation bridge network (Bug 10)."
    )


# ---------------------------------------------------------------------------
# TV-S9T6-11 — Bug 11: single-org agent KeyManager "disk"
# ---------------------------------------------------------------------------


def test_tv_s9t6_11_agent_single_org_keymanager_disk() -> None:
    body = _strip_hcl_comments(
        AGENT_SINGLE_ORG_CONF.read_text(encoding="utf-8")
    )
    assert re.search(r'KeyManager\s+"disk"', body), (
        "single-org agent config MUST use ``KeyManager \"disk\"`` to "
        "persist the agent SVID-signing keys across container restarts. "
        "Without disk persistence every restart forces a fresh join-"
        "token (Bug 11)."
    )
    # The disk-keymanager directory must point under /var/lib/spire/agent
    # (the agent data_dir, which is the named-volume mount target).
    assert re.search(
        r'directory\s*=\s*"/var/lib/spire/agent"',
        body,
    ), (
        "single-org agent KeyManager \"disk\" MUST set "
        "``directory = \"/var/lib/spire/agent\"`` so the keys are "
        "persisted inside the named ``-data`` volume (Bug 11)."
    )
    # And the legacy ``memory`` form MUST be absent from the active body
    # (commentary that mentions it is allowed; the comment-stripper handles
    # that). Sprint-9-Tag-6 deliberately diverges single-org from the
    # federation default here.
    assert not re.search(r'KeyManager\s+"memory"', body), (
        "single-org agent config MUST NOT use ``KeyManager \"memory\"`` "
        "in the active HCL body (Bug 11). The federation variant keeps "
        "memory by design; check ``spire-agent-wakir.conf`` not this "
        "single-org file."
    )


# ---------------------------------------------------------------------------
# TV-S9T6-12 — Bug 12: both Quadlet templates Tmpfs mode=0755
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "label"),
    [
        (SERVER_FED_TPL, "server"),
        (AGENT_FED_TPL, "agent"),
    ],
)
def test_tv_s9t6_12_tmpfs_mode_0755(path: Path, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    body = _strip_systemd_comments(text)
    m = re.search(
        r"^\s*Tmpfs=/run/spire:rw,size=16m,mode=(\d{4})\s*$",
        body,
        re.MULTILINE,
    )
    assert m, (
        f"{label} Quadlet template MUST declare a Tmpfs=/run/spire "
        f"line in the active body (Bug 12)."
    )
    assert m.group(1) == "0755", (
        f"{label} Quadlet template Tmpfs=/run/spire MUST use mode=0755 "
        f"so the uid:1000 container user can bind sockets under it. "
        f"Got mode={m.group(1)}. (Bug 12)."
    )


# ---------------------------------------------------------------------------
# Meta — coverage envelope
# ---------------------------------------------------------------------------


def test_tag6_cleanup_suite_covers_all_kai_vectors() -> None:
    """Inventory check: the 10 Kai-owned Tag-6 bugs each have a named
    test function. Bugs 3 + 6 (Tomás) and Bugs 13 + 14 (Amara) are
    NOT in this module."""
    module_src = Path(__file__).read_text(encoding="utf-8")
    expected_vectors = [
        "test_tv_s9t6_01_bootstrap_single_org_join_token_workflow",
        "test_tv_s9t6_02_bootstrap_chown_named_volumes",
        "test_tv_s9t6_04_skip_cosign_still_passes_provisioner_digest",
        "test_tv_s9t6_05_bucket_init_timeout_300s",
        "test_tv_s9t6_07_server_quadlet_exec_no_run_token",
        "test_tv_s9t6_08_agent_quadlet_exec_no_run_token",
        "test_tv_s9t6_09_server_single_org_bind_address_zero",
        "test_tv_s9t6_10_server_quadlet_network_alias",
        "test_tv_s9t6_11_agent_single_org_keymanager_disk",
        "test_tv_s9t6_12_tmpfs_mode_0755",
    ]
    for name in expected_vectors:
        assert f"def {name}(" in module_src, (
            f"expected TV function missing: {name}"
        )
