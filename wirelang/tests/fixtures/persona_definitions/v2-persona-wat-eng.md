---
name: wat-eng
description: "WAT-engineering role-string fixture (vector v2, cross-review zone K counterpart)."
tools:
  - Read
  - Glob
  - Bash
  - Edit
schema_version: persona-v1
identity_pinned:
  cross_review_zones:
    - zone: K
      partner: persona-eng
      trigger: v-907-impl
    - zone: G
      partner: identity-eng
      trigger: capability-token-bridge
  authority:
    push_remote: false
    budget_cap_eur_per_month: 10
    sub_delegation: false
  hierarchy:
    reports_to: cto
    escalation: cto
---

# WAT-engineering test fixture (v2)

Body section: free narrative, out-of-hash. Frame-projection details
live here as docs but are not part of the persona-hash.
