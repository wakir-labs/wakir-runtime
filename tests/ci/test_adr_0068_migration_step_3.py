# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic tests for the ADR-0068 Migration-Step-3 cutover script.

Covers:

  * Gate 1 (drift): pass when drift_event_count=0 and sample_count
    >= min; fail on non-zero drift, missing fields, bad types, or
    too-few samples.
  * Gate 2 (time): pass after >= min_days since approval; fail
    before.
  * Gate 3 (operator): pass on env=1 or CLI flag; fail when both
    missing.
  * Aggregate ``evaluate_all_gates`` returns ``all_passed``
    conjunction.
  * ``build_cutover_plan`` produces a deterministic backup path.
  * ``build_patch_payload`` produces the correct PATCH body.
  * ``build_backup_document`` round-trips through
    ``build_rollback_payload``.
  * ``build_rollback_payload`` rejects schema-mismatched / empty
    backups.
  * End-to-end ``main()`` dry-run via fixtures, with stdout
    capture.
  * End-to-end ``main()`` rollback via fixture backup, in
    apply-mocked mode.

Sandbox boundary: no network calls. ``fetch_current_protection``
and ``apply_patch`` are stubbed via monkeypatch where necessary,
or sidestepped by the ``--fixture-current-protection`` /
``--dry-run`` modes.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import io
import json
import pathlib
import sys

import pytest


# ---------------------------------------------------------------------------
# Module loader (file name contains hyphens, so we can't `import` it)
# ---------------------------------------------------------------------------


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "ci" / "adr-0068-migration-step-3-cutover.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "adr_0068_migration_step_3_cutover", _SCRIPT_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"could not load module spec from {_SCRIPT_PATH}"
        )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def cutover():
    return _load_module()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _tracker_payload(
    *,
    drift_event_count: int = 0,
    ci_aggregator_sample_count: int = 52,
    include_ci_aggregator_rollup: bool = True,
) -> dict:
    rollups = []
    if include_ci_aggregator_rollup:
        rollups.append(
            {
                "check_name": "ci-aggregator",
                "windows": {
                    "50": {
                        "window_size": 50,
                        "sample_count": min(
                            ci_aggregator_sample_count, 50
                        ),
                        "failure_count": 0,
                        "success_count": min(
                            ci_aggregator_sample_count, 50
                        ),
                        "skipped_count": 0,
                        "failure_rate": 0.0,
                        "latency_p50_seconds": 12.5,
                        "latency_p95_seconds": 30.0,
                        "latency_p99_seconds": 45.0,
                    },
                    "100": {
                        "window_size": 100,
                        "sample_count": ci_aggregator_sample_count,
                        "failure_count": 0,
                        "success_count": ci_aggregator_sample_count,
                        "skipped_count": 0,
                        "failure_rate": 0.0,
                        "latency_p50_seconds": 12.5,
                        "latency_p95_seconds": 30.0,
                        "latency_p99_seconds": 45.0,
                    },
                },
            }
        )
    return {
        "schema_version": 1,
        "anchor": "ADR-0068 Migration-Step-2",
        "timestamp_unixtime": 1747500000.0,
        "rollups": rollups,
        "drift_events": [],
        "summary": {
            "rollup_count": len(rollups),
            "drift_event_count": drift_event_count,
        },
    }


# ---------------------------------------------------------------------------
# Gate 1 (drift)
# ---------------------------------------------------------------------------


def test_gate_drift_passes_when_zero_drift_and_enough_samples(cutover):
    payload = _tracker_payload(
        drift_event_count=0, ci_aggregator_sample_count=52
    )
    r = cutover.gate_drift(payload, min_clean_runs=50)
    assert r.name == "drift"
    assert r.passed is True
    assert "drift_event_count=0" in r.detail
    assert "52 runs" in r.detail


def test_gate_drift_fails_when_drift_nonzero(cutover):
    payload = _tracker_payload(drift_event_count=3)
    r = cutover.gate_drift(payload)
    assert r.passed is False
    assert "drift_event_count=3" in r.detail
    assert "unsafe" in r.detail.lower()


def test_gate_drift_fails_when_drift_count_missing(cutover):
    payload = _tracker_payload()
    del payload["summary"]["drift_event_count"]
    r = cutover.gate_drift(payload)
    assert r.passed is False
    assert "missing" in r.detail


def test_gate_drift_fails_when_drift_count_bad_type(cutover):
    payload = _tracker_payload()
    payload["summary"]["drift_event_count"] = "0"  # str, not int
    r = cutover.gate_drift(payload)
    assert r.passed is False
    assert "expected int" in r.detail


def test_gate_drift_fails_when_sample_count_too_low(cutover):
    payload = _tracker_payload(
        drift_event_count=0, ci_aggregator_sample_count=10
    )
    r = cutover.gate_drift(payload, min_clean_runs=50)
    assert r.passed is False
    assert "sample_count=10" in r.detail
    assert "min 50" in r.detail


def test_gate_drift_fails_when_aggregator_rollup_absent(cutover):
    payload = _tracker_payload(include_ci_aggregator_rollup=False)
    r = cutover.gate_drift(payload)
    assert r.passed is False
    assert "no rollup" in r.detail


# ---------------------------------------------------------------------------
# Gate 2 (time)
# ---------------------------------------------------------------------------


def test_gate_time_fails_on_approval_day(cutover):
    r = cutover.gate_time(
        dt.date(2026, 5, 18),
        approval_date=dt.date(2026, 5, 18),
        min_days=7,
    )
    assert r.passed is False
    assert "0 day" in r.detail


def test_gate_time_fails_six_days_after(cutover):
    r = cutover.gate_time(
        dt.date(2026, 5, 24),
        approval_date=dt.date(2026, 5, 18),
        min_days=7,
    )
    assert r.passed is False
    assert "6 day" in r.detail


def test_gate_time_passes_at_exactly_seven_days(cutover):
    r = cutover.gate_time(
        dt.date(2026, 5, 25),
        approval_date=dt.date(2026, 5, 18),
        min_days=7,
    )
    assert r.passed is True
    assert "7 day" in r.detail


def test_gate_time_passes_well_after(cutover):
    r = cutover.gate_time(
        dt.date(2026, 6, 18),
        approval_date=dt.date(2026, 5, 18),
        min_days=7,
    )
    assert r.passed is True


# ---------------------------------------------------------------------------
# Gate 3 (operator)
# ---------------------------------------------------------------------------


def test_gate_operator_fails_when_unauthorized(cutover):
    r = cutover.gate_operator(env_flag=None, cli_flag=False)
    assert r.passed is False
    assert "no operator authorization" in r.detail


def test_gate_operator_passes_via_env(cutover):
    r = cutover.gate_operator(env_flag="1", cli_flag=False)
    assert r.passed is True
    assert "env(MIRA_HAND_AUTHORIZED=1)" in r.detail


def test_gate_operator_passes_via_cli(cutover):
    r = cutover.gate_operator(env_flag=None, cli_flag=True)
    assert r.passed is True
    assert "cli(--mira-hand-authorized)" in r.detail


def test_gate_operator_env_wrong_value_fails(cutover):
    r = cutover.gate_operator(env_flag="yes", cli_flag=False)
    # We accept only "1" by design (avoids accidental "true"/"yes"
    # values from CI matrices).
    assert r.passed is False


# ---------------------------------------------------------------------------
# Aggregate evaluate_all_gates
# ---------------------------------------------------------------------------


def test_evaluate_all_gates_all_pass(cutover):
    payload = _tracker_payload()
    rep = cutover.evaluate_all_gates(
        payload,
        now=dt.date(2026, 5, 26),
        env_flag="1",
        cli_flag=False,
    )
    assert rep.all_passed is True
    assert {g.name for g in rep.gates} == {"drift", "time", "operator"}


def test_evaluate_all_gates_short_circuits_on_time(cutover):
    payload = _tracker_payload()
    rep = cutover.evaluate_all_gates(
        payload,
        now=dt.date(2026, 5, 19),  # 1 day after approval
        env_flag="1",
        cli_flag=False,
    )
    # Drift + operator still pass, only time fails -- so all_passed
    # is False. The aggregate is a conjunction, not a short-circuit.
    assert rep.all_passed is False
    by_name = {g.name: g for g in rep.gates}
    assert by_name["drift"].passed is True
    assert by_name["time"].passed is False
    assert by_name["operator"].passed is True


# ---------------------------------------------------------------------------
# Cutover plan + patch payload
# ---------------------------------------------------------------------------


def test_build_cutover_plan_backup_path_format(cutover, tmp_path):
    # 2026-05-25T12:00:00Z -> 1779710400
    plan = cutover.build_cutover_plan(
        repo="wakir-labs/wakir-runtime",
        pre_contexts=("a", "b", "c"),
        backup_dir=tmp_path,
        timestamp_unixtime=1779710400.0,
    )
    assert plan.pre_contexts == ("a", "b", "c")
    assert plan.post_contexts == ("ci-aggregator",)
    assert plan.backup_path.name == (
        "branch-protection-pre-migration-20260525T120000Z.json"
    )


def test_build_patch_payload_targets_ci_aggregator(cutover):
    p = cutover.build_patch_payload(("ci-aggregator",))
    assert p == {
        "required_status_checks": {
            "strict": True,
            "contexts": ["ci-aggregator"],
        }
    }


def test_build_backup_document_round_trip(cutover):
    pre_protection = {
        "required_status_checks": {
            "strict": True,
            "contexts": [
                "License-Hygiene Gate (ADR-0061)",
                "wirelang suite with rfc8785 + jsonschema",
                "cross-repo drift (wakir-runtime <-> wakir-protocol)",
            ],
        }
    }
    doc = cutover.build_backup_document(
        repo="wakir-labs/wakir-runtime",
        pre_protection=pre_protection,
        timestamp_unixtime=1779710400.0,
    )
    assert doc["schema_version"] == 1
    assert doc["repo"] == "wakir-labs/wakir-runtime"
    assert doc["required_status_checks"]["contexts"] == [
        "License-Hygiene Gate (ADR-0061)",
        "wirelang suite with rfc8785 + jsonschema",
        "cross-repo drift (wakir-runtime <-> wakir-protocol)",
    ]
    # Round-trip via build_rollback_payload.
    payload = cutover.build_rollback_payload(doc)
    assert payload["required_status_checks"]["contexts"] == doc[
        "required_status_checks"
    ]["contexts"]
    assert payload["required_status_checks"]["strict"] is True


def test_build_rollback_payload_rejects_wrong_schema(cutover):
    with pytest.raises(ValueError, match="schema_version"):
        cutover.build_rollback_payload({"schema_version": 99})


def test_build_rollback_payload_rejects_empty_contexts(cutover):
    with pytest.raises(ValueError, match="empty"):
        cutover.build_rollback_payload(
            {
                "schema_version": 1,
                "required_status_checks": {
                    "strict": True,
                    "contexts": [],
                },
            }
        )


# ---------------------------------------------------------------------------
# End-to-end main() via fixtures
# ---------------------------------------------------------------------------


def _write_tracker_fixture(tmp_path: pathlib.Path) -> pathlib.Path:
    path = tmp_path / "tracker.json"
    path.write_text(json.dumps(_tracker_payload()))
    return path


def _write_protection_fixture(tmp_path: pathlib.Path) -> pathlib.Path:
    path = tmp_path / "protection.json"
    payload = {
        "required_status_checks": {
            "strict": True,
            "contexts": [
                "License-Hygiene Gate (ADR-0061)",
                "wirelang suite with rfc8785 + jsonschema",
                "cross-repo drift (wakir-runtime <-> wakir-protocol)",
            ],
        }
    }
    path.write_text(json.dumps(payload))
    return path


def test_main_dry_run_all_gates_pass(cutover, tmp_path, capsys):
    tracker_path = _write_tracker_fixture(tmp_path)
    protection_path = _write_protection_fixture(tmp_path)
    backup_dir = tmp_path / "backup"

    rc = cutover.main(
        [
            "--dry-run",
            "--tracker-json",
            str(tracker_path),
            "--fixture-current-protection",
            str(protection_path),
            "--backup-dir",
            str(backup_dir),
            "--now",
            "2026-05-26",
            "--mira-hand-authorized",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "ALL GATES PASSED" in out
    assert "ci-aggregator" in out
    # Dry-run must NOT write a backup.
    assert not backup_dir.exists()


def test_main_dry_run_fails_on_drift(cutover, tmp_path, capsys):
    tracker_path = tmp_path / "tracker.json"
    tracker_path.write_text(
        json.dumps(_tracker_payload(drift_event_count=2))
    )
    protection_path = _write_protection_fixture(tmp_path)

    rc = cutover.main(
        [
            "--dry-run",
            "--tracker-json",
            str(tracker_path),
            "--fixture-current-protection",
            str(protection_path),
            "--now",
            "2026-05-26",
            "--mira-hand-authorized",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAIL" in out
    assert "drift_event_count=2" in out


def test_main_apply_refused_when_gate_fails(
    cutover, tmp_path, capsys, monkeypatch
):
    """Apply mode with a failing gate must NOT call apply_patch."""
    tracker_path = _write_tracker_fixture(tmp_path)
    protection_path = _write_protection_fixture(tmp_path)
    backup_dir = tmp_path / "backup"

    called = {"apply": False, "backup": False}

    def fake_apply(*args, **kwargs):
        called["apply"] = True
        return {}

    def fake_write_backup(*args, **kwargs):
        called["backup"] = True

    monkeypatch.setattr(cutover, "apply_patch", fake_apply)
    monkeypatch.setattr(cutover, "write_backup", fake_write_backup)

    rc = cutover.main(
        [
            "--apply",
            "--tracker-json",
            str(tracker_path),
            "--fixture-current-protection",
            str(protection_path),
            "--backup-dir",
            str(backup_dir),
            "--now",
            "2026-05-19",  # only 1 day after approval -> gate-time fail
            "--mira-hand-authorized",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "Refusing to --apply" in out
    assert called["apply"] is False
    assert called["backup"] is False


def test_main_apply_happy_path_writes_backup_and_patches(
    cutover, tmp_path, capsys, monkeypatch
):
    tracker_path = _write_tracker_fixture(tmp_path)
    protection_path = _write_protection_fixture(tmp_path)
    backup_dir = tmp_path / "backup"

    captured = {"patch_payload": None, "repo": None}

    def fake_apply(repo, payload, *, gh_path="gh"):
        captured["repo"] = repo
        captured["patch_payload"] = payload
        return {}

    monkeypatch.setattr(cutover, "apply_patch", fake_apply)

    rc = cutover.main(
        [
            "--apply",
            "--tracker-json",
            str(tracker_path),
            "--fixture-current-protection",
            str(protection_path),
            "--backup-dir",
            str(backup_dir),
            "--now",
            "2026-05-26",
            "--mira-hand-authorized",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "PATCH applied" in out
    assert captured["repo"] == "wakir-labs/wakir-runtime"
    assert captured["patch_payload"] == {
        "required_status_checks": {
            "strict": True,
            "contexts": ["ci-aggregator"],
        }
    }
    # Backup file exists and round-trips.
    backups = list(backup_dir.glob("branch-protection-pre-migration-*.json"))
    assert len(backups) == 1
    doc = json.loads(backups[0].read_text())
    assert doc["schema_version"] == 1
    assert doc["required_status_checks"]["contexts"] == [
        "License-Hygiene Gate (ADR-0061)",
        "wirelang suite with rfc8785 + jsonschema",
        "cross-repo drift (wakir-runtime <-> wakir-protocol)",
    ]


def test_main_apply_missing_operator_authorization_fails(
    cutover, tmp_path, capsys, monkeypatch
):
    tracker_path = _write_tracker_fixture(tmp_path)
    protection_path = _write_protection_fixture(tmp_path)
    backup_dir = tmp_path / "backup"

    called = {"apply": False}

    def fake_apply(*args, **kwargs):
        called["apply"] = True
        return {}

    monkeypatch.setattr(cutover, "apply_patch", fake_apply)
    monkeypatch.delenv("MIRA_HAND_AUTHORIZED", raising=False)

    rc = cutover.main(
        [
            "--apply",
            "--tracker-json",
            str(tracker_path),
            "--fixture-current-protection",
            str(protection_path),
            "--backup-dir",
            str(backup_dir),
            "--now",
            "2026-05-26",
            # NO --mira-hand-authorized, NO env var
        ]
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert called["apply"] is False
    assert "operator" in out.lower()


def test_main_rollback_restores_contexts(
    cutover, tmp_path, capsys, monkeypatch
):
    # Write a backup file by hand (simulating a previous --apply run).
    backup_path = tmp_path / "branch-protection-pre-migration-X.json"
    backup_doc = {
        "schema_version": 1,
        "anchor": "ADR-0068 Migration-Step-3",
        "timestamp_unixtime": 1779710400.0,
        "timestamp_iso": "2026-05-25T12:00:00+00:00",
        "repo": "wakir-labs/wakir-runtime",
        "required_status_checks": {
            "strict": True,
            "contexts": [
                "License-Hygiene Gate (ADR-0061)",
                "wirelang suite with rfc8785 + jsonschema",
                "cross-repo drift (wakir-runtime <-> wakir-protocol)",
            ],
        },
    }
    backup_path.write_text(json.dumps(backup_doc))

    captured = {"payload": None}

    def fake_apply(repo, payload, *, gh_path="gh"):
        captured["payload"] = payload
        return {}

    monkeypatch.setattr(cutover, "apply_patch", fake_apply)

    rc = cutover.main(
        [
            "--rollback",
            str(backup_path),
            "--mira-hand-authorized",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "rollback" in out.lower()
    assert captured["payload"] == {
        "required_status_checks": {
            "strict": True,
            "contexts": backup_doc["required_status_checks"]["contexts"],
        }
    }


def test_main_rollback_refuses_without_operator_authorization(
    cutover, tmp_path, capsys, monkeypatch
):
    backup_path = tmp_path / "backup.json"
    backup_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "required_status_checks": {
                    "strict": True,
                    "contexts": ["x"],
                },
            }
        )
    )
    called = {"apply": False}

    def fake_apply(*args, **kwargs):
        called["apply"] = True
        return {}

    monkeypatch.setattr(cutover, "apply_patch", fake_apply)
    monkeypatch.delenv("MIRA_HAND_AUTHORIZED", raising=False)

    rc = cutover.main(["--rollback", str(backup_path)])
    out = capsys.readouterr().out
    assert rc == 1
    assert called["apply"] is False
    assert "operator" in out.lower()


def test_main_rollback_rejects_missing_file(cutover, tmp_path, capsys):
    rc = cutover.main(
        [
            "--rollback",
            str(tmp_path / "nonexistent.json"),
            "--mira-hand-authorized",
        ]
    )
    err = capsys.readouterr().err
    assert rc == 2
    assert "not found" in err


def test_main_rollback_rejects_bad_json(cutover, tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    rc = cutover.main(
        [
            "--rollback",
            str(bad),
            "--mira-hand-authorized",
        ]
    )
    err = capsys.readouterr().err
    assert rc == 2
    assert "not valid JSON" in err


def test_main_dry_run_requires_tracker_json(cutover, capsys):
    rc = cutover.main(["--dry-run"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "--tracker-json" in err


# ---------------------------------------------------------------------------
# Atomic-backup write
# ---------------------------------------------------------------------------


def test_write_backup_creates_parent_and_atomic(cutover, tmp_path):
    target = tmp_path / "nested" / "deep" / "backup.json"
    doc = {"schema_version": 1, "x": 1}
    cutover.write_backup(target, doc)
    assert target.exists()
    # The .tmp staging file should NOT exist after the rename.
    assert not (target.with_suffix(target.suffix + ".tmp")).exists()
    loaded = json.loads(target.read_text())
    assert loaded == doc
