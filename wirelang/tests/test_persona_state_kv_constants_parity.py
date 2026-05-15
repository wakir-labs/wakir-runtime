# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Parity tests for the persona-state KV constants-only shim
(Sprint-Pengine-7 Tag-5 OI-PILOT-2 + Reza Cross-Review Zone-B B-5).

The shim ``wirelang.persona.persona_state_kv_constants`` is the
crypto-free import surface for the provisioner driver
``bin/nats_kv_bucket_provision.py``. Its public surface MUST be
byte-equal to the corresponding names in the full module
``wirelang.persona.persona_state_kv``; otherwise a drift in the
shim silently breaks the persona-state bucket provisioning on the
wakir-provisioner image (Tag-4 Bug-6 pattern, recurrence avoidance).

The tests below run in the hermetic test environment where
``rfc8785`` IS installed, so both modules import cleanly. The
sandbox-import semantics (shim crypto-free under the wakir-
provisioner wheel-set) are covered by
``wirelang/tests/test_identity_lazy_crypto_imports.py::test_bucket_provisioner_module_imports_crypto_free``
and its sibling persona-engine variant in this file (T-PSC-04).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


_REPO_ROOT = str(Path(__file__).resolve().parents[2])


def _run_isolated(code: str) -> tuple[int, str, str]:
    """Run a Python snippet in a fresh child interpreter; return
    ``(returncode, stdout, stderr)``.
    """
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


# ---------------------------------------------------------------------------
# T-PSC-01..03 — public-surface byte parity between shim and full module
# ---------------------------------------------------------------------------


def test_bucket_name_prefix_byte_equal() -> None:
    """T-PSC-01: ``BUCKET_NAME_PREFIX`` is byte-equal in both modules."""
    from wirelang.persona.persona_state_kv_constants import (
        BUCKET_NAME_PREFIX as shim_prefix,
    )
    from wirelang.persona.persona_state_kv import (
        BUCKET_NAME_PREFIX as full_prefix,
    )
    assert shim_prefix == full_prefix
    assert shim_prefix == "wakir-persona-state-"


def test_bucket_config_byte_equal() -> None:
    """T-PSC-02: ``BUCKET_CONFIG`` mapping is field-by-field equal."""
    from wirelang.persona.persona_state_kv_constants import (
        BUCKET_CONFIG as shim_config,
    )
    from wirelang.persona.persona_state_kv import (
        BUCKET_CONFIG as full_config,
    )
    assert dict(shim_config) == dict(full_config), (
        f"BUCKET_CONFIG drift: shim={dict(shim_config)!r} vs "
        f"full={dict(full_config)!r}"
    )


def test_bucket_name_for_org_round_trip_equal() -> None:
    """T-PSC-03: ``bucket_name_for_org`` returns the same string for
    the same input on both modules.
    """
    from wirelang.persona.persona_state_kv_constants import (
        bucket_name_for_org as shim_fn,
    )
    from wirelang.persona.persona_state_kv import (
        bucket_name_for_org as full_fn,
    )
    for combined in ("acme-tomas", "orbit-mira", "acme-priya"):
        assert shim_fn(combined) == full_fn(combined)

    # Validation drift would also be a parity bug; assert both raise
    # on the same malformed inputs.
    #
    # - empty string fails the non-empty guard.
    # - leading-underscore fails the regex (first char must be [A-Za-z0-9]).
    # - no-hyphen token fails the explicit '-' presence guard.
    for malformed in ("", "_leading-underscore", "missingHyphenToken"):
        with pytest.raises(ValueError):
            shim_fn(malformed)
        with pytest.raises(ValueError):
            full_fn(malformed)


# ---------------------------------------------------------------------------
# T-PSC-04 — sandbox-import semantics: shim is crypto-free
# ---------------------------------------------------------------------------


def test_constants_shim_imports_without_rfc8785_or_cryptography() -> None:
    """T-PSC-04: ``import wirelang.persona.persona_state_kv_constants``
    in a child interpreter where ``rfc8785`` and ``cryptography`` are
    finder-blocked MUST succeed and expose the three driver-facing
    names.

    This is the Sprint-Pengine-7 Tag-5 Reza-Cross-Review Zone-B B-5
    acceptance: the persona-state family populates on the wakir-
    provisioner image (wheel-set without ``rfc8785``).
    """
    rc, out, err = _run_isolated(
        """
        import sys

        class _Blocker:
            def find_spec(self, name, path, target=None):
                if name == 'rfc8785' or name.startswith('rfc8785.'):
                    raise ImportError('blocked: ' + name)
                if name == 'cryptography' or name.startswith('cryptography.'):
                    raise ImportError('blocked: ' + name)
                return None

        sys.meta_path.insert(0, _Blocker())
        sys.path.insert(0, %r)

        from wirelang.persona import persona_state_kv_constants as shim

        # Probe sandbox semantics: neither rfc8785 nor cryptography
        # may be present in sys.modules.
        crypto_loaded = any(
            k == 'cryptography' or k.startswith('cryptography.')
            for k in sys.modules
        )
        rfc_loaded = any(
            k == 'rfc8785' or k.startswith('rfc8785.')
            for k in sys.modules
        )
        print('crypto_loaded', crypto_loaded)
        print('rfc_loaded', rfc_loaded)
        print('prefix', shim.BUCKET_NAME_PREFIX)
        print('bucket', shim.bucket_name_for_org('acme-tomas'))
        print('history', shim.BUCKET_CONFIG['history'])
        """ % _REPO_ROOT
    )
    assert rc == 0, f"child exited {rc}: stderr={err}"
    assert "crypto_loaded False" in out, out
    assert "rfc_loaded False" in out, out
    assert "prefix wakir-persona-state-" in out, out
    assert "bucket wakir-persona-state-acme-tomas" in out, out
    assert "history 1" in out, out


def test_provisioner_with_constants_shim_lists_three_families() -> None:
    """T-PSC-05: with the constants-only shim present and rfc8785 /
    cryptography blocked, the provisioner driver MUST register the
    persona-state family alongside marker-stack and sequence-ledger
    (family-count = 3).

    This re-asserts the Tag-5 expected end-state described in
    ``test_identity_lazy_crypto_imports.test_bucket_provisioner_module_imports_crypto_free``
    (Kai-Drift-Guard, ``family_count >= 2 and family_count <= 3``)
    on the strict-equality axis once the shim is in tree.
    """
    rc, out, err = _run_isolated(
        """
        import sys

        class _Blocker:
            def find_spec(self, name, path, target=None):
                if name == 'rfc8785' or name.startswith('rfc8785.'):
                    raise ImportError('blocked: ' + name)
                if name == 'cryptography' or name.startswith('cryptography.'):
                    raise ImportError('blocked: ' + name)
                return None

        sys.meta_path.insert(0, _Blocker())
        sys.path.insert(0, %r)

        import bin.nats_kv_bucket_provision as m

        print('families', len(m.BUCKET_FAMILIES))
        for fam in m.BUCKET_FAMILIES:
            print('family', fam.family_id, fam.bucket_name_prefix)
        """ % _REPO_ROOT
    )
    assert rc == 0, f"child exited {rc}: stderr={err}"
    assert "families 3" in out, out
    assert "family persona-state wakir-persona-state-" in out, out
    assert "family marker-stack wakir-marker-stack-" in out, out
