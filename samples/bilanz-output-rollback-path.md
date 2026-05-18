# Phase-3 Marathon Final Bilanz

Generated at **2026-06-12T09:30:00Z** by `scripts/observability/phase-3-final-bilanz-generator.py`.

Schema version: `1.0.0`. This document is a snapshot; re-run the generator to refresh.

---

## 1. Executive Summary

- Wellen total: **7** (W1..W7 Rust-default cutover)
- Wellen with Henrik sign-off: **6 / 7**
- Marathon-Aggregat-Tracker last update: `2026-06-12T09:15:00Z`
- ci-aggregator runs total: **4**, failure-rate **50.00 %**

### Drift status across wellen

| Status | Count |
|---|---|
| OK | 7 |
| WARN | 0 |
| BREACH | 0 |
| NO_DATA | 0 |

### Latency status across wellen

| Status | Count |
|---|---|
| OK | 7 |
| WARN | 0 |
| BREACH | 0 |
| NO_DATA | 0 |
| NO_BUDGET | 0 |

**Phase-3-COMPLETE marker valid:** NO

**Aggregate audit OK:** NO

---

## 2. Per-Welle Mini-Bilanz

### 2.1 W1 v907-verify

**Substanz-Anker:**

- Welle-ID: `welle-1-v907-verify`
- Cutover-runs total: 1550
- Rust decisions: 1530 (98.71 %)
- Python-fallback decisions: 20
- Last sample at: `2026-06-10T22:30:00Z`

**Decision-Latency (ms):**

| Quantile | Value |
|---|---|
| p50 | 360 ms |
| p95 | 576 ms |
| p99 | 595 ms |
| samples n | 5 |
| budget p95 | 1500 ms |
| **status** | **OK** |

**BackendDecision-Snapshots:**

- Snapshots collected: 2
- Rust decisions total: 500, Python: 9
- Rust share: 98.23 %
- First snapshot: `2026-06-01T10:00:00Z`, last: `2026-06-02T10:00:00Z`

**Drift-Histogram:**

- Samples: 3
- Buckets: 7
- p50 drift %: 0.1
- p95 drift %: 0.145
- max drift %: 0.15
- **drift status:** **OK**

**Henrik Sign-Off:**

- Signed off at: `2026-06-25T10:00:00Z` by **henrik**
- Audit OK: YES
- Exception count: 0
- Audit findings: _none_

---

### 2.2 W2 svid-workload-identity

**Substanz-Anker:**

- Welle-ID: `welle-2-svid-workload-identity`
- Cutover-runs total: 1600
- Rust decisions: 1580 (98.75 %)
- Python-fallback decisions: 20
- Last sample at: `2026-06-10T22:30:00Z`

**Decision-Latency (ms):**

| Quantile | Value |
|---|---|
| p50 | 480 ms |
| p95 | 768 ms |
| p99 | 794 ms |
| samples n | 5 |
| budget p95 | 2000 ms |
| **status** | **OK** |

**BackendDecision-Snapshots:**

- Snapshots collected: 2
- Rust decisions total: 500, Python: 9
- Rust share: 98.23 %
- First snapshot: `2026-06-01T10:00:00Z`, last: `2026-06-02T10:00:00Z`

**Drift-Histogram:**

- Samples: 3
- Buckets: 7
- p50 drift %: 0.1
- p95 drift %: 0.145
- max drift %: 0.15
- **drift status:** **OK**

**Henrik Sign-Off:**

- Signed off at: `2026-06-25T10:00:00Z` by **henrik**
- Audit OK: YES
- Exception count: 0
- Audit findings: _none_

---

### 2.3 W3 bridge-audit-writer

**Substanz-Anker:**

- Welle-ID: `welle-3-bridge-audit-writer`
- Cutover-runs total: 1650
- Rust decisions: 1630 (98.79 %)
- Python-fallback decisions: 20
- Last sample at: `2026-06-10T22:30:00Z`

**Decision-Latency (ms):**

| Quantile | Value |
|---|---|
| p50 | 600 ms |
| p95 | 960 ms |
| p99 | 992 ms |
| samples n | 5 |
| budget p95 | 2500 ms |
| **status** | **OK** |

**BackendDecision-Snapshots:**

- Snapshots collected: 2
- Rust decisions total: 500, Python: 9
- Rust share: 98.23 %
- First snapshot: `2026-06-01T10:00:00Z`, last: `2026-06-02T10:00:00Z`

**Drift-Histogram:**

- Samples: 3
- Buckets: 7
- p50 drift %: 0.1
- p95 drift %: 0.145
- max drift %: 0.15
- **drift status:** **OK**

**Henrik Sign-Off:**

- Signed off at: `2026-06-25T10:00:00Z` by **henrik**
- Audit OK: YES
- Exception count: 0
- Audit findings: _none_

---

### 2.4 W4 state-backing

**Substanz-Anker:**

- Welle-ID: `welle-4-state-backing`
- Cutover-runs total: 80
- Rust decisions: 30 (37.50 %)
- Python-fallback decisions: 50
- Last sample at: `2026-06-12T08:50:00Z`

**Decision-Latency (ms):**

| Quantile | Value |
|---|---|
| p50 | 720 ms |
| p95 | 1152 ms |
| p99 | 1190 ms |
| samples n | 5 |
| budget p95 | 3000 ms |
| **status** | **OK** |

**BackendDecision-Snapshots:**

- Snapshots collected: 2
- Rust decisions total: 500, Python: 9
- Rust share: 98.23 %
- First snapshot: `2026-06-01T10:00:00Z`, last: `2026-06-02T10:00:00Z`

**Drift-Histogram:**

- Samples: 3
- Buckets: 7
- p50 drift %: 0.1
- p95 drift %: 0.145
- max drift %: 0.15
- **drift status:** **OK**

**Henrik Sign-Off:**

- Signed off at: `2026-06-25T10:00:00Z` by **henrik**
- Audit OK: YES
- Exception count: 0
- Audit findings: _none_

---

### 2.5 W5 lifecycle-state-machine

**Substanz-Anker:**

- Welle-ID: `welle-5-lifecycle-state-machine`
- Cutover-runs total: 80
- Rust decisions: 30 (37.50 %)
- Python-fallback decisions: 50
- Last sample at: `2026-06-12T08:50:00Z`

**Decision-Latency (ms):**

| Quantile | Value |
|---|---|
| p50 | 840 ms |
| p95 | 1344 ms |
| p99 | 1389 ms |
| samples n | 5 |
| budget p95 | 3500 ms |
| **status** | **OK** |

**BackendDecision-Snapshots:**

- Snapshots collected: 2
- Rust decisions total: 500, Python: 9
- Rust share: 98.23 %
- First snapshot: `2026-06-01T10:00:00Z`, last: `2026-06-02T10:00:00Z`

**Drift-Histogram:**

- Samples: 3
- Buckets: 7
- p50 drift %: 0.1
- p95 drift %: 0.145
- max drift %: 0.15
- **drift status:** **OK**

**Henrik Sign-Off:**

- Signed off at: `2026-06-25T10:00:00Z` by **henrik**
- Audit OK: YES
- Exception count: 0
- Audit findings: _none_

---

### 2.6 W6 subscribe-loop

**Substanz-Anker:**

- Welle-ID: `welle-6-subscribe-loop`
- Cutover-runs total: 80
- Rust decisions: 30 (37.50 %)
- Python-fallback decisions: 50
- Last sample at: `2026-06-12T08:50:00Z`

**Decision-Latency (ms):**

| Quantile | Value |
|---|---|
| p50 | 600 ms |
| p95 | 960 ms |
| p99 | 992 ms |
| samples n | 5 |
| budget p95 | 2500 ms |
| **status** | **OK** |

**BackendDecision-Snapshots:**

- Snapshots collected: 2
- Rust decisions total: 500, Python: 9
- Rust share: 98.23 %
- First snapshot: `2026-06-01T10:00:00Z`, last: `2026-06-02T10:00:00Z`

**Drift-Histogram:**

- Samples: 3
- Buckets: 7
- p50 drift %: 0.1
- p95 drift %: 0.145
- max drift %: 0.15
- **drift status:** **OK**

**Henrik Sign-Off:**

- Signed off at: `2026-06-25T10:00:00Z` by **henrik**
- Audit OK: YES
- Exception count: 0
- Audit findings: _none_

---

### 2.7 W7 recovery-workflow

**Substanz-Anker:**

- Welle-ID: `welle-7-recovery-workflow`
- Cutover-runs total: 80
- Rust decisions: 30 (37.50 %)
- Python-fallback decisions: 50
- Last sample at: `2026-06-12T08:50:00Z`

**Decision-Latency (ms):**

| Quantile | Value |
|---|---|
| p50 | 720 ms |
| p95 | 1152 ms |
| p99 | 1190 ms |
| samples n | 5 |
| budget p95 | 3000 ms |
| **status** | **OK** |

**BackendDecision-Snapshots:**

- Snapshots collected: 2
- Rust decisions total: 500, Python: 9
- Rust share: 98.23 %
- First snapshot: `2026-06-01T10:00:00Z`, last: `2026-06-02T10:00:00Z`

**Drift-Histogram:**

- Samples: 3
- Buckets: 7
- p50 drift %: 0.1
- p95 drift %: 0.145
- max drift %: 0.15
- **drift status:** **OK**

**Henrik Sign-Off:**

- _NO SIGN-OFF FILED YET_

---

## 3. Cross-Welle Coupling Bilanz

Cross-welle coupling is observed via the drift histograms in section 2 and via the aggregator failure buckets below. The two coupling questions the operator must answer:

1. **Does any welle's drift correlate with another welle's drift?** -- inspect the per-welle drift status; if two or more wellen are BREACH simultaneously the cause is likely systemic (NATS / SPIFFE / wirelang) rather than welle-local.

2. **Does the ci-aggregator wait-loop correlate with a specific sub-workflow regression?** -- the failure-bucket table below indicates which sub-workflows accumulated the most failures across the Marathon window.

### ci-aggregator wait-loop latency

| Quantile | Seconds |
|---|---|
| p50 | 915.0 |
| p95 | 1727.9999999999998 |
| p99 | 1785.6 |

### Sub-workflow failure buckets

| Sub-workflow | Failure count |
|---|---|
| wirelang suite production | 1 |
| Phase-2 Aggregator (All Gates + Cross-Gate Non-Interference) | 1 |
| production-vs-sandbox drift envelope | 1 |

---

## 4. Henrik Audit Aggregate

- Aggregate audit OK: **NO**
- Total findings across wellen: 0
- Total exception count across wellen: 0
- **Missing sign-offs:**
  - W7 recovery-workflow (`welle-7-recovery-workflow`)

### Per-welle sign-off table

| Welle | Signed off at | By | OK | Exceptions | Findings |
|---|---|---|---|---|---|
| W1 v907-verify | `2026-06-25T10:00:00Z` | henrik | YES | 0 | 0 |
| W2 svid-workload-identity | `2026-06-25T10:00:00Z` | henrik | YES | 0 | 0 |
| W3 bridge-audit-writer | `2026-06-25T10:00:00Z` | henrik | YES | 0 | 0 |
| W4 state-backing | `2026-06-25T10:00:00Z` | henrik | YES | 0 | 0 |
| W5 lifecycle-state-machine | `2026-06-25T10:00:00Z` | henrik | YES | 0 | 0 |
| W6 subscribe-loop | `2026-06-25T10:00:00Z` | henrik | YES | 0 | 0 |
| W7 recovery-workflow | _MISSING_ | _MISSING_ | _MISSING_ | _MISSING_ | _MISSING_ |

---

## 5. Phase-3-COMPLETE-Marker Validation

**Marker file is missing.** Without the marker file, the Phase-3 Marathon is not complete and Phase-4 must not start.

---

## 6. Phase-4 Follow-up Items

The following items must be carried into the Phase-4 pre-substanz aufstellung. Items are derived from this bilanz and not hand-edited; re-run the generator to update.

- W7 recovery-workflow: Henrik sign-off MISSING -- blocker for Phase-3-COMPLETE acceptance
- Phase-3-COMPLETE-marker not valid -- marker_file_missing

---

## 7. Source-of-Truth Inputs

The bilanz aggregates the following observability streams. Each path is the canonical input; the hermetic test suite overrides them with fixtures.

- `state/phase-3-marathon-state.json` (Selin #261)
- `state/aggregator-failure-rate-history.json` (Noa #251)
- `state/backend-decision-snapshots/<welle-id>.json` (per-welle)
- `state/cross-welle-drift-histograms.json` (Noa Tag-41)
- `state/welle-N-sign-off.json` (Henrik, one per welle)
- `state/phase-3-complete-marker.json` (Tomas #258)

Runbook: `docs/observability/phase-3-final-bilanz-generator-runbook.md`.

-- Noa
