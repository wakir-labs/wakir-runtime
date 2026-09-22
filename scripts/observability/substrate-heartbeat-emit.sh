#!/usr/bin/env bash
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Substrate heartbeat emitter — push the probe's verdict out of the LAN.
#
# Runs on the substrate node next to
# ``scripts/observability/substrate-liveness-probe.sh``, and is read by
# ``scripts/observability/substrate-liveness-window.py`` on the other
# side of the network boundary.
#
# Direction, and why
# ------------------
#
# Outbound HTTPS works from both nodes (measured 2026-09-22: the broker
# answers 200). Inbound does not exist, and three named live-evidence
# lanes died on assuming otherwise. So the node speaks and the outside
# listens, never the reverse. Nothing here opens a port, holds a GitHub
# token, or grants anyone a way in.
#
# The heartbeat is the liveness signal; the verdict is its content
# -----------------------------------------------------------------
#
# This script sends **whatever the probe said**, including ``red`` and
# ``unmeasurable``, and exits 0 when the send succeeded. It is not the
# emitter's job to decide whether the news is worth telling. Suppressing
# bad news here would mean silence carried two meanings — "all well" and
# "badly broken" — which is precisely the ambiguity that let a dead
# substrate look like a running one for four months.
#
# So: heartbeat present and green    -> the node is alive and attesting
#     heartbeat present and not green -> the node is alive and honest
#     no heartbeat                    -> the window closes and somebody is told
#
# Authenticity is not optional
# ----------------------------
#
# Anyone who learns the topic can post to it. Without a signature they
# could post a forged ``green`` and switch the alarm off from the
# outside. Every message carries an HMAC-SHA256 over the exact probe
# bytes, and the evaluator discards anything that does not verify before
# it looks at the contents.
#
# The key is read from a file by preference. A key passed in the
# environment is visible in ``/proc``; a key on argv would be visible in
# the process table to every user on the host.
#
# Confidentiality
# ---------------
#
# The transmitted payload is the probe's output verbatim. That output is
# pinned by a test to carry no address, no hostname, no SPIFFE ID and no
# key material — the node is an opaque label. Nothing is added here. The
# message carries no title and minimum priority, because the heartbeat
# topic is polled by a scheduled job, not subscribed to by a human; an
# alarm that pushes ninety-six times a day to somebody's phone is an
# alarm that gets muted.
#
# Wire format
# -----------
#
#     wakir-hb1 <hmac-sha256-hex> <base64(probe-json)>
#
# Three space-separated fields, deliberately flat: this host has no
# python and no jq, so anything needing a JSON encoder on the sending
# side would have been a dependency in the one place that cannot carry
# one.
#
# Exit codes
# ----------
#
#     0  heartbeat built and sent
#     1  built, but could not be sent
#     2  could not be built at all (no key, no topic, no probe output)
#
# Requires: bash, openssl, base64, curl. All measured present on
# Fedora CoreOS 44 on both nodes, 2026-09-22.
#
# Environment
# -----------
#
#   WAKIR_HMAC_KEY_FILE        path to the shared key. Preferred.
#   WAKIR_HEARTBEAT_HMAC_KEY   the key itself. Fallback.
#   WAKIR_NTFY_TOPIC           topic to post to.
#   WAKIR_NTFY_BASE            broker base URL. Default https://ntfy.sh
#   WAKIR_PROBE_CMD            probe command. Default: the probe next to
#                              this script. Injectable, which is what
#                              makes this hermetically testable.
#   WAKIR_POST_CMD             when set, the message is piped to this
#                              command instead of curl. Tests use it so
#                              that no test touches the network.
#   WAKIR_SIDE, WAKIR_NODE_LABEL, ... are passed through to the probe.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROBE_CMD="${WAKIR_PROBE_CMD:-${HERE}/substrate-liveness-probe.sh}"
NTFY_BASE="${WAKIR_NTFY_BASE:-https://ntfy.sh}"

fail() { echo "[heartbeat-emit] $1" >&2; exit "$2"; }

for tool in openssl base64; do
    command -v "${tool}" >/dev/null 2>&1 || fail "missing tool: ${tool}" 2
done

# --- key ---------------------------------------------------------------
KEY=""
if [[ -n "${WAKIR_HMAC_KEY_FILE:-}" ]]; then
    [[ -r "${WAKIR_HMAC_KEY_FILE}" ]] || fail "key file not readable" 2
    KEY="$(cat "${WAKIR_HMAC_KEY_FILE}")"
else
    KEY="${WAKIR_HEARTBEAT_HMAC_KEY:-}"
fi
# Trailing newlines are the classic way for a key file and an
# environment variable to disagree about the same secret.
KEY="${KEY%$'\n'}"
[[ -n "${KEY}" ]] || fail "no HMAC key (WAKIR_HMAC_KEY_FILE or WAKIR_HEARTBEAT_HMAC_KEY)" 2

# --- probe -------------------------------------------------------------
#
# The probe's exit code is deliberately not checked. 0, 1 and 2 are all
# things worth telling; only an empty answer is not sendable.
PAYLOAD="$(${PROBE_CMD} 2>/dev/null)"
[[ -n "${PAYLOAD}" ]] || fail "probe produced no output — nothing to attest to" 2

# --- sign --------------------------------------------------------------
MAC="$(printf '%s' "${PAYLOAD}" \
    | openssl dgst -sha256 -hmac "${KEY}" 2>/dev/null \
    | awk '{print $NF}')"
[[ -n "${MAC}" ]] || fail "could not compute HMAC" 2

B64="$(printf '%s' "${PAYLOAD}" | base64 | tr -d '\n')"
[[ -n "${B64}" ]] || fail "could not encode payload" 2

MESSAGE="wakir-hb1 ${MAC} ${B64}"

# --- send --------------------------------------------------------------
if [[ -n "${WAKIR_POST_CMD:-}" ]]; then
    printf '%s\n' "${MESSAGE}" | ${WAKIR_POST_CMD} || fail "post command failed" 1
    echo "[heartbeat-emit] sent via WAKIR_POST_CMD"
    exit 0
fi

command -v curl >/dev/null 2>&1 || fail "missing tool: curl" 2
TOPIC="${WAKIR_NTFY_TOPIC:-}"
[[ -n "${TOPIC}" ]] || fail "WAKIR_NTFY_TOPIC is unset" 2

if ! printf '%s' "${MESSAGE}" | curl -fsS --max-time 20 \
        -H "Priority: min" \
        -H "X-Title: " \
        --data-binary @- \
        "${NTFY_BASE%/}/${TOPIC}" >/dev/null 2>&1; then
    fail "could not post the heartbeat" 1
fi

echo "[heartbeat-emit] sent"
exit 0
