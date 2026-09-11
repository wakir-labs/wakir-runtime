#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Canonical schema digest for the cross-repo compatibility gate.

Rule (identical in ``wakir-protocol/tooling/compat/`` — the two
implementations must agree byte-for-byte)::

    digest = sha256(JCS(strip(doc)))

where ``strip`` removes, **at every nesting level**, every object
member whose key

* starts with ``x-spdx-`` **and whose value is a string** (licence-
  header extension keys; protocol and runtime copies legitimately carry
  different licence headers), or
* equals ``description`` **and whose value is a string** (prose that
  may be edited independently without changing the contract).

The string-valued condition matters: five persona schemas *define* a
property named ``description`` (``"description": {"type": "string",
...}``). That member is contract and must survive; only prose strings
are dropped.

Why recursive: JSON-Schema prose lives inside ``properties``,
``items``, ``$defs`` and so on. Stripping only the top level leaves 7
of the 16 mirrored schemas red on prose differences (measured
2026-09-11 against protocol ``b7de631``); stripping recursively yields
16/16 identical. Everything else — ``enum``, ``const``, ``required``,
``pattern``, ``$id``, ``title``, ``additionalProperties``, ``examples``
— is part of the contract and stays in the digest.

Stdlib + ``rfc8785`` only.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import rfc8785

#: Key prefix stripped before canonicalisation (licence-header extension keys).
STRIPPED_KEY_PREFIX = "x-spdx-"

#: Exact keys stripped before canonicalisation.
STRIPPED_KEYS = frozenset({"description"})

#: Marker key/value on a protocol schema that is not yet canonical.
STUB_STATUS_KEY = "x-status"
STUB_STATUS_VALUE = "stub"


def is_stripped_member(key: str, value: Any) -> bool:
    """True when the object member ``key: value`` is excluded from the canonical form."""
    if not isinstance(value, str):
        return False
    return key.startswith(STRIPPED_KEY_PREFIX) or key in STRIPPED_KEYS


def strip_non_canonical(obj: Any) -> Any:
    """Return a deep copy of ``obj`` without the stripped members (recursive)."""
    if isinstance(obj, dict):
        return {
            key: strip_non_canonical(value)
            for key, value in obj.items()
            if not is_stripped_member(key, value)
        }
    if isinstance(obj, list):
        return [strip_non_canonical(item) for item in obj]
    return obj


def canonical_bytes(schema: Any) -> bytes:
    """JCS bytes of the stripped schema."""
    return rfc8785.dumps(strip_non_canonical(schema))


def canonical_digest(schema: Any) -> str:
    """SHA-256 hex digest of :func:`canonical_bytes`."""
    return hashlib.sha256(canonical_bytes(schema)).hexdigest()


def load_json(path: str | Path) -> Any:
    """Read a JSON document from disk (UTF-8)."""
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def canonical_digest_of_file(path: str | Path) -> str:
    """Canonical digest of the JSON document stored at ``path``."""
    return canonical_digest(load_json(path))


def is_stub_schema(schema: Any) -> bool:
    """True when the schema declares itself a placeholder (``x-status: stub``)."""
    return isinstance(schema, dict) and schema.get(STUB_STATUS_KEY) == STUB_STATUS_VALUE


def main(argv: list[str] | None = None) -> int:
    """CLI: print ``<digest>  <path>`` per argument (sha256sum-style)."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Canonical (JCS, string-valued x-spdx-*/description stripped) SHA-256 of JSON schemas.",
    )
    parser.add_argument("paths", nargs="+", help="JSON schema files")
    args = parser.parse_args(argv)
    for raw in args.paths:
        print(f"{canonical_digest_of_file(raw)}  {raw}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
