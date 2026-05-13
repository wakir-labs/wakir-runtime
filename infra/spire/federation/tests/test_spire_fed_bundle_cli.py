# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic acceptance tests for the ``spire-fed-bundle`` CLI
(Phase-2 Sprint-8 Tag-1 SPIRE-Federation manual bootstrap path).

Roundtrip exercise:

  1) ``spire-fed-bundle export --trust-domain wakir.test --out /tmp/x``
  2) ``spire-fed-bundle import --from-file /tmp/x --as-trust-domain wakir.test
        --out /tmp/y``
  3) Assert /tmp/x and /tmp/y are bit-identical (canonical-JSON
     round-trip).
  4) Cross-import: import a wakir.test JWKS as partner.test must FAIL
     (trust-domain mismatch guard).

These tests are hermetic and exercise the CLI Python module directly
via ``main([...])`` — no subprocess, no podman, no live SPIRE.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
FED_DIR = HERE.parent
CLI_MODULE_PATH = FED_DIR / "bin" / "spire_fed_bundle.py"


@pytest.fixture(scope="module")
def cli():
    """Import the spire_fed_bundle module from its file path."""
    spec = importlib.util.spec_from_file_location(
        "spire_fed_bundle_cli", CLI_MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["spire_fed_bundle_cli"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------


def test_export_wakir_produces_jwks(cli, tmp_path: Path) -> None:
    out = tmp_path / "wakir.jwks"
    rc = cli.main(["export", "--trust-domain", "wakir.test", "--out", str(out)])
    assert rc == 0
    assert out.exists()
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    assert "keys" in doc
    assert isinstance(doc["keys"], list) and doc["keys"]
    jwk = doc["keys"][0]
    assert jwk["kty"] == "EC"
    assert jwk["crv"] == "P-256"
    assert "x" in jwk and "y" in jwk
    assert jwk["kid"] == "spiffe://wakir.test/spire/server/fixture-key"
    assert jwk["_wakir_trust_domain"] == "wakir.test"


def test_export_partner_produces_jwks(cli, tmp_path: Path) -> None:
    out = tmp_path / "partner.jwks"
    rc = cli.main(["export", "--trust-domain", "partner.test", "--out", str(out)])
    assert rc == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["keys"][0]["_wakir_trust_domain"] == "partner.test"


def test_export_wakir_and_partner_differ(cli, tmp_path: Path) -> None:
    w_out = tmp_path / "wakir.jwks"
    p_out = tmp_path / "partner.jwks"
    cli.main(["export", "--trust-domain", "wakir.test", "--out", str(w_out)])
    cli.main(["export", "--trust-domain", "partner.test", "--out", str(p_out)])
    # Different trust-domains MUST produce different key material
    # (deterministic seed includes trust-domain literal).
    assert w_out.read_bytes() != p_out.read_bytes()
    w_jwk = json.loads(w_out.read_text())["keys"][0]
    p_jwk = json.loads(p_out.read_text())["keys"][0]
    assert w_jwk["x"] != p_jwk["x"]
    assert w_jwk["y"] != p_jwk["y"]
    assert w_jwk["kid"] != p_jwk["kid"]


def test_export_is_deterministic(cli, tmp_path: Path) -> None:
    out_a = tmp_path / "a.jwks"
    out_b = tmp_path / "b.jwks"
    cli.main(["export", "--trust-domain", "wakir.test", "--out", str(out_a)])
    cli.main(["export", "--trust-domain", "wakir.test", "--out", str(out_b)])
    # Two exports for the same trust-domain must be bit-identical.
    assert out_a.read_bytes() == out_b.read_bytes()


# ---------------------------------------------------------------------
# Roundtrip
# ---------------------------------------------------------------------


def test_export_then_import_roundtrip(cli, tmp_path: Path) -> None:
    src = tmp_path / "src.jwks"
    dst = tmp_path / "dst.jwks"
    cli.main(["export", "--trust-domain", "wakir.test", "--out", str(src)])
    rc = cli.main(
        [
            "import",
            "--from-file",
            str(src),
            "--as-trust-domain",
            "wakir.test",
            "--out",
            str(dst),
        ]
    )
    assert rc == 0
    assert dst.exists()
    # Canonical-JSON roundtrip — bit-identical.
    assert src.read_bytes() == dst.read_bytes()


# ---------------------------------------------------------------------
# Trust-domain mismatch guard
# ---------------------------------------------------------------------


def test_import_with_wrong_trust_domain_rejects(cli, tmp_path: Path) -> None:
    src = tmp_path / "wakir.jwks"
    cli.main(["export", "--trust-domain", "wakir.test", "--out", str(src)])
    rc = cli.main(
        [
            "import",
            "--from-file",
            str(src),
            # WRONG — the file is a wakir.test bundle.
            "--as-trust-domain",
            "partner.test",
        ]
    )
    assert rc == 2, (
        "import with wrong as-trust-domain must fail with exit-code 2 "
        "(trust-domain mismatch guard)"
    )


def test_import_rejects_invalid_trust_domain(cli, tmp_path: Path) -> None:
    src = tmp_path / "wakir.jwks"
    cli.main(["export", "--trust-domain", "wakir.test", "--out", str(src)])
    rc = cli.main(
        [
            "import",
            "--from-file",
            str(src),
            "--as-trust-domain",
            "Has-Uppercase.test",  # invalid: uppercase
        ]
    )
    assert rc == 2


def test_import_rejects_malformed_jwks(cli, tmp_path: Path) -> None:
    bad = tmp_path / "bad.jwks"
    bad.write_text('{"not-keys": []}', encoding="utf-8")
    rc = cli.main(
        [
            "import",
            "--from-file",
            str(bad),
            "--as-trust-domain",
            "wakir.test",
        ]
    )
    assert rc == 2


def test_import_rejects_empty_keys_array(cli, tmp_path: Path) -> None:
    bad = tmp_path / "empty.jwks"
    bad.write_text('{"keys": []}', encoding="utf-8")
    rc = cli.main(
        [
            "import",
            "--from-file",
            str(bad),
            "--as-trust-domain",
            "wakir.test",
        ]
    )
    assert rc == 2


def test_import_rejects_jwk_missing_required_field(cli, tmp_path: Path) -> None:
    bad = tmp_path / "missing.jwks"
    # Missing 'y' coordinate.
    bad.write_text(
        json.dumps(
            {"keys": [{"kty": "EC", "crv": "P-256", "x": "AAA", "kid": "k"}]}
        ),
        encoding="utf-8",
    )
    rc = cli.main(
        [
            "import",
            "--from-file",
            str(bad),
            "--as-trust-domain",
            "wakir.test",
        ]
    )
    assert rc == 2


# ---------------------------------------------------------------------
# Cross-trust-domain bundle roundtrip — the Sprint-8 Tag-1 X.509-SVID
# cross-trust verify SUBSTRATE (hermetic; live verify is Operator-Hand)
# ---------------------------------------------------------------------


def test_cross_trust_domain_roundtrip(cli, tmp_path: Path) -> None:
    """Wakir exports → partner imports → partner exports → wakir imports.

    This is the Sprint-8 Tag-1 acceptance roundtrip in hermetic form:
    each side exports its own JWKS, the operator (or automation) copies
    the JWKS across, the peer imports it as its peer-trust-anchor.
    Live cross-trust X.509-SVID verify is documented in README §3
    (Operator-Hand-pendet from sandbox).
    """
    wakir_src = tmp_path / "wakir.jwks"
    wakir_at_partner = tmp_path / "wakir-imported-at-partner.jwks"
    partner_src = tmp_path / "partner.jwks"
    partner_at_wakir = tmp_path / "partner-imported-at-wakir.jwks"

    # Wakir → Partner
    rc1 = cli.main(["export", "--trust-domain", "wakir.test", "--out", str(wakir_src)])
    rc2 = cli.main(
        [
            "import",
            "--from-file",
            str(wakir_src),
            "--as-trust-domain",
            "wakir.test",
            "--out",
            str(wakir_at_partner),
        ]
    )
    assert rc1 == 0 and rc2 == 0
    assert wakir_src.read_bytes() == wakir_at_partner.read_bytes()

    # Partner → Wakir
    rc3 = cli.main(
        ["export", "--trust-domain", "partner.test", "--out", str(partner_src)]
    )
    rc4 = cli.main(
        [
            "import",
            "--from-file",
            str(partner_src),
            "--as-trust-domain",
            "partner.test",
            "--out",
            str(partner_at_wakir),
        ]
    )
    assert rc3 == 0 and rc4 == 0
    assert partner_src.read_bytes() == partner_at_wakir.read_bytes()

    # Both peers now hold each other's bundles — the X.509-SVID cross-
    # trust verify (live) operates on these files as the bootstrap
    # trust-anchor.
