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

"""Explicitly loaded pytest adapter for the shared import-time gate."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from ._baseline import Baseline, BaselineError, load_baseline
from ._measurement import (
    ImportMeasurementError,
    _interpreter_path,
    _timeout,
    _working_directory,
)
from ._regression import (
    _require_same_environment,
    _target_set,
    check_baseline,
    probe_environment,
)
from ._report import report_text


@dataclass(slots=True)
class _Gate:
    baseline: Baseline
    modules: tuple[str, ...]
    python_executable: str
    timeout_seconds: float
    working_directory: Path
    profile: str
    summary: str | None = None


_GATE = pytest.StashKey[_Gate]()


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register options only when the plugin is explicitly loaded."""
    group = parser.getgroup("importtime-check", "optional import-time regression gate")
    group.addoption(
        "--importtime-baseline", default=None, help="approved baseline JSON"
    )
    group.addoption(
        "--importtime-module",
        action="append",
        default=None,
        help="expected module; repeatable",
    )
    group.addoption(
        "--importtime-python", default=None, help="absolute Python interpreter"
    )
    group.addoption(
        "--importtime-timeout-seconds", type=float, default=None, help="child timeout"
    )
    group.addoption(
        "--importtime-working-directory", default=None, help="child directory"
    )
    group.addoption("--importtime-profile", default=None, help="environment profile")
    parser.addini("importtime_baseline", "approved baseline JSON")
    parser.addini("importtime_modules", "expected modules", type="args")
    parser.addini("importtime_python", "absolute Python interpreter")
    parser.addini("importtime_timeout_seconds", "child timeout")
    parser.addini("importtime_working_directory", "child directory")
    parser.addini("importtime_profile", "environment profile")


def _setting(config: pytest.Config, option: str, ini: str) -> Any:
    value: Any = config.getoption(option)
    return config.getini(ini) if value is None else value


def _optional(value: str) -> str | None:
    return value or None


def _gate(config: pytest.Config) -> _Gate:
    baseline_name: str = _setting(
        config, "--importtime-baseline", "importtime_baseline"
    )
    if not baseline_name:
        raise ValueError("--importtime-baseline or importtime_baseline is required")
    baseline = load_baseline(baseline_name)
    configured_modules: list[str] = _setting(
        config, "--importtime-module", "importtime_modules"
    )
    modules = _target_set(
        baseline, configured_modules if configured_modules else tuple(baseline.targets)
    )
    python_name: str = _setting(config, "--importtime-python", "importtime_python")
    interpreter = _interpreter_path(_optional(python_name))
    timeout_text: str | float = _setting(
        config, "--importtime-timeout-seconds", "importtime_timeout_seconds"
    )
    timeout = _timeout(float(timeout_text) if timeout_text != "" else 30.0)
    directory_name: str = _setting(
        config, "--importtime-working-directory", "importtime_working_directory"
    )
    directory = _working_directory(_optional(directory_name))
    profile_name: str = _setting(config, "--importtime-profile", "importtime_profile")
    profile = profile_name if profile_name != "" else "default"
    if not profile.strip():
        raise ValueError("importtime profile must be non-blank")
    identity = probe_environment(
        python_executable=interpreter,
        timeout_seconds=timeout,
        working_directory=directory,
        profile=profile,
    )
    _require_same_environment(baseline, identity)
    return _Gate(baseline, modules, interpreter, timeout, directory, profile)


def pytest_configure(config: pytest.Config) -> None:
    """Reject invalid settings before collection or test execution."""
    try:
        config.stash[_GATE] = _gate(config)
    except (BaselineError, ImportMeasurementError, ValueError) as error:
        raise pytest.UsageError(f"importtime-check: {error}") from error


def pytest_sessionfinish(session: pytest.Session, exitstatus: pytest.ExitCode) -> None:
    """Run exactly one gate after an otherwise successful test session."""
    if exitstatus != pytest.ExitCode.OK:
        return
    gate = session.config.stash[_GATE]
    try:
        report = check_baseline(
            gate.baseline,
            python_executable=gate.python_executable,
            timeout_seconds=gate.timeout_seconds,
            working_directory=gate.working_directory,
            profile=gate.profile,
            modules=gate.modules,
        )
    except (BaselineError, ImportMeasurementError) as error:
        gate.summary = f"error: {error}"
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        return
    gate.summary = report_text(report).rstrip("\n")
    if report.status == "regression":
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter: Any, exitstatus: pytest.ExitCode) -> None:
    """Show one session-level result without fabricating test failures."""
    gate = terminalreporter.config.stash[_GATE]
    if gate.summary is not None:
        terminalreporter.write_sep("=", "importtime-check")
        terminalreporter.write_line(gate.summary)
