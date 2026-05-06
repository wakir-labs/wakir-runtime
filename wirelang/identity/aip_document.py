# SPDX-License-Identifier: Apache-2.0
"""AIP-document generator with the Wakir ``biscuit_root_pubkey`` extension.

Builds AIP documents that conform to ``draft-prakash-aip-00`` section 2.3
(required fields ``aip``, ``id``, ``public_keys``, ``name``,
``delegation``, ``protocols``, ``document_signature``, ``expires``) and
adds the Wakir ``biscuit_root_pubkey`` extension that points at the
Ed25519 key used to verify Biscuit authority blocks issued under this
identity.

Validation: the produced document validates against
``wirelang/schemas/aip-document.json`` shipped in this repository.

Document signatures are NOT produced here. Signing requires the
persona's Ed25519 master private key and JCS canonicalisation of the
document body, which lives in a higher-level orchestration layer (and
the signing keys never reach this module). Callers MUST replace the
placeholder ``document_signature`` before publishing the document.
"""

from __future__ import annotations

from datetime import datetime, timezone


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_aip_document(
    persona_id: str,
    ed25519_root_pub: bytes,
    did_uri: str,
    *,
    name: str | None = None,
    aip_id: str | None = None,
    valid_after: str | None = None,
    valid_until: str | None = None,
    expires: str | None = None,
    delegation_mode: str = "chained",
    protocols: tuple[str, ...] = ("wirelang/0.1",),
) -> dict:
    """Build an AIP document for a Wakir persona.

    Args:
        persona_id: bare persona role-string (e.g. ``"treasury-issuer"``).
            Per Wakir Brand-Guide §9 this is always a role-string, never
            a clear personal name. Used to derive the default ``name``
            and the ``aip:web`` identifier when not supplied.
        ed25519_root_pub: 32-byte raw Ed25519 public key. Becomes the
            ``biscuit_root_pubkey`` extension *and* the
            ``public_keys[0]`` entry with ``purpose="biscuit-root"``.
        did_uri: the persona's ``did:web`` identifier. Stored in
            ``verification_methods[0].controller`` to bind the AIP
            document to the DID document.
        name: optional human-readable agent name. Defaults to
            ``persona_id``.
        aip_id: optional AIP identifier. Defaults to
            ``aip:web:wakir.dev/personas/<persona_id>`` per AIP draft
            section 2.2.
        valid_after / valid_until: optional validity window for the
            ``public_keys`` entry. Defaults: ``valid_after=now``,
            ``valid_until=None``.
        expires: optional document expiration timestamp. Defaults to
            one year after ``valid_after``.
        delegation_mode: ``"compact"``, ``"chained"`` or ``"both"``
            (AIP draft section 2.3). Defaults to ``"chained"`` because
            Wakir Phase-1a issues Biscuit chained tokens.
        protocols: protocol bindings advertised by this identity.
            Defaults to ``("wirelang/0.1",)``.

    Returns:
        A dict that validates against ``wirelang/schemas/aip-document.json``
        *modulo* the ``document_signature`` field, which the caller must
        compute and attach. A placeholder ``document_signature`` is
        included so the document layout is well-formed; the placeholder
        signature is the all-zero Ed25519 signature and MUST be replaced
        before publication.

    Raises:
        ValueError: on key-length mismatch or invalid arguments.
    """
    if len(ed25519_root_pub) != 32:
        raise ValueError(
            "ed25519_root_pub must be a 32-byte raw key; "
            f"got {len(ed25519_root_pub)} bytes"
        )
    if delegation_mode not in {"compact", "chained", "both"}:
        raise ValueError(
            "delegation_mode must be one of compact|chained|both"
        )
    if "/" in persona_id or ":" in persona_id:
        raise ValueError(
            "persona_id must be a bare role-string (no slashes, no colons)"
        )

    now = _utc_now_iso()
    if valid_after is None:
        valid_after = now
    if expires is None:
        # Document expires in 365 days unless the caller picks a date.
        try:
            base = datetime.strptime(valid_after, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            base = datetime.now(timezone.utc)
        expires_dt = base.replace(year=base.year + 1)
        expires = expires_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    if aip_id is None:
        aip_id = f"aip:web:wakir.dev/personas/{persona_id}"

    document: dict = {
        "aip": "1.0",
        "id": aip_id,
        "name": name or persona_id,
        "public_keys": [
            {
                "kid": "biscuit-root-1",
                "alg": "Ed25519",
                "key_hex": ed25519_root_pub.hex(),
                "validafter": valid_after,
                "validuntil": valid_until,
                "purpose": "biscuit-root",
            }
        ],
        "delegation": {"mode": delegation_mode},
        "protocols": list(protocols),
        "expires": expires,
        "document_signature": {
            "alg": "Ed25519",
            "kid": "biscuit-root-1",
            "signature": "00" * 64,  # placeholder; caller MUST replace.
        },
        "verification_methods": [
            {
                "id": f"{did_uri}#keys-ed25519-1",
                "type": "Ed25519VerificationKey2020",
                "controller": did_uri,
                "publicKeyHex": ed25519_root_pub.hex(),
            }
        ],
        "biscuit_root_pubkey": ed25519_root_pub.hex(),
    }
    return document
