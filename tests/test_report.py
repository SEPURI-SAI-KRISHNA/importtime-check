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

"""Deterministic report serialization and diagnostic text."""

import json

from importtime_check import (
    BaselineError,
    EnvironmentIdentity,
    ImportMeasurementError,
    ImportTimeEvent,
    RegressionReport,
    TargetRegressionResult,
)
from importtime_check._report import error_json, report_json, report_text


def _report(regression: bool) -> RegressionReport:
    return RegressionReport(
        EnvironmentIdentity("cpython", "3.11", "win32", "amd64"),
        (
            TargetRegressionResult(
                "json",
                "regression" if regression else "pass",
                100,
                120 if regression else 90,
                20 if regression else -10,
                5,
                "10",
                (80,),
                (120 if regression else 90,),
                (ImportTimeEvent("json", 3, 120, 0),),
            ),
        ),
    )


def test_report_json_has_stable_schema_and_canonical_encoding() -> None:
    encoded = report_json(_report(True))
    document = json.loads(encoded)
    assert encoded.endswith("\n")
    assert encoded == json.dumps(document, sort_keys=True, indent=2) + "\n"
    assert document == {
        "schema_version": 1,
        "status": "regression",
        "environment": {
            "implementation": "cpython",
            "python": "3.11",
            "platform": "win32",
            "machine": "amd64",
            "profile": "default",
        },
        "results": [
            {
                "module": "json",
                "status": "regression",
                "baseline_cumulative_us": 100,
                "current_cumulative_us": 120,
                "change_us": 20,
                "max_increase_us": 5,
                "max_increase_percent": "10",
                "warmups_cumulative_us": [80],
                "samples_cumulative_us": [120],
                "top_imports": [
                    {"module": "json", "self_us": 3, "cumulative_us": 120, "depth": 0}
                ],
            }
        ],
    }


def test_text_report_distinguishes_pass_and_regression() -> None:
    assert report_text(_report(False)) == (
        "importtime-check: pass (0/1 targets regressed)\n"
        "PASS json: 100 -> 90 us (-10 us; allowances 5 us or 10%)\n"
    )
    assert report_text(_report(True)) == (
        "importtime-check: regression (1/1 targets regressed)\n"
        "REGRESSION json: 100 -> 120 us (+20 us; allowances 5 us or 10%)\n"
        "  recorded samples (us): 120\n"
        "  top self-time imports: json (3 us)\n"
    )


def test_error_json_is_structured_and_does_not_expose_process_output() -> None:
    baseline = json.loads(error_json(BaselineError("baseline-missing", "not found")))
    assert baseline == {
        "schema_version": 1,
        "status": "error",
        "error": {"kind": "baseline-missing", "message": "not found"},
    }
    probe = json.loads(
        error_json(BaselineError("interpreter-probe-failed", "C:\\private"))
    )
    assert probe["error"]["message"] == "selected interpreter could not be probed"
    measurement = json.loads(
        error_json(
            ImportMeasurementError(
                module="json",
                kind="exit",
                python_executable="C:\\private\\python.exe",
                reason="secret",
                stderr="private output",
                run_phase="sample",
                run_number=2,
            )
        )
    )
    assert measurement["error"] == {
        "kind": "measurement-failed",
        "message": "import measurement failed: exit",
        "module": "json",
        "run_phase": "sample",
        "run_number": 2,
    }
    assert "private" not in json.dumps(measurement)
    assert json.loads(
        error_json(
            ImportMeasurementError(
                module="json",
                kind="timeout",
                python_executable="C:\\python.exe",
                reason="x",
            )
        )
    )["error"] == {
        "kind": "measurement-failed",
        "message": "import measurement failed: timeout",
        "module": "json",
    }
