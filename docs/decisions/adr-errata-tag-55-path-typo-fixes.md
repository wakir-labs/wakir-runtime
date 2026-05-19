<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors
-->

# ADR-Errata — Tag-55 Path-Typo Fixes (ERR-S1..S6)

**Status:** documented (Tag-55, 2026-05-19).
**Source audit:** `reports/audit/adr-spec-compliance-audit-2026-05-19.md`
(Tag-54 ADR Spec-Compliance Audit, Reza, PR #349).
**Scope:** runtime-side documentation snapshot of six errata against
corp-internal ADRs (`AI-Corp/decisions/`). This file records the
corrected canonical citations so that downstream tooling, scripts,
and follow-up ADRs read against ground-truth paths at main-tip.

This is **not** an ADR-Vorlage. Per Reza Persona §4, errata-addenda
in the runtime repo are a documentation hand. The actual ADR-head
addenda in `AI-Corp/decisions/` remain a Mira-hand item.

## 1. Errata Inventory

| ERR-ID | Target ADR | Surface (cited) | Corrected canonical citation |
|---|---|---|---|
| ERR-S1 | 0034 | `wirelang/spec/v0.1.0/*.md` | `wirelang/specs/wirelang-spec-v0-*.md` |
| ERR-S2 | 0034 | `wirelang/parser/*.py` | `wirelang/builder/*.py` + `wirelang/canonical/*.py` + `wirelang/identity/*.py` |
| ERR-S3 | 0034 | `decisions/0023a-wirelang-tech-spec.md` | `decisions/0023a-inter-agent-protokoll-layer-architektur.md` (filename uses `0023a-` prefix; the cited `0023a-wirelang-tech-spec.md` does not exist; the Wirelang-Tech-Spec content rolled into ADR-0023 as Pfad gamma) |
| ERR-S4 | 0052 | `wirelang/canonical/self_reference.py (~50 LOC)` exporting `verify_caveat_hash_self_reference(caveats)` | folded into `wirelang/canonical/caveat_set.py`; the `caveat_hash` self-reference predicate is implemented inline (no standalone helper module, no function with the exact cited name; semantic substance preserved via the `caveat_hash`-promotion predicate in `caveat_set.py`) |
| ERR-S5 | 0062 | `wakir-runtime/wirelang/spec/`, `wirelang/parser/` (Source-Origin list, line 72-73) | `wakir-runtime/wirelang/specs/`, `wakir-runtime/wirelang/builder/`, `wakir-runtime/wirelang/canonical/`, `wakir-runtime/wirelang/identity/` (same correction-pair as ERR-S1+S2; applies at repo-split-execution) |
| ERR-S6 | 0064 | `wirelang/persona_engine/llm_hook.py` exporting `EchoReflectionLlmHook` (Phase-2-Stub) and `anthropic_messages_hook_phase_3_stub()` | both symbols live in `wirelang/persona_engine/llm_call_shim.py` (single file, not three; the audit's three-file split was a heuristic guess that the working-copy refuted). `EchoReflectionLlmHook` is exported at line 177; `anthropic_messages_hook_phase_3_stub` is exported at line 270. Both names survived. |

## 2. Cross-Reference Table (runtime substrate as authority)

The following are the **present-tense canonical paths** at runtime
main-tip. These are the citations future ADRs and audit tooling
should adopt:

### 2.1 Wirelang spec dir

- Canonical: `wirelang/specs/` (with trailing `s`).
- Files: `wirelang-spec-v0-2.md`, `wirelang-spec-v0-4-1.md`,
  `wirelang-spec-v0-4-2.md`, `wirelang-spec-v0-4-3.md`.
- The v0.4 base spec is referenced as `wirelang/specs/wirelang-spec-v0-4-3.md`
  for pre-cutover-freeze pinning (Tag-53 PR #338).

### 2.2 Reference-parser surfaces

The historic "Reference-Parser" surface (ADR-0034 line 323) was
never produced as a separate top-level dir. The semantic-equivalent
code is split across:

- `wirelang/builder/` — frame-builder (`frame_builder.py`).
- `wirelang/canonical/` — canonical caveat-set (`caveat_set.py`).
- `wirelang/identity/` — identity-substrate Python modules
  (`key_derivation.py`, `did_document.py`, `aip_document.py`,
  `shamir_split.py`, `aip_signing.py`).

License-mix for these three subtrees is Apache-2.0 (per ADR-0061
license hygiene welle Phase-1). Any future license-mix table in
ADR-0034 or downstream should cite these three paths in place of
the non-existent `wirelang/parser/`.

### 2.3 LLM-hook surface (ADR-0064)

- Canonical file: `wirelang/persona_engine/llm_call_shim.py`.
- License: BUSL-1.1 (BSL — per ADR-0061 persona_engine subtree).
- Public symbols (verified by `__all__` block):
  - `EchoReflectionLlmHook` (Phase-2-Stub class)
  - `anthropic_messages_hook_phase_3_stub` (factory function)
- Two adjacent files in the same package implement complementary
  surfaces (`llm_classifier.py`, `rust_adapter_hook.py`) but
  neither replaces `llm_call_shim.py` as the canonical LLM-hook
  trait-layer file.

### 2.4 Caveat-hash self-reference (ADR-0052)

- Canonical file: `wirelang/canonical/caveat_set.py`.
- The Class-P `caveat_hash` self-reference predicate is documented
  in the file's module docstring (search-term: "self-reference
  predicate (Phase-2 Class P").
- There is no standalone `wirelang/canonical/self_reference.py`.
- There is no function with the literal name
  `verify_caveat_hash_self_reference`. The verification flow runs
  through `caveat_set.py` together with the schema-bound
  `datalog-caveat/0.2.1` Class-P predicate.

## 3. Out-of-Scope (recorded for completeness)

- ERR-S3 dual-claim: the audit recommended renaming the cited
  filename from `0023a-` to `0023-`. The corp-decisions inventory
  shows `0023a-inter-agent-protokoll-layer-architektur.md` is
  the actual filename (with `a` suffix), so the audit's `0023-`
  recommendation was off-by-one. The right correction is: drop
  the non-existent `0023a-wirelang-tech-spec.md` citation; cite
  the actual `0023a-inter-agent-protokoll-layer-architektur.md`
  instead (or drop the citation entirely since the Wirelang-Tech-
  Spec content rolled into ADR-0023 as Pfad gamma at activation).
- The ADR-head addenda in `AI-Corp/decisions/` are out-of-scope
  for runtime PRs. They are a separate Mira-hand follow-up.

## 4. Verification

Hermetic tests pin every claim in this errata document against the
runtime working-copy. See `wirelang/tests/test_adr_errata_tag55.py`
(11 tests).

## 5. Author Note

Errata are advisory only. No ADR semantic decision is reversed.
Path-typo corrections do not require ADR-supersedure; they require
documentation hygiene.

Per Reza Persona §4, no ADR-Vorlage is filed. This document is the
runtime-side audit-trail artefact, mirroring how the Tag-54 audit
report itself was filed as `reports/audit/...` rather than as an ADR.

— Reza
