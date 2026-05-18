#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# welle-5-lifecycle-state-machine-cutover-smoke.sh — Bash wrapper for
# the Phase-3c Welle-5 End-to-End Cutover-Smoke (ADR-0066 KW-26
# Doppel-Welle, lifecycle_state_machine/fsm focus-component; parallel
# with Welle-4 state_backing).
#
# The real substrate is the sibling Python script
# (welle-5-lifecycle-state-machine-cutover-smoke.py). This wrapper
# exists so operator-hand shell-gates and CI-step invocations can
# `bash scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.sh ...`
# without having to know the Python interpreter path.
# All CLI flags pass through unchanged; the exit-code triad (0/1/2)
# is preserved.
#
# Cross-Modul-Drift-Mitigation reminder (ADR-0066 §Welle-4-5-Risiken):
# Welle-4 and Welle-5 run in parallel during KW-26. The smoke's A7
# assert verifies that the fsm cutover does NOT leak into the
# state_backing BackendDecision path — the state_backing env-var
# stays at python in PHASE_POST and the state_backing's
# chosen_backend must match. A7 failure means the parallel-Welle
# isolation contract is broken and the cutover MUST roll back. A7 is
# symmetric to Welle-4's A7 (which checks the inverse leak direction).
#
# FSM-Transition-Integrity reminder: A6 verifies that the Python
# lifecycle-state-machine canonical serializer is byte-stable across
# the pre/post window AND that no phantom transitions (edges outside
# spec §3.3 VALID_TRANSITIONS) appear in the recomputed trace. The
# baseline is captured in PHASE_PRE before the cutover-step
# constructs the PHASE_POST env-map. Do not modify the smoke to
# capture the baseline in any other phase — that breaks the temporal
# anchor that lets the Rust backend read the Python backend's
# lifecycle traces without re-emission.
#
# Discoverable from the Welle-5 runbook
# (docs/phase-3c/welle-5-cutover-smoke.md).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="${SCRIPT_DIR}/welle-5-lifecycle-state-machine-cutover-smoke.py"

if [[ ! -r "${PYTHON_SCRIPT}" ]]; then
    echo "welle-5-cutover-smoke: cannot find ${PYTHON_SCRIPT}" >&2
    exit 2
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"

exec "${PYTHON_BIN}" "${PYTHON_SCRIPT}" "$@"
