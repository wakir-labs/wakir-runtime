# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Part of the Wakir Audit Trail (WAT) module. Licensed under
# Business Source License 1.1; see ../LICENSE-BSL.md.

"""WAT-side identity layer — anchor-kid reference + resolver bridge.

This package is the WAT-side parallel to the Identity-Substrate
``kid``-resolver (``wirelang.identity.kid_resolver``, Phase-2 Sprint-4
Tag-3, Identity-Substrate-engineering owner). It carries the
**WAT-domain reference shape** that
binds a hour-manifest to the AIP-document key that authorised the
anchor, and a thin resolver bridge that re-uses the canonical
Identity-Substrate resolver under the ``purpose == "wat-anchor"``
filter.

Cross-Review-Zone-1 alignment (DRY-consistent with Identity-Substrate-Sprint-4-Tag-3):

- The canonical resolver lives in ``wirelang.identity.kid_resolver``.
  This package does NOT re-implement the resolution algorithm; the
  6-step filter (mapping-shape, kid-found, single-match, alg-Ed25519,
  key_hex-shape, validity-window) is delegated.
- This package adds the WAT-domain ``purpose == "wat-anchor"`` filter
  via the existing ``require_purpose`` parameter of ``resolve_kid``.
  The ``"wat-anchor"`` purpose value is enumerated in
  ``wirelang/schemas/aip-document.json`` ``public_keys[].purpose`` —
  the schema is the byte-source of the value.
- Errors from the canonical resolver are surfaced as
  :class:`WatAnchorKidError` so WAT-domain callers (manifest
  verifier, aggregator, archive walker) do not have to depend on
  ``wirelang.identity.kid_resolver`` exception types directly.

References:

- Identity-Substrate-Sprint-4-Tag-3 kid-resolver spec §5.9 (operational contract):
  ``wirelang/identity/kid_resolver.py`` module docstring.
- Z-1-K-Sprint-4-1 (kid-Resolver-Shape) — closed by Identity-Substrate-Sprint-4-Tag-3.
- Z-1-K-Sprint-4-3 (two-curve-stack reinforced) — WAT-side anchor
  consumes Ed25519 only, inherited from canonical resolver.
- AIP-document schema purpose-enum:
  ``wirelang/schemas/aip-document.json`` §public_keys.purpose.

This package is intentionally minimal in Sprint-4 Tag-5: it pins the
WAT-side reference shape + bridge contract. Manifest-level wire-up
(adding an ``anchor_kid`` optional field to ``wat-manifest-v2.json``
and a verifier-side resolver call) is a future slot — it requires
Cross-Review-Zone-1 coordination with Identity-Substrate-engineering
on the canonical reference
shape inside the AIP-document schema and is not in scope here.
"""

from wat.identity.anchor_kid import (
    PURPOSE_WAT_ANCHOR,
    ResolvedAnchorKey,
    WatAnchorKidError,
    WatAnchorKidRef,
    is_kid_resolver_available,
    resolve_wat_anchor_kid,
    validate_anchor_kid_ref_shape,
)

__all__ = [
    "PURPOSE_WAT_ANCHOR",
    "ResolvedAnchorKey",
    "WatAnchorKidError",
    "WatAnchorKidRef",
    "is_kid_resolver_available",
    "resolve_wat_anchor_kid",
    "validate_anchor_kid_ref_shape",
]
