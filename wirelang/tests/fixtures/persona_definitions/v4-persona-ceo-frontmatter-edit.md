---
name: ceo
description: "Chief executive role-string for the wakir org test fixture (vector v4: description edited)."
tools:
  - Read
  - Glob
  - Bash
schema_version: persona-v1
identity_pinned:
  cross_review_zones:
    - zone: A
      partner: aufsichtsrat
      trigger: strategic-decision
  authority:
    push_remote: true
    budget_cap_eur_per_month: 1000
    sub_delegation: true
  hierarchy:
    reports_to: aufsichtsrat
    escalation: aufsichtsrat
---

# CEO test fixture (v4 — frontmatter edit, mutation class M-1)

Same body as v1 but description in front-matter changed → hash MUST drift.
