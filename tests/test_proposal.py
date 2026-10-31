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

"""Candidate baseline construction never implies policy approval or file I/O."""

from __future__ import annotations

import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any, cast

import pytest

from importtime_check import (
    Baseline,
    BaselineProposalError,
    CohortSummary,
    EnvironmentIdentity,
    ImportMeasurement,
    ImportSampleSet,
    ImportTimeEvent,
    ImportTimeParseResult,
    MeasurementReportError,
    ReportIdentity,
    SamplingPolicy,
    TargetAllowance,
    TargetBaseline,
    TargetCohortSummary,
    decode_baseline,
    encode_baseline,
    evaluate_baseline,
    load_baseline,
    load_measurement_report,
    propose_baseline,
    save_baseline,
    summarize_measurement_reports,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _cohort() -> CohortSummary:
    return summarize_measurement_reports(
        (
            load_measurement_report(FIXTURES / "report-v1-before-1.json"),
            load_measurement_report(FIXTURES / "report-v1-before-2.json"),
        ),
        runner_context="ubuntu24-py311",
        install_context="build-before",
    )


def _allowances() -> dict[str, TargetAllowance]:
    return {"json": TargetAllowance(8, "10.0"), "email": TargetAllowance(3, "15")}


def test_candidate_uses_upper_median_and_only_explicit_policy(tmp_path: Path) -> None:
    cohort = _cohort()
    allowances = _allowances()
    candidate = propose_baseline(
        cohort, profile="ci-locked-v1", per_target_allowances=allowances
    )
    allowances.clear()
    assert candidate == Baseline(
        EnvironmentIdentity("cpython", "3.11", "linux", "x86_64", "ci-locked-v1"),
        SamplingPolicy(1, 3),
        {
            "email": TargetBaseline(11, 3, "15"),
            "json": TargetBaseline(42, 8, "10"),
        },
    )
    assert tuple(candidate.targets) == ("email", "json")
    assert candidate.sampling is cohort.sampling
    assert candidate.environment.profile != cohort.install_context
    assert candidate.environment.profile != cohort.runner_context
    assert not hasattr(candidate, "approved")
    assert not hasattr(candidate, "source_sha256")
    assert tuple(tmp_path.iterdir()) == ()
    with pytest.raises(TypeError):
        candidate.targets["other"] = TargetBaseline(1, 0, "0")  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        candidate.schema_version = 2  # type: ignore[misc]
    raw = encode_baseline(candidate)
    assert decode_baseline(raw) == candidate
    assert b"runner_context" not in raw and b"candidate" not in raw
    path = tmp_path / "reviewed.json"
    save_baseline(path, candidate)
    assert load_baseline(path) == candidate
    assert path.read_bytes() == raw


def test_zero_and_fractional_allowances_are_explicit() -> None:
    candidate = propose_baseline(
        _cohort(),
        profile="reviewed",
        per_target_allowances={
            "email": TargetAllowance(0, "0"),
            "json": TargetAllowance(1, "0.2500"),
        },
    )
    assert candidate.targets["email"] == TargetBaseline(11, 0, "0")
    assert candidate.targets["json"] == TargetBaseline(42, 1, "0.25")


def test_deliberately_saved_candidate_uses_existing_check_math(tmp_path: Path) -> None:
    candidate = propose_baseline(
        _cohort(), profile="reviewed", per_target_allowances=_allowances()
    )
    path = tmp_path / "approved.json"
    save_baseline(path, candidate)
    approved = load_baseline(path)
    interpreter = str(Path(sys.executable).resolve())

    def sample_set(module: str, values: tuple[int, int, int]) -> ImportSampleSet:
        def measurement(value: int) -> ImportMeasurement:
            event = ImportTimeEvent(module, 1, value, 0)
            return ImportMeasurement(
                module,
                interpreter,
                ImportTimeParseResult((event,), ()),
                event,
            )

        return ImportSampleSet(
            module,
            interpreter,
            (measurement(values[0]),),
            tuple(measurement(value) for value in values),
            sorted(values)[1],
        )

    report = evaluate_baseline(
        approved,
        {
            "email": sample_set("email", (11, 11, 15)),
            "json": sample_set("json", (42, 52, 53)),
        },
        approved.environment,
    )
    assert tuple(result.status for result in report.results) == (
        "pass",
        "regression",
    )


@pytest.mark.parametrize("cohort", [None, {}, [], "report"])
def test_rejects_fabricated_non_cohort_values(cohort: object) -> None:
    with pytest.raises(BaselineProposalError) as found:
        propose_baseline(
            cast(Any, cohort), profile="reviewed", per_target_allowances=_allowances()
        )
    assert found.value.kind == "proposal-invalid"
    assert found.value.missing == found.value.unknown == ()


@pytest.mark.parametrize("profile", [None, "", " ", 0])
def test_rejects_missing_or_invalid_explicit_profile(profile: object) -> None:
    with pytest.raises(BaselineProposalError, match="profile") as found:
        propose_baseline(
            _cohort(),
            profile=cast(Any, profile),
            per_target_allowances=_allowances(),
        )
    assert found.value.kind == "proposal-invalid"


def test_rejects_nonmapping_and_nonstr_budget_keys() -> None:
    invalid_inputs: tuple[object, ...] = (
        None,
        [],
        {1: TargetAllowance(1, "1")},
    )
    for invalid in invalid_inputs:
        with pytest.raises(BaselineProposalError) as found:
            propose_baseline(
                _cohort(), profile="reviewed", per_target_allowances=cast(Any, invalid)
            )
        assert found.value.kind == "proposal-invalid"


def test_rejects_missing_and_unknown_budgets_with_sorted_details() -> None:
    for allowances, missing, unknown in (
        ({}, ("email", "json"), ()),
        ({"email": TargetAllowance(1, "1")}, ("json",), ()),
        (
            _allowances()
            | {"z": TargetAllowance(1, "1"), "a": TargetAllowance(1, "1")},
            (),
            ("a", "z"),
        ),
        ({"a": TargetAllowance(1, "1")}, ("email", "json"), ("a",)),
    ):
        with pytest.raises(BaselineProposalError) as found:
            propose_baseline(
                _cohort(), profile="reviewed", per_target_allowances=allowances
            )
        assert found.value.kind == "proposal-invalid"
        assert found.value.missing == missing
        assert found.value.unknown == unknown


def test_rejects_wrong_or_mutated_allowance_without_partial_result(
    tmp_path: Path,
) -> None:
    for invalid in (None, 3, TargetBaseline(11, 3, "15")):
        allowances: dict[str, Any] = _allowances()
        allowances["json"] = invalid
        with pytest.raises(BaselineProposalError, match="TargetAllowance"):
            propose_baseline(
                _cohort(), profile="reviewed", per_target_allowances=allowances
            )
    for field, value in (("max_increase_us", True), ("max_increase_percent", "-1")):
        invalid_allowance = TargetAllowance(1, "1")
        object.__setattr__(invalid_allowance, field, value)
        allowances = _allowances()
        allowances["json"] = invalid_allowance
        with pytest.raises(BaselineProposalError, match="allowance") as found:
            propose_baseline(
                _cohort(), profile="reviewed", per_target_allowances=allowances
            )
        assert found.value.kind == "proposal-invalid"
    assert tuple(tmp_path.iterdir()) == ()


def test_upstream_cohort_validation_remains_separate() -> None:
    report = load_measurement_report(FIXTURES / "report-v1-before-1.json")
    with pytest.raises(MeasurementReportError) as found:
        summarize_measurement_reports(
            (report,), runner_context="runner", install_context="install"
        )
    assert found.value.kind == "cohort-invalid"
    with pytest.raises(MeasurementReportError) as found:
        summarize_measurement_reports(
            (report, report), runner_context="runner", install_context="install"
        )
    assert found.value.kind == "cohort-invalid"
    different = replace(
        report,
        environment=ReportIdentity("cpython", "3.12", "linux", "x86_64"),
        source_sha256="f" * 64,
    )
    with pytest.raises(MeasurementReportError) as found:
        summarize_measurement_reports(
            (report, different), runner_context="runner", install_context="install"
        )
    assert found.value.kind == "cohort-mismatch"


def test_programmatic_summary_is_allowed_but_not_certified() -> None:
    summary = CohortSummary(
        _cohort().environment,
        SamplingPolicy(0, 2),
        "runner-assertion",
        "install-assertion",
        ("1" * 64, "2" * 64),
        {"email": TargetCohortSummary((0, 1))},
    )
    candidate = propose_baseline(
        summary,
        profile="manual-review",
        per_target_allowances={"email": TargetAllowance(0, "0")},
    )
    assert candidate.targets["email"].baseline_cumulative_us == 1
    assert candidate.sampling == SamplingPolicy(0, 2)
