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

"""Parse numeric CPython ``-X importtime`` stderr output."""

from __future__ import annotations

import re

from ._model import ImportTimeEvent, ImportTimeParseResult

_PREFIX = "import time:"
_HEADER = "import time: self [us] | cumulative | imported package"
_INTEGER = re.compile(r"[0-9]+")


class ImportTimeParseError(ValueError):
    """A malformed line that claims to be import-time output."""

    __slots__ = ("line", "line_number", "reason")

    def __init__(self, line_number: int, line: str, reason: str) -> None:
        self.line_number = line_number
        self.line = line
        self.reason = reason
        super().__init__(f"line {line_number}: {reason}: {line!r}")


def _fail(line_number: int, line: str, reason: str) -> ImportTimeParseError:
    return ImportTimeParseError(line_number, line, reason)


def _parse_integer(value: str, field: str, line_number: int, line: str) -> int:
    stripped = value.strip()
    if stripped == "cached":
        raise _fail(
            line_number,
            line,
            f"cached {field} is unsupported; use numeric -X importtime output",
        )
    if _INTEGER.fullmatch(stripped) is None:
        raise _fail(line_number, line, f"{field} must be an integer in microseconds")
    return int(stripped)


def _parse_event(line_number: int, line: str) -> ImportTimeEvent:
    columns = line[len(_PREFIX) :].split("|")
    if len(columns) != 3:
        raise _fail(line_number, line, "expected three pipe-separated columns")

    self_us = _parse_integer(columns[0], "self time", line_number, line)
    cumulative_us = _parse_integer(columns[1], "cumulative time", line_number, line)
    if cumulative_us < self_us:
        raise _fail(
            line_number,
            line,
            "cumulative time must not be smaller than self time",
        )

    module_column = columns[2]
    if not module_column.startswith(" "):
        raise _fail(line_number, line, "module column must start with one space")
    indented_module = module_column[1:]
    leading_spaces = len(indented_module) - len(indented_module.lstrip(" "))
    if leading_spaces % 2:
        raise _fail(line_number, line, "module indentation must use two-space levels")
    module = indented_module[leading_spaces:].rstrip()
    if not module:
        raise _fail(line_number, line, "module name is missing")
    if module[0].isspace():
        raise _fail(line_number, line, "module indentation must contain only spaces")

    return ImportTimeEvent(
        module=module,
        self_us=self_us,
        cumulative_us=cumulative_us,
        depth=leading_spaces // 2,
    )


def parse_importtime(stderr: str) -> ImportTimeParseResult:
    """Parse numeric CPython import-time output without performing I/O."""
    events: list[ImportTimeEvent] = []
    diagnostics: list[str] = []
    for line_number, line in enumerate(stderr.splitlines(), start=1):
        if line == _HEADER:
            continue
        if line.startswith(_PREFIX):
            events.append(_parse_event(line_number, line))
        else:
            diagnostics.append(line)
    return ImportTimeParseResult(tuple(events), tuple(diagnostics))
