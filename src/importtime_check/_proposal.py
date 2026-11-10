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

import hashlib
import re
from collections.abc import Mapping
from typing import Literal

from ._baseline import (
    Baseline,
    EnvironmentIdentity,
    TargetAllowance,
    TargetBaseline,
    encode_baseline,
)
from ._cohort import CohortSummary

_REVIEW_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


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


def _policy_changes(before: Baseline, after: Baseline) -> tuple[str, ...]:
    changes: list[str] = []
    for name in ("implementation", "python", "platform", "machine", "profile"):
        if getattr(before.environment, name) != getattr(after.environment, name):
            changes.append(f"environment.{name}")
    for name in ("warmups", "samples", "statistic"):
        if getattr(before.sampling, name) != getattr(after.sampling, name):
            changes.append(f"sampling.{name}")
    old_names = set(before.targets)
    new_names = set(after.targets)
    changes.extend(f"targets.removed.{name}" for name in sorted(old_names - new_names))
    changes.extend(f"targets.added.{name}" for name in sorted(new_names - old_names))
    for module in sorted(old_names & new_names):
        for name in (
            "baseline_cumulative_us",
            "max_increase_us",
            "max_increase_percent",
        ):
            if getattr(before.targets[module], name) != getattr(
                after.targets[module], name
            ):
                changes.append(f"targets.{module}.{name}")
    return tuple(changes)


def _review_label(value: str) -> str:
    return value if _REVIEW_LABEL.fullmatch(value) is not None else "[redacted]"


def explain_baseline_proposal(
    cohort: CohortSummary,
    candidate: Baseline,
    *,
    previous: Baseline | None = None,
) -> str:
    """Render deterministic, path-free evidence and optional policy field changes."""
    if not isinstance(cohort, CohortSummary) or not isinstance(candidate, Baseline):
        raise BaselineProposalError("review needs a cohort and candidate baseline")
    if previous is not None and not isinstance(previous, Baseline):
        raise BaselineProposalError("previous policy must be a baseline")
    identity = candidate.environment
    reported = cohort.environment
    if (
        (
            identity.implementation,
            identity.python,
            identity.platform,
            identity.machine,
        )
        != (
            reported.implementation,
            reported.python,
            reported.platform,
            reported.machine,
        )
        or candidate.sampling != cohort.sampling
        or set(candidate.targets) != set(cohort.targets)
        or any(
            candidate.targets[module].baseline_cumulative_us
            != cohort.targets[module].observed_median_us
            for module in cohort.targets
        )
    ):
        raise BaselineProposalError("candidate does not match cohort evidence")
    digest = hashlib.sha256(encode_baseline(candidate)).hexdigest()
    lines = [
        "Unapproved baseline candidate; review evidence and budgets before CI use.",
        f"Candidate SHA-256: {digest}",
        f"Source reports: {cohort.report_count}",
        "Source SHA-256 digests:",
        *(f"  {source}" for source in cohort.sources_sha256),
        f"Runner context: {cohort.runner_context}",
        f"Install context: {cohort.install_context}",
        "Environment: "
        f"{_review_label(identity.implementation)} "
        f"{_review_label(identity.python)}, "
        f"{_review_label(identity.platform)}/{_review_label(identity.machine)}; "
        f"profile {_review_label(identity.profile)}",
        f"Sampling: {cohort.sampling.warmups} warmup(s), "
        f"{cohort.sampling.samples} sample(s), {cohort.sampling.statistic}",
    ]
    for module, observed in cohort.targets.items():
        target = candidate.targets[module]
        lines.append(
            f"{module}: run medians {', '.join(map(str, observed.run_medians_us))} us; "
            f"range {observed.min_us}..{observed.max_us} us; "
            f"spread {observed.spread_us} us; "
            f"candidate median {target.baseline_cumulative_us} us; "
            f"allowances {target.max_increase_us} us or "
            f"{target.max_increase_percent}%"
        )
    if previous is not None:
        changes = _policy_changes(previous, candidate)
        lines.append("Changed policy fields:")
        lines.extend(f"  {field}" for field in changes)
        if not changes:
            lines.append("  none")
    lines.append(
        "Review runner definition, Python patch, dependency lock, installed "
        "revision, and each budget rationale; source hashes do not prove origin."
    )
    return "\n".join(lines) + "\n"
