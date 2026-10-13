# Copyright 2026 importtime-check contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""CLI behavior using synthetic observations, without timing assumptions."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import importtime_check._cli as cli
import importtime_check._regression as regression
from importtime_check import (
    Baseline,
    BaselineError,
    EnvironmentIdentity,
    ImportMeasurement,
    ImportMeasurementError,
    ImportSampleSet,
    ImportTimeEvent,
    ImportTimeParseResult,
    SamplingPolicy,
    TargetBaseline,
    decode_baseline,
    encode_baseline,
    save_baseline,
)

ENV = EnvironmentIdentity("cpython", "3.11", "win32", "amd64")


def _sample(module: str, **options: Any) -> ImportSampleSet:
    value = 150 if module == "json" else 90
    interpreter = str(Path(sys.executable).resolve())
    event = ImportTimeEvent(module, 1, value, 0)
    measurement = ImportMeasurement(
        module, interpreter, ImportTimeParseResult((event,), ()), event
    )
    warmups = (measurement,) * options.get("warmups", 1)
    samples = (measurement,) * options.get("samples", 5)
    return ImportSampleSet(module, interpreter, warmups, samples, value)


@pytest.fixture
def synthetic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "sample_import", _sample)
    monkeypatch.setattr(regression, "sample_import", _sample)
    monkeypatch.setattr(cli, "probe_environment", lambda **options: ENV)
    monkeypatch.setattr(regression, "probe_environment", lambda **options: ENV)


def _record(path: Path, *extra: str) -> list[str]:
    return [
        "baseline",
        "record",
        "--output",
        str(path),
        "--module",
        "json",
        "--max-increase-us",
        "5",
        "--max-increase-percent",
        "10",
        *extra,
    ]


def _record_budgets(path: Path, *extra: str) -> list[str]:
    return [
        "baseline",
        "record",
        "--output",
        str(path),
        "--module",
        "zeta",
        "--module",
        "json",
        *extra,
    ]


def _refresh(path: Path, *extra: str) -> list[str]:
    return ["baseline", "refresh", "--file", str(path), "--replace", *extra]


def _refresh_source(path: Path) -> Baseline:
    baseline = Baseline(
        ENV,
        SamplingPolicy(1, 2),
        {
            "zeta": TargetBaseline(100, 25, "2.5"),
            "json": TargetBaseline(130, 5, "10"),
        },
    )
    save_baseline(path, baseline)
    return baseline


def test_refresh_preserves_reviewed_policy_and_reports_sorted_changes(
    synthetic: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "baseline.json"
    before = _refresh_source(path)
    calls: list[tuple[str, int, int, str]] = []

    def sample(module: str, **options: Any) -> ImportSampleSet:
        calls.append(
            (
                module,
                options["warmups"],
                options["samples"],
                options["python_executable"],
            )
        )
        return _sample(module, **options)

    monkeypatch.setattr(cli, "sample_import", sample)
    assert cli.main(_refresh(path, "--working-directory", str(tmp_path))) == 0
    after = decode_baseline(path.read_bytes())
    assert path.read_bytes() == encode_baseline(after)
    assert after.environment == before.environment
    assert after.sampling == before.sampling
    assert tuple(after.targets) == ("json", "zeta")
    assert after.targets["json"] == TargetBaseline(150, 5, "10")
    assert after.targets["zeta"] == TargetBaseline(90, 25, "2.5")
    assert calls == [
        ("json", 1, 2, str(Path(sys.executable).resolve())),
        ("zeta", 1, 2, str(Path(sys.executable).resolve())),
    ]
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out.splitlines() == [
        "json: 130 -> 150 us (+20 us)",
        "zeta: 100 -> 90 us (-10 us)",
        "Target names, sampling, identity, and allowances retained; review the file.",
    ]


def test_refresh_requires_explicit_replace_before_probe(
    synthetic: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "baseline.json"
    _refresh_source(path)
    original = path.read_bytes()

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("must not probe or measure")

    monkeypatch.setattr(cli, "probe_environment", forbidden)
    monkeypatch.setattr(cli, "sample_import", forbidden)
    with pytest.raises(SystemExit) as error:
        cli.main(["baseline", "refresh", "--file", str(path)])
    assert error.value.code == 2
    assert "requires --replace" in capsys.readouterr().err
    with pytest.raises(SystemExit) as option:
        cli.main(_refresh(path, "--module", "json"))
    assert option.value.code == 2
    capsys.readouterr()
    assert path.read_bytes() == original


def test_refresh_rejects_missing_invalid_and_nonregular_files(
    synthetic: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "missing.json"
    assert cli.main(_refresh(missing)) == 2
    assert "baseline file not found" in capsys.readouterr().err
    invalid = tmp_path / "invalid.json"
    invalid.write_bytes(b"{")
    assert cli.main(_refresh(invalid)) == 2
    assert "importtime-check:" in capsys.readouterr().err
    assert invalid.read_bytes() == b"{"
    assert cli.main(_refresh(tmp_path)) == 2
    assert "regular non-symlink" in capsys.readouterr().err


def test_refresh_rejects_environment_before_target_imports(
    synthetic: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "baseline.json"
    _refresh_source(path)
    original = path.read_bytes()
    monkeypatch.setattr(
        cli,
        "probe_environment",
        lambda **options: EnvironmentIdentity("cpython", "3.12", "win32", "amd64"),
    )

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("target import must not run")

    monkeypatch.setattr(cli, "sample_import", forbidden)
    assert cli.main(_refresh(path)) == 2
    assert "environment differs" in capsys.readouterr().err
    assert path.read_bytes() == original


def test_refresh_failure_or_interrupt_keeps_original_bytes(
    synthetic: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "baseline.json"
    _refresh_source(path)
    original = path.read_bytes()
    error = ImportMeasurementError(
        module="zeta",
        kind="timeout",
        python_executable=str(Path(sys.executable).resolve()),
        reason="child timeout",
    )

    def partial(module: str, **options: Any) -> ImportSampleSet:
        if module == "zeta":
            raise error
        return _sample(module, **options)

    monkeypatch.setattr(cli, "sample_import", partial)
    assert cli.main(_refresh(path)) == 2
    assert "timeout" in capsys.readouterr().err
    assert path.read_bytes() == original

    def interrupted(*args: Any, **kwargs: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "sample_import", interrupted)
    with pytest.raises(KeyboardInterrupt):
        cli.main(_refresh(path))
    assert path.read_bytes() == original


def test_refresh_detects_external_edit_or_removal_before_commit(
    synthetic: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "baseline.json"
    before = _refresh_source(path)
    external = b"external change"

    def edit(module: str, **options: Any) -> ImportSampleSet:
        path.write_bytes(external)
        return _sample(module, **options)

    monkeypatch.setattr(cli, "sample_import", edit)
    assert cli.main(_refresh(path)) == 2
    assert "baseline changed during refresh" in capsys.readouterr().err
    assert path.read_bytes() == external
    assert not list(tmp_path.glob(".importtime-check-*"))

    path.write_bytes(encode_baseline(before))

    def remove(module: str, **options: Any) -> ImportSampleSet:
        if path.exists():
            path.unlink()
        return _sample(module, **options)

    monkeypatch.setattr(cli, "sample_import", remove)
    assert cli.main(_refresh(path)) == 2
    assert "baseline changed during refresh" in capsys.readouterr().err
    assert not path.exists()
    assert not list(tmp_path.glob(".importtime-check-*"))


def test_refresh_replace_failure_keeps_file_and_cleans_temporary(
    synthetic: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "baseline.json"
    _refresh_source(path)
    original = path.read_bytes()

    def fail_replace(*args: Any, **kwargs: Any) -> None:
        raise OSError("replacement unavailable")

    monkeypatch.setattr(os, "replace", fail_replace)
    assert cli.main(_refresh(path)) == 2
    assert "cannot write baseline" in capsys.readouterr().err
    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".importtime-check-*"))


def test_refresh_temporary_write_failure_keeps_original(
    synthetic: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "baseline.json"
    _refresh_source(path)
    original = path.read_bytes()

    def fail_sync(file_descriptor: int) -> None:
        raise OSError("sync unavailable")

    monkeypatch.setattr(os, "fsync", fail_sync)
    assert cli.main(_refresh(path)) == 2
    assert "cannot write baseline" in capsys.readouterr().err
    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".importtime-check-*"))


def test_refresh_file_reader_classifies_missing_and_symlink_changes(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(BaselineError) as changed:
        cli._read_refresh_bytes(missing, initial=False)
    assert changed.value.kind == "io-error"
    fake = cast(
        Any,
        SimpleNamespace(lstat=lambda: SimpleNamespace(st_mode=stat.S_IFLNK)),
    )
    with pytest.raises(BaselineError, match="non-symlink") as link:
        cli._read_refresh_bytes(fake, initial=True)
    assert link.value.kind == "io-error"
    with pytest.raises(BaselineError, match="changed during refresh"):
        cli._read_refresh_bytes(fake, initial=False)
    unreadable = cast(
        Any,
        SimpleNamespace(lstat=lambda: (_ for _ in ()).throw(PermissionError("denied"))),
    )
    with pytest.raises(BaselineError, match="cannot read baseline"):
        cli._read_refresh_bytes(unreadable, initial=True)
    with pytest.raises(BaselineError, match="changed during refresh"):
        cli._read_refresh_bytes(unreadable, initial=False)


def test_measure_and_record_show_workflows(
    synthetic: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        cli.main(["measure", "--module", "json", "--warmups", "0", "--samples", "1"])
        == 0
    )
    assert "upper median 150 us" in capsys.readouterr().out

    path = tmp_path / "baseline.json"
    assert cli.main(_record(path)) == 0
    assert path.exists()
    assert "Recorded 1 target(s)" in capsys.readouterr().out
    assert cli.main(["baseline", "show", "--file", str(path)]) == 0
    assert "json: 150 us" in capsys.readouterr().out
    assert cli.main(["baseline", "show", "--file", str(path), "--format", "json"]) == 0
    assert (
        json.loads(capsys.readouterr().out)["targets"]["json"]["baseline_cumulative_us"]
        == 150
    )
    assert cli.main(_record(path, "--replace")) == 0
    capsys.readouterr()
    with pytest.raises(SystemExit) as error:
        cli.main(_record(path))
    assert error.value.code == 2
    assert "use --replace" in capsys.readouterr().err


def test_record_per_target_budgets_are_sorted_normalized_and_reviewable(
    synthetic: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "baseline.json"
    arguments = _record_budgets(
        path, "--budget", "zeta=0,2.500", "--budget", "json=25,10.00"
    )
    assert cli.main(arguments) == 0
    baseline = decode_baseline(path.read_bytes())
    assert path.read_bytes() == encode_baseline(baseline)
    assert tuple(baseline.targets) == ("json", "zeta")
    assert baseline.targets["json"] == TargetBaseline(150, 25, "10")
    assert baseline.targets["zeta"] == TargetBaseline(90, 0, "2.5")
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out.splitlines() == [
        f"Recorded 2 target(s) in {path}",
        "json: allowances 25 us or 10%",
        "zeta: allowances 0 us or 2.5%",
        "Review the baseline file diff before accepting these budgets.",
    ]
    original = path.read_bytes()
    with pytest.raises(SystemExit) as error:
        cli.main(arguments)
    assert error.value.code == 2
    assert "use --replace" in capsys.readouterr().err
    assert path.read_bytes() == original
    replacement = _record_budgets(
        path, "--budget", "json=5,1", "--budget", "zeta=10,3", "--replace"
    )
    assert cli.main(replacement) == 0
    assert decode_baseline(path.read_bytes()).targets["json"] == TargetBaseline(
        150, 5, "1"
    )
    capsys.readouterr()


def test_recorded_per_target_allowances_flow_to_show_and_check(
    synthetic: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "baseline.json"
    assert (
        cli.main(
            _record_budgets(path, "--budget", "json=25,10", "--budget", "zeta=50,2.5")
        )
        == 0
    )
    capsys.readouterr()
    assert cli.main(["baseline", "show", "--file", str(path)]) == 0
    shown = capsys.readouterr().out
    assert "json: 150 us; allowances 25 us or 10%" in shown
    assert "zeta: 90 us; allowances 50 us or 2.5%" in shown

    recorded = decode_baseline(path.read_bytes())
    comparison = Baseline(
        recorded.environment,
        recorded.sampling,
        {
            module: TargetBaseline(
                100 if module == "json" else 80,
                target.max_increase_us,
                target.max_increase_percent,
            )
            for module, target in recorded.targets.items()
        },
    )
    save_baseline(path, comparison, replace=True)
    assert cli.main(["check", "--baseline", str(path)]) == 1
    report = capsys.readouterr().out
    assert "REGRESSION json: 100 -> 150 us (+50 us; allowances 25 us or 10%)" in report
    assert "PASS zeta: 80 -> 90 us (+10 us; allowances 50 us or 2.5%)" in report


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ([], "supply both"),
        (["--max-increase-us", "5"], "supply both"),
        (["--max-increase-percent", "10"], "supply both"),
        (["--budget", "json=5,10"], "missing: zeta"),
        (
            ["--budget", "json=5,10", "--budget", "extra=1,2"],
            "missing: zeta; unknown: extra",
        ),
        (
            ["--budget", "json=5,10", "--budget", "json=5,10"],
            "duplicate --budget for module 'json'",
        ),
        (
            ["--budget", "json=5,10", "--max-increase-us", "0"],
            "cannot be mixed",
        ),
        (
            ["--budget", "json=5,10", "--max-increase-percent", "0"],
            "cannot be mixed",
        ),
    ],
)
def test_record_budget_modes_and_target_sets_fail_before_probe(
    synthetic: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    options: list[str],
    message: str,
) -> None:
    path = tmp_path / "baseline.json"
    path.write_bytes(b"reviewed baseline bytes")

    def forbidden(**kwargs: Any) -> None:
        raise AssertionError("must not probe")

    monkeypatch.setattr(cli, "probe_environment", forbidden)
    with pytest.raises(SystemExit) as error:
        cli.main(_record_budgets(path, *options, "--replace"))
    assert error.value.code == 2
    assert message in capsys.readouterr().err
    assert path.read_bytes() == b"reviewed baseline bytes"


@pytest.mark.parametrize(
    "entry",
    [
        "json",
        "json=5",
        "json=5,10,2",
        "json=5=6,10",
        "json=,10",
        "json=01,10",
        "json=+1,10",
        "json=-1,10",
        "json=1.0,10",
        "json=1e2,10",
        "json=1us,10",
        "json=1,",
        "json=1,+10",
        "json=1,1e2",
        "json=1,10.0%",
        "json=1,01",
        " json=1,10",
        "json =1,10",
        "json=1,10 ",
        "bad-name=1,10",
    ],
)
def test_record_malformed_budget_is_usage_error_without_measurement(
    synthetic: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    entry: str,
) -> None:
    path = tmp_path / "baseline.json"
    path.write_bytes(b"reviewed baseline bytes")

    def forbidden(**kwargs: Any) -> None:
        raise AssertionError("must not probe")

    monkeypatch.setattr(cli, "probe_environment", forbidden)
    with pytest.raises(SystemExit) as error:
        cli.main(_record_budgets(path, "--budget", entry, "--replace"))
    assert error.value.code == 2
    assert entry in capsys.readouterr().err
    assert path.read_bytes() == b"reviewed baseline bytes"


def test_record_duplicate_module_and_refresh_budget_fail_before_probe(
    synthetic: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "baseline.json"
    path.write_bytes(b"reviewed baseline bytes")

    def forbidden(**kwargs: Any) -> None:
        raise AssertionError("must not probe")

    monkeypatch.setattr(cli, "probe_environment", forbidden)
    with pytest.raises(SystemExit) as duplicate:
        cli.main(
            _record_budgets(
                path,
                "--module",
                "json",
                "--budget",
                "json=5,10",
                "--budget",
                "zeta=1,2",
                "--replace",
            )
        )
    assert duplicate.value.code == 2
    assert "module names must not repeat" in capsys.readouterr().err
    with pytest.raises(SystemExit) as refresh:
        cli.main(_refresh(path, "--budget", "json=5,10"))
    assert refresh.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err
    assert path.read_bytes() == b"reviewed baseline bytes"


def test_record_budget_probe_or_sample_failure_preserves_existing_bytes(
    synthetic: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "baseline.json"
    path.write_bytes(b"reviewed baseline bytes")
    arguments = _record_budgets(
        path, "--budget", "json=5,10", "--budget", "zeta=1,2", "--replace"
    )

    def probe_failure(**kwargs: Any) -> None:
        raise ValueError("probe unavailable")

    monkeypatch.setattr(cli, "probe_environment", probe_failure)
    with pytest.raises(SystemExit) as probe:
        cli.main(arguments)
    assert probe.value.code == 2
    assert "probe unavailable" in capsys.readouterr().err
    assert path.read_bytes() == b"reviewed baseline bytes"
    monkeypatch.setattr(cli, "probe_environment", lambda **kwargs: ENV)

    def sample_failure(module: str, **kwargs: Any) -> ImportSampleSet:
        if module == "zeta":
            raise ValueError("sample unavailable")
        return _sample(module, **kwargs)

    monkeypatch.setattr(cli, "sample_import", sample_failure)
    with pytest.raises(SystemExit) as sample:
        cli.main(arguments)
    assert sample.value.code == 2
    assert "sample unavailable" in capsys.readouterr().err
    assert path.read_bytes() == b"reviewed baseline bytes"


def test_check_exit_codes_and_json_contract(
    synthetic: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "baseline.json"
    assert cli.main(_record(path, "--warmups", "0", "--samples", "1")) == 0
    capsys.readouterr()
    assert cli.main(["check", "--baseline", str(path)]) == 0
    assert "pass" in capsys.readouterr().out
    assert cli.main(["check", "--baseline", str(path), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pass"

    document = json.loads(path.read_text(encoding="utf-8"))
    document["targets"]["json"]["baseline_cumulative_us"] = 100
    path.write_text(json.dumps(document), encoding="utf-8")
    assert cli.main(["check", "--baseline", str(path)]) == 1
    assert "REGRESSION json" in capsys.readouterr().out
    assert cli.main(["check", "--baseline", str(path), "--format", "json"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "regression"


def test_check_errors_and_debug(
    synthetic: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = str(tmp_path / "missing.json")
    assert cli.main(["check", "--baseline", missing, "--format", "json"]) == 2
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out)["error"]["kind"] == "baseline-missing"
    assert cli.main(["check", "--baseline", missing]) == 2
    assert "importtime-check:" in capsys.readouterr().err
    with pytest.raises(BaselineError):
        cli.main(["--debug", "check", "--baseline", missing])

    path = tmp_path / "baseline.json"
    cli.main(_record(path))
    capsys.readouterr()
    assert (
        cli.main(
            ["check", "--baseline", str(path), "--module", "other", "--format", "json"]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out)["error"]["kind"] == "target-set-mismatch"


def test_check_mismatch_diagnostics_keep_schema_and_exit_code(
    synthetic: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "baseline.json"
    _refresh_source(path)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("probe or target import should not start")

    monkeypatch.setattr(regression, "sample_import", forbidden)
    monkeypatch.setattr(
        regression,
        "probe_environment",
        lambda **kwargs: EnvironmentIdentity(
            "cpython", "3.12", "private-platform", "private-host", "private-profile"
        ),
    )
    arguments = ["check", "--baseline", str(path), "--format", "json"]
    assert cli.main(arguments) == 2
    output = capsys.readouterr()
    assert output.err == ""
    document = json.loads(output.out)
    assert set(document) == {"schema_version", "status", "error"}
    assert document["schema_version"] == 1
    assert document["status"] == "error"
    assert set(document["error"]) == {"kind", "message"}
    assert document["error"]["kind"] == "environment-mismatch"
    message = document["error"]["message"]
    assert "python: baseline 3.11, current 3.12" in message
    assert "platform differs; machine differs; profile differs" in message
    for secret in ("private-platform", "private-host", "private-profile", str(path)):
        assert secret not in message
    assert cli.main(arguments[:-2]) == 2
    assert message in capsys.readouterr().err

    monkeypatch.setattr(regression, "probe_environment", forbidden)
    assert (
        cli.main(
            [
                "check",
                "--baseline",
                str(path),
                "--module",
                "omega",
                "--module",
                "delta",
                "--format",
                "json",
            ]
        )
        == 2
    )
    target_error = json.loads(capsys.readouterr().out)["error"]
    assert set(target_error) == {"kind", "message"}
    assert target_error["kind"] == "target-set-mismatch"
    assert "missing from baseline: delta, omega" in target_error["message"]
    assert "stale in baseline: json, zeta" in target_error["message"]


def test_preflight_rejects_bad_options_before_measurement(
    synthetic: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("must not measure")

    monkeypatch.setattr(cli, "sample_import", forbidden)
    cases = [
        _record(tmp_path / "x.json", "--module", "json"),
        _record(tmp_path / "x.json", "--samples", "0"),
        _record(tmp_path / "missing" / "x.json"),
        _record(tmp_path / "x.json", "--profile", " "),
        _record(tmp_path / "x.json", "--max-increase-percent", "nan"),
        _record(tmp_path / "x.json", "--max-increase-us", "-1"),
    ]
    for arguments in cases:
        with pytest.raises(SystemExit) as error:
            cli.main(arguments)
        assert error.value.code == 2
        assert "error:" in capsys.readouterr().err
    with pytest.raises(ValueError, match="samples"):
        cli.main(["--debug", *_record(tmp_path / "x.json", "--samples", "0")])
    with pytest.raises(SystemExit) as error:
        cli.main(["check", "--baseline", "file", "--format", "yaml"])
    assert error.value.code == 2


def test_measurement_error_has_distinct_exit_and_json_context(
    synthetic: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = ImportMeasurementError(
        module="json",
        kind="timeout",
        python_executable=str(Path(sys.executable).resolve()),
        reason="child timeout",
        run_phase="sample",
        run_number=1,
    )

    def fail(*args: Any, **kwargs: Any) -> None:
        raise error

    monkeypatch.setattr(cli, "sample_import", fail)
    assert cli.main(["measure", "--module", "json"]) == 2
    assert "timeout" in capsys.readouterr().err
    with pytest.raises(ImportMeasurementError):
        cli.main(["--debug", "measure", "--module", "json"])
    path = tmp_path / "baseline.json"
    assert cli.main(_record(path)) == 2
    assert "timeout" in capsys.readouterr().err
    monkeypatch.setattr(cli, "sample_import", _sample)
    assert cli.main(_record(path)) == 0
    capsys.readouterr()
    monkeypatch.setattr(regression, "sample_import", fail)
    assert cli.main(["check", "--baseline", str(path), "--format", "json"]) == 2
    details = json.loads(capsys.readouterr().out)["error"]
    assert (details["kind"], details["run_phase"], details["run_number"]) == (
        "measurement-failed",
        "sample",
        1,
    )
