#!/usr/bin/env bash
# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Phase-2 Sprint-9 Tag-5 — Acceptance-Gate verdict for the disposable
#                          VM bring-up run.
#
# Reads:
#   $WAKIR_E2E_STATE_DIR/smoke-run.json
#   $WAKIR_E2E_STATE_DIR/bootstrap-run.log
#   $WAKIR_E2E_STATE_DIR/run.env
#
# Pass conditions (all must hold):
#   1. Bootstrap exited 0.
#   2. Smoke exited 0 (which by contract implies 6/6 PASS).
#   3. Smoke JSON parses and reports pass_count == 6 and fail_count == 0.
#   4. Bootstrap log does NOT contain the Bug-1 ``sudo bash bash``
#      resume-hint doubling.
#
# On failure, prints a structured bug-vector classification that maps
# each failed smoke check to the candidate 2026-05-13 bug(s) and exits
# non-zero.
#
# Exit codes:
#   0  Acceptance-Gate PASS
#   2  Acceptance-Gate FAIL (with classification)
#   3  Input artefacts missing (gate cannot decide)

set -u

: "${WAKIR_E2E_STATE_DIR:=/var/lib/wakir-e2e}"
RUN_ENV="$WAKIR_E2E_STATE_DIR/run.env"
SMOKE_JSON="$WAKIR_E2E_STATE_DIR/smoke-run.json"
BOOTSTRAP_LOG="$WAKIR_E2E_STATE_DIR/bootstrap-run.log"
VERDICT_JSON="$WAKIR_E2E_STATE_DIR/gate-verdict.json"

emit() { echo "[gate] $*" >&2; }

# Allow tests to override the artefact paths via env without touching
# the script.
[[ -n "${WAKIR_E2E_OVERRIDE_SMOKE_JSON:-}" ]]    && SMOKE_JSON="$WAKIR_E2E_OVERRIDE_SMOKE_JSON"
[[ -n "${WAKIR_E2E_OVERRIDE_BOOTSTRAP_LOG:-}" ]] && BOOTSTRAP_LOG="$WAKIR_E2E_OVERRIDE_BOOTSTRAP_LOG"
[[ -n "${WAKIR_E2E_OVERRIDE_RUN_ENV:-}" ]]       && RUN_ENV="$WAKIR_E2E_OVERRIDE_RUN_ENV"
[[ -n "${WAKIR_E2E_OVERRIDE_VERDICT_JSON:-}" ]]  && VERDICT_JSON="$WAKIR_E2E_OVERRIDE_VERDICT_JSON"

missing=()
[[ -f "$RUN_ENV" ]]       || missing+=("$RUN_ENV")
[[ -f "$SMOKE_JSON" ]]    || missing+=("$SMOKE_JSON")
[[ -f "$BOOTSTRAP_LOG" ]] || missing+=("$BOOTSTRAP_LOG")

if (( ${#missing[@]} > 0 )); then
  emit "ERROR: required artefacts missing:"
  for m in "${missing[@]}"; do emit "  - $m"; done
  exit 3
fi

# shellcheck disable=SC1090
. "$RUN_ENV"

bootstrap_rc="${WAKIR_E2E_BOOTSTRAP_RC:-1}"
smoke_rc="${WAKIR_E2E_SMOKE_RC:-1}"

# Bug-1 detection: a bootstrap with the "sudo bash bash" doubling tells
# the operator a wrong resume command. This is non-blocking but failing
# the gate keeps the regression out of main.
bug1=0
if grep -E -q 'sudo bash bash --resume-from' "$BOOTSTRAP_LOG"; then
  bug1=1
fi

# Parse smoke JSON. Schema (set by proxmox-bringup-smoke --json):
#   {
#     "summary": {"pass": N, "fail": M, "total": T},
#     "results": [
#       {"name": "quadlet-units-active", "status": "PASS"|"FAIL", "detail": "..."},
#       ...
#     ]
#   }
python3 - "$SMOKE_JSON" > "$VERDICT_JSON" <<'PYEOF'
import json
import sys
from pathlib import Path

CHECK_TO_BUGS = {
    "quadlet-units-active":          ["Bug 2 (Volume-filename mismatch)", "Bug 5 (Phase-6 not idempotent)"],
    "nats-jetstream-reachable":      ["Bug 6 cascade (Bucket-Init cryptography ModuleNotFoundError)"],
    "spire-server-healthy":          ["Bug 7 (SPIRE-Server restart loop)"],
    "spire-agent-healthy":           ["Bug 3 (Agent Volume-Pfad)", "Bug 4 (Agent Requires)"],
    "spire-workload-api-reachable":  ["Bug 3", "Bug 4", "Bug 7 cascade"],
    "marker-stack-bucket-present":   ["Bug 6 (Bucket-Init crash)"],
}

src = Path(sys.argv[1])
try:
    data = json.loads(src.read_text(encoding="utf-8"))
except Exception as exc:
    print(json.dumps({
        "verdict": "FAIL",
        "reason": f"smoke JSON unparseable: {exc!r}",
        "bug_vectors": ["unknown — smoke output corrupted"],
    }, indent=2))
    sys.exit(0)

summary = data.get("summary", {}) or {}
pass_count = int(summary.get("pass", 0))
fail_count = int(summary.get("fail", 0))
total = int(summary.get("total", 0))
results = data.get("results", []) or []

failed = [c for c in results if c.get("status") != "PASS"]
failed_names = [c.get("name", "?") for c in failed]

bug_vectors = []
for n in failed_names:
    bug_vectors.extend(CHECK_TO_BUGS.get(n, [f"unknown check '{n}'"]))

verdict_pass = (
    pass_count == 6
    and fail_count == 0
    and total == 6
    and not failed
)
out = {
    "verdict": "PASS" if verdict_pass else "FAIL",
    "pass_count": pass_count,
    "fail_count": fail_count,
    "total_checks": total,
    "failed_checks": failed_names,
    "bug_vectors": sorted(set(bug_vectors)),
}
print(json.dumps(out, indent=2))
PYEOF

verdict=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("verdict","FAIL"))' "$VERDICT_JSON")

# Final pass requires: gate verdict PASS, bootstrap_rc==0, smoke_rc==0, bug1==0.
overall_pass=1
[[ "$verdict" == "PASS" ]] || overall_pass=0
[[ "$bootstrap_rc" == "0" ]] || overall_pass=0
[[ "$smoke_rc" == "0" ]] || overall_pass=0
[[ "$bug1" == "0" ]] || overall_pass=0

emit "verdict: $verdict"
emit "bootstrap_rc: $bootstrap_rc"
emit "smoke_rc: $smoke_rc"
emit "bug1 (resume-hint doubling): $bug1"

if (( overall_pass == 1 )); then
  emit "ACCEPTANCE-GATE PASS"
  exit 0
fi

emit "ACCEPTANCE-GATE FAIL"
emit "verdict json:"
cat "$VERDICT_JSON" >&2 || true
emit ""
emit "bug-vector classification (from smoke + bootstrap log inspection):"
python3 -c '
import json, sys
v = json.load(open(sys.argv[1]))
if v.get("bug_vectors"):
    for b in v["bug_vectors"]: print("  - " + b)
else:
    print("  (no smoke-driven bug vectors; failure was bootstrap-rc or bug1)")
' "$VERDICT_JSON" >&2 || true

if (( bug1 == 1 )); then
  emit "  - Bug 1 (resume-hint 'sudo bash bash' doubling) detected in bootstrap log"
fi

exit 2
