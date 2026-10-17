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

"""Fixed-value comparisons of complete descriptive report cohorts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, cast

import pytest

from importtime_check import (
    CohortComparison,
    CohortSummary,
    MeasurementReportError,
    ReportIdentity,
    SamplingPolicy,
    TargetCohortChange,
    TargetCohortSummary,
    compare_report_cohorts,
)

IDENTITY = ReportIdentity("cpython", "3.11", "linux", "x86_64")
SAMPLING = SamplingPolicy(1, 3)


def _summary(
    *,
    email: tuple[int, ...] = (10, 11),
    json: tuple[int, ...] = (42, 41),
    install: str = "build-before",
    runner: str = "ubuntu24-py311",
    identity: ReportIdentity = IDENTITY,
    sampling: SamplingPolicy = SAMPLING,
    targets: dict[str, TargetCohortSummary] | None = None,
) -> CohortSummary:
    if targets is None:
        targets = {
            "json": TargetCohortSummary(json),
            "email": TargetCohortSummary(email),
        }
    count = len(next(iter(targets.values())).run_medians_us)
    return CohortSummary(
        identity,
        sampling,
        runner,
        install,
        tuple(f"{index:064x}" for index in range(1, count + 1)),
        targets,
    )


def test_compares_fixed_before_after_cohorts_without_policy_verdict(
    tmp_path: Path,
) -> None:
    before = _summary()
    after = _summary(email=(14, 15), json=(47, 48), install="build-after")
    result = compare_report_cohorts(before, after)
    assert result == CohortComparison(before, after)
    assert result.before is before
    assert result.after is after
    assert tuple(result.changes) == ("email", "json")
    assert result.changes["email"] == TargetCohortChange(11, 15)
    assert result.changes["email"].change_us == 4
    assert result.changes["email"].change_percent == "+36.36"
    assert result.changes["json"].change_us == 6
    assert result.changes["json"].change_percent == "+14.29"
    assert result.before.targets["email"].spread_us == 1
    assert result.after.targets["json"].spread_us == 1
    assert not hasattr(result, "status")
    assert not hasattr(result.changes["email"], "allowance")
    assert tuple(tmp_path.iterdir()) == ()
    with pytest.raises(TypeError):
        result.changes["other"] = result.changes["email"]  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        result.before = after  # type: ignore[misc]


@pytest.mark.parametrize(
    ("before", "after", "change", "percent"),
    [
        (32, 31, -1, "-3.13"),
        (20_000, 20_001, 1, "+0.01"),
        (1_000_000, 1_000_001, 1, "0.00"),
        (1_000_000, 999_999, -1, "0.00"),
        (5, 5, 0, "0.00"),
        (5, 0, -5, "-100.00"),
        (0, 0, 0, None),
        (0, 1, 1, None),
    ],
)
def test_signed_half_up_percent_and_zero_denominator(
    before: int, after: int, change: int, percent: str | None
) -> None:
    result = TargetCohortChange(before, after)
    assert result.change_us == change
    assert result.change_percent == percent
    with pytest.raises(FrozenInstanceError):
        result.change_percent = "1.00"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("before", "after"),
    [(True, 1), (-1, 1), (1, False), (1, -1), (1, 2**63)],
)
def test_change_rejects_invalid_microsecond_values(
    before: object, after: object
) -> None:
    with pytest.raises(ValueError):
        TargetCohortChange(cast(Any, before), cast(Any, after))


def test_unequal_cohort_counts_are_allowed_with_shared_runner() -> None:
    before = _summary(email=(10, 11), json=(42, 41))
    after = _summary(email=(12, 13, 14), json=(43, 44, 45), install="build-after")
    result = compare_report_cohorts(before, after)
    assert result.before.report_count == 2
    assert result.after.report_count == 3
    assert result.changes["email"].change_us == 2


@pytest.mark.parametrize(
    ("changed", "fields"),
    [
        (
            {"identity": ReportIdentity("cpython", "3.12", "darwin", "arm64")},
            ("environment.machine", "environment.platform", "environment.python"),
        ),
        ({"sampling": SamplingPolicy(0, 3)}, ("sampling.warmups",)),
        ({"sampling": SamplingPolicy(1, 5)}, ("sampling.samples",)),
        ({"runner": "another-runner"}, ("runner_context",)),
        (
            {"targets": {"json": TargetCohortSummary((42, 41))}},
            ("targets",),
        ),
    ],
)
def test_comparison_rejects_incompatible_cohorts_without_partial_result(
    changed: dict[str, Any], fields: tuple[str, ...]
) -> None:
    with pytest.raises(MeasurementReportError) as failure:
        compare_report_cohorts(_summary(), _summary(install="build-after", **changed))
    assert failure.value.kind == "cohort-mismatch"
    assert failure.value.differing_fields == fields
    assert failure.value.source_index is None


def test_comparison_rejects_noncohort_input() -> None:
    valid = _summary()
    for before, after in ((None, valid), (valid, None)):
        with pytest.raises(MeasurementReportError) as failure:
            compare_report_cohorts(cast(Any, before), cast(Any, after))
        assert failure.value.kind == "cohort-invalid"
