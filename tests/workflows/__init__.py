# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic workflow-structure tests.

Tests in this package parse `.github/workflows/*.yml` on disk and
assert structural invariants (permission scopes, step ordering,
trigger surface). They do not exec any workflow steps and do not
require network access — they run inside the claude-dev sandbox.
"""
