<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# ADR Cross-Repo Migration Pattern

**Status:** Operations runbook, Tomás (Dev-Engineering) Tag-66.
**Audience:** Engineering personas drafting ADRs in `wakir-runtime`,
plus Mira-Hand performing the official migration into the corporate
`AI-Corp/decisions/` register.
**Anchors:** ADR-0070 (template-in-`wakir-runtime` example), ADR-0001
delegation matrix, `feedback_repo_topologie_vollstaendig.md`.

## 1. Why this document exists

ADR-0070 (the AR-Hand Cutover-Day-Morgen Override-Flag pattern that
Tag-65 implemented) was drafted in
`wakir-runtime/docs/decisions/` while the **official** ADR register
lives at `/var/home/fred/AI-Corp/decisions/`. This split is
deliberate and recurring -- engineering personas surface
ADR-shaped artefacts inside the substance repo where the code
lives, then Mira-Hand migrates them to the corporate decision
register where the Aufsichtsrat reviews and approves them.

The pattern has been repeated enough times (ADR-0034, ADR-0058,
ADR-0061, ADR-0065, ADR-0066, ADR-0070) that the next persona
running into it deserves a written runbook instead of having to
re-derive it from prior PR discussions.

The five sections below codify the pattern: where to file the
template, what the template MUST contain, how the corporate
register cross-references it, who does the migration, and how
cross-repo references survive the migration.

## 2. Where the ADR template lives in `wakir-runtime`

ADR templates that arise inside the runtime repo are placed at:

```
wakir-runtime/docs/decisions/<slug>.md
```

The `<slug>` is descriptive (e.g.
`ar-hand-cutover-override-flag.md`), NOT numbered. The numbering
belongs to the corporate register; assigning a number in the
runtime repo would create a desynchronisation risk if multiple
templates land before the next Mira-Hand migration cycle.

**Filing checklist** (template author):

* Use a descriptive slug, lowercase, hyphenated.
* Open with `**Status:** OPEN -- pending Mira-Hand migration to
  AI-Corp/decisions/NNNN-*.md`. The OPEN status signals the
  template is not yet authoritative.
* Carry SPDX headers (`Apache-2.0` for runbook-style templates,
  `BUSL-1.1` for templates that ship inside the federation /
  persona-engine subtrees per ADR-0034 / ADR-0059).
* Link any related code under the runtime repo with **relative**
  paths from the template file (e.g.
  `../../tooling/ci/ar_hand_cutover_override_listener.py`).
  Cross-repo references (e.g. links into `AI-Corp/decisions/`)
  remain text-only -- do **not** hard-code absolute paths into
  the Aufsichtsrat workspace, since adopters cloning the
  open-source repo do not have that workspace.

The current population of `wakir-runtime/docs/decisions/` is the
canonical example of the pattern in steady state:

* `ar-hand-cutover-override-flag.md` -- Tag-65 Tomás (this Tag-66
  doc was authored to accompany it).
* `adr-errata-tag-55-path-typo-fixes.md` -- Errata addendum for
  ADR-0055 (Reza).
* `topology-bilateral-federation.md` -- Bug-39 federation
  topology decision (Kai).
* `phase-3-nodeattestor-migration.md` -- Reza Phase-3 migration
  template.
* `rust-rewrite-crate-wahlen.md` -- Selin rust-rewrite library
  selection template.

All of the above are templates. None of them are the
authoritative ADR. The authoritative ADR is whatever
`/var/home/fred/AI-Corp/decisions/NNNN-*.md` Mira-Hand creates
from the template.

## 3. Template must-haves before Mira-Hand picks it up

A template is migration-ready when the author has:

1. **Status banner** -- the literal string `Status: OPEN --
   pending Mira-Hand migration` at the top, so a `grep -r
   "OPEN -- pending Mira-Hand"` lists the queue.
2. **Substance summary** -- one paragraph that states the
   decision and the rationale in a form that survives being
   lifted into the corporate register without further editing.
3. **Code anchors** -- explicit paths to the runtime files that
   implement (or will implement) the decision. Mira-Hand uses
   these to verify the substance has actually shipped before
   the corporate ADR moves out of OPEN status.
4. **Cross-references** -- list of *related* corporate ADRs by
   number (e.g. "extends ADR-0066 §Welle-Sequenz"). The
   migration step will reverse this and add a "see also" pointer
   from the related corporate ADRs back to the new ADR's number
   once assigned.
5. **No claim of authority** -- never write phrases like
   "ADR-0070 mandates X". Use "the proposed override flag" or
   "this template". The decision is not authoritative until
   Mira-Hand and the Aufsichtsrat have signed off.

If any of the five items are missing, Mira-Hand returns the
template to the author rather than migrating it.

## 4. Migration ownership and forbidden actions

Migration into `/var/home/fred/AI-Corp/decisions/NNNN-*.md` is
**Mira-Hand only**. Engineering personas -- including the
Matrix-Lead -- do not write into the AI-Corp `decisions/` tree.
This is a hard boundary from ADR-0001 (delegation matrix) and
from the recurring `feedback_kein_mikro_management.md` direction.

Forbidden actions for engineering personas:

* Writing to `/var/home/fred/AI-Corp/decisions/`.
* Assigning an ADR number to a template (numbering is Mira-Hand
  prerogative, since she also reserves the next free slot in the
  register).
* Editing the corporate ADR after migration. Errata go back into
  `wakir-runtime/docs/decisions/` as a new
  `adr-errata-<slug>.md` template, and Mira-Hand re-migrates.
* Linking from runtime code into
  `/var/home/fred/AI-Corp/decisions/`. Use the corporate ADR
  *number* as a text reference (e.g. "see ADR-0070"); do not
  embed a clickable link into the corporate workspace path.

Permitted engineering-persona actions:

* Drafting the template inside `wakir-runtime/docs/decisions/`.
* Updating the template in response to review feedback.
* Linking *to* the runtime template from runtime code (relative
  paths, see §2).
* Adding a `// ADR-NNNN` comment in code once Mira-Hand has
  migrated the template and assigned the number.

## 5. Cross-repo reference hygiene after migration

After Mira-Hand has migrated a template into the corporate
register, the runtime template stays in place as a
**code-adjacent pointer**. Concretely, after migration:

* The runtime template's `Status:` banner flips from
  `OPEN -- pending Mira-Hand migration` to
  `MIGRATED -- canonical ADR is AI-Corp/decisions/NNNN-<slug>.md`.
* A one-line `**Canonical:** ADR-NNNN` reference is added near
  the top of the runtime template. The Aufsichtsrat-approved
  text lives in the corporate register; the runtime template
  retains its substance summary as developer-facing context.
* Runtime code that references the decision uses the ADR
  number (`# ADR-0070`) in comments or docstrings, NOT the
  template's slug. This keeps the source-of-truth identifier
  stable even if the template slug is renamed for clarity.
* Open-source adopters cloning `wakir-runtime` will see the
  runtime template AND the SPDX-compliant pointer to the
  corporate ADR number. The corporate ADR text itself is not
  redistributed because it is internal Aufsichtsrat
  documentation; adopters who need the rationale are pointed at
  the runtime template, which carries the substance summary in
  a form intentionally drafted to be redistributable.

When a related ADR is later migrated (e.g. ADR-0070 references
ADR-0066), the cross-reference works because *both* registers
agree on the number. The runtime template can carry
`See also: ADR-0066 §Welle-Sequenz` because the number resolves
in either context.

This pattern is observed -- not enforced by CI today. A
follow-up Tag-N could add a lint that scans
`wakir-runtime/docs/decisions/*.md` for the `Status:` banner
and flags templates that have been OPEN for more than 30 days,
but that gate is operator-hand for now (see
`feedback_branch_protection_check_names.md` precedent for not
gating governance-flow on green-checks).

---

*Author: Tomás Reinhart (Dev-Engineering / Matrix-Lead). Tag-66.*
