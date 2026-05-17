---
name: pre-framework-agent
description: "Pre-framework persona fixture for self-migration vector (v8, schema persona-v0-ish — flagged as unsupported)."
tools:
  - Read
schema_version: persona-v1
identity_pinned:
  cross_review_zones: []
  authority:
    push_remote: false
    budget_cap_eur_per_month: 0
    sub_delegation: false
  hierarchy:
    reports_to: cto
    escalation: cto
---

# Framework-native test fixture (v9 — self-migration target)

Same logical persona as v8 but schema_version upgraded to persona-v1.
This is the ADR-0036 converter target shape: same content, valid
schema. persona_hash MUST be computable AND distinct from any v8
hash (since v8 is rejected, "distinct" reduces to "v9 hashes
without raising").
