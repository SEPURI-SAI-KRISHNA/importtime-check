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

"""Immutable values produced by the import-time parser."""

from __future__ import annotations

from dataclasses import dataclass


def _validate_non_negative_integer(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-boolean non-negative integer")


@dataclass(frozen=True, slots=True)
class ImportTimeEvent:
    """One module row from CPython's import-time diagnostics."""

    module: str
    self_us: int
    cumulative_us: int
    depth: int

    def __post_init__(self) -> None:
        """Validate the event's value constraints."""
        if not isinstance(self.module, str) or not self.module.strip():
            raise ValueError("module must be a non-empty string")
        _validate_non_negative_integer("self_us", self.self_us)
        _validate_non_negative_integer("cumulative_us", self.cumulative_us)
        _validate_non_negative_integer("depth", self.depth)
        if self.cumulative_us < self.self_us:
            raise ValueError("cumulative_us must not be smaller than self_us")


@dataclass(frozen=True, slots=True)
class ImportTimeParseResult:
    """All parsed events and unrelated stderr lines from one input stream."""

    events: tuple[ImportTimeEvent, ...] = ()
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Copy nested collections into immutable tuples and validate them."""
        events = tuple(self.events)
        diagnostics = tuple(self.diagnostics)
        if not all(isinstance(event, ImportTimeEvent) for event in events):
            raise ValueError("events must contain only ImportTimeEvent values")
        if not all(isinstance(line, str) for line in diagnostics):
            raise ValueError("diagnostics must contain only strings")
        object.__setattr__(self, "events", events)
        object.__setattr__(self, "diagnostics", diagnostics)
