<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Cross-repo sync audit — operator documentation

Companion documentation for `scripts/audit/cross-repo-sync-audit.py`
(Tag-42, Reza). The audit is the **local / offline / pre-CI** twin
of the GitHub Actions workflow
`.github/workflows/cross-repo-drift-audit.yml`.

## 1. When to run it

| Trigger | Mode |
| --- | --- |
| Pre-PR self-review when touching `wirelang/schemas/**`, `wirelang/canonical/**`, `wirelang/identity/**` | audit-only |
| Reza+Tomás Cross-Review-Zone-3 (OTS-Schema-Anker compatibility) sessions | audit-only, with `--report-path` for a snapshot |
| Tag-N closeout — verify cross-repo readiness for the next welle | audit-only |
| Enforce-flip readiness gate (one-way migration to enforce=true) | `--enforce` |
| Whitepaper / external-audit due-diligence packaging | audit-only with `--report-path` + `--json` |

The script is **stdlib-only**. No PyYAML, no requests, no git
invocations at audit time — `--protocol-root` points at a worktree
that the operator has already cloned/pulled.

## 2. Invocation

```bash
# Minimal audit-only run against a checked-out protocol clone.
python3 scripts/audit/cross-repo-sync-audit.py \
  --runtime-root . \
  --protocol-root /tmp/wakir-protocol-tag42

# Generate the Tag-42 deliverable report:
python3 scripts/audit/cross-repo-sync-audit.py \
  --runtime-root . \
  --protocol-root /tmp/wakir-protocol-tag42 \
  --report-path reports/cross-repo-audit/2026-05-18-runtime-protocol-sync.md \
  --json reports/cross-repo-audit/2026-05-18-runtime-protocol-sync.json \
  --date 2026-05-18

# Enforce-mode (for the readiness flip):
python3 scripts/audit/cross-repo-sync-audit.py \
  --runtime-root . \
  --protocol-root /tmp/wakir-protocol-tag42 \
  --enforce

# Welle-substance-only (no protocol root): synthesizes
# missing-protocol rows for the mirror pairs and runs the
# class-4 (welle triad) check against runtime only. Useful for
# pre-flight when offline.
python3 scripts/audit/cross-repo-sync-audit.py --runtime-root .
```

## 3. What it audits

### 3.1 Mirror-pair drift (substance classes 1–3)

Ten file pairs are byte-hashed (SHA-256) on each side and compared.
The table is **kept in lock-step with the CI workflow's `pairs=(
... )` array** — any addition or rename touches both files. The
classes are:

* `layer-{0,1,2,3}-schema` — Wirelang Layer-0/1/2/3 JSON Schemas
* `aip` — AIP-Document JSON Schema + Python primitives
  (`aip_document.py`, `dns_anchor.py`)
* `capability` — datalog-caveat schema, federation-trust-document
  schema, canonical caveat-set (`caveat_set.py`)

Status taxonomy:

| Status | Meaning |
| --- | --- |
| `ok` | Bytes identical. |
| `DRIFT` | Bytes differ and no allowlist entry matches. |
| `drift-allowed` | Bytes differ, but `.cross-repo-drift-allowlist.yaml` has an explicit waiver for this exact (runtime, protocol) tuple. |
| `missing-runtime` | Runtime file absent. |
| `missing-protocol` | Protocol counterpart absent. |
| `missing-both` | Both sides absent. |

### 3.2 ADR-0066 Welle-Substanz consistency (substance class 4)

Per ADR-0062 Cut-2, the runtime repo owns the *operational*
welle-substance artefacts (smoke scripts, runbooks, validation
workflows, Phase-3a module references). The protocol repo does
NOT mirror these byte-for-byte — that would invert the Cut-2
boundary. Instead, the audit verifies:

1. The runtime triad is **complete** for every welle (smoke +
   runbook + validation workflow + at least one Phase-3a module
   directory present).
2. If a protocol-side `docs/welle-substance.md` exists, it
   **mentions every welle** by canonical id (`welle-1` ...
   `welle-7`). This is a consistency tripwire, not a byte-mirror.

Welle status taxonomy:

| Status | Meaning |
| --- | --- |
| `ok` | Runtime triad complete AND protocol welle-substance doc names this welle. |
| `consistent-runtime-only` | Runtime triad complete; protocol welle-substance doc not present. Cut-2-compliant. |
| `protocol-doc-missing-mention` | Runtime triad complete; protocol welle-substance doc exists but does not name this welle. Info-level finding. |
| `incomplete-runtime` | Runtime triad has at least one missing element. |

## 4. Allowlist format

Read from `.cross-repo-drift-allowlist.yaml` at the runtime repo
root (override with `--allowlist`).

```yaml
# allow: []                # inline-empty (no waivers)
# OR
allow:
  - runtime:  wirelang/schemas/example.json
    protocol: wakir_protocol/schemas/example.json
    reason:   SPDX-header-only delta (BUSL-1.1 vs Apache-2.0)
    follow_up: permanent
```

`reason` and `follow_up` are documented but not load-bearing for
the audit logic itself. Anything outside the documented shape is
reported as `__MALFORMED__`:

* Audit-only mode: the malformed allowlist is reported on stderr
  and treated as empty (matches the CI workflow's soft-fail).
* `--enforce` mode: a malformed allowlist is a hard fail (exit 1).

The minimal stdlib YAML subset parser accepts:

* `allow: []` (inline empty)
* `allow:` followed by an indented list of mappings with
  `runtime:`, `protocol:`, and optional `reason:` / `follow_up:`
  keys.

The parser **does not** accept anchors, flow mappings,
multi-line scalars, or any key outside the documented set. This
is by design — the allowlist is a load-bearing contract, not a
free-form text file.

## 5. Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Clean (or drift + audit-only mode). |
| 1 | Enforce mode + un-allowlisted drift / missing pair (with protocol root) / incomplete runtime triad / malformed allowlist. |
| 2 | Invocation error — missing or non-directory `--runtime-root` / `--protocol-root`. |

Enforce mode WITHOUT `--protocol-root` does NOT fail on the
synthesized missing-protocol rows. This is intentional: the
"no protocol root" invocation is a runtime-only triad audit,
not a mirror audit.

## 6. Outputs

* **stdout** — one-line summary block (`mirror-pairs: ok=... drift=... allowed=... missing=...` and `welle-substance: ok=... ...`) plus per-entry warnings for non-ok rows.
* **`--report-path`** — markdown report mirroring the CI job-summary table, plus Recommended-Actions + Phase-3-Marathon-Readiness sections. Suggested location: `reports/cross-repo-audit/<DATE>-runtime-protocol-sync.md`. The Tag-42 deliverable is at `reports/cross-repo-audit/2026-05-18-runtime-protocol-sync.md`.
* **`--json`** — machine-readable tally for downstream dashboards.

## 7. Cross-references

* CI tripwire: `.github/workflows/cross-repo-drift-audit.yml`
* Allowlist file: `.cross-repo-drift-allowlist.yaml`
* Mirror-pair status log: `docs/operations/cross-repo-drift-mirror-pair-status.md`
* Drift runbook: `docs/operations/cross-repo-drift-runbook.md`
* Enforce-flip readiness: `docs/operations/cross-repo-drift-enforce-flip-readiness.md`
* ADR-0062 Cut-2 protocol-substance classification:
  `docs/decisions/cut2-protocol-substance-classification.md`

## 8. Maintenance

When adding a mirror pair:

1. Add the new row in **both** places — `MIRROR_PAIRS` in
   `scripts/audit/cross-repo-sync-audit.py` AND the `pairs=( ... )`
   array in `.github/workflows/cross-repo-drift-audit.yml`.
2. Update `docs/operations/cross-repo-drift-mirror-pair-status.md`
   with a baseline-SHA row.
3. If the new pair is expected to drift on day-one (e.g., a
   different SPDX header), seed `.cross-repo-drift-allowlist.yaml`
   in the same PR.
4. Add a test to `tests/audit/test_cross_repo_sync_audit.py`
   if the new pair exposes a status class not yet covered.

When adding a welle:

1. Append a `WelleSubstance` row in `WELLE_INVENTORY`.
2. Confirm the runtime triad (smoke + runbook + validation
   workflow + Phase-3a modules) is in place.
3. If the protocol-side `docs/welle-substance.md` exists, lift
   the new welle id into it; otherwise the audit will simply
   report `consistent-runtime-only`.
4. Update the contract test
   `test_welle_inventory_contract_is_one_to_seven`'s expected
   range.

— Reza
