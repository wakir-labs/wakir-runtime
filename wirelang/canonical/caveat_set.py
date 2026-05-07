# SPDX-License-Identifier: Apache-2.0
"""Caveat-Set Canonicalisation Rule (§4-CSC).

Implementation of the Phase-2 ratified Caveat-Set Canonicalisation
Rule from ``wirelang/specs/datalog-caveat-vocabulary-phase-2.md`` §4.

The four canonicalisation steps, applied in order:

1. **Whitespace normalisation.** Within each caveat, collapse runs
   of ASCII space (U+0020) to a single space, replace TAB / CR / LF
   with a single space before collapsing, and strip leading/trailing
   space.
2. **Predicate-call dedup.** Byte-identical normalised duplicates
   are removed; the first occurrence is kept.
3. **Lexicographic sort.** Sort the deduplicated, normalised caveats
   as UTF-8 byte sequences in ascending order.
4. **JCS-array serialisation.** Serialise as a JSON array of strings
   per RFC 8785; SHA-256 of the resulting byte sequence is the
   ``caveat_set_hash``.

The module exposes both an rfc8785-backed and a Pure-Python fallback
serialisation path so the cross-lane parity invariant from
TV-W-2 §6.2 is maintained even on the sandbox CI lane (where
``rfc8785`` is not installed).
"""

from __future__ import annotations

import hashlib
import re
from typing import Iterable, List

# Allow rfc8785 when present; fall back to the project's local
# pure-Python JCS canonicaliser otherwise. The same indirection
# pattern is used by ``aip_signing`` and ``did_document_signing``.
try:  # pragma: no cover - import-time selection
    import rfc8785 as _rfc8785

    def _jcs_dumps(value: object) -> bytes:
        return _rfc8785.dumps(value)

except ImportError:  # pragma: no cover - import-time selection
    from wirelang.identity._jcs_pure import canonicalize as _jcs_pure

    def _jcs_dumps(value: object) -> bytes:
        return _jcs_pure(value)


# ---------------------------------------------------------------------------
# Step 1 — whitespace normalisation
# ---------------------------------------------------------------------------

# All whitespace classes the §4.1 normalisation rule covers. The rule
# is deliberately scoped to the four ASCII whitespace characters; an
# extension to wider Unicode whitespace classes is a future spec
# event (see §6.3 re-baseline list, item 2).
_WS_RE = re.compile(r"[ \t\r\n]+")


def _normalize_whitespace(caveat: str) -> str:
    """Apply §4.1 step 1 to a single caveat string."""
    if not isinstance(caveat, str):
        raise TypeError(
            "caveat must be str; got "
            f"{type(caveat).__name__}"
        )
    # Replace any whitespace run with a single ASCII space, then
    # strip leading/trailing whitespace. The regex collapses runs
    # of mixed whitespace characters in one pass.
    return _WS_RE.sub(" ", caveat).strip()


# ---------------------------------------------------------------------------
# Step 2+3 — dedup-and-sort (combined for cleanliness)
# ---------------------------------------------------------------------------


def _dedup_then_sort(normalised: Iterable[str]) -> List[str]:
    """Apply §4.1 steps 2 and 3 to an iterable of normalised caveats.

    Dedup keeps the first occurrence (set semantics; byte-identical
    duplicates are no-ops in Biscuit-Datalog so order of "kept"
    occurrences is irrelevant). Sort is UTF-8 lexicographic.
    """
    seen: set[str] = set()
    deduped: List[str] = []
    for c in normalised:
        if c in seen:
            continue
        seen.add(c)
        deduped.append(c)
    # Python's default str-sort uses code-point order; for the ASCII
    # subset that admits the v0.1+v0.2 vocabulary this is identical
    # to UTF-8 byte-sort. (For non-ASCII content the encode-then-sort
    # path is used to guarantee byte-order parity.)
    return sorted(deduped, key=lambda s: s.encode("utf-8"))


# ---------------------------------------------------------------------------
# Public API — the four-step composition
# ---------------------------------------------------------------------------


def canonicalize_caveat_set(caveats: Iterable[str]) -> List[str]:
    """Return the canonical caveat-set as a Python list of strings.

    This is the input to JCS-array serialisation. Returned list is
    a fresh list owned by the caller; the input is not mutated.
    """
    normalised = [_normalize_whitespace(c) for c in caveats]
    return _dedup_then_sort(normalised)


def canonical_caveat_set_bytes(caveats: Iterable[str]) -> bytes:
    """Return the JCS-array byte sequence per §4.1 step 4.

    The returned bytes are the canonical pre-image used by the
    ``caveat_hash`` self-reference predicate (Phase-2 Class P,
    deferred) and by the TV-W-2 ``caveat_set_hashes`` field.
    """
    canonical_list = canonicalize_caveat_set(caveats)
    return _jcs_dumps(canonical_list)


def canonical_caveat_set_hash(caveats: Iterable[str]) -> bytes:
    """Return the SHA-256 of :func:`canonical_caveat_set_bytes`.

    This is the load-bearing primitive ratified in §4.1: the
    ``caveat_set_hash`` of a caveat-set is a 32-byte SHA-256 digest
    over the canonical JCS-array serialisation.
    """
    return hashlib.sha256(canonical_caveat_set_bytes(caveats)).digest()


# ---------------------------------------------------------------------------
# Pure-Python-only path for cross-lane parity testing
# ---------------------------------------------------------------------------


def _canonical_caveat_set_bytes_pure(caveats: Iterable[str]) -> bytes:
    """Force the Pure-Python JCS path regardless of rfc8785 presence.

    Used by the test suite to assert cross-lane parity: production
    lane (rfc8785) and sandbox lane (_jcs_pure) MUST produce
    byte-identical output for the same input.
    """
    from wirelang.identity._jcs_pure import canonicalize as _jcs_pure

    canonical_list = canonicalize_caveat_set(caveats)
    return _jcs_pure(canonical_list)


def _canonical_caveat_set_hash_pure(caveats: Iterable[str]) -> bytes:
    """SHA-256 over the Pure-Python canonical bytes."""
    return hashlib.sha256(_canonical_caveat_set_bytes_pure(caveats)).digest()
