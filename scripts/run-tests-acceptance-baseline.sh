#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Phase-2 Sprint-6 Tag-4 — Acceptance-baseline test wrapper.
#
# Convention: no-PATH-prepend is the acceptance-reference form for
# every wakir-runtime outbox test-progression stamp. This wrapper
# enforces that form by stripping any directory ending in
# ``/.venv/bin`` from the inherited PATH before invoking pytest. The
# result is environment-independent: whether the caller has
# source-activated the venv or not, the test counts the wrapper
# produces match the documented acceptance-reference.
#
# See ``docs/test-counts-convention.md`` for the full convention.
#
# Usage:
#
#   scripts/run-tests-acceptance-baseline.sh                   # full suite
#   scripts/run-tests-acceptance-baseline.sh tests/orchestrator/  # subset
#   scripts/run-tests-acceptance-baseline.sh -v -k <pattern>   # filtered

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${REPO_ROOT}/.venv"

if [[ ! -x "${VENV}/bin/python" ]]; then
  echo "scripts/run-tests-acceptance-baseline.sh: venv not present at ${VENV}" >&2
  echo "  hint: bootstrap with 'python -m venv .venv && .venv/bin/pip install -e .'" >&2
  exit 1
fi

# Strip any */.venv/bin from PATH so source-activated callers still
# produce no-PATH-prepend results.
CLEAN_PATH=""
IFS=':' read -ra _entries <<< "${PATH:-}"
for _e in "${_entries[@]}"; do
  case "${_e}" in
    */.venv/bin) ;;     # drop
    "") ;;              # drop empty entries
    *) CLEAN_PATH="${CLEAN_PATH:+${CLEAN_PATH}:}${_e}" ;;
  esac
done

# Invoke pytest with the cleaned PATH; preserve all caller args.
exec env PATH="${CLEAN_PATH}" "${VENV}/bin/python" -m pytest "$@"
