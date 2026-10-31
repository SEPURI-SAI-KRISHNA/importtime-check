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

"""Construct unapproved schema-1 candidate values from report cohorts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from ._baseline import Baseline, EnvironmentIdentity, TargetAllowance, TargetBaseline
from ._cohort import CohortSummary


class BaselineProposalError(ValueError):
    """Proposal inputs do not define one complete candidate baseline."""

    __slots__ = ("kind", "missing", "reason", "unknown")

    def __init__(
        self,
        reason: str,
        *,
        missing: tuple[str, ...] = (),
        unknown: tuple[str, ...] = (),
    ) -> None:
        self.kind: Literal["proposal-invalid"] = "proposal-invalid"
        self.reason = reason
        self.missing = tuple(sorted(missing))
        self.unknown = tuple(sorted(unknown))
        super().__init__(reason)


def propose_baseline(
    cohort: CohortSummary,
    *,
    profile: str,
    per_target_allowances: Mapping[str, TargetAllowance],
) -> Baseline:
    """Build an immutable candidate; choosing, saving, and approving are separate."""
    if not isinstance(cohort, CohortSummary):
        raise BaselineProposalError("cohort must be a validated CohortSummary")
    try:
        environment = EnvironmentIdentity(
            cohort.environment.implementation,
            cohort.environment.python,
            cohort.environment.platform,
            cohort.environment.machine,
            profile,
        )
    except ValueError as error:
        raise BaselineProposalError("profile or cohort identity is invalid") from error
    if not isinstance(per_target_allowances, Mapping):
        raise BaselineProposalError("allowances must be a mapping")
    if any(not isinstance(name, str) for name in per_target_allowances):
        raise BaselineProposalError("allowance names must be target names")
    expected = set(cohort.targets)
    supplied = set(per_target_allowances)
    missing = tuple(sorted(expected - supplied))
    unknown = tuple(sorted(supplied - expected))
    if missing or unknown:
        raise BaselineProposalError(
            "allowances must match the cohort targets exactly",
            missing=missing,
            unknown=unknown,
        )
    targets: dict[str, TargetBaseline] = {}
    for module, summary in cohort.targets.items():
        allowance = per_target_allowances[module]
        if not isinstance(allowance, TargetAllowance):
            raise BaselineProposalError(
                "allowances must contain TargetAllowance values"
            )
        try:
            targets[module] = TargetBaseline(
                summary.observed_median_us,
                allowance.max_increase_us,
                allowance.max_increase_percent,
            )
        except ValueError as error:
            raise BaselineProposalError("a target allowance is invalid") from error
    return Baseline(environment, cohort.sampling, targets)
