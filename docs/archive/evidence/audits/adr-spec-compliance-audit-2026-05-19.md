<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors
-->

# ADR Spec-Compliance Audit (Tag-54)

- **Generated:** 2026-05-19T01:25:00Z (Tag-54 RE-DISPATCH, Continuous-Mode)
- **Audit class:** static cross-reference walk over ADR set vs.
  `wakir-runtime` main-tip
- **Auftrag:** Mira (CEO), Re-Dispatch nach Quota-Hit 03:20 CEST
- **Spec under audit:** Wirelang-Spec stream
  (`wirelang/specs/wirelang-spec-v0-4.md`,
  `wirelang/specs/wirelang-spec-v0-4-1.md`,
  `wirelang/specs/wirelang-spec-v0-4-2.md`,
  `wirelang/specs/wirelang-spec-v0-4-3.md`) at main-tip
- **Audit baseline (main tip):** `f713e75` — Tag-53 final-sanity-gate
  S2 freeze-regex hotfix + operator runbook (#345)
- **Spec freeze marker (main-tip):** v0.4.3 pre-cutover-freeze
  (`freeze-anchor: persona-engine-0.5.2-final-pre-cutover`,
  Tag-53 PR #338, 2026-05-19)
- **ADR-Scope:** ADR-0009, 0021, 0035, 0036, 0040, 0058,
  0061..0068 (Auftrags-Set)
- **ADR-Extended:** ADR-0023a (Inter-Agent-Protokoll), ADR-0034
  (Lizenz-Strategie), ADR-0047 (Phase-Gate), ADR-0052 (Class-P-
  Promotion), ADR-0031 (Federation), ADR-0048 (Anti-AI-Slop) —
  additional surfaces found during sweep, included for completeness
- **Author role:** Dev-Engineering-2 / Wirelang (Reza)

## 1. Scope and Method

The audit is a static cross-reference walk. For every ADR in scope
the document was scanned for citations of:

- Wirelang Spec versions (e.g. `v0.4`, `v0.4.1`, `v0.4.2`, `v0.4.3`).
- Wirelang Spec paths (e.g. `wirelang/specs/`, `wirelang/spec/`).
- Wirelang substrate paths (e.g. `wirelang/schemas/registry.py`,
  `wirelang/canonical/self_reference.py`,
  `wirelang/persona_engine/llm_hook.py`).
- Schema-`$id` versions (`datalog-caveat/0.2.1`,
  `aip-document/0.1.0`, ...).
- Vocabulary file names (`datalog-caveat-vocabulary.md`,
  `datalog-caveat-vocabulary-phase-2.md`).

Each citation was verified against the working-copy at main-tip
`f713e75`. The verdicts are:

- **MATCH** — the citation resolves to an actually present
  artefact at main-tip with the same name and surface as cited.
- **DRIFT (expected)** — the citation no longer resolves, but the
  drift was introduced by a downstream ADR that consciously
  superseded the surface. No erratum is required because the
  later ADR governs.
- **DRIFT (erratum-pending)** — the citation no longer resolves
  and the drift was not picked up by any downstream ADR; the ADR
  still reads as if the cited artefact were authoritative. An
  ADR-erratum addendum is recommended.
- **MATCH-after-renormalisation** — the citation resolves once a
  trivial path-typo (e.g. `wirelang/spec/` vs. `wirelang/specs/`)
  is resolved.

## 2. Per-ADR Findings

### ADR-0009 — Zweiter Engineering-Agent (Reza)

- **Citations:** "Wirelang-Spec/Schema-Registry v0.1" (line 243),
  "ADOL-Foundation", "Wirelang-Schema-Registry v0.1".
- **Verdict:** MATCH. ADR-0009 is the Reza-activation ADR (Tag-Phase-0,
  2026-05-05). Its "Wirelang-Schema-Registry v0.1" forward-looking
  citation was satisfied by the Phase-1a closeout at Tag-15 (see
  ADR-0047). The spec stream evolved past v0.1 (now at v0.4.3) but
  ADR-0009 sets only the activation gate, not a version pin. No
  drift, no erratum needed.

### ADR-0021 — Übersichts-Frontend (Quartz)

- **Verdict:** MATCH (no Wirelang citations beyond surface
  references). Frontend ADR — Wirelang-Spec is not in scope.

### ADR-0023a — Inter-Agent-Protokoll Layer-Architektur

- **Citations:** "v0.1 → v0.2" (line 249) — abstract version-bump
  example.
- **Verdict:** MATCH. ADR-0023a predates concrete spec numbering;
  the cited `v0.1 → v0.2` is illustrative, not a pin. Today's
  v0.4.3 freeze marker is consistent with the schema-versioning
  policy ADR-0023a sketches.

### ADR-0031 — Inter-Org-Federation-Architecture

- **Citations:** `https://wakir.dev/wirelang/schema/<version>.json`
  (line 205) — URL pattern.
- **Verdict:** MATCH. The pattern is consistent with the seven
  `$id`s shipped under `wirelang/schemas/` (e.g.
  `https://wakir.dev/wirelang/schema/datalog-caveat/0.2.1`). The
  URL is a documentation pattern, not a live-fetch promise.

### ADR-0034 — Repo-Lizenz-Strategie

- **Citations:**
  - `wirelang/spec/v0.1.0/*.md` (line 322).
  - `wirelang/parser/*.py` (line 323).
  - `decisions/0023a-wirelang-tech-spec.md` (line 344).
- **Verdict:** DRIFT (erratum-pending).
  - `wirelang/spec/` does **not** exist. Correct path is
    `wirelang/specs/` (with `s`).
  - `wirelang/parser/` does **not** exist. The reference-parser
    surface was never produced as a separate top-level dir; the
    semantic-equivalent code lives in `wirelang/builder/`,
    `wirelang/canonical/`, and `wirelang/identity/`.
  - `decisions/0023a-wirelang-tech-spec.md` does **not** exist.
    ADR-0023a is filed as `0023-inter-agent-protokoll-layer-
    architektur.md`; the original Tomás Wirelang-Tech-Spec ADR
    was rolled into ADR-0023 as Pfad γ.
- **Severity:** Medium. ADR-0034 is the license-mix anchor and is
  consumed by ADR-0061 / ADR-0062 — the pathing typos do not
  invalidate the license decision (Apache-2.0 surface is correct
  by content), but should be corrected so license-audit tooling
  does not look up non-existent paths.
- **Recommendation:** Light erratum addendum (single paragraph at
  ADR head): rename `wirelang/spec/` → `wirelang/specs/`,
  `wirelang/parser/*.py` → `wirelang/builder/*.py +
  wirelang/canonical/*.py + wirelang/identity/*.py`, drop the
  `0023a-` filename and cite `0023-` instead.

### ADR-0035 — Framework-Sprache Python/Rust Hybrid

- **Citations:** Multiple `wirelang/identity/*.py` paths
  (lines 162-167), `wirelang/schemas/*.json` (line 167),
  `wirelang/tests/*.py` (line 168).
- **Verdict:** MATCH. All cited Python identity-substrate files
  exist (`key_derivation.py`, `did_document.py`,
  `aip_document.py`, `shamir_split.py`, `aip_signing.py`). The
  JSON-Schema surface and Python-test surface exist.
- **Note:** ADR-0035 cites *production* paths to make the case
  for Rust-rewrite. ADR-0063 / ADR-0065 govern the actual
  Python→Rust cutover; the Python files are still present at
  main-tip because the Rust-Default cutover has not landed yet.
  Consistent with ADR-0065 §Phase-3c-Cutover-Plan.

### ADR-0036 — Self-Migration-Plan

- **Citations:** "Wirelang (typed Inter-Agent-Messaging)" (line 29).
- **Verdict:** MATCH. High-level reference, no version pin or
  path citation.

### ADR-0040 — Frontend-Engineer-Persona-Aktivierung

- **Citations:** "Wirelang-Schemas (Reza-Domain) für Persona-
  Editor-Validation" (line 104), "Zone E — Frontend × Wirelang-
  Schema" (line 123).
- **Verdict:** MATCH. Zone-E cross-review boundary is consistent
  with the seven schemas inventoried in
  `docs/wirelang-schema-inventory.md`.

### ADR-0047 — Phase-Gate-Kriterien Phase-1a → Phase-1b

- **Citations:**
  - `wirelang/schemas/registry.py` (line 101).
  - `wirelang/schemas/` 7 JSON-Schemas (line 100).
  - `wat/`, `wirelang/tooling/scripts/tests`, `docs/`/`specs/`
    license-mix (line 143).
- **Verdict:** DRIFT (erratum-pending), partially.
  - The `registry.py` file does **not** exist at the cited path.
    Today the schema-registry surface is implemented as
    `wirelang/schemas/registry_nats_kv_backend.py` (Phase-1b NATS-
    KV backend), with the Phase-1a in-memory registry surface
    consolidated into `wirelang/schemas/__init__.py` (per ADR-0062
    Cut-2 protocol-layer-consolidation note).
  - The 7-schema count at line 100 is **MATCH**: today seven
    schemas ship (`docs/wirelang-schema-inventory.md`).
- **Severity:** Low. The phase-gate cited evidence (Tag-15 baseline)
  was correct at decision-time. The substrate moved; ADR-0047
  was the gate, not a moving target.
- **Recommendation:** No erratum required. Phase-gate ADRs are
  point-in-time decisions; they should not chase substrate
  evolution. The renaming is captured in ADR-0062 governance.

### ADR-0048 — Anti-AI-Slop Schreib-Qualitäts-Pflicht

- **Verdict:** MATCH (no concrete Wirelang citations).

### ADR-0052 — Class-P-Promotion `caveat_hash`

- **Citations:**
  - `wirelang/specs/datalog-caveat-vocabulary-phase-2.md` §3.4
    (line 32-33). **MATCH** — file exists.
  - `wirelang/canonical/caveat_set.py` (line 40). **MATCH** —
    file exists at the cited path.
  - `wirelang/canonical/self_reference.py` (line 208-209).
    **DRIFT (erratum-pending)** — file does **not** exist at
    main-tip. The promotion-implementation surface either
    consolidated into `wirelang/canonical/caveat_set.py`
    (most likely) or `wirelang/canonical/__init__.py`. The
    `verify_caveat_hash_self_reference(caveats)` function name
    cited in line 209 was not found via grep.
  - `wirelang/tests/test_caveat_hash_promotion_substrate.py`
    (line 131, 166). **MATCH** — file exists.
  - Schema-`$id` `datalog-caveat/0.2.1` (line 87, 143).
    **MATCH** — `wirelang/schemas/datalog-caveat.json` `$id`
    today is `https://wakir.dev/wirelang/schema/datalog-caveat/
    0.2.1`. Consistent.
  - `wirelang/tests/fixtures/tv-w-2/` (line 262). **MATCH** —
    `pin-pack.json` + `README.md` present.
- **Severity:** Low. The promotion landed; only the helper-module
  filename diverged.
- **Recommendation:** Light erratum addendum at ADR-0052 head:
  rename `wirelang/canonical/self_reference.py (~50 LOC)` →
  `consolidated into wirelang/canonical/caveat_set.py
  (verify_caveat_hash_self_reference helper)`. Or confirm by
  Selin/Reza code-search where the function actually lives.

### ADR-0058 — Pilot-Persona-Migrations-Plan

- **Citations:**
  - `wirelang/specs/persona-engine-format-spec.md` v1.0
    (lines 17, 55, 96, 194).
- **Verdict:** DRIFT (expected — superseded by ADR-0063 +
  Sprint-Pengine-7 evolution).
  - File exists at cited path.
  - Header version at main-tip is `1.2.0` (frontmatter) / `v1.3`
    (heading) — major version step from cited v1.0.
  - The drift is **expected** because the persona-engine-format-
    spec evolution was a known additive process under Pengine-
    sprint cadence (Tag-1 v1.0 → Tag-4 v1.3).
- **Severity:** None (drift is expected).
- **Recommendation:** No erratum. ADR-0058 was an entry-gate ADR;
  the version pin would be inappropriate.

### ADR-0061 — License-Hygiene-Welle Phase-1

- **Citations:**
  - `wirelang/federation/`, `wirelang/persona_engine/`,
    `wirelang/persona/` (lines 37, 39, 46, 75, 78-79, 92,
    123-124, 163-167).
- **Verdict:** MATCH. All cited Wirelang subtrees exist at
  main-tip with the cited license markers (BSL for federation
  + persona_engine, Apache for the rest).

### ADR-0062 — Repo-Split-Strategie Phase-2

- **Citations:**
  - `wakir-runtime/wirelang/spec/` (line 72) **DRIFT** — should
    be `wirelang/specs/`.
  - `wirelang/parser/` (line 73) **DRIFT** — does not exist.
  - "Wirelang-Spec Layer 0-2, AIP-Wrapper, Identity-Substrate-
    Krypto" (line 216) — abstract reference, MATCH.
- **Severity:** Low. Same drift pattern as ADR-0034: path typos
  that pre-date the standardisation of `wirelang/specs/` plural.
  Since ADR-0062 governs the future split (target = new repo
  `wakir-protocol`), the path-typos will be cleaned up during
  the actual repo-split execution. No standalone erratum needed
  if the repo-split-execution captures it.
- **Recommendation:** Add a cross-reference in the eventual
  repo-split-execution ticket to rename `wirelang/spec/` →
  `wirelang/specs/` in the destination layout and to drop
  `wirelang/parser/` from the asset list (or replace with the
  actual reference-implementation paths
  `wirelang/builder/ + wirelang/canonical/`).

### ADR-0063 — Persona-Engine-Sprach-Revision (Rust Rewrite)

- **Citations:**
  - `wirelang/persona_engine/` Python module (lines 21, 27, 207,
    221-222). **MATCH** — Python module exists.
  - `wirelang-rust/crates/persona-engine/` scaffold (line 207).
    **MATCH-pending** — Rust scaffolding under
    `runtime/wakir-runtime` lives in
    `crates/wakir-persona-engine/` (per Tag-49+ migration plan;
    not under `wirelang-rust/` umbrella). Path-cite is
    aspirational at ADR-time.
  - `wirelang/persona_engine_py_legacy/` retire target (line 222).
    **DRIFT (expected)** — does **not** exist at main-tip
    because the Phase-3c-cutover (ADR-0065) has not yet executed
    the rename. ADR-0065 §Cutover-Step explicitly cites this
    rename as a downstream action.
- **Severity:** None (drift is sequenced).
- **Recommendation:** No erratum. ADR-0065 governs the actual
  rename; ADR-0063 is the strategic frame.

### ADR-0064 — Model-Routing + Prompt-Caching für Persona-Engine

- **Citations:** Trait-Layer `wirelang/persona_engine/llm_hook.py`
  with `EchoReflectionLlmHook` and
  `anthropic_messages_hook_phase_3_stub()` (lines 18-20).
- **Verdict:** DRIFT (erratum-pending).
  - `wirelang/persona_engine/llm_hook.py` does **not** exist at
    main-tip.
  - The LLM-hook surface today lives across
    `wirelang/persona_engine/llm_call_shim.py`,
    `wirelang/persona_engine/llm_classifier.py`, and
    `wirelang/persona_engine/rust_adapter_hook.py`.
  - The `EchoReflectionLlmHook` and
    `anthropic_messages_hook_phase_3_stub()` symbols cited at
    ADR-0064-time may have been renamed or split during the
    rust-adapter migration; symbol-grep at main-tip finds
    neither name.
- **Severity:** Medium. ADR-0064 is the prompt-caching strategy
  anchor and is consumed by downstream ops decisions. The path
  divergence is real and the symbol-naming is unconfirmed.
- **Recommendation:** Erratum addendum at ADR-0064 head: list
  the three replacement files and confirm where the
  `EchoReflectionLlmHook` Phase-2-stub got merged (probably
  `llm_classifier.py` or `llm_call_shim.py` — needs code-walk).

### ADR-0065 — Phase-3c Cutover (Python-Default → Rust-Default)

- **Citations:**
  - `wirelang/persona_engine_py_legacy/` (lines 288, 381) —
    rename target. **DRIFT (expected, pre-cutover)** — directory
    does not exist because the cutover has not landed at
    main-tip. Tag-53 PR #338 marks pre-cutover-freeze;
    rename happens at KW-24 cutover gate.
- **Verdict:** No drift in ADR-0065 itself. The ADR is a future-
  state plan, not a present-tense description.

### ADR-0066 — Phase-3c-Beschleunigung Option A+

- **Verdict:** MATCH (no concrete Wirelang-spec path citations
  beyond ADR-0065 lineage).

### ADR-0067 — SVID-Cutover Phase-4 Verschiebung (WITHDRAWN)

- **Status:** withdrawn 2026-05-18. **Excluded from drift-risk
  calculus** (per status block).

### ADR-0068 — Status-Aggregator-Workflow

- **Citations:** "11 paths-filtered Jobs im CI-Stack (wirelang
  suite production + shadow, License-Hygiene, cross-repo drift,
  production-vs-sandbox drift envelope, ...)" (lines 17-18).
- **Verdict:** MATCH. The cited surface is consistent with
  `.github/workflows/ci-aggregator.yml` at main-tip (Tag-53):
  `tests.yml` (Wirelang production lane) and `sandbox-ci.yml`
  (Wirelang sandbox lane) are both present and both wired into
  the aggregator (`ci-aggregator` job is the Required-Check).

## 3. Drift Summary Table

| ADR | Severity | Type | Recommendation |
|---|---|---|---|
| 0009 | None | — | No action |
| 0021 | None | — | No action |
| 0023a | None | — | No action |
| 0031 | None | — | No action |
| 0034 | Medium | erratum-pending | Light erratum: path typos `spec` vs `specs`, `parser`, `0023a-` filename |
| 0035 | None | — | No action |
| 0036 | None | — | No action |
| 0040 | None | — | No action |
| 0047 | Low | obsolete-by-design | No action; point-in-time gate |
| 0048 | None | — | No action |
| 0052 | Low | erratum-pending | Light erratum: helper-module rename `self_reference.py` |
| 0058 | None | expected-drift | No action |
| 0061 | None | — | No action |
| 0062 | Low | erratum-pending | Captured by repo-split-execution |
| 0063 | None | sequenced-drift | No action |
| 0064 | Medium | erratum-pending | Erratum: LLM-hook file rename + symbol confirmation |
| 0065 | None | future-state | No action |
| 0066 | None | — | No action |
| 0067 | Withdrawn | — | N/A |
| 0068 | None | — | No action |

## 4. Headline Findings

- **Spec-version compliance:** Every ADR that pins a Wirelang Spec
  version (or pins a version-conditional behaviour) is consistent
  with the main-tip v0.4.3 pre-cutover-freeze. No ADR cites a
  spec-version that contradicts v0.4.3's strict-superset
  guarantee (every v0.4.0 / v0.4.1 / v0.4.2 frame remains valid).
- **Path-citation hygiene:** Two systematic typos appear across
  ADR-0034 and ADR-0062: `wirelang/spec/` (without `s`) and
  `wirelang/parser/`. Both are corrigible with a single erratum
  pair.
- **LLM-hook rename:** ADR-0064 cites `llm_hook.py` which has
  fragmented into three files. This is the most consequential
  drift because ADR-0064 is the live prompt-caching anchor.
- **Class-P helper module:** ADR-0052 cites
  `self_reference.py` which does not exist as a standalone file.
  Function may have been folded into `caveat_set.py` — needs
  code-walk confirmation.
- **Pre-cutover-freeze respected:** No ADR in scope cites a
  post-freeze symbol or path that would violate the v0.4.3
  freeze surface (frame attrs, caveat predicates, ENV-flag
  schema). The freeze is structurally intact.

## 5. Recommended Errata (for AR-Pre-Sichtung)

| Erratum-ID | ADR | Surface | One-Sentence Fix |
|---|---|---|---|
| ERR-S1 | 0034 | `wirelang/spec/` typo | rename to `wirelang/specs/` in license-mix table |
| ERR-S2 | 0034 | `wirelang/parser/` non-existent | replace with `wirelang/builder/ + wirelang/canonical/` |
| ERR-S3 | 0034 | `0023a-` filename | rename to `0023-` |
| ERR-S4 | 0052 | `self_reference.py` helper module | confirm where `verify_caveat_hash_self_reference` lives today |
| ERR-S5 | 0062 | `wirelang/spec/` + `parser/` | same as ERR-S1+S2, applied in repo-split-execution ticket |
| ERR-S6 | 0064 | `llm_hook.py` + `EchoReflectionLlmHook` | replace with three present files; confirm symbol survival |

The total erratum work-load is small: six addenda, all single-
paragraph at ADR head. None of the errata change semantic decisions.
Recommend bundling as a single follow-up PR after AR-pre-sichtung.

## 6. Out-of-Scope (recorded for completeness)

- ADR-0067 is withdrawn; not audited.
- ADR-0066 has no Wirelang-spec citations of substance (Phase-3c
  accel plan).
- ADR-0021 is frontend-only.

## 7. Audit Methodology Notes

- Static cross-reference only: no test execution, no engine boot,
  no remote fetch.
- Working-copy at main-tip `f713e75` (Tag-53 final-sanity-gate
  hotfix). No uncommitted-state contamination (clean worktree).
- Symbol-existence verified by `find ... -name` and `grep -l`.
- Schema-`$id` verified by inline JSON property read.
- ADR-erratum recommendations are advisory only — no ADR-vorlage
  is produced; that is Mira's call after AR-pre-sichtung
  (per Reza Persona §4 — keine ADR-Vorlagen).

— Reza
