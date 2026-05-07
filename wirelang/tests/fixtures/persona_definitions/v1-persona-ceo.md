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
  authority:
    push_remote: true
    budget_cap_eur_per_month: 1000
    sub_delegation: true
  hierarchy:
    reports_to: aufsichtsrat
    escalation: aufsichtsrat
---

# CEO test fixture (v1)

Werdegang, Arbeitsstil, Stärken — narrative body, out-of-hash by design.
Edits below this line MUST NOT change persona_hash.
