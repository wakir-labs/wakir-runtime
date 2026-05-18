#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# welle-6-subscribe-loop-cutover-smoke.sh — Bash wrapper for the
# Phase-3c Welle-6 End-to-End Cutover-Smoke (ADR-0066 KW-27 Doppel-
# Welle, subscribe_loop focus-component; parallel with Welle-7
# recovery_workflow).
#
# The real substrate is the sibling Python script
# (welle-6-subscribe-loop-cutover-smoke.py). This wrapper exists so
# operator-hand shell-gates and CI-step invocations can
# `bash scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.sh ...`
# without having to know the Python interpreter path.
# All CLI flags pass through unchanged; the exit-code triad (0/1/2)
# is preserved.
#
# Cross-Modul-Drift-Mitigation reminder (ADR-0066 §Welle-6-7-Risiken):
# Welle-6 and Welle-7 run in parallel during KW-27 (the final
# Doppel-Welle of Phase-3). The smoke's A7 assert verifies that the
# subscribe_loop cutover does NOT leak into the recovery
# BackendDecision path — the recovery env-var stays at python in
# PHASE_POST and the recovery's chosen_backend must match. A7
# failure means the parallel-Welle isolation contract is broken
# and the cutover MUST roll back. A7 is symmetric to Welle-7's A7
# (which checks the inverse leak direction).
#
# Subscribe-Loop-Lag-Stability reminder: A6 verifies that the
# Python subscribe-ack canonical serializer is byte-stable across
# the pre/post window AND that the synthetic lag-distribution
# mean+P95 stay within a 25% drift envelope. The baseline is
# captured in PHASE_PRE before the cutover-step constructs the
# PHASE_POST env-map.
#
# FSM-Awareness reminder: the smoke's env-map pins
# WAKIR_FSM_BACKEND=rust in every phase to reflect the post-KW-26
# production state (Welle-5 already cutovert). The Welle-6 cutover
# must NOT be started or stopped inside an FSM-cutover-window.
#
# Discoverable from the Welle-6 runbook
# (docs/phase-3c/welle-6-cutover-smoke.md).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="${SCRIPT_DIR}/welle-6-subscribe-loop-cutover-smoke.py"

if [[ ! -r "${PYTHON_SCRIPT}" ]]; then
    echo "welle-6-cutover-smoke: cannot find ${PYTHON_SCRIPT}" >&2
    exit 2
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"

exec "${PYTHON_BIN}" "${PYTHON_SCRIPT}" "$@"
