# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic acceptance tests for the Phase-2 Sprint-8 Tag-3
``spire-agent-fed-reload`` helper.

Coverage:

  * Snapshot determinism: bit-identical bundle yields identical
    snapshot.
  * Change-detection: rotator-output vs. pre-rotation snapshot
    produces an ``added`` set.
  * Expire-detection: post-expire snapshot vs. mid-grace snapshot
    produces a ``removed`` set.
  * Cron-cycle ``step_loop``: drives a single iteration without
    wall-clock sleep; updates the snapshot on change.
  * Race-condition (malformed read mid-write): poll_once raises on
    partial JWKS; loop counts the error and keeps the previous
    snapshot intact.
  * SIGHUP-style operator-hand trigger: simulate by calling
    ``step_loop`` directly out-of-cycle — the cache-refresh is
    immediate.
  * CLI ``snapshot`` and ``poll-once`` subcommands emit valid JSON.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
AGENT_DIR = HERE.parent
RELOAD_PATH = AGENT_DIR / "bin" / "spire_agent_fed_reload.py"
FED_BUNDLE_PATH = (
    AGENT_DIR.parent / "federation" / "bin" / "spire_fed_bundle.py"
)
ROTATOR_PATH = (
    AGENT_DIR.parent / "federation" / "bin" / "spire_fed_bundle_rotator.py"
)


@pytest.fixture(scope="module")
def reload_mod():
    spec = importlib.util.spec_from_file_location(
        "spire_agent_fed_reload", RELOAD_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["spire_agent_fed_reload"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def fed_bundle():
    spec = importlib.util.spec_from_file_location(
        "spire_fed_bundle", FED_BUNDLE_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["spire_fed_bundle"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rotator():
    spec = importlib.util.spec_from_file_location(
        "spire_fed_bundle_rotator", ROTATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["spire_fed_bundle_rotator"] = mod
    spec.loader.exec_module(mod)
    return mod


T0 = "2026-05-13T00:00:00+00:00"
T0_PLUS_25H = "2026-05-14T01:00:00+00:00"
GRACE_24H = 86400


def _export(fed_bundle, td: str, dst: Path) -> Path:
    fed_bundle.main(["export", "--trust-domain", td, "--out", str(dst)])
    return dst


def _rotate(rotator, td: str, src: Path, dst: Path, now: str) -> Path:
    rc = rotator.main(
        [
            "rotate",
            "--trust-domain", td,
            "--in-file", str(src),
            "--out", str(dst),
            "--now", now,
            "--grace-seconds", str(GRACE_24H),
        ]
    )
    assert rc == 0
    return dst


# ---------------------------------------------------------------------
# 1. Snapshot determinism
# ---------------------------------------------------------------------


def test_snapshot_is_deterministic(
    reload_mod, fed_bundle, tmp_path: Path
) -> None:
    src = _export(fed_bundle, "wakir.test", tmp_path / "v1.jwks")
    snap_a = reload_mod.snapshot_bundle(src)
    snap_b = reload_mod.snapshot_bundle(src)
    assert snap_a == snap_b


# ---------------------------------------------------------------------
# 2. Different bundles → different content_hash
# ---------------------------------------------------------------------


def test_different_bundles_distinguishable(
    reload_mod, fed_bundle, tmp_path: Path
) -> None:
    wakir = _export(fed_bundle, "wakir.test", tmp_path / "w.jwks")
    partner = _export(fed_bundle, "partner.test", tmp_path / "p.jwks")
    snap_w = reload_mod.snapshot_bundle(wakir)
    snap_p = reload_mod.snapshot_bundle(partner)
    assert snap_w.content_hash != snap_p.content_hash
    assert snap_w.kids != snap_p.kids


# ---------------------------------------------------------------------
# 3. Change-detection on rotate
# ---------------------------------------------------------------------


def test_rotate_produces_added_kid(
    reload_mod, fed_bundle, rotator, tmp_path: Path
) -> None:
    v1 = _export(fed_bundle, "wakir.test", tmp_path / "v1.jwks")
    snap_v1 = reload_mod.snapshot_bundle(v1)
    v2 = _rotate(rotator, "wakir.test", v1, tmp_path / "v2.jwks", T0)
    change = reload_mod.poll_once(v2, snap_v1)
    assert change.changed
    assert len(change.added) == 1, (
        f"rotate must add exactly one kid; got added={change.added}"
    )
    assert len(change.removed) == 0, (
        "rotate must NOT remove any kid during soft-cutover"
    )
    # The added kid is the rot1 generation.
    added_kid = next(iter(change.added))
    assert "rot1" in added_kid


# ---------------------------------------------------------------------
# 4. Change-detection on expire
# ---------------------------------------------------------------------


def test_expire_produces_removed_kid(
    reload_mod, fed_bundle, rotator, tmp_path: Path
) -> None:
    v1 = _export(fed_bundle, "wakir.test", tmp_path / "v1.jwks")
    v2 = _rotate(rotator, "wakir.test", v1, tmp_path / "v2.jwks", T0)
    snap_v2 = reload_mod.snapshot_bundle(v2)

    v3 = tmp_path / "v3.jwks"
    rotator.main(
        [
            "expire",
            "--trust-domain", "wakir.test",
            "--in-file", str(v2),
            "--out", str(v3),
            "--now", T0_PLUS_25H,
        ]
    )
    change = reload_mod.poll_once(v3, snap_v2)
    assert change.changed
    assert len(change.removed) == 1, (
        f"expire must remove exactly the old kid; got removed={change.removed}"
    )
    assert len(change.added) == 0


# ---------------------------------------------------------------------
# 5. Cron-cycle step_loop
# ---------------------------------------------------------------------


def test_step_loop_records_change_iteration(
    reload_mod, fed_bundle, rotator, tmp_path: Path
) -> None:
    bundle_path = tmp_path / "live.jwks"
    _export(fed_bundle, "wakir.test", bundle_path)
    state = reload_mod.ReloadLoopState(
        path=bundle_path, interval_seconds=3600.0
    )

    captured: list = []
    change_a = reload_mod.step_loop(
        state, on_change=lambda c: captured.append(c)
    )
    assert change_a is not None, "first poll must detect content"
    assert state.iterations == 1
    assert state.changes == 1
    assert len(captured) == 1

    # Second iteration without filesystem change → no transition.
    change_b = reload_mod.step_loop(
        state, on_change=lambda c: captured.append(c)
    )
    assert change_b is None, "no fs change → no transition"
    assert state.iterations == 2
    assert state.changes == 1, (
        "unchanged bundle must NOT bump the changes counter"
    )

    # Operator rotates between iterations.
    _rotate(rotator, "wakir.test", bundle_path, bundle_path, T0)
    change_c = reload_mod.step_loop(
        state, on_change=lambda c: captured.append(c)
    )
    assert change_c is not None
    assert state.iterations == 3
    assert state.changes == 2


# ---------------------------------------------------------------------
# 6. Race-condition: malformed JWKS mid-write
# ---------------------------------------------------------------------


def test_step_loop_handles_malformed_bundle(
    reload_mod, tmp_path: Path
) -> None:
    """Simulate the operator-hand non-atomic write window where the
    bundle file is mid-flight (partial JSON). The loop MUST NOT
    crash; it MUST count the error and KEEP the previous snapshot.
    """
    bundle_path = tmp_path / "live.jwks"
    bundle_path.write_text(
        '{"keys": [{"kty": "EC", "crv": "P-256", "x": "AA", "y": "BB", '
        '"kid": "first"}]}\n',
        encoding="utf-8",
    )
    state = reload_mod.ReloadLoopState(
        path=bundle_path, interval_seconds=3600.0
    )
    reload_mod.step_loop(state)
    pre_error_snapshot = state.snapshot

    # Simulate mid-write truncation.
    bundle_path.write_text('{"keys": [', encoding="utf-8")
    errors: list[Exception] = []
    change = reload_mod.step_loop(
        state, on_error=lambda e: errors.append(e)
    )
    assert change is None
    assert state.errors == 1
    assert state.snapshot == pre_error_snapshot, (
        "malformed read must NOT poison the cache; previous snapshot kept"
    )
    assert len(errors) == 1


def test_step_loop_handles_missing_file(reload_mod, tmp_path: Path) -> None:
    """File-not-found is a recoverable error (e.g. operator-hand
    rm-then-write between cycles)."""
    bundle_path = tmp_path / "missing.jwks"
    state = reload_mod.ReloadLoopState(
        path=bundle_path, interval_seconds=3600.0
    )
    errors: list[Exception] = []
    reload_mod.step_loop(state, on_error=lambda e: errors.append(e))
    assert state.errors == 1
    assert isinstance(errors[0], FileNotFoundError)


# ---------------------------------------------------------------------
# 7. SIGHUP-style operator-hand trigger
# ---------------------------------------------------------------------


def test_sighup_style_immediate_trigger(
    reload_mod, fed_bundle, rotator, tmp_path: Path
) -> None:
    """SIGHUP-pattern: out-of-cycle ``step_loop`` invocation refreshes
    the snapshot immediately, without waiting for the next interval.

    The hermetic test demonstrates this by calling step_loop twice in
    rapid succession across an in-cycle rotation.
    """
    bundle_path = tmp_path / "live.jwks"
    _export(fed_bundle, "wakir.test", bundle_path)
    state = reload_mod.ReloadLoopState(
        path=bundle_path, interval_seconds=99999.0  # long cron cadence
    )
    reload_mod.step_loop(state)  # initial snapshot
    snap_initial = state.snapshot

    # Operator rotates the bundle and signals SIGHUP — simulated by
    # an immediate out-of-cycle step_loop call.
    _rotate(rotator, "wakir.test", bundle_path, bundle_path, T0)
    change = reload_mod.step_loop(state)

    assert change is not None, "SIGHUP-style trigger must refresh immediately"
    assert state.snapshot != snap_initial
    assert state.snapshot.n_keys == 2


# ---------------------------------------------------------------------
# 8. run_loop with injected sleep (max_iterations)
# ---------------------------------------------------------------------


def test_run_loop_respects_max_iterations(
    reload_mod, fed_bundle, tmp_path: Path
) -> None:
    bundle_path = tmp_path / "live.jwks"
    _export(fed_bundle, "wakir.test", bundle_path)
    sleeps: list[float] = []
    state = reload_mod.ReloadLoopState(
        path=bundle_path, interval_seconds=1.5
    )
    reload_mod.run_loop(
        state,
        max_iterations=3,
        sleep=lambda s: sleeps.append(s),
    )
    assert state.iterations == 3
    # sleep called BETWEEN iterations — 2 calls for 3 iterations.
    assert sleeps == [1.5, 1.5]


# ---------------------------------------------------------------------
# 9. Cross-trust-domain isolation in the reload helper
# ---------------------------------------------------------------------


def test_reload_helper_treats_trust_domains_independently(
    reload_mod, fed_bundle, rotator, tmp_path: Path
) -> None:
    wakir = _export(fed_bundle, "wakir.test", tmp_path / "wakir.jwks")
    partner = _export(fed_bundle, "partner.test", tmp_path / "partner.jwks")
    wakir_state = reload_mod.ReloadLoopState(
        path=wakir, interval_seconds=3600.0
    )
    partner_state = reload_mod.ReloadLoopState(
        path=partner, interval_seconds=3600.0
    )
    reload_mod.step_loop(wakir_state)
    reload_mod.step_loop(partner_state)

    # Rotate wakir.test ONLY.
    _rotate(rotator, "wakir.test", wakir, wakir, T0)
    reload_mod.step_loop(wakir_state)
    reload_mod.step_loop(partner_state)

    assert wakir_state.changes == 2, "wakir state must record 2 changes"
    assert partner_state.changes == 1, (
        "partner state must NOT record an extra change after a wakir-only "
        "rotation"
    )


# ---------------------------------------------------------------------
# 10. snapshot CLI subcommand
# ---------------------------------------------------------------------


def test_cli_snapshot_emits_json(
    reload_mod, fed_bundle, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    bundle_path = _export(fed_bundle, "wakir.test", tmp_path / "v1.jwks")
    rc = reload_mod.main(["snapshot", "--bundle-path", str(bundle_path)])
    assert rc == 0
    out = capsys.readouterr().out
    doc = json.loads(out)
    assert "content_hash" in doc
    assert "kids" in doc
    assert "rotation_counters" in doc
    assert doc["n_keys"] == 1


# ---------------------------------------------------------------------
# 11. poll-once CLI subcommand
# ---------------------------------------------------------------------


def test_cli_poll_once_emits_change_descriptor(
    reload_mod, fed_bundle, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    bundle_path = _export(fed_bundle, "wakir.test", tmp_path / "v1.jwks")
    rc = reload_mod.main(["poll-once", "--bundle-path", str(bundle_path)])
    assert rc == 0
    out = capsys.readouterr().out
    doc = json.loads(out)
    assert doc["unchanged"] is False, "poll-once vs. empty cache is a change"
    assert len(doc["added"]) == 1
    assert doc["removed"] == []


# ---------------------------------------------------------------------
# 12. CLI rejects missing bundle file
# ---------------------------------------------------------------------


def test_cli_rejects_missing_bundle(
    reload_mod, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    rc = reload_mod.main(
        ["snapshot", "--bundle-path", str(tmp_path / "nonexistent.jwks")]
    )
    assert rc == 2


# ---------------------------------------------------------------------
# 13. CLI rejects malformed JWKS
# ---------------------------------------------------------------------


def test_cli_rejects_malformed_jwks(
    reload_mod, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    bad = tmp_path / "bad.jwks"
    bad.write_text("{not-json", encoding="utf-8")
    rc = reload_mod.main(["snapshot", "--bundle-path", str(bad)])
    assert rc == 2
