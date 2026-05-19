<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->
---
title: "Operator-Hand OTS-Live-Stamping Setup-Recipe (Tag-77)"
status: "active"
owner: "tomas"
audience: "operator,ar,engineering"
created: "2026-05-19"
tag: "tag-77"
predecessors:
  - "docs/operations/manifest-hash-ots-anchor-wiring.md"
  - "docs/operations/wirelang-spec-ots-anchor-wiring.md"
related_adrs:
  - "ADR-0007"
  - "ADR-0023a"
  - "ADR-0044"
  - "ADR-0066"
related_docs:
  - "docs/operations/manifest-hash-ots-anchor-wiring.md"
  - "docs/operations/wirelang-spec-ots-anchor-wiring.md"
  - "docs/operations/res-d4-high-residual-mitigation-deep-dive.md"
  - "docs/operations/operator-hand-cutover-eve-final-recipe.md"
related_prs:
  - "#366"
  - "#371"
  - "#382"
  - "#440"
  - "#484"
cross_review_markers:
  - "Zone-K: WAT-Core × OTS-Substrate (Tomas-domain)"
  - "Zone-L: Identity × Spec-Seal (Reza-cross-anchor)"
  - "Zone-N: QA × Audit-Trail (Henrik-evidence)"
---

# Operator-Hand OTS-Live-Stamping Setup-Recipe (Tag-77)

Pre-Cutover-Eve Operator-Hand-Activation-Recipe for the
`WAKIR_OTS_LIVE_EMIT=1` toggle. Consumed at KW-24 cutover gate
(2026-06-08 T0, Eve 2026-06-07) by the Operator-Hand to flip the
OTS substrate from audit-only to live-emit on a network-attached
host.

This doc is a **doc-form-only Operator-Hand recipe**. The Sandbox
side never crosses into live-emit; the helper substrate
(`tooling/ots/emit_manifest_hash_ots_marker.py`,
`tooling/ots/emit_wirelang_spec_ots_marker.py`) refuses to set the
ENV-flag by construction (Tag-70 HD-1 invariant, see
`tooling/audit/prepare_res_d4_hd1_ots_substrate.py`). The
Aufsichtsrat-authorisation gate sits between probe-readiness and
live-flip; see §3.

## §1 Scope

### §1.1 Activation-Pfad

This recipe covers the **single Operator-Hand step** that flips the
OTS substrate from audit-only to live-emit at the KW-24 cutover
gate. It documents every action between the AR-authorisation drop
(§3) and the first verified live-OTS-anchor (§5), and pins the
rollback path (§7) for the case the live-flip fails.

### §1.2 Scope-Table

| Phase | When | Owner | Action |
|---|---|---|---|
| Pre-Eve | 2026-06-07 T-24h | Operator | Probe-readiness verification (§2) |
| Eve | 2026-06-07 evening | AR | Authorisation-drop into `ar-hand/` inbox (§3) |
| Eve+1 | 2026-06-07 late | Operator | `WAKIR_OTS_LIVE_EMIT=1` toggle (§4) |
| T0 | 2026-06-08 T0 | Operator | First-Live-Stamp test (§5) |
| T0+0.5h | 2026-06-08 T0+0.5h | Operator | Marker-chain verification (§6) |
| T0..T0+6 | rolling | Operator | Phase-3c-Welle-1..7 live-stamping under flag |

### §1.3 Non-Scope

- This recipe does **not** ship a new helper that performs the
  live-emit itself. The live-emit is a CLI flow on a
  network-attached host using the upstream `opentimestamps-client`
  package; see §4.2 invocation.
- This recipe does **not** modify any audit-only Sandbox substrate.
  The Sandbox helpers stay stdlib-only and never see
  `WAKIR_OTS_LIVE_EMIT=1` (Sandbox-Boundary, §8).
- This recipe does **not** open the AR-authorisation request.
  Mira drives that step via ADR-Vorlage or AR-Hand decision marker.

## §2 Pre-Activation-Probe-Verifikation

Before requesting AR-authorisation, the Operator confirms that the
hermetic Tag-59 pre-activation-probe is green across all
pre-cutover manifests AND the Tag-76 Phase-3-COMPLETE-Marker has
been emitted (Marathon-Closeout consolidation done).

### §2.1 Manifest-Hash Pre-Activation-Probe

Run the Tag-59 probe across all three pre-cutover manifests and
confirm every verdict is `PROBE-READY`:

```bash
# On the network-attached host, in a fresh checkout of main.
cd /tmp/wakir-runtime-pre-eve && \
  git fetch origin main && \
  git checkout origin/main

mkdir -p out/probe-verdicts

for manifest in MANIFEST-0.5.0-pre-cutover.md \
                MANIFEST-0.5.1-pre-cutover.md \
                MANIFEST-0.5.2-final-pre-cutover.md ; do
  python3 tooling/ots/emit_manifest_hash_ots_marker.py \
    --mode pre-activation-probe \
    --manifest "wirelang/persona_engine/${manifest}" \
    --probe-verdict-out "out/probe-verdicts/${manifest}.json" \
    --actor operator-hand
done
```

Every emitted verdict envelope MUST satisfy:

- `kind: ots-pre-activation-probe-verdict`
- `verdict: PROBE-READY` (all four stages start with `"OK"`)
- `ar_authorisation_required: true`
- `sandbox_boundary_intact: true`

### §2.2 Phase-3-COMPLETE-Marker

Confirm the Tag-76 Marathon-Closeout-Audit-Anchor-Bundle has
emitted the Phase-3-COMPLETE-Marker for Welle-1..7. The marker
file lives under `tooling/ots/markers/` after Tag-76 PR #484
merge:

```bash
ls tooling/ots/markers/phase-3-complete-*.json
jq -r '.kind, .mode, .welle_1_7_kind_disjointness_pin_ok' \
  tooling/ots/markers/phase-3-complete-marker-*.json
```

Expected:
- `kind: phase-3-complete-marker`
- `mode: phase-3-complete-marker`
- `welle_1_7_kind_disjointness_pin_ok: true`

### §2.3 Probe-Verdict-Aggregate

Aggregate the per-manifest verdicts into a single
`PRE-EVE-PROBE-GREEN` summary. The Operator carries this summary
into the AR-authorisation request as evidence-attachment:

```bash
python3 -c "
import json, pathlib, sys
verdicts = sorted(pathlib.Path('out/probe-verdicts').glob('*.json'))
all_ready = True
for v in verdicts:
    payload = json.loads(v.read_text())
    if payload.get('verdict') != 'PROBE-READY':
        all_ready = False
        print(f'DEFECT: {v.name}', file=sys.stderr)
print('PRE-EVE-PROBE-GREEN' if all_ready else 'PRE-EVE-PROBE-DEFECT')
"
```

If the aggregate prints `PRE-EVE-PROBE-DEFECT`, **do not proceed
to §3**. Open a Tag-77-defect-ticket and escalate to Tomas
(Matrix-Lead) + Priya (CTO).

## §3 AR-Authorisierungs-Schritt

The Aufsichtsrat-authorisation drop is the **single gate** between
probe-readiness (§2) and the live-flip toggle (§4). The Operator
MUST NOT proceed to §4 without an explicit AR-authorisation marker
present.

### §3.1 AR-Authorisation-Request (Mira-Hand)

Mira files the AR-authorisation request via ADR-Vorlage or
AR-Hand-Decision-Marker. The request MUST contain:

- **Purpose**: Live-OTS-anchor activation for Phase-3c-Welle-1..7
  cutover (KW-24, T0 = 2026-06-08).
- **Scope**: `WAKIR_OTS_LIVE_EMIT=1` on the Operator-Host only.
  Sandbox stays audit-only.
- **Rollback**: §7 of this doc.
- **Audit-Trail**: Henrik Voss Zone-N audit-sample includes
  live-stamp markers + `.ots` proof files.
- **Sandbox-Boundary recital**: Sandbox helpers refuse the flag
  by construction; flag is host-side only.

### §3.2 AR-Authorisation-Marker

When the Aufsichtsrat approves, a signed decision marker lands in
`ar-hand/inbox/` with the canonical filename pattern:

```
ar-hand/inbox/<YYYY-MM-DD>-ots-live-emit-activation-authorisation.md
```

The Operator confirms presence and reads the marker:

```bash
ls ar-hand/inbox/*-ots-live-emit-activation-authorisation.md
cat ar-hand/inbox/2026-06-07-ots-live-emit-activation-authorisation.md
```

The marker MUST contain a signature block from the Aufsichtsrat
and the cutover-target-date `2026-06-08`. The Operator records the
marker SHA-256 as audit-evidence:

```bash
sha256sum ar-hand/inbox/2026-06-07-ots-live-emit-activation-authorisation.md \
  > out/ar-authorisation-marker.sha256
```

### §3.3 No-AR-No-Flip Pin

If the AR-authorisation marker is absent or unsigned, the Operator
**MUST NOT** export `WAKIR_OTS_LIVE_EMIT=1`. This is the canonical
no-AR-no-flip-pin from ADR-0023a (Sandbox-Boundary) §6.1.

## §4 WAKIR_OTS_LIVE_EMIT-Toggle-Sequence

With probe-green (§2) and AR-authorisation-present (§3), the
Operator executes the toggle sequence on the network-attached
host.

### §4.1 Pre-Toggle-Verification

Confirm the ENV-flag is currently unset (audit-only default):

```bash
echo "WAKIR_OTS_LIVE_EMIT before flip: '${WAKIR_OTS_LIVE_EMIT:-<unset>}'"
echo "WAKIR_OTS_CALENDAR_URL before flip: '${WAKIR_OTS_CALENDAR_URL:-<unset>}'"
```

Expected: both unset OR `WAKIR_OTS_LIVE_EMIT=0` AND
`WAKIR_OTS_CALENDAR_URL=fixture://ots-calendar.invalid/audit-only/stub`.

### §4.2 Toggle-Export (Operator-Hand)

The toggle is **shell-scope export only** — never written to
`.env`, never committed to the repo, never persisted across
Operator-Host reboots without explicit re-export:

```bash
# Export the live-emit flag for THIS shell session only.
export WAKIR_OTS_LIVE_EMIT=1
export WAKIR_OTS_CALENDAR_URL="https://alice.btc.calendar.opentimestamps.org"

# Confirm export.
echo "WAKIR_OTS_LIVE_EMIT after flip:    '${WAKIR_OTS_LIVE_EMIT}'"
echo "WAKIR_OTS_CALENDAR_URL after flip: '${WAKIR_OTS_CALENDAR_URL}'"

# Belt-and-suspenders: ots CLI presence check.
command -v ots || { echo "FAIL: ots CLI missing on host"; exit 1; }
ots --version
```

The Operator-Host MUST have `opentimestamps-client` installed
(via the host package manager or a pinned pip venv). The Sandbox
never sees this CLI.

### §4.3 Toggle-Audit-Record

Append a toggle-record to the local Operator-Hand audit log
(out-of-band, host-side only):

```bash
cat >> out/operator-hand-audit-log.jsonl <<EOF
{"event": "ots-live-emit-toggle", "ts": "$(date -u +%Y-%m-%dT%H:%M:%SZ)", "actor": "operator-hand", "ar_marker_sha256": "$(cat out/ar-authorisation-marker.sha256 | awk '{print $1}')", "calendar_url": "${WAKIR_OTS_CALENDAR_URL}"}
EOF
```

This log file is Operator-Hand evidence. It is **not** committed to
the repo. Henrik Voss reads it via the Zone-N audit-sample
out-of-band path.

## §5 First-Live-Stamp Test

With the flag exported, run the **first live-OTS-stamp** against
the Tag-76 Phase-3-COMPLETE-Marker. This is the canonical proof
that the live-flip works.

### §5.1 Stamp-Invocation

```bash
# Locate the Phase-3-COMPLETE-Marker emitted at Tag-76.
MARKER=$(ls tooling/ots/markers/phase-3-complete-marker-*.json | head -1)
echo "Stamping: ${MARKER}"

# Run the real ots stamp against the marker JSON.
ots stamp "${MARKER}"

# Confirm sibling .ots file appeared.
ls -la "${MARKER}.ots"
```

Expected output: `ots stamp` reports a successful submission to
the configured calendar URL. A sibling `.ots` proof file appears
next to the marker JSON.

### §5.2 Calendar-Wait

The first calendar attestation arrives in ~3 hours. Wait, then
upgrade:

```bash
# Wait for the attestation window. Document the wait in the audit-log.
sleep 10800  # 3 hours; adjust per calendar SLO.
ots upgrade "${MARKER}.ots"
```

The `ots upgrade` step pulls the calendar attestation into the
local `.ots` file.

### §5.3 First-Live-Stamp-Verify

Verify the attestation against the Bitcoin block-anchor:

```bash
ots verify "${MARKER}.ots"
```

Expected output:
- "Success! Bitcoin block N attests existence as of ..."

If `ots verify` fails, **immediately invoke §7 rollback**. The
live-flip is not considered successful until the verify-step
prints a Bitcoin-block attestation.

### §5.4 First-Live-Stamp-Audit-Record

```bash
cat >> out/operator-hand-audit-log.jsonl <<EOF
{"event": "ots-first-live-stamp", "ts": "$(date -u +%Y-%m-%dT%H:%M:%SZ)", "marker": "${MARKER}", "marker_sha256": "$(sha256sum "${MARKER}" | awk '{print $1}')", "ots_sha256": "$(sha256sum "${MARKER}.ots" | awk '{print $1}')", "verify_result": "OK"}
EOF
```

## §6 Marker-Chain-Verifikation

The Phase-3-COMPLETE-Marker references the seven Welle-N
audit-anchor markers (Tag-69..Tag-75). The Operator confirms each
predecessor marker is stamp-eligible AND records the chain.

### §6.1 Welle-1..7-Marker-Stamp-Sequence

Iterate over the seven Welle-N markers and stamp each one in
order (Welle-1, Welle-2, Welle-3, Welle-4, Welle-5, Welle-6,
Welle-7):

```bash
for welle in 1 2 3 4 5 6 7 ; do
  WELLE_MARKER="tooling/ots/markers/welle-${welle}-audit-anchor.json"
  echo "Stamping Welle-${welle}: ${WELLE_MARKER}"
  ots stamp "${WELLE_MARKER}"
done
```

### §6.2 Chain-Hash-Verifikation

The Phase-3-COMPLETE-Marker carries a `welle_1_7_marker_chain`
field that SHA-256s the seven Welle-N markers in canonical
sort-order. Confirm the chain hash matches:

```bash
python3 -c "
import json, hashlib, pathlib
marker = json.loads(pathlib.Path('${MARKER}').read_text())
chain = marker.get('welle_1_7_marker_chain', '')
computed = hashlib.sha256()
for i in range(1, 8):
    p = pathlib.Path(f'tooling/ots/markers/welle-{i}-audit-anchor.json')
    computed.update(p.read_bytes())
assert chain == computed.hexdigest(), f'chain drift: {chain} != {computed.hexdigest()}'
print('CHAIN-OK:', chain)
"
```

### §6.3 Cross-Substrate-Parity

Confirm the Phase-3-COMPLETE-Marker's
`cross_substrate_parity_markers` list points at the seven Welle-N
marker filenames AND each `.ots` proof file is present after §6.1:

```bash
python3 -c "
import json, pathlib
marker = json.loads(pathlib.Path('${MARKER}').read_text())
parity = marker.get('cross_substrate_parity_markers', [])
assert len(parity) == 7, f'expected 7 parity markers, got {len(parity)}'
for entry in parity:
    p = pathlib.Path('tooling/ots/markers') / entry['filename']
    assert p.exists(), f'missing marker: {p}'
    assert (p.with_suffix('.json.ots')).exists() or \
           pathlib.Path(str(p) + '.ots').exists(), f'missing .ots proof: {p}'
print('PARITY-CHAIN-OK')
"
```

### §6.4 Audit-Evidence-Bundle

Bundle the seven `.ots` proofs + the Phase-3-COMPLETE `.ots` proof
into a single tarball as Zone-N audit-evidence:

```bash
tar czf out/welle-1-7-plus-phase-3-complete-ots-bundle.tar.gz \
  tooling/ots/markers/welle-*.json.ots \
  tooling/ots/markers/phase-3-complete-marker-*.json.ots
sha256sum out/welle-1-7-plus-phase-3-complete-ots-bundle.tar.gz \
  >> out/operator-hand-audit-log.jsonl
```

## §7 Rollback-Pfad

If §5 or §6 fails (calendar-down, verify-failure, chain-drift,
parity-mismatch), the Operator invokes the rollback path. The
rollback returns the substrate to audit-only without retaining
any live-stamp residue.

### §7.1 Rollback-Trigger-Conditions

| Trigger | Symptom | Severity |
|---|---|---|
| R1-Calendar-Down | `ots stamp` fails with calendar-unreachable | HIGH |
| R2-Verify-Failure | `ots verify` does not return Bitcoin-block attestation | CRITICAL |
| R3-Chain-Drift | §6.2 chain-hash mismatch | CRITICAL |
| R4-Parity-Mismatch | §6.3 parity-list missing or `.ots` proof absent | HIGH |
| R5-AR-Recall | Aufsichtsrat retracts authorisation post-flip | CRITICAL |

### §7.2 Rollback-Sequence

```bash
# 1. Unset the live-emit ENV flag in the active shell.
unset WAKIR_OTS_LIVE_EMIT
unset WAKIR_OTS_CALENDAR_URL

# 2. Confirm unset.
echo "WAKIR_OTS_LIVE_EMIT after rollback: '${WAKIR_OTS_LIVE_EMIT:-<unset>}'"

# 3. Move any partial .ots proof files into a quarantine dir.
mkdir -p out/rollback-quarantine
mv tooling/ots/markers/*.json.ots out/rollback-quarantine/ 2>/dev/null || true

# 4. Append rollback record to audit log.
cat >> out/operator-hand-audit-log.jsonl <<EOF
{"event": "ots-live-emit-rollback", "ts": "$(date -u +%Y-%m-%dT%H:%M:%SZ)", "trigger": "<R1|R2|R3|R4|R5>", "quarantined_proofs": "$(ls out/rollback-quarantine | wc -l)"}
EOF

# 5. Notify Mira + Priya + Henrik via the standard notify-bridge.
echo "OTS-LIVE-EMIT-ROLLBACK trigger=<R1|R2|R3|R4|R5>" \
  > out/notify-mira-rollback.txt
```

### §7.3 Rollback-Audit-Trail

The quarantined `.ots` proof files MUST be retained for Henrik's
Zone-N audit-sample. Do **not** delete them. The audit-trail
remains complete even after rollback.

### §7.4 Re-Activation-After-Rollback

Re-activation requires a **new AR-authorisation marker** (a
re-arm marker, ADR-0023a §6.1). The Operator does NOT re-export
`WAKIR_OTS_LIVE_EMIT=1` without a re-arm marker present in
`ar-hand/inbox/`.

## §8 Sandbox-Boundary

### §8.1 Sandbox-Scope

**In Sandbox (Repo/CI):**
- `tooling/ots/emit_manifest_hash_ots_marker.py` — audit-only emit
  + pre-activation-probe + Welle-N audit-anchor + Phase-3-COMPLETE.
- `tooling/ots/emit_wirelang_spec_ots_marker.py` — audit-only emit.
- Hermetic schema-tests over marker JSON shape.
- This recipe doc (`docs/operations/ots-live-stamping-operator-setup.md`).
- The Tag-77 verifier helper
  (`tooling/ci/verify_ots_live_setup_doc.py`).
- The Tag-77 test-suite
  (`tests/ci/test_ots_live_setup_doc_tag77.py`).

### §8.2 Out-of-Sandbox-Scope

**Operator-Hand only (network-attached host):**
- `ots stamp <marker.json>` invocation.
- `ots upgrade <marker.json.ots>` calendar-pull.
- `ots verify <marker.json.ots>` Bitcoin-block-attestation check.
- `WAKIR_OTS_LIVE_EMIT=1` ENV-flag export.
- `WAKIR_OTS_CALENDAR_URL=<https://...>` ENV-flag export.
- `out/operator-hand-audit-log.jsonl` host-side audit log.
- `out/rollback-quarantine/` quarantine directory.
- Tarball bundle of `.ots` proofs.

### §8.3 Operator-Hand-Sandbox-Gap

The Sandbox cannot reach the OTS calendar. The Sandbox helpers
refuse `WAKIR_OTS_LIVE_EMIT=1` by construction (no `--mode live`
flag in `emit_manifest_hash_ots_marker.py`; the Tag-70 HD-1
substrate enforces ENV-flag-default-off via
`tooling/audit/prepare_res_d4_hd1_ots_substrate.py`). This is the
canonical **Operator-Hand-Sandbox-Gap** pattern from
`feedback_sandbox_host_trennung.md` (memory anchor) and ADR-0023a
(Sandbox-Boundary).

The Sandbox-side substrate validates that:
- Marker JSON files match the documented schema.
- Helper subprocesses do not import `socket`, `subprocess`,
  `urllib.request`, or any network module.
- Helper subprocesses exit non-zero when invoked with
  `WAKIR_OTS_LIVE_EMIT=1` (defensive trip — Tag-70
  `test_helper_subprocess_rejects_live_emit_env_flag`).

### §8.4 ADR-Anchors

- **ADR-0007** — Internal Audit Trail via OTS (substrate).
- **ADR-0023a** — Sandbox-Boundary (no live-emit in Sandbox).
- **ADR-0044** — QA × Audit Cross-Review (Zone-N evidence).
- **ADR-0066** — Marathon-Closeout Substanz-Prüfung Pflicht.

### §8.5 Cross-Anchor-PRs

- **#366** (Tomás Tag-57) — audit-only emit substrate.
- **#371** (Reza Tag-58) — Wirelang-Spec v0.4.3 seal.
- **#382** (Tomás Tag-60) — Live-VM-Rotation-Stub.
- **#440** (Tomás Tag-69 RES-D4 deep-dive) — HD-1 OTS-substrate-prep.
- **#484** (Tomás Tag-76) — Phase-3-COMPLETE-Marker
  (Marathon-Closeout-Audit-Anchor-Bundle).

---

**Anchors:**

- ADR-0007 (Internal Audit Trail via OTS).
- ADR-0023a (Sandbox-Boundary).
- Tag-57 PR #366 K1+K2 closeout.
- Tag-58 PR #371 Wirelang-Spec seal.
- Tag-59 pre-activation-probe + AR-authorisation pfad.
- Tag-69 RES-D4 deep-dive HD-1 substrate-prep.
- Tag-76 PR #484 Phase-3-COMPLETE-Marker.

-- Tomás
