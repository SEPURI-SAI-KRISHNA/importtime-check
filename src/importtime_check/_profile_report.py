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

"""Bounded, deterministic text and JSON for selected profile evidence."""

from __future__ import annotations

import json
from typing import Any

from ._profile_inspection import ProfileInspection, ProfileOccurrence


def _row(occurrence: ProfileOccurrence) -> dict[str, int | str]:
    return {
        "occurrence": occurrence.occurrence,
        "module": occurrence.module,
        "depth": occurrence.depth,
        "self_us": occurrence.self_us,
        "cumulative_us": occurrence.cumulative_us,
    }


def profile_inspection_json(inspection: ProfileInspection) -> str:
    """Render one selected run without implying cumulative values are additive."""
    document: dict[str, Any] = {
        "inspection_type": "import-profile-run",
        "inspection_version": 1,
        "source_sha256": inspection.source_sha256,
        "environment": {
            "implementation": inspection.environment.implementation,
            "python": inspection.environment.python,
            "platform": inspection.environment.platform,
            "machine": inspection.environment.machine,
        },
        "target": inspection.target,
        "phase": inspection.phase,
        "run_number": inspection.run_number,
        "event_count": inspection.event_count,
        "limit": inspection.limit,
        "rankings": {
            "self_time": {
                "metric": "self_us",
                "rows": [_row(row) for row in inspection.self_time],
            },
            "cumulative_time": {
                "metric": "cumulative_us",
                "overlapping_not_additive": True,
                "rows": [_row(row) for row in inspection.cumulative_time],
            },
        },
    }
    return json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def profile_inspection_text(inspection: ProfileInspection) -> str:
    """Show both rankings with original occurrence numbers and a timing caveat."""
    environment = inspection.environment
    lines = [
        f"Profile source SHA-256: {inspection.source_sha256 or 'none (in-memory capture)'}",
        "Environment: "
        f"{_quoted(environment.implementation)} Python {_quoted(environment.python)}, "
        f"platform {_quoted(environment.platform)}, machine {_quoted(environment.machine)}",
        f"Target: {_quoted(inspection.target)}; {inspection.phase} {inspection.run_number}; "
        f"events: {inspection.event_count}; shown per ranking: {inspection.limit}",
        "Self time (us):",
    ]
    for row in inspection.self_time:
        lines.append(
            f"  #{row.occurrence} {row.self_us} us; "
            f"cumulative {row.cumulative_us} us; depth {row.depth}; "
            f"module {_quoted(row.module)}"
        )
    lines.append("Cumulative time (us; overlapping, not additive):")
    for row in inspection.cumulative_time:
        lines.append(
            f"  #{row.occurrence} {row.cumulative_us} us; "
            f"self {row.self_us} us; depth {row.depth}; "
            f"module {_quoted(row.module)}"
        )
    return "\n".join(lines) + "\n"
