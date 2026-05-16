# SPDX-License-Identifier: Apache-2.0
"""Wakir Wirelang schema package.

The package exposes JSON schema files via ``importlib.resources`` for
verifier modules; in particular, :mod:`wirelang.identity.verify_bridge`
loads ``aip-document.json`` through this package.

Protocol-layer consolidation (ADR-0062 Cut-2, 2026-05-16)
---------------------------------------------------------
This Apache-2.0 package — including all JSON schemas and the
``entry_signing`` / ``capability_policy_*`` / ``publisher_cli`` /
``registered_by_capability`` / ``registry_nats_kv_backend`` /
``replication`` Python adapter modules — is also published as
``wakir_protocol.schemas`` under the standalone
``wakir-labs/wakir-protocol`` repository. The upstream copy carries
the JSON-Schema SPDX refactor (``x-spdx-license-identifier``
top-level property instead of ``description``-field string, external
audit recommendation #6).

External adopters should depend on ``wakir-protocol`` and import
from ``wakir_protocol.schemas`` directly.
"""
