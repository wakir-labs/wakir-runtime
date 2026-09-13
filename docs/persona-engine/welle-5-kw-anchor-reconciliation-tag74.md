<!--
REUSE-IgnoreStart
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
REUSE-IgnoreEnd
-->

# Welle-5 KW-Anchor Reconciliation — Tag-74

| Field | Value |
|---|---|
| Owner | Selin (Persona-Engine) |
| Date | 2026-05-19 |
| Status | Final — committed in the Tag-74 PR alongside the Welle-6 producer add-on. |
| Scope | `tooling/ci/render_engine_state_file_stub.py` default-map + `state/welle-4.json` + `state/welle-5.json` kw_cutover_anchor. |

## 1. Question

Where does the operational Source-of-Truth for the Welle-N KW-anchor
field live, when multiple canonical docs disagree?

Concrete instance (Tag-74 W5-anchor-Drift-Fix):

* `tooling/ci/render_engine_state_file_stub.py` (Tag-68 helper-default)
  mapped Welle-5 to `KW-25` (and Welle-4 to `KW-25`).
* `docs/quality-gates/pre-cutover-acceptance-run-order.md` §3 per-Welle
  Run-Order table (lines 90..98) lists Welle-4 and Welle-5 on `KW-26`
  (Cutover-Mittwoch 2026-06-24, Sign-off-Freitag 2026-06-26 — the
  ADR-0066 Doppel-Welle-4+5).
* `docs/quality-gates/phase-3c-doppel-welle-4-5.md` §3.2 Leg-2 header
  reads "Welle-5 cutover (cutover-Mittwoch KW 27)" — a stale residual
  reference from a pre-ADR-0066 schedule draft.
* `state/welle-5.json` (committed) carried `kw_cutover_anchor: KW-25`
  until this PR; `state/welle-4.json` likewise.
* Producer-substrate docstrings (e.g. `handle_welle_5_signoff_event`)
  carry the inherited string `KW-25 Fr 2026-06-19` from the Tag-73
  Welle-5 add-on — these are historical references, not runtime gates.

## 2. Resolution rule (Mira-Hand call, Tag-74)

There are **two canonical-doc views** in the codebase for the Welle-N
KW-anchor field, with intentionally different framings:

| View | Doc | Aggregator | KW-anchor philosophy |
|---|---|---|---|
| **Run-order** | `docs/quality-gates/pre-cutover-acceptance-run-order.md` §3 table | engine-side helper + state-files + producer | "Which KW does the Cutover-Mittwoch sit on?" (ADR-0066 four-Wochen-Cadence) |
| **Acceptance-criteria** | `docs/quality-gates/kw-24-welle-1-7-acceptance-criteria.md` | `tooling/ci/aggregate_kw_24_welle_acceptance.py` `WELLE_ANCHORS` | "Which KW + weekday + modul-focus does the acceptance-gate-evidence anchor on?" |

The two views disagree on Welle-4, Welle-5, Welle-6 KW-anchor. The
Tag-73 Welle-5 aggregator
(`tooling/ci/aggregate_welle_5_integration.py::BRIEF_VS_CANONICAL_
RECONCILIATION`) already documents this dual-view precedent and
surfaces both verbatim on the envelope.

> **Tag-74 resolution rule: the engine-side runtime artefacts (the
> helper-default `CANONICAL_KW_ANCHOR` map + the committed
> `state/welle-N.json` files) align to the run-order view. The
> acceptance-criteria-view aggregator stays as-is. Cross-view
> disagreement is surfaced (not erased) via the brief-vs-canonical
> reconciliation envelopes.**

Rationale: `pre-cutover-acceptance-run-order.md` §3 is the run-order
doc that Amara, Henrik, and Aisha consult on Cutover-Mittwoch and
Sign-off-Freitag. It is downstream of ADR-0066 (four-Wochen-Cadence
KW-24..KW-27) and the Tag-57 Amara Auftrag roll-up. The engine-side
`state/welle-N.json` files are runtime rollup-records consumed by the
producer-substrate; the producer is kw-anchor-agnostic (§3 below), so
the runtime alignment is to whichever doc the *human* operator
consults when filing the state-file kw_cutover_anchor field — that is
the run-order doc.

The acceptance-criteria view remains valid as the *parallel-substrate-
evidence view* used by the kw-24-welle-1-7-acceptance-criteria
aggregator; that aggregator's `WELLE_ANCHORS` map is unchanged in
Tag-74. Producer-substrate docstrings and helper-default maps that
inherit stale KW-anchor strings (e.g. the Tag-73-era
`KW-25 Fr 2026-06-19` string for Welle-5) are run-order-view artefacts
and MUST be brought into alignment by an explicit reconciliation PR
(this PR is that reconciliation for the Tag-74 W5-fix scope).

## 3. Producer-substrate scope clarification

The Welle-N producer-substrate
(`wirelang/persona_engine/welle_state_producer.py`) is
**kw-anchor-agnostic** at the transition-machine level:

* The Welle-N transition guards (`handle_cutover_event`,
  `handle_sign_off_event`, `handle_welle_2_sealing_event`,
  `handle_welle_4_signoff_event`, `handle_welle_5_signoff_event`,
  `handle_welle_6_signoff_event`, `handle_rollback_event`) do NOT read
  the `kw_cutover_anchor` field for any decision.
* The `kw_cutover_anchor` field is preserved across transitions
  (read-then-write) but never consulted as a precondition.
* The schema-pin (`docs/quality-gates/welle-n-state-file-conventions.md`,
  Tag-67) requires the field to match `^KW-2[2-7]$`; that is the only
  producer-side invariant on the field.

This means the Tag-74 W5-anchor-Drift-Fix is a **doc-level + state-file-
level alignment** PR; it changes no runtime behaviour. A subsequent
re-anchor (e.g. an ADR rebasing Welle-5 to a different KW) would need
a state-file update and a helper-default update but no producer-code
change.

## 4. Tag-74 fix delta

The Tag-74 PR aligns the engine-side helper-default and the committed
state-files to the §3 table:

| Artefact | Before Tag-74 | After Tag-74 | Source-of-Truth |
|---|---|---|---|
| `render_engine_state_file_stub.py::CANONICAL_KW_ANCHOR[4]` | `KW-25` | `KW-26` | §3 table line 95 |
| `render_engine_state_file_stub.py::CANONICAL_KW_ANCHOR[5]` | `KW-25` | `KW-26` | §3 table line 96 |
| `state/welle-4.json::kw_cutover_anchor` | `KW-25` | `KW-26` | §3 table line 95 |
| `state/welle-5.json::kw_cutover_anchor` | `KW-25` | `KW-26` | §3 table line 96 |

Welle-1/2/3/7 already matched the §3 table and require no Tag-74 fix.

## 5. Known residual drift (out-of-scope for Tag-74)

The Tag-74 PR addresses the engine-side W4+W5 alignment. The
following drift items are flagged for a follow-up doc-refresh and are
**not** in Tag-74 scope:

### 5.1 `phase-3c-doppel-welle-4-5.md` §3.2 Leg-2 header

The string "Welle-5 cutover (cutover-Mittwoch KW 27)" on line 119 is
stale (§3 table places Welle-5 on KW-26). Recommendation: doc-refresh
PR by Amara (QA) or Aisha (HR / doc-owner) to bring the §3.2 header
into alignment with the §3 table of `pre-cutover-acceptance-run-
order.md`.

### 5.2 Welle-6 KW-anchor — `KW-26` vs `KW-27` (two-canonical-views)

Two canonical-doc views describe the Welle-6 anchor differently:

* **Run-order view** (`docs/quality-gates/pre-cutover-acceptance-run-
  order.md` §3 table line 97): Welle-6 on `KW-27` (Cutover-Mittwoch
  2026-07-01 / Sign-off-Freitag 2026-07-03; Doppel-Welle-6+7 with
  Welle-7 on the same KW).
* **Acceptance-criteria view** (`docs/quality-gates/kw-24-welle-1-7-
  acceptance-criteria.md`, codified in `tooling/ci/aggregate_kw_24_
  welle_acceptance.py::WELLE_ANCHORS[6]`): Welle-6 on `("KW-26", "Fr",
  "cross_substrate_parity")` — the cross-substrate-parity acceptance-
  gate sits on KW-26 Fr in this view.

The Tag-74 PR scope:

* The engine-side helper-default `CANONICAL_KW_ANCHOR[6]` and the
  committed `state/welle-6.json` carry `KW-26` — matching the
  **acceptance-criteria view** (consistent with the Tag-74 Auftrag
  wording "Welle-6 (Cross-Substrate-Parity-Welle, KW-26 Fr per
  kanonisch)").
* The producer-substrate is kw-anchor-agnostic (§3 above), so the
  Welle-6 producer-method does not gate on the KW-anchor field; the
  Welle-6 producer-add-on lands independently of which view "wins".

This dual-view is the same pattern as the Welle-5 case (run-order
view: KW-26 Doppel-Welle-4+5 modul=lifecycle_state_machine;
acceptance-criteria view: KW-25 Fr modul=capability_token). The Tag-73
Welle-5 aggregator (`tooling/ci/aggregate_welle_5_integration.py`)
already documents the precedent: "Marathon-Rollback-Runbook wins for
Tag-73 canonical; KW-24-Acceptance view surfaced as parallel-substrate-
evidence". The Tag-74 PR follows the same precedent for Welle-6 by
**not** unilaterally reconciling the two views and instead surfacing
the dual-view for a future explicit reconciliation PR.

The Welle-4 + Welle-5 alignment in Tag-74 is the case where the two
views **agreed** (both point to KW-26 for W4+W5) and the engine-side
helper-default was the outlier (drifted to KW-25). That made the W5-
anchor-fix unambiguous; the W6 dual-view is structurally different
because the two canonical-doc views disagree, and the producer-domain
owner (Selin) is not authorised to choose between them.

### 5.3 Producer-substrate docstring strings

Several producer-substrate docstrings (e.g. the
`handle_welle_5_signoff_event` docstring's `KW-25 Fr 2026-06-19`
inherited string from Tag-73) carry historical KW-anchor references.
These are non-load-bearing (no test pins on the docstring string) and
can be cleaned up in a doc-only follow-up PR. The Tag-74 PR refreshes
the module-level docstring of `welle_state_producer.py` to the post-
Tag-74 KW-26 anchor for Welle-5; per-method docstrings remain on the
backlog.

## 6. Audit-trail anchor

This reconciliation note is the engine-side audit-trail anchor for the
W4+W5 KW-anchor alignment. Henrik (Internal Audit) Zone-N quarterly
review will sample this doc + the `state/welle-{4,5}.json` diff against
the §3 table line-items.

— Selin (Tag-74, 2026-05-19, Continuous-Mode)
