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

"""Repeat isolated imports and aggregate recorded target observations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ._measurement import (
    ImportMeasurement,
    ImportMeasurementError,
    _interpreter_path,
    _measure_import_validated,
    _timeout,
    _validate_module_name,
    _working_directory,
)


def _count(value: int, name: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer at least {minimum}")
    return value


def _upper_median(measurements: tuple[ImportMeasurement, ...]) -> int:
    observations = sorted(item.target_event.cumulative_us for item in measurements)
    return observations[len(observations) // 2]


@dataclass(frozen=True, slots=True)
class ImportSampleSet:
    """Ordered warmups, recorded samples, and their observed upper median."""

    module: str
    python_executable: str
    warmups: tuple[ImportMeasurement, ...]
    samples: tuple[ImportMeasurement, ...]
    median_cumulative_us: int

    def __post_init__(self) -> None:
        """Copy collections and reject inconsistent manually constructed sets."""
        _validate_module_name(self.module)
        if (
            not isinstance(self.python_executable, str)
            or not Path(self.python_executable).is_absolute()
        ):
            raise ValueError("python_executable must be an absolute path")
        try:
            warmups = tuple(self.warmups)
            samples = tuple(self.samples)
        except TypeError as error:
            raise ValueError("warmups and samples must be collections") from error
        if not samples:
            raise ValueError("samples must contain at least one measurement")
        if any(
            not isinstance(item, ImportMeasurement)
            or item.module != self.module
            or item.python_executable != self.python_executable
            for item in (*warmups, *samples)
        ):
            raise ValueError("measurements must share the target and interpreter")
        if (
            isinstance(self.median_cumulative_us, bool)
            or not isinstance(self.median_cumulative_us, int)
            or self.median_cumulative_us != _upper_median(samples)
        ):
            raise ValueError("median_cumulative_us must be the recorded upper median")
        object.__setattr__(self, "warmups", warmups)
        object.__setattr__(self, "samples", samples)


def sample_import(
    module: str,
    *,
    python_executable: str | os.PathLike[str] | None = None,
    timeout_seconds: float = 30.0,
    working_directory: str | os.PathLike[str] | None = None,
    warmups: int = 1,
    samples: int = 5,
) -> ImportSampleSet:
    """Run fresh child processes and return an upper-median target timing."""
    _validate_module_name(module)
    interpreter = _interpreter_path(python_executable)
    timeout = _timeout(timeout_seconds)
    directory = _working_directory(working_directory)
    warmup_count = _count(warmups, "warmups", 0)
    sample_count = _count(samples, "samples", 1)
    environment = os.environ.copy()

    def run(phase: Literal["warmup", "sample"], number: int) -> ImportMeasurement:
        try:
            return _measure_import_validated(
                module, interpreter, timeout, directory, environment
            )
        except ImportMeasurementError as error:
            error.run_phase = phase
            error.run_number = number
            error.args = (
                f"{error.kind} while measuring {module!r} "
                f"({phase} {number}): {error.reason}",
            )
            raise

    completed_warmups = tuple(
        run("warmup", number) for number in range(1, warmup_count + 1)
    )
    completed_samples = tuple(
        run("sample", number) for number in range(1, sample_count + 1)
    )
    return ImportSampleSet(
        module,
        interpreter,
        completed_warmups,
        completed_samples,
        _upper_median(completed_samples),
    )
