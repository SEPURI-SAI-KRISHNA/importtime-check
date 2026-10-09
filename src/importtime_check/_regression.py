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

"""Pure regression decisions and optional isolated measurement orchestration."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from ._baseline import (
    Baseline,
    BaselineError,
    EnvironmentIdentity,
    SamplingPolicy,
    TargetBaseline,
    _nonnegative_int,
    _percent,
    _percent_ratio,
)
from ._measurement import (
    _interpreter_path,
    _timeout,
    _validate_module_name,
    _working_directory,
)
from ._model import ImportTimeEvent
from ._sampling import ImportSampleSet, sample_import

_PROBE = (
    "import json,platform,sys;"
    "print(json.dumps({'implementation':sys.implementation.name,"
    "'python':f'{sys.version_info.major}.{sys.version_info.minor}',"
    "'platform':sys.platform,'machine':platform.machine()}))"
)


@dataclass(frozen=True, slots=True)
class TargetRegressionResult:
    """One comparable target's decision and deterministic diagnostics."""

    module: str
    status: Literal["pass", "regression"]
    baseline_cumulative_us: int
    current_cumulative_us: int
    change_us: int
    max_increase_us: int
    max_increase_percent: str
    warmups_cumulative_us: tuple[int, ...]
    samples_cumulative_us: tuple[int, ...]
    top_imports: tuple[ImportTimeEvent, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "warmups_cumulative_us", tuple(self.warmups_cumulative_us)
        )
        object.__setattr__(
            self, "samples_cumulative_us", tuple(self.samples_cumulative_us)
        )
        object.__setattr__(self, "top_imports", tuple(self.top_imports))


@dataclass(frozen=True, slots=True)
class RegressionReport:
    """One complete comparable verdict consumed by all presentation layers."""

    environment: EnvironmentIdentity
    results: tuple[TargetRegressionResult, ...]

    def __post_init__(self) -> None:
        results = tuple(self.results)
        if not results or any(
            not isinstance(item, TargetRegressionResult) for item in results
        ):
            raise ValueError("results must contain target regression results")
        modules = [item.module for item in results]
        if modules != sorted(set(modules)):
            raise ValueError("results must have unique modules in sorted order")
        object.__setattr__(self, "results", results)

    @property
    def status(self) -> Literal["pass", "regression"]:
        """A report regresses when any target does."""
        return (
            "regression"
            if any(item.status == "regression" for item in self.results)
            else "pass"
        )


def _target_set(baseline: Baseline, modules: Sequence[str]) -> tuple[str, ...]:
    for module in modules:
        _validate_module_name(module)
    if len(modules) != len(set(modules)):
        raise BaselineError(
            "target-set-mismatch", "requested targets contain duplicates"
        )
    current = set(modules)
    expected = set(baseline.targets)
    missing = tuple(sorted(current - expected))
    stale = tuple(sorted(expected - current))
    if missing or stale:
        raise BaselineError(
            "target-set-mismatch",
            f"target set differs: missing={missing}, stale={stale}",
            missing=missing,
            stale=stale,
        )
    return tuple(sorted(current))


def _require_same_environment(
    baseline: Baseline, environment: EnvironmentIdentity
) -> None:
    if environment != baseline.environment:
        raise BaselineError(
            "environment-mismatch", "current environment differs from baseline"
        )


def record_baseline(
    observations: Mapping[str, ImportSampleSet],
    environment: EnvironmentIdentity,
    *,
    max_increase_us: int,
    max_increase_percent: str,
) -> Baseline:
    """Construct a reviewable baseline from complete observed sample sets."""
    allowance = _nonnegative_int(max_increase_us, "max_increase_us")
    percent = _percent(max_increase_percent)
    if not isinstance(environment, EnvironmentIdentity):
        raise ValueError("environment must be an EnvironmentIdentity")
    if not observations:
        raise ValueError("observations must not be empty")
    counts: set[tuple[int, int]] = set()
    interpreters: set[str] = set()
    targets: dict[str, TargetBaseline] = {}
    for module, sample_set in observations.items():
        _validate_module_name(module)
        if not isinstance(sample_set, ImportSampleSet) or sample_set.module != module:
            raise ValueError("observations must match their module names")
        counts.add((len(sample_set.warmups), len(sample_set.samples)))
        interpreters.add(sample_set.python_executable)
        targets[module] = TargetBaseline(
            sample_set.median_cumulative_us, allowance, percent
        )
    if len(counts) != 1 or len(interpreters) != 1:
        raise ValueError("observations must share sampling settings and interpreter")
    warmups, samples = counts.pop()
    return Baseline(environment, SamplingPolicy(warmups, samples), targets)


def refresh_baseline(
    baseline: Baseline,
    observations: Mapping[str, ImportSampleSet],
    environment: EnvironmentIdentity,
) -> Baseline:
    """Replace only recorded medians in a complete, comparable baseline."""
    if not isinstance(baseline, Baseline):
        raise ValueError("baseline must be a Baseline")
    if not isinstance(observations, Mapping):
        raise ValueError("observations must be a mapping")
    _require_same_environment(baseline, environment)
    modules = _target_set(baseline, tuple(observations))
    interpreters: set[str] = set()
    targets: dict[str, TargetBaseline] = {}
    for module in modules:
        sample_set = observations[module]
        if not isinstance(sample_set, ImportSampleSet) or sample_set.module != module:
            raise ValueError("observations must match their module names")
        if (
            len(sample_set.warmups) != baseline.sampling.warmups
            or len(sample_set.samples) != baseline.sampling.samples
        ):
            raise ValueError("observations must match baseline sampling settings")
        interpreters.add(sample_set.python_executable)
        old = baseline.targets[module]
        targets[module] = TargetBaseline(
            sample_set.median_cumulative_us,
            old.max_increase_us,
            old.max_increase_percent,
        )
    if len(interpreters) != 1:
        raise BaselineError(
            "environment-mismatch", "samples use different interpreters"
        )
    return Baseline(baseline.environment, baseline.sampling, targets)


def evaluate_baseline(
    baseline: Baseline,
    observations: Mapping[str, ImportSampleSet],
    environment: EnvironmentIdentity,
) -> RegressionReport:
    """Make an exact, side-effect-free decision from complete sample sets."""
    _require_same_environment(baseline, environment)
    modules = _target_set(baseline, tuple(observations))
    results: list[TargetRegressionResult] = []
    interpreters: set[str] = set()
    for module in modules:
        sample_set = observations[module]
        if not isinstance(sample_set, ImportSampleSet) or sample_set.module != module:
            raise ValueError("observations must match their module names")
        if (
            len(sample_set.warmups) != baseline.sampling.warmups
            or len(sample_set.samples) != baseline.sampling.samples
        ):
            raise ValueError("observations must match baseline sampling settings")
        interpreters.add(sample_set.python_executable)
        target = baseline.targets[module]
        baseline_us = target.baseline_cumulative_us
        current_us = sample_set.median_cumulative_us
        change_us = current_us - baseline_us
        increase = max(change_us, 0)
        digits, scale = _percent_ratio(target.max_increase_percent)
        regression = (
            increase > target.max_increase_us
            and 100 * increase * scale > baseline_us * digits
        )
        representative = next(
            item
            for item in sample_set.samples
            if item.target_event.cumulative_us == current_us
        )
        results.append(
            TargetRegressionResult(
                module=module,
                status="regression" if regression else "pass",
                baseline_cumulative_us=baseline_us,
                current_cumulative_us=current_us,
                change_us=change_us,
                max_increase_us=target.max_increase_us,
                max_increase_percent=target.max_increase_percent,
                warmups_cumulative_us=tuple(
                    item.target_event.cumulative_us for item in sample_set.warmups
                ),
                samples_cumulative_us=tuple(
                    item.target_event.cumulative_us for item in sample_set.samples
                ),
                top_imports=tuple(
                    sorted(
                        representative.parsed.events, key=lambda event: -event.self_us
                    )[:5]
                ),
            )
        )
    if len(interpreters) != 1:
        raise BaselineError(
            "environment-mismatch", "samples use different interpreters"
        )
    return RegressionReport(environment, tuple(results))


def probe_environment(
    *,
    python_executable: str | os.PathLike[str] | None = None,
    timeout_seconds: float = 30.0,
    working_directory: str | os.PathLike[str] | None = None,
    profile: str = "default",
) -> EnvironmentIdentity:
    """Ask the selected interpreter for comparable environment attributes."""
    interpreter = _interpreter_path(python_executable)
    timeout = _timeout(timeout_seconds)
    directory = _working_directory(working_directory)
    if not isinstance(profile, str) or not profile.strip():
        raise ValueError("profile must be non-blank")
    try:
        completed = subprocess.run(
            [interpreter, "-I", "-c", _PROBE],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            cwd=directory,
            env=os.environ.copy(),
            shell=False,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BaselineError("interpreter-probe-failed", str(error)) from error
    if completed.returncode != 0:
        raise BaselineError(
            "interpreter-probe-failed",
            f"interpreter exited with code {completed.returncode}",
        )
    try:
        details: Any = json.loads(completed.stdout)
        if not isinstance(details, dict) or set(details) != {
            "implementation",
            "python",
            "platform",
            "machine",
        }:
            raise ValueError("interpreter returned invalid identity")
        return EnvironmentIdentity(**details, profile=profile)
    except (TypeError, ValueError) as error:
        raise BaselineError("interpreter-probe-failed", str(error)) from error


def check_baseline(
    baseline: Baseline,
    *,
    python_executable: str | os.PathLike[str] | None = None,
    timeout_seconds: float = 30.0,
    working_directory: str | os.PathLike[str] | None = None,
    profile: str = "default",
    modules: Sequence[str] | None = None,
) -> RegressionReport:
    """Check every requested target using the one shared decision engine."""
    requested = _target_set(
        baseline, tuple(baseline.targets) if modules is None else modules
    )
    interpreter = _interpreter_path(python_executable)
    environment = probe_environment(
        python_executable=interpreter,
        timeout_seconds=timeout_seconds,
        working_directory=working_directory,
        profile=profile,
    )
    _require_same_environment(baseline, environment)
    observations = {
        module: sample_import(
            module,
            python_executable=interpreter,
            timeout_seconds=timeout_seconds,
            working_directory=working_directory,
            warmups=baseline.sampling.warmups,
            samples=baseline.sampling.samples,
        )
        for module in requested
    }
    return evaluate_baseline(baseline, observations, environment)
