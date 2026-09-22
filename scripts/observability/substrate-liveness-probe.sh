#!/usr/bin/env bash
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Substrate liveness probe — does this SPIRE agent still attest?
#
# Why this exists
# ---------------
#
# Measured read-only on both live VMs on 2026-09-22, ~08:15-08:19 UTC:
#
#   * the SPIRE agent container reported ``Up`` continuously while
#     never attesting once since May;
#   * ``podman inspect .RestartCount`` read ``0`` although systemd
#     recreated the container every few seconds;
#   * the workload-API socket file ``api.sock`` was present in the
#     volume, dated May, with no process listening on it;
#   * the persisted agent SVID had ``notAfter = 2026-05-15T08:32:35Z``
#     on one node and ``2026-05-17T04:59:19Z`` on the other.
#
# Every cheap "is it running" signal was true and worthless. The one
# unambiguous signal is the expiry of the credential the agent
# persisted the last time it successfully attested. This probe reads
# exactly that: offline, read-only, from the agent's own state file.
#
# What it reads
# -------------
#
# ``<agent data_dir>/agent-data.json``, the SPIRE agent's persisted
# state. Two fields are load-bearing:
#
#   ``.svid``    base64-wrapped PEM chain of the agent SVID. Its
#                ``notAfter`` is the hard end of the last successful
#                attestation. Measured span notBefore..notAfter is
#                1h00m10s, consistent with the server's measured
#                ``default_x509_svid_ttl = "1h"``.
#   ``.bundle``  base64-wrapped PEM trust bundle as cached by the
#                agent. Its newest ``notAfter`` is the point past
#                which the agent can no longer verify the server —
#                the point of no return without operator action.
#
# The file's mtime is read as an independent second opinion. It is
# NOT the primary signal: ``keys.json`` in the same directory was
# rewritten on 2026-09-21 by a bootstrap re-run while
# ``agent-data.json`` stayed at its May timestamp. Watching the
# directory, or the wrong file in it, would have reported freshness.
#
# What it deliberately does NOT read
# ----------------------------------
#
#   * container state / ``Up`` duration          — true for four months
#   * ``podman inspect .RestartCount``           — read 0 under a
#                                                  systemd restart loop
#   * existence of the workload-API socket file  — stale inode present
#   * the SPIFFE ID in the SVID's SAN            — it embeds the
#                                                  join-token UUID and
#                                                  must not leave the node
#
# Dependencies
# ------------
#
# bash, openssl, base64, stat, date, sed, tr. Nothing else — in
# particular no jq and no python. Both nodes run Fedora CoreOS 44 and
# have **no python3 at all** (measured 2026-09-22); the repo's existing
# systemd health units invoke ``/opt/wakir-runtime/.venv/bin/python3``,
# which does not exist on either node. A probe whose job is to notice
# that something is not running must not itself be unable to run.
#
# The JSON reader below is a narrow extractor for a known file shape,
# not a general JSON parser. The shape is asserted: if ``"svid"`` is
# absent from the file the verdict is ``unmeasurable``, never green.
#
# Output contract
# ---------------
#
# One JSON object on stdout. Exit code:
#
#   0  verdict "green"        — SVID and bundle valid, state fresh
#   1  verdict "red"          — measured, and it is bad
#   2  verdict "unmeasurable" — could not measure
#
# Exit 2 is deliberately NOT exit 0. A probe that cannot measure must
# not report green; that is the defect class this probe answers.
#
# The payload carries no hostname, no IP, no SPIFFE ID and no key
# material. The node is identified by an opaque label supplied by the
# caller so the payload can travel over a push channel without
# disclosing topology.
#
# Environment
# -----------
#
#   WAKIR_AGENT_DATA_FILE  path to agent-data.json. When set, podman is
#                          never invoked — this is what makes the probe
#                          hermetically testable.
#   WAKIR_SIDE             federation side; only used to derive the
#                          default volume name when the path is unset.
#   WAKIR_NODE_LABEL       opaque node pseudonym. Default
#                          "node-unlabelled". Sanitised to
#                          [A-Za-z0-9._-].
#   WAKIR_SVID_TTL_SECONDS SVID lifetime, default 3600 (measured).
#   WAKIR_GRACE_SECONDS    how long an expired credential is tolerated
#                          before the verdict turns red. Default 3600,
#                          i.e. one full TTL.
#   WAKIR_STATE_MAX_AGE_SECONDS
#                          max tolerated age of the state file.
#                          Default 21600 (6 h).
#   WAKIR_NOW_EPOCH        override for "now", for tests.

set -uo pipefail

SCHEMA="wakir.substrate-liveness/v1"

RAW_LABEL="${WAKIR_NODE_LABEL:-node-unlabelled}"
NODE_LABEL="$(printf '%s' "${RAW_LABEL}" | tr -c 'A-Za-z0-9._-' '_')"
[[ -z "${NODE_LABEL}" ]] && NODE_LABEL="node-unlabelled"

SVID_TTL_SECONDS="${WAKIR_SVID_TTL_SECONDS:-3600}"
GRACE_SECONDS="${WAKIR_GRACE_SECONDS:-3600}"
STATE_MAX_AGE_SECONDS="${WAKIR_STATE_MAX_AGE_SECONDS:-21600}"

if [[ -n "${WAKIR_NOW_EPOCH:-}" ]]; then
    NOW="${WAKIR_NOW_EPOCH}"
else
    NOW="$(date -u +%s)"
fi

# Measurements. Empty string means "not measured"; it is rendered as
# JSON null so a consumer can tell "measured as absent" from "this
# probe version did not look".
M_SVID_NOT_AFTER=""
M_SVID_EXPIRED_FOR=""
M_BUNDLE_NOT_AFTER=""
M_BUNDLE_EXPIRED_FOR=""
M_BUNDLE_COUNT=""
M_STATE_MTIME=""
M_STATE_AGE=""

json_num() { if [[ -z "$1" ]]; then printf 'null'; else printf '%s' "$1"; fi; }

# emit <verdict> <reason>
#
# All string values are either constants from this file or the
# sanitised node label, so no escaping is required and none is faked.
emit() {
    local verdict="$1" reason="$2" observed_at
    observed_at="$(date -u -d "@${NOW}" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || printf '')"
    printf '{'
    printf '"schema":"%s",' "${SCHEMA}"
    printf '"node":"%s",' "${NODE_LABEL}"
    printf '"observed_at_epoch":%s,' "$(json_num "${NOW}")"
    printf '"observed_at":"%s",' "${observed_at}"
    printf '"verdict":"%s",' "${verdict}"
    printf '"reason":"%s",' "${reason}"
    printf '"svid_ttl_seconds":%s,' "$(json_num "${SVID_TTL_SECONDS}")"
    printf '"grace_seconds":%s,' "$(json_num "${GRACE_SECONDS}")"
    printf '"state_max_age_seconds":%s,' "$(json_num "${STATE_MAX_AGE_SECONDS}")"
    printf '"svid_not_after_epoch":%s,' "$(json_num "${M_SVID_NOT_AFTER}")"
    printf '"svid_expired_for_seconds":%s,' "$(json_num "${M_SVID_EXPIRED_FOR}")"
    printf '"bundle_newest_not_after_epoch":%s,' "$(json_num "${M_BUNDLE_NOT_AFTER}")"
    printf '"bundle_expired_for_seconds":%s,' "$(json_num "${M_BUNDLE_EXPIRED_FOR}")"
    printf '"bundle_cert_count":%s,' "$(json_num "${M_BUNDLE_COUNT}")"
    printf '"state_mtime_epoch":%s,' "$(json_num "${M_STATE_MTIME}")"
    printf '"state_age_seconds":%s' "$(json_num "${M_STATE_AGE}")"
    printf '}\n'
    case "${verdict}" in
        green) exit 0 ;;
        red) exit 1 ;;
        *) exit 2 ;;
    esac
}

# A probe that cannot run must say so in the same shape it says
# everything else, and it must never be mistaken for a negative
# verdict. The container healthchecks on this substrate are the
# counter-example: measured 2026-09-22 08:32 UTC, the SPIRE server's
# healthcheck has been producing ``ExitCode 1, Output ""`` every ten
# seconds since May, because podman wraps a string ``HealthCmd`` in
# ``/bin/sh -c`` and the SPIRE image has no shell. The container has
# read ``unhealthy`` for four months while the same command run
# directly answers ``Server is healthy.`` — a check that never started,
# published as a judgement. Empty output is not a finding.
for tool in date openssl base64 stat tr sed; do
    command -v "${tool}" >/dev/null 2>&1 || emit unmeasurable "missing_tool_${tool}"
done

# --- locate the state file -------------------------------------------
STATE_FILE="${WAKIR_AGENT_DATA_FILE:-}"
if [[ -z "${STATE_FILE}" ]]; then
    side="${WAKIR_SIDE:-}"
    [[ -z "${side}" ]] && emit unmeasurable no_state_file_and_no_side
    command -v podman >/dev/null 2>&1 || emit unmeasurable podman_absent
    mountpoint="$(podman volume inspect "wakir-spire-agent-${side}-data" \
        --format '{{.Mountpoint}}' 2>/dev/null)"
    [[ -z "${mountpoint}" ]] && emit unmeasurable agent_data_volume_absent
    STATE_FILE="${mountpoint}/agent-data.json"
fi

[[ -f "${STATE_FILE}" ]] || emit red state_missing
[[ -r "${STATE_FILE}" ]] || emit unmeasurable state_unreadable

M_STATE_MTIME="$(stat -c %Y "${STATE_FILE}" 2>/dev/null)"
[[ -z "${M_STATE_MTIME}" ]] && emit unmeasurable state_mtime_unreadable
M_STATE_AGE=$(( NOW - M_STATE_MTIME ))

# --- read the state file ----------------------------------------------
#
# Whitespace is stripped first so the extractor works on both the
# compact form SPIRE writes and a pretty-printed one. Every value in
# this file is base64, a number, a boolean or an RFC-3339 timestamp —
# none of them contain significant whitespace.
STATE_FLAT="$(tr -d ' \t\n\r' < "${STATE_FILE}" 2>/dev/null)"
[[ -z "${STATE_FLAT}" ]] && emit unmeasurable state_empty
case "${STATE_FLAT}" in
    *'"svid"'*) : ;;
    *) emit unmeasurable state_unparseable ;;
esac

# array_items <key> — one base64 blob per line.
array_items() {
    printf '%s' "${STATE_FLAT}" \
        | sed -n 's/.*"'"$1"'":\[\([^]]*\)\].*/\1/p' \
        | tr ',' '\n' \
        | sed -e 's/^"//' -e 's/"$//' \
        | sed '/^$/d'
}

# not_after_epoch — PEM on stdin, unix epoch on stdout.
not_after_epoch() {
    local end
    end="$(openssl x509 -noout -enddate 2>/dev/null | sed 's/^notAfter=//')"
    [[ -z "${end}" ]] && return 1
    date -u -d "${end}" +%s 2>/dev/null
}

# --- agent SVID -------------------------------------------------------
svid_b64="$(array_items svid | head -n 1)"
[[ -z "${svid_b64}" ]] && emit red svid_absent

M_SVID_NOT_AFTER="$(printf '%s' "${svid_b64}" | base64 -d 2>/dev/null | not_after_epoch)"
[[ -z "${M_SVID_NOT_AFTER}" ]] && emit unmeasurable svid_undecodable

M_SVID_EXPIRED_FOR=$(( NOW - M_SVID_NOT_AFTER ))
(( M_SVID_EXPIRED_FOR < 0 )) && M_SVID_EXPIRED_FOR=0

# --- cached trust bundle ----------------------------------------------
M_BUNDLE_COUNT=0
newest=""
# The ``|| [[ -n ... ]]`` guard is load-bearing: the extractor's last
# item carries no trailing newline, and a plain ``read`` loop silently
# drops it. On a single-entry bundle that means dropping everything.
while IFS= read -r cert_b64 || [[ -n "${cert_b64}" ]]; do
    [[ -z "${cert_b64}" ]] && continue
    M_BUNDLE_COUNT=$(( M_BUNDLE_COUNT + 1 ))
    e="$(printf '%s' "${cert_b64}" | base64 -d 2>/dev/null | not_after_epoch)"
    [[ -z "${e}" ]] && continue
    if [[ -z "${newest}" ]] || (( e > newest )); then
        newest="${e}"
    fi
done < <(array_items bundle)

[[ -z "${newest}" ]] && emit red bundle_absent

M_BUNDLE_NOT_AFTER="${newest}"
M_BUNDLE_EXPIRED_FOR=$(( NOW - M_BUNDLE_NOT_AFTER ))
(( M_BUNDLE_EXPIRED_FOR < 0 )) && M_BUNDLE_EXPIRED_FOR=0

# --- verdict ----------------------------------------------------------
#
# Order matters. The bundle is reported before the SVID because an
# expired bundle is the condition the agent cannot recover from on its
# own, while an expired SVID alone can still be renewed.
(( M_BUNDLE_EXPIRED_FOR > GRACE_SECONDS )) && emit red bundle_expired
(( M_SVID_EXPIRED_FOR > GRACE_SECONDS )) && emit red svid_expired
(( M_STATE_AGE > STATE_MAX_AGE_SECONDS )) && emit red state_stale

emit green ok
