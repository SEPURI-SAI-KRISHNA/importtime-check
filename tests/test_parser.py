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

"""Tests for immutable import-time values and numeric stderr parsing."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any, cast

import pytest

import importtime_check
from importtime_check import (
    ImportTimeEvent,
    ImportTimeParseError,
    ImportTimeParseResult,
    parse_importtime,
)

HEADER = "import time: self [us] | cumulative | imported package"


def test_parser_preserves_order_depth_and_diagnostics() -> None:
    source = (
        "warning before import timing\r\n"
        f"{HEADER}\r\n"
        "import time:        10 |         30 | root\r\n"
        "import time:         4 |         12 |   child\r\n"
        "\r\n"
        "import time:         1 |          1 |     grand.child"
    )

    result = parse_importtime(source)

    assert result == ImportTimeParseResult(
        events=(
            ImportTimeEvent("root", 10, 30, 0),
            ImportTimeEvent("child", 4, 12, 1),
            ImportTimeEvent("grand.child", 1, 1, 2),
        ),
        diagnostics=("warning before import timing", ""),
    )


def test_parser_accepts_empty_input() -> None:
    assert parse_importtime("") == ImportTimeParseResult()


@pytest.mark.parametrize(
    ("line", "reason"),
    (
        ("import time: bad | 2 | module", "self time must be an integer"),
        ("import time: 1 | bad | module", "cumulative time must be an integer"),
        ("import time: cached | 2 | module", "cached self time is unsupported"),
        ("import time: 1 | cached | module", "cached cumulative time is unsupported"),
        ("import time: 1 | 2", "expected three pipe-separated columns"),
        ("import time: 1 | 2 |module", "module column must start with one space"),
        ("import time: 1 | 2 |  module", "two-space levels"),
        ("import time: 1 | 2 | \tmodule", "must contain only spaces"),
        ("import time: 1 | 2 |   ", "module name is missing"),
        ("import time: 3 | 2 | module", "must not be smaller than self time"),
        (
            "import time: self [ms] | cumulative | imported package",
            "self time must be an integer",
        ),
    ),
)
def test_parser_rejects_malformed_prefixed_lines(line: str, reason: str) -> None:
    with pytest.raises(ImportTimeParseError, match=reason) as captured:
        parse_importtime(f"diagnostic\n{line}\nunreached")

    assert captured.value.line_number == 2
    assert captured.value.line == line
    assert captured.value.reason in str(captured.value)


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"module": ""}, "module must be a non-empty string"),
        ({"module": "   "}, "module must be a non-empty string"),
        ({"module": cast(Any, 1)}, "module must be a non-empty string"),
        ({"self_us": -1}, "self_us must be"),
        ({"self_us": True}, "self_us must be"),
        ({"self_us": cast(Any, 1.5)}, "self_us must be"),
        ({"cumulative_us": -1}, "cumulative_us must be"),
        ({"cumulative_us": False}, "cumulative_us must be"),
        ({"depth": -1}, "depth must be"),
        ({"depth": True}, "depth must be"),
        ({"cumulative_us": 1}, "must not be smaller than self_us"),
    ),
)
def test_event_rejects_invalid_values(changes: dict[str, object], message: str) -> None:
    values: dict[str, object] = {
        "module": "module",
        "self_us": 2,
        "cumulative_us": 3,
        "depth": 0,
    }
    values.update(changes)

    with pytest.raises(ValueError, match=message):
        ImportTimeEvent(**cast(Any, values))


def test_result_copies_nested_collections_and_is_frozen() -> None:
    event = ImportTimeEvent("module", 1, 1, 0)
    source_events = [event]
    source_diagnostics = ["warning"]
    result = ImportTimeParseResult(
        cast(Any, source_events), cast(Any, source_diagnostics)
    )
    source_events.clear()
    source_diagnostics.clear()

    assert result.events == (event,)
    assert result.diagnostics == ("warning",)
    with pytest.raises(FrozenInstanceError):
        result.events = ()  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        event.depth = 1  # type: ignore[misc]


@pytest.mark.parametrize(
    ("events", "diagnostics", "message"),
    (
        ((cast(Any, "not an event"),), (), "events must contain"),
        ((), (cast(Any, 1),), "diagnostics must contain"),
    ),
)
def test_result_rejects_invalid_nested_values(
    events: tuple[ImportTimeEvent, ...],
    diagnostics: tuple[str, ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ImportTimeParseResult(events, diagnostics)


def test_public_exports_are_exact() -> None:
    assert importtime_check.__all__ == (
        "ImportMeasurement",
        "ImportMeasurementError",
        "ImportSampleSet",
        "ImportTimeEvent",
        "ImportTimeParseError",
        "ImportTimeParseResult",
        "__version__",
        "measure_import",
        "parse_importtime",
        "sample_import",
    )
