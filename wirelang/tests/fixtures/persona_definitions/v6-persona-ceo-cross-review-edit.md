---
name: ceo
description: "Chief executive role-string for the wakir org test fixture (vector v1)."
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
    - zone: B
      partner: hr
      trigger: persona-format-decision
  authority:
    push_remote: true
    budget_cap_eur_per_month: 1000
    sub_delegation: true
  hierarchy:
    reports_to: aufsichtsrat
    escalation: aufsichtsrat
---

# CEO test fixture (v6 — identity_pinned edit, mutation class M-2)

Same v1 baseline plus a second cross_review_zone entry. This is an
in-hash structured field tamper. persona_hash MUST drift from v1.
