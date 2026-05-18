<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Quality-Gate — Bug-42 Regression-Suite (Tag-48)

| Field | Value |
|---|---|
| Owner | Amara Osei (QA), with Zone-M cross-check by Selin Çelik (Persona-Engine) |
| Status | Tag-48 baseline — drift-free, 25 tests passing |
| Phase | 3 (closing): Bug-42 silent-drop closure regression-suite |
| Source | Tag-48 Amara Auftrag (Continuous-Mode, 2026-05-19); Tag-41 PR #265 (Selin) Bug-42 fix; Tag-43 PR #278 (Selin) NATS-subjects-audit baseline |
| Date | 2026-05-19 (Tag-48 creation) |
| Test-File | [`tests/integration/test_bug_42_regression_suite_tag_48.py`](../../tests/integration/test_bug_42_regression_suite_tag_48.py) |
| Companion (contract module) | [`wirelang/persona_engine/publish_mode_contract.py`](../../wirelang/persona_engine/publish_mode_contract.py) |
| Companion (audit script) | [`scripts/audit/nats-jetstream-subjects-audit.py`](../../scripts/audit/nats-jetstream-subjects-audit.py) |
| Companion (audit doc) | [`docs/audit/nats-jetstream-subjects-audit.md`](../audit/nats-jetstream-subjects-audit.md) |
| Spec reference | `wirelang/specs/wirelang-spec-v0-2.md` §13.2 / §13.3 / §13.4 / §13.5 |
| Schema reference | `wirelang/schemas/layer-0-transport.json` (subject regex SoT) |

---

## 0. Contract scope

This document is the **Bug-42 regression-suite quality-gate** for
the Tag-48 substantive closure of the publish/subscribe surface
silent-drop class (Tag-41 PR #265).

Tag-41 PR #265 (Selin) closed Bug-42 F-1 by landing three artefacts:

1. **Adapter-B substrate** at
   `wirelang/persona_engine/publish_mode_contract.py` — the
   programmatic publish/subscribe surface compatibility matrix
   (spec §13.2 frozen table), the machine-readable failure-mode
   dispatch (spec §13.3 catalogue), and the `require_compatible(...)`
   preflight gate.

2. **Producer-side dispatch** at `wirelang/cli/bridge_forward.py`:
   a `--publish-mode {core,jetstream}` switch and the `js.publish`
   path (so the producer can opt into JetStream-publish semantics
   without an external Adapter A stream-mirror).

3. **Subscriber-side gate** at `wirelang/persona_engine/cli.py`:
   the `require_compatible(...)` call that refuses silent-drop pairs
   before binding the JetStream consumer.

Tag-43 PR #278 (Selin) extended the closure with a **static audit**
at `scripts/audit/nats-jetstream-subjects-audit.py` that pins the
fix at the codebase level: every Python / Rust source file is
scanned for publish/subscribe sigils, every `wakir.<env>.*` literal
is classified against the canonical schema regex, and every
mode-aware module is cross-checked for dispatch and gate consistency.
The first baseline (`reports/audit/2026-05-18-nats-jetstream-subjects-audit.md`):
0 drift rows across 276 scanned files.

The Tag-48 regression-suite is the **third layer** of the closure
contract: it pins the substantive invariants of the contract module
AND the audit script as observable test surface in CI, so a future
refactor on either side cannot silently re-open Bug-42.

This is **not** a re-implementation of either upstream test surface
(`tests/persona_engine/test_publish_mode_contract.py` already pins
the contract module's unit-level behaviour; `tests/audit/test_nats_jetstream_subjects_audit.py`
already pins the audit script's hermetic classifier). The Tag-48
suite is an **integration cross-check**: it asserts that the union
of the two surfaces is internally consistent and externally pinned
against the spec / schema source-of-truth.

---

## 1. The four-section test contract

### 1.1 Section A — Publish-Mode-Contract-Matrix (5 tests, A1 parametrized × 6 cells)

The spec §13.2 frozen matrix has six cells:

|                  | sub=core   | sub=js-push   | sub=js-pull   |
|------------------|------------|---------------|---------------|
| pub=core         | COMPATIBLE | F-2 BROKEN    | F-1 BROKEN    |
| pub=jetstream    | FANOUT¹    | COMPATIBLE    | COMPATIBLE    |

¹ Spec §13.2 footnote ¹ — fan-out MUST NOT be relied upon for
correctness (server-config-dependent).

| Test | Contract |
|---|---|
| A1 (parametrized × 6) | Every cell returns the expected verdict and failure-mode-id. |
| A2 | The matrix dimensions stay 2 × 3 — a future mode addition forces the parametrize gap to surface loudly. |
| A3 | `require_compatible` raises `SurfaceMismatchError` on F-1 (Adapter-B preflight gate intact). |
| A4 | `require_compatible` raises on FANOUT by default; `allow_fanout=True` opt-in returns the verdict. |
| A5 | `resolve_publish_mode` round-trips both valid modes via env var and rejects an unknown mode (`kafka`). |

### 1.2 Section B — NATS-Subject-Pattern-Drift (6 tests)

The Tag-43 audit baseline lists **24 wakir.* literals** in
production code (NATS subjects: 7, namespace-ids: 17). The 7 NATS
subjects span:

| File | Form |
|---|---|
| `wirelang/cli/bridge_forward.py:63` | template — `wakir.{env}.agent.agent.task.assigned.{persona_slug}` |
| `wirelang/persona_engine/nats_subscribe_loop.py:128` | template — `wakir.{env}.agent.agent.task.assigned.{persona_slug}` |
| `wirelang/persona_engine/nats_subscribe_loop.py:132` | template — `wakir.{env}.agent.agent.task.output.{persona_slug}` |
| `wirelang-rust/.../persona-engine-bridge-forward/src/lib.rs:295` | template — `wakir.{env}.agent.agent.task.assigned.{persona_slug}` |
| `wirelang-rust/.../persona-engine-bridge-forward/src/lib.rs:590` | concrete — `wakir.dev.agent.agent.task.assigned.tomas` |
| `wirelang-rust/.../persona-engine-subscribe-loop/src/lib.rs:82` | template — `wakir.{env}.agent.agent.task.assigned.{persona_slug}` |
| `wirelang-rust/.../persona-engine-subscribe-loop/src/ack_record.rs:405` | concrete — `wakir.dev.agent.agent.task.assigned.reza` |

| Test | Contract |
|---|---|
| B1 | The audit's `SCHEMA_SUBJECT_REGEX` mirrors `wirelang/schemas/layer-0-transport.json` `subject.pattern` exactly. |
| B2 | The inventory has exactly 7 NATS-subject hits (Tag-43 baseline). 8+ means a new publisher needs review; <7 means a publisher silently demoted. |
| B3 | Every NATS-subject row the audit classifies as `ok` actually matches the regex (templates → `TEMPLATE_SUBJECT_REGEX`, concrete → `SCHEMA_SUBJECT_REGEX`). |
| B4 | The inventory covers both event types (`task.assigned`, `task.output`) and contains a persona-slug concrete literal (`.tomas` / `.reza`). |
| B5 | Canonical regex rejects `wakir.dev.Agent.task.assigned` (capital domain) and `wakir.test.agent.task.assigned` (non-{dev,staging,prod} env). |
| B6 | The 7-subject split spans both Python and Rust — cross-language parity preserved. |

### 1.3 Section C — Failure-Mode-Catalogue (5 tests)

Spec §13.3 enumerates F-1..F-6:

| ID | Class | Pair-static? |
|----|-------|--------------|
| F-1 | core-pub → JS-pull-sub silent-drop | YES (in `_FAILURE_MODE_BY_PAIR`) |
| F-2 | core-pub → JS-push-sub silent-drop | YES (in `_FAILURE_MODE_BY_PAIR`) |
| F-3 | JS-pub → core-sub fan-out blocked | NO (server-config-dependent) |
| F-4 | JS-pub → JS-sub on wrong stream | NO (stream-filter-dependent) |
| F-5 | JS-pull-sub no `msg.ack()` | NO (subscribe-loop-state-dependent) |
| F-6 | Mode-flip post-bring-up | NO (operational drift) |

| Test | Contract |
|---|---|
| C1 | Spec file mentions all six IDs F-1..F-6 (no silent demotion). |
| C2 | `_FAILURE_MODE_BY_PAIR` maps exactly F-1, F-2 — F-3..F-6 stay out of pair-static dispatch (correct categorisation). |
| C3 | `SurfaceMismatchError` carries the `CompatibilityVerdict` with the right `failure_mode_id`; the exception message is operator-friendly. |
| C4 | For F-1/F-2 the verdict's `recommended_adapter` sentence cites both Adapter A (stream-mirror) and Adapter B (producer-rewrite). |
| C5 | COMPATIBLE and FANOUT verdicts have `failure_mode_id=None` (only BROKEN carries an ID — no annotation drift). |

### 1.4 Section D — Audit-Script-Invariants (4 tests)

The audit script is itself a regression target. A silent loosening
of its exclusion rules or a silent change to its classification
would let drift slip through CI undetected.

| Test | Contract |
|---|---|
| D1 | `audit_repo(.)` reports drift_count=0 and scanned_files≥200 at HEAD. |
| D2 | Three mode-cross-validation modules at HEAD: `bridge_forward.py`, `persona_engine/cli.py`, `publish_mode_contract.py`. 4+ means a new publisher needs Bug-42 review. |
| D3 | Namespace-id count ≥15 (Tag-43 baseline 17, allows growth, flags shrinkage); total wakir.* inventory ≥22 (Tag-43 baseline 24). |
| D4 | Audit CLI exits 0 in audit-only and 0 in `--enforce` mode (drift-free repo). |

---

## 2. Tag-48 baseline summary

- **Tests:** 25 collection-IDs (20 logical tests; A1 parametrized
  over 6 matrix cells contributes 6 IDs).
- **Pass rate at Tag-48 baseline:** 25/25.
- **Runtime:** ~2 seconds (hermetic, subprocess `--enforce` adds
  one fork).
- **Hermetic profile:** no live NATS, no container runtime, no
  network. Reads three on-disk files: contract module (importable),
  audit script (loaded via `importlib.util` because of hyphens in
  filename), spec / schema (text + JSON parse).

---

## 3. Bug-42 closure pyramid

The Bug-42 closure now stands on three layers:

| Layer | Suite | Owner | Pin |
|---|---|---|---|
| 1 — Contract unit | `tests/persona_engine/test_publish_mode_contract.py` (Tag-41) | Selin | Per-function behaviour of contract module (matrix, gate, env resolver). |
| 2 — Audit hermetic | `tests/audit/test_nats_jetstream_subjects_audit.py` (Tag-43) | Selin | Audit script classifier behaviour against synthetic fixtures (14 hermetic tests). |
| 3 — Integration regression | `tests/integration/test_bug_42_regression_suite_tag_48.py` (Tag-48, this gate) | Amara | Cross-check that the union of Layer-1 + Layer-2 stays internally consistent and externally pinned against spec / schema SoT. |

Layer 1 and Layer 2 are Selin's substantive surface; Layer 3 is the
QA Zone-M cross-component pin. The three layers are complementary,
not redundant: removing Layer 1 would leave the contract surface
unpinned; removing Layer 2 would leave the codebase-wide audit
classifier unpinned; removing Layer 3 would leave the union of the
two unpinned against the spec / schema SoT.

---

## 4. Quality-Gate criteria (Phase-3-acceptance)

For Phase-3-Welle-Marathon acceptance the Bug-42 closure must
satisfy:

1. **G-Bug-42-1:** `tests/integration/test_bug_42_regression_suite_tag_48.py`
   passes 25/25 at HEAD on every CI run.
2. **G-Bug-42-2:** `scripts/audit/nats-jetstream-subjects-audit.py --enforce`
   exits 0 on every CI run (i.e. drift-free repo).
3. **G-Bug-42-3:** No new publish-call site is merged without a
   companion review against the `--publish-mode` dispatch and (if
   subscriber-side) the `require_compatible(...)` gate. Test D2 is
   the early warning when this discipline lapses.
4. **G-Bug-42-4:** No spec §13 amendment (failure-mode-catalogue or
   compatibility matrix) lands without an accompanying update to
   this regression-suite and the Tag-43 audit script. Tests C1, C2,
   and B1 are the early warnings.

---

## 5. Zone-M / Zone-N posture

- **Zone-M (QA × Persona-Engine):** Selin owns the substantive
  surface (contract module + audit script). Amara owns the
  integration regression-suite as cross-component pin. Tag-48
  delivery coordinated as a read-only consumer of Selin's surface
  (no edits to `publish_mode_contract.py` or the audit script).

- **Zone-N (QA × Internal-Audit, Henrik):** This gate's evidence
  (test pass-rate, audit drift-count) is a QA-evidence input for
  Henrik's quarterly Audit-Sample. The boundary is preserved: QA
  verifies *functional behaviour*, Henrik verifies *governance
  compliance* (ADR-Konsistenz, sample-based review of the audit
  workflow's CI posture). Henrik may consume the test pass-rate as
  one input but does not re-run the suite.

---

*Created: 2026-05-19 (Tag-48). — Amara*
