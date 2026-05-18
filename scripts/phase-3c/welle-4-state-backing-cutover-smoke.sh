#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# welle-4-state-backing-cutover-smoke.sh — Bash wrapper for the
# Phase-3c Welle-4 End-to-End Cutover-Smoke (ADR-0066 KW-26 Doppel-
# Welle, state_backing focus-component; parallel with Welle-5
# lifecycle_state_machine).
#
# The real substrate is the sibling Python script
# (welle-4-state-backing-cutover-smoke.py). This wrapper exists
# so operator-hand shell-gates and CI-step invocations can
# `bash scripts/phase-3c/welle-4-state-backing-cutover-smoke.sh ...`
# without having to know the Python interpreter path.
# All CLI flags pass through unchanged; the exit-code triad (0/1/2)
# is preserved.
#
# Cross-Modul-Drift-Mitigation reminder (ADR-0066 §Welle-4-5-Risiken):
# Welle-4 and Welle-5 run in parallel during KW-26. The smoke's A7
# assert verifies that the state_backing cutover does NOT leak into
# the fsm (lifecycle_state_machine) BackendDecision path — the fsm
# env-var stays at python in PHASE_POST and the fsm's chosen_backend
# must match. A7 failure means the parallel-Welle isolation contract
# is broken and the cutover MUST roll back.
#
# Cross-Backend-Read-Compatibility reminder: A6 verifies that the
# Python state_backing.snapshot_to_jcs_bytes encoder is byte-stable
# across the pre/post window. The baseline is captured in PHASE_PRE
# before the cutover-step constructs the PHASE_POST env-map. Do not
# modify the smoke to capture the baseline in any other phase — that
# breaks the temporal anchor that lets the Rust backend read the
# Python backend's snapshots without re-emission.
#
# Discoverable from the Welle-4 runbook
# (docs/phase-3c/welle-4-cutover-smoke.md).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="${SCRIPT_DIR}/welle-4-state-backing-cutover-smoke.py"

if [[ ! -r "${PYTHON_SCRIPT}" ]]; then
    echo "welle-4-cutover-smoke: cannot find ${PYTHON_SCRIPT}" >&2
    exit 2
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"

exec "${PYTHON_BIN}" "${PYTHON_SCRIPT}" "$@"
