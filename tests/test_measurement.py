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

"""Tests for one isolated import-time measurement."""

from __future__ import annotations

import math
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, cast

import pytest

from importtime_check import (
    ImportMeasurement,
    ImportMeasurementError,
    ImportTimeEvent,
    ImportTimeParseError,
    ImportTimeParseResult,
    measure_import,
)

HEADER = "import time: self [us] | cumulative | imported package"
TARGET_ROW = "import time:         4 |         12 | sample"


def _completed(stderr: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, None, stderr)


def test_measurement_uses_isolated_argv_and_selects_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorded: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        recorded["command"] = command
        recorded.update(kwargs)
        return _completed(
            "warning\n"
            f"{HEADER}\n"
            "import time:         1 |          2 | dependency\n"
            f"{TARGET_ROW}\n"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("IMPORTTIME_CHECK_TEST_VALUE", "preserved")
    result = measure_import(
        "sample",
        python_executable=Path(sys.executable),
        timeout_seconds=7,
        working_directory=tmp_path,
    )

    assert result.module == "sample"
    assert result.python_executable == str(Path(sys.executable).resolve())
    assert result.target_event == ImportTimeEvent("sample", 4, 12, 0)
    assert result.parsed.diagnostics == ("warning",)
    assert len(result.parsed.events) == 2
    assert recorded["command"][:5] == [
        result.python_executable,
        "-I",
        "-X",
        "importtime",
        "-c",
    ]
    assert recorded["command"][5] == "import sys; __import__(sys.argv[1])"
    assert recorded["command"][6] == "sample"
    assert recorded["stdin"] == subprocess.DEVNULL
    assert recorded["stdout"] == subprocess.DEVNULL
    assert recorded["stderr"] == subprocess.PIPE
    assert recorded["cwd"] == tmp_path.resolve()
    assert recorded["env"]["IMPORTTIME_CHECK_TEST_VALUE"] == "preserved"
    assert recorded["shell"] is False
    assert recorded["check"] is False
    assert recorded["text"] is True
    assert recorded["encoding"] == "utf-8"
    assert recorded["errors"] == "replace"
    assert recorded["timeout"] == 7.0


def test_defaults_are_resolved_before_launch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert command[0] == str(Path(sys.executable).resolve())
        assert kwargs["cwd"] == Path.cwd().resolve()
        assert kwargs["timeout"] == 30.0
        return _completed(TARGET_ROW)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert measure_import("sample").target_event.cumulative_us == 12


@pytest.mark.parametrize(
    "module",
    ("", ".sample", "sample.", "sample..child", "sample-child", "for", 42),
)
def test_invalid_module_fails_before_launch(
    monkeypatch: pytest.MonkeyPatch, module: object
) -> None:
    def unexpected_run(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("subprocess should not start")

    monkeypatch.setattr(subprocess, "run", unexpected_run)
    with pytest.raises(ValueError, match="dotted Python module name"):
        measure_import(cast(Any, module))


@pytest.mark.parametrize(
    "value", ("", "python", 42, b"python"), ids=("empty", "relative", "number", "bytes")
)
def test_invalid_interpreter_fails_before_launch(
    monkeypatch: pytest.MonkeyPatch, value: object
) -> None:
    def unexpected_run(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("subprocess should not start")

    monkeypatch.setattr(subprocess, "run", unexpected_run)
    with pytest.raises(ValueError, match="python_executable"):
        measure_import("sample", python_executable=cast(Any, value))


@pytest.mark.parametrize("value", ("", 42, b"directory"))
def test_invalid_directory_value_fails_before_launch(
    monkeypatch: pytest.MonkeyPatch, value: object
) -> None:
    def unexpected_run(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("subprocess should not start")

    monkeypatch.setattr(subprocess, "run", unexpected_run)
    with pytest.raises(ValueError, match="working_directory"):
        measure_import("sample", working_directory=cast(Any, value))


def test_missing_directory_fails_before_launch(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="existing directory"):
        measure_import("sample", working_directory=tmp_path / "missing")


@pytest.mark.parametrize("value", (True, "3", 0, -1, math.inf, math.nan, 10**400))
def test_invalid_timeout_fails_before_launch(
    monkeypatch: pytest.MonkeyPatch, value: object
) -> None:
    def unexpected_run(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("subprocess should not start")

    monkeypatch.setattr(subprocess, "run", unexpected_run)
    with pytest.raises(ValueError, match="finite positive number"):
        measure_import("sample", timeout_seconds=cast(Any, value))


def test_launch_failure_is_focused(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: Any, **kwargs: Any) -> None:
        raise FileNotFoundError("interpreter is missing")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ImportMeasurementError, match="interpreter is missing") as found:
        measure_import("sample")
    assert found.value.kind == "launch"
    assert found.value.returncode is None
    assert found.value.stderr == ""
    assert found.value.run_phase is None
    assert found.value.run_number is None
    assert isinstance(found.value.__cause__, FileNotFoundError)


@pytest.mark.parametrize("partial", (None, b"bad\xff", "partial"))
def test_timeout_preserves_available_stderr(
    monkeypatch: pytest.MonkeyPatch, partial: bytes | str | None
) -> None:
    def fake_run(*args: Any, **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired("python", 2, stderr=partial)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ImportMeasurementError, match="within 2 seconds") as found:
        measure_import("sample", timeout_seconds=2)
    assert found.value.kind == "timeout"
    assert found.value.returncode is None
    assert found.value.stderr == (
        partial.decode("utf-8", "replace")
        if isinstance(partial, bytes)
        else partial or ""
    )
    assert isinstance(found.value.__cause__, subprocess.TimeoutExpired)


def test_nonzero_exit_precedes_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return _completed("import time: malformed", returncode=7)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ImportMeasurementError, match="code 7") as found:
        measure_import("sample")
    assert found.value.kind == "exit"
    assert found.value.returncode == 7
    assert found.value.stderr == "import time: malformed"
    assert found.value.__cause__ is None


def test_parse_failure_keeps_original_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return _completed("warning\nimport time: malformed")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ImportMeasurementError, match="line 2") as found:
        measure_import("sample")
    assert found.value.kind == "parse"
    assert found.value.returncode == 0
    assert isinstance(found.value.__cause__, ImportTimeParseError)
    assert found.value.__cause__.line_number == 2


def test_missing_target_is_not_zero_measurement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return _completed("")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ImportMeasurementError, match="no import-time event") as found:
        measure_import("sample")
    assert found.value.kind == "missing-target"
    assert found.value.stderr == ""


def test_ambiguous_target_is_not_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return _completed(f"{TARGET_ROW}\n{TARGET_ROW}")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(
        ImportMeasurementError, match="multiple import-time events"
    ) as found:
        measure_import("sample")
    assert found.value.kind == "ambiguous-target"


def test_public_measurement_model_is_consistent_and_frozen() -> None:
    event = ImportTimeEvent("sample", 4, 12, 0)
    parsed = ImportTimeParseResult((event,), ())
    value = ImportMeasurement(
        "sample", str(Path(sys.executable).resolve()), parsed, event
    )
    assert value.target_event in value.parsed.events
    with pytest.raises(FrozenInstanceError):
        value.module = "other"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("module", "executable", "parsed", "event", "message"),
    (
        ("bad-name", "absolute", "valid", "valid", "dotted Python module name"),
        ("sample", 42, "valid", "valid", "absolute path"),
        ("sample", "relative", "valid", "valid", "absolute path"),
        ("sample", "absolute", "bad", "valid", "ImportTimeParseResult"),
        ("sample", "absolute", "valid", "bad", "ImportTimeEvent"),
        ("sample", "absolute", "empty", "valid", "only matching parsed event"),
        ("sample", "absolute", "duplicate", "valid", "only matching parsed event"),
        ("sample", "absolute", "valid", "other", "only matching parsed event"),
    ),
)
def test_public_measurement_model_rejects_inconsistent_values(
    module: str,
    executable: object,
    parsed: str,
    event: str,
    message: str,
) -> None:
    target = ImportTimeEvent("sample", 4, 12, 0)
    selected_executable: object = (
        str(Path(sys.executable).resolve()) if executable == "absolute" else executable
    )
    selected_parsed: object = {
        "valid": ImportTimeParseResult((target,), ()),
        "empty": ImportTimeParseResult(),
        "duplicate": ImportTimeParseResult((target, target), ()),
    }.get(parsed, "not parsed")
    selected_event: object = (
        target
        if event == "valid"
        else ImportTimeEvent("other", 4, 12, 0)
        if event == "other"
        else "not an event"
    )
    with pytest.raises(ValueError, match=message):
        ImportMeasurement(
            module,
            cast(Any, selected_executable),
            cast(Any, selected_parsed),
            cast(Any, selected_event),
        )


def test_real_python_process_reports_target(tmp_path: Path) -> None:
    result = measure_import(
        "email.utils", python_executable=sys.executable, working_directory=tmp_path
    )
    assert result.target_event.module == "email.utils"
    assert result.target_event.cumulative_us >= result.target_event.self_us
    assert result.parsed.events
    assert os.path.isabs(result.python_executable)
