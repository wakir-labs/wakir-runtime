# SPDX-License-Identifier: Apache-2.0
"""Pure-Python RFC 8785 JCS canonicalisation.

This module is the dependency-free fallback for ``rfc8785.dumps``.
It produces byte-identical output to the ``rfc8785`` PyPI package
for the JSON subset used by Wakir Phase-1b documents (AIP-document,
FTD-document, federation-document, DID-document).

The module is intentionally lifted out of ``ftd_verifier._local_jcs``
(Tag-6) so that ``aip_signing``, ``did_document_signing`` and any
future signer / verifier can share a single canonicaliser without
duplicating it. Tag-9 introduced this central module as part of the
"resolver indirection" pattern: production callers wrap the import
in a ``try/except`` and fall back to :func:`canonicalize` when the
``rfc8785`` package is not installed in the runtime environment.

References (URL-200-stamped 2026-05-07):

- RFC 8785: <https://datatracker.ietf.org/doc/html/rfc8785>
- ECMA-262 § 7.1.12.1 (Number-to-String):
  <https://www.ecma-international.org/ecma-262/12.0/index.html#sec-tostring-applied-to-the-number-type>

Spec-coverage map (RFC 8785 § 3):

- § 3.1   UTF-8 output (no BOM, no trailing whitespace).
- § 3.2.1 Numbers per ECMA-262 § 7.1.12.1; this module handles
          integers exactly (Python ``int`` repr) and provides a
          defensive float branch using ``repr`` (Python's own
          shortest-roundtrip-string algorithm) which matches
          ECMA-262 for the values exercised by Phase-1b documents.
          Phase-1b documents do not contain floats; the float branch
          is hardened for forward compatibility.
- § 3.2.2 Strings: control characters (< 0x20) are ``\\u``-escaped;
          backslash, double-quote and the standard short escapes
          are emitted in their short form; all other characters are
          emitted verbatim as UTF-8 bytes (RFC 8785 § 3.2.2.2 mandates
          the "shortest form" for U+0080 and above).
- § 3.2.3 Object members are sorted by their UTF-16 code-unit
          sequence. For ASCII-only keys (the entire Phase-1b shape)
          this matches Python's default string ordering. The
          implementation does the spec-precise UTF-16 ordering so
          schema evolution into non-ASCII keys remains canonical.
- § 3.2.4 Arrays preserve input order.
"""

from __future__ import annotations


__all__ = ["canonicalize"]


def canonicalize(value: object) -> bytes:
    """Return the JCS-canonical UTF-8 bytes of ``value``.

    The output is byte-identical to ``rfc8785.dumps(value)`` for the
    JSON subset exercised by Phase-1b documents; cross-equivalence is
    verified by ``test_jcs_pure_matches_rfc8785_per_vector`` in the
    Tag-9 test suite.

    Args:
        value: A JSON-compatible Python object. Permitted types:
            ``dict`` (with ``str`` keys), ``list``, ``str``, ``int``
            (not ``bool``), ``float``, ``bool``, ``None``.

    Returns:
        UTF-8 encoded JCS-canonical bytes.

    Raises:
        TypeError: if ``value`` (or any nested element) is of an
            unsupported type. Refusal is loud-by-design: silent
            coercion of e.g. ``set`` to ``list`` would produce a
            different canonical form than ``rfc8785``.
    """
    return _serialize(value).encode("utf-8")


def _serialize(value: object) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _serialize_string(value)
    if isinstance(value, bool):
        # Already handled above; defensive guard against subclassing.
        return "true" if value else "false"
    if isinstance(value, int):
        return _serialize_integer(value)
    if isinstance(value, float):
        return _serialize_float(value)
    if isinstance(value, list):
        return "[" + ",".join(_serialize(x) for x in value) + "]"
    if isinstance(value, dict):
        return _serialize_object(value)
    raise TypeError(
        f"JCS: unsupported type {type(value).__name__!r}; "
        "rfc8785 produces no canonical form for this type"
    )


def _serialize_integer(value: int) -> str:
    # Python int repr is identical to ECMA-262's ToString for
    # finite integers in the range JSON exercises. RFC 8785 § 3.2.1
    # delegates to ECMA-262 § 7.1.12.1.
    return repr(value)


def _serialize_float(value: float) -> str:
    # ECMA-262 § 7.1.12.1 step 5: shortest-roundtrip-string.
    # Python's float ``repr`` already implements
    # shortest-roundtrip (since Python 3.1, see PEP 3101 / CPython
    # ``floatobject.c``). Special values below match ECMA-262 step 1-4.
    if value != value:  # NaN
        raise ValueError("JCS: NaN is not a valid JSON number (RFC 8785 § 3.2.1)")
    if value == float("inf"):
        raise ValueError("JCS: +Infinity is not a valid JSON number (RFC 8785 § 3.2.1)")
    if value == float("-inf"):
        raise ValueError("JCS: -Infinity is not a valid JSON number (RFC 8785 § 3.2.1)")
    if value == 0.0:
        # ECMA-262 step 2: +0 and -0 both serialise as "0".
        return "0"
    return repr(value)


def _serialize_string(value: str) -> str:
    out = ['"']
    for ch in value:
        cp = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\b":
            out.append("\\b")
        elif ch == "\f":
            out.append("\\f")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif cp < 0x20:
            out.append(f"\\u{cp:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _utf16_codeunits(s: str) -> tuple[int, ...]:
    """Decompose ``s`` into a tuple of UTF-16 code units.

    For BMP code points (U+0000..U+FFFF) this is just ``(ord(c),)``;
    for supplementary code points (U+10000..U+10FFFF) it returns
    a high-surrogate / low-surrogate pair. The tuple is suitable as
    a sort key — Python tuple ordering is lexicographic, which is
    exactly what RFC 8785 § 3.2.3 requires.
    """
    out: list[int] = []
    for ch in s:
        cp = ord(ch)
        if cp <= 0xFFFF:
            out.append(cp)
        else:
            # Surrogate pair.
            cp -= 0x10000
            high = 0xD800 + (cp >> 10)
            low = 0xDC00 + (cp & 0x3FF)
            out.append(high)
            out.append(low)
    return tuple(out)


def _serialize_object(value: dict) -> str:
    items = []
    for key in value.keys():
        if not isinstance(key, str):
            raise TypeError(
                f"JCS: object keys must be strings; got {type(key).__name__!r}"
            )
        items.append(key)
    items.sort(key=_utf16_codeunits)
    body = ",".join(
        _serialize_string(k) + ":" + _serialize(value[k]) for k in items
    )
    return "{" + body + "}"
