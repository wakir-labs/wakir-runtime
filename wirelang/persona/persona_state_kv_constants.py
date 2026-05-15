# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# This file is part of the Wakir Persona-Engine module. Licensed
# under the Business Source License 1.1; see ../LICENSE-BSL.md
# (the wirelang-package canonical header). Change Date: four (4)
# years after first publication; Change License: Apache 2.0.
"""Constants-only shim for the persona-state NATS-KV bucket family
(Sprint-Pengine-7 Tag-5 OI-PILOT-2 + Reza-Cross-Review Zone-B B-5).

This module is the **crypto-free** import surface for the per-org-
per-persona NATS-JetStream KV bucket family that
``wirelang.persona.persona_state_kv`` defines. The provisioner
driver ``bin/nats_kv_bucket_provision.py`` imports the bucket-
family constants from this module **first**, falling back to the
full ``wirelang.persona.persona_state_kv`` only when this shim is
absent (back-compat for non-bundle deployments).

Why a separate shim
-------------------

The full ``wirelang.persona.persona_state_kv`` module is a thin
wrapper that itself imports only ``re`` and ``typing`` at top level.
But importing **any** module under ``wirelang.persona.*`` triggers
``wirelang.persona.__init__`` which, prior to the Tag-5 PEP-562
disentanglement (see ``wirelang/persona/__init__.py`` lazy block),
eagerly imported ``persona_hash`` → ``rfc8785``.

On the production ``wakir-provisioner:0.1.x`` container image
(post-ADR-0059 BSL-1.1 wheel set: ``nats-py`` + ``cryptography``,
**no** ``rfc8785``) that eager import chain raised ``ImportError``
and the provisioner driver's family-probe try-chain caught it,
silently dropping the persona-state family from
``BUCKET_FAMILIES``. The ``--persona-state-pair`` flag then became
a silent no-op on the pilot VM (Tag-4 Bug-6 pattern, recurrence).

The constants-only shim restores byte-equal substrate semantics
**without** triggering any persona-engine-side crypto-bearing
import chain. Tag-5 paired-update on the ``__init__`` side
(PEP-562 lazy block) closes the residual issue that even
``from wirelang.persona.persona_state_kv_constants import X`` would
otherwise trigger ``wirelang.persona.__init__`` eager imports;
together the two changes guarantee a clean import on the
provisioner image regardless of which surface the driver imports.

Source-of-truth contract
------------------------

Every constant in this module is **byte-identical** to its
counterpart in ``wirelang.persona.persona_state_kv``. A
regression test
(``wirelang/tests/test_persona_state_kv_constants_parity.py``)
asserts byte-equality between the two modules so a drift in one
direction surfaces immediately. This module does NOT import the
full module to enforce equality at import time; the parity test
runs in an environment where the full module IS importable
(rfc8785 present).

Public surface
--------------

The driver-required surface is intentionally minimal:

- :data:`BUCKET_NAME_PREFIX`
- :data:`BUCKET_CONFIG`
- :func:`bucket_name_for_org` (the combined-token shim required by
  the per-org-family driver shape).

Identifier-validation helpers, key-derivation helpers, schema-URI
constants, and the inverse-direction parser are **not** part of
this shim. The provisioner driver needs only the three names
above; downstream consumers that need the richer surface
(lifecycle event keys, recovery-audit keys, schema URIs) import
from ``wirelang.persona.persona_state_kv`` directly and accept the
crypto-bearing transitive dependency.

References
----------

- Reza-Cross-Review Zone-B B-5 (Sprint-Pengine-7 Tag-5):
  ``https://github.com/wakir-labs/wakir-runtime/pull/61``.
- Tag-4 Bug-6 lazy-crypto-import pattern:
  ``wirelang/identity/__init__.py`` (PEP-562 ``__getattr__``).
- Sprint-9 Tag-1 provisioner driver:
  ``bin/nats_kv_bucket_provision.py`` (multi-family registry
  consumer).
- ADR-0059 BSL-1.1 wakir-provisioner image wheel-set.
"""

from __future__ import annotations

import re
from typing import Any, Mapping


# ---------------------------------------------------------------------------
# Bucket identity (byte-equal to ``wirelang.persona.persona_state_kv``)
# ---------------------------------------------------------------------------


#: Bucket name prefix; the full bucket name is
#: ``BUCKET_NAME_PREFIX + "<org_id>-<persona_id>"``.
BUCKET_NAME_PREFIX = "wakir-persona-state-"


#: Bucket configuration. Drift-policy: any deviation between the
#: live cluster and these values is reported as drift, never auto-
#: corrected (same contract as the marker-stack / sequence-ledger
#: families).
BUCKET_CONFIG: Mapping[str, Any] = {
    "description": "Wakir persona-engine state log (Phase-2 Pengine-7)",
    "history": 1,
    "ttl_seconds": 0,
    "max_value_size": 65_536,
    "storage": "file",
    "replicas": 1,
}


# ---------------------------------------------------------------------------
# Identifier validation (re-declared locally, byte-equal pattern)
# ---------------------------------------------------------------------------


#: Permitted-character regex for the combined ``<org_id>-<persona_id>``
#: token. URI-safe ASCII subset, no slashes, no whitespace. Mirrors
#: ``wirelang.persona.persona_state_kv._IDENT_RE`` byte-precisely so
#: the validation surface is identical regardless of which import
#: shape the caller used.
_IDENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]*$")


def _validate_identifier(name: str, kind: str) -> None:
    if not isinstance(name, str) or not name:
        raise ValueError(f"{kind} must be a non-empty string, got {name!r}")
    if not _IDENT_RE.match(name):
        raise ValueError(
            f"{kind} {name!r} does not match permitted-character "
            f"pattern {_IDENT_RE.pattern!r}"
        )


def bucket_name_for_org(combined: str) -> str:
    """Driver-compatible shim: accept a combined ``<org_id>-<persona_id>``
    token and return the bucket name.

    Byte-equal to
    ``wirelang.persona.persona_state_kv.bucket_name_for_org``. The
    Sprint-9 Tag-1 provisioner driver's ``BucketFamily`` surface
    treats each family as keyed by ONE identifier (``org_id``); for
    the persona-state family the driver-side identifier is the
    combined token ``"<org_id>-<persona_id>"``. This shim lets the
    family register with the driver's existing per-org idiom
    without splitting the driver's iteration shape.

    Validation: the combined token must satisfy ``_IDENT_RE`` and
    contain at least one ``-``. The ``-`` split is **not** validated
    here against the permitted-character regex for the two halves;
    callers that require the strict pair-shape MUST use
    ``wirelang.persona.persona_state_kv.bucket_name_for_pair``
    directly (and accept the crypto-bearing transitive import).
    """
    _validate_identifier(combined, "persona_state_id")
    if "-" not in combined:
        raise ValueError(
            f"persona_state_id must contain a '-' separating "
            f"<org_id> and <persona_id>, got {combined!r}"
        )
    return f"{BUCKET_NAME_PREFIX}{combined}"


__all__ = [
    "BUCKET_CONFIG",
    "BUCKET_NAME_PREFIX",
    "bucket_name_for_org",
]
