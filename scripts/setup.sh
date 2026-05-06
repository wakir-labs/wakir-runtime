#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Initial setup script for a development checkout.
#
# What it does
# ------------
#
# 1. Verifies Python >= 3.11 is available.
# 2. Creates a project-local venv at .venv (idempotent).
# 3. Installs this project in editable mode with test extras.
# 4. Verifies the `ots` CLI from opentimestamps-client is on PATH
#    (we shell out to it from wat.anchor.ots_anchor).
#
# Why a hand-rolled bash setup rather than a Makefile or tox: it's
# the smallest thing that works on a stock Linux box without extra
# tooling, and it documents the invariants in plain prose.

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

log()  { printf '[setup] %s\n' "$*"; }
fail() { printf '[setup] ERROR: %s\n' "$*" >&2; exit 1; }

# --- 1. Python version check.
if ! command -v python3 >/dev/null 2>&1; then
    fail "python3 not found on PATH."
fi
PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
PY_MAJOR="${PY_VER%%.*}"
PY_MINOR="${PY_VER##*.}"
if (( PY_MAJOR < 3 )) || { (( PY_MAJOR == 3 )) && (( PY_MINOR < 11 )); }; then
    fail "Python >= 3.11 required, found ${PY_VER}."
fi
log "python3 ${PY_VER} ok."

# --- 2. venv.
if [[ ! -d ".venv" ]]; then
    log "creating .venv ..."
    python3 -m venv .venv
else
    log ".venv already exists, reusing."
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# --- 3. editable install with test extras.
log "upgrading pip..."
python -m pip install --upgrade pip >/dev/null

log "installing wakir-runtime in editable mode (with [test])..."
python -m pip install -e ".[test]"

# --- 4. opentimestamps-client / ots CLI check.
if ! command -v ots >/dev/null 2>&1; then
    cat >&2 <<'EOF'
[setup] WARNING: ots CLI not on PATH after install.

The wat.anchor.ots_anchor module shells out to `ots` from
opentimestamps-client. Install it into this venv with:

    pip install opentimestamps-client

or place the binary on your global PATH. Without it, anchor_root /
upgrade_pending / verify_receipt will raise AnchorError at runtime.
The unit tests stub the subprocess call and pass without ots.
EOF
else
    OTS_PATH="$(command -v ots)"
    log "ots CLI ok at ${OTS_PATH}"
fi

log "setup complete. activate with: source .venv/bin/activate"
