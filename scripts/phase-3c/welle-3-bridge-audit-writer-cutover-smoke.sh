#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# welle-3-bridge-audit-writer-cutover-smoke.sh — Bash wrapper for the
# Phase-3c Welle-3 End-to-End Cutover-Smoke (ADR-0066 KW-25 solo
# wave, bridge_audit_writer focus-component).
#
# The real substrate is the sibling Python script
# (welle-3-bridge-audit-writer-cutover-smoke.py). This wrapper exists
# so operator-hand shell-gates and CI-step invocations can
# `bash scripts/phase-3c/welle-3-bridge-audit-writer-cutover-
# smoke.sh ...` without having to know the Python interpreter path.
# All CLI flags pass through unchanged; the exit-code triad (0/1/2)
# is preserved.
#
# Self-Reference-Trap-Mitigation reminder (per ADR-0066 §Welle-3-
# Risiken): the smoke captures the bridge-audit-stream baseline
# in the PRE_CUTOVER phase *before* the cutover-step constructs the
# POST_CUTOVER env-map. The A7 assert verifies the temporal
# invariant on every run. Do not modify the smoke to capture the
# baseline in any other phase — that re-introduces the
# Consistency-Oracle-Selbst-Cutover-Risiko Henrik flagged.
#
# Discoverable from the Welle-3 runbook
# (docs/phase-3c/welle-3-cutover-smoke.md).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="${SCRIPT_DIR}/welle-3-bridge-audit-writer-cutover-smoke.py"

if [[ ! -r "${PYTHON_SCRIPT}" ]]; then
    echo "welle-3-cutover-smoke: cannot find ${PYTHON_SCRIPT}" >&2
    exit 2
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"

exec "${PYTHON_BIN}" "${PYTHON_SCRIPT}" "$@"
