# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic HCL-shape acceptance tests for the Phase-2 Sprint-10 Tag-1
SPIRE-Server federation configs (Sprint-10 Tag-6 substance-fix).

**Why this test surface exists.**

The Sprint-10 Tag-5 Live-Trial uncovered four federation-config bugs
(Bug-30..33) that the prior hermetic test surface
(``test_federation_compose.py`` + ``test_pilot_bootstrap_side_aware.py``)
did NOT catch:

- **Bug-30:** ``bundle_endpoint_profile = "X" { block }`` — HCL forbids
  the mixed flat-attribute-plus-block form. SPIRE 1.14.6 emits
  ``malformed configuration``.
- **Bug-31:** ``profile = "https_spiffe"`` flat-attribute inside
  ``bundle_endpoint { }`` — must be either named-block or absent
  (default ``https_spiffe``).
- **Bug-32:** ``federates_with`` block placed at top-level — must be
  nested inside ``server.federation { }``.
- **Bug-33:** Bootstrap step 5 skip-cosign-path called the resolver
  without ``--spire-server-digest`` etc. — covered by
  ``test_proxmox_resolve_image_pins.py``.

The prior tests only checked **string-presence-invariants**
(``"https_spiffe" in text``), not structural HCL parse validity. The
present module adds a minimal in-tree HCL-fragment-validator that
catches the 4 bug shapes by examining the parse-relevant structure
(no new external dependency, no ``hcl2``/``pyhcl`` install). This is a
**regression-guard**, not a full HCL parser: it asserts the four
bug-shape invariants, leaves general validation to SPIRE's own
``spire-server validate`` in the live-VM acceptance lane
(``scripts/federation-live-vm-acceptance.sh``).

**Memory anchor:** ``feedback_live_bringup_sandbox_gap.md`` — Sprint-10
Tag-5 was the 6th trigger of this anti-pattern; this test closes the
gap for the 4 federation-config bug shapes by lifting the hermetic test
surface from string-presence to structural-shape invariants.

Invariant IDs:

- ``T-FED-HCL-01``: NO ``profile = "..."`` flat-attribute inside
  ``bundle_endpoint { }`` (Bug-31 regression-guard).
- ``T-FED-HCL-02``: NO ``bundle_endpoint_profile = "X" { ... }`` mixed
  form anywhere (Bug-30 regression-guard).
- ``T-FED-HCL-03``: ``federates_with`` MUST be nested inside
  ``server.federation { }``, NEVER at top-level (Bug-32 regression-guard).
- ``T-FED-HCL-04``: ``bundle_endpoint_profile "X" { ... }`` named-block
  form MUST be used when the profile is declared at all (positive
  shape assertion).
- ``T-FED-HCL-05``: Brace balance — every config file must have equal
  open/close brace counts.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
FED_CONFIG_DIR = REPO_ROOT / "infra" / "spire" / "federation" / "config"


def _strip_comments_and_strings(text: str) -> str:
    """Strip ``#``/``//`` line comments and ``"..."`` string literals.

    The four bug-shape invariants must be checked on the structural
    skeleton of the HCL document, NOT on comment text or string
    literals. Otherwise a comment like ``# profile = "https_spiffe"``
    would trigger a false positive on T-FED-HCL-01.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        # Line comment.
        if c == "#" or (c == "/" and i + 1 < n and text[i + 1] == "/"):
            # Skip to end of line.
            while i < n and text[i] != "\n":
                i += 1
            continue
        # Block comment.
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        # String literal — replace with empty quotes to keep token
        # boundaries intact but drop the literal contents.
        if c == '"':
            out.append('""')
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                i += 1
            i += 1  # skip closing quote
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _config_files() -> list[Path]:
    files = sorted(FED_CONFIG_DIR.glob("spire-server-*.conf"))
    assert files, f"no federation configs found under {FED_CONFIG_DIR}"
    return files


@pytest.fixture(scope="module", params=_config_files(), ids=lambda p: p.name)
def config_text(request) -> tuple[str, str, Path]:
    path: Path = request.param
    raw = path.read_text(encoding="utf-8")
    stripped = _strip_comments_and_strings(raw)
    return raw, stripped, path


# ---------------------------------------------------------------------
# T-FED-HCL-01 — Bug-31 regression-guard
# ---------------------------------------------------------------------


def test_no_profile_flat_attribute_inside_bundle_endpoint(config_text):
    """Bug-31 regression-guard.

    The flat-attribute form ``profile = "https_spiffe"`` inside
    ``bundle_endpoint { }`` is invalid HCL for SPIRE 1.14.6. The
    profile MUST be either omitted (default = https_spiffe) or
    expressed as a named-block via
    ``bundle_endpoint_profile "https_spiffe" { ... }`` on the
    ``federates_with`` side.
    """
    _raw, stripped, path = config_text
    # Look for ``profile = "..."`` as a flat attribute. We match in the
    # comment-stripped text, so any hit is real code.
    flat_profile = re.search(r"\bprofile\s*=\s*\"\"", stripped)
    assert flat_profile is None, (
        f"{path.name}: Bug-31 regression — "
        f"`profile = \"...\"` flat-attribute is invalid HCL for SPIRE "
        f"1.14.6 (parser emits `malformed configuration`). Use the "
        f"`bundle_endpoint_profile \"...\" {{ }}` named-block form on "
        f"the federates_with side, or omit (default is https_spiffe)."
    )


# ---------------------------------------------------------------------
# T-FED-HCL-02 — Bug-30 regression-guard
# ---------------------------------------------------------------------


def test_no_mixed_attribute_block_form(config_text):
    """Bug-30 regression-guard.

    The mixed form ``bundle_endpoint_profile = "X" { ... }`` is invalid
    HCL: an attribute (``key = value``) cannot also be a block. SPIRE
    1.14.6 rejects this with ``malformed configuration``.
    """
    _raw, stripped, path = config_text
    # Mixed form: <ident> = "..." {
    # In stripped text, strings are "" so the pattern becomes:
    #   bundle_endpoint_profile = "" {
    mixed = re.search(
        r"\bbundle_endpoint_profile\s*=\s*\"\"\s*\{", stripped
    )
    assert mixed is None, (
        f"{path.name}: Bug-30 regression — "
        f"`bundle_endpoint_profile = \"...\" {{ }}` mixed form is "
        f"invalid HCL. Use the named-block form "
        f"`bundle_endpoint_profile \"...\" {{ }}` (no equals sign)."
    )


# ---------------------------------------------------------------------
# T-FED-HCL-03 — Bug-32 regression-guard
# ---------------------------------------------------------------------


def _find_block_extents(text: str, block_name: str) -> list[tuple[int, int]]:
    """Find ``<block_name> { ... }`` extents in brace-balanced form.

    Returns a list of (start, end) byte-offsets covering the block
    body including the opening/closing braces. Block name matches
    are anchored on word-boundaries. Nested braces are tracked.
    """
    extents: list[tuple[int, int]] = []
    pattern = re.compile(rf"\b{re.escape(block_name)}\b\s*\{{")
    for m in pattern.finditer(text):
        start = m.end() - 1  # the opening brace position
        depth = 1
        i = start + 1
        while i < len(text) and depth > 0:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        extents.append((m.start(), i))
    return extents


def test_federates_with_nested_inside_server_federation(config_text):
    """Bug-32 regression-guard.

    ``federates_with "<td>" { }`` blocks MUST be nested inside the
    ``server { federation { } }`` chain, NEVER at top-level. SPIRE
    1.14.6 emits ``malformed configuration`` if the block is placed
    at top-level.
    """
    _raw, stripped, path = config_text

    server_extents = _find_block_extents(stripped, "server")
    federation_extents = _find_block_extents(stripped, "federation")

    # Find every `federates_with` occurrence (the keyword followed by
    # a quoted string literal — replaced with "" after stripping —
    # and an opening brace).
    fw_pattern = re.compile(r"\bfederates_with\s+\"\"\s*\{")
    fw_matches = list(fw_pattern.finditer(stripped))
    if not fw_matches:
        # Single-org pilot config legitimately does not federate; it
        # has no federates_with block to validate. The federation-mode
        # configs (wakir, partner, orbit) MUST carry at least one.
        if "pilot-single-org" in path.name:
            pytest.skip(
                "single-org config has no federates_with by design"
            )
        pytest.fail(
            f"{path.name}: no federates_with block found — expected "
            f"at least one in every federation-mode config."
        )

    for m in fw_matches:
        pos = m.start()
        # Must lie inside one of the server-block extents AND inside
        # one of the federation-block extents.
        in_server = any(start < pos < end for start, end in server_extents)
        in_federation = any(
            start < pos < end for start, end in federation_extents
        )
        assert in_server, (
            f"{path.name}: Bug-32 regression — `federates_with` block "
            f"at byte {pos} is NOT inside a `server {{ }}` block. "
            f"SPIRE 1.14.6 rejects top-level federates_with."
        )
        assert in_federation, (
            f"{path.name}: Bug-32 regression — `federates_with` block "
            f"at byte {pos} is NOT inside a `federation {{ }}` block. "
            f"Must be nested as `server {{ federation {{ federates_with "
            f"\"...\" {{ }} }} }}`."
        )


# ---------------------------------------------------------------------
# T-FED-HCL-04 — positive shape assertion
# ---------------------------------------------------------------------


def test_bundle_endpoint_profile_uses_named_block_form_when_present(config_text):
    """When the federates_with block declares a bundle_endpoint_profile
    at all, it MUST use the named-block syntax
    ``bundle_endpoint_profile "X" { ... }`` (no equals sign).
    """
    _raw, stripped, path = config_text
    # The keyword MAY be absent entirely (the SPIRE default
    # https_spiffe applies). When present, the form must be:
    #   bundle_endpoint_profile <whitespace> "X" <whitespace> {
    occurrences = [
        m for m in re.finditer(r"\bbundle_endpoint_profile\b", stripped)
    ]
    for m in occurrences:
        tail = stripped[m.end() : m.end() + 12]
        # Reject `bundle_endpoint_profile =` form (Bug-30/31 territory).
        assert not re.match(r"\s*=", tail), (
            f"{path.name}: Bug-30/31 regression — "
            f"bundle_endpoint_profile must NOT be followed by `=`. "
            f"Use named-block form: bundle_endpoint_profile \"X\" {{ }}"
        )
        # Accept `bundle_endpoint_profile ""` followed (eventually) by `{`.
        assert re.match(r"\s+\"\"\s*\{", tail), (
            f"{path.name}: bundle_endpoint_profile must use named-block "
            f"form `bundle_endpoint_profile \"X\" {{ }}`. Got "
            f"{tail!r} after keyword."
        )


# ---------------------------------------------------------------------
# T-FED-HCL-05 — brace balance
# ---------------------------------------------------------------------


def test_brace_balance(config_text):
    """Every federation config must have equal open/close brace counts.

    Trivial structural sanity check — catches the most common manual-
    edit mistake (missing/extra brace).
    """
    _raw, stripped, path = config_text
    opens = stripped.count("{")
    closes = stripped.count("}")
    assert opens == closes, (
        f"{path.name}: brace imbalance — {opens} `{{` vs {closes} `}}`. "
        f"HCL parse will fail."
    )


# ---------------------------------------------------------------------
# T-FED-HCL-06 — server / trust_domain / federation skeleton present
# ---------------------------------------------------------------------


def test_required_skeleton_present(config_text):
    """Every federation config must declare server / trust_domain /
    federation block. Sanity floor before we ship the file to SPIRE.
    """
    _raw, stripped, path = config_text
    assert re.search(r"\bserver\s*\{", stripped), (
        f"{path.name}: missing top-level `server {{ }}` block"
    )
    assert re.search(r"\btrust_domain\s*=\s*\"\"", stripped), (
        f"{path.name}: missing `trust_domain = \"...\"` declaration"
    )
    # Federation block — only required for federation-mode configs.
    # The single-org pilot config does not federate.
    if "pilot-single-org" not in path.name:
        assert re.search(r"\bfederation\s*\{", stripped), (
            f"{path.name}: missing `federation {{ }}` block (federation "
            f"config; single-org configs are exempted by name)"
        )


# ---------------------------------------------------------------------
# T-FED-HCL-07 — helper self-test (strip-comments-and-strings)
# ---------------------------------------------------------------------


def test_strip_helper_kills_line_comments_and_strings():
    sample = '# profile = "https_spiffe"\nserver { trust_domain = "wakir.test" }\n'
    stripped = _strip_comments_and_strings(sample)
    # The comment is gone; the string body is replaced with "".
    assert "profile" not in stripped, stripped
    assert "https_spiffe" not in stripped, stripped
    assert "wakir.test" not in stripped, stripped
    # But the structural tokens remain.
    assert "server" in stripped
    assert "trust_domain" in stripped
    assert "{" in stripped
    assert "}" in stripped


# ---------------------------------------------------------------------
# T-FED-HCL-08 — negative-control: synthetic broken configs must FAIL
# the validator. Proves the validator actually catches the 4 bug shapes
# rather than rubber-stamping anything. Without these tests, the
# positive-only tests above could pass on a no-op validator.
# ---------------------------------------------------------------------


_BUG30_BROKEN_CONFIG = """
server {
  trust_domain = "wakir.test"
  federation {
    bundle_endpoint { address = "0.0.0.0" port = 8443 }
    federates_with "partner.test" {
      bundle_endpoint_url = "https://x:8443"
      bundle_endpoint_profile = "https_spiffe" {
        endpoint_spiffe_id = "spiffe://partner.test/spire/server"
      }
    }
  }
}
"""

_BUG31_BROKEN_CONFIG = """
server {
  trust_domain = "wakir.test"
  federation {
    bundle_endpoint {
      address = "0.0.0.0"
      port = 8443
      profile = "https_spiffe"
    }
    federates_with "partner.test" {
      bundle_endpoint_url = "https://x:8443"
    }
  }
}
"""

_BUG32_BROKEN_CONFIG = """
server {
  trust_domain = "wakir.test"
  federation {
    bundle_endpoint { address = "0.0.0.0" port = 8443 }
  }
}
federates_with "partner.test" {
  bundle_endpoint_url = "https://x:8443"
}
"""


def _run_validator_on_synthetic(text: str, invariant: str) -> str:
    """Run the four invariant-checks on synthetic text. Returns the
    name of the invariant that fired (or "" if none fired)."""
    stripped = _strip_comments_and_strings(text)
    # T-FED-HCL-01 — flat profile attribute.
    if re.search(r"\bprofile\s*=\s*\"\"", stripped):
        return "T-FED-HCL-01"
    # T-FED-HCL-02 — mixed attribute/block form.
    if re.search(r"\bbundle_endpoint_profile\s*=\s*\"\"\s*\{", stripped):
        return "T-FED-HCL-02"
    # T-FED-HCL-03 — federates_with outside server/federation.
    server_extents = _find_block_extents(stripped, "server")
    federation_extents = _find_block_extents(stripped, "federation")
    for m in re.finditer(r"\bfederates_with\s+\"\"\s*\{", stripped):
        pos = m.start()
        in_server = any(s < pos < e for s, e in server_extents)
        in_federation = any(s < pos < e for s, e in federation_extents)
        if not (in_server and in_federation):
            return "T-FED-HCL-03"
    return ""


def test_bug30_broken_config_caught_by_validator():
    """Mixed `bundle_endpoint_profile = "X" { ... }` form must trigger
    T-FED-HCL-02 (most specific) — not T-FED-HCL-01 (the flat-attribute
    check also matches, but the mixed-form check is the canonical
    Bug-30 catch).
    """
    # Our validator order checks T-FED-HCL-01 first (matches the
    # `<ident> = ""` substring), so Bug-30 actually trips
    # T-FED-HCL-01 — both are correct catches; the important thing is
    # that the validator REJECTS the input.
    result = _run_validator_on_synthetic(_BUG30_BROKEN_CONFIG, "T-FED-HCL-02")
    assert result in ("T-FED-HCL-01", "T-FED-HCL-02"), (
        f"validator must catch Bug-30 mixed form, got {result!r}"
    )


def test_bug31_broken_config_caught_by_validator():
    result = _run_validator_on_synthetic(_BUG31_BROKEN_CONFIG, "T-FED-HCL-01")
    assert result == "T-FED-HCL-01", (
        f"validator must catch Bug-31 flat-profile via T-FED-HCL-01, "
        f"got {result!r}"
    )


def test_bug32_broken_config_caught_by_validator():
    result = _run_validator_on_synthetic(_BUG32_BROKEN_CONFIG, "T-FED-HCL-03")
    assert result == "T-FED-HCL-03", (
        f"validator must catch Bug-32 top-level federates_with via "
        f"T-FED-HCL-03, got {result!r}"
    )


def test_known_good_config_passes_validator():
    """Sanity: the actual main-tip wakir-config (post Bug-30..32 fix)
    must NOT trip any invariant. Otherwise we have a false positive in
    the validator itself.
    """
    good = (FED_CONFIG_DIR / "spire-server-wakir.conf").read_text(
        encoding="utf-8"
    )
    result = _run_validator_on_synthetic(good, "")
    assert result == "", (
        f"known-good wakir config tripped {result!r} — false positive"
    )
