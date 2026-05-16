# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Live-VM Test-Suite.

Tests in this package are SKIPPED BY DEFAULT in the hermetic Sandbox.
They run only when both the pytest CLI flag ``--run-live-vm`` is
passed and the env-var ``WAKIR_LIVE_VM_ACCEPTANCE=1`` is set. See
``test_phase_2_doppelbetrieb_live.py`` module docstring for invocation
details.
"""
