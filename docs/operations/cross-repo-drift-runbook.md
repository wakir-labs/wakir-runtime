<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Cross-Repo-Drift Runbook (3-Repo Operating Manual)

**Status:** Living operations document (read by humans + parsed by tests).
**Scope:** `wakir-labs/wakir-runtime` (BUSL-1.1) ↔
`wakir-labs/wakir-protocol` (Apache-2.0 + CC-BY-4.0) ↔
`wakir-labs/wakir-verify` (Apache-2.0).
**Authored:** 2026-05-17 (Reza, EXT-AUDIT-FOLGE Tag-31, Sprint
`Cross-Repo-Drift-Gates-Doku-Sync-MINI`).
**ADR-Anker:** ADR-0062 Cut-2 / Cut-3 (protocol-substance
classification), ADR-0066 (live-telemetry observability).

---

## 1. Why this runbook exists

The cross-repo drift surface is the single largest auditor-facing
contract-integrity tripwire after license hygiene. External Audit
2026-05-17 §3.4 codified the operator demand verbatim:

> "Cross-repo drift kontrollieren — runtime ↔ protocol schema drift,
> runtime ↔ verify manifest/proof drift, test vectors shared across
> repos."

PR #105 / PR #111 / PR #126 covered the *runtime ↔ protocol* schema
edge in audit-only mode plus the Enforce-Flip readiness contract
(see [cross-repo-drift-enforce-flip-readiness.md](./cross-repo-drift-enforce-flip-readiness.md)).
This runbook extends the operator surface in three directions the
external-audit demand identifies but the Enforce-Flip-Readiness doc
does not:

1. **Verify-repo coverage** — `wakir-verify` is the third leg of the
   contract surface (Apache-2.0, BUSL-import-free verifier), and any
   drift between *its* manifest-reader / proof-types and the
   `wakir-runtime` `wat/anchor` + `wat/verify` substrate is just as
   silent and just as audit-flagged.
2. **Test-vector parallel inventory** — both repos ship parallel
   `tests/fixtures/` trees with substantive cryptographic vectors
   (BIP32, SLIP-0010, JCS-leaf, AIP-document, FTD, DID-document).
   Drift here is harder to spot than schema drift but causes the
   same disagreement-without-cause for downstream adopters.
3. **Living drift-map** — the Enforce-Flip-Readiness doc pinned a
   Day-1 snapshot (`6/10` drift). This runbook re-measures the
   drift-map at each external-audit-follow-up Welle and records the
   trajectory, so a future auditor can see *change* not just *state*.

---

## 2. Drift surface inventory (which boundaries we audit)

The cross-repo drift surface decomposes into four contract zones.
Each zone has its own enforcement posture, owner, and CI lane.

### 2.1 Zone-A — Runtime ↔ Protocol mirror-pair schemas

* **CI lane:** `.github/workflows/cross-repo-drift-audit.yml`
  (PR #105 / #111).
* **Enforcement:** Audit-only (`CROSS_REPO_DRIFT_ENFORCE='false'`).
  Flip-gated by §5 of [cross-repo-drift-enforce-flip-readiness.md](./cross-repo-drift-enforce-flip-readiness.md).
* **Required-status-check:** *not yet* — added after Enforce-Flip
  per Step-7 of the Enforce-Flip-Readiness doc.
* **Inventory:** ten mirror-pairs hard-coded in `pairs=( ... )`.
* **Allowlist:** `.cross-repo-drift-allowlist.yaml`. Currently
  **empty** by design (ADR-0062 Cut-2 follow-up).
* **Owner:** Reza (substance) + Tomás (Cross-Review-Zone-3, OTS-
  Schema-Anker compatibility).

### 2.2 Zone-B — Runtime ↔ Protocol shared test-vector fixtures

* **CI lane:** *not yet automated.* Manual side-by-side `sha256sum`
  diff at each external-audit-follow-up Welle (see §4 below).
* **Enforcement:** Doku-only. Drift is recorded in this runbook §3
  and resolved manually by the affected vector's owner.
* **Required-status-check:** none (intentional — cryptographic
  vectors evolve at a different cadence than schemas).
* **Inventory:** ten parallel fixture sets present in both repos
  (see §3.2 below).
* **Owner:** Reza (Identity-Substrate + Wirelang vectors), Kai (WAT
  vectors), Tomás (Cross-Review-Zone-3 boundary).

### 2.3 Zone-C — Runtime ↔ Verify manifest/proof types

* **CI lane:** *not yet automated.* See §3.3 for the manual drift-
  check methodology and the rationale for keeping this manual.
* **Enforcement:** Doku-only. Drift is recorded in this runbook
  §3.3 and resolved manually.
* **Required-status-check:** none.
* **Inventory:** four shape-equivalence pairs (`wat/verify/manifest_v2.py`
  ↔ `wakir_verify/manifest.py`, etc.).
* **Owner:** Kai (WAT-Layer-4 substrate) + Reza (Cross-Review on
  cryptographic equivalence) + Tomás (OTS-Schema-Anker
  compatibility).

### 2.4 Zone-D — Wirelang spec prose docs

* **CI lane:** none. Cadence-mismatched with schemas (prose changes
  at sprint-cadence, schemas at hours-cadence).
* **Enforcement:** Status-log only.
* **Inventory:** see [cross-repo-drift-mirror-pair-status.md](./cross-repo-drift-mirror-pair-status.md).
* **Owner:** Reza.

---

## 3. Current drift-map (measured 2026-05-17, Reza)

The §3.x tables below are **point-in-time measurements** against the
following baselines:

* `wakir-runtime` main tip: `4e9a2eb` (post-Welle-3 telemetry).
* `wakir-protocol` main tip: `575898c` (Cut-1 CI bootstrap).
* `wakir-verify` main tip: `24e7df1` (Cut-1 README final).

Re-measurement methodology: §4 below. Trajectory log: §6 below.

### 3.1 Zone-A drift-map — Runtime ↔ Protocol schemas (TODAY)

| # | Runtime path | Protocol path | Status | Day-1 status (PR #126) | Trajectory |
|---|---|---|---|---|---|
| 1 | `wirelang/schemas/layer-0-transport.json` | `wakir_protocol/schemas/layer-0-transport.json` | `DRIFT` | `drift` | unchanged |
| 2 | `wirelang/schemas/layer-1-wire.json` | `wakir_protocol/schemas/layer-1-wire.json` | `ok` | `drift` | resolved |
| 3 | `wirelang/schemas/layer-2-semantic.json` | `wakir_protocol/schemas/layer-2-semantic.json` | `DRIFT` | `drift` | unchanged |
| 4 | `wirelang/schemas/layer-3-capability-token.json` | `wakir_protocol/schemas/layer-3-capability-token.json` | `DRIFT` | `clean` | **regressed** |
| 5 | `wirelang/schemas/aip-document.json` | `wakir_protocol/schemas/aip-document.json` | `DRIFT` | `drift` | unchanged |
| 6 | `wirelang/schemas/datalog-caveat.json` | `wakir_protocol/schemas/datalog-caveat.json` | `ok` | `clean` | unchanged |
| 7 | `wirelang/schemas/federation-trust-document.json` | `wakir_protocol/schemas/federation-trust-document.json` | `DRIFT` | `clean` | **regressed** |
| 8 | `wirelang/canonical/caveat_set.py` | `wakir_protocol/canonical/caveat_set.py` | `DRIFT` | `drift` | unchanged |
| 9 | `wirelang/identity/aip_document.py` | `wakir_protocol/identity_substrate/aip_document.py` | `ok` | `drift` | resolved |
| 10 | `wirelang/identity/dns_anchor.py` | `wakir_protocol/identity_substrate/dns_anchor.py` | `ok` | `clean` | unchanged |

**Tally TODAY: `ok=4`, `DRIFT=6`, `missing=0`.**
**Tally Day-1 (PR #126): `ok=4`, `drift=6`, `missing=0`.**

Net drift-count is unchanged (`6 = 6`), but the *identity* of the
six drift rows has shifted: rows 2 and 9 resolved, rows 4 and 7
regressed. This is exactly the kind of silent-equilibrium-with-
churn that the audit workflow was built to detect, and exactly
why Step-1 of the Enforce-Flip-Readiness doc requires a *new
baseline snapshot* on the day of flip — yesterday's drift-set is
not today's drift-set.

**Action items spawned by this measurement:**

* Pair `4` (Layer-3 capability-token) regression — open a follow-up
  PR to determine which side is authoritative and apply the
  appropriate `re-sync-*-from-*` strategy per Enforce-Flip-
  Readiness §3. Owner: Reza.
* Pair `7` (federation-trust-document) regression — same
  treatment. Owner: Reza.
* Pair `8` (canonical caveat-set) still drifting on Day-31 —
  confirm SPDX-header-only-vs-substance with side-by-side diff
  before admitting to allowlist per `allowlist-spdx-header-only`
  strategy. Owner: Tomás.

### 3.2 Zone-B drift-map — Runtime ↔ Protocol shared fixtures (TODAY)

Measured against the same Day-31 baselines. The fixture-set names
are common to both repos but the path conventions differ between
sides — see the path-prefix column.

| Fixture set | Runtime prefix | Protocol prefix | `ok` | `DRIFT` | `only-rt` | `only-pt` | Notes |
|---|---|---|---|---|---|---|---|
| `aip-document-vectors` | `tests/fixtures/` | `tests/fixtures/` | 4 | 0 | 0 | 0 | clean |
| `bip32-vectors` | `tests/fixtures/` | `tests/fixtures/` | 3 | 0 | 0 | 0 | clean |
| `did-document-vectors` | `tests/fixtures/` | `tests/fixtures/` | 3 | 0 | 0 | 0 | clean |
| `jcs-leaf-vectors` | `tests/fixtures/` | `tests/fixtures/` | 4 | 1 | 0 | 0 | **vector-4-multi-utf8.json** drifts — UTF-8-native (runtime) vs `\uXXXX`-escape (protocol) in the `_notes` field. Substance-equivalent JSON but byte-divergent. Resolution: re-sync-protocol-from-runtime to keep canonical UTF-8 bytes on the published side. |
| `schema-registry/caveat-override-event-export-v1` | `tests/fixtures/` | `tests/fixtures/` | 0 | 2 | 0 | 0 | **Substance drift** — `schema_file_sha256` and `schema_file_bytes` mismatch (6988 vs. 6907). This is real drift, not header drift. Resolution: re-sync per the authoritative side after Cross-Review-Zone-3. |
| `slip0010-ed25519-vectors` | `tests/fixtures/` | `tests/fixtures/` | 2 | 0 | 0 | 0 | clean |
| `tv-w-1` (Wirelang pin-pack) | `wirelang/tests/fixtures/` | `tests/fixtures/` | 2 | 0 | 0 | 0 | clean (path-rename pair) |
| `tv-w-2` (Wirelang pin-pack) | `wirelang/tests/fixtures/` | `tests/fixtures/` | 2 | 0 | 0 | 0 | clean (path-rename pair) |
| `wakir-ftd-vectors` | `tests/fixtures/` | `tests/fixtures/` | 4 | 0 | 0 | 0 | clean |
| `persona_definitions` | `wirelang/tests/fixtures/` | `tests/fixtures/` | 8 | 0 | 0 | 0 | clean (path-rename pair) |

**Tally TODAY: `ok=32`, `DRIFT=3`, `only-side=0`, `missing-sets=0`.**

This is a strong signal: cryptographic test vectors are largely
byte-synced across runtime and protocol. The three drifters are
two `schema-registry` rows (substance) and one `jcs-leaf-vector`
row (encoding only).

**Action items:**

* `jcs-leaf-vectors/vector-4-multi-utf8.json` — re-sync to the
  runtime version (UTF-8-native is the canonical JCS-emit per
  RFC 8785). Owner: Reza.
* `schema-registry/caveat-override-event-export-v1` rows — Reza
  + Tomás side-by-side diff to identify which schema version is
  authoritative; the 81-byte size delta (6988 vs. 6907) suggests
  a partial commit on one side.

### 3.3 Zone-C drift-map — Runtime ↔ Verify manifest/proof (TODAY)

The `wakir-verify` repo (Apache-2.0, BUSL-import-free verifier
reference) replicates the *shape* — not the byte content — of the
manifest/proof types implemented in `wakir-runtime/wat/`. A 1:1
byte-mirror would defeat the BUSL-isolation purpose of the verify
repo. Instead the audit-surface here is **shape-equivalence**:
the verifier must accept manifests / proofs produced by the runtime
without re-implementing the runtime's BUSL-only optimizations.

The four shape-equivalence pairs are:

| # | Runtime path | Verify path | Equivalence type |
|---|---|---|---|
| 1 | `wat/anchor/ots_anchor.py` (write side) | `wakir_verify/ots_verify.py` (read side) | round-trip OTS-blob shape |
| 2 | `wat/verify/manifest_v2.py` | `wakir_verify/manifest.py` | manifest reader contract |
| 3 | `wat/merkle/aggregator.py` | `wakir_verify/merkle_proof.py` + `wakir_verify/aggregator.py` | Merkle proof shape |
| 4 | `wat/identity/manifest_signing.py` | `wakir_verify/format.py` | signature format |

**Drift methodology:** for each pair, run the verifier-side test
suite against a runtime-emitted artifact (a real WAT-manifest-v2
under `tests/fixtures/wat-tv2-real-signed/` is the canonical
witness). The verifier-test-suite-passes-against-runtime-artifact
predicate is the contract. Byte-level diff is meaningless here —
the BUSL and Apache sides are *intended* to diverge in source.

**TODAY (2026-05-17) shape-equivalence verdict:** *unknown* — this
runbook is the first welle in which Zone-C is named as a contract
zone. No automated CI lane exists yet. **Action:** spawn follow-up
sprint `Cross-Repo-Verify-Shape-Equivalence-MINI` to build the
CI lane that runs `pytest` from `wakir-verify` against the runtime-
shipped `wat-tv2-real-signed` fixture. Owner: Kai (WAT) + Reza
(Cross-Review boundary).

### 3.4 Zone-D drift-map — Wirelang prose spec

Tracked in [cross-repo-drift-mirror-pair-status.md](./cross-repo-drift-mirror-pair-status.md).
TODAY: `wirelang-spec-v0-2.md` was byte-identical at the Sprint-
Wirelang-Spec-Sync-Cross-Repo-MINI snapshot (2026-05-16) per that
file's row. No new prose-spec drift verifications since.

---

## 4. Drift re-measurement methodology

This runbook is a **living document**: §3 must be re-measured at each
external-audit-follow-up Welle and the new measurement appended to §6
without rewriting older rows.

### 4.1 Zone-A measurement (5 min, fully scripted)

```bash
# From an up-to-date wakir-runtime worktree.
git fetch origin main
git checkout origin/main
rm -rf /tmp/wakir-protocol-drift-snapshot
git clone --depth=1 --branch main \
  https://github.com/wakir-labs/wakir-protocol.git \
  /tmp/wakir-protocol-drift-snapshot

# Extract the literal pairs=() array from the workflow and diff.
python3 scripts/cross_repo_drift_snapshot.py \
  --runtime-root . \
  --protocol-root /tmp/wakir-protocol-drift-snapshot \
  --output docs/operations/cross-repo-drift-runbook-snapshot-$(date -I).md
```

(Script does not exist yet — placeholder for the follow-up Welle. For
TODAY's measurement Reza ran the equivalent shell inline; see §6 log.)

### 4.2 Zone-B measurement (10 min, semi-scripted)

The fixture-set list is enumerated by directory-name in both repos.
A future welle should add `--include-fixtures` flag to the same
snapshot script; for TODAY the operator runs the inline shell
recorded in this PR's commit message.

### 4.3 Zone-C measurement (manual until CI lane exists)

1. Check out a clean `wakir-runtime` worktree.
2. Locate the canonical witness artefact:
   `tests/fixtures/wat-tv2-real-signed/` (a real-WAT-manifest-v2
   emission with full signature chain).
3. Check out a clean `wakir-verify` worktree.
4. Copy the runtime-emitted artefact into `wakir-verify/tests/`
   under a witness-import name.
5. Run `pytest tests/ -k manifest_v2` from the verify worktree.
6. Record pass/fail and any divergence in §3.3 of this runbook.

### 4.4 Zone-D measurement (per-sprint, manual)

Append a new row to [cross-repo-drift-mirror-pair-status.md](./cross-repo-drift-mirror-pair-status.md)
each time a Wirelang prose spec change ships across both repos.
The status-log already encodes the methodology.

---

## 5. Allowlist audit (TODAY)

The `.cross-repo-drift-allowlist.yaml` is **empty** as of
2026-05-17. Status:

| Item | Value |
|---|---|
| `len(allow)` | 0 |
| Last audit | 2026-05-17 (Reza, EXT-AUDIT-FOLGE Tag-31) |
| Tech-debt rows | none — empty list cannot carry debt |
| Justification | ADR-0062 Cut-2 follow-up: baseline drift is observed in audit-only mode before any waiver is admitted. Until §4 of the Enforce-Flip-Readiness doc completes Steps 2–4, the allowlist remains empty. |
| Next refresh trigger | Step-2 of Enforce-Flip-Readiness (SPDX-header-only allowlist seed for current rows `8` if confirmed SPDX-only). |

**No tech-debt to flush from the allowlist on Tag-31.** The audit
demand "are the [allowlist entries] still begründbar oder Tech-
Schuld?" resolves to "no entries exist; the empty-allowlist posture
is intentional and ADR-anchored". The next refresh window opens
only when the Enforce-Flip cleanup sequence (Enforce-Flip-Readiness
§4) advances to Step 2.

---

## 6. Trajectory log (append-only)

Each measurement welle appends a new section here. **Do not edit
older entries** — they are the audit-trail for the drift trajectory.

### 6.1 Day-1 (2026-05-16, Tomás, PR #126)

* Zone-A: `ok=4, drift=6, missing=0`.
* Zone-B: not measured.
* Zone-C: not measured.
* Zone-D: clean (`wirelang-spec-v0-2.md` byte-identical).
* Source: [cross-repo-drift-enforce-flip-readiness.md](./cross-repo-drift-enforce-flip-readiness.md) §2.

### 6.2 Day-31 (2026-05-17, Reza, this PR)

* Zone-A: `ok=4, DRIFT=6, missing=0`. Identity of drift rows
  shifted vs. Day-1 (rows 2 and 9 resolved; rows 4 and 7
  regressed). Net count unchanged.
* Zone-B: `ok=32, DRIFT=3, only-side=0`. Three drifters:
  `jcs-leaf-vector-4-multi-utf8.json` (encoding-only) and two
  `schema-registry/caveat-override-event-export-v1/` rows
  (substance, `~80-byte size delta`).
* Zone-C: shape-equivalence audit not yet CI-automated;
  Zone-C is named here for the first time. Spawn follow-up
  sprint to add the CI lane.
* Zone-D: no change since 2026-05-16.
* Source: this runbook, EXT-AUDIT-FOLGE Tag-31.
* Cross-Review-Zone-3 sign-off: pending Tomás (Tag-31 outbox).

---

## 7. Cross-references

* [cross-repo-drift-enforce-flip-readiness.md](./cross-repo-drift-enforce-flip-readiness.md)
  — Tomás's operator checklist for the Enforce-Flip itself
  (Steps 1–8). This runbook is the *measurement+map* companion;
  the Enforce-Flip-Readiness doc is the *flip-procedure* companion.
* [cross-repo-drift-mirror-pair-status.md](./cross-repo-drift-mirror-pair-status.md)
  — Reza's status log for Zone-D prose-spec sync verifications.
* [branch-protection-required-status-checks.md](./branch-protection-required-status-checks.md)
  — what gets added to required-status-checks after the
  Enforce-Flip per Step-7.
* `.github/workflows/cross-repo-drift-audit.yml` — the Zone-A CI lane.
* `.cross-repo-drift-allowlist.yaml` — the Zone-A waiver contract.
* `tests/infra/test_cross_repo_drift_audit.py` — hermetic tests for
  the audit-workflow logic.
* `tests/infra/test_cross_repo_drift_enforce_readiness.py` — pins
  the Enforce-Flip readiness contract.
* `tests/infra/test_cross_repo_drift_state.py` — pins TODAY's
  Zone-A inventory, Zone-B fixture parallelism, Zone-C shape-
  equivalence pair list, and this runbook's living-doc schema.
* ADR-0062 Cut-2 — protocol substance classification (the canonical
  "which files are mirrored?" decision).

---

— Reza
