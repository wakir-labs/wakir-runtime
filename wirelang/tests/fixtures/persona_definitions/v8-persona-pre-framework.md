---
name: pre-framework-agent
description: "Pre-framework persona fixture for self-migration vector (v8, schema persona-v0-ish — flagged as unsupported)."
tools:
  - Read
schema_version: persona-v0
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

# Pre-framework test fixture (v8 — self-migration source)

This fixture intentionally declares schema_version=persona-v0. The
V-907 hash function must REJECT it with PersonaSchemaUnsupportedError;
the self-migration converter (ADR-0036) is responsible for upgrading
v0 sources before they can be hashed.
