# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic doc-audit tests for `docs/quality-gates/*`.

Each test-module in this package asserts that one quality-gate doc
remains internally consistent with the test-substrate it describes
(canonical layer-maps, anchor-files, per-layer test-counts in the
declared bounds). The tests are deliberately doc-side audits — they
do NOT re-execute the underlying contracts.
"""
