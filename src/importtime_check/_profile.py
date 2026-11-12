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

"""Opt-in, bounded capture of ordered CPython import-time profile evidence."""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from io import BufferedReader
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, cast

from ._baseline import SamplingPolicy
from ._measurement import (
    _IMPORT_SNIPPET,
    ImportMeasurement,
    ImportMeasurementError,
    _interpreter_path,
    _measurement_from_stderr,
    _timeout,
    _validate_module_name,
    _working_directory,
)
from ._measurement_report import ReportIdentity
from ._model import ImportTimeEvent
from ._regression import _PROBE
from ._sampling import _count

_MAX_STDERR_BYTES = 2 * 1024 * 1024
_MAX_EVENT_BYTES = 256
_MAX_EVENTS_PER_RUN = 5_000
_MAX_EVENTS_TOTAL = 50_000
_MAX_TIMING_US = 2**63 - 1
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ProfileErrorKind = Literal[
    "limit", "probe", "io", "oversized", "unsupported-version", "invalid"
]
_RunPhase = Literal["warmup", "sample"]


class ImportProfileError(ValueError):
    """A profile could not be captured or validated without losing evidence."""

    __slots__ = ("kind", "module", "reason", "run_number", "run_phase")

    def __init__(
        self,
        kind: _ProfileErrorKind,
        reason: str,
        *,
        module: str | None = None,
        run_phase: _RunPhase | None = None,
        run_number: int | None = None,
    ) -> None:
        self.kind = kind
        self.reason = reason
        self.module = module
        self.run_phase = run_phase
        self.run_number = run_number
        super().__init__(reason)


def _profile_module(name: str) -> None:
    _validate_module_name(name)
    if len(name.encode("utf-8")) > _MAX_EVENT_BYTES:
        raise ValueError("profile module exceeds 256 UTF-8 bytes")


@dataclass(frozen=True, slots=True)
class ProfileRun:
    """One complete run's ordered numeric rows, without unrelated stderr."""

    phase: _RunPhase
    number: int
    events: tuple[ImportTimeEvent, ...]

    def __post_init__(self) -> None:
        if self.phase not in ("warmup", "sample"):
            raise ValueError("phase must be warmup or sample")
        if type(self.number) is not int or self.number < 1:
            raise ValueError("run number must be a positive integer")
        try:
            events = tuple(self.events)
        except TypeError as error:
            raise ValueError("events must be a collection") from error
        if not 1 <= len(events) <= _MAX_EVENTS_PER_RUN:
            raise ValueError("run event count exceeds the profile limit")
        for event in events:
            if not isinstance(event, ImportTimeEvent):
                raise ValueError("events must contain ImportTimeEvent values")
            _profile_module(event.module)
            if (
                event.self_us > _MAX_TIMING_US
                or event.cumulative_us > _MAX_TIMING_US
                or event.depth > _MAX_EVENTS_PER_RUN
            ):
                raise ValueError("profile event value exceeds the supported range")
        object.__setattr__(self, "events", events)


@dataclass(frozen=True, slots=True)
class ProfileTarget:
    """Complete warmup and sample traces for one selected target."""

    module: str
    runs: tuple[ProfileRun, ...]

    def __post_init__(self) -> None:
        _profile_module(self.module)
        try:
            runs = tuple(self.runs)
        except TypeError as error:
            raise ValueError("runs must be a collection") from error
        if not 1 <= len(runs) <= 25:
            raise ValueError("target run count exceeds the profile limit")
        for run in runs:
            if not isinstance(run, ProfileRun):
                raise ValueError("runs must contain ProfileRun values")
            if sum(event.module == self.module for event in run.events) != 1:
                raise ValueError("each run must have exactly one target event")
        object.__setattr__(self, "runs", runs)


@dataclass(frozen=True, slots=True)
class ImportProfile:
    """Immutable, observation-only evidence from complete isolated runs."""

    environment: ReportIdentity
    sampling: SamplingPolicy
    targets: Mapping[str, ProfileTarget]
    source_sha256: str | None = None
    profile_version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.environment, ReportIdentity):
            raise ValueError("environment must be a ReportIdentity")
        if not isinstance(self.sampling, SamplingPolicy):
            raise ValueError("sampling must be a SamplingPolicy")
        if not 0 <= self.sampling.warmups <= 5 or not 1 <= self.sampling.samples <= 20:
            raise ValueError("sampling counts exceed the profile limits")
        if type(self.profile_version) is not int or self.profile_version != 1:
            raise ValueError("profile_version must be 1")
        if not isinstance(self.targets, Mapping) or not 1 <= len(self.targets) <= 16:
            raise ValueError("targets must contain 1 to 16 entries")
        if len(self.targets) * (self.sampling.warmups + self.sampling.samples) > 100:
            raise ValueError("total run count exceeds the profile limit")
        expected = tuple(
            [("warmup", number) for number in range(1, self.sampling.warmups + 1)]
            + [("sample", number) for number in range(1, self.sampling.samples + 1)]
        )
        event_count = 0
        for module, target in self.targets.items():
            _profile_module(module)
            if not isinstance(target, ProfileTarget) or target.module != module:
                raise ValueError("targets must match their ProfileTarget module")
            if tuple((run.phase, run.number) for run in target.runs) != expected:
                raise ValueError("target runs must match complete sampling order")
            event_count += sum(len(run.events) for run in target.runs)
        if event_count > _MAX_EVENTS_TOTAL:
            raise ValueError("total event count exceeds the profile limit")
        if self.source_sha256 is not None and (
            not isinstance(self.source_sha256, str)
            or _DIGEST.fullmatch(self.source_sha256) is None
        ):
            raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
        object.__setattr__(
            self, "targets", MappingProxyType(dict(sorted(self.targets.items())))
        )


def _probe_identity(
    interpreter: str, timeout: float, directory: Path, environment: dict[str, str]
) -> ReportIdentity:
    """Obtain the four safe fields without importing a selected target."""
    try:
        completed = subprocess.run(
            [interpreter, "-I", "-c", _PROBE],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            cwd=directory,
            env=environment,
            shell=False,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ImportProfileError(
            "probe", "interpreter identity probe failed"
        ) from error
    if completed.returncode != 0:
        raise ImportProfileError("probe", "interpreter identity probe failed")
    try:
        details: Any = json.loads(completed.stdout)
        if not isinstance(details, dict) or set(details) != {
            "implementation",
            "python",
            "platform",
            "machine",
        }:
            raise ValueError("unexpected identity fields")
        return ReportIdentity(**cast(dict[str, str], details))
    except (TypeError, ValueError) as error:
        raise ImportProfileError("probe", "interpreter identity is invalid") from error


def _kill_and_reap(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        with suppress(OSError):
            process.kill()
    process.wait()


def _bounded_stderr(
    module: str,
    interpreter: str,
    timeout: float,
    directory: Path,
    environment: dict[str, str],
    phase: _RunPhase,
    number: int,
) -> tuple[str, int]:
    """Drain a pipe concurrently; never buffer more than the profile limit."""
    arguments = [interpreter, "-I", "-X", "importtime", "-c", _IMPORT_SNIPPET, module]
    try:
        process = subprocess.Popen(
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            cwd=directory,
            env=environment,
            shell=False,
        )
    except OSError as error:
        raise ImportMeasurementError(
            module=module,
            kind="launch",
            python_executable=interpreter,
            reason=str(error),
        ) from error

    chunks: list[bytes] = []
    total = 0
    exceeded = threading.Event()
    read_errors: list[OSError] = []

    def drain() -> None:
        nonlocal total
        stream = process.stderr
        if stream is None:
            read_errors.append(OSError("missing stderr pipe"))
            return
        try:
            while chunk := cast(BufferedReader, stream).read1(65536):
                total += len(chunk)
                if total > _MAX_STDERR_BYTES:
                    exceeded.set()
                    if process.poll() is None:
                        process.kill()
                    return
                chunks.append(chunk)
        except OSError as error:
            read_errors.append(error)
            if process.poll() is None:
                with suppress(OSError):
                    process.kill()

    reader = threading.Thread(target=drain, daemon=True)
    started = time.monotonic()
    reader.start()
    try:
        returncode = process.wait(timeout=timeout)
        remaining = max(0.05, timeout - (time.monotonic() - started))
        reader.join(timeout=remaining)
        if reader.is_alive():
            raise subprocess.TimeoutExpired(arguments, timeout)
    except subprocess.TimeoutExpired as error:
        _kill_and_reap(process)
        reader.join(timeout=0.1)
        raise ImportMeasurementError(
            module=module,
            kind="timeout",
            python_executable=interpreter,
            reason=f"child did not finish within {timeout:g} seconds",
            stderr=b"".join(chunks).decode("utf-8", errors="replace"),
        ) from error
    except BaseException:
        _kill_and_reap(process)
        reader.join(timeout=0.1)
        raise
    finally:
        if not reader.is_alive() and process.stderr is not None:
            process.stderr.close()

    if exceeded.is_set():
        raise ImportProfileError(
            "limit",
            "child stderr exceeds the 2 MiB profile limit",
            module=module,
            run_phase=phase,
            run_number=number,
        )
    if read_errors:
        raise ImportProfileError(
            "io",
            "could not read complete child stderr",
            module=module,
            run_phase=phase,
            run_number=number,
        ) from read_errors[0]
    return b"".join(chunks).decode("utf-8", errors="replace"), returncode


def _profile_measurement(
    module: str,
    interpreter: str,
    timeout: float,
    directory: Path,
    environment: dict[str, str],
    phase: _RunPhase,
    number: int,
) -> ImportMeasurement:
    stderr, returncode = _bounded_stderr(
        module, interpreter, timeout, directory, environment, phase, number
    )
    return _measurement_from_stderr(module, interpreter, stderr, returncode)


def capture_import_profile(
    modules: Sequence[str],
    *,
    python_executable: str | os.PathLike[str] | None = None,
    timeout_seconds: float = 30.0,
    working_directory: str | os.PathLike[str] | None = None,
    warmups: int = 1,
    samples: int = 5,
) -> ImportProfile:
    """Capture complete, ordered traces from fresh isolated target imports.

    The result is observation evidence only. No run is chosen as representative
    and no regression or causal claim is made. Targets must be installed in the
    selected interpreter's isolated import environment.
    """
    if not isinstance(modules, Sequence) or isinstance(modules, (str, bytes)):
        raise ValueError("modules must be a non-empty sequence of module names")
    selected = tuple(modules)
    if not 1 <= len(selected) <= 16:
        raise ValueError("modules must contain 1 to 16 distinct module names")
    for module in selected:
        _profile_module(module)
    if len(set(selected)) != len(selected):
        raise ValueError("modules must contain distinct module names")
    interpreter = _interpreter_path(python_executable)
    timeout = _timeout(timeout_seconds)
    directory = _working_directory(working_directory)
    warmup_count = _count(warmups, "warmups", 0)
    sample_count = _count(samples, "samples", 1)
    if warmup_count > 5 or sample_count > 20:
        raise ValueError("sampling counts exceed the profile limits")
    if len(selected) * (warmup_count + sample_count) > 100:
        raise ValueError("total run count exceeds the profile limit")

    environment = os.environ.copy()
    identity = _probe_identity(interpreter, timeout, directory, environment)
    captured: dict[str, ProfileTarget] = {}
    total_events = 0
    for module in sorted(selected):
        runs: list[ProfileRun] = []
        for phase, count in (("warmup", warmup_count), ("sample", sample_count)):
            for number in range(1, count + 1):
                try:
                    measurement = _profile_measurement(
                        module,
                        interpreter,
                        timeout,
                        directory,
                        environment,
                        cast(_RunPhase, phase),
                        number,
                    )
                except ImportMeasurementError as error:
                    error.run_phase = cast(_RunPhase, phase)
                    error.run_number = number
                    error.args = (
                        f"{error.kind} while measuring {module!r} "
                        f"({phase} {number}): {error.reason}",
                    )
                    raise
                events = measurement.parsed.events
                if len(events) > _MAX_EVENTS_PER_RUN:
                    raise ImportProfileError(
                        "limit",
                        "run event count exceeds the profile limit",
                        module=module,
                        run_phase=cast(_RunPhase, phase),
                        run_number=number,
                    )
                try:
                    run = ProfileRun(cast(_RunPhase, phase), number, events)
                except ValueError as error:
                    raise ImportProfileError(
                        "invalid",
                        "captured events cannot be represented as a complete profile",
                        module=module,
                        run_phase=cast(_RunPhase, phase),
                        run_number=number,
                    ) from error
                total_events += len(run.events)
                if total_events > _MAX_EVENTS_TOTAL:
                    raise ImportProfileError(
                        "limit",
                        "total event count exceeds the profile limit",
                        module=module,
                        run_phase=cast(_RunPhase, phase),
                        run_number=number,
                    )
                runs.append(run)
        captured[module] = ProfileTarget(module, tuple(runs))
    return ImportProfile(identity, SamplingPolicy(warmup_count, sample_count), captured)
