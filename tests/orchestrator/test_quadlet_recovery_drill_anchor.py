# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Hermetic Quadlet-unit invariant tests for the Sprint-Pengine-7
# Tag-5 OI-PILOT-4 recovery-drill WAT-anchor oneshot + its sister
# timer unit (Cross-Pair Reza OI-PEF-11).

from __future__ import annotations

import configparser
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
QUADLET_DIR = REPO_ROOT / "quadlet"
QUADLET_CONTAINER = QUADLET_DIR / "wakir-recovery-drill-anchor.container"
QUADLET_TIMER = QUADLET_DIR / "wakir-recovery-drill-anchor.timer"


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
# Container unit tests
# ---------------------------------------------------------------------


def test_quadlet_files_exist():
    assert QUADLET_CONTAINER.exists(), QUADLET_CONTAINER
    assert QUADLET_TIMER.exists(), QUADLET_TIMER


def test_container_unit_is_oneshot_with_no_remain_after_exit():
    container = _read_ini(QUADLET_CONTAINER)
    service = container["Service"]
    assert service.get("Type") == "oneshot"
    assert service.get("RemainAfterExit") == "no"


def test_container_unit_after_chain_includes_nats():
    flat = " ".join(_section_lines(QUADLET_CONTAINER, "Unit", "After"))
    assert "wakir-nats.service" in flat
    assert "network-online.target" in flat


def test_container_unit_requires_nats_hard():
    flat = " ".join(_section_lines(QUADLET_CONTAINER, "Unit", "Requires"))
    assert "wakir-nats.service" in flat


def test_container_exec_invokes_recovery_drill_anchor_with_bucket_arg():
    # Quadlet permits line-continuations via trailing backslash;
    # we re-scan the raw file text instead of the section-helper
    # which only sees the first line. The continuation block
    # carries the flags --bucket --spool-root --activity-log.
    text = QUADLET_CONTAINER.read_text(encoding="utf-8")
    assert "wakir-recovery-drill-anchor" in text
    assert "--bucket" in text
    assert "--spool-root" in text
    assert "--activity-log" in text


def test_container_section_carries_full_hardening_set():
    container = _read_ini(QUADLET_CONTAINER)
    section = container["Container"]
    assert section.get("ReadOnly") == "true"
    assert section.get("DropCapability") == "ALL"
    assert section.get("NoNewPrivileges") == "true"
    assert section.get("User") == "1000"
    assert section.get("Group") == "1000"


def test_container_attaches_to_orchestrator_network():
    container = _read_ini(QUADLET_CONTAINER)
    assert container["Container"].get("Network") == "wakir-orchestrator.network"


def test_container_env_file_points_at_operator_managed_path():
    container = _read_ini(QUADLET_CONTAINER)
    env_file = container["Container"].get("EnvironmentFile", "")
    assert env_file == "/etc/wakir/recovery-drill-anchor.env"


def test_container_volume_mounts_carry_z_flag():
    volumes = _section_lines(QUADLET_CONTAINER, "Container", "Volume")
    # Every Volume= line carries the SELinux Z (relabel-private)
    # flag per Bug-20 substance-fix discipline.
    for v in volumes:
        flags = v.split(":")[-1].split(",")
        assert "Z" in flags, v


def test_container_timeout_gives_cold_start_runway():
    container = _read_ini(QUADLET_CONTAINER)
    service = container["Service"]
    timeout = service.get("TimeoutStartSec", "0s")
    assert timeout.endswith("s")
    # 300s parity with the bucket-init oneshot (image-pull on cold
    # bring-up). 60s is too short.
    assert int(timeout.rstrip("s")) >= 120, timeout


# ---------------------------------------------------------------------
# Timer unit tests
# ---------------------------------------------------------------------


def test_timer_unit_parses_as_ini_and_carries_required_sections():
    timer = _read_ini(QUADLET_TIMER)
    assert "Unit" in timer.sections()
    assert "Timer" in timer.sections()
    assert "Install" in timer.sections()


def test_timer_fires_after_boot_and_periodically():
    timer = _read_ini(QUADLET_TIMER)
    timer_section = timer["Timer"]
    on_boot = timer_section.get("OnBootSec", "")
    on_active = timer_section.get("OnUnitActiveSec", "")
    assert on_boot, "OnBootSec must be set"
    assert on_active, "OnUnitActiveSec must be set"
    # The cadence MUST be at most 60 minutes during pilot phase
    # (the WAT hourly aggregator runs at minute 0; the anchoring
    # MUST complete before that, so a 15-30 min cadence is
    # operationally sensible). Reject ≥ 60 minutes.
    assert on_active.endswith("min") or on_active.endswith("s"), on_active
    if on_active.endswith("min"):
        minutes = int(on_active.rstrip("min"))
    else:
        minutes = int(on_active.rstrip("s")) // 60
    assert minutes < 60, on_active


def test_timer_unit_targets_the_anchor_service():
    timer = _read_ini(QUADLET_TIMER)
    unit = timer["Timer"].get("Unit", "")
    assert unit == "wakir-recovery-drill-anchor.service"


def test_timer_unit_is_persistent_for_missed_ticks():
    timer = _read_ini(QUADLET_TIMER)
    assert timer["Timer"].get("Persistent") == "true"


def test_timer_install_targets_timers_target():
    timer = _read_ini(QUADLET_TIMER)
    assert timer["Install"].get("WantedBy") == "timers.target"
