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

"""Tests for deterministic repeated import measurements."""

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
    ImportSampleSet,
    ImportTimeEvent,
    ImportTimeParseError,
    ImportTimeParseResult,
    sample_import,
    sample_imports,
)


def _measurement(
    cumulative_us: int,
    *,
    module: str = "sample",
    interpreter: str | None = None,
) -> ImportMeasurement:
    event = ImportTimeEvent(module, 1, cumulative_us, 0)
    return ImportMeasurement(
        module,
        interpreter or str(Path(sys.executable).resolve()),
        ImportTimeParseResult((event,), ()),
        event,
    )


def test_sampling_runs_in_order_with_one_environment_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    values = (99, 7, 3, 5, 8, 1)
    calls: list[tuple[list[str], dict[str, Any]]] = []
    monkeypatch.setenv("IMPORTTIME_CHECK_SNAPSHOT", "original")

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        if len(calls) == 1:
            monkeypatch.setenv("IMPORTTIME_CHECK_SNAPSHOT", "changed")
        value = values[len(calls) - 1]
        return subprocess.CompletedProcess(
            command, 0, None, f"import time: 1 | {value} | sample"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = sample_import(
        "sample",
        python_executable=sys.executable,
        timeout_seconds=4,
        working_directory=tmp_path,
    )

    assert len(calls) == 6
    assert [run.target_event.cumulative_us for run in result.warmups] == [99]
    assert [run.target_event.cumulative_us for run in result.samples] == [7, 3, 5, 8, 1]
    assert result.median_cumulative_us == 5
    assert result.module == "sample"
    assert result.python_executable == str(Path(sys.executable).resolve())
    assert all(command == calls[0][0] for command, _ in calls)
    assert all(options["cwd"] == tmp_path.resolve() for _, options in calls)
    assert all(options["timeout"] == 4.0 for _, options in calls)
    assert all(options["env"] is calls[0][1]["env"] for _, options in calls)
    assert all(
        options["env"]["IMPORTTIME_CHECK_SNAPSHOT"] == "original"
        for _, options in calls
    )


def test_zero_warmups_and_even_samples_use_observed_upper_median(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = iter((2, 10))

    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        value = next(values)
        return subprocess.CompletedProcess(
            [], 0, None, f"import time: 1 | {value} | sample"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = sample_import("sample", warmups=0, samples=2)
    assert result.warmups == ()
    assert len(result.samples) == 2
    assert result.median_cumulative_us == 10


@pytest.mark.parametrize(
    ("keyword", "value", "message"),
    (
        ("warmups", True, "warmups"),
        ("warmups", -1, "warmups"),
        ("warmups", 1.5, "warmups"),
        ("samples", False, "samples"),
        ("samples", 0, "samples"),
        ("samples", 1.5, "samples"),
        ("timeout_seconds", math.inf, "timeout_seconds"),
        ("python_executable", "python", "python_executable"),
        ("working_directory", "", "working_directory"),
    ),
)
def test_invalid_configuration_starts_no_child(
    monkeypatch: pytest.MonkeyPatch, keyword: str, value: object, message: str
) -> None:
    def unexpected_run(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("subprocess should not start")

    monkeypatch.setattr(subprocess, "run", unexpected_run)
    with pytest.raises(ValueError, match=message):
        sample_import("sample", **cast(Any, {keyword: value}))


def test_invalid_target_starts_no_child(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_run(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("subprocess should not start")

    monkeypatch.setattr(subprocess, "run", unexpected_run)
    with pytest.raises(ValueError, match="dotted Python module name"):
        sample_import("bad-name")


@pytest.mark.parametrize(
    ("failure_call", "phase", "number"),
    ((2, "warmup", 2), (3, "sample", 1), (4, "sample", 2)),
)
def test_failure_reports_phase_and_one_based_index_without_retry(
    monkeypatch: pytest.MonkeyPatch, failure_call: int, phase: str, number: int
) -> None:
    calls = 0

    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == failure_call:
            return subprocess.CompletedProcess([], 7, None, "target failed")
        return subprocess.CompletedProcess([], 0, None, "import time: 1 | 2 | sample")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ImportMeasurementError, match=f"{phase} {number}") as found:
        sample_import("sample", warmups=2, samples=3)
    assert calls == failure_call
    assert found.value.kind == "exit"
    assert found.value.run_phase == phase
    assert found.value.run_number == number
    assert found.value.returncode == 7
    assert found.value.stderr == "target failed"


def test_parse_failure_preserves_direct_cause_and_run_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, None, "import time: malformed")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ImportMeasurementError, match="sample 1") as found:
        sample_import("sample", warmups=0, samples=2)
    assert found.value.kind == "parse"
    assert found.value.run_phase == "sample"
    assert found.value.run_number == 1
    assert isinstance(found.value.__cause__, ImportTimeParseError)


def test_sample_set_copies_collections_and_is_frozen() -> None:
    interpreter = str(Path(sys.executable).resolve())
    warmups = [_measurement(90)]
    samples = [_measurement(2), _measurement(10)]
    result = ImportSampleSet(
        "sample", interpreter, cast(Any, warmups), cast(Any, samples), 10
    )
    warmups.clear()
    samples.clear()
    assert len(result.warmups) == 1
    assert len(result.samples) == 2
    assert result.median_cumulative_us == 10
    with pytest.raises(FrozenInstanceError):
        result.samples = ()  # type: ignore[misc]


@pytest.mark.parametrize(
    ("module", "interpreter", "warmups", "samples", "median", "message"),
    (
        ("bad-name", "absolute", (), ("valid",), 4, "dotted Python module name"),
        ("sample", "relative", (), ("valid",), 4, "absolute path"),
        ("sample", 42, (), ("valid",), 4, "absolute path"),
        ("sample", "absolute", 42, ("valid",), 4, "collections"),
        ("sample", "absolute", (), 42, 4, "collections"),
        ("sample", "absolute", (), (), 4, "at least one"),
        ("sample", "absolute", ("invalid",), ("valid",), 4, "share the target"),
        ("sample", "absolute", (), ("wrong-target",), 4, "share the target"),
        ("sample", "absolute", (), ("wrong-interpreter",), 4, "share the target"),
        ("sample", "absolute", (), ("valid",), True, "upper median"),
        ("sample", "absolute", (), ("valid",), "4", "upper median"),
        ("sample", "absolute", (), ("valid",), 5, "upper median"),
    ),
)
def test_sample_set_rejects_inconsistent_values(
    module: str,
    interpreter: object,
    warmups: object,
    samples: object,
    median: object,
    message: str,
) -> None:
    executable = str(Path(sys.executable).resolve())
    selected_interpreter = executable if interpreter == "absolute" else interpreter
    alternatives: dict[str, object] = {
        "valid": _measurement(4),
        "wrong-target": _measurement(4, module="other"),
        "wrong-interpreter": _measurement(4, interpreter=str(Path.cwd().resolve())),
        "invalid": "not a measurement",
    }
    selected_warmups = (
        tuple(alternatives[item] for item in warmups)
        if isinstance(warmups, tuple)
        else warmups
    )
    selected_samples = (
        tuple(alternatives[item] for item in samples)
        if isinstance(samples, tuple)
        else samples
    )
    with pytest.raises(ValueError, match=message):
        ImportSampleSet(
            module,
            cast(Any, selected_interpreter),
            cast(Any, selected_warmups),
            cast(Any, selected_samples),
            cast(Any, median),
        )


def test_real_interpreter_sampling_uses_complete_observations(tmp_path: Path) -> None:
    result = sample_import(
        "email.utils",
        python_executable=sys.executable,
        working_directory=tmp_path,
        warmups=0,
        samples=2,
    )
    assert len(result.samples) == 2
    assert result.median_cumulative_us in {
        run.target_event.cumulative_us for run in result.samples
    }
    assert all(run.module == "email.utils" for run in result.samples)
    assert os.path.isabs(result.python_executable)


def test_batch_samples_sorted_targets_with_one_runtime_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    values = {"alpha": (40, 2, 8), "zeta": (50, 6, 10)}
    counts = {"alpha": 0, "zeta": 0}
    calls: list[tuple[list[str], dict[str, Any]]] = []
    monkeypatch.setenv("IMPORTTIME_CHECK_SNAPSHOT", "original")

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        if len(calls) == 1:
            monkeypatch.setenv("IMPORTTIME_CHECK_SNAPSHOT", "changed")
        module = command[-1]
        number = counts[module]
        counts[module] += 1
        return subprocess.CompletedProcess(
            command, 0, None, f"import time: 1 | {values[module][number]} | {module}"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    results = sample_imports(
        ["zeta", "alpha"],
        python_executable=sys.executable,
        timeout_seconds=4,
        working_directory=tmp_path,
        warmups=1,
        samples=2,
    )

    assert isinstance(results, tuple)
    assert [result.module for result in results] == ["alpha", "zeta"]
    assert [command[-1] for command, _ in calls] == [
        "alpha",
        "alpha",
        "alpha",
        "zeta",
        "zeta",
        "zeta",
    ]
    assert len({id(command) for command, _ in calls}) == 6
    assert [run.target_event.cumulative_us for run in results[0].warmups] == [40]
    assert [run.target_event.cumulative_us for run in results[0].samples] == [2, 8]
    assert [run.target_event.cumulative_us for run in results[1].warmups] == [50]
    assert [run.target_event.cumulative_us for run in results[1].samples] == [6, 10]
    assert [result.median_cumulative_us for result in results] == [8, 10]
    assert all(
        result.python_executable == str(Path(sys.executable).resolve())
        for result in results
    )
    assert all(options["cwd"] == tmp_path.resolve() for _, options in calls)
    assert all(options["timeout"] == 4.0 for _, options in calls)
    assert all(options["env"] is calls[0][1]["env"] for _, options in calls)
    assert all(
        options["env"]["IMPORTTIME_CHECK_SNAPSHOT"] == "original"
        for _, options in calls
    )
    with pytest.raises(FrozenInstanceError):
        results[0].samples = ()  # type: ignore[misc]


@pytest.mark.parametrize(
    ("modules", "message"),
    (
        (None, "non-empty sequence"),
        (42, "non-empty sequence"),
        ("alpha", "non-empty sequence"),
        (b"alpha", "non-empty sequence"),
        (iter(("alpha",)), "non-empty sequence"),
        ((), "non-empty sequence"),
        ([], "non-empty sequence"),
        (("alpha", "alpha"), "distinct module names"),
        (("alpha", "bad-name"), "dotted Python module name"),
        (("alpha", 42), "dotted Python module name"),
    ),
    ids=(
        "none",
        "integer",
        "string",
        "bytes",
        "iterator",
        "empty-tuple",
        "empty-list",
        "duplicate",
        "invalid-name",
        "invalid-type",
    ),
)
def test_batch_rejects_invalid_target_sets_before_starting_a_child(
    monkeypatch: pytest.MonkeyPatch, modules: object, message: str
) -> None:
    def unexpected_run(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("subprocess should not start")

    monkeypatch.setattr(subprocess, "run", unexpected_run)
    with pytest.raises(ValueError, match=message):
        sample_imports(cast(Any, modules))


@pytest.mark.parametrize(
    ("keyword", "value", "message"),
    (
        ("python_executable", "python", "python_executable"),
        ("timeout_seconds", 0, "timeout_seconds"),
        ("working_directory", "", "working_directory"),
        ("warmups", True, "warmups"),
        ("samples", 0, "samples"),
    ),
)
def test_batch_rejects_invalid_runtime_before_starting_a_child(
    monkeypatch: pytest.MonkeyPatch, keyword: str, value: object, message: str
) -> None:
    def unexpected_run(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("subprocess should not start")

    monkeypatch.setattr(subprocess, "run", unexpected_run)
    with pytest.raises(ValueError, match=message):
        sample_imports(("alpha", "zeta"), **cast(Any, {keyword: value}))


def test_later_batch_failure_reports_target_and_run_without_partial_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counts = {"alpha": 0, "zeta": 0}
    calls: list[str] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        module = command[-1]
        calls.append(module)
        counts[module] += 1
        if module == "zeta" and counts[module] == 3:
            return subprocess.CompletedProcess(command, 7, None, "target failed")
        return subprocess.CompletedProcess(
            command, 0, None, f"import time: 1 | 2 | {module}"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ImportMeasurementError, match=r"zeta.*sample 2") as found:
        sample_imports(("zeta", "alpha"), warmups=1, samples=2)
    assert calls == ["alpha", "alpha", "alpha", "zeta", "zeta", "zeta"]
    assert found.value.module == "zeta"
    assert found.value.kind == "exit"
    assert found.value.run_phase == "sample"
    assert found.value.run_number == 2
    assert found.value.returncode == 7
    assert found.value.stderr == "target failed"


def test_real_interpreter_batch_returns_complete_immutable_results(
    tmp_path: Path,
) -> None:
    results = sample_imports(
        ("json", "email.utils"),
        python_executable=sys.executable,
        working_directory=tmp_path,
        warmups=0,
        samples=1,
    )
    assert tuple(result.module for result in results) == ("email.utils", "json")
    assert all(result.warmups == () and len(result.samples) == 1 for result in results)
    assert all(
        result.median_cumulative_us == result.samples[0].target_event.cumulative_us
        for result in results
    )
