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

"""Deterministic terminal and JSON presentation of shared regression results."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from ._baseline import BaselineError, EnvironmentIdentity, SamplingPolicy
from ._measurement import ImportMeasurementError
from ._regression import RegressionReport
from ._sampling import ImportSampleSet


def _json(document: dict[str, Any]) -> str:
    return (
        json.dumps(
            document, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2
        )
        + "\n"
    )


def measurement_json(
    observations: Sequence[ImportSampleSet],
    environment: EnvironmentIdentity,
    sampling: SamplingPolicy,
) -> str:
    """Render a versioned observation without baseline policy or private paths."""
    return _json(
        {
            "environment": {
                "implementation": environment.implementation,
                "python": environment.python,
                "platform": environment.platform,
                "machine": environment.machine,
            },
            "report_type": "measurement",
            "report_version": 1,
            "sampling": {
                "warmups": sampling.warmups,
                "samples": sampling.samples,
                "statistic": sampling.statistic,
            },
            "targets": {
                result.module: {
                    "warmups_us": [
                        run.target_event.cumulative_us for run in result.warmups
                    ],
                    "samples_us": [
                        run.target_event.cumulative_us for run in result.samples
                    ],
                    "upper_median_us": result.median_cumulative_us,
                }
                for result in observations
            },
        }
    )


def measurement_text(observations: Sequence[ImportSampleSet]) -> str:
    """Repeat the published one-target three-line text block in target order."""
    lines: list[str] = []
    for result in observations:
        lines.extend(
            (
                f"{result.module}: upper median {result.median_cumulative_us} us",
                "warmups (us): "
                + ", ".join(
                    str(run.target_event.cumulative_us) for run in result.warmups
                ),
                "samples (us): "
                + ", ".join(
                    str(run.target_event.cumulative_us) for run in result.samples
                ),
            )
        )
    return "\n".join(lines) + "\n"


def report_json(report: RegressionReport) -> str:
    """Render the schema-1 machine report without ambient paths or stderr."""
    return _json(
        {
            "schema_version": 1,
            "status": report.status,
            "environment": {
                "implementation": report.environment.implementation,
                "python": report.environment.python,
                "platform": report.environment.platform,
                "machine": report.environment.machine,
                "profile": report.environment.profile,
            },
            "results": [
                {
                    "module": item.module,
                    "status": item.status,
                    "baseline_cumulative_us": item.baseline_cumulative_us,
                    "current_cumulative_us": item.current_cumulative_us,
                    "change_us": item.change_us,
                    "max_increase_us": item.max_increase_us,
                    "max_increase_percent": item.max_increase_percent,
                    "warmups_cumulative_us": list(item.warmups_cumulative_us),
                    "samples_cumulative_us": list(item.samples_cumulative_us),
                    "top_imports": [
                        {
                            "module": event.module,
                            "self_us": event.self_us,
                            "cumulative_us": event.cumulative_us,
                            "depth": event.depth,
                        }
                        for event in item.top_imports
                    ],
                }
                for item in report.results
            ],
        }
    )


def error_json(error: BaselineError | ImportMeasurementError) -> str:
    """Render one fail-closed schema-1 error without private process output."""
    if isinstance(error, ImportMeasurementError):
        details: dict[str, Any] = {
            "kind": "measurement-failed",
            "message": f"import measurement failed: {error.kind}",
            "module": error.module,
        }
        if error.run_phase is not None:
            details["run_phase"] = error.run_phase
        if error.run_number is not None:
            details["run_number"] = error.run_number
    else:
        details = {
            "kind": error.kind,
            "message": (
                "selected interpreter could not be probed"
                if error.kind == "interpreter-probe-failed"
                else error.reason
            ),
        }
    return _json({"schema_version": 1, "status": "error", "error": details})


def report_text(report: RegressionReport) -> str:
    """Render a compact report with actionable details for regressions."""
    failures = sum(item.status == "regression" for item in report.results)
    lines = [
        f"importtime-check: {report.status} ({failures}/{len(report.results)} targets regressed)"
    ]
    for item in report.results:
        sign = "+" if item.change_us >= 0 else ""
        lines.append(
            f"{item.status.upper()} {item.module}: "
            f"{item.baseline_cumulative_us} -> {item.current_cumulative_us} us "
            f"({sign}{item.change_us} us; allowances {item.max_increase_us} us "
            f"or {item.max_increase_percent}%)"
        )
        if item.status == "regression":
            lines.append(
                "  recorded samples (us): "
                + ", ".join(str(value) for value in item.samples_cumulative_us)
            )
            lines.append(
                "  top self-time imports: "
                + ", ".join(
                    f"{event.module} ({event.self_us} us)" for event in item.top_imports
                )
            )
    return "\n".join(lines) + "\n"
