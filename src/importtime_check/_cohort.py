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

"""Descriptive summaries of explicitly comparable measurement reports."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from ._baseline import SamplingPolicy
from ._measurement import _validate_module_name
from ._measurement_report import (
    _DIGEST,
    _MAX_TARGETS,
    MeasurementReport,
    MeasurementReportError,
    ReportIdentity,
    _timing,
)

_CONTEXT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_MAX_COHORT_REPORTS = 64


def _context(value: object, name: str) -> str:
    if not isinstance(value, str) or _CONTEXT.fullmatch(value) is None:
        raise MeasurementReportError(
            "context-invalid", f"{name} must be a safe non-empty context label"
        )
    return value


@dataclass(frozen=True, slots=True)
class TargetCohortSummary:
    """Observed median of run medians and their full range in microseconds."""

    run_medians_us: tuple[int, ...]
    observed_median_us: int = field(init=False)
    min_us: int = field(init=False)
    max_us: int = field(init=False)
    spread_us: int = field(init=False)

    def __post_init__(self) -> None:
        try:
            values = tuple(self.run_medians_us)
        except TypeError as error:
            raise ValueError("run_medians_us must be a sequence") from error
        if not 2 <= len(values) <= _MAX_COHORT_REPORTS:
            raise ValueError("run_medians_us must contain 2 to 64 observations")
        observations = tuple(_timing(value, "run_medians_us") for value in values)
        ordered = sorted(observations)
        object.__setattr__(self, "run_medians_us", observations)
        object.__setattr__(self, "observed_median_us", ordered[len(ordered) // 2])
        object.__setattr__(self, "min_us", ordered[0])
        object.__setattr__(self, "max_us", ordered[-1])
        object.__setattr__(self, "spread_us", ordered[-1] - ordered[0])


@dataclass(frozen=True, slots=True)
class CohortSummary:
    """One complete reviewable cohort without allowances or verdicts."""

    environment: ReportIdentity
    sampling: SamplingPolicy
    runner_context: str
    install_context: str
    sources_sha256: tuple[str, ...]
    targets: Mapping[str, TargetCohortSummary]
    report_count: int = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.environment, ReportIdentity):
            raise ValueError("environment must be a ReportIdentity")
        if not isinstance(self.sampling, SamplingPolicy):
            raise ValueError("sampling must be a SamplingPolicy")
        _context(self.runner_context, "runner_context")
        _context(self.install_context, "install_context")
        try:
            sources = tuple(self.sources_sha256)
        except TypeError as error:
            raise ValueError("sources_sha256 must be a sequence") from error
        if not 2 <= len(sources) <= _MAX_COHORT_REPORTS:
            raise ValueError("sources_sha256 must contain 2 to 64 digests")
        if any(
            not isinstance(source, str) or _DIGEST.fullmatch(source) is None
            for source in sources
        ):
            raise ValueError("sources_sha256 must contain lowercase SHA-256 digests")
        if tuple(sorted(sources)) != sources or len(set(sources)) != len(sources):
            raise ValueError("sources_sha256 must be sorted and distinct")
        if (
            not isinstance(self.targets, Mapping)
            or not 1 <= len(self.targets) <= _MAX_TARGETS
        ):
            raise ValueError("targets must contain 1 to 128 entries")
        for module, summary in self.targets.items():
            _validate_module_name(module)
            if not isinstance(summary, TargetCohortSummary):
                raise ValueError("targets must contain TargetCohortSummary values")
            if len(summary.run_medians_us) != len(sources):
                raise ValueError("target observations differ from report count")
        object.__setattr__(self, "sources_sha256", sources)
        object.__setattr__(
            self, "targets", MappingProxyType(dict(sorted(self.targets.items())))
        )
        object.__setattr__(self, "report_count", len(sources))


def _differing_fields(
    reference: MeasurementReport, report: MeasurementReport
) -> tuple[str, ...]:
    differences: list[str] = []
    for name in ("implementation", "python", "platform", "machine"):
        if getattr(reference.environment, name) != getattr(report.environment, name):
            differences.append(f"environment.{name}")
    for name in ("warmups", "samples", "statistic"):
        if getattr(reference.sampling, name) != getattr(report.sampling, name):
            differences.append(f"sampling.{name}")
    if set(reference.targets) != set(report.targets):
        differences.append("targets")
    return tuple(sorted(differences))


def summarize_measurement_reports(
    reports: Sequence[MeasurementReport],
    *,
    runner_context: str,
    install_context: str,
) -> CohortSummary:
    """Summarize 2-64 asserted-comparable reports without a policy verdict."""
    runner = _context(runner_context, "runner_context")
    install = _context(install_context, "install_context")
    if not isinstance(reports, Sequence) or isinstance(
        reports, (str, bytes, bytearray)
    ):
        raise MeasurementReportError(
            "cohort-invalid", "reports must be a sequence of measurement reports"
        )
    selected = tuple(reports)
    if not 2 <= len(selected) <= _MAX_COHORT_REPORTS:
        raise MeasurementReportError(
            "cohort-invalid", "cohort must contain 2 to 64 reports"
        )
    seen: set[str] = set()
    reference: MeasurementReport | None = None
    for index, report in enumerate(selected, start=1):
        if not isinstance(report, MeasurementReport):
            raise MeasurementReportError(
                "cohort-invalid",
                "cohort contains a non-report value",
                source_index=index,
            )
        if report.source_sha256 in seen:
            raise MeasurementReportError(
                "cohort-invalid",
                "cohort contains duplicate report bytes",
                source_index=index,
            )
        seen.add(report.source_sha256)
        if reference is None:
            reference = report
            continue
        differences = _differing_fields(reference, report)
        if differences:
            raise MeasurementReportError(
                "cohort-mismatch",
                "cohort reports differ in identity, sampling, or targets",
                source_index=index,
                differing_fields=differences,
            )
    assert reference is not None
    ordered = tuple(sorted(selected, key=lambda report: report.source_sha256))
    targets = {
        module: TargetCohortSummary(
            tuple(report.targets[module].upper_median_us for report in ordered)
        )
        for module in reference.targets
    }
    return CohortSummary(
        reference.environment,
        reference.sampling,
        runner,
        install,
        tuple(report.source_sha256 for report in ordered),
        targets,
    )
