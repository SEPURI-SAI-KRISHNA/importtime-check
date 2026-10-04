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

"""Run one isolated CPython import-time measurement."""

from __future__ import annotations

import keyword
import math
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ._model import ImportTimeEvent, ImportTimeParseResult
from ._parser import ImportTimeParseError, parse_importtime

_IMPORT_SNIPPET = "import sys; __import__(sys.argv[1])"
_FailureKind = Literal[
    "launch", "timeout", "exit", "parse", "missing-target", "ambiguous-target"
]


def _validate_module_name(module: str) -> None:
    if (
        not isinstance(module, str)
        or not module
        or any(
            not part.isidentifier() or keyword.iskeyword(part)
            for part in module.split(".")
        )
    ):
        raise ValueError("module must be a dotted Python module name")


def _path_text(value: str | os.PathLike[str], name: str) -> str:
    try:
        path = os.fspath(value)
    except TypeError as error:
        raise ValueError(f"{name} must be a path") from error
    if not isinstance(path, str) or not path:
        raise ValueError(f"{name} must be a non-empty text path")
    return path


def _interpreter_path(value: str | os.PathLike[str] | None) -> str:
    path = _path_text(sys.executable if value is None else value, "python_executable")
    if not Path(path).is_absolute():
        raise ValueError("python_executable must be an absolute path")
    return str(Path(path).resolve())


def _working_directory(value: str | os.PathLike[str] | None) -> Path:
    path = Path.cwd() if value is None else Path(_path_text(value, "working_directory"))
    directory = path.resolve()
    if not directory.is_dir():
        raise ValueError("working_directory must be an existing directory")
    return directory


def _timeout(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("timeout_seconds must be a finite positive number")
    try:
        seconds = float(value)
    except OverflowError as error:
        raise ValueError("timeout_seconds must be a finite positive number") from error
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("timeout_seconds must be a finite positive number")
    return seconds


def _captured_stderr(value: bytes | str | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


@dataclass(frozen=True, slots=True)
class ImportMeasurement:
    """One target event and its complete parsed import-time stderr."""

    module: str
    python_executable: str
    parsed: ImportTimeParseResult
    target_event: ImportTimeEvent

    def __post_init__(self) -> None:
        """Keep manually constructed measurements consistent with parsed data."""
        _validate_module_name(self.module)
        if (
            not isinstance(self.python_executable, str)
            or not Path(self.python_executable).is_absolute()
        ):
            raise ValueError("python_executable must be an absolute path")
        if not isinstance(self.parsed, ImportTimeParseResult):
            raise ValueError("parsed must be an ImportTimeParseResult")
        if not isinstance(self.target_event, ImportTimeEvent):
            raise ValueError("target_event must be an ImportTimeEvent")
        matches = tuple(
            event for event in self.parsed.events if event.module == self.module
        )
        if len(matches) != 1 or matches[0] != self.target_event:
            raise ValueError("target_event must be the only matching parsed event")


class ImportMeasurementError(RuntimeError):
    """A launched measurement could not produce one target timing."""

    __slots__ = (
        "kind",
        "module",
        "python_executable",
        "reason",
        "returncode",
        "run_number",
        "run_phase",
        "stderr",
    )

    def __init__(
        self,
        *,
        module: str,
        kind: _FailureKind,
        python_executable: str,
        reason: str,
        returncode: int | None = None,
        stderr: str = "",
        run_phase: Literal["warmup", "sample"] | None = None,
        run_number: int | None = None,
    ) -> None:
        self.module = module
        self.kind = kind
        self.python_executable = python_executable
        self.reason = reason
        self.returncode = returncode
        self.stderr = stderr
        self.run_phase = run_phase
        self.run_number = run_number
        super().__init__(f"{kind} while measuring {module!r}: {reason}")


def measure_import(
    module: str,
    *,
    python_executable: str | os.PathLike[str] | None = None,
    timeout_seconds: float = 30.0,
    working_directory: str | os.PathLike[str] | None = None,
) -> ImportMeasurement:
    """Measure one module import in a fresh isolated CPython subprocess."""
    _validate_module_name(module)
    interpreter = _interpreter_path(python_executable)
    timeout = _timeout(timeout_seconds)
    directory = _working_directory(working_directory)
    environment = os.environ.copy()
    arguments = [interpreter, "-I", "-X", "importtime", "-c", _IMPORT_SNIPPET, module]

    try:
        completed = subprocess.run(
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            cwd=directory,
            env=environment,
            shell=False,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise ImportMeasurementError(
            module=module,
            kind="timeout",
            python_executable=interpreter,
            reason=f"child did not finish within {timeout:g} seconds",
            stderr=_captured_stderr(error.stderr),
        ) from error
    except OSError as error:
        raise ImportMeasurementError(
            module=module,
            kind="launch",
            python_executable=interpreter,
            reason=str(error),
        ) from error

    stderr = completed.stderr or ""
    if completed.returncode != 0:
        raise ImportMeasurementError(
            module=module,
            kind="exit",
            python_executable=interpreter,
            reason=f"child exited with code {completed.returncode}",
            returncode=completed.returncode,
            stderr=stderr,
        )

    try:
        parsed = parse_importtime(stderr)
    except ImportTimeParseError as error:
        raise ImportMeasurementError(
            module=module,
            kind="parse",
            python_executable=interpreter,
            reason=f"invalid import-time output on line {error.line_number}",
            returncode=completed.returncode,
            stderr=stderr,
        ) from error

    matches = tuple(event for event in parsed.events if event.module == module)
    if not matches:
        raise ImportMeasurementError(
            module=module,
            kind="missing-target",
            python_executable=interpreter,
            reason="no import-time event matched the requested module",
            returncode=completed.returncode,
            stderr=stderr,
        )
    if len(matches) != 1:
        raise ImportMeasurementError(
            module=module,
            kind="ambiguous-target",
            python_executable=interpreter,
            reason="multiple import-time events matched the requested module",
            returncode=completed.returncode,
            stderr=stderr,
        )
    return ImportMeasurement(module, interpreter, parsed, matches[0])
