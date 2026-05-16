# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Live-VM pytest configuration.

This conftest scopes the ``--run-live-vm`` CLI flag and the
``WAKIR_LIVE_VM_ACCEPTANCE=1`` env-var gate to the ``tests/live_vm``
package only. Both must be present for any ``@pytest.mark.live_vm``
test to actually execute. In every other case the test is skipped
with a reason string so CI logs remain explicit.

Sandbox boundary
----------------

The hermetic claude-dev Sandbox cannot reach an SSH-driven Pilot-VM
(see ``feedback_sandbox_host_trennung.md``). The skip-by-default
default is therefore the *correct* CI behaviour. The on-VM
acceptance lane that these tests harden lives in
``scripts/federation-live-vm-acceptance.sh`` and is operator-hand
(Mira-Hand) triggered.

— Amara
"""

from __future__ import annotations

import os

import pytest


_RUN_FLAG = "--run-live-vm"
_ENV_VAR = "WAKIR_LIVE_VM_ACCEPTANCE"


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the ``--run-live-vm`` CLI flag.

    Defaults to False; only opt-in. The flag is intentionally
    redundant with the env-var: both must agree to switch the suite
    on. This is a belt-and-braces guard against the CI lane and the
    operator-hand lane drifting out of sync.
    """

    parser.addoption(
        _RUN_FLAG,
        action="store_true",
        default=False,
        help=(
            "Run the Live-VM acceptance suite under tests/live_vm/. "
            "Requires WAKIR_LIVE_VM_ACCEPTANCE=1 to be set in the "
            "environment in addition to this flag. Off by default."
        ),
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``live_vm`` marker so ``--strict-markers`` is happy."""

    config.addinivalue_line(
        "markers",
        (
            "live_vm: requires a live Pilot-VM target. Skipped unless "
            "both --run-live-vm and WAKIR_LIVE_VM_ACCEPTANCE=1 are set."
        ),
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip every ``@pytest.mark.live_vm`` test unless both gates open."""

    flag_set = bool(config.getoption(_RUN_FLAG))
    env_set = os.environ.get(_ENV_VAR) == "1"
    if flag_set and env_set:
        return

    if flag_set and not env_set:
        reason = (
            "live-vm suite gated: --run-live-vm passed but "
            f"{_ENV_VAR}=1 not set"
        )
    elif env_set and not flag_set:
        reason = (
            f"live-vm suite gated: {_ENV_VAR}=1 set but "
            "--run-live-vm flag not passed"
        )
    else:
        reason = (
            "live-vm suite skipped by default; pass --run-live-vm and "
            f"set {_ENV_VAR}=1 to enable"
        )

    skip_marker = pytest.mark.skip(reason=reason)
    for item in items:
        if "live_vm" in item.keywords:
            item.add_marker(skip_marker)
