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

# CEO test fixture (v5 — BODY EDIT, mutation class M-3)

This fixture has the SAME front-matter as v1 (byte-for-byte) but a
completely different body. The persona_hash MUST be identical to v1.

This is the audit-pin pillar that proves the in-hash / out-of-hash
boundary is enforced by the canonical-subset extractor.

Additional narrative paragraphs to make the body length divergence
obvious to a casual reader. Lorem ipsum filler omitted intentionally
in favour of operational text — but the point stands: none of this
text reaches the JCS input.
