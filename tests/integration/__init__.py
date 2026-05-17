# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Integration-test package.

Tests in this package are hermetic (no live network, no live NATS, no
container runtime) but exercise multi-process roundtrips across the
Python / Rust boundary.

The :mod:`tests.integration.test_bridge_audit_roundtrip_e2e` module
is the Phase-2 Doppelbetrieb-Bridge cross-language acceptance gate:
Python emits, Rust replays, both sides agree on the stream-hash.
"""
