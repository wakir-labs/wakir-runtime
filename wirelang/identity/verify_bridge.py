# SPDX-License-Identifier: Apache-2.0
"""Cross-persona verify-bridge: HTTPS-transport → AIP-doc verify.

This module is the Phase-1b Tag-9 bridge between the HTTPS transport
layer (Tag-8 :class:`~wirelang.identity.aip_https_backend.HTTPSDocumentTransport`),
the AIP-document signature helpers (:mod:`wirelang.identity.aip_signing`),
and the JCS / schema validation indirections introduced by Tag-9.

The bridge exposes a single public entry point::

    verify_from_transport(transport, doc_id, *, ...) -> VerifyResult

which packages "fetch + parse + schema-check + id-sanity + signature
+ JCS-hash" into one call. The result type is a frozen dataclass
(:class:`VerifyResult`) carrying either a successful verification or
a typed error reason (:class:`VerifyError`); the function deliberately
does *not* raise for business-level failures.

Design rationale
----------------

1. **Result-type, not exceptions.** Federation resolvers iterate over
   trust-anchor candidates and want a per-candidate boolean without
   try/except scaffolding. Tag-7 :class:`FederationResolver` and
   future WAT-side consumers compose more cleanly against
   ``if r.ok: ...`` than against ``except VerifyError: ...``.
2. **Single source of verification truth.** The bridge wires the
   resolver-indirection helpers (``_jcs_canonicalize`` from
   :mod:`aip_signing`, the structural validator from
   :mod:`_schema_pure`) so consumers do not duplicate JCS or
   schema-check code.
3. **Caller-pluggable schema lookup.** The schema lookup is a
   callable injection (``schema_loader``) so we do not bake a
   schema-registry dependency into the bridge. Tests inject an
   in-memory dict; production wires it to the schemas/ directory.

Out of scope
------------

- Real HTTPS calls (caller injects a transport instance; tests use
  a stub transport that implements the duck-typed protocol).
- ETag / Cache-Control honouring (the bridge calls ``transport.get``
  with no ``if_none_match``; cache-tier wrapping is the caller's
  responsibility, mirroring Tag-8's separation of concerns).
- Federation-document or DID-document verify (the bridge today
  targets AIP-documents; same shape extends trivially via a
  different ``schema_name``).

References
----------

- Tag-8 outbox spec (wirelang-eng workspace, 2026-05-06).
- Tag-9 outbox spec (wirelang-eng workspace, 2026-05-07).
- AIP draft: <https://datatracker.ietf.org/doc/html/draft-prakash-aip-00>
- RFC 8785 JCS: <https://datatracker.ietf.org/doc/html/rfc8785>
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional, Protocol

from . import _schema_pure
from .aip_signing import _jcs_canonicalize, verify_aip_signature


__all__ = [
    "DocumentTransport",
    "TransportResponse",
    "VerifyResult",
    "VerifyError",
    "verify_from_transport",
    "make_https_aip_verify_fn",
]


# ---------------------------------------------------------------------------
# Duck-typed transport protocol
# ---------------------------------------------------------------------------


class TransportResponse(Protocol):
    """Minimal response shape consumed by the bridge.

    Compatible with Tag-8 :class:`HTTPSDocumentResponse` (which
    exposes ``body`` and ``body_bytes``) and with simple test stubs.
    """

    body: dict
    body_bytes: bytes


class DocumentTransport(Protocol):
    """Minimal transport shape consumed by the bridge.

    Compatible with Tag-8 :class:`HTTPSDocumentTransport.get`. Test
    stubs implement ``get(uri)`` directly without subclassing.
    """

    def get(self, uri: str) -> TransportResponse: ...


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


VerifyErrorKind = Literal[
    "transport-failed",
    "json-parse-failed",
    "schema-failed",
    "id-mismatch",
    "signature-failed",
    "hash-mismatch",
]


@dataclass(frozen=True)
class VerifyError:
    """Typed business-level error from :func:`verify_from_transport`.

    Attributes:
        kind: the failure mode tag.
        message: human-readable description.
        cause: the underlying exception (transport / json / schema /
            signature error) or ``None`` for purely structural failures
            (e.g. ``id-mismatch``, ``hash-mismatch``).
    """

    kind: VerifyErrorKind
    message: str
    cause: Optional[Exception] = None


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of a :func:`verify_from_transport` call.

    Attributes:
        ok: True iff verification fully succeeded.
        document: the parsed body on success; ``None`` on failure.
        jcs_sha256: the recomputed JCS-hash of the body without
            ``document_signature`` on success; ``None`` on failure.
        source: the document URI / id; useful for provenance logs.
        error: the typed error on failure; ``None`` on success.
    """

    ok: bool
    document: Optional[dict]
    jcs_sha256: Optional[str]
    source: str
    error: Optional[VerifyError]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


SchemaLoader = Callable[[str], dict]
SignatureVerifier = Callable[[dict, dict, bytes], bool]


def verify_from_transport(
    transport: DocumentTransport,
    doc_id: str,
    *,
    expected_jcs_sha256: Optional[str] = None,
    schema_name: str = "aip-document/0.1.0",
    schema_loader: Optional[SchemaLoader] = None,
    pubkey_resolver: Optional[Callable[[dict], bytes]] = None,
    signature_verifier: SignatureVerifier = verify_aip_signature,
) -> VerifyResult:
    """Fetch ``doc_id`` via ``transport`` and run the AIP-verify pipeline.

    Pipeline (Tag-9 spec § 2.4):

    1. ``transport.get(doc_id)`` — any exception → ``transport-failed``.
    2. JSON parse via ``json.loads(resp.body_bytes)`` if the transport
       did not already parse, else use ``resp.body``. Failure →
       ``json-parse-failed``.
    3. Schema validation via the resolver indirection
       (``jsonschema`` if installed, else :mod:`_schema_pure`).
       Failure → ``schema-failed``.
    4. Sanity: ``body["id"] == doc_id``. Failure → ``id-mismatch``.
    5. Signature verification (Ed25519 over JCS-hash of body without
       ``document_signature``). Failure → ``signature-failed``.
    6. Optional pin check: if ``expected_jcs_sha256`` is provided,
       compare against the recomputed hash. Mismatch → ``hash-mismatch``.

    Args:
        transport: any object exposing ``get(uri) -> TransportResponse``.
        doc_id: the document identifier (also used as the transport URI).
        expected_jcs_sha256: optional pin against which the recomputed
            hash is compared. None disables the pin check.
        schema_name: the schema identifier; default
            ``"aip-document/0.1.0"``.
        schema_loader: callable mapping ``schema_name -> schema_dict``.
            Default loads from ``wirelang/schemas/aip-document.json``
            on the filesystem (lazy).
        pubkey_resolver: callable mapping the parsed body to the
            32-byte raw Ed25519 verification key. Default extracts
            the first ``public_keys`` entry. Tests inject a stub.
        signature_verifier: signature-verify callable; default is
            :func:`wirelang.identity.aip_signing.verify_aip_signature`.

    Returns:
        :class:`VerifyResult`.
    """
    # 1. Transport
    try:
        resp = transport.get(doc_id)
    except Exception as exc:  # transport may raise any exception
        return VerifyResult(
            ok=False,
            document=None,
            jcs_sha256=None,
            source=doc_id,
            error=VerifyError("transport-failed", str(exc), exc),
        )

    # 2. JSON parse — prefer the transport's already-parsed body if
    # present, fall back to body_bytes.
    body: dict
    body_attr = getattr(resp, "body", None)
    if isinstance(body_attr, dict):
        body = body_attr
    else:
        try:
            body_bytes = getattr(resp, "body_bytes")
        except AttributeError as exc:
            return VerifyResult(
                False, None, None, doc_id,
                VerifyError(
                    "json-parse-failed",
                    "transport response exposes neither parsed body nor body_bytes",
                    exc,
                ),
            )
        try:
            body = json.loads(body_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return VerifyResult(
                False, None, None, doc_id,
                VerifyError("json-parse-failed", str(exc), exc),
            )
        if not isinstance(body, dict):
            return VerifyResult(
                False, None, None, doc_id,
                VerifyError(
                    "json-parse-failed",
                    f"AIP body must be a JSON object; got {type(body).__name__}",
                    None,
                ),
            )

    # 3. Schema validation
    try:
        loader = schema_loader or _default_schema_loader
        schema = loader(schema_name)
        _resolver_schema_validate(body, schema)
    except _schema_pure.ValidationError as exc:
        return VerifyResult(
            False, None, None, doc_id,
            VerifyError("schema-failed", str(exc), exc),
        )
    except Exception as exc:
        # jsonschema's ValidationError is not _schema_pure.ValidationError;
        # any schema-level exception maps to schema-failed.
        if exc.__class__.__name__ == "ValidationError":
            return VerifyResult(
                False, None, None, doc_id,
                VerifyError("schema-failed", str(exc), exc),
            )
        raise  # programmer error -- let it propagate

    # 4. ID sanity
    if body.get("id") != doc_id:
        return VerifyResult(
            False, None, None, doc_id,
            VerifyError(
                "id-mismatch",
                f"body.id={body.get('id')!r} != doc_id={doc_id!r}",
                None,
            ),
        )

    # 5. Signature verify
    sig_block = body.get("document_signature")
    if not isinstance(sig_block, dict):
        return VerifyResult(
            False, None, None, doc_id,
            VerifyError(
                "signature-failed",
                "document_signature is missing or not an object",
                None,
            ),
        )
    try:
        resolver = pubkey_resolver or _default_pubkey_resolver
        pubkey = resolver(body)
    except Exception as exc:
        return VerifyResult(
            False, None, None, doc_id,
            VerifyError("signature-failed", f"pubkey resolution failed: {exc}", exc),
        )
    try:
        verified = signature_verifier(body, sig_block, pubkey)
    except (ValueError, TypeError) as exc:
        return VerifyResult(
            False, None, None, doc_id,
            VerifyError("signature-failed", str(exc), exc),
        )
    if not verified:
        return VerifyResult(
            False, None, None, doc_id,
            VerifyError(
                "signature-failed",
                "Ed25519 signature did not verify",
                None,
            ),
        )

    # 6. JCS hash recompute (and optional pin)
    body_minus_sig = copy.deepcopy(body)
    body_minus_sig.pop("document_signature", None)
    canonical = _jcs_canonicalize(body_minus_sig)
    actual_hash = hashlib.sha256(canonical).hexdigest()

    if expected_jcs_sha256 is not None and actual_hash != expected_jcs_sha256:
        return VerifyResult(
            False, None, None, doc_id,
            VerifyError(
                "hash-mismatch",
                f"actual={actual_hash}, expected={expected_jcs_sha256}",
                None,
            ),
        )

    return VerifyResult(
        ok=True,
        document=body,
        jcs_sha256=actual_hash,
        source=doc_id,
        error=None,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolver_schema_validate(instance: object, schema: dict) -> None:
    """Validate ``instance`` against ``schema``.

    Production path: ``jsonschema.validate``. Fallback path:
    :func:`_schema_pure.validate`. Mirrors the JCS resolver indirection
    in :mod:`aip_signing`.
    """
    try:
        import jsonschema as _jsonschema_lib
    except ImportError:
        _schema_pure.validate(instance, schema)
        return
    _jsonschema_lib.validate(instance=instance, schema=schema)


def _default_schema_loader(schema_name: str) -> dict:
    """Load a Wakir AIP-document schema from the on-disk schemas/ tree.

    Currently supports ``"aip-document/0.1.0"``; extend by adding a
    case here when new schemas are declared.
    """
    if schema_name == "aip-document/0.1.0":
        from importlib import resources

        schema_text = (
            resources.files("wirelang.schemas").joinpath("aip-document.json").read_text(
                encoding="utf-8"
            )
        )
        return json.loads(schema_text)
    raise KeyError(
        f"unknown schema_name {schema_name!r}; supply schema_loader= explicitly"
    )


def make_https_aip_verify_fn(
    *,
    schema_loader: Optional[SchemaLoader] = None,
    pubkey_resolver: Optional[Callable[[dict], bytes]] = None,
    signature_verifier: SignatureVerifier = verify_aip_signature,
    schema_name: str = "aip-document/0.1.0",
) -> Callable[[str, bytes, dict], dict]:
    """Build a ``verify_fn`` callable compatible with
    :class:`wirelang.identity.aip_https_backend.HTTPSAipResolver`.

    PS-7-Wiring (Tag-10): the Tag-8 :class:`HTTPSAipResolver` accepts
    a caller-supplied ``verify_fn`` of shape
    ``(uri, body_bytes, body) -> AIPDocumentLike``; this factory
    returns a closure that runs the full Tag-9 verify pipeline against
    the supplied (already-fetched) body.

    The closure raises (instead of returning a :class:`VerifyResult`)
    so it slots into the Tag-8 :class:`HTTPSAipResolver` exception-flow
    contract; failures surface as :class:`VerifyError`-tagged
    :class:`RuntimeError` exceptions whose ``args[0]`` is a
    :class:`VerifyError`. Callers needing the result-type API call
    :func:`verify_from_transport` directly.

    Args:
        schema_loader: schema lookup callable; defaults to the
            on-disk loader (``wirelang/schemas/aip-document.json``).
        pubkey_resolver: pubkey extraction callable; defaults to the
            "kid-match-or-first" resolver.
        signature_verifier: signature-verify callable.
        schema_name: schema identifier (default ``"aip-document/0.1.0"``).

    Returns:
        A callable suitable for :class:`HTTPSAipResolver(verify_fn=...)`.
    """

    class _PreFetchedTransport:
        """Inner adapter: pretends to ``get`` but returns the
        already-fetched body the caller hands in via the closure.
        """

        def __init__(self, body: dict, body_bytes: bytes) -> None:
            self._body = body
            self._body_bytes = body_bytes

        def get(self, uri: str):  # noqa: ARG002 -- uri is captured upstream
            return _FetchedResponse(body=self._body, body_bytes=self._body_bytes)

    @dataclass(frozen=True)
    class _FetchedResponse:
        body: dict
        body_bytes: bytes

    def _verify_fn(uri: str, body_bytes: bytes, body: dict) -> dict:
        transport = _PreFetchedTransport(body=body, body_bytes=body_bytes)
        result = verify_from_transport(
            transport,
            uri,
            schema_name=schema_name,
            schema_loader=schema_loader,
            pubkey_resolver=pubkey_resolver,
            signature_verifier=signature_verifier,
        )
        if not result.ok:
            assert result.error is not None
            raise RuntimeError(result.error)
        # Return the parsed body; downstream consumers wrap it into
        # an AIPDocumentLike via project_aip_document, but the
        # production verify_fn (Phase-1a Tag-21) returned just the
        # parsed body too.
        return result.document  # type: ignore[return-value]

    return _verify_fn


def _default_pubkey_resolver(body: dict) -> bytes:
    """Resolve the verification key from ``body["public_keys"][0].key_hex``.

    Phase-1b convention: the first ``public_keys`` entry is the
    AIP-signing key. A future enhancement matches the
    ``document_signature.kid`` against ``public_keys[*].kid``; for
    Tag-9 the simple "first entry" convention matches the existing
    Phase-1a generator.
    """
    pks = body.get("public_keys")
    if not isinstance(pks, list) or not pks:
        raise ValueError("body has no public_keys array")
    sig_block = body.get("document_signature") or {}
    target_kid = sig_block.get("kid") if isinstance(sig_block, dict) else None
    chosen: Optional[dict] = None
    if target_kid is not None:
        for entry in pks:
            if isinstance(entry, dict) and entry.get("kid") == target_kid:
                chosen = entry
                break
    if chosen is None:
        chosen = pks[0]
    if not isinstance(chosen, dict):
        raise ValueError("public_keys entry is not an object")
    key_hex = chosen.get("key_hex")
    if not isinstance(key_hex, str):
        raise ValueError("public_keys entry has no key_hex string")
    try:
        return bytes.fromhex(key_hex)
    except ValueError as exc:
        raise ValueError(f"public_keys entry key_hex is not valid hex: {exc}") from exc
