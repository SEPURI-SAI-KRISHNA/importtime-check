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

"""Keep fixed, archived v1 report bytes usable by all supported Pythons."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from importtime_check import (
    MeasurementReportError,
    ReportIdentity,
    SamplingPolicy,
    compare_report_cohorts,
    decode_measurement_report,
    load_measurement_report,
    summarize_measurement_reports,
)

FIXTURES = Path(__file__).parent / "fixtures"
EXPECTED_SHA256 = {
    "report-v1-after-1.json": "b4aec3e37638445a29e02466ef1c50d5d9d727e5e3ceb5d34a324837fd9b3508",
    "report-v1-after-2.json": "957b2c534f058c20e193adf2217c9752f8d82f4a00e09a76f3e353ccac4fe873",
    "report-v1-before-1.json": "e87808012083fc8c3db6a9cc2c0270f0017c38ca7a900b3250ff3cc70b409c67",
    "report-v1-before-2.json": "67c4713968e2e7837638218dac7c6a84523512ce9291df69930f6b50e9c1e79d",
    "report-v1-duplicate-key.json": "ef08a05f0ebb03a622d80d840b067bed67d735eabaed7c94f14a5047743151f3",
    "report-v2-unsupported.json": "05c7f15b910e3976277069c07b1eb0f868d2eee973fa909c87a4af08de35e335",
}


@pytest.mark.parametrize("name", EXPECTED_SHA256)
def test_archived_report_bytes_are_unchanged(name: str) -> None:
    raw = (FIXTURES / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_SHA256[name]


def test_archived_v1_reports_load_summarize_and_compare() -> None:
    before = [
        load_measurement_report(FIXTURES / f"report-v1-before-{number}.json")
        for number in (1, 2)
    ]
    after = [
        load_measurement_report(FIXTURES / f"report-v1-after-{number}.json")
        for number in (1, 2)
    ]
    for name, report in zip(
        (
            "report-v1-before-1.json",
            "report-v1-before-2.json",
            "report-v1-after-1.json",
            "report-v1-after-2.json",
        ),
        (*before, *after),
        strict=True,
    ):
        assert decode_measurement_report((FIXTURES / name).read_bytes()) == report
        assert report.report_version == 1
        assert report.source_sha256 == EXPECTED_SHA256[name]
        assert report.environment == ReportIdentity(
            "cpython", "3.11", "linux", "x86_64"
        )
        assert report.sampling == SamplingPolicy(1, 3)
        assert tuple(report.targets) == ("email", "json")

    before_summary = summarize_measurement_reports(
        before, runner_context="ubuntu24-py311", install_context="build-before"
    )
    after_summary = summarize_measurement_reports(
        after, runner_context="ubuntu24-py311", install_context="build-after"
    )
    assert before_summary.report_count == after_summary.report_count == 2
    assert before_summary.sources_sha256 == tuple(
        sorted(report.source_sha256 for report in before)
    )
    assert after_summary.sources_sha256 == tuple(
        sorted(report.source_sha256 for report in after)
    )
    assert before_summary.targets["email"].run_medians_us == (11, 10)
    assert before_summary.targets["json"].run_medians_us == (41, 42)
    assert after_summary.targets["email"].run_medians_us == (15, 14)
    assert after_summary.targets["json"].run_medians_us == (48, 47)

    comparison = compare_report_cohorts(before_summary, after_summary)
    assert comparison.changes["email"].change_us == 4
    assert comparison.changes["email"].change_percent == "+36.36"
    assert comparison.changes["json"].change_us == 6
    assert comparison.changes["json"].change_percent == "+14.29"
    assert not hasattr(comparison, "status")


@pytest.mark.parametrize(
    ("name", "kind", "reason"),
    [
        (
            "report-v1-duplicate-key.json",
            "report-invalid",
            "measurement report has invalid v1 content",
        ),
        (
            "report-v2-unsupported.json",
            "report-unsupported",
            "unsupported measurement report_version",
        ),
    ],
)
def test_archived_invalid_and_future_reports_fail_closed(
    name: str, kind: str, reason: str
) -> None:
    path = FIXTURES / name
    for from_bytes in (False, True):
        with pytest.raises(MeasurementReportError) as failure:
            if from_bytes:
                decode_measurement_report(path.read_bytes())
            else:
                load_measurement_report(path)
        assert failure.value.kind == kind
        assert reason in str(failure.value)
