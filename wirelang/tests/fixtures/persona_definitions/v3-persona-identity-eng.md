---
name: identity-eng
description: "Identity-substrate role-string fixture (vector v3, cross-review zone L counterpart)."
tools:
  - Read
  - Glob
  - Bash
schema_version: persona-v1
identity_pinned:
  cross_review_zones:
    - zone: L
      partner: persona-eng
      trigger: persona-identity-doc
    - zone: G
      partner: wat-eng
      trigger: aip-document-bridge
  authority:
    push_remote: false
    budget_cap_eur_per_month: 10
    sub_delegation: false
  hierarchy:
    reports_to: cto
    escalation: cto
---

# Identity-engineering test fixture (v3)

Body content (Werdegang / Arbeitsstil): out-of-hash. Documentation
of Ed25519/secp256k1 key choices lives here.
