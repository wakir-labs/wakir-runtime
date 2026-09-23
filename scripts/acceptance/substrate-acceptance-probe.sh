#!/usr/bin/env bash
# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Hourly sample for the ADR-0076 seven-day acceptance window.
#
# What this is, and what it is deliberately not
# ---------------------------------------------
#
# This script SAMPLES. It does not judge. One invocation writes one
# line of measured facts to a sample log; the verdict is computed
# afterwards, off the node, by
# ``scripts/acceptance/substrate_acceptance_window.py``.
#
# The split is not tidiness. ADR-0076's acceptance turns on the
# difference between *running* and *still running out of the cache*,
# and that difference is not readable from any single state -- only
# from movement between states. A probe that emitted a verdict per run
# would have to answer, once an hour, a question that only the series
# can answer. It would answer it from the one sample it has, and the
# answer would look like the May evidence: true at the moment it was
# taken and worthless.
#
# There is a second reason, and it is the binding one. The record this
# script writes carries **no verdict field at all**, and the reader
# refuses a record that carries one. The judgement is computed from
# measured values every time it is needed. Reading a verdict off a flag
# written by the thing under observation is the defect class this house
# found twice on 2026-09-22 (PR #560, then its own review).
#
# What it measures -- ADR-0076 "Abnahme", CTO decision paper §6.1
# --------------------------------------------------------------
#
#   1. the current X509-SVID from the Workload API: not-before,
#      not-after, and the identity of the authority that issued it,
#      taken from the chain;
#   2. the set of authorities the SPIRE **server** currently holds
#      (``spire-server bundle show -format spiffe``);
#   3. the mtime of ``agent-data.json`` in the agent's data volume --
#      the number that stood still for four months;
#   4. the staged bootstrap anchor in the bundles volume: presence,
#      size, mtime and the authority set inside it.
#
# (4) is not in §6.1. It is here because ADR-0076's own risk section
# says the re-staging timer "muss Teil der Sonde aus der Abnahme sein,
# sonst wiederholt sich die Klasse", and because the mandatory negative
# control -- an emptied ``bundles`` volume must come out red -- has
# nothing to turn red without it. A running agent keeps serving from
# its cache when the anchor is deleted; that is exactly the May failure
# mode. Without (4) the prescribed negative control would come out
# green, and a negative control that cannot fail invalidates the green
# result with it.
#
# What it must not read -- ADR-0076 "Nicht als Evidenz zulässig"
# --------------------------------------------------------------
#
#   * podman health state. Measured 2026-09-22: the healthcheck is
#     wrapped in ``/bin/sh -c`` against an image with no shell, so it
#     has published ``unhealthy`` since May while the same command run
#     directly answers "healthy". The label is not merely meaningless,
#     it is inverted.
#   * container ``Up`` state and ``RestartCount``.
#   * server logs. The server was busy and error-free for 127 days,
#     rotating its CA cleanly, with no consumer.
#
# ``tests/infra/test_substrate_acceptance_probe.py`` greps this file
# for those surfaces and fails if one appears. A prohibition that only
# exists in a comment is the same class of instrument as a healthcheck
# that never runs.
#
# Seam to the bootstrap (ADR-0076 umsetzungsschnitt steps 3 and 4)
# ------------------------------------------------------
#
# The staged anchor is ``bootstrap.jwks`` in the volume
# ``wakir-spire-server-federation-<side>-bundles``, written by the
# bootstrap before the agent starts and refreshed by a timer at a
# cadence well under ``ca_ttl``. This script reads that file and never
# writes it. Both the file name and the volume name are env-overridable
# so that the contract can move without a change here. Nothing under
# ``infra/spire/`` is touched by this script or by its tests.
#
# Sandbox boundary
# ----------------
#
# Runs on an operator-controlled node, as root, next to podman. It is
# fully hermetically testable: with the four ``*_FILE`` overrides set,
# podman is never invoked and the script reads fixtures. That is the
# same construction as scripts/observability/substrate-liveness-probe.sh
# and for the same reason -- a probe that can only be exercised on the
# substrate it is supposed to check has never been exercised.
#
# Dependencies: bash, openssl, base64, od, dd, stat, date, sed, grep,
# tr, mktemp. No jq, no python. Both nodes are Fedora CoreOS with no
# python3 at all (measured 2026-09-22).
#
# Exit codes
# ----------
#
#   0  a sample was written and every source produced a measurement
#      (a measurement may say the target is in a bad state -- that is
#      a measurement, and the judge reads it)
#   2  a sample was written, and at least one source could not be
#      measured. Not a pass. The record names the fields and why.
#   3  no sample could be written at all, or the invocation was
#      malformed. Nothing was recorded.
#
# There is deliberately no exit code meaning "the substrate is fine".
# This script is not entitled to that statement.

set -uo pipefail

SCHEMA="wakir-runtime/substrate-acceptance-sample@1"

# ---------------------------------------------------------------- args
MARKER=""
# Closed set. A marker the reader does not know is worse than no
# marker: the reader would carve the window on a boundary it cannot
# interpret, or silently ignore it. Refused here instead.
VALID_MARKERS="window-start window-end cold-agent-stop cold-agent-start negative-control-start negative-control-end"

die() { printf 'substrate-acceptance-probe: %s\n' "$1" >&2; exit 3; }

while (( $# > 0 )); do
  case "$1" in
    --mark)
      [[ $# -ge 2 ]] || die "--mark needs a value"
      MARKER="$2"; shift 2
      ;;
    --mark=*)
      MARKER="${1#--mark=}"; shift
      ;;
    -h|--help)
      sed -n '3,120p' "$0"; exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

if [[ -n "$MARKER" ]]; then
  case " ${VALID_MARKERS} " in
    *" ${MARKER} "*) : ;;
    *) die "unknown marker '${MARKER}'; known: ${VALID_MARKERS}" ;;
  esac
fi

# --------------------------------------------------------------- setup
SIDE_RAW="${WAKIR_ACC_SIDE:-}"
[[ -n "$SIDE_RAW" ]] || die "WAKIR_ACC_SIDE is unset; the sample would not say which side it describes"
# Sanitised to the same alphabet as the liveness probe's node label.
# The side is a pseudonym in the record, not a hostname and not an
# address; nothing in this file emits either.
SIDE="$(printf '%s' "$SIDE_RAW" | tr -c 'A-Za-z0-9._-' '_')"

LOG_FILE="${WAKIR_ACC_LOG:-/var/lib/wakir/acceptance/samples-${SIDE}.ndjson}"

AGENT_CTR="${WAKIR_ACC_AGENT_CTR:-wakir-spire-agent-${SIDE}}"
SERVER_CTR="${WAKIR_ACC_SERVER_CTR:-wakir-spire-server-federation-${SIDE}}"
AGENT_SOCKET="${WAKIR_ACC_AGENT_SOCKET:-/run/spire/agent-sockets/api.sock}"
AGENT_BIN="${WAKIR_ACC_SPIRE_AGENT_BIN:-/opt/spire/bin/spire-agent}"
SERVER_BIN="${WAKIR_ACC_SPIRE_SERVER_BIN:-/opt/spire/bin/spire-server}"
AGENT_DATA_VOLUME="${WAKIR_ACC_AGENT_DATA_VOLUME:-wakir-spire-agent-${SIDE}-data}"
BUNDLES_VOLUME="${WAKIR_ACC_BUNDLES_VOLUME:-wakir-spire-server-federation-${SIDE}-bundles}"
# The seam to bootstrap step 3. Name of the staged bootstrap anchor inside
# the bundles volume.
ANCHOR_NAME="${WAKIR_ACC_ANCHOR_NAME:-bootstrap.jwks}"
# Overridable so the podman code path -- which the four ``*_FILE``
# fixtures bypass entirely -- can be driven by a stub in the test
# surface. A branch that no test can reach is a branch nobody has read.
PODMAN_BIN="${WAKIR_ACC_PODMAN_BIN:-podman}"

if [[ -n "${WAKIR_ACC_NOW_EPOCH:-}" ]]; then
  NOW="${WAKIR_ACC_NOW_EPOCH}"
else
  NOW="$(date -u +%s)"
fi

TMPDIR_ACC=""
cleanup() { [[ -n "$TMPDIR_ACC" && -d "$TMPDIR_ACC" ]] && rm -rf "$TMPDIR_ACC"; }
trap cleanup EXIT

# ---------------------------------------------------------- measurement
# Empty string means "not measured" and is rendered as JSON null, so a
# consumer can tell "measured as absent" from "this probe did not
# look". Same contract as the liveness probe.
M_SVID_STATUS=""
M_SVID_NOT_BEFORE=""
M_SVID_NOT_AFTER=""
M_SVID_CHAIN_LEN=""
M_SVID_CHAIN_AUTHORITY_ID=""
M_SVID_LEAF_AUTHORITY_ID=""
M_SVID_CHAIN_IDS=""
M_AGENT_BUNDLE_IDS=""

M_BUNDLE_STATUS=""
M_BUNDLE_AUTHORITY_IDS=""
M_BUNDLE_JWT_KIDS=""

M_AGENT_DATA_STATUS=""
M_AGENT_DATA_MTIME=""

M_ANCHOR_STATUS=""
M_ANCHOR_SIZE=""
M_ANCHOR_MTIME=""
M_ANCHOR_AUTHORITY_IDS=""

# Fields that could not be measured, with a reason from a closed
# vocabulary. This list -- not the absence of a value -- is what makes
# the difference between "not measured" and "measured and bad"
# readable by the judge.
UNMEASURED_FIELDS=()
UNMEASURED_REASONS=()

note_unmeasured() {
  UNMEASURED_FIELDS+=("$1")
  UNMEASURED_REASONS+=("$2")
}

# ------------------------------------------------------------- helpers

# json_num <value> -- a number, or JSON null when not measured.
json_num() { if [[ -z "${1:-}" ]]; then printf 'null'; else printf '%s' "$1"; fi; }

# json_str <value> -- a quoted string, or JSON null when not measured.
# Every value that reaches this function is either a constant from this
# file, a sanitised label, or an uppercase-hex identifier, so there is
# nothing to escape and nothing is faked.
json_str() {
  if [[ -z "${1:-}" ]]; then printf 'null'; else printf '"%s"' "$1"; fi
}

# json_str_list <space-separated> <source-status> -- a JSON array of
# strings, or JSON null.
#
# The status decides, not the emptiness of the list. "the source was
# read and holds nothing" is ``[]`` and "nobody read the source" is
# ``null``, and collapsing the two would put the very distinction this
# harness exists for into its own wire format. An empty list is a
# measurement; null is the absence of one.
json_str_list() {
  local first=1 item
  case "${2:-}" in
    ""|unmeasured) printf 'null'; return ;;
  esac
  printf '['
  for item in ${1:-}; do
    (( first )) || printf ','
    printf '"%s"' "$item"
    first=0
  done
  printf ']'
}

# der_split_b64 <file> -- concatenated DER certificates in, one
# base64 blob per certificate out.
#
# Written by hand because the alternative was worse. The Workload API
# hands back the chain as one DER blob; ``openssl x509`` reads the
# first certificate of such a blob and ignores the rest, and the only
# CLI path that yields separate PEM files is ``-write``, which also
# writes the SVID **private key** to disk. This probe never puts key
# material on a filesystem, so it splits the blob itself: every
# certificate is a DER SEQUENCE, and a SEQUENCE announces its own
# length in its header.
#
# Lengths above 65535 bytes (0x83 and up) are refused rather than
# guessed at; an EC certificate is ~500 bytes and a blob that claims
# otherwise is not a chain we understand.
der_split_b64() {
  local f="$1" off=0 size hdr b0 b1 b2 b3 hl len
  size="$(stat -c %s "$f" 2>/dev/null)" || return 1
  [[ -n "$size" ]] || return 1
  (( size > 0 )) || return 1
  while (( off < size )); do
    hdr="$(od -An -v -tu1 -j "$off" -N 4 "$f" 2>/dev/null | tr -s ' ')" || return 1
    # shellcheck disable=SC2086
    set -- $hdr
    b0="${1:-}"; b1="${2:-}"; b2="${3:-}"; b3="${4:-}"
    [[ -n "$b0" && -n "$b1" ]] || return 1
    (( b0 == 48 )) || return 1          # 0x30, SEQUENCE
    if   (( b1 < 128 ));  then hl=2; len="$b1"
    elif (( b1 == 129 )); then hl=3; len="${b2:-0}"
    elif (( b1 == 130 )); then hl=4; len=$(( ${b2:-0} * 256 + ${b3:-0} ))
    else return 1
    fi
    (( len > 0 )) || return 1
    (( off + hl + len <= size )) || return 1
    dd if="$f" bs=1 skip="$off" count=$(( hl + len )) status=none 2>/dev/null | base64 | tr -d '\n'
    printf '\n'
    off=$(( off + hl + len ))
  done
  return 0
}

# cert_id <der-file> <subject|authority> -- the key identifier as
# uppercase hex without separators, or nothing.
#
# For X.509 authorities the SPIFFE bundle format carries no ``kid``
# (SPIFFE_Trust_Domain_and_Bundle §4.2 defines ``x5c`` for
# ``use=x509-svid`` and does not define ``kid`` for it), so the stable
# identifier available on both sides of the comparison is the
# certificate's Subject Key Identifier -- and the issuing authority of
# an SVID names exactly that value in its Authority Key Identifier.
# That is what makes ADR-0076's Z1 a set-membership test on comparable
# identifiers rather than a name match.
#
# Only the first payload line is read. OpenSSL 1.x prints the AKI as
# ``keyid:AA:BB`` possibly followed by ``DirName:`` and ``serial:``
# lines whose contents are also hex; taking the whole section and
# filtering for hex characters would silently concatenate the serial
# onto the identifier.
cert_id() {
  local der="$1" which="$2" ext line
  case "$which" in
    subject)   ext="subjectKeyIdentifier" ;;
    authority) ext="authorityKeyIdentifier" ;;
    *) return 1 ;;
  esac
  line="$(openssl x509 -inform DER -in "$der" -noout -ext "$ext" 2>/dev/null | sed -n '2p')"
  [[ -n "$line" ]] || return 1
  line="${line//keyid:/}"
  line="$(printf '%s' "$line" | tr -cd '0-9A-Fa-f:' | tr -d ':' | tr 'a-f' 'A-F')"
  [[ "$line" =~ ^[0-9A-F]{8,}$ ]] || return 1
  printf '%s' "$line"
}

# cert_epoch <der-file> <start|end>
cert_epoch() {
  local der="$1" which="$2" raw
  case "$which" in
    start) raw="$(openssl x509 -inform DER -in "$der" -noout -startdate 2>/dev/null | sed 's/^notBefore=//')" ;;
    end)   raw="$(openssl x509 -inform DER -in "$der" -noout -enddate   2>/dev/null | sed 's/^notAfter=//')"  ;;
    *) return 1 ;;
  esac
  [[ -n "$raw" ]] || return 1
  date -u -d "$raw" +%s 2>/dev/null
}

# jwks_x5c <file> -- one base64 DER certificate per line, taken ONLY
# from entries that declare ``"use":"x509-svid"``.
#
# The scoping is load-bearing and was measured, not reasoned about. A
# bundle that holds exactly one ``jwt-svid`` key and no X.509 authority
# is well-formed, is real server-issued key material, and kills the
# agent: ``no certificates found in trust bundle``, measured against a
# real SPIRE v1.14.6. If the authority sets on the two sides of Z4's
# comparison were taken over all JWKS keys, such an anchor would share
# its JWT key with the server's set, satisfy the overlap, and read green
# over a substrate whose agent is in a retry loop.
#
# So the sets are X.509 sets by construction. An ``x5c`` on an entry
# that does not declare itself an X.509 authority is ignored rather than
# counted: the agent will not use it either, and a measurement that is
# more generous than the consumer is a measurement of the wrong thing.
#
# Each JWK is an innermost JSON object -- every member of a SPIFFE
# bundle entry is a string or an array of strings -- so the objects can
# be isolated without a JSON parser and without jq, which neither node
# has.
jwks_x5c() {
  local obj
  while IFS= read -r obj || [[ -n "$obj" ]]; do
    [[ "$obj" == *'"use":"x509-svid"'* ]] || continue
    printf '%s' "$obj" \
      | grep -o '"x5c":\[[^]]*\]' \
      | grep -o '"[A-Za-z0-9+/=]\{16,\}"' \
      | tr -d '"'
  done < <(tr -d ' \t\n\r' < "$1" 2>/dev/null | grep -o '{[^{}]*}')
}

# jwks_kids <file> -- the JWT authority key ids, informational.
jwks_kids() {
  tr -d ' \t\n\r' < "$1" 2>/dev/null \
    | grep -o '"kid":"[^"]*"' \
    | sed -e 's/^"kid":"//' -e 's/"$//' \
    | tr -c 'A-Za-z0-9._\-\n' '_'
}

# jwks_authority_ids <file> -- the SKI set of the X.509 authorities in
# a SPIFFE bundle, sorted and de-duplicated. Empty output with status 0
# means "parsed, and it holds no X.509 authority" -- which is a
# measurement, and a bad one. Status 1 means "could not read it".
jwks_authority_ids() {
  local f="$1" b64 der ids=()
  [[ -r "$f" ]] || return 1
  while IFS= read -r b64 || [[ -n "$b64" ]]; do
    [[ -z "$b64" ]] && continue
    der="${TMPDIR_ACC}/jwks-x5c.der"
    printf '%s' "$b64" | base64 -d > "$der" 2>/dev/null || continue
    id="$(cert_id "$der" subject)" || continue
    ids+=("$id")
  done < <(jwks_x5c "$f")
  printf '%s\n' "${ids[@]+"${ids[@]}"}" | sed '/^$/d' | sort -u | tr '\n' ' ' | sed 's/ $//'
  return 0
}

TMPDIR_ACC="$(mktemp -d 2>/dev/null)" || die "could not create a temporary directory"

# ------------------------------------------------------- source 1: SVID
#
# ``spire-agent api fetch x509 -output json`` and not ``-write``: the
# JSON form keeps the response in a pipe, while ``-write`` puts
# ``svid.0.key`` -- the workload's private key -- into a volume that
# persona containers mount. The response carries the key in
# ``x509_svid_key``; that field is never extracted, never logged and
# never written. A test feeds a response with a recognisable key and
# asserts it appears in neither the record nor the log.
measure_svid() {
  local resp="" chain_b64="" agent_bundle_b64="" rc=0

  if [[ -n "${WAKIR_ACC_SVID_JSON_FILE:-}" ]]; then
    if [[ ! -e "${WAKIR_ACC_SVID_JSON_FILE}" ]]; then
      M_SVID_STATUS="unmeasured"
      note_unmeasured svid svid_source_unreadable
      return
    fi
    resp="$(cat "${WAKIR_ACC_SVID_JSON_FILE}" 2>/dev/null)"
    rc=$?
  else
    if ! command -v "$PODMAN_BIN" >/dev/null 2>&1; then
      M_SVID_STATUS="unmeasured"
      note_unmeasured svid podman_absent
      return
    fi
    local errfile="${TMPDIR_ACC}/svid.err"
    resp="$("$PODMAN_BIN" exec "$AGENT_CTR" "$AGENT_BIN" api fetch x509 \
              -socketPath "$AGENT_SOCKET" -output json 2>"$errfile")"
    rc=$?
    # The stderr text is matched against a closed set of patterns and
    # then dropped. It is never copied into the record: a SPIRE error
    # line can carry a SPIFFE ID, and on this substrate the agent's own
    # ID embeds the join-token UUID.
    if (( rc != 0 )) && [[ -s "$errfile" ]] \
       && grep -qE 'PermissionDenied|no identity issued' "$errfile" 2>/dev/null; then
      # The Workload API answered and refused. That is a different
      # sentence from "the API is dead", and on a freshly bootstrapped
      # node it is the likely one: the bootstrap creates no registration
      # entries, so nothing matches the caller. Still a finding about the
      # window -- a substrate that issues no identity is the thing being
      # measured -- but an operator reading a week of red needs to know
      # it says "nobody is registered" and not "the agent is gone".
      # Step 0 of the test plan exists to catch this in minutes.
      M_SVID_STATUS="target_bad_no_identity_issued_to_the_probe"
      resp=""
      return
    fi
    if (( rc == 125 )); then
      # Podman's own "I could not start this at all" code: no such
      # container, or it is not running. Still a measurement of the
      # target and still bad -- during an acceptance window an absent
      # agent is the finding, not an excuse -- but a different sentence
      # from "the container is there and the API said nothing", and the
      # person reading the report needs the difference.
      M_SVID_STATUS="target_bad_agent_container_unavailable"
      resp=""
      return
    fi
  fi

  if (( rc != 0 )) || [[ -z "$resp" ]]; then
    # The Workload API did not answer. That is a measurement of the
    # target, not a failure of the probe: the one thing this window is
    # about is whether an identity is being served, and nothing was.
    M_SVID_STATUS="target_bad_workload_api_no_response"
    resp=""
    return
  fi

  chain_b64="$(printf '%s' "$resp" | tr -d ' \t\n\r' \
                | grep -o '"x509_svid":"[^"]*"' | head -n 1 \
                | sed -e 's/^"x509_svid":"//' -e 's/"$//')"
  agent_bundle_b64="$(printf '%s' "$resp" | tr -d ' \t\n\r' \
                | grep -o '"bundle":"[^"]*"' | head -n 1 \
                | sed -e 's/^"bundle":"//' -e 's/"$//')"
  resp=""
  unset resp

  if [[ -z "$chain_b64" ]]; then
    # A response arrived and contains no SVID. SPIRE's own CLI calls
    # this "workload response contains no svids". The Workload API is
    # up and hands out no identity: measured, and bad.
    M_SVID_STATUS="target_bad_no_svid_in_response"
    return
  fi

  local chain_der="${TMPDIR_ACC}/chain.der"
  if ! printf '%s' "$chain_b64" | base64 -d > "$chain_der" 2>/dev/null; then
    M_SVID_STATUS="unmeasured"
    note_unmeasured svid svid_chain_undecodable
    return
  fi

  local certs=() line
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -n "$line" ]] && certs+=("$line")
  done < <(der_split_b64 "$chain_der")

  if (( ${#certs[@]} == 0 )); then
    M_SVID_STATUS="unmeasured"
    note_unmeasured svid svid_chain_unsplittable
    return
  fi

  M_SVID_STATUS="ok"
  M_SVID_CHAIN_LEN="${#certs[@]}"

  local i der id
  local chain_ids=()
  for (( i = 0; i < ${#certs[@]}; i++ )); do
    der="${TMPDIR_ACC}/chain-${i}.der"
    printf '%s' "${certs[$i]}" | base64 -d > "$der" 2>/dev/null || continue
    if id="$(cert_id "$der" subject)"; then chain_ids+=("$id"); fi
  done
  M_SVID_CHAIN_IDS="$(printf '%s\n' "${chain_ids[@]+"${chain_ids[@]}"}" | sed '/^$/d' | tr '\n' ' ' | sed 's/ $//')"

  local leaf="${TMPDIR_ACC}/chain-0.der"
  local top="${TMPDIR_ACC}/chain-$(( ${#certs[@]} - 1 )).der"

  M_SVID_NOT_BEFORE="$(cert_epoch "$leaf" start)" || M_SVID_NOT_BEFORE=""
  M_SVID_NOT_AFTER="$(cert_epoch "$leaf" end)"    || M_SVID_NOT_AFTER=""
  [[ -z "$M_SVID_NOT_BEFORE" ]] && note_unmeasured svid_not_before svid_leaf_dates_unreadable
  [[ -z "$M_SVID_NOT_AFTER"  ]] && note_unmeasured svid_not_after  svid_leaf_dates_unreadable

  # The authority that signed the topmost certificate of the chain.
  # Under an UpstreamAuthority the chain is leaf + intermediate and the
  # root stays in the bundle, so the leaf's own issuer is NOT in the
  # bundle set and comparing it would read red on a healthy substrate.
  # Under a self-signed server the chain is the leaf alone and the two
  # values coincide. Both topologies are covered by taking the top of
  # the chain, and both are covered by test vectors.
  M_SVID_CHAIN_AUTHORITY_ID="$(cert_id "$top" authority)" || M_SVID_CHAIN_AUTHORITY_ID=""
  [[ -z "$M_SVID_CHAIN_AUTHORITY_ID" ]] && note_unmeasured svid_chain_authority_id svid_chain_top_has_no_authority_key_id
  M_SVID_LEAF_AUTHORITY_ID="$(cert_id "$leaf" authority)" || M_SVID_LEAF_AUTHORITY_ID=""

  # The bundle as the AGENT has it cached, recorded and deliberately
  # not gated on: during a rotation overlap the agent legitimately
  # holds authorities the server has already pruned. It is here so a
  # human reading a red window can see whether the two views diverged.
  if [[ -n "$agent_bundle_b64" ]]; then
    local ab_der="${TMPDIR_ACC}/agent-bundle.der"
    if printf '%s' "$agent_bundle_b64" | base64 -d > "$ab_der" 2>/dev/null; then
      local ab_ids=() ab_line ab_i=0
      while IFS= read -r ab_line || [[ -n "$ab_line" ]]; do
        [[ -z "$ab_line" ]] && continue
        der="${TMPDIR_ACC}/agent-bundle-${ab_i}.der"
        ab_i=$(( ab_i + 1 ))
        printf '%s' "$ab_line" | base64 -d > "$der" 2>/dev/null || continue
        if id="$(cert_id "$der" subject)"; then ab_ids+=("$id"); fi
      done < <(der_split_b64 "$ab_der")
      M_AGENT_BUNDLE_IDS="$(printf '%s\n' "${ab_ids[@]+"${ab_ids[@]}"}" | sed '/^$/d' | sort -u | tr '\n' ' ' | sed 's/ $//')"
    fi
  fi
}

# --------------------------------------------- source 2: server bundle
measure_bundle() {
  local jwks="${TMPDIR_ACC}/server-bundle.jwks" rc=0

  if [[ -n "${WAKIR_ACC_BUNDLE_JWKS_FILE:-}" ]]; then
    if [[ ! -e "${WAKIR_ACC_BUNDLE_JWKS_FILE}" ]]; then
      M_BUNDLE_STATUS="unmeasured"
      note_unmeasured bundle bundle_source_unreadable
      return
    fi
    cat "${WAKIR_ACC_BUNDLE_JWKS_FILE}" > "$jwks" 2>/dev/null
    rc=$?
  else
    if ! command -v "$PODMAN_BIN" >/dev/null 2>&1; then
      M_BUNDLE_STATUS="unmeasured"
      note_unmeasured bundle podman_absent
      return
    fi
    "$PODMAN_BIN" exec "$SERVER_CTR" "$SERVER_BIN" bundle show -format spiffe > "$jwks" 2>/dev/null
    rc=$?
    if (( rc == 125 )); then
      M_BUNDLE_STATUS="target_bad_server_container_unavailable"
      return
    fi
  fi

  if (( rc != 0 )) || [[ ! -s "$jwks" ]]; then
    # The server did not hand over its bundle. Measured, and bad: the
    # authority set is the reference every other statement is made
    # against, and there is none.
    M_BUNDLE_STATUS="target_bad_bundle_show_no_output"
    return
  fi

  case "$(tr -d ' \t\n\r' < "$jwks")" in
    *'"keys":'*) : ;;
    *)
      M_BUNDLE_STATUS="unmeasured"
      note_unmeasured bundle bundle_not_a_jwks
      return
      ;;
  esac

  M_BUNDLE_AUTHORITY_IDS="$(jwks_authority_ids "$jwks")"
  M_BUNDLE_JWT_KIDS="$(jwks_kids "$jwks" | sort -u | tr '\n' ' ' | sed 's/ $//')"
  if [[ -z "$M_BUNDLE_AUTHORITY_IDS" ]]; then
    # Parsed, and it holds no usable X.509 authority.
    M_BUNDLE_STATUS="target_bad_bundle_holds_no_x509_authority"
  else
    M_BUNDLE_STATUS="ok"
  fi
}

# --------------------------------------------- source 3: agent-data.json
measure_agent_data() {
  local f="${WAKIR_ACC_AGENT_DATA_FILE:-}" mountpoint

  if [[ -z "$f" ]]; then
    if ! command -v "$PODMAN_BIN" >/dev/null 2>&1; then
      M_AGENT_DATA_STATUS="unmeasured"
      note_unmeasured agent_data_mtime podman_absent
      return
    fi
    mountpoint="$("$PODMAN_BIN" volume inspect "$AGENT_DATA_VOLUME" --format '{{.Mountpoint}}' 2>/dev/null)"
    if [[ -z "$mountpoint" ]]; then
      M_AGENT_DATA_STATUS="unmeasured"
      note_unmeasured agent_data_mtime agent_data_volume_absent
      return
    fi
    f="${mountpoint}/agent-data.json"
  fi

  if [[ ! -e "$f" ]]; then
    # The file the agent writes when it attests does not exist.
    M_AGENT_DATA_STATUS="target_bad_agent_data_absent"
    return
  fi

  M_AGENT_DATA_MTIME="$(stat -c %Y "$f" 2>/dev/null)"
  if [[ -z "$M_AGENT_DATA_MTIME" ]]; then
    M_AGENT_DATA_STATUS="unmeasured"
    note_unmeasured agent_data_mtime agent_data_mtime_unreadable
    return
  fi
  M_AGENT_DATA_STATUS="ok"
}

# ------------------------------------ source 4: staged bootstrap anchor
measure_anchor() {
  local f="${WAKIR_ACC_ANCHOR_FILE:-}" mountpoint

  if [[ -z "$f" ]]; then
    if ! command -v "$PODMAN_BIN" >/dev/null 2>&1; then
      M_ANCHOR_STATUS="unmeasured"
      note_unmeasured anchor podman_absent
      return
    fi
    mountpoint="$("$PODMAN_BIN" volume inspect "$BUNDLES_VOLUME" --format '{{.Mountpoint}}' 2>/dev/null)"
    if [[ -z "$mountpoint" ]]; then
      M_ANCHOR_STATUS="unmeasured"
      note_unmeasured anchor bundles_volume_absent
      return
    fi
    f="${mountpoint}/${ANCHOR_NAME}"
  fi

  if [[ ! -e "$f" ]]; then
    # This is the state the mandatory negative control produces, and
    # the state both nodes have been in since the volumes were created
    # in May. It is a measurement of the target.
    M_ANCHOR_STATUS="target_bad_anchor_absent"
    M_ANCHOR_SIZE=0
    return
  fi

  M_ANCHOR_SIZE="$(stat -c %s "$f" 2>/dev/null)"
  M_ANCHOR_MTIME="$(stat -c %Y "$f" 2>/dev/null)"
  if [[ -z "$M_ANCHOR_SIZE" || -z "$M_ANCHOR_MTIME" ]]; then
    M_ANCHOR_STATUS="unmeasured"
    note_unmeasured anchor anchor_stat_unreadable
    return
  fi
  if (( M_ANCHOR_SIZE == 0 )); then
    M_ANCHOR_STATUS="target_bad_anchor_empty"
    return
  fi
  if ! [[ -r "$f" ]]; then
    M_ANCHOR_STATUS="unmeasured"
    note_unmeasured anchor anchor_unreadable
    return
  fi
  case "$(tr -d ' \t\n\r' < "$f")" in
    *'"keys":'*) : ;;
    *)
      # A file at the right path that is not a bundle. This is the
      # shape the fixture CLIs in infra/spire/federation/bin/ would
      # produce if anyone wired them into the staging path, except
      # that theirs would parse -- see ADR-0076 context (c). Parsing
      # is necessary here and nowhere near sufficient; the authority
      # comparison below is what carries the statement.
      M_ANCHOR_STATUS="target_bad_anchor_not_a_jwks"
      return
      ;;
  esac
  M_ANCHOR_AUTHORITY_IDS="$(jwks_authority_ids "$f")"
  if [[ -z "$M_ANCHOR_AUTHORITY_IDS" ]]; then
    M_ANCHOR_STATUS="target_bad_anchor_holds_no_x509_authority"
  else
    M_ANCHOR_STATUS="ok"
  fi
}

for tool in date openssl base64 od dd stat sed grep tr sort; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    note_unmeasured "tooling" "missing_tool_${tool}"
  fi
done

measure_svid
measure_bundle
measure_agent_data
measure_anchor

# ------------------------------------------------------------- emission
observed_at="$(date -u -d "@${NOW}" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || printf '')"

unmeasured_json() {
  local i first=1
  printf '['
  for (( i = 0; i < ${#UNMEASURED_FIELDS[@]}; i++ )); do
    (( first )) || printf ','
    printf '{"field":"%s","reason":"%s"}' "${UNMEASURED_FIELDS[$i]}" "${UNMEASURED_REASONS[$i]}"
    first=0
  done
  printf ']'
}

# The record carries measurements and nothing else. There is no
# verdict field, no "ok", no "healthy" -- and
# substrate_acceptance_window.py rejects any record that grows one.
record="$(
  printf '{'
  printf '"schema":"%s",' "$SCHEMA"
  printf '"side":"%s",' "$SIDE"
  printf '"observed_at_epoch":%s,' "$(json_num "$NOW")"
  printf '"observed_at":"%s",' "$observed_at"
  printf '"marker":%s,' "$(json_str "$MARKER")"
  printf '"svid_status":%s,' "$(json_str "$M_SVID_STATUS")"
  printf '"svid_not_before_epoch":%s,' "$(json_num "$M_SVID_NOT_BEFORE")"
  printf '"svid_not_after_epoch":%s,' "$(json_num "$M_SVID_NOT_AFTER")"
  printf '"svid_chain_len":%s,' "$(json_num "$M_SVID_CHAIN_LEN")"
  printf '"svid_chain_authority_id":%s,' "$(json_str "$M_SVID_CHAIN_AUTHORITY_ID")"
  printf '"svid_leaf_authority_id":%s,' "$(json_str "$M_SVID_LEAF_AUTHORITY_ID")"
  printf '"svid_chain_ids":%s,' "$(json_str_list "$M_SVID_CHAIN_IDS" "$M_SVID_STATUS")"
  printf '"agent_cached_bundle_authority_ids":%s,' "$(json_str_list "$M_AGENT_BUNDLE_IDS" "$M_SVID_STATUS")"
  printf '"bundle_status":%s,' "$(json_str "$M_BUNDLE_STATUS")"
  printf '"bundle_authority_ids":%s,' "$(json_str_list "$M_BUNDLE_AUTHORITY_IDS" "$M_BUNDLE_STATUS")"
  printf '"bundle_jwt_kids":%s,' "$(json_str_list "$M_BUNDLE_JWT_KIDS" "$M_BUNDLE_STATUS")"
  printf '"agent_data_status":%s,' "$(json_str "$M_AGENT_DATA_STATUS")"
  printf '"agent_data_mtime_epoch":%s,' "$(json_num "$M_AGENT_DATA_MTIME")"
  printf '"anchor_status":%s,' "$(json_str "$M_ANCHOR_STATUS")"
  printf '"anchor_size_bytes":%s,' "$(json_num "$M_ANCHOR_SIZE")"
  printf '"anchor_mtime_epoch":%s,' "$(json_num "$M_ANCHOR_MTIME")"
  printf '"anchor_authority_ids":%s,' "$(json_str_list "$M_ANCHOR_AUTHORITY_IDS" "$M_ANCHOR_STATUS")"
  printf '"unmeasured":%s' "$(unmeasured_json)"
  printf '}'
)"

printf '%s\n' "$record"

log_dir="$(dirname "$LOG_FILE")"
if ! mkdir -p "$log_dir" 2>/dev/null; then
  printf 'substrate-acceptance-probe: cannot create %s; the sample was printed but not recorded\n' "$log_dir" >&2
  exit 3
fi
if ! printf '%s\n' "$record" >> "$LOG_FILE" 2>/dev/null; then
  printf 'substrate-acceptance-probe: cannot append to %s; the sample was printed but not recorded\n' "$LOG_FILE" >&2
  exit 3
fi

if (( ${#UNMEASURED_FIELDS[@]} > 0 )); then
  exit 2
fi
exit 0
