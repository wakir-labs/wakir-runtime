# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Phase-3c End-to-End Rollback-Drill SLA-Verifikations-Suite.

This package houses the ≤10-minute Rollback-SLA E2E verification
suite for the nine Phase-3c-Komponenten. Per ADR-0065 §Rollback-
Strategie and ADR-0066 §Rollback, every Phase-3c-Komponente must
demonstrate that an ENV-Flag-Switch from ``rust`` back to ``python``
completes inside the 10-minute SLA and emits a Backend-Decision-
Audit-Record for the rollback event.

See ``conftest.py`` for the shared fixture-set and
``docs/quality-gates/phase-3c-acceptance-criteria.md`` §12 for the
quality-gate contract this suite enforces.
"""
