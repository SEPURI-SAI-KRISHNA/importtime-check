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

"""Tests for exact regression decisions and isolated identity probing."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, cast

import pytest

import importtime_check._regression as regression_module
from importtime_check import (
    Baseline,
    BaselineError,
    EnvironmentIdentity,
    ImportMeasurement,
    ImportSampleSet,
    ImportTimeEvent,
    ImportTimeParseResult,
    RegressionReport,
    SamplingPolicy,
    TargetBaseline,
    TargetRegressionResult,
    check_baseline,
    evaluate_baseline,
    probe_environment,
    record_baseline,
    refresh_baseline,
    sample_import,
)

INTERPRETER = str(Path(sys.executable).resolve())
ENV = EnvironmentIdentity("cpython", "3.11", "win32", "amd64")


def _run(
    module: str, value: int, *, detailed: bool = False, interpreter: str = INTERPRETER
) -> ImportMeasurement:
    target = ImportTimeEvent(module, 1, value, 0)
    events = (
        (
            ImportTimeEvent("first", 8, 8, 0),
            ImportTimeEvent("second", 8, 8, 0),
            ImportTimeEvent("third", 9, 9, 0),
            target,
        )
        if detailed
        else (target,)
    )
    return ImportMeasurement(
        module, interpreter, ImportTimeParseResult(events, ()), target
    )


def _set(
    module: str,
    values: tuple[int, ...],
    *,
    warmups: tuple[int, ...] = (),
    detailed: bool = False,
    interpreter: str = INTERPRETER,
) -> ImportSampleSet:
    recorded = tuple(
        _run(module, value, detailed=detailed, interpreter=interpreter)
        for value in values
    )
    warmup_runs = tuple(
        _run(module, value, interpreter=interpreter) for value in warmups
    )
    median = sorted(values)[len(values) // 2]
    return ImportSampleSet(module, interpreter, warmup_runs, recorded, median)


def _baseline(
    *,
    baseline_us: int = 100,
    absolute_us: int = 5,
    percent: str = "10",
    modules: tuple[str, ...] = ("sample",),
    warmups: int = 0,
    samples: int = 1,
) -> Baseline:
    return Baseline(
        ENV,
        SamplingPolicy(warmups, samples),
        {
            module: TargetBaseline(baseline_us, absolute_us, percent)
            for module in modules
        },
    )


@pytest.mark.parametrize(
    ("baseline_us", "absolute", "percent", "current", "expected"),
    (
        (100, 5, "10", 95, "pass"),
        (100, 5, "10", 100, "pass"),
        (100, 5, "0", 105, "pass"),
        (100, 0, "10", 110, "pass"),
        (100, 5, "10", 111, "regression"),
        (101, 0, "5", 106, "pass"),
        (101, 0, "5", 107, "regression"),
        (0, 5, "10", 5, "pass"),
        (0, 5, "10", 6, "regression"),
        (100, 0, "0", 101, "regression"),
        (100, 0, "0.25", 101, "regression"),
    ),
)
def test_exact_threshold_boundaries(
    baseline_us: int, absolute: int, percent: str, current: int, expected: str
) -> None:
    baseline = _baseline(baseline_us=baseline_us, absolute_us=absolute, percent=percent)
    result = evaluate_baseline(baseline, {"sample": _set("sample", (current,))}, ENV)
    assert result.status == expected
    assert result.results[0].change_us == current - baseline_us


def test_multiple_targets_sort_and_preserve_diagnostics() -> None:
    baseline = _baseline(modules=("zeta", "alpha"), samples=3, warmups=1)
    observations = {
        "zeta": _set("zeta", (110, 112, 111), warmups=(900,)),
        "alpha": _set("alpha", (100, 100, 90), warmups=(800,), detailed=True),
    }
    result = evaluate_baseline(baseline, observations, ENV)
    assert result.status == "regression"
    assert [item.module for item in result.results] == ["alpha", "zeta"]
    alpha = result.results[0]
    assert alpha.warmups_cumulative_us == (800,)
    assert alpha.samples_cumulative_us == (100, 100, 90)
    assert alpha.current_cumulative_us == 100
    assert [event.module for event in alpha.top_imports] == [
        "third",
        "first",
        "second",
        "alpha",
    ]


def test_diagnostics_use_first_median_run_and_only_five_heaviest_events() -> None:
    target = ImportTimeEvent("sample", 1, 100, 0)
    events = tuple(
        ImportTimeEvent(f"dependency_{index}", index, index, 0) for index in range(1, 7)
    )
    first = ImportMeasurement(
        "sample", INTERPRETER, ImportTimeParseResult((*events, target), ()), target
    )
    second = _run("sample", 100)
    samples = ImportSampleSet("sample", INTERPRETER, (), (first, second), 100)
    report = evaluate_baseline(_baseline(samples=2), {"sample": samples}, ENV)
    assert [event.module for event in report.results[0].top_imports] == [
        "dependency_6",
        "dependency_5",
        "dependency_4",
        "dependency_3",
        "dependency_2",
    ]


def test_record_baseline_uses_observed_medians_and_normalizes_percent() -> None:
    baseline = record_baseline(
        {
            "zeta": _set("zeta", (2, 10), warmups=(90,)),
            "alpha": _set("alpha", (3, 5), warmups=(80,)),
        },
        ENV,
        max_increase_us=2,
        max_increase_percent="5.00",
    )
    assert tuple(baseline.targets) == ("alpha", "zeta")
    assert baseline.targets["zeta"].baseline_cumulative_us == 10
    assert baseline.targets["alpha"].max_increase_percent == "5"
    assert baseline.sampling == SamplingPolicy(1, 2)


@pytest.mark.parametrize(
    ("observations", "environment", "absolute", "percent", "message"),
    (
        ({}, "valid", 0, "0", "empty"),
        ({"wrong": "valid"}, "valid", 0, "0", "module names"),
        ({"sample": "bad"}, "valid", 0, "0", "module names"),
        ({"sample": "valid"}, "bad", 0, "0", "EnvironmentIdentity"),
        ({"sample": "valid"}, "valid", True, "0", "max_increase_us"),
        ({"sample": "valid"}, "valid", 0, "bad", "max_increase_percent"),
    ),
)
def test_record_rejects_invalid_input(
    observations: dict[str, str],
    environment: str,
    absolute: object,
    percent: str,
    message: str,
) -> None:
    selected = {
        module: _set("sample", (1,)) if value == "valid" else value
        for module, value in observations.items()
    }
    with pytest.raises(ValueError, match=message):
        record_baseline(
            cast(Any, selected),
            ENV if environment == "valid" else cast(Any, environment),
            max_increase_us=cast(Any, absolute),
            max_increase_percent=percent,
        )


def test_record_rejects_mixed_settings_and_interpreters() -> None:
    with pytest.raises(ValueError, match="share sampling settings"):
        record_baseline(
            {"a": _set("a", (1,)), "b": _set("b", (1, 2))},
            ENV,
            max_increase_us=0,
            max_increase_percent="0",
        )
    with pytest.raises(ValueError, match="share sampling settings"):
        record_baseline(
            {"a": _set("a", (1,)), "b": _set("b", (1,), interpreter=str(Path.cwd()))},
            ENV,
            max_increase_us=0,
            max_increase_percent="0",
        )


def test_refresh_preserves_policy_and_changes_only_observed_medians() -> None:
    baseline = Baseline(
        ENV,
        SamplingPolicy(1, 3),
        {
            "zeta": TargetBaseline(100, 5, "10"),
            "alpha": TargetBaseline(200, 25, "2.5"),
        },
    )
    refreshed = refresh_baseline(
        baseline,
        {
            "zeta": _set("zeta", (110, 120, 115), warmups=(900,)),
            "alpha": _set("alpha", (190, 180, 200), warmups=(800,)),
        },
        ENV,
    )
    assert refreshed is not baseline
    assert refreshed.environment is baseline.environment
    assert refreshed.sampling is baseline.sampling
    assert tuple(refreshed.targets) == ("alpha", "zeta")
    assert refreshed.targets["alpha"] == TargetBaseline(190, 25, "2.5")
    assert refreshed.targets["zeta"] == TargetBaseline(115, 5, "10")
    assert baseline.targets["alpha"].baseline_cumulative_us == 200
    assert baseline.targets["zeta"].baseline_cumulative_us == 100


def test_refresh_rejects_noncomparable_or_incomplete_observations() -> None:
    baseline = _baseline(modules=("a", "b"))
    with pytest.raises(ValueError, match="Baseline"):
        refresh_baseline(cast(Any, None), {}, ENV)
    with pytest.raises(ValueError, match="mapping"):
        refresh_baseline(baseline, cast(Any, None), ENV)
    with pytest.raises(BaselineError) as identity:
        refresh_baseline(
            baseline,
            {"a": _set("a", (1,)), "b": _set("b", (2,))},
            EnvironmentIdentity("cpython", "3.12", "win32", "amd64"),
        )
    assert identity.value.kind == "environment-mismatch"
    with pytest.raises(BaselineError) as targets:
        refresh_baseline(baseline, {"a": _set("a", (1,))}, ENV)
    assert targets.value.kind == "target-set-mismatch"
    with pytest.raises(BaselineError) as extra:
        refresh_baseline(baseline, {"a": _set("a", (1,)), "c": _set("c", (2,))}, ENV)
    assert extra.value.missing == ("c",)
    assert extra.value.stale == ("b",)
    with pytest.raises(ValueError, match="module names"):
        refresh_baseline(baseline, {"a": cast(Any, "bad"), "b": _set("b", (2,))}, ENV)
    with pytest.raises(ValueError, match="module names"):
        refresh_baseline(baseline, {"a": _set("b", (1,)), "b": _set("b", (2,))}, ENV)
    with pytest.raises(ValueError, match="sampling settings"):
        refresh_baseline(baseline, {"a": _set("a", (1, 2)), "b": _set("b", (2,))}, ENV)
    with pytest.raises(BaselineError, match="different interpreters"):
        refresh_baseline(
            baseline,
            {"a": _set("a", (1,)), "b": _set("b", (2,), interpreter=str(Path.cwd()))},
            ENV,
        )


def test_evaluation_rejects_noncomparable_data() -> None:
    baseline = _baseline(modules=("a", "b"))
    with pytest.raises(BaselineError) as mismatch:
        evaluate_baseline(baseline, {"a": _set("a", (1,))}, ENV)
    assert mismatch.value.kind == "target-set-mismatch"
    assert mismatch.value.missing == ()
    assert mismatch.value.stale == ("b",)
    with pytest.raises(BaselineError) as extra:
        evaluate_baseline(baseline, {"a": _set("a", (1,)), "c": _set("c", (1,))}, ENV)
    assert extra.value.missing == ("c",)
    assert extra.value.stale == ("b",)
    with pytest.raises(BaselineError) as environment:
        evaluate_baseline(
            baseline,
            {"a": _set("a", (1,))},
            EnvironmentIdentity("cpython", "3.12", "win32", "amd64"),
        )
    assert environment.value.kind == "environment-mismatch"


def test_evaluation_rejects_wrong_sample_values() -> None:
    baseline = _baseline()
    with pytest.raises(ValueError, match="module names"):
        evaluate_baseline(baseline, {"sample": cast(Any, "bad")}, ENV)
    with pytest.raises(ValueError, match="module names"):
        evaluate_baseline(baseline, {"sample": _set("other", (1,))}, ENV)
    with pytest.raises(ValueError, match="sampling settings"):
        evaluate_baseline(baseline, {"sample": _set("sample", (1, 2))}, ENV)
    two = _baseline(modules=("a", "b"))
    with pytest.raises(BaselineError, match="different interpreters"):
        evaluate_baseline(
            two,
            {"a": _set("a", (1,)), "b": _set("b", (1,), interpreter=str(Path.cwd()))},
            ENV,
        )


def test_report_values_are_frozen_and_ordered() -> None:
    result = evaluate_baseline(_baseline(), {"sample": _set("sample", (100,))}, ENV)
    with pytest.raises(FrozenInstanceError):
        result.results = ()  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.results[0].status = "regression"  # type: ignore[misc]
    item = result.results[0]
    copied = TargetRegressionResult(
        item.module,
        item.status,
        item.baseline_cumulative_us,
        item.current_cumulative_us,
        item.change_us,
        item.max_increase_us,
        item.max_increase_percent,
        cast(Any, [1]),
        cast(Any, [2]),
        cast(Any, [item.top_imports[0]]),
    )
    assert isinstance(copied.warmups_cumulative_us, tuple)
    assert isinstance(copied.samples_cumulative_us, tuple)
    assert isinstance(copied.top_imports, tuple)
    assert isinstance(RegressionReport(ENV, cast(Any, [item])).results, tuple)
    with pytest.raises(ValueError, match="results"):
        RegressionReport(ENV, ())
    with pytest.raises(ValueError, match="results"):
        RegressionReport(ENV, cast(Any, ("bad",)))
    with pytest.raises(ValueError, match="sorted order"):
        RegressionReport(ENV, (item, item))


def _identity_json() -> str:
    return json.dumps(
        {
            "implementation": "cpython",
            "python": "3.11",
            "platform": "win32",
            "machine": "AMD64",
        }
    )


def test_probe_passes_isolated_argv_and_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, _identity_json(), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("IMPORTTIME_PROBE_TEST", "snapshot")
    identity = probe_environment(
        python_executable=sys.executable,
        timeout_seconds=4,
        working_directory=tmp_path,
        profile="ci",
    )
    assert identity == EnvironmentIdentity("cpython", "3.11", "win32", "amd64", "ci")
    assert captured["command"][:3] == [INTERPRETER, "-I", "-c"]
    assert captured["cwd"] == tmp_path.resolve()
    assert captured["timeout"] == 4.0
    assert captured["env"]["IMPORTTIME_PROBE_TEST"] == "snapshot"
    assert captured["stdin"] == subprocess.DEVNULL
    assert captured["capture_output"] is True
    assert captured["shell"] is False
    assert captured["encoding"] == "utf-8"


@pytest.mark.parametrize("profile", ("", " ", 3))
def test_probe_rejects_invalid_profile_before_launch(
    monkeypatch: pytest.MonkeyPatch, profile: object
) -> None:
    def unexpected_run(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("probe should not start")

    monkeypatch.setattr(subprocess, "run", unexpected_run)
    with pytest.raises(ValueError, match="profile"):
        probe_environment(profile=cast(Any, profile))


@pytest.mark.parametrize(
    "failure",
    (FileNotFoundError("missing python"), subprocess.TimeoutExpired("python", 2)),
)
def test_probe_wraps_launch_and_timeout(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    def fake_run(*args: Any, **kwargs: Any) -> None:
        raise failure

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(BaselineError) as found:
        probe_environment()
    assert found.value.kind == "interpreter-probe-failed"
    assert found.value.__cause__ is failure


@pytest.mark.parametrize(
    ("returncode", "stdout"),
    (
        (7, ""),
        (0, "{"),
        (0, "[]"),
        (
            0,
            '{"implementation":"pypy","python":"3.11","platform":"win32","machine":"amd64"}',
        ),
    ),
)
def test_probe_rejects_invalid_response(
    monkeypatch: pytest.MonkeyPatch, returncode: int, stdout: str
) -> None:
    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], returncode, stdout, "failure")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(BaselineError) as found:
        probe_environment()
    assert found.value.kind == "interpreter-probe-failed"


def test_check_preflights_targets_and_environment_before_sampling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_probe(**kwargs: Any) -> EnvironmentIdentity:
        calls.append("probe")
        return ENV

    def fake_sample(module: str, **kwargs: Any) -> ImportSampleSet:
        calls.append(module)
        assert kwargs["python_executable"] == INTERPRETER
        assert kwargs["warmups"] == 0
        assert kwargs["samples"] == 1
        return _set(module, (100,))

    monkeypatch.setattr(regression_module, "probe_environment", fake_probe)
    monkeypatch.setattr(regression_module, "sample_import", fake_sample)
    baseline = _baseline(modules=("zeta", "alpha"))
    report = check_baseline(baseline, python_executable=sys.executable)
    assert report.status == "pass"
    assert calls == ["probe", "alpha", "zeta"]
    calls.clear()
    with pytest.raises(BaselineError) as duplicate:
        check_baseline(baseline, modules=("alpha", "alpha"))
    assert duplicate.value.kind == "target-set-mismatch"
    with pytest.raises(ValueError, match="dotted"):
        check_baseline(baseline, modules=("bad-name",))
    assert calls == []


def test_check_rejects_environment_mismatch_without_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_probe(**kwargs: Any) -> EnvironmentIdentity:
        return EnvironmentIdentity("cpython", "3.12", "win32", "amd64")

    def unexpected_sample(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("target import should not start")

    monkeypatch.setattr(regression_module, "probe_environment", fake_probe)
    monkeypatch.setattr(regression_module, "sample_import", unexpected_sample)
    with pytest.raises(BaselineError) as found:
        check_baseline(_baseline())
    assert found.value.kind == "environment-mismatch"


def test_real_interpreter_identity_probe() -> None:
    identity = probe_environment()
    assert identity.implementation == "cpython"
    assert identity.python == f"{sys.version_info.major}.{sys.version_info.minor}"
    assert identity.platform == sys.platform
    assert identity.machine
    assert os.path.isabs(sys.executable)


def test_real_record_and_check_share_the_engine(tmp_path: Path) -> None:
    environment = probe_environment(working_directory=tmp_path)
    observation = sample_import(
        "email.utils", warmups=0, samples=1, working_directory=tmp_path
    )
    baseline = record_baseline(
        {"email.utils": observation},
        environment,
        max_increase_us=1_000_000_000,
        max_increase_percent="0",
    )
    report = check_baseline(baseline, working_directory=tmp_path)
    assert report.status == "pass"
    assert report.results[0].module == "email.utils"
