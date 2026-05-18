<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Cross-repo sync audit refresh — 2026-05-19 (Tag-52)

Tag-52 Reza Cross-Repo-Sync-Audit refresh between `wakir-runtime`
(BUSL-dominant) and `wakir-protocol` (Apache-2.0 + CC-BY-4.0).

This refresh re-runs the Tag-42 audit (PR #271, report
`2026-05-18-runtime-protocol-sync.md`) on the current main-tip of
both repos, 1 day calendar-time after the original (the Tag-42
report itself was written 2026-05-18; the refresh window the
auftrag references is the Tag-X marathon day index, not the
calendar delta). The deliverable answers three questions:

1. What is the **current** drift bilanz (ok / DRIFT / missing)?
2. Are any of the **6 Tag-42 baseline drift items** now resolved?
3. Have any **new** drift items appeared in the audited surface?

## Audit baselines

| Field | Tag-42 (2026-05-18) | Tag-52 refresh (2026-05-19) |
| --- | --- | --- |
| Runtime root | `/var/home/fred/AI-Corp/.worktree-reza-tag42-cross-repo-audit-runtime` | `/var/home/fred/AI-Corp/.worktree-reza-tag52-cross-repo-refresh-runtime` |
| Runtime HEAD | `64b1c170418d` | `b16e2631da2f` |
| Protocol root | `/tmp/wakir-protocol-tag42` | `/tmp/wakir-protocol-tag52` |
| Protocol HEAD | `9eca1e2d4b5b` | `9eca1e2d4b5b` |
| Enforce mode | `False` (audit-only) | `False` (audit-only) |
| Allowlist status | `ok` (empty) | `ok` (empty) |

Notable: protocol HEAD has not moved since Tag-42 (still `9eca1e2`).
Runtime HEAD has advanced ~30 commits but **none touch the audited
mirror-pair surface** — verified by `git log a87d427..HEAD --
wirelang/schemas wirelang/canonical wirelang/identity/aip_document.py
wirelang/identity/dns_anchor.py` returning only the Welle-6+7
Pre-Cutover-Sanity PR (PR #275, smoke probes, not in mirror table).

## Mirror-pair drift table (substance class 1-3)

| Status | Class | Runtime | Protocol | r-SHA | p-SHA |
|---|---|---|---|---|---|
| DRIFT | layer-0-schema | `wirelang/schemas/layer-0-transport.json` | `wakir_protocol/schemas/layer-0-transport.json` | `714f9d42b8fc` | `5e95e26c127b` |
| ok | layer-1-schema | `wirelang/schemas/layer-1-wire.json` | `wakir_protocol/schemas/layer-1-wire.json` | `15a8f97f8925` | `15a8f97f8925` |
| DRIFT | layer-2-schema | `wirelang/schemas/layer-2-semantic.json` | `wakir_protocol/schemas/layer-2-semantic.json` | `c0f54b92f8ab` | `c9519af54347` |
| DRIFT | layer-3-schema | `wirelang/schemas/layer-3-capability-token.json` | `wakir_protocol/schemas/layer-3-capability-token.json` | `2b4eb8d067f5` | `4d8e064c8133` |
| DRIFT | aip | `wirelang/schemas/aip-document.json` | `wakir_protocol/schemas/aip-document.json` | `cec984969de3` | `0219e3c0c39a` |
| ok | aip | `wirelang/identity/aip_document.py` | `wakir_protocol/identity_substrate/aip_document.py` | `ad520986ab69` | `ad520986ab69` |
| ok | aip | `wirelang/identity/dns_anchor.py` | `wakir_protocol/identity_substrate/dns_anchor.py` | `9e3faabca58e` | `9e3faabca58e` |
| ok | capability | `wirelang/schemas/datalog-caveat.json` | `wakir_protocol/schemas/datalog-caveat.json` | `dfe35884bbb9` | `dfe35884bbb9` |
| DRIFT | capability | `wirelang/schemas/federation-trust-document.json` | `wakir_protocol/schemas/federation-trust-document.json` | `d1b09c7bc815` | `b1f4cc169a08` |
| DRIFT | capability | `wirelang/canonical/caveat_set.py` | `wakir_protocol/canonical/caveat_set.py` | `a2155411ef68` | `f7d391fab9e6` |

### Mirror-pair tally

- ok: 4
- drift (un-allowlisted): 6
- drift (allowlisted): 0
- missing on either side: 0

## Tag-42 baseline diff (refresh delta)

| Pair | Tag-42 status | Tag-52 status | r-SHA delta | p-SHA delta |
| --- | --- | --- | --- | --- |
| `layer-0-transport.json` | DRIFT | DRIFT | unchanged | unchanged |
| `layer-1-wire.json` | ok | ok | unchanged | unchanged |
| `layer-2-semantic.json` | DRIFT | DRIFT | unchanged | unchanged |
| `layer-3-capability-token.json` | DRIFT | DRIFT | unchanged | unchanged |
| `aip-document.json` | DRIFT | DRIFT | unchanged | unchanged |
| `aip_document.py` | ok | ok | unchanged | unchanged |
| `dns_anchor.py` | ok | ok | unchanged | unchanged |
| `datalog-caveat.json` | ok | ok | unchanged | unchanged |
| `federation-trust-document.json` | DRIFT | DRIFT | unchanged | unchanged |
| `canonical/caveat_set.py` | DRIFT | DRIFT | unchanged | unchanged |

**Refresh-delta tally**

- newly fixed since Tag-42: **0**
- newly drifting since Tag-42: **0**
- still drifting: **6** (same set, same SHAs on both sides)
- pair-table additions/removals: **0** (MIRROR_PAIRS unchanged)
- pair-table renames: **0**

## Drift-item type classification (new in Tag-52)

The Tag-42 baseline established the drift inventory but did not
sub-classify the 6 drift items by drift *type*. The refresh
characterizes each item to inform the allowlist-admission decision
(per `docs/operations/cross-repo-drift-enforce-flip-readiness.md`
Step-2):

| # | Pair | Drift type | Semantic-equal? | Allowlist admission posture |
| --- | --- | --- | --- | --- |
| 1 | `layer-0-transport.json` | JSON-formatting (inline-array vs. multiline-array) | **yes** (verified via `json.load`+`==`) | candidate for `reason: json-formatting-only`, `follow_up: format-normalisation-sweep` |
| 2 | `layer-2-semantic.json` | JSON-formatting (inline-array vs. multiline-array) | **yes** | same as #1 |
| 3 | `layer-3-capability-token.json` | JSON-formatting (inline-array vs. multiline-array) | **yes** | same as #1 |
| 4 | `aip-document.json` | JSON-formatting (inline-array vs. multiline-array, inline-object vs. multiline-object) | **yes** | same as #1 |
| 5 | `federation-trust-document.json` | JSON-formatting (inline-array vs. multiline-array, inline-object vs. multiline-object) | **yes** | same as #1 |
| 6 | `canonical/caveat_set.py` | Import-path delta (`wirelang.identity._jcs_pure` ↔ `wakir_protocol.identity_substrate._jcs_pure`) | **yes** (functionally — same `canonicalize` symbol resolved through different package roots) | candidate for `reason: package-root-import-path delta (BUSL wirelang.* vs Apache wakir_protocol.*)`, `follow_up: permanent` |

**Verification commands** (reproducible from this report):

```bash
# JSON semantic equivalence (items 1-5)
for r in wirelang/schemas/layer-0-transport.json \
         wirelang/schemas/layer-2-semantic.json \
         wirelang/schemas/layer-3-capability-token.json \
         wirelang/schemas/aip-document.json \
         wirelang/schemas/federation-trust-document.json ; do
  p="wakir_protocol/schemas/$(basename "$r")"
  python3 -c "import json,sys; a=json.load(open('$r'));
              b=json.load(open('/tmp/wakir-protocol-tag52/$p'));
              print('$r', a==b)"
done

# Import-path delta (item 6)
diff wirelang/canonical/caveat_set.py \
     /tmp/wakir-protocol-tag52/wakir_protocol/canonical/caveat_set.py
# Expected: 2 hunks, both `from wirelang.identity._jcs_pure` vs.
# `from wakir_protocol.identity_substrate._jcs_pure`.
```

## ADR-0066 Welle-Substanz consistency (class 4)

| Welle | Smoke | Runbook | Validation WF | Modules | Protocol mention | Status |
|---|---|---|---|---|---|---|
| 1 | Y | Y | Y | Y | — | consistent-runtime-only |
| 2 | Y | Y | Y | Y | — | consistent-runtime-only |
| 3 | Y | Y | Y | Y | — | consistent-runtime-only |
| 4 | Y | Y | Y | Y/Y | — | consistent-runtime-only |
| 5 | Y | Y | Y | Y/Y | — | consistent-runtime-only |
| 6 | Y | Y | Y | Y | — | consistent-runtime-only |
| 7 | Y | Y | Y | Y | — | consistent-runtime-only |

### Welle tally

- ok (runtime-complete + protocol-mentioned): 0
- consistent (runtime-complete, protocol doc absent): 7
- protocol-doc-missing-mention: 0
- incomplete runtime triad: 0

Tag-42 status: 7× `consistent-runtime-only`. Tag-52 refresh: 7×
`consistent-runtime-only`. **No welle-substance delta.**

## Recommended mirror-sync actions

The refresh-delta tally (0 fixed, 0 new) confirms the Tag-42 drift
inventory is **stable and structurally bounded**. Per the enforce-
flip readiness contract:

1. **Drift items 1-5 (JSON-formatting only)** are candidates for a
   one-shot **format-normalisation sweep** — re-emit both sides via
   `json.dumps(..., indent=2, sort_keys=False)` to produce a single
   canonical form. Owner: Reza (matrix-lead Cross-Review-Zone-3),
   timing: optional pre-flip housekeeping, not blocking.

2. **Drift item 6 (import-path delta)** is structurally-permanent
   and an allowlist admission, not a sync action. The two repos
   intentionally use different package roots
   (`wirelang.identity._jcs_pure` BUSL vs.
   `wakir_protocol.identity_substrate._jcs_pure` Apache-2.0).
   Recommended allowlist entry:

   ```yaml
   - runtime:  wirelang/canonical/caveat_set.py
     protocol: wakir_protocol/canonical/caveat_set.py
     reason:   package-root import-path delta (BUSL wirelang.* vs Apache wakir_protocol.*)
     follow_up: permanent
   ```

3. **No new items** require Welle-substance protocol-side mirror
   (Cut-2 boundary unchanged).

## Phase-3-Marathon cross-repo readiness

- **Status: STABLE-BLOCKED.** The drift bilanz has not regressed in
  the ~30 main-tip commits since Tag-42 (no audited mirror-pair
  surface was touched), so the **scope of the enforce-flip
  blocker is unchanged**. The 6 drift items remain the same 6
  items, with the same SHAs on both sides. Phase-3-Marathon
  cross-repo gate remains BLOCKED until either:
  - all 6 items are normalised (sync sweep), or
  - all 6 items are admitted into `.cross-repo-drift-allowlist.yaml`
    with named reasons and follow-up references.

- The refresh-delta property `stable=true` (no churn) is itself a
  positive signal: the audited surface is **dormant**, not
  silently drifting. The CI tripwire workflow has held the line
  since Tag-42.

## Cross-references

- Tag-42 baseline: `reports/cross-repo-audit/2026-05-18-runtime-protocol-sync.md`
  (PR #271).
- ADR-0062 Cut-2 protocol-substance classification
  (`docs/decisions/cut2-protocol-substance-classification.md`).
- ADR-0066 Welle-Substanz roadmap.
- `.github/workflows/cross-repo-drift-audit.yml` (CI tripwire,
  audit-only at the time of this refresh).
- `.cross-repo-drift-allowlist.yaml` (CI allowlist, still empty).
- `docs/operations/cross-repo-drift-runbook.md`.
- `docs/operations/cross-repo-drift-enforce-flip-readiness.md`.
- `docs/operations/cross-repo-drift-mirror-pair-status.md`.

— Reza
