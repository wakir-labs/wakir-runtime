# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""V-907 persona-hash verify (spec §3.7.2.2 #1, §5).

Real implementation of the V-907 pin-verify step that the
Sprint-10 Tag-4 stub binary only **computes** (stub emits the
SHA-256 of axis-A bytes prefixed ``sha256-stub:``). This module:

1. Reads axis-A bytes (``/etc/wakir/persona/<slug>.md``).
2. Splits front-matter via ``persona-canonical-form-yaml``.
3. Walks the YAML mapping into the V-907 canonical-subset shape.
4. Computes the JCS-SHA-256 over the canonical subset via the
   existing ``wirelang.persona.persona_hash`` primitive (no new
   hash function — spec §5 anchor).
5. Compares against an operator-supplied expected pin
   (env-var ``WAKIR_PERSONA_V907_EXPECTED_PIN``); on mismatch
   raises :class:`PersonaHashDriftError`.

Spec §5 anchor
--------------

The hash function and canonical subset are unchanged from
Phase-1b. This module is the **engine-side caller** that wires the
existing primitive into the spawn-time verification gate. Zone-K
(Tomás/WAT-bridge) was satisfied by the upstream primitive; this
module only consumes.

Stub vs. real
-------------

Stub binary (``0.1.0-pilot``):

    pin = "sha256-stub:" + sha256(raw_axis_a_bytes).hex()

Real engine (``0.2.0-pilot``, this module):

    pin = persona_hash.compute_persona_hash(canonical_subset_dict)
        = "sha256:" + sha256(jcs_canonical_bytes(canonical_subset)).hex()

The two are byte-distinct by construction (the stub hashes raw
markdown bytes; the real engine hashes the JCS canonical subset).
The stub prefix ``sha256-stub:`` is the audit signal that the
engine is in stub mode; the real engine emits ``sha256:`` and the
``v907_pin_mode`` field in the spawn audit record reads ``real``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class PersonaHashDriftError(RuntimeError):
    """Raised when the computed V-907 pin does not match the expected
    pin supplied by the operator."""

    def __init__(self, expected: str, computed: str, persona_id: str) -> None:
        self.expected = expected
        self.computed = computed
        self.persona_id = persona_id
        super().__init__(
            f"V-907 pin drift for persona {persona_id!r}: "
            f"expected={expected} computed={computed}"
        )


class PersonaHashComputeError(RuntimeError):
    """Raised when the V-907 pin cannot be computed (axis-A parse error,
    missing schema_version, etc.)."""


@dataclass(frozen=True)
class V907VerifyResult:
    """Result of a V-907 verify call.

    - :attr:`pin`: the computed pin (``"sha256:<64hex>"``).
    - :attr:`mode`: ``"real"`` for this module, ``"stub"`` for the
      0.1.0-pilot stub binary. The audit substrate uses this to
      filter stub-period output from the 4-Achsen-Score-Bilanz.
    - :attr:`matched`: True iff an expected pin was supplied AND
      the computed pin matched it.
    """

    pin: str
    mode: str
    matched: Optional[bool]  # None if no expected pin supplied


def compute_v907_pin(axis_a_bytes: bytes) -> str:
    """Compute the V-907 pin per spec §5 over axis-A markdown bytes.

    The path is:

        axis-A bytes
          -> persona_canonical_form_yaml.split_frontmatter
          -> persona_canonical_form_yaml.parse_frontmatter
          -> walk into canonical_subset (persona-v1 mock shape)
          -> persona_hash.compute_persona_hash_from_canonical_jcs

    Lazy imports of the crypto-bearing surfaces (parity with
    ``wirelang.persona`` PEP-562 disentanglement).
    """
    try:
        from wirelang.persona.persona_canonical_form import (
            parse_frontmatter,
            split_frontmatter,
        )
    except ImportError as exc:  # pragma: no cover — defensive
        raise PersonaHashComputeError(
            "wirelang.persona.persona_canonical_form missing; "
            "this engine image is mis-built (rebuild from the "
            "wakir-runtime tree)."
        ) from exc

    text = axis_a_bytes.decode("utf-8")
    try:
        fm, _body = split_frontmatter(text)
    except Exception as exc:  # noqa: BLE001
        raise PersonaHashComputeError(
            f"axis-A front-matter split failed: {exc}"
        ) from exc

    try:
        mapping = parse_frontmatter(fm)
    except Exception as exc:  # noqa: BLE001
        raise PersonaHashComputeError(
            f"axis-A front-matter YAML parse failed: {exc}"
        ) from exc

    # Build canonical_subset from the mapping. Only V-907 mock shape
    # is supported in v0.2.0-pilot: schema_version + identity_pinned +
    # capabilities (if present). HR-slot can extend this later via
    # ADR-0029.
    schema_version = mapping.get("schema_version")
    if not schema_version:
        # Axis-A from .claude/agents/*.md does not always carry
        # schema_version; the persona-engine-format converter
        # synthesises persona-v1 defaults in that case. We mirror that
        # shape here for the spawn-time verify.
        schema_version = "persona-v1"

    canonical_subset = {
        "schema_version": schema_version,
    }
    # Walk recognised V-907 keys into the canonical subset. Order
    # within the subset does NOT matter — JCS canonicaliser sorts
    # alphabetically.
    for key in ("identity_pinned", "capabilities", "domain", "reports_to"):
        if key in mapping:
            canonical_subset[key] = mapping[key]

    # Delegate to the existing V-907 hash primitive.
    try:
        from wirelang.persona.persona_hash import (
            compute_persona_hash_from_canonical,
        )
    except ImportError as exc:
        raise PersonaHashComputeError(
            "wirelang.persona.persona_hash missing; this engine "
            "image is mis-built."
        ) from exc

    return compute_persona_hash_from_canonical(canonical_subset)


def verify_v907_pin(
    persona_id: str,
    axis_a_path: Path,
    expected_pin: Optional[str],
) -> V907VerifyResult:
    """Compute + optionally verify the V-907 pin for a persona.

    Parameters
    ----------
    persona_id
        Persona slug (used only for error context).
    axis_a_path
        Path to ``<slug>.md`` (the bind-mounted axis-A definition).
    expected_pin
        Operator-supplied pin (typically from env-var
        ``WAKIR_PERSONA_V907_EXPECTED_PIN``). If None, the function
        only computes; if set, mismatch raises
        :class:`PersonaHashDriftError`.
    """
    if not axis_a_path.is_file():
        raise PersonaHashComputeError(
            f"axis-A path {axis_a_path} not a regular file"
        )
    axis_a_bytes = axis_a_path.read_bytes()
    pin = compute_v907_pin(axis_a_bytes)
    matched: Optional[bool] = None
    if expected_pin is not None and expected_pin.strip():
        matched = pin == expected_pin
        if not matched:
            raise PersonaHashDriftError(
                expected=expected_pin,
                computed=pin,
                persona_id=persona_id,
            )
    return V907VerifyResult(pin=pin, mode="real", matched=matched)
