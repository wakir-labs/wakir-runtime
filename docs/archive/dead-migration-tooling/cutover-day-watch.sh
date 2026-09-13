#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Cutover-Day-Watch — operator-side wrapper around the Tag-41
# cutover-day-live-stream-aggregator (Noa SRE).
#
# Usage (Cutover-Tag-Morgen 06:30 CEST):
#
#     ./scripts/observability/cutover-day-watch.sh [--mode fixture|nats] \
#         [--fixture-stream PATH] [--window-size 60|300|1800] \
#         [--prometheus-output PATH] [--state-dir DIR]
#
# The wrapper:
#   1. Starts cutover-day-live-stream-aggregator as a background process
#      with stdout piped into a named-pipe.
#   2. Tails the named-pipe to the operator's terminal (live view).
#   3. On SIGINT (Ctrl-C), forwards SIGTERM to the background process,
#      waits for the final-state-dump, then exits.
#   4. Notify lines (DRIFT_RED_CROSSING / DRIFT_AMBER_CROSSING) on
#      stderr are tee'd to a notify-log file the Mira-Notify pickup
#      script consumes (operator runbook docs/observability/
#      cutover-day-watch-runbook.md).
#
# Sandbox boundary: in mode=fixture this script is hermetic (no NATS,
# no SPIFFE, no GitHub). In mode=nats it requires the NATS-CLI to be
# on PATH and the workload-SVID to be mounted (Kai's ADR-0020 NATS
# substrate). Live-runs are Operator-Hand per
# feedback_sandbox_host_trennung.md.
#
# Anchor: ADR-0066 Phase-3c §Cutover-Plan, Tag-41 Noa SRE.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGGREGATOR_PY="${SCRIPT_DIR}/cutover-day-live-stream-aggregator.py"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

MODE="fixture"
FIXTURE_STREAM=""
WINDOW_SIZE="300"
NATS_SUBJECT="wakir.persona-engine.boot-decision-audit.*"
NATS_URL=""
PROMETHEUS_OUTPUT=""
STATE_DIR=""
EMIT_EVERY="50"
MAX_EVENTS="0"

print_usage() {
    cat <<USAGE
cutover-day-watch.sh — Operator-Wrapper für Tag-41 Live-Stream-Aggregator.

Optionen:
  --mode {fixture|nats}        Default: fixture (hermetisch)
  --fixture-stream PATH        JSONL-Fixture-Datei (mode=fixture)
  --window-size N              Sliding-window (60|300|1800). Default 300.
  --emit-every N               Snapshot alle N Events. Default 50.
  --max-events N               Stop nach N Events (0 = unbegrenzt).
  --nats-subject PATTERN       Default: ${NATS_SUBJECT}
  --nats-url URL               NATS-Server-URL (optional)
  --prometheus-output PATH     Prometheus-textfile-Ausgabe
  --state-dir DIR              Verzeichnis für JSON-state + final-dump + notify-log.
                               Default: \$XDG_RUNTIME_DIR/wakir-cutover-watch
                               oder /tmp/wakir-cutover-watch
  -h, --help                   Diese Hilfe

Beispiele:
  ./cutover-day-watch.sh --mode fixture \\
      --fixture-stream tests/fixtures/cutover-day-rehearsal.jsonl

  ./cutover-day-watch.sh --mode nats \\
      --state-dir /var/lib/wakir/cutover-state-welle-1 \\
      --prometheus-output /var/lib/prometheus/node-exporter/wakir_cutover_live_stream.prom
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode) MODE="$2"; shift 2 ;;
        --fixture-stream) FIXTURE_STREAM="$2"; shift 2 ;;
        --window-size) WINDOW_SIZE="$2"; shift 2 ;;
        --emit-every) EMIT_EVERY="$2"; shift 2 ;;
        --max-events) MAX_EVENTS="$2"; shift 2 ;;
        --nats-subject) NATS_SUBJECT="$2"; shift 2 ;;
        --nats-url) NATS_URL="$2"; shift 2 ;;
        --prometheus-output) PROMETHEUS_OUTPUT="$2"; shift 2 ;;
        --state-dir) STATE_DIR="$2"; shift 2 ;;
        -h|--help) print_usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; print_usage >&2; exit 2 ;;
    esac
done

# Default state-dir.
if [[ -z "$STATE_DIR" ]]; then
    if [[ -n "${XDG_RUNTIME_DIR:-}" && -d "$XDG_RUNTIME_DIR" ]]; then
        STATE_DIR="${XDG_RUNTIME_DIR}/wakir-cutover-watch"
    else
        STATE_DIR="/tmp/wakir-cutover-watch"
    fi
fi
mkdir -p "$STATE_DIR"

JSON_STREAM="${STATE_DIR}/live-stream.jsonl"
NOTIFY_LOG="${STATE_DIR}/notify.log"
FINAL_DUMP="${STATE_DIR}/final-state.json"
PID_FILE="${STATE_DIR}/aggregator.pid"

# Truncate previous run's stream so the operator-tail starts fresh.
: > "$JSON_STREAM"
: > "$NOTIFY_LOG"
rm -f "$FINAL_DUMP" "$PID_FILE"

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

if [[ ! -x "$AGGREGATOR_PY" ]]; then
    if [[ ! -r "$AGGREGATOR_PY" ]]; then
        echo "ERROR: aggregator script not found: $AGGREGATOR_PY" >&2
        exit 1
    fi
fi

if [[ "$MODE" == "fixture" ]]; then
    if [[ -z "$FIXTURE_STREAM" ]]; then
        echo "ERROR: --fixture-stream required when mode=fixture" >&2
        exit 2
    fi
    if [[ ! -r "$FIXTURE_STREAM" ]]; then
        echo "ERROR: fixture stream not readable: $FIXTURE_STREAM" >&2
        exit 1
    fi
elif [[ "$MODE" == "nats" ]]; then
    if ! command -v nats >/dev/null 2>&1; then
        echo "ERROR: NATS-CLI 'nats' not on PATH (mode=nats requires Kai's NATS substrate)" >&2
        exit 1
    fi
else
    echo "ERROR: unknown mode: $MODE" >&2
    exit 2
fi

# ---------------------------------------------------------------------------
# Build the aggregator command line
# ---------------------------------------------------------------------------

AGG_CMD=(python3 "$AGGREGATOR_PY"
    --mode "$MODE"
    --window-size "$WINDOW_SIZE"
    --emit-every "$EMIT_EVERY"
    --json-output "$JSON_STREAM"
    --notify-output "$NOTIFY_LOG"
    --final-dump-output "$FINAL_DUMP"
)
if [[ "$MAX_EVENTS" != "0" ]]; then
    AGG_CMD+=(--max-events "$MAX_EVENTS")
fi
if [[ "$MODE" == "fixture" ]]; then
    AGG_CMD+=(--fixture-stream "$FIXTURE_STREAM")
else
    AGG_CMD+=(--nats-subject "$NATS_SUBJECT")
    if [[ -n "$NATS_URL" ]]; then
        AGG_CMD+=(--nats-url "$NATS_URL")
    fi
fi
if [[ -n "$PROMETHEUS_OUTPUT" ]]; then
    AGG_CMD+=(--prometheus-output "$PROMETHEUS_OUTPUT")
fi

echo "[cutover-day-watch] mode=$MODE window=$WINDOW_SIZE state-dir=$STATE_DIR" >&2
echo "[cutover-day-watch] live-view: $JSON_STREAM" >&2
echo "[cutover-day-watch] notify-log: $NOTIFY_LOG" >&2
echo "[cutover-day-watch] final-dump (on shutdown): $FINAL_DUMP" >&2
echo "[cutover-day-watch] aggregator cmd: ${AGG_CMD[*]}" >&2

# ---------------------------------------------------------------------------
# Spawn aggregator as background process
# ---------------------------------------------------------------------------

"${AGG_CMD[@]}" &
AGG_PID=$!
echo "$AGG_PID" > "$PID_FILE"
echo "[cutover-day-watch] aggregator started PID=$AGG_PID" >&2

# ---------------------------------------------------------------------------
# Signal-handling: clean shutdown on SIGINT/SIGTERM
# ---------------------------------------------------------------------------

TAIL_PID=""

cleanup() {
    local sig="${1:-EXIT}"
    echo "" >&2
    echo "[cutover-day-watch] received $sig, shutting down..." >&2
    if [[ -n "$TAIL_PID" ]] && kill -0 "$TAIL_PID" 2>/dev/null; then
        kill "$TAIL_PID" 2>/dev/null || true
    fi
    if kill -0 "$AGG_PID" 2>/dev/null; then
        kill -TERM "$AGG_PID" 2>/dev/null || true
        # Give the aggregator up to 5s to dump final state.
        for _ in 1 2 3 4 5; do
            if ! kill -0 "$AGG_PID" 2>/dev/null; then
                break
            fi
            sleep 1
        done
        if kill -0 "$AGG_PID" 2>/dev/null; then
            kill -KILL "$AGG_PID" 2>/dev/null || true
        fi
    fi
    if [[ -r "$FINAL_DUMP" ]]; then
        echo "[cutover-day-watch] final-state-dump:" >&2
        cat "$FINAL_DUMP" >&2
    fi
    rm -f "$PID_FILE"
    exit 0
}

trap 'cleanup INT' INT
trap 'cleanup TERM' TERM

# ---------------------------------------------------------------------------
# Live tail of JSON-stream to stdout (operator's live-view)
# ---------------------------------------------------------------------------

# tail -F follows the file even if truncated/rotated; -n +1 starts at
# the top so the operator sees the first snapshot.
tail -F -n +1 "$JSON_STREAM" &
TAIL_PID=$!

# Wait for aggregator. Bash's `wait $pid` returns aggregator's exit
# code; we honour it.
set +e
wait "$AGG_PID"
AGG_EXIT=$?
set -e

# Aggregator exited on its own (fixture-mode end-of-stream, or
# max-events hit). Stop the tail and exit cleanly.
if [[ -n "$TAIL_PID" ]] && kill -0 "$TAIL_PID" 2>/dev/null; then
    kill "$TAIL_PID" 2>/dev/null || true
fi
rm -f "$PID_FILE"

if [[ -r "$FINAL_DUMP" ]]; then
    echo "[cutover-day-watch] aggregator exited normally (exit=$AGG_EXIT), final-state-dump available at $FINAL_DUMP" >&2
fi

exit "$AGG_EXIT"
