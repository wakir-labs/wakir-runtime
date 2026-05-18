#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# welle-7-recovery-workflow-cutover-smoke.sh — Bash wrapper for the
# Phase-3c Welle-7 End-to-End Cutover-Smoke (ADR-0066 KW-27 Doppel-
# Welle, recovery_workflow / recovery focus-component; parallel
# with Welle-6 subscribe_loop, Phase-3-Ende).
#
# The real substrate is the sibling Python script
# (welle-7-recovery-workflow-cutover-smoke.py). This wrapper exists
# so operator-hand shell-gates and CI-step invocations can
# `bash scripts/phase-3c/welle-7-recovery-workflow-cutover-smoke.sh ...`
# without having to know the Python interpreter path.
# All CLI flags pass through unchanged; the exit-code triad (0/1/2)
# is preserved.
#
# Cross-Modul-Drift-Mitigation reminder (ADR-0066 §Welle-6-7-Risiken):
# Welle-7 and Welle-6 run in parallel during KW-27 (the final
# Doppel-Welle of Phase-3, Phase-3-Ende). The smoke's A7 assert
# verifies that the recovery cutover does NOT leak into the
# subscribe_loop BackendDecision path — the subscribe_loop env-var
# stays at python in PHASE_POST and the subscribe_loop's
# chosen_backend must match. A7 failure means the parallel-Welle
# isolation contract is broken and the cutover MUST roll back. A7
# is symmetric to Welle-6's A7 (which checks the inverse leak
# direction).
#
# Recovery-R1..R4-Drill reminder: A6 verifies that the Python
# RecoveryOutcome canonical serializer is byte-stable across the
# pre/post window AND that the recomputed outcome preserves the
# spec §3.7.4 phase ordering (R1 -> R2 -> R3 -> R4). The baseline
# is captured in PHASE_PRE before the cutover-step constructs the
# PHASE_POST env-map.
#
# State-Backing-Awareness reminder: the smoke's env-map pins
# WAKIR_STATE_BACKING_BACKEND=rust in every phase to reflect the
# post-KW-26 production state (Welle-4 already cutovert). The
# Welle-7 cutover must NOT be started before state_backing is
# stable on Rust-default.
#
# FSM-Awareness reminder: the smoke's env-map also pins
# WAKIR_FSM_BACKEND=rust in every phase (Welle-5 already cutovert
# in KW-26).
#
# Discoverable from the Welle-7 runbook
# (docs/phase-3c/welle-7-cutover-smoke.md).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="${SCRIPT_DIR}/welle-7-recovery-workflow-cutover-smoke.py"

if [[ ! -r "${PYTHON_SCRIPT}" ]]; then
    echo "welle-7-cutover-smoke: cannot find ${PYTHON_SCRIPT}" >&2
    exit 2
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"

exec "${PYTHON_BIN}" "${PYTHON_SCRIPT}" "$@"
