# SPDX-License-Identifier: Apache-2.0
"""Frame-builder helper for Wirelang Layer-1 frames.

This module exposes a single-call constructor (:func:`build_layer_1_frame`)
and a fluent-style :class:`FrameBuilder` for assembling Wirelang frames
in tests and integration glue. The output is a plain ``dict`` matching
``wirelang/schemas/layer-1-wire.json``.

The builder is intentionally permissive: it does not run the
JSON-Schema validator. Callers that want validation can pass the
output through ``jsonschema.Draft202012Validator``; the default
expectation is that producers run the validator at the wire boundary
(NATS publish, HTTP egress) rather than at every internal call site.

Naming conventions follow Brand-Guide §9: the builder accepts
role-strings and DID URIs only. There is no path that surfaces a
clear name into the frame.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


WIRELANG_DEFAULT_VERSION = "0.2.0"
"""Default Wirelang spec version stamped on built frames.

Producers MAY override via ``wirelangversion`` argument; both v0.1.0
and v0.2.0 frames are valid against a v0.2 verifier per
``specs/wirelang-spec-v0-2.md`` §1.1.
"""

DEFAULT_DATACONTENTTYPE = "application/wirelang+json"
DEFAULT_VOCAB_ID = "wakir.core"
DEFAULT_VOCAB_VERSION = "0.1.0"
DEFAULT_VOCAB_ANCHOR_URL = (
    f"https://wakir.dev/wirelang/vocab/{DEFAULT_VOCAB_VERSION}.json"
)


def capability_token_hash_ref(token_bytes: bytes) -> str:
    """Compute a Layer-1 ``caprefs`` entry from raw token bytes.

    Returns ``sha256:<64-hex>`` matching the Layer-1 schema pattern.
    """
    digest = hashlib.sha256(token_bytes).hexdigest()
    return f"sha256:{digest}"


def _layer_2_envelope(
    *,
    schema_id: str,
    schema_version: str,
    valid_after: Optional[str],
    valid_until: Optional[str],
    vocabulary_id: str,
    vocabulary_version: str,
    vocabulary_anchor_url: str,
    frame_class: str,
) -> Dict[str, Any]:
    return {
        "frame_class": frame_class,
        "schema_id": schema_id,
        "schema_version": schema_version,
        "validafter": valid_after,
        "validuntil": valid_until,
        "vocabulary": {
            "id": vocabulary_id,
            "version": vocabulary_version,
            "anchor_url": vocabulary_anchor_url,
        },
    }


def _classify_frame(event_type: str) -> str:
    """Return ``meta-event`` for ``wakir.meta.*`` types, else ``domain-event``."""
    return "meta-event" if event_type.startswith("wakir.meta.") else "domain-event"


def build_layer_1_frame(
    *,
    persona_did: str,
    event_type: str,
    schema_id: Optional[str] = None,
    schema_version: str = "0.1.0",
    actorrole: str,
    event_id: str,
    payload: Optional[Dict[str, Any]] = None,
    capability_token_hashes: Optional[List[str]] = None,
    time: Optional[str] = None,
    wirelangversion: str = WIRELANG_DEFAULT_VERSION,
    agentid: Optional[str] = None,
    personapin: Optional[str] = None,
    personahash: Optional[str] = None,
    attestationref: Optional[str] = None,
    imagedigest: Optional[str] = None,
    dataschemaref: Optional[str] = None,
    valid_after: Optional[str] = None,
    valid_until: Optional[str] = None,
    embed_layer_2_envelope: bool = True,
    extra_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Construct a Wirelang Layer-1 frame as a dict.

    Parameters
    ----------
    persona_did
        DID URI of the sending persona; goes into ``source``. MUST match
        the ``did:web:`` pattern enforced by the Layer-1 schema.
    event_type
        Reverse-DNS event type (e.g. ``wakir.treasury.read``).
    schema_id
        Schema-registry identifier. Defaults to ``event_type`` when
        omitted, which is the common Wakir convention.
    actorrole
        Pseudonymised role string (no clear names).
    event_id
        Event identifier; Wakir convention is UUIDv7.
    payload
        Arbitrary JSON-serialisable dict for Layer-2 ``data``. May be
        ``None`` to produce a frame with no payload (the schema permits
        a missing ``data`` slot).
    capability_token_hashes
        Optional list of pre-computed ``sha256:<hex>`` strings; consumed
        verbatim into ``caprefs``.
    time
        RFC 3339 UTC timestamp. Defaults to ``None`` (omits ``time``).
    embed_layer_2_envelope
        When True (default), wraps the user payload under
        ``data.wirelang_layer_2_envelope`` per the convention used by
        the example frames. Set False if the caller wants to embed an
        envelope shape themselves or skip it entirely.
    extra_data
        Free-form additional fields merged into the ``data`` slot
        alongside the user payload. Used by tests that need atypical
        Layer-2 shapes.

    Returns
    -------
    dict
        A dict that validates against ``schemas/layer-1-wire.json``
        when populated with valid arguments.
    """
    schema_id = schema_id or event_type
    frame: Dict[str, Any] = {
        "specversion": "1.0",
        "type": event_type,
        "source": persona_did,
        "id": event_id,
        "wirelangversion": wirelangversion,
        "schemaid": schema_id,
        "schemaversion": schema_version,
        "actorrole": actorrole,
        "datacontenttype": DEFAULT_DATACONTENTTYPE,
    }
    if time is not None:
        frame["time"] = time
    if agentid is not None:
        frame["agentid"] = agentid
    if personapin is not None:
        frame["personapin"] = personapin
    if personahash is not None:
        frame["personahash"] = personahash
    if attestationref is not None:
        frame["attestationref"] = attestationref
    if imagedigest is not None:
        frame["imagedigest"] = imagedigest
    if dataschemaref is not None:
        frame["dataschemaref"] = dataschemaref
    if capability_token_hashes:
        frame["caprefs"] = list(capability_token_hashes)

    data: Dict[str, Any] = {}
    if payload:
        data.update(payload)
    if extra_data:
        data.update(extra_data)
    if embed_layer_2_envelope:
        data["wirelang_layer_2_envelope"] = _layer_2_envelope(
            schema_id=schema_id,
            schema_version=schema_version,
            valid_after=valid_after,
            valid_until=valid_until,
            vocabulary_id=DEFAULT_VOCAB_ID,
            vocabulary_version=DEFAULT_VOCAB_VERSION,
            vocabulary_anchor_url=DEFAULT_VOCAB_ANCHOR_URL,
            frame_class=_classify_frame(event_type),
        )
    if data:
        frame["data"] = data
    return frame


@dataclass
class FrameBuilder:
    """Fluent-style builder around :func:`build_layer_1_frame`.

    Common Wakir defaults are pre-set; ``with_*`` methods customise
    individual attributes. Each ``with_*`` returns ``self`` for
    chaining; ``build()`` materialises the dict.
    """

    persona_did: str = "did:web:wakir.dev:treasury-agent"
    event_type: str = "wakir.treasury.read"
    schema_id: Optional[str] = None
    schema_version: str = "0.1.0"
    actorrole: str = "treasury-operator"
    event_id: str = "01HK4P8X3W2N5Q9V0R6T7S8YZA"
    payload: Dict[str, Any] = field(default_factory=dict)
    capability_token_hashes: List[str] = field(default_factory=list)
    time: Optional[str] = "2026-05-06T11:35:00Z"
    wirelangversion: str = WIRELANG_DEFAULT_VERSION
    agentid: Optional[str] = None

    def with_persona(self, did: str, *, actorrole: Optional[str] = None) -> "FrameBuilder":
        self.persona_did = did
        if actorrole is not None:
            self.actorrole = actorrole
        return self

    def with_event_type(self, event_type: str, *, schema_id: Optional[str] = None) -> "FrameBuilder":
        self.event_type = event_type
        if schema_id is not None:
            self.schema_id = schema_id
        return self

    def with_payload(self, payload: Dict[str, Any]) -> "FrameBuilder":
        self.payload = dict(payload)
        return self

    def with_capability(self, token_bytes: bytes) -> "FrameBuilder":
        self.capability_token_hashes.append(capability_token_hash_ref(token_bytes))
        return self

    def with_capability_hash(self, capref: str) -> "FrameBuilder":
        self.capability_token_hashes.append(capref)
        return self

    def with_event_id(self, event_id: str) -> "FrameBuilder":
        self.event_id = event_id
        return self

    def with_time(self, time: Optional[str]) -> "FrameBuilder":
        self.time = time
        return self

    def with_agentid(self, agentid: str) -> "FrameBuilder":
        self.agentid = agentid
        return self

    def build(self, *, embed_layer_2_envelope: bool = True) -> Dict[str, Any]:
        return build_layer_1_frame(
            persona_did=self.persona_did,
            event_type=self.event_type,
            schema_id=self.schema_id,
            schema_version=self.schema_version,
            actorrole=self.actorrole,
            event_id=self.event_id,
            payload=self.payload or None,
            capability_token_hashes=self.capability_token_hashes or None,
            time=self.time,
            wirelangversion=self.wirelangversion,
            agentid=self.agentid,
            embed_layer_2_envelope=embed_layer_2_envelope,
        )
