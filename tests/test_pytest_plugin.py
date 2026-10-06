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

"""Opt-in plugin configuration, status preservation, and real pytest loading."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

import pytest

import importtime_check.pytest_plugin as plugin
from importtime_check import (
    Baseline,
    BaselineError,
    EnvironmentIdentity,
    ImportMeasurementError,
    ImportTimeEvent,
    RegressionReport,
    SamplingPolicy,
    TargetBaseline,
    TargetRegressionResult,
    probe_environment,
    save_baseline,
)

ENV = EnvironmentIdentity("cpython", "3.11", "win32", "amd64")
BASELINE = Baseline(ENV, SamplingPolicy(0, 1), {"json": TargetBaseline(100, 5, "10")})


def _config(
    *, options: dict[str, Any] | None = None, ini: dict[str, Any] | None = None
) -> pytest.Config:
    option_values = {
        "--importtime-baseline": None,
        "--importtime-module": None,
        "--importtime-python": None,
        "--importtime-timeout-seconds": None,
        "--importtime-working-directory": None,
        "--importtime-profile": None,
    }
    ini_values: dict[str, Any] = {
        "importtime_baseline": "baseline.json",
        "importtime_modules": [],
        "importtime_python": "",
        "importtime_timeout_seconds": "",
        "importtime_working_directory": "",
        "importtime_profile": "",
    }
    option_values.update(options or {})
    ini_values.update(ini or {})
    config = Mock(spec=pytest.Config)
    config.getoption.side_effect = option_values.__getitem__
    config.getini.side_effect = ini_values.__getitem__
    config.stash = {}
    return cast(pytest.Config, config)


@pytest.fixture
def prepared(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plugin, "load_baseline", lambda name: BASELINE)
    monkeypatch.setattr(plugin, "probe_environment", lambda **kwargs: ENV)


def _report(status: str) -> RegressionReport:
    return RegressionReport(
        ENV,
        (
            TargetRegressionResult(
                "json",
                cast(Any, status),
                100,
                120,
                20,
                5,
                "10",
                (),
                (120,),
                (ImportTimeEvent("json", 1, 120, 0),),
            ),
        ),
    )


def test_options_are_registered_only_by_explicit_plugin_loading() -> None:
    parser = Mock(spec=pytest.Parser)
    group = parser.getgroup.return_value
    plugin.pytest_addoption(parser)
    assert group.addoption.call_count == 6
    assert parser.addini.call_count == 6
    assert not any(call.args[0] == "pytest11" for call in parser.addini.call_args_list)


def test_configure_defaults_and_explicit_precedence(
    prepared: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _config()
    plugin.pytest_configure(config)
    gate = config.stash[plugin._GATE]
    assert gate.modules == ("json",)
    assert gate.timeout_seconds == 30.0
    assert gate.profile == "default"

    config = _config(
        options={
            "--importtime-baseline": "cli.json",
            "--importtime-module": ["json"],
            "--importtime-python": sys.executable,
            "--importtime-timeout-seconds": 2.5,
            "--importtime-working-directory": str(tmp_path),
            "--importtime-profile": "ci",
        },
        ini={
            "importtime_baseline": "ignored.json",
            "importtime_modules": ["wrong"],
            "importtime_python": "ignored",
            "importtime_timeout_seconds": "bad",
            "importtime_working_directory": "ignored",
            "importtime_profile": "ignored",
        },
    )
    seen: list[str] = []

    def load(name: str) -> Baseline:
        seen.append(name)
        return BASELINE

    monkeypatch.setattr(plugin, "load_baseline", load)
    monkeypatch.setattr(plugin, "probe_environment", lambda **kwargs: ENV)
    plugin.pytest_configure(config)
    gate = config.stash[plugin._GATE]
    assert seen == ["cli.json"]
    assert (
        gate.modules,
        gate.timeout_seconds,
        gate.working_directory,
        gate.profile,
    ) == (("json",), 2.5, tmp_path.resolve(), "ci")


@pytest.mark.parametrize(
    ("options", "ini", "message"),
    [
        ({}, {"importtime_baseline": ""}, "required"),
        ({"--importtime-module": ["other"]}, {}, "target set differs"),
        ({"--importtime-module": ["json", "json"]}, {}, "duplicates"),
        ({"--importtime-timeout-seconds": -1.0}, {}, "finite positive"),
        ({}, {"importtime_timeout_seconds": "bad"}, "convert"),
        ({"--importtime-working-directory": "missing-dir"}, {}, "existing directory"),
        ({"--importtime-profile": " "}, {}, "non-blank"),
    ],
)
def test_configure_rejects_invalid_settings_before_tests(
    prepared: None, options: dict[str, Any], ini: dict[str, Any], message: str
) -> None:
    with pytest.raises(pytest.UsageError, match=message):
        plugin.pytest_configure(_config(options=options, ini=ini))


def test_configure_rejects_invalid_baseline_and_environment(
    prepared: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        plugin,
        "load_baseline",
        lambda name: (_ for _ in ()).throw(
            BaselineError("baseline-missing", "missing")
        ),
    )
    with pytest.raises(pytest.UsageError, match="missing"):
        plugin.pytest_configure(_config())
    monkeypatch.setattr(plugin, "load_baseline", lambda name: BASELINE)
    monkeypatch.setattr(
        plugin,
        "probe_environment",
        lambda **kwargs: EnvironmentIdentity("cpython", "3.12", "win32", "amd64"),
    )
    with pytest.raises(pytest.UsageError, match="environment differs"):
        plugin.pytest_configure(_config())
    monkeypatch.setattr(
        plugin,
        "probe_environment",
        lambda **kwargs: (_ for _ in ()).throw(
            BaselineError("interpreter-probe-failed", "failed")
        ),
    )
    with pytest.raises(pytest.UsageError, match="failed"):
        plugin.pytest_configure(_config())


def test_session_verdicts_and_existing_failures(
    prepared: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config()
    plugin.pytest_configure(config)
    session = Mock(spec=pytest.Session)
    session.config = config
    session.exitstatus = pytest.ExitCode.OK
    monkeypatch.setattr(
        plugin, "check_baseline", lambda *args, **kwargs: _report("pass")
    )
    plugin.pytest_sessionfinish(session, pytest.ExitCode.TESTS_FAILED)
    assert config.stash[plugin._GATE].summary is None
    plugin.pytest_sessionfinish(session, pytest.ExitCode.NO_TESTS_COLLECTED)
    assert config.stash[plugin._GATE].summary is None
    plugin.pytest_sessionfinish(session, pytest.ExitCode.OK)
    summary = config.stash[plugin._GATE].summary
    assert summary is not None and "pass" in summary
    assert session.exitstatus != pytest.ExitCode.TESTS_FAILED

    monkeypatch.setattr(
        plugin, "check_baseline", lambda *args, **kwargs: _report("regression")
    )
    plugin.pytest_sessionfinish(session, pytest.ExitCode.OK)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    summary = config.stash[plugin._GATE].summary
    assert summary is not None and "regression" in summary


@pytest.mark.parametrize(
    "error",
    [
        BaselineError("environment-mismatch", "environment changed"),
        ImportMeasurementError(
            module="json",
            kind="timeout",
            python_executable=sys.executable,
            reason="child timed out",
            run_phase="sample",
            run_number=1,
        ),
    ],
)
def test_session_operational_errors_are_test_failures(
    prepared: None,
    monkeypatch: pytest.MonkeyPatch,
    error: BaselineError | ImportMeasurementError,
) -> None:
    config = _config()
    plugin.pytest_configure(config)
    session = Mock(spec=pytest.Session)
    session.config = config

    def fail(*args: Any, **kwargs: Any) -> None:
        raise error

    monkeypatch.setattr(plugin, "check_baseline", fail)
    plugin.pytest_sessionfinish(session, pytest.ExitCode.OK)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    summary = config.stash[plugin._GATE].summary
    assert summary is not None and summary.startswith("error:")


def test_terminal_summary_only_when_gate_ran(prepared: None) -> None:
    config = _config()
    plugin.pytest_configure(config)
    reporter = Mock()
    reporter.config = config
    plugin.pytest_terminal_summary(reporter, pytest.ExitCode.OK)
    reporter.write_sep.assert_not_called()
    config.stash[plugin._GATE].summary = "pass"
    plugin.pytest_terminal_summary(reporter, pytest.ExitCode.OK)
    reporter.write_sep.assert_called_once_with("=", "importtime-check")
    reporter.write_line.assert_called_once_with("pass")


@pytest.mark.integration
def test_explicit_plugin_loads_in_isolated_pytest_process(tmp_path: Path) -> None:
    baseline = Baseline(
        probe_environment(),
        SamplingPolicy(0, 1),
        {"json": TargetBaseline(0, 100000000000000000000, "0")},
    )
    baseline_path = tmp_path / "baseline.json"
    save_baseline(baseline_path, baseline)
    (tmp_path / "test_example.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    environment = os.environ.copy()
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    base = [sys.executable, "-m", "pytest", "-q", "-o", "addopts="]
    disabled = subprocess.run(
        base,
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert disabled.returncode == 0
    assert "importtime-check" not in disabled.stdout
    enabled = subprocess.run(
        [
            *base,
            "-p",
            "importtime_check.pytest_plugin",
            "--importtime-baseline",
            str(baseline_path),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert enabled.returncode == 0, enabled.stderr + enabled.stdout
    assert "importtime-check" in enabled.stdout

    (tmp_path / "pytest.ini").write_text(
        f"[pytest]\nimporttime_baseline = {baseline_path}\n"
        "importtime_modules = json\nimporttime_timeout_seconds = 10\n",
        encoding="utf-8",
    )
    from_config = subprocess.run(
        [*base, "-p", "importtime_check.pytest_plugin"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert from_config.returncode == 0, from_config.stderr + from_config.stdout
    assert "importtime-check" in from_config.stdout

    (tmp_path / "pytest.ini").write_text(
        "[pytest]\nimporttime_baseline = missing.json\n"
        "importtime_modules = wrong\nimporttime_timeout_seconds = bad\n",
        encoding="utf-8",
    )
    overridden = subprocess.run(
        [
            *base,
            "-p",
            "importtime_check.pytest_plugin",
            "--importtime-baseline",
            str(baseline_path),
            "--importtime-module",
            "json",
            "--importtime-timeout-seconds",
            "10",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert overridden.returncode == 0, overridden.stderr + overridden.stdout

    invalid = subprocess.run(
        [*base, "-p", "importtime_check.pytest_plugin"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert invalid.returncode == pytest.ExitCode.USAGE_ERROR
    assert "missing.json" in invalid.stderr
