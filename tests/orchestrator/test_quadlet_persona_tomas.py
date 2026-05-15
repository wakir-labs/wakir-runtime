# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Hermetic Quadlet-unit invariant tests for the Sprint-Pengine-7
# Tag-5 OI-PILOT-1 Tomás-Persona pilot container (Selin-owned
# domain, Cross-Review Zone-J with Kai).
#
# Unlike the Phase-2 Sprint-6 NATS / SPIRE Quadlet parity tests
# (which assert byte-precise mirror against compose/*.yaml), the
# Tomás-Persona container has no compose counterpart — the
# persona-engine pilot is Quadlet-native from Sprint-Pengine-7
# Tag-5 onward (Phase-1c migration substrate, no Phase-1b compose
# back-port). The invariants asserted here therefore cover:
#
# 1. ADR-0058-Pilot-Phase pre-condition contract:
#    After= / Requires= encode the dependency chain on
#    wakir-nats / wakir-spire-agent / wakir-nats-kv-bucket-init.
# 2. SPIFFE-Workload-API integration: the Quadlet bind-mounts
#    the wakir-spire-agent-sockets named volume read-only at
#    /run/spire/agent-sockets, and the persona-engine's env var
#    contract points SPIFFE_ENDPOINT_SOCKET at that path.
# 3. Persona-state bucket env var: the Quadlet pins
#    WAKIR_PERSONA_STATE_BUCKET to the OI-PILOT-2 bucket name
#    wakir-persona-state-acme-tomas (the bucket that
#    ``wakir-nats-kv-bucket-init.service`` provisions via the
#    Tag-5 ``--persona-state-pair`` extension).
# 4. Hermetic-hardening parity with SPIRE-Agent / NATS Quadlets:
#    ReadOnly, DropCapability=ALL, NoNewPrivileges, User=1000.
# 5. SELinux relabel discipline: the workspace volume carries
#    Z,U flags (Bug-20 fix shape from Sprint-9 Tag-8).
# 6. Restart policy: on-failure with 10s backoff (Tag-4 §3.7.4.2
#    R4 resume-operation pre-condition).
# 7. Health-probe contract: persona-engine healthcheck subcommand
#    with start-period >= 30s (matches Tag-3 §3.7.2.4
#    spawn-state-machine cold-start latency).

from __future__ import annotations

import configparser
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
QUADLET_DIR = REPO_ROOT / "quadlet"
QUADLET_CONTAINER = QUADLET_DIR / "wakir-persona-tomas.container"
QUADLET_WORKSPACE_VOL = (
    QUADLET_DIR / "wakir-persona-tomas-workspace.volume"
)


# ---------------------------------------------------------------------
# Helpers (parity with test_quadlet_spire / test_quadlet_nats)
# ---------------------------------------------------------------------


def _read_ini(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(
        strict=False,
        interpolation=None,
        comment_prefixes=("#", ";"),
        allow_no_value=True,
    )
    parser.read(path, encoding="utf-8")
    return parser


def _section_lines(path: Path, section: str, key: str) -> list[str]:
    text = path.read_text(encoding="utf-8")
    values: list[str] = []
    in_target_section = False
    section_marker = f"[{section}]"
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_target_section = line == section_marker
            continue
        if not in_target_section:
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == key:
            values.append(v.strip())
    return values


# ---------------------------------------------------------------------
# T-QUADLET-PERSONA-01 — files exist and parse as ini
# ---------------------------------------------------------------------


def test_quadlet_unit_files_exist():
    assert QUADLET_CONTAINER.exists(), QUADLET_CONTAINER
    assert QUADLET_WORKSPACE_VOL.exists(), QUADLET_WORKSPACE_VOL


def test_quadlet_unit_files_parse_as_ini():
    container = _read_ini(QUADLET_CONTAINER)
    assert "Unit" in container.sections()
    assert "Container" in container.sections()
    assert "Service" in container.sections()
    assert "Install" in container.sections()
    volume = _read_ini(QUADLET_WORKSPACE_VOL)
    assert "Unit" in volume.sections()
    assert "Volume" in volume.sections()
    assert "Install" in volume.sections()


# ---------------------------------------------------------------------
# T-QUADLET-PERSONA-02 — ADR-0058 pre-condition chain
# ---------------------------------------------------------------------


def test_unit_after_chain_carries_phase_1b_and_2_pre_conditions():
    after_lines = _section_lines(QUADLET_CONTAINER, "Unit", "After")
    # Quadlet permits a single space-separated After= or multiple
    # lines; flatten before checking.
    flat = " ".join(after_lines)
    assert "wakir-nats.service" in flat, after_lines
    assert "wakir-spire-agent.service" in flat, after_lines
    assert "wakir-nats-kv-bucket-init.service" in flat, after_lines
    assert "network-online.target" in flat, after_lines


def test_unit_requires_chain_carries_hard_pre_conditions():
    requires_lines = _section_lines(QUADLET_CONTAINER, "Unit", "Requires")
    flat = " ".join(requires_lines)
    # NATS and SPIRE-Agent are hard requirements (Tomás-pilot
    # cannot spawn without them). The bucket-init oneshot is a
    # soft After-only ordering: the bucket may have been
    # provisioned on a prior boot and the oneshot stays inactive
    # afterwards.
    assert "wakir-nats.service" in flat, requires_lines
    assert "wakir-spire-agent.service" in flat, requires_lines


# ---------------------------------------------------------------------
# T-QUADLET-PERSONA-03 — SPIFFE-Workload-API integration
# ---------------------------------------------------------------------


def test_spire_agent_sockets_volume_is_mounted_readonly():
    volumes = _section_lines(QUADLET_CONTAINER, "Container", "Volume")
    socket_mounts = [
        v for v in volumes
        if "wakir-spire-agent-sockets.volume" in v
        and "/run/spire/agent-sockets" in v
    ]
    assert len(socket_mounts) == 1, volumes
    # Must be read-only ro flag + Z + U.
    mount = socket_mounts[0]
    assert "ro" in mount.split(":")[-1].split(","), mount
    assert "Z" in mount.split(":")[-1].split(","), mount
    assert "U" in mount.split(":")[-1].split(","), mount


def test_spiffe_endpoint_socket_env_var_points_to_workload_api():
    env_lines = _section_lines(QUADLET_CONTAINER, "Container", "Environment")
    spiffe_env = [e for e in env_lines if e.startswith("SPIFFE_ENDPOINT_SOCKET=")]
    assert len(spiffe_env) == 1, env_lines
    assert spiffe_env[0] == (
        "SPIFFE_ENDPOINT_SOCKET=unix:///run/spire/agent-sockets/api.sock"
    )


# ---------------------------------------------------------------------
# T-QUADLET-PERSONA-04 — Persona-state bucket env var (OI-PILOT-2)
# ---------------------------------------------------------------------


def test_persona_state_bucket_env_pins_oi_pilot_2_bucket_name():
    env_lines = _section_lines(QUADLET_CONTAINER, "Container", "Environment")
    bucket_env = [e for e in env_lines if e.startswith("WAKIR_PERSONA_STATE_BUCKET=")]
    assert len(bucket_env) == 1, env_lines
    assert bucket_env[0] == (
        "WAKIR_PERSONA_STATE_BUCKET=wakir-persona-state-acme-tomas"
    )


def test_persona_id_and_org_id_env_vars_are_present():
    env_lines = _section_lines(QUADLET_CONTAINER, "Container", "Environment")
    assert "WAKIR_PERSONA_ID=tomas" in env_lines
    assert "WAKIR_ORG_ID=acme" in env_lines


def test_nats_servers_env_points_at_orchestrator_dns():
    env_lines = _section_lines(QUADLET_CONTAINER, "Container", "Environment")
    nats_env = [e for e in env_lines if e.startswith("WAKIR_NATS_SERVERS=")]
    assert len(nats_env) == 1, env_lines
    assert nats_env[0] == "WAKIR_NATS_SERVERS=nats://wakir-nats:4222"


# ---------------------------------------------------------------------
# T-QUADLET-PERSONA-05 — hermetic-hardening parity
# ---------------------------------------------------------------------


def test_container_section_carries_full_hardening_set():
    container = _read_ini(QUADLET_CONTAINER)
    section = container["Container"]
    assert section.get("ReadOnly") == "true"
    assert section.get("DropCapability") == "ALL"
    assert section.get("NoNewPrivileges") == "true"
    assert section.get("User") == "1000"
    assert section.get("Group") == "1000"


# ---------------------------------------------------------------------
# T-QUADLET-PERSONA-06 — SELinux relabel discipline (Bug-20 fix shape)
# ---------------------------------------------------------------------


def test_workspace_named_volume_carries_z_and_u_flags():
    volumes = _section_lines(QUADLET_CONTAINER, "Container", "Volume")
    workspace_mounts = [
        v for v in volumes
        if "wakir-persona-tomas-workspace.volume" in v
    ]
    assert len(workspace_mounts) == 1, volumes
    mount = workspace_mounts[0]
    flags = mount.split(":")[-1].split(",")
    assert "Z" in flags, mount
    assert "U" in flags, mount


def test_persona_definition_bind_mounts_are_readonly():
    volumes = _section_lines(QUADLET_CONTAINER, "Container", "Volume")
    tomas_md = [v for v in volumes if "/etc/wakir/persona/tomas.md" in v]
    tomas_json = [v for v in volumes if "/etc/wakir/persona/tomas.json" in v]
    assert len(tomas_md) == 1, volumes
    assert len(tomas_json) == 1, volumes
    for mount in (tomas_md[0], tomas_json[0]):
        flags = mount.split(":")[-1].split(",")
        assert "ro" in flags, mount
        assert "Z" in flags, mount


# ---------------------------------------------------------------------
# T-QUADLET-PERSONA-06b — Sprint-10 Tag-6 Bug-35: persona-files source
# paths MUST be decoupled from the wakir-runtime repo-topology. The
# Pilot-VM does NOT carry the AI-Corp main repo, where the axis-A
# Markdown + axis-C JSON sources live. The operator stages the files
# at /etc/wakir/persona/<slug>.{md,json} (see TOMAS_SPAWN_RECIPE.md
# §9a, Bug-35 substance-fix). The Quadlet MUST source from that
# operator-staged path, NOT from /opt/wakir-runtime/.
# ---------------------------------------------------------------------


def test_persona_definition_source_paths_decoupled_from_repo_topology():
    """Bug-35 fix: persona-files MUST source from /etc/wakir/persona/.

    Regression-guard against the prior /opt/wakir-runtime/.claude/agents/
    + /opt/wakir-runtime/wakir-persona/ paths which do NOT exist on the
    Pilot-VM (the AI-Corp main repo is not present there).
    """
    volumes = _section_lines(QUADLET_CONTAINER, "Container", "Volume")
    persona_file_mounts = [
        v for v in volumes
        if "/etc/wakir/persona/tomas.md" in v
        or "/etc/wakir/persona/tomas.json" in v
    ]
    assert len(persona_file_mounts) == 2, volumes
    for mount in persona_file_mounts:
        # Volume= format is <source>:<dest>:<flags>. Source MUST start
        # with /etc/wakir/persona/ (operator-staged), NOT with
        # /opt/wakir-runtime/ (repo-topology-bound, does NOT exist on
        # Pilot-VM).
        source = mount.split(":")[0]
        assert source.startswith("/etc/wakir/persona/"), (
            f"Bug-35: persona-file source MUST be /etc/wakir/persona/* "
            f"(operator-staged, decoupled from repo-topology). Got: {source!r}"
        )
        assert "/opt/wakir-runtime/" not in source, (
            f"Bug-35 regression: /opt/wakir-runtime/ source path is "
            f"forbidden — the AI-Corp main repo is NOT present on the "
            f"Pilot-VM. Got: {source!r}"
        )


# ---------------------------------------------------------------------
# T-QUADLET-PERSONA-07 — restart policy (Tag-4 §3.7.4.2 R4)
# ---------------------------------------------------------------------


def test_service_section_carries_on_failure_restart_with_backoff():
    container = _read_ini(QUADLET_CONTAINER)
    service = container["Service"]
    assert service.get("Restart") == "on-failure"
    # RestartSec must be >= 5s to give recovery-workflow R4
    # resume-operation room. The default 10s in the unit file
    # is the operator-validated value.
    restart_sec = service.get("RestartSec", "0")
    assert restart_sec.endswith("s")
    assert int(restart_sec.rstrip("s")) >= 5, restart_sec


# ---------------------------------------------------------------------
# T-QUADLET-PERSONA-08 — health-probe contract
# ---------------------------------------------------------------------


def test_health_cmd_invokes_persona_engine_healthcheck_subcommand():
    container = _read_ini(QUADLET_CONTAINER)
    section = container["Container"]
    health_cmd = section.get("HealthCmd", "")
    assert "persona-engine" in health_cmd, health_cmd
    assert "healthcheck" in health_cmd, health_cmd


def test_health_start_period_gives_cold_start_runway():
    container = _read_ini(QUADLET_CONTAINER)
    section = container["Container"]
    start_period = section.get("HealthStartPeriod", "0s")
    assert start_period.endswith("s")
    # The persona-engine cold-start path runs V-907 hash
    # recomputation + canonical-form materialisation + SPIRE-SVID
    # fetch; <30s gives no comfortable runway.
    assert int(start_period.rstrip("s")) >= 30, start_period


# ---------------------------------------------------------------------
# T-QUADLET-PERSONA-09 — network attach
# ---------------------------------------------------------------------


def test_container_attaches_to_orchestrator_network():
    container = _read_ini(QUADLET_CONTAINER)
    section = container["Container"]
    assert section.get("Network") == "wakir-orchestrator.network"


# ---------------------------------------------------------------------
# T-QUADLET-PERSONA-10 — install target parity with siblings
# ---------------------------------------------------------------------


def test_install_section_targets_multi_user_and_default():
    container = _read_ini(QUADLET_CONTAINER)
    wanted_by = container["Install"].get("WantedBy", "")
    assert "multi-user.target" in wanted_by
    assert "default.target" in wanted_by


# ---------------------------------------------------------------------
# T-QUADLET-PERSONA-11 — workspace volume sidecar invariants
# ---------------------------------------------------------------------


def test_workspace_volume_sidecar_has_volume_section():
    volume = _read_ini(QUADLET_WORKSPACE_VOL)
    # The [Volume] section is permitted to be empty; Quadlet
    # interprets that as "use the default local driver".
    assert "Volume" in volume.sections()


def test_workspace_volume_sidecar_install_targets_match_container():
    volume = _read_ini(QUADLET_WORKSPACE_VOL)
    wanted_by = volume["Install"].get("WantedBy", "")
    assert "multi-user.target" in wanted_by
    assert "default.target" in wanted_by
