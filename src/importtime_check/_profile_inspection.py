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

"""Bounded, occurrence-preserving inspection of one complete import trace."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ._measurement_report import ReportIdentity
from ._profile import ImportProfile, ImportProfileError

_RunPhase = Literal["warmup", "sample"]


@dataclass(frozen=True, slots=True)
class ProfileOccurrence:
    """One event's original one-based position and observed timing values."""

    occurrence: int
    module: str
    depth: int
    self_us: int
    cumulative_us: int


@dataclass(frozen=True, slots=True)
class ProfileInspection:
    """Separate, bounded rankings from one explicitly selected profile run."""

    environment: ReportIdentity
    source_sha256: str | None
    target: str
    phase: _RunPhase
    run_number: int
    event_count: int
    limit: int
    self_time: tuple[ProfileOccurrence, ...]
    cumulative_time: tuple[ProfileOccurrence, ...]


def inspect_import_profile(
    profile: ImportProfile,
    *,
    target: str,
    phase: _RunPhase,
    run_number: int,
    limit: int = 20,
) -> ProfileInspection:
    """Rank, but never combine or sum, the events in one selected run."""
    if not isinstance(profile, ImportProfile):
        raise ImportProfileError("invalid", "profile must be an ImportProfile")
    if not isinstance(target, str) or target not in profile.targets:
        raise ImportProfileError("invalid", "selected profile target does not exist")
    if phase not in ("warmup", "sample"):
        raise ImportProfileError("invalid", "phase must be warmup or sample")
    if type(run_number) is not int or run_number < 1:
        raise ImportProfileError("invalid", "run number must be positive")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ImportProfileError("invalid", "limit must be from 1 to 100")
    selected = next(
        (
            run
            for run in profile.targets[target].runs
            if run.phase == phase and run.number == run_number
        ),
        None,
    )
    if selected is None:
        raise ImportProfileError("invalid", "selected profile run does not exist")
    occurrences = tuple(
        ProfileOccurrence(
            occurrence=index,
            module=event.module,
            depth=event.depth,
            self_us=event.self_us,
            cumulative_us=event.cumulative_us,
        )
        for index, event in enumerate(selected.events, start=1)
    )
    return ProfileInspection(
        environment=profile.environment,
        source_sha256=profile.source_sha256,
        target=target,
        phase=phase,
        run_number=run_number,
        event_count=len(occurrences),
        limit=limit,
        self_time=tuple(
            sorted(occurrences, key=lambda item: (-item.self_us, item.occurrence))[
                :limit
            ]
        ),
        cumulative_time=tuple(
            sorted(
                occurrences, key=lambda item: (-item.cumulative_us, item.occurrence)
            )[:limit]
        ),
    )
