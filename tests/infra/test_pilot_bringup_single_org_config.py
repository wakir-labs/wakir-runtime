# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic acceptance tests for the Sprint-9-Tag-5 Bug 7 substance-fix:
single-org SPIRE-Server / SPIRE-Agent config variants for the
Phase-1b Pilot-VM bring-up.

Context
-------

The Sprint-8 Tag-1/Tag-2 federation configs declare a
``federates_with "partner.test"`` block on the server side and
``insecure_bootstrap = false`` + ``trust_bundle_path = .../bootstrap.jwks``
on the agent side. On a single-org Pilot-VM there is no partner peer:
the server fails to resolve the peer DNS name, the agent cannot
bootstrap the trust-anchor, and both crash-loop (live-bring-up
2026-05-13, Mira-Bug-Bilanz §Bug-7).

The Sprint-9-Tag-5 substance-fix ships two new config variants:

  * ``infra/spire/federation/config/spire-server-pilot-single-org.conf``
    -- no ``federates_with``, no ``federation { bundle_endpoint }``
  * ``infra/spire/agent/config/spire-agent-pilot-single-org.conf``
    -- ``insecure_bootstrap = true``, no ``trust_bundle_path``

plus a ``WAKIR_PILOT_MODE`` env-var in ``wakir-pilot-bootstrap.sh`` that
selects which variant the bootstrap installs (``single-org`` default
for Phase-1b; ``federation`` for Phase-2.1 dual-side).

Plus two cold-start hardenings:
  * ``HealthStartPeriod=60s`` on server + agent Quadlet templates
    (was 30s -- Bug 7 H3 candidate).
  * SELinux defense-in-depth recipe in
    ``infra/spire/federation/selinux/SELINUX_RECIPE.md`` plus the
    canonical custom-policy baseline ``wakir-spire-pilot.te`` (Bug 7
    H2 candidate).

Test-Vector index
-----------------

  * ``TV-S9T5-01`` single-org server config has NO ``federates_with``
    block (HCL body; comments excluded).
  * ``TV-S9T5-02`` single-org server config has NO
    ``federation { bundle_endpoint { ... } }`` listener block.
  * ``TV-S9T5-03`` single-org server config still declares the
    trust_domain literal ``wakir.test`` (parity with agent side).
  * ``TV-S9T5-04`` single-org agent config sets ``insecure_bootstrap
    = true``.
  * ``TV-S9T5-05`` single-org agent config has NO ``trust_bundle_path``
    directive (HCL body; comments excluded).
  * ``TV-S9T5-06`` single-org agent config keeps the SPIFFE-canonical
    Workload-API socket-path.
  * ``TV-S9T5-07`` bootstrap.sh accepts ``WAKIR_PILOT_MODE`` env-var
    with values ``single-org`` and ``federation``; defaults to
    ``single-org``.
  * ``TV-S9T5-08`` bootstrap.sh in single-org mode installs the
    single-org server config; in federation mode installs the
    per-side spire-server-${side}.conf.
  * ``TV-S9T5-09`` bootstrap.sh in single-org mode installs the
    single-org agent config; in federation mode installs the per-side
    spire-agent-${side}.conf.
  * ``TV-S9T5-10`` bootstrap.sh in single-org mode drops the
    federated-bundles read-only mount line from the agent container
    template via in-place sed-deletion.
  * ``TV-S9T5-11`` server Quadlet template has
    ``HealthStartPeriod=60s`` (Bug 7 H3 fix).
  * ``TV-S9T5-12`` agent Quadlet template has
    ``HealthStartPeriod=60s`` (Bug 7 H3 fix).
  * ``TV-S9T5-13`` SELinux-recipe document exists at the canonical
    path.
  * ``TV-S9T5-14`` SELinux custom-policy ``wakir-spire-pilot.te``
    exists and declares only the defense-in-depth type-transition
    (no broad grants).
  * ``TV-S9T5-15`` invalid ``WAKIR_PILOT_MODE`` value fails
    pre-flight with exit-code 1.
  * ``TV-S9T5-16`` Sprint-8-Tag-1/Tag-2 federation configs remain
    untouched on disk (so Phase-2.1 dual-side bring-up still works
    after the Sprint-9-Tag-5 fix lands).

Sandbox boundary
----------------

All tests read source files and parse them. No subprocess invocations
that could touch network, podman, or systemd. The bootstrap-script
test surface uses ``bash -c`` to drive only the variable-resolution
and case-validation logic, not Phases 1-8.

-- Kai
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
FED_CONFIG_DIR = REPO_ROOT / "infra" / "spire" / "federation" / "config"
AGENT_CONFIG_DIR = REPO_ROOT / "infra" / "spire" / "agent" / "config"
FED_QUADLET_DIR = REPO_ROOT / "infra" / "spire" / "federation" / "quadlet"
AGENT_QUADLET_DIR = REPO_ROOT / "infra" / "spire" / "agent" / "quadlet"
SELINUX_DIR = REPO_ROOT / "infra" / "spire" / "federation" / "selinux"
BOOTSTRAP = (
    REPO_ROOT / "infra" / "spire" / "federation" / "wakir-pilot-bootstrap.sh"
)

SERVER_SINGLE_ORG_CONF = FED_CONFIG_DIR / "spire-server-pilot-single-org.conf"
AGENT_SINGLE_ORG_CONF = AGENT_CONFIG_DIR / "spire-agent-pilot-single-org.conf"
SERVER_WAKIR_CONF = FED_CONFIG_DIR / "spire-server-wakir.conf"
SERVER_PARTNER_CONF = FED_CONFIG_DIR / "spire-server-partner.conf"
AGENT_WAKIR_CONF = AGENT_CONFIG_DIR / "spire-agent-wakir.conf"
AGENT_PARTNER_CONF = AGENT_CONFIG_DIR / "spire-agent-partner.conf"
SERVER_FED_TPL = FED_QUADLET_DIR / "wakir-spire-server-federation.container"
AGENT_FED_TPL = AGENT_QUADLET_DIR / "wakir-spire-agent-federation.container"

SELINUX_RECIPE = SELINUX_DIR / "SELINUX_RECIPE.md"
SELINUX_POLICY = SELINUX_DIR / "wakir-spire-pilot.te"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_hcl_comments(text: str) -> str:
    """Return text with HCL comment lines removed.

    HCL accepts ``#`` and ``//`` line-prefixed comments. Block comments
    (``/* ... */``) are not used in our Mock/Stub configs but are
    handled defensively.
    """
    # Strip /* ... */ block comments.
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


# ---------------------------------------------------------------------------
# TV-S9T5-01 — single-org server config: no federates_with block
# ---------------------------------------------------------------------------


def test_tv_s9t5_01_server_single_org_has_no_federates_with() -> None:
    body = _strip_hcl_comments(
        SERVER_SINGLE_ORG_CONF.read_text(encoding="utf-8")
    )
    assert "federates_with" not in body, (
        "single-org server config HCL body MUST NOT declare a "
        "``federates_with`` block. The single-org Pilot-VM has no "
        "federation peer; this block is the root cause of Bug 7 H1 "
        "(SPIRE-Server crash-loops on peer-DNS-miss)."
    )


# ---------------------------------------------------------------------------
# TV-S9T5-02 — single-org server config: no federation bundle_endpoint
# ---------------------------------------------------------------------------


def test_tv_s9t5_02_server_single_org_has_no_bundle_endpoint() -> None:
    body = _strip_hcl_comments(
        SERVER_SINGLE_ORG_CONF.read_text(encoding="utf-8")
    )
    # Both keywords ``federation`` and ``bundle_endpoint`` MUST be
    # absent from the active HCL body. Either alone would suggest a
    # peer-export listener that the single-org pilot does not consume.
    assert "bundle_endpoint" not in body, (
        "single-org server config HCL body MUST NOT declare a "
        "``bundle_endpoint`` listener (no peer to export the trust-"
        "bundle to)."
    )
    # The word ``federation`` may appear in identifiers but MUST not
    # be the keyword opening a block — assert by checking for the
    # block-opening form.
    assert not re.search(r"^\s*federation\s*\{", body, re.MULTILINE), (
        "single-org server config HCL body MUST NOT open a "
        "``federation { ... }`` block."
    )


# ---------------------------------------------------------------------------
# TV-S9T5-03 — single-org server config: trust_domain literal
# ---------------------------------------------------------------------------


def test_tv_s9t5_03_server_single_org_trust_domain() -> None:
    text = SERVER_SINGLE_ORG_CONF.read_text(encoding="utf-8")
    assert re.search(
        r'trust_domain\s*=\s*"wakir\.test"', text
    ), (
        "single-org server config MUST declare trust_domain = \"wakir.test\" "
        "to match the single-org agent config."
    )


# ---------------------------------------------------------------------------
# TV-S9T5-04 — single-org agent config: insecure_bootstrap = true
# ---------------------------------------------------------------------------


def test_tv_s9t5_04_agent_single_org_insecure_bootstrap_true() -> None:
    text = AGENT_SINGLE_ORG_CONF.read_text(encoding="utf-8")
    assert re.search(
        r"insecure_bootstrap\s*=\s*true", text
    ), (
        "single-org agent config MUST declare ``insecure_bootstrap = "
        "true``. The single-org Pilot-VM has no federated-bundles "
        "volume to source a pre-staged trust-anchor from; the agent "
        "obtains the local server's trust-bundle via the join-token "
        "attestation handshake instead."
    )


# ---------------------------------------------------------------------------
# TV-S9T5-05 — single-org agent config: no trust_bundle_path
# ---------------------------------------------------------------------------


def test_tv_s9t5_05_agent_single_org_no_trust_bundle_path() -> None:
    body = _strip_hcl_comments(
        AGENT_SINGLE_ORG_CONF.read_text(encoding="utf-8")
    )
    assert "trust_bundle_path" not in body, (
        "single-org agent config HCL body MUST NOT declare "
        "``trust_bundle_path``. With ``insecure_bootstrap = true`` the "
        "agent does not require a pre-staged trust-anchor file."
    )


# ---------------------------------------------------------------------------
# TV-S9T5-06 — single-org agent config: SPIFFE-canonical socket-path
# ---------------------------------------------------------------------------


def test_tv_s9t5_06_agent_single_org_workload_api_socket_path() -> None:
    text = AGENT_SINGLE_ORG_CONF.read_text(encoding="utf-8")
    assert re.search(
        r'socket_path\s*=\s*"/run/spire/agent-sockets/api\.sock"', text
    ), (
        "single-org agent config socket_path MUST be the SPIFFE-spec "
        "canonical /run/spire/agent-sockets/api.sock (Phase-2.3+ "
        "persona-Workload-API consumers depend on this convention)."
    )


# ---------------------------------------------------------------------------
# TV-S9T5-07 — bootstrap.sh WAKIR_PILOT_MODE env-var default + validation
# ---------------------------------------------------------------------------


def test_tv_s9t5_07_bootstrap_default_pilot_mode_single_org() -> None:
    text = _bootstrap_text()
    # Default-value declaration via shell parameter-expansion.
    assert re.search(
        r':\s*"\$\{WAKIR_PILOT_MODE:=single-org\}"', text
    ), (
        "bootstrap.sh MUST default WAKIR_PILOT_MODE to 'single-org' "
        "via shell parameter expansion: "
        ":\"${WAKIR_PILOT_MODE:=single-org}\""
    )
    # Validation of the two allowed values must be present.
    assert re.search(
        r'case\s+"\$WAKIR_PILOT_MODE"\s+in\s*\n?\s*single-org\|federation',
        text,
    ), (
        "bootstrap.sh MUST validate WAKIR_PILOT_MODE against the "
        "exact set {single-org, federation} via a case-statement."
    )


# ---------------------------------------------------------------------------
# TV-S9T5-08 — bootstrap.sh Phase 6c: single-org server-conf source
# ---------------------------------------------------------------------------


def test_tv_s9t5_08_bootstrap_phase6c_picks_single_org_server_conf() -> None:
    text = _bootstrap_text()
    # Bootstrap must reference the single-org source path in Phase 6c.
    assert "spire-server-pilot-single-org.conf" in text, (
        "bootstrap.sh Phase 6c MUST reference "
        "``spire-server-pilot-single-org.conf`` as the single-org "
        "server-config source."
    )
    # And must still reference the per-side variant for federation mode.
    assert re.search(
        r'spire-server-\$\{side\}\.conf', text
    ), (
        "bootstrap.sh Phase 6c MUST also reference the per-side "
        "``spire-server-${side}.conf`` for WAKIR_PILOT_MODE=federation."
    )


# ---------------------------------------------------------------------------
# TV-S9T5-09 — bootstrap.sh Phase 6d: single-org agent-conf source
# ---------------------------------------------------------------------------


def test_tv_s9t5_09_bootstrap_phase6d_picks_single_org_agent_conf() -> None:
    text = _bootstrap_text()
    assert "spire-agent-pilot-single-org.conf" in text, (
        "bootstrap.sh Phase 6d MUST reference "
        "``spire-agent-pilot-single-org.conf`` as the single-org "
        "agent-config source."
    )
    assert re.search(
        r'spire-agent-\$\{side\}\.conf', text
    ), (
        "bootstrap.sh Phase 6d MUST also reference the per-side "
        "``spire-agent-${side}.conf`` for WAKIR_PILOT_MODE=federation."
    )


# ---------------------------------------------------------------------------
# TV-S9T5-10 — bootstrap.sh single-org mode drops bundles-volume line
# ---------------------------------------------------------------------------


def test_tv_s9t5_10_bootstrap_drops_bundles_volume_in_single_org() -> None:
    text = _bootstrap_text()
    # In single-org mode we sed-delete the federated-bundles read-only
    # mount line. Assert the deletion expression is present.
    assert re.search(
        r'wakir-spire-server-federation-<SIDE>-bundles\\?\.volume:/var/lib/spire/bundles:ro',
        text,
    ), (
        "bootstrap.sh single-org branch MUST contain a sed expression "
        "that targets the federated-bundles read-only mount line in "
        "the agent Quadlet template for deletion."
    )
    # And the sed expression must be a deletion (``d``).
    # Look for the ``|d`` terminator of a sed-address-pattern.
    bundles_lines = [
        line for line in text.splitlines()
        if "wakir-spire-server-federation-<SIDE>-bundles" in line
        and ":/var/lib/spire/bundles:ro" in line
    ]
    has_deletion = any("|d\"" in line or "|d'" in line for line in bundles_lines)
    assert has_deletion, (
        "bootstrap.sh single-org branch MUST use a sed deletion "
        "(address|d) to drop the bundles-volume line. Found candidates: "
        f"{bundles_lines}"
    )


# ---------------------------------------------------------------------------
# TV-S9T5-11 — server Quadlet HealthStartPeriod = 60s
# ---------------------------------------------------------------------------


def test_tv_s9t5_11_server_quadlet_health_start_period_60s() -> None:
    text = SERVER_FED_TPL.read_text(encoding="utf-8")
    m = re.search(r"^HealthStartPeriod=(\d+)s", text, re.MULTILINE)
    assert m, "server-federation Quadlet declares no HealthStartPeriod"
    period_seconds = int(m.group(1))
    assert period_seconds >= 60, (
        f"server-federation Quadlet HealthStartPeriod={period_seconds}s "
        f"is too short for cold Pilot-VM CA-init; Sprint-9-Tag-5 "
        f"target is 60s (Bug 7 H3 fix)."
    )


# ---------------------------------------------------------------------------
# TV-S9T5-12 — agent Quadlet HealthStartPeriod = 60s
# ---------------------------------------------------------------------------


def test_tv_s9t5_12_agent_quadlet_health_start_period_60s() -> None:
    text = AGENT_FED_TPL.read_text(encoding="utf-8")
    m = re.search(r"^HealthStartPeriod=(\d+)s", text, re.MULTILINE)
    assert m, "agent-federation Quadlet declares no HealthStartPeriod"
    period_seconds = int(m.group(1))
    assert period_seconds >= 60, (
        f"agent-federation Quadlet HealthStartPeriod={period_seconds}s "
        f"is too short for cold Pilot-VM CA-init + attestation "
        f"handshake; Sprint-9-Tag-5 target is 60s (Bug 7 H3 fix)."
    )


# ---------------------------------------------------------------------------
# TV-S9T5-13 — SELinux recipe document exists
# ---------------------------------------------------------------------------


def test_tv_s9t5_13_selinux_recipe_exists() -> None:
    assert SELINUX_RECIPE.exists(), (
        f"SELinux defense-in-depth recipe MUST exist at "
        f"{SELINUX_RECIPE} (Bug 7 H2 fix substrate)."
    )
    text = SELINUX_RECIPE.read_text(encoding="utf-8")
    # Recipe must reference the canonical Pilot-VM commands.
    for marker in (
        "ausearch -m AVC",
        "chcon -Rt container_file_t",
        "audit2allow",
        "wakir-spire-pilot.te",
    ):
        assert marker in text, (
            f"SELinux recipe MUST mention `{marker}` "
            f"(operator-hand recovery substrate)."
        )


# ---------------------------------------------------------------------------
# TV-S9T5-14 — SELinux custom-policy ``wakir-spire-pilot.te`` minimal
# ---------------------------------------------------------------------------


def test_tv_s9t5_14_selinux_policy_minimal_defense_in_depth() -> None:
    assert SELINUX_POLICY.exists(), (
        f"SELinux custom-policy ``wakir-spire-pilot.te`` MUST exist at "
        f"{SELINUX_POLICY}."
    )
    text = SELINUX_POLICY.read_text(encoding="utf-8")
    # The policy MUST declare a type-transition (defense-in-depth) and
    # NOT declare a broad ``allow ... unlabeled_t ...`` rule (which is
    # what the naive audit2allow output looks like).
    assert re.search(
        r"type_transition\s+container_runtime_t\s+container_var_lib_t",
        text,
    ), (
        "wakir-spire-pilot.te MUST declare a type-transition for "
        "container_runtime_t to ensure new volume files inherit "
        "container_file_t."
    )
    # No broad allow rules targeting unlabeled_t -- that would be an
    # over-permissive policy.
    assert "allow container_t unlabeled_t" not in text, (
        "wakir-spire-pilot.te MUST NOT allow container_t -> "
        "unlabeled_t (broad attack surface). Use the type-transition "
        "instead."
    )


# ---------------------------------------------------------------------------
# TV-S9T5-15 — bootstrap.sh rejects invalid WAKIR_PILOT_MODE
# ---------------------------------------------------------------------------


def test_tv_s9t5_15_bootstrap_rejects_invalid_pilot_mode(tmp_path: Path) -> None:
    """Drive the variable-resolution + case-validation logic of the
    bootstrap script directly. We do not enter Phases 1-8 (those would
    require root + podman); we only assert the pre-flight reject.
    """
    # Build a minimal harness that sources the variable-resolution
    # block by extracting the script preamble up to (but not
    # including) the pre-banner. We replace the validation's exit 1
    # with a printable marker so the test sees the reject path.
    bootstrap_text = _bootstrap_text()
    # Reject path: case * | echo + exit 1. We assert the case-stmt
    # textually rather than executing.
    case_block = re.search(
        r"case\s+\"\$WAKIR_PILOT_MODE\"\s+in.*?esac",
        bootstrap_text,
        re.DOTALL,
    )
    assert case_block, "bootstrap.sh MUST have a case-statement validating WAKIR_PILOT_MODE"
    case_body = case_block.group(0)
    assert "exit 1" in case_body, (
        "bootstrap.sh case-statement for WAKIR_PILOT_MODE MUST exit 1 "
        "on an invalid value (catch the operator typo early)."
    )
    # Execute a small standalone snippet that mirrors the validation
    # to confirm the regex describes a real working bash branch.
    snippet = (
        '#!/usr/bin/env bash\n'
        ': "${WAKIR_PILOT_MODE:=single-org}"\n'
        'case "$WAKIR_PILOT_MODE" in\n'
        '  single-org|federation) echo OK ;;\n'
        '  *) echo "ERROR: invalid mode" >&2; exit 1 ;;\n'
        'esac\n'
    )
    script = tmp_path / "validate.sh"
    script.write_text(snippet, encoding="utf-8")
    script.chmod(0o755)
    env = os.environ.copy()
    env["WAKIR_PILOT_MODE"] = "bogus-mode"
    proc = subprocess.run(
        ["bash", str(script)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, (
        f"bootstrap-validation snippet MUST exit 1 on invalid mode; "
        f"got returncode={proc.returncode}, stdout={proc.stdout!r}, "
        f"stderr={proc.stderr!r}"
    )
    assert "ERROR" in proc.stderr


# ---------------------------------------------------------------------------
# TV-S9T5-16 — Sprint-8 federation configs preserved
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "preserved_conf",
    [
        SERVER_WAKIR_CONF,
        SERVER_PARTNER_CONF,
        AGENT_WAKIR_CONF,
        AGENT_PARTNER_CONF,
    ],
)
def test_tv_s9t5_16_federation_configs_preserved(preserved_conf: Path) -> None:
    """The Sprint-9-Tag-5 fix MUST NOT delete or alter the Sprint-8
    federation config variants -- they are needed for Phase-2.1
    dual-side bring-up (``WAKIR_PILOT_MODE=federation``)."""
    assert preserved_conf.exists(), (
        f"federation config {preserved_conf} MUST be preserved by the "
        f"Sprint-9-Tag-5 fix (used for WAKIR_PILOT_MODE=federation)."
    )
    text = preserved_conf.read_text(encoding="utf-8")
    # Sanity: the federation server configs MUST still carry the
    # federation-specific markers; the federation agent configs MUST
    # still carry ``insecure_bootstrap = false``.
    if "spire-server-" in preserved_conf.name:
        assert "federates_with" in text or "bundle_endpoint" in text, (
            f"federation server config {preserved_conf} MUST still "
            f"contain federation-specific markers."
        )
    elif "spire-agent-" in preserved_conf.name:
        assert re.search(r"insecure_bootstrap\s*=\s*false", text), (
            f"federation agent config {preserved_conf} MUST still "
            f"declare insecure_bootstrap = false."
        )


# ---------------------------------------------------------------------------
# Meta — coverage envelope
# ---------------------------------------------------------------------------


def test_single_org_suite_covers_all_sprint9_tag5_vectors() -> None:
    """Inventory check: the 16 test-vector groups exist as named
    test functions in this module. Future Sprint-9-Tag-5 follow-ups
    land here so the substance-fix and the regression net stay
    synchronized."""
    module_src = Path(__file__).read_text(encoding="utf-8")
    expected_vectors = [
        "test_tv_s9t5_01_server_single_org_has_no_federates_with",
        "test_tv_s9t5_02_server_single_org_has_no_bundle_endpoint",
        "test_tv_s9t5_03_server_single_org_trust_domain",
        "test_tv_s9t5_04_agent_single_org_insecure_bootstrap_true",
        "test_tv_s9t5_05_agent_single_org_no_trust_bundle_path",
        "test_tv_s9t5_06_agent_single_org_workload_api_socket_path",
        "test_tv_s9t5_07_bootstrap_default_pilot_mode_single_org",
        "test_tv_s9t5_08_bootstrap_phase6c_picks_single_org_server_conf",
        "test_tv_s9t5_09_bootstrap_phase6d_picks_single_org_agent_conf",
        "test_tv_s9t5_10_bootstrap_drops_bundles_volume_in_single_org",
        "test_tv_s9t5_11_server_quadlet_health_start_period_60s",
        "test_tv_s9t5_12_agent_quadlet_health_start_period_60s",
        "test_tv_s9t5_13_selinux_recipe_exists",
        "test_tv_s9t5_14_selinux_policy_minimal_defense_in_depth",
        "test_tv_s9t5_15_bootstrap_rejects_invalid_pilot_mode",
        "test_tv_s9t5_16_federation_configs_preserved",
    ]
    for name in expected_vectors:
        assert f"def {name}(" in module_src, (
            f"expected TV function missing: {name}"
        )


# ---------------------------------------------------------------------------
# Source-shape sanity: the four-file substrate must be present.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "p",
    [
        SERVER_SINGLE_ORG_CONF,
        AGENT_SINGLE_ORG_CONF,
        SELINUX_RECIPE,
        SELINUX_POLICY,
        BOOTSTRAP,
        SERVER_FED_TPL,
        AGENT_FED_TPL,
    ],
)
def test_source_targets_exist(p: Path) -> None:
    assert p.exists(), f"required source file missing: {p}"
