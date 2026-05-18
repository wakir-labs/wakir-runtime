#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# welle-2-svid-workload-identity-cutover-smoke.sh — Bash wrapper for
# the Phase-3c Welle-2 End-to-End Cutover-Smoke (ADR-0065 + ADR-0066
# KW-24 doppel-cutover, parallel to Welle-1 v907_verify).
#
# The real substrate is the sibling Python script
# (welle-2-svid-workload-identity-cutover-smoke.py). This wrapper
# exists so operator-hand shell-gates and CI-step invocations can
# `bash scripts/phase-3c/welle-2-svid-workload-identity-cutover-
# smoke.sh ...` without having to know the Python interpreter path.
# All CLI flags pass through unchanged; the exit-code triad (0/1/2)
# is preserved.
#
# Discoverable from the Welle-2 runbook
# (docs/phase-3c/welle-2-cutover-smoke.md).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="${SCRIPT_DIR}/welle-2-svid-workload-identity-cutover-smoke.py"

if [[ ! -r "${PYTHON_SCRIPT}" ]]; then
    echo "welle-2-cutover-smoke: cannot find ${PYTHON_SCRIPT}" >&2
    exit 2
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"

exec "${PYTHON_BIN}" "${PYTHON_SCRIPT}" "$@"
