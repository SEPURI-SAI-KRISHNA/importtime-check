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

"""Fixed-value tests for descriptive, explicitly controlled report cohorts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any, cast

import pytest

from importtime_check import (
    CohortSummary,
    MeasurementReport,
    MeasurementReportError,
    ReportIdentity,
    ReportTarget,
    SamplingPolicy,
    TargetCohortSummary,
    summarize_measurement_reports,
)

IDENTITY = ReportIdentity("cpython", "3.11", "linux", "x86_64")
SAMPLING = SamplingPolicy(1, 3)


def _report(
    number: int,
    *,
    email: int = 10,
    json: int = 42,
    identity: ReportIdentity = IDENTITY,
    sampling: SamplingPolicy = SAMPLING,
    targets: dict[str, ReportTarget] | None = None,
) -> MeasurementReport:
    if targets is None:
        targets = {
            "json": ReportTarget(
                (json + 3,) * sampling.warmups,
                (json - 2, json, json + 2)[: sampling.samples],
                json if sampling.samples == 3 else json - 2,
            ),
            "email": ReportTarget(
                (email + 3,) * sampling.warmups,
                (email - 2, email, email + 2)[: sampling.samples],
                email if sampling.samples == 3 else email - 2,
            ),
        }
    return MeasurementReport(identity, sampling, targets, f"{number:064x}")


def test_summarizes_sorted_provenance_and_run_medians_not_pooled_samples() -> None:
    first = _report(2, email=10, json=42)
    second = _report(1, email=11, json=41)
    summary = summarize_measurement_reports(
        [first, second], runner_context="ubuntu24-py311", install_context="build-before"
    )
    assert summary == summarize_measurement_reports(
        [second, first], runner_context="ubuntu24-py311", install_context="build-before"
    )
    assert summary.environment == IDENTITY
    assert summary.sampling == SAMPLING
    assert summary.runner_context == "ubuntu24-py311"
    assert summary.install_context == "build-before"
    assert summary.report_count == 2
    assert summary.sources_sha256 == (second.source_sha256, first.source_sha256)
    assert tuple(summary.targets) == ("email", "json")
    assert summary.targets["email"] == TargetCohortSummary((11, 10))
    assert summary.targets["email"].observed_median_us == 11
    assert summary.targets["email"].min_us == 10
    assert summary.targets["email"].max_us == 11
    assert summary.targets["email"].spread_us == 1
    assert summary.targets["json"].run_medians_us == (41, 42)
    assert summary.targets["json"].observed_median_us == 42
    with pytest.raises(TypeError):
        summary.targets["other"] = summary.targets["email"]  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        summary.report_count = 3  # type: ignore[misc]


def test_many_reports_use_upper_median_and_full_range() -> None:
    reports = [
        _report(index + 1, email=value) for index, value in enumerate((7, 3, 9, 5))
    ]
    summary = summarize_measurement_reports(
        reports, runner_context="runner_1", install_context="install.2"
    )
    assert summary.targets["email"].run_medians_us == (7, 3, 9, 5)
    assert summary.targets["email"].observed_median_us == 7
    assert summary.targets["email"].min_us == 3
    assert summary.targets["email"].max_us == 9
    assert summary.targets["email"].spread_us == 6


def test_target_summary_copies_inputs_and_rejects_invalid_observations() -> None:
    observations = [3, 5]
    result = TargetCohortSummary(cast(Any, observations))
    observations.append(7)
    assert result.run_medians_us == (3, 5)
    with pytest.raises(FrozenInstanceError):
        result.min_us = 0  # type: ignore[misc]
    for values in (None, (), (1,), (1,) * 65, (1, True), (1, -1)):
        with pytest.raises(ValueError):
            TargetCohortSummary(cast(Any, values))


@pytest.mark.parametrize("label", ["", "a/b", "a b", "_abc", "é", "a" * 129, None])
def test_contexts_fail_closed(label: object) -> None:
    reports = (_report(1), _report(2))
    for name in ("runner_context", "install_context"):
        options = {"runner_context": "runner", "install_context": "install"}
        options[name] = cast(str, label)
        with pytest.raises(MeasurementReportError) as failure:
            summarize_measurement_reports(reports, **options)
        assert failure.value.kind == "context-invalid"
        assert failure.value.source_index is None


@pytest.mark.parametrize(
    "reports",
    [
        None,
        "abc",
        b"abc",
        bytearray(b"abc"),
        (),
        (_report(1),),
        tuple(_report(i) for i in range(65)),
    ],
    ids=("none", "text", "bytes", "bytearray", "empty", "one", "too-many"),
)
def test_cohort_rejects_invalid_sequence_or_count(reports: object) -> None:
    with pytest.raises(MeasurementReportError) as failure:
        summarize_measurement_reports(
            cast(Any, reports), runner_context="runner", install_context="install"
        )
    assert failure.value.kind == "cohort-invalid"


def test_cohort_rejects_nonreport_and_duplicate_bytes_with_position() -> None:
    for reports, position in (((_report(1), None), 2), ((_report(1), _report(1)), 2)):
        with pytest.raises(MeasurementReportError) as failure:
            summarize_measurement_reports(
                cast(Any, reports), runner_context="runner", install_context="install"
            )
        assert failure.value.kind == "cohort-invalid"
        assert failure.value.source_index == position


@pytest.mark.parametrize(
    ("changed", "fields"),
    [
        (
            {"identity": ReportIdentity("cpython", "3.12", "darwin", "arm64")},
            ("environment.machine", "environment.platform", "environment.python"),
        ),
        ({"sampling": SamplingPolicy(0, 3)}, ("sampling.warmups",)),
        ({"sampling": SamplingPolicy(1, 1)}, ("sampling.samples",)),
        ({"targets": {"json": ReportTarget((45,), (40, 42, 44), 42)}}, ("targets",)),
    ],
)
def test_cohort_rejects_different_identity_sampling_or_target_set(
    changed: dict[str, Any], fields: tuple[str, ...]
) -> None:
    with pytest.raises(MeasurementReportError) as failure:
        summarize_measurement_reports(
            (_report(1), _report(2, **changed)),
            runner_context="runner",
            install_context="install",
        )
    assert failure.value.kind == "cohort-mismatch"
    assert failure.value.source_index == 2
    assert failure.value.differing_fields == fields


def test_cohort_summary_model_copies_mapping_and_checks_invariants() -> None:
    values = {"email": TargetCohortSummary((3, 5))}
    sources = ("1" * 64, "2" * 64)
    summary = CohortSummary(IDENTITY, SAMPLING, "runner", "install", sources, values)
    values.clear()
    assert tuple(summary.targets) == ("email",)
    base: dict[str, Any] = {
        "environment": IDENTITY,
        "sampling": SAMPLING,
        "runner_context": "runner",
        "install_context": "install",
        "sources_sha256": sources,
        "targets": {"email": TargetCohortSummary((3, 5))},
    }
    invalid: tuple[tuple[str, Any], ...] = (
        ("environment", None),
        ("sampling", None),
        ("runner_context", "bad/path"),
        ("install_context", "bad path"),
        ("sources_sha256", None),
        ("sources_sha256", ("1" * 64,)),
        ("sources_sha256", ("bad", "2" * 64)),
        ("sources_sha256", ("2" * 64, "1" * 64)),
        ("sources_sha256", ("1" * 64, "1" * 64)),
        ("targets", None),
        ("targets", {}),
        ("targets", {"bad/path": TargetCohortSummary((3, 5))}),
        ("targets", {"email": None}),
        ("targets", {"email": TargetCohortSummary((3, 5, 7))}),
    )
    for name, value in invalid:
        with pytest.raises((ValueError, MeasurementReportError)):
            CohortSummary(**(base | {name: value}))
