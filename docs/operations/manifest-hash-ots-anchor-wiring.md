<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Manifest-Hash OTS-Anchor Wiring (Tag-57 OPEN-K2)

Audit-only Sandbox-side wiring for the persona-engine
manifest-hash OpenTimestamps anchor. Closes OPEN-K2 from
Selin's Tag-56 0.5.2-final production-readiness audit
(PR #362).

This document is the **Operator-Hand runbook** for the real
OTS calendar step. The Sandbox-side substrate is intentionally
stub-only — see Section 4.

## 1. Scope and Sandbox Boundary

**In scope (Sandbox / Repo / CI):**

- Computing the SHA-256 of a manifest file deterministically.
- Emitting a JSON marker that captures the anchor-intent
  (manifest path, hash, requested-at timestamp, actor) and the
  WAT-spool envelope shape.
- Hermetic tests over the marker schema and the helper script.
- Repo-Gate that prevents marker-schema drift.

**Out of scope (Sandbox), Operator-Hand only:**

- Calling the OpenTimestamps calendar server.
- Producing the `.ots` proof file.
- Attaching the proof file to the marker as an out-of-band
  artefact.

The Sandbox cannot reach the OTS calendar:

- No host-podman-socket access (see
  `feedback_sandbox_host_trennung.md`).
- No outbound network for non-allow-listed endpoints.

That is by design. Tag-57 closes the wiring shape; real
anchoring runs on a network-attached host by Operator-Hand.

## 2. Wiring Topology

```
+-------------------------------+
| wirelang/persona_engine/      |
| MANIFEST-*-pre-cutover.md     |
+-----+-------------------------+
      |
      | (1) sha256 streaming
      v
+-------------------------------+
| tooling/ots/                  |
|   emit_manifest_hash_ots_     |
|   marker.py                   |   audit-only emit
+-----+-------------------------+
      |
      | (2) marker JSON write
      v
+-------------------------------+
| tooling/ots/markers/          |
|   <manifest-name>.json        |
+-----+-------------------------+
      |
      | (3) Operator-Hand pickup
      |     on network-attached host
      v
+-------------------------------+
| `ots stamp` (real OTS CLI)    |
| -> attaches <marker>.json.ots |
+-------------------------------+
```

The "WAT spool" reference in the OPEN-K2 phrasing refers to
the JSON envelope shape embedded in the marker
(`wat_spool_envelope` field). The substrate-level WAT spool
itself (`wat/` directory) is not touched by this audit-only
wiring — the Tag-57 closeout is intentionally minimal.

## 3. Marker Schema (v1)

The emit helper produces a JSON object with this shape:

```json
{
  "schema_version": 1,
  "kind": "manifest-hash-ots-anchor-marker",
  "mode": "audit-only",
  "manifest_path": "wirelang/persona_engine/MANIFEST-0.5.2-final-pre-cutover.md",
  "manifest_sha256": "<64-hex>",
  "manifest_size_bytes": 12345,
  "wat_spool_envelope": {
    "schema_version": 1,
    "kind": "ots-anchor-request",
    "manifest_sha256": "<64-hex>",
    "requested_at_utc": "2026-05-19T...",
    "actor": "<github.actor|local>",
    "anchor_target": "opentimestamps-calendar"
  },
  "emitted_at_utc": "2026-05-19T...",
  "anchors": {
    "adr_audit_trail": "decisions/0007-internal-audit-trail-ots.md",
    "selin_tag_56_audit": "tag-56 PR #362 OPEN-K2 ..."
  },
  "operator_hand_next_step": "Run `ots stamp <marker_out>` ..."
}
```

`mode: "audit-only"` is the explicit flag that this marker
was emitted from the Sandbox without performing the real
calendar call. The Operator-Hand step changes nothing about
the marker JSON itself — it only adds the `<marker>.ots`
proof file next to it.

## 4. Operator-Hand Runbook

On a network-attached host with the `opentimestamps-client`
package installed:

```bash
# 1. Pull the marker from the CI artefact or this repo's
#    tooling/ots/markers/ directory.
ls tooling/ots/markers/

# 2. Stamp the marker file. This produces a sibling .ots
#    proof file (e.g. tooling/ots/markers/foo.json.ots).
ots stamp tooling/ots/markers/MANIFEST-0.5.2-final-pre-cutover.json

# 3. Wait ~3 hours for the calendar attestation.
ots upgrade tooling/ots/markers/MANIFEST-0.5.2-final-pre-cutover.json.ots

# 4. Verify against the Bitcoin block-anchor.
ots verify tooling/ots/markers/MANIFEST-0.5.2-final-pre-cutover.json.ots

# 5. Commit the proof file out-of-band (Operator-Hand PR).
git add tooling/ots/markers/MANIFEST-0.5.2-final-pre-cutover.json.ots
git commit -m "ots(manifest-hash-anchor): MANIFEST-0.5.2-final-pre-cutover"
```

The marker JSON itself never needs editing. The proof is a
strict additive artefact.

## 5. CI-Side Invariants (Tag-57 Closeout)

The hermetic test-suite at
`tests/ci/test_k1_k2_containerfile_ots_tag57.py` enforces
these invariants:

- The emit helper is stdlib-only (no third-party imports).
- The emit helper always writes `mode: "audit-only"` (no
  CLI flag flips it to a live mode).
- The marker JSON validates against schema-v1 shape (all
  required fields present, no extra top-level keys beyond
  the documented set).
- The SHA-256 of a fixture manifest is byte-stable across
  runs.
- The `tooling/ots/manifest-hash-ots-anchor-stub.json`
  registry lists all three pre-cutover manifests
  (0.5.0/0.5.1/0.5.2) and points at this runbook.

If any of these invariants drifts, CI fails and Tag-57
closeout regresses. The real OTS-calendar step
(Operator-Hand) is explicitly out of CI scope.

---

**Anchors:**

- ADR-0007 (Internal Audit Trail via OTS).
- Selin's Tag-56 0.5.2-final audit (PR #362), OPEN-K2.
- Tomás Tag-57 K1+K2 closeout PR.
