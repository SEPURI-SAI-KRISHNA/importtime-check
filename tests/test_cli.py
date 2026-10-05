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
import sys
from pathlib import Path
from typing import Any

import pytest

import importtime_check._cli as cli
import importtime_check._regression as regression
from importtime_check import (
    BaselineError,
    EnvironmentIdentity,
    ImportMeasurement,
    ImportMeasurementError,
    ImportSampleSet,
    ImportTimeEvent,
    ImportTimeParseResult,
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
