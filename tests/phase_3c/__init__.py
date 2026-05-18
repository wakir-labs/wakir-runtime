# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for Phase-3c per-Welle cutover-smoke artefacts.

Each ``test_welle_<N>_<focus>_smoke.py`` covers the end-to-end
cutover-smoke script for that Welle's focus component, mirroring the
:mod:`tests.scripts` dry-run / observability-baseline siblings but
scoped to the ADR-0065 §Verifikations-Plan strict-asserts surface.
"""
