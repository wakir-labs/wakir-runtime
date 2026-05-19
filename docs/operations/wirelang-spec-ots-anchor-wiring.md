<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors
-->

# Wirelang-Spec OTS-Anchor Wiring (Tag-60)

**Status:** audit-only stub, pre-activation-probe added Tag-60.
**Cutover gate:** KW-24 (2026-06-09).
**AR-authorisation required:** yes.
**Owner:** Reza (Dev-Engineering-2).
**Mirror-twin:** Tomás Tag-59 manifest-hash anchor (`docs/operations/manifest-hash-ots-anchor-wiring.md`).

---

## 1. Purpose

The Wirelang-Spec markdown documents under `wirelang/specs/`
(currently `wirelang-spec-v0-4-3.md`, plus its `v0.4.1` and `v0.2`
ancestors) are the canonical normative reference for every Wakir
runtime, persona-engine, and audit-trail consumer. Once the
Aufsichtsrat authorises live OTS anchoring at the KW-24 cutover
gate (2026-06-09), each wired spec file must be cryptographically
timestamped against the public OpenTimestamps calendar so that
auditors can prove, off-chain and irrespective of repo history,
*"this exact byte-sequence of the spec existed at or before this
calendar block"*.

The Tag-60 wiring is the **audit-only stub + pre-activation
probe** that establishes the Repo-Side pipeline shape without
crossing the Sandbox boundary. No actual OTS calendar call is
performed by any CI runner or claude-dev Sandbox.

This document is the mirror-twin of Tomás's manifest-hash anchor
runbook. Both runbooks share §6 (AR-authorisation gate) and §7
(Operator-Hand cutover) — when one moves, the other moves in
lockstep.

---

## 2. Wiring inventory

The wired specs are declared in
`tooling/ots/wirelang-spec-ots-anchor-stub.json` under
`wired_specs[]`. The current Tag-60 inventory:

| Spec name | Version | Path | Freeze-marker |
| --- | --- | --- | --- |
| `wirelang-spec-v0-4-3` | 0.4.3 | `wirelang/specs/wirelang-spec-v0-4-3.md` | `kw-24-cutover-gate` |
| `wirelang-spec-v0-4-1` | 0.4.1 | `wirelang/specs/wirelang-spec-v0-4-1.md` | none (pre-freeze) |
| `wirelang-spec-v0-2`   | 0.2   | `wirelang/specs/wirelang-spec-v0-2.md`   | none (pre-freeze) |

Adding a wired spec is a one-line stub edit + a workflow path-filter
addition (`.github/workflows/wirelang-spec-ots-pre-anchor-probe.yml`).
Removing a wired spec is a deliberate ADR-class decision and must
be paired with a re-anchor of the remaining wired set so that the
removal itself is auditable.

The pre-activation-probe (Tag-60) walks the **entire** wired set
on every CI run; a defect on any single wired spec turns the
aggregate verdict into `PROBE-DEFECT` and (in enforce-mode) blocks
the merge.

---

## 3. Helper + stub layout

```
tooling/ots/
  emit_wirelang_spec_ots_marker.py       (Tag-60, this runbook)
  wirelang-spec-ots-anchor-stub.json     (Tag-60, this runbook)
  emit_manifest_hash_ots_marker.py       (Tag-57/59, Tomás mirror)
  manifest-hash-ots-anchor-stub.json     (Tag-57/59, Tomás mirror)
  markers/                                (shared output dir; both
                                           runbooks write here)

.github/workflows/
  wirelang-spec-ots-pre-anchor-probe.yml (Tag-60, this runbook)
  ots-pre-anchor-activation-probe.yml    (Tag-59, Tomás mirror)
  wirelang-spec-freeze-seal-probe.yml    (Tag-58, Reza freeze-seal)

tests/audit/
  test_wirelang_spec_ots_pre_anchor_probe_tag60.py  (Tag-60)
  test_wirelang_spec_freeze_seal_probe_tag58.py     (Tag-58)
tests/ci/
  test_ots_pre_anchor_activation_probe_tag59.py     (Tag-59)

docs/operations/
  wirelang-spec-ots-anchor-wiring.md     (Tag-60, this doc)
  manifest-hash-ots-anchor-wiring.md     (Tag-59, Tomás mirror)
```

Both helpers are stdlib-only. Both stubs are schema-v1 JSON. Both
workflows emit per-target verdict envelopes to
`out/probe-verdicts/` (artifact-friendly), one envelope per wired
target. Both runbooks share `§6` and `§7` literally.

### Cross-anchor with Tomás Tag-59

The `cross_anchor_with_tomas_tag_59` block of
`wirelang-spec-ots-anchor-stub.json` documents the structural
twinning: shared WAT-spool envelope kind discipline, shared
marker output directory, shared runbook §6 + §7. The probes are
**independent** — a defect on the manifest-hash side does not
trip the spec side, and vice versa — but the runbook moves in
lockstep so the Operator-Hand cutover (§7) anchors both pipelines
in one KW-24 session.

---

## 4. Probe modes

`emit_wirelang_spec_ots_marker.py` exposes two modes:

### 4.1 `--mode audit-only` (default, pre-cutover)

Emits a **marker JSON** to `--marker-out`. The marker captures:

* `spec_path` (relative to repo root),
* `spec_version` (parsed from frontmatter, `unknown` on miss),
* `spec_sha256` + `spec_size_bytes`,
* `wat_spool_envelope` (kind = `wirelang-spec-ots-anchor-request`,
  schema_version = 1, anchor_target = `opentimestamps-calendar`),
* `anchors[]` cross-referencing this runbook and the Tag-58/Tag-59
  PRs.

The marker is the artifact the Operator-Hand picks up at cutover
to perform the real `ots stamp` invocation off-Sandbox.

### 4.2 `--mode pre-activation-probe` (Tag-60)

Runs a four-stage hermetic dry-run over the exact pipeline shape
a real `ots stamp` invocation would receive, and emits a **verdict
envelope** to `--probe-verdict-out`:

* Stage 1 — `input_validation`: spec exists, is a file, is listed
  in the in-repo stub registry (registry check skipped for
  tmp-path test fixtures via `ValueError` fallback).
* Stage 2 — `hash_computation`: SHA-256 streamed in 64 KiB chunks,
  byte-stable; the resulting digest is also surfaced in
  `spec_sha256`.
* Stage 3 — `payload_shape`: build a marker via the same builder
  the audit-only path uses, validate required-key set, schema_version,
  marker kind, and WAT-spool envelope kind + anchor_target.
* Stage 4 — `sandbox_boundary`: stdlib-only OK-by-construction;
  test-suite reinforces with an explicit `no_subprocess` /
  `no_socket` invariant.

Verdict literal: `PROBE-READY` (all four stages start with `OK`)
or `PROBE-DEFECT` (any non-OK). The verdict envelope sets
`ar_authorisation_required: true` so downstream consumers cannot
silently flip the probe into a live anchor without crossing the §6
gate first.

The probe is hermetic. **It still performs no real OTS calendar
call.** The Sandbox boundary is preserved end-to-end.

---

## 5. Cross-trip-wire with Tag-58 freeze-seal

The Tag-58 freeze-seal probe
(`wirelang-spec-freeze-seal-probe.yml`) detects post-freeze drift
inside the spec markdown body (frontmatter markers + body
allowlist). The Tag-60 OTS-anchor probe acts on the **same**
spec file but anchors the *full byte sequence* off-chain.

Together they form a two-layer guard:

1. **Tag-58** says *"the spec has not been edited outside the
   allowlist since freeze"* (in-repo, content-aware).
2. **Tag-60** says *"the spec's exact byte sequence is or will be
   pinned at the OpenTimestamps calendar"* (off-repo, content-
   agnostic, time-pinned).

The Tag-60 stub deliberately re-references the Tag-58 PR (#371)
and the Tag-59 mirror PR (#380) so the auditor can chain across
the three probes without out-of-band knowledge.

---

## 6. AR-authorisation gate (shared with Tag-59)

Live OTS anchoring requires explicit Aufsichtsrat (AR)
authorisation. The authorisation flow:

1. The CI pipeline emits `PROBE-READY` on the aggregate verdict
   for **both** the Tag-59 manifest-hash probe and the Tag-60
   spec probe.
2. Mira presents the aggregate verdicts plus the wired-inventory
   diff (any additions/removals since the last cutover-style
   session) to the AR.
3. AR issues a one-line authorisation in the AR-thread (Markdown,
   timestamped, attached to a decisions/ADR-XXXX). The
   authorisation explicitly names the cutover window (KW-24,
   start 2026-06-09).
4. The Operator-Hand workflow (§7) consumes the authorisation
   payload as its gate input. Without the payload, the live
   anchor refuses to run.

This section is mirrored verbatim in
`docs/operations/manifest-hash-ots-anchor-wiring.md` — when this
section moves, the mirror moves with it.

---

## 7. Operator-Hand cutover (shared with Tag-59)

Cutover-day procedure (KW-24, 2026-06-09):

1. Operator pulls the latest `main`, confirms aggregate
   `PROBE-READY` on both pipelines via the most recent CI run.
2. Operator runs `emit_wirelang_spec_ots_marker.py --mode
   audit-only` per wired spec to (re-)materialise the markers
   under `tooling/ots/markers/`.
3. Operator runs `ots stamp tooling/ots/markers/wirelang-spec-v0-4-3.json`
   (and the sibling marker files) on a network-attached host. The
   `.ots` proofs are written next to each marker.
4. Operator commits the resulting `.ots` files in a single
   cutover commit with the AR-authorisation hash in the commit
   message body.
5. Operator verifies the proofs round-trip via
   `ots verify <marker>.ots <marker>` and attaches the verify
   transcript to the cutover commit.

The Sandbox plays no role in steps 3–5. Mira's claude-dev
Sandbox has no host-podman-socket and no outbound network for the
OTS calendar by policy
(`feedback_sandbox_host_trennung.md`, `feedback_live_bringup_sandbox_gap.md`).

This section is mirrored verbatim in
`docs/operations/manifest-hash-ots-anchor-wiring.md`.

---

## 8. Open items (carry into Tag-61+)

* Wire a `verify_wirelang_spec_ots_anchor.py` helper that reads a
  `.ots` proof + marker pair and re-verifies the chain. Currently
  the Operator-Hand round-trips via the `ots` CLI directly; a
  hermetic verify helper makes the verify-step reproducible
  in CI without needing the upstream `ots` package.
* Add a third probe-stage flag (`--anchor-budget-check`) that
  asserts the aggregate marker count fits in the per-cutover
  calendar-call budget once Wakir runs at higher spec-cadence.
* Cross-link the AR-authorisation payload format with the
  `decisions/` ADR template so the authorisation hash is captured
  in a standardised commit-trailer.

— Reza
