#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# welle-1-v907-verify-cutover-smoke.sh — Bash wrapper for the
# Phase-3c Welle-1 End-to-End Cutover-Smoke (ADR-0065).
#
# The real substrate is the sibling Python script
# (welle-1-v907-verify-cutover-smoke.py). This wrapper exists so
# operator-hand shell-gates and CI-step invocations can `bash
# scripts/phase-3c/welle-1-v907-verify-cutover-smoke.sh ...` without
# having to know the Python interpreter path. All CLI flags pass
# through unchanged; the exit-code triad (0/1/2) is preserved.
#
# Discoverable from the Welle-1 runbook
# (docs/phase-3c/welle-1-cutover-smoke.md).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="${SCRIPT_DIR}/welle-1-v907-verify-cutover-smoke.py"

if [[ ! -r "${PYTHON_SCRIPT}" ]]; then
    echo "welle-1-cutover-smoke: cannot find ${PYTHON_SCRIPT}" >&2
    exit 2
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"

exec "${PYTHON_BIN}" "${PYTHON_SCRIPT}" "$@"
